#!/usr/bin/env python3
"""Smoke harness for the LLM-cluster-assignment path —
TASK-CLUSTER-LLM-ASSIGNMENT Phase 1.

Runs the new ``AssignClustersStage → cluster_to_finding_assignments``
pair against the three eval-anchor state files (2026-05-08,
2026-05-11-v1-baseline, 2026-05-13), three runs per day, to
characterise the stochastic profile of temperature 1.0.

## Methodology — fixed-topic input

The smoke uses the **fixed `_topics.json` from `audit-2026-05-16`** as
the topic-set input to `AssignClustersStage`, instead of running
`CuratorTopicDiscoveryStage` fresh. Reason: the Phase-2 audit
cross-references the smoke output against the 2,542 audit labels,
which are keyed on those exact audit topics. Using the audit topics
guarantees direct 1:1 comparability against Brief 5b's pinned
configuration (8.23 % aggregate weighted off-topic, same topics, same
findings, only the assignment algorithm differs). This mirrors Brief
5b's reaudit methodology — labels copy forward verbatim.

Pre-cluster output is deterministic; reused from
`docs/cluster-internal-audit/audit-2026-05-17/_cache/` when present.

## Per-day plan

1. Load `curator_findings` from the state file.
2. Load cached pre-cluster output (or compute fresh if cache missing).
3. Load the audit's `_topics.json` as the topic-set input.
4. Run `AssignClustersStage` + `cluster_to_finding_assignments`
   **three times** per day. The discovered-topics slot is held
   constant; only the LLM's stochastic assignment varies.

## Per-run capture

- `assignments_llm.json`   — raw `curator_cluster_assignments_llm`
- `topic_assignments.json` — translated `curator_topic_assignments`
- `run_meta.json`          — wall, cost, tokens, counts

## Per-day capture

- `_topics.json`           — the audit's topic-set (verbatim copy)
- `_pre_clusters.json`     — the cached pre-cluster record
- `summary.md`             — per-run + per-date table with spread,
                              topic-level Jaccard stability table

## Cross-day capture (smoke root)

- `summary.md`             — per-run rows × 9, per-date aggregates with
                              spread, total cost, schema-failure log
- `summary.json`           — machine-readable

## Cost budget

9 `AssignClustersStage` calls × ~$0.05 each ≈ $0.45. No topic-discovery
calls (audit topics are loaded from disk).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agent_stages import AssignClustersStage  # noqa: E402
from src.bus import RunBus  # noqa: E402
from src.stages.cluster_to_finding_assignments import (  # noqa: E402
    cluster_to_finding_assignments,
)
from src.stages.pre_cluster import pre_cluster_findings  # noqa: E402

# scripts/run.py builds the agents (incl. assign_clusters).
from scripts.run import create_agents  # noqa: E402


DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}


PRE_CLUSTER_CACHE_ROOT = (
    REPO_ROOT / "docs" / "cluster-internal-audit" / "audit-2026-05-17" / "_cache"
)

AUDIT_DATA_ROOT = (
    REPO_ROOT / "docs" / "cluster-quality-audit" / "audit-2026-05-16" / "_data"
)

OUT_ROOT = REPO_ROOT / "docs" / "cluster-llm-assignment-2026-05-17" / "smoke"

RUNS_PER_DATE: int = 3


def _load_findings(state_path: Path) -> list[dict]:
    with state_path.open() as f:
        data = json.load(f)
    return list(data.get("curator_findings") or [])


def _load_audit_topics(date: str) -> list[dict]:
    """Load the audit's `_topics.json` for one date. This is the
    fixed topic-set the smoke uses as the AssignClustersStage input."""
    topics_path = AUDIT_DATA_ROOT / date / "_topics.json"
    with topics_path.open() as f:
        return json.load(f)


def _load_or_compute_pre_clusters(
    date: str,
    findings: list[dict],
) -> dict:
    cache_path = PRE_CLUSTER_CACHE_ROOT / f"{date}.preclusters.json"
    if cache_path.exists():
        with cache_path.open() as f:
            return json.load(f)
    print(f"  [{date}] pre-cluster cache miss — running pre_cluster_findings (~15-30s)")
    t0 = time.monotonic()
    rb = RunBus(
        run_id=f"smoke-{date}-precluster",
        run_date=date,
        curator_findings=findings,
    )
    rb = asyncio.run(pre_cluster_findings(rb))
    print(f"  [{date}] pre_cluster: {rb.curator_pre_clusters.get('n_clusters', 0)} "
          f"clusters in {time.monotonic() - t0:.1f}s")
    return rb.curator_pre_clusters


async def _run_one_assign(
    date: str,
    run_idx: int,
    findings: list[dict],
    pre_clusters_record: dict,
    discovered_topics_record: dict,
    assign_agent,
) -> dict:
    """One AssignClustersStage + cluster_to_finding_assignments pass."""
    rb = RunBus(
        run_id=f"smoke-{date}-assign-{run_idx}",
        run_date=date,
        curator_findings=findings,
        curator_pre_clusters=pre_clusters_record,
        curator_discovered_topics=discovered_topics_record,
    )

    schema_failure: dict | None = None
    t0 = time.monotonic()
    try:
        rb = await AssignClustersStage(assign_agent)(rb)
    except Exception as exc:  # pragma: no cover — defensive; surface up
        schema_failure = {
            "phase": "assign_clusters_stage",
            "exception_type": type(exc).__name__,
            "message": str(exc)[:500],
        }
        print(f"  [{date} run-{run_idx}] !! AssignClustersStage failed: "
              f"{type(exc).__name__}: {exc}")
        return {
            "date": date,
            "run": run_idx,
            "schema_failure": schema_failure,
            "wall_seconds": time.monotonic() - t0,
            "assignments_llm": None,
            "topic_assignments": None,
        }

    rb = await cluster_to_finding_assignments(rb)
    wall = time.monotonic() - t0

    return {
        "date": date,
        "run": run_idx,
        "schema_failure": None,
        "wall_seconds": round(wall, 3),
        "assignments_llm": rb.curator_cluster_assignments_llm,
        "topic_assignments": rb.curator_topic_assignments,
    }


def _per_day_run_stats(run: dict) -> dict:
    """Distil one run into the per-run table row."""
    llm = run.get("assignments_llm") or {}
    ta = run.get("topic_assignments") or {}
    n_multi = sum(
        1 for a in (llm.get("assignments") or []) if len(a.get("topic_indices", [])) >= 2
    )
    return {
        "date": run["date"],
        "run": run["run"],
        "wall_seconds": run["wall_seconds"],
        "cost_usd": (llm.get("llm_cost_usd") or 0.0),
        "tokens_used": (llm.get("llm_input_tokens") or 0),
        "n_clusters_input": llm.get("n_clusters_input", 0),
        "n_clusters_assigned": llm.get("n_clusters_assigned", 0),
        "n_clusters_orphan": llm.get("n_clusters_orphan", 0),
        "n_multi_assignments": n_multi,
        "n_findings_assigned": ta.get("n_findings_assigned", 0),
        "n_orphans": ta.get("n_orphans", 0),
        "schema_failure": run.get("schema_failure"),
    }


def _spread(values: list[float | int]) -> dict:
    if not values:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "n": 0}
    return {
        "mean": round(statistics.mean(values), 3),
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


def _per_topic_cluster_sets(run: dict) -> dict[int, set[str]]:
    """For one run: {topic_index → set(cluster_ids assigned to that topic)}."""
    out: dict[int, set[str]] = {}
    llm = run.get("assignments_llm") or {}
    for entry in (llm.get("assignments") or []):
        for ti in (entry.get("topic_indices") or []):
            out.setdefault(int(ti), set()).add(entry.get("cluster_id", ""))
    return out


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _topic_stability_table(runs: list[dict], n_topics: int) -> list[dict]:
    """For each topic: jaccard across the three pairwise comparisons of
    the assigned cluster set. Returns one row per topic with the mean
    + min jaccard across the (n_runs choose 2) pairs."""
    per_run_sets = [_per_topic_cluster_sets(r) for r in runs]
    rows: list[dict] = []
    for ti in range(n_topics):
        sets = [s.get(ti, set()) for s in per_run_sets]
        pairs = [_jaccard(a, b) for a, b in combinations(sets, 2)]
        sizes = [len(s) for s in sets]
        rows.append({
            "topic_index": ti,
            "per_run_cluster_counts": sizes,
            "jaccard_mean": round(statistics.mean(pairs), 4) if pairs else 1.0,
            "jaccard_min": round(min(pairs), 4) if pairs else 1.0,
        })
    return rows


def _render_per_day_summary(
    date: str,
    discovered_topics: list[dict],
    per_day_runs: list[dict],
    out_dir: Path,
) -> None:
    """Per-day summary.md including topic-stability table."""
    rows = [_per_day_run_stats(r) for r in per_day_runs]
    stability = _topic_stability_table(per_day_runs, len(discovered_topics))

    lines: list[str] = []
    lines.append(f"# Cluster-LLM-assignment smoke — {date}")
    lines.append("")
    lines.append(f"Three runs of `AssignClustersStage` at temperature 1.0 against the "
                 f"fixed `audit-2026-05-16` topic-set ({len(discovered_topics)} topics) "
                 f"and the cached `curator_pre_clusters` "
                 f"({rows[0]['n_clusters_input']} clusters).")
    lines.append("")
    lines.append("## Per-run table")
    lines.append("")
    lines.append("| Run | Wall (s) | Cost (USD) | Tokens | Clusters in | Assigned | Orphan | Multi-asg | Findings assigned | Orphan findings |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        if r["schema_failure"]:
            lines.append(
                f"| {r['run']} | — | — | — | — | — | — | — | — | — "
                f"(SCHEMA FAIL: {r['schema_failure']['exception_type']}) |"
            )
            continue
        lines.append(
            f"| {r['run']} | {r['wall_seconds']:.1f} | "
            f"${r['cost_usd']:.4f} | {r['tokens_used']:,} | "
            f"{r['n_clusters_input']} | {r['n_clusters_assigned']} | "
            f"{r['n_clusters_orphan']} | {r['n_multi_assignments']} | "
            f"{r['n_findings_assigned']} | {r['n_orphans']} |"
        )
    lines.append("")

    # Per-day spread
    lines.append("## Per-day spread across 3 runs")
    lines.append("")
    lines.append("| Metric | Mean | Min | Max | Spread (max - min) |")
    lines.append("|---|---:|---:|---:|---:|")
    for label, key in (
        ("Wall (s)", "wall_seconds"),
        ("Cost (USD)", "cost_usd"),
        ("Clusters assigned", "n_clusters_assigned"),
        ("Clusters orphan", "n_clusters_orphan"),
        ("Multi-assignments", "n_multi_assignments"),
        ("Findings assigned", "n_findings_assigned"),
        ("Orphan findings", "n_orphans"),
    ):
        values = [r[key] for r in rows if r["schema_failure"] is None]
        sp = _spread(values)
        spread = (sp["max"] - sp["min"]) if values else 0
        lines.append(
            f"| {label} | {sp['mean']} | {sp['min']} | {sp['max']} | {spread} |"
        )
    lines.append("")

    # Topic-level Jaccard stability
    lines.append("## Topic-level cluster-set stability (Jaccard across runs)")
    lines.append("")
    lines.append("For each topic, the assigned cluster set per run is compared "
                 "pairwise; mean and min Jaccard across the 3 pairs are reported. "
                 "1.0 = identical cluster set across all 3 runs.")
    lines.append("")
    lines.append("| # | Topic title (truncated) | Per-run cluster counts | Jaccard mean | Jaccard min |")
    lines.append("|---:|---|---|---:|---:|")
    for row in stability:
        ti = row["topic_index"]
        title = (discovered_topics[ti].get("title") or "")[:60] if ti < len(discovered_topics) else ""
        counts = "/".join(str(c) for c in row["per_run_cluster_counts"])
        lines.append(
            f"| {ti} | {title} | {counts} | {row['jaccard_mean']:.3f} | {row['jaccard_min']:.3f} |"
        )
    lines.append("")

    # Cross-run aggregate jaccard
    mean_jaccards = [row["jaccard_mean"] for row in stability]
    min_jaccards = [row["jaccard_min"] for row in stability]
    if mean_jaccards:
        lines.append("**Day aggregates:** mean-across-topics of "
                     f"`jaccard_mean` = **{statistics.mean(mean_jaccards):.3f}**; "
                     f"mean-across-topics of `jaccard_min` = "
                     f"**{statistics.mean(min_jaccards):.3f}**.")
        lines.append("")

    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _render_cross_day_summary(
    per_day: dict[str, dict],
    total_cost_usd: float,
    schema_failures: list[dict],
    pre_cluster_counts: dict[str, int],
) -> None:
    """Smoke-root summary.md."""
    lines: list[str] = []
    lines.append("# Cluster-LLM-assignment smoke — cross-day summary")
    lines.append("")
    lines.append("Three runs per day × three eval datasets = **nine "
                 "`AssignClustersStage` LLM calls**, all at temperature 1.0.")
    lines.append("")
    lines.append("## Methodology — fixed-topic input")
    lines.append("")
    lines.append("The topic-set input to `AssignClustersStage` is the fixed "
                 "`_topics.json` from `docs/cluster-quality-audit/audit-2026-05-16/` "
                 "(the same topics Brief 5b's pinned configuration was audited "
                 "against). No `CuratorTopicDiscoveryStage` call is made — the "
                 "topics come from disk. This guarantees that the Phase-2 "
                 "audit cross-references against the 2,542 labels are directly "
                 "comparable to Brief 5b's 8.23 % aggregate weighted off-topic "
                 "baseline: same topics, same findings, only the assignment "
                 "algorithm differs.")
    lines.append("")
    lines.append("Pre-cluster output is deterministic and reused from "
                 "`docs/cluster-internal-audit/audit-2026-05-17/_cache/` "
                 "when present.")
    lines.append("")
    lines.append("## Cost")
    lines.append("")
    lines.append(f"- **Total LLM cost: ${total_cost_usd:.4f}**")
    lines.append("")

    # Per-run × per-day table
    lines.append("## Per-run table (9 rows = 3 dates × 3 runs)")
    lines.append("")
    lines.append("| Date | Run | Wall (s) | Cost (USD) | Tokens | Clusters in | Assigned | Orphan | Multi-asg | Findings assigned | Orphan findings |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for date, day in per_day.items():
        for r in day["per_run"]:
            if r["schema_failure"]:
                lines.append(
                    f"| {date} | {r['run']} | — | — | — | — | — | — | — | — | — "
                    f"(SCHEMA FAIL) |"
                )
                continue
            lines.append(
                f"| {date} | {r['run']} | {r['wall_seconds']:.1f} | "
                f"${r['cost_usd']:.4f} | {r['tokens_used']:,} | "
                f"{r['n_clusters_input']} | {r['n_clusters_assigned']} | "
                f"{r['n_clusters_orphan']} | {r['n_multi_assignments']} | "
                f"{r['n_findings_assigned']} | {r['n_orphans']} |"
            )
    lines.append("")

    # Per-day spread aggregates
    lines.append("## Per-day spread (mean ± min ± max across 3 runs)")
    lines.append("")
    lines.append("Spread is the load-bearing signal for production viability "
                 "at temperature 1.0 — large spread = the LLM makes materially "
                 "different judgements run-to-run.")
    lines.append("")
    lines.append("| Date | Pre-clusters | n_topics | Clusters assigned (mean / min / max) | Orphan clusters (mean / min / max) | Findings assigned (mean / min / max) | Topic-Jaccard mean / min |")
    lines.append("|---|---:|---:|---|---|---|---|")
    for date, day in per_day.items():
        rows = [r for r in day["per_run"] if r["schema_failure"] is None]
        ca = _spread([r["n_clusters_assigned"] for r in rows])
        co = _spread([r["n_clusters_orphan"] for r in rows])
        fa = _spread([r["n_findings_assigned"] for r in rows])
        stab = day.get("stability_aggregate") or {}
        lines.append(
            f"| {date} | {pre_cluster_counts.get(date, 0)} | {day['n_topics']} | "
            f"{ca['mean']} / {ca['min']} / {ca['max']} | "
            f"{co['mean']} / {co['min']} / {co['max']} | "
            f"{fa['mean']} / {fa['min']} / {fa['max']} | "
            f"{stab.get('mean_of_means', 0.0):.3f} / "
            f"{stab.get('mean_of_mins', 0.0):.3f} |"
        )
    lines.append("")

    # Cross-date aggregate
    all_rows = [
        r for day in per_day.values() for r in day["per_run"]
        if r["schema_failure"] is None
    ]
    if all_rows:
        lines.append("## Cross-date aggregate (9-run pool)")
        lines.append("")
        lines.append("| Metric | Mean | Min | Max |")
        lines.append("|---|---:|---:|---:|")
        for label, key in (
            ("Wall (s)", "wall_seconds"),
            ("Cost per call (USD)", "cost_usd"),
            ("Clusters assigned", "n_clusters_assigned"),
            ("Clusters orphan", "n_clusters_orphan"),
            ("Multi-assignments per run", "n_multi_assignments"),
            ("Findings assigned", "n_findings_assigned"),
            ("Orphan findings", "n_orphans"),
        ):
            values = [r[key] for r in all_rows]
            sp = _spread(values)
            lines.append(
                f"| {label} | {sp['mean']} | {sp['min']} | {sp['max']} |"
            )
        lines.append("")

    # Schema failures
    lines.append("## Schema-failure log")
    lines.append("")
    if schema_failures:
        lines.append("**Schema-failure rate is itself a production-viability "
                     "signal** — surfaced verbatim per the brief.")
        lines.append("")
        for f in schema_failures:
            lines.append(
                f"- `{f['date']}` run-{f['run']}: "
                f"{f['schema_failure']['exception_type']} — "
                f"{f['schema_failure']['message']}"
            )
    else:
        lines.append("No schema-validation failures across the 9 LLM calls — every "
                     "response parsed cleanly under strict mode.")
    lines.append("")

    lines.append("## Per-day reports")
    lines.append("")
    for date in per_day:
        lines.append(f"- [`{date}/summary.md`]({date}/summary.md)")
    lines.append("")

    (OUT_ROOT / "summary.md").write_text("\n".join(lines), encoding="utf-8")


async def smoke_one_day(
    date: str,
    state_path: Path,
    assign_agent,
) -> dict:
    if not state_path.exists():
        print(f"  [{date}] state file missing → skipping")
        return {"date": date, "error": "state-missing"}

    print(f"\n== {date} ==")
    findings = _load_findings(state_path)
    pre_clusters_record = _load_or_compute_pre_clusters(date, findings)
    n_clusters = pre_clusters_record.get("n_clusters") or len(
        pre_clusters_record.get("clusters", [])
    )
    topics = _load_audit_topics(date)
    n_topics = len(topics)
    print(f"  [{date}] findings={len(findings)}, pre-clusters={n_clusters}, "
          f"audit-topics={n_topics}")

    out_dir = OUT_ROOT / date
    out_dir.mkdir(parents=True, exist_ok=True)

    # Discovered-topics record mimics the shape CuratorTopicDiscoveryStage
    # writes — n_topics + topics; downstream stages read the topics list.
    discovered_record = {
        "agent_name": "audit-2026-05-16-fixed",
        "model_name": "fixed-from-disk",
        "params": {"temperature": None, "max_tokens": None, "reasoning": None},
        "sample_titles_per_cluster": None,
        "wall_seconds": 0.0,
        "llm_cost_usd": 0.0,
        "tokens_used": 0,
        "n_micro_clusters_input": n_clusters,
        "n_topics": n_topics,
        "topics": topics,
    }

    (out_dir / "_topics.json").write_text(
        json.dumps(topics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "_pre_clusters.json").write_text(
        json.dumps(pre_clusters_record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Three runs
    per_day_runs: list[dict] = []
    for run_idx in range(1, RUNS_PER_DATE + 1):
        print(f"  [{date} run-{run_idx}/{RUNS_PER_DATE}] AssignClustersStage ...")
        run = await _run_one_assign(
            date, run_idx, findings, pre_clusters_record,
            discovered_record, assign_agent,
        )
        per_day_runs.append(run)
        # Per-run capture
        run_dir = out_dir / f"run-{run_idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        if run["assignments_llm"] is not None:
            (run_dir / "assignments_llm.json").write_text(
                json.dumps(run["assignments_llm"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        if run["topic_assignments"] is not None:
            (run_dir / "topic_assignments.json").write_text(
                json.dumps(run["topic_assignments"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        meta = _per_day_run_stats(run)
        (run_dir / "run_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if meta["schema_failure"]:
            print(f"  [{date} run-{run_idx}] SCHEMA FAIL — {meta['schema_failure']}")
        else:
            print(f"  [{date} run-{run_idx}] {meta['n_clusters_assigned']} assigned, "
                  f"{meta['n_clusters_orphan']} orphan, "
                  f"{meta['n_multi_assignments']} multi, "
                  f"${meta['cost_usd']:.4f}, {meta['wall_seconds']:.1f}s")

    # Stability aggregate
    stability_rows = _topic_stability_table(per_day_runs, n_topics)
    stab_means = [r["jaccard_mean"] for r in stability_rows]
    stab_mins = [r["jaccard_min"] for r in stability_rows]
    stability_aggregate = {
        "mean_of_means": (
            statistics.mean(stab_means) if stab_means else 1.0
        ),
        "mean_of_mins": (
            statistics.mean(stab_mins) if stab_mins else 1.0
        ),
        "n_topics": n_topics,
    }

    _render_per_day_summary(date, topics, per_day_runs, out_dir)

    return {
        "date": date,
        "n_findings": len(findings),
        "n_pre_clusters": n_clusters,
        "n_topics": n_topics,
        "per_run": [_per_day_run_stats(r) for r in per_day_runs],
        "stability_aggregate": stability_aggregate,
    }


async def amain(args) -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    datasets = (
        list(DATASETS.items())
        if args.dataset == "all"
        else [(args.dataset, DATASETS[args.dataset])]
    )

    agents = create_agents()
    assign_agent = agents.get("assign_clusters")
    if assign_agent is None:
        print("!! assign_clusters agent not registered in scripts/run.py")
        return 1

    print(f"== Cluster-LLM-assignment smoke ==")
    print(f"  assign agent: {assign_agent.name} model={assign_agent.model} "
          f"temp={assign_agent.temperature} max_tokens={assign_agent.max_tokens}")
    print(f"  datasets: {[d for d, _ in datasets]}")
    print(f"  runs per dataset: {RUNS_PER_DATE}")
    print(f"  topic-set input: docs/cluster-quality-audit/audit-2026-05-16/_data/{{date}}/_topics.json")
    print(f"  output: {OUT_ROOT.relative_to(REPO_ROOT)}/")

    per_day: dict[str, dict] = {}
    pre_cluster_counts: dict[str, int] = {}
    total_cost = 0.0
    schema_failures: list[dict] = []
    t0 = time.monotonic()

    for date, state in datasets:
        day = await smoke_one_day(date, state, assign_agent)
        if "error" in day:
            continue
        per_day[date] = day
        pre_cluster_counts[date] = day["n_pre_clusters"]
        for r in day["per_run"]:
            total_cost += r.get("cost_usd", 0.0) or 0.0
            if r["schema_failure"]:
                schema_failures.append(r)

    # Cross-day summary
    _render_cross_day_summary(
        per_day, total_cost, schema_failures, pre_cluster_counts
    )

    # Machine-readable summary
    summary_json = {
        "task": "TASK-CLUSTER-LLM-ASSIGNMENT — Phase 1 smoke",
        "methodology": "fixed audit-2026-05-16 topic-set input",
        "assign_agent": {
            "name": assign_agent.name,
            "model": assign_agent.model,
            "temperature": assign_agent.temperature,
            "reasoning": assign_agent.reasoning,
            "max_tokens": assign_agent.max_tokens,
        },
        "runs_per_dataset": RUNS_PER_DATE,
        "total_cost_usd": round(total_cost, 4),
        "schema_failure_count": len(schema_failures),
        "schema_failures": schema_failures,
        "per_day": {
            date: {
                "n_findings": day["n_findings"],
                "n_pre_clusters": day["n_pre_clusters"],
                "n_topics": day["n_topics"],
                "stability_aggregate": day["stability_aggregate"],
                "per_run": day["per_run"],
            }
            for date, day in per_day.items()
        },
    }
    (OUT_ROOT / "summary.json").write_text(
        json.dumps(summary_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    wall = time.monotonic() - t0
    print(f"\n== Done ==")
    print(f"  Total LLM cost: ${total_cost:.4f}")
    print(f"  Schema failures: {len(schema_failures)}")
    print(f"  Wall: {wall:.1f}s")
    print(f"  Wrote {(OUT_ROOT / 'summary.md').relative_to(REPO_ROOT)}")
    print(f"  Wrote {(OUT_ROOT / 'summary.json').relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dataset",
        choices=list(DATASETS.keys()) + ["all"],
        default="all",
    )
    args = ap.parse_args()
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())
