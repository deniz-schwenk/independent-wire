#!/usr/bin/env python3
"""Audit the LLM-cluster-assignment smoke against the 2,542-label
ground truth from `docs/cluster-quality-audit/audit-2026-05-16/` —
TASK-CLUSTER-LLM-ASSIGNMENT Phase 2.

For each of the 9 smoke runs (3 dates × 3 runs), cross-reference the
``curator_topic_assignments`` slot against the audit labels and
surface a side-by-side comparison with Brief 5b's pinned configuration
(8.23 % aggregate weighted off-topic).

## Methodology

The smoke used the audit's fixed `_topics.json` as the topic-set
input, so topic indices in the smoke output are aligned 1:1 with the
audit's `_topics.json` ordering. For each audited topic bundle
(`topic-NN.json` for NN in 00..09 per day):

1. Match the bundle to its topic_index in `_topics.json` by source_ids
   set equality (same logic Brief 5b's reaudit uses).
2. For each finding assigned to that topic in the smoke run, look up
   the audit label in `topic-NN.audit.csv`.
3. Findings not in the audit labels (i.e. new assignments that fall
   outside the V1 top-10 audit space) are excluded from the aggregate
   per the brief's "audit covers only the V1 top-10 audit space"
   constraint — same as Brief 5b had.

## Per-run audit numbers

- date, run, weighted off-topic %, simple-mean off-topic %,
  n_findings_in_audit_scope, n_off_topic, per-topic precision / recall,
  per-topic off-topic distribution.

## Per-date aggregates

- Mean ± spread (min, max) of the off-topic rate across the 3 runs.

## Cross-date aggregate

- 9-run pool: overall weighted off-topic + spread.

## Comparison vs Brief 5b

- Side-by-side: 8.23 % baseline vs LLM 9-run mean + spread.

## Per-topic detail

- For each of the 30 audited topics, precision / recall / off% across
  all 9 runs + the baseline column.

## Gravity-trap case studies

- Putin/Schröder (2026-05-11 topic-02)
- Yermak (2026-05-13 topic-03)
- Sport-Wochenende cluster mc-04 (2026-05-11): the cluster's per-run
  assignment fate (which topic — if any — it lands on, run-by-run).
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


AUDIT_DATA_ROOT = (
    REPO_ROOT / "docs" / "cluster-quality-audit" / "audit-2026-05-16" / "_data"
)
AUDIT_RECALIBRATED_SUMMARY = (
    REPO_ROOT / "docs" / "cluster-quality-audit"
    / "audit-2026-05-16-recalibrated" / "summary.json"
)

SMOKE_ROOT = REPO_ROOT / "docs" / "cluster-llm-assignment-2026-05-17" / "smoke"
OUT_ROOT = REPO_ROOT / "docs" / "cluster-llm-assignment-2026-05-17" / "audit"

DATES = ("2026-05-08", "2026-05-11", "2026-05-13")
RUNS_PER_DATE = 3
TOP_K_TOPICS = 10  # the audit covers top-10 per day

# Gravity-trap case studies — date → bundle_idx → description
GRAVITY_TRAPS: list[dict] = [
    {
        "date": "2026-05-11",
        "bundle_idx": 2,
        "label": "Putin/Schröder",
        "description": (
            "Brief 5b's pinned configuration drops topic-02 from 27.5 % "
            "off (baseline T=0.30) to 21.4 % off at T=0.55 — a hard "
            "case where gravitational drift pulls Pistorius / EU funding "
            "into the Schröder Victory-Day topic."
        ),
    },
    {
        "date": "2026-05-13",
        "bundle_idx": 3,
        "label": "Yermak/Russia-Ukraine",
        "description": (
            "Topic-03 carries cross-topic drift between Yermak's resignation "
            "and the broader Russia-Ukraine war coverage."
        ),
    },
    {
        "date": "2026-05-11",
        "bundle_idx": 4,
        "label": "Sport-Wochenende",
        "description": (
            "The Sport-Wochenende cluster mc-04 was the architectural "
            "pivot in the cluster-level gravitation brief — under "
            "deterministic cluster-level T=0.55, it landed wholesale on "
            "topic-09 (Barcelona LaLiga), causing 50 % drift on a "
            "previously-clean topic. The LLM's per-run fate of mc-04 is "
            "the architectural canary case."
        ),
    },
]

# Specifically watch the Sport-Wochenende cluster ID
SPORT_CLUSTER_ID = "mc-04"
SPORT_DATE = "2026-05-11"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _audited_bundle_indices(date: str) -> list[int]:
    return sorted(
        int(p.stem.split("topic-")[-1])
        for p in (AUDIT_DATA_ROOT / date).glob("topic-*.json")
    )


def _load_audit_bundle(date: str, bi: int) -> dict:
    return json.loads(
        (AUDIT_DATA_ROOT / date / f"topic-{bi:02d}.json").read_text(encoding="utf-8")
    )


def _load_audit_csv(date: str, bi: int) -> dict[str, int]:
    """{finding_id: is_on_topic (0/1)} for labelled rows only."""
    out: dict[str, int] = {}
    path = AUDIT_DATA_ROOT / date / f"topic-{bi:02d}.audit.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        for row in r:
            label = (row.get("is_on_topic") or "").strip()
            if label not in ("0", "1"):
                continue
            out[row["finding_id"].strip()] = int(label)
    return out


def _load_smoke_topics(date: str) -> list[dict]:
    return json.loads(
        (SMOKE_ROOT / date / "_topics.json").read_text(encoding="utf-8")
    )


def _load_smoke_pre_clusters(date: str) -> dict:
    return json.loads(
        (SMOKE_ROOT / date / "_pre_clusters.json").read_text(encoding="utf-8")
    )


def _load_smoke_run_topic_assignments(date: str, run: int) -> dict:
    return json.loads(
        (SMOKE_ROOT / date / f"run-{run}" / "topic_assignments.json").read_text(
            encoding="utf-8"
        )
    )


def _load_smoke_run_assignments_llm(date: str, run: int) -> dict:
    return json.loads(
        (SMOKE_ROOT / date / f"run-{run}" / "assignments_llm.json").read_text(
            encoding="utf-8"
        )
    )


def _load_baseline_summary() -> dict:
    return json.loads(AUDIT_RECALIBRATED_SUMMARY.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Topic-index mapping bundle_idx → smoke topic_index
# ---------------------------------------------------------------------------


def _map_bundle_to_topic_idx(date: str, bundle_indices: list[int]) -> dict[int, int]:
    """Match each audited bundle to its topic_index in the smoke's
    fixed `_topics.json`. The smoke uses the audit's `_topics.json`
    verbatim, so the source_ids set equality match from Brief 5b's
    reaudit applies identically here.
    """
    topics = _load_smoke_topics(date)
    out: dict[int, int] = {}
    for bi in bundle_indices:
        bundle = _load_audit_bundle(date, bi)
        bundle_sids = {f["source_id"] for f in bundle.get("findings", [])}
        matched: int | None = None
        for ti, t in enumerate(topics):
            if set(t.get("source_ids") or []) == bundle_sids:
                matched = ti
                break
        if matched is None:
            # Title fallback
            bundle_title = (bundle.get("topic_title") or "").strip()
            for ti, t in enumerate(topics):
                if (t.get("title") or "").strip() == bundle_title:
                    matched = ti
                    break
        if matched is None:
            raise ValueError(
                f"could not match {date}/topic-{bi:02d} "
                f"({bundle.get('topic_title','')[:80]!r}) to any topic in _topics.json"
            )
        out[bi] = matched
    return out


# ---------------------------------------------------------------------------
# Per-run audit
# ---------------------------------------------------------------------------


def _audit_one_run(
    date: str,
    run: int,
    bundle_to_topic_idx: dict[int, int],
    per_bundle_labels: dict[int, dict[str, int]],
) -> dict:
    """Audit one smoke run against the audit labels."""
    topic_assignments = _load_smoke_run_topic_assignments(date, run)
    topics_out = topic_assignments.get("topics") or []
    topic_idx_to_bucket: dict[int, list[str]] = {}
    for t in topics_out:
        ti = t.get("topic_index")
        if ti is None:
            continue
        topic_idx_to_bucket[int(ti)] = [
            a.get("source_id")
            for a in (t.get("assignments") or [])
            if a.get("source_id")
        ]

    per_topic_rows: list[dict] = []
    n_findings_audited_total = 0
    n_off_topic_total = 0
    per_topic_off_pcts: list[float] = []

    for bi, ti in sorted(bundle_to_topic_idx.items()):
        labels = per_bundle_labels[bi]  # finding_id → 0/1
        labelled_sid_set = set(labels)
        new_assigned = topic_idx_to_bucket.get(ti, [])
        # Intersect new assignments with labelled set (those outside
        # are excluded from the aggregate per the brief).
        intersect = [s for s in new_assigned if s in labelled_sid_set]
        on = sum(1 for s in intersect if labels[s] == 1)
        off = sum(1 for s in intersect if labels[s] == 0)
        n_lab = on + off
        n_unlabeled_new = sum(1 for s in new_assigned if s not in labelled_sid_set)
        off_pct = (100.0 * off / n_lab) if n_lab else 0.0

        # Precision = on / n_lab; recall = on / on_in_original_audit
        original_on = sum(1 for v in labels.values() if v == 1)
        original_off = sum(1 for v in labels.values() if v == 0)
        recall = (on / original_on) if original_on else 0.0
        precision = (on / n_lab) if n_lab else 0.0
        # Bundle title
        bundle = _load_audit_bundle(date, bi)
        per_topic_rows.append({
            "bundle_idx": bi,
            "topic_idx": ti,
            "topic_title": (bundle.get("topic_title") or "")[:120],
            "n_new_assigned": len(new_assigned),
            "n_labeled": n_lab,
            "n_unlabeled_new": n_unlabeled_new,
            "n_original_on": original_on,
            "n_original_off": original_off,
            "on_topic": on,
            "off_topic": off,
            "off_topic_pct": round(off_pct, 2),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        })
        n_findings_audited_total += n_lab
        n_off_topic_total += off
        if n_lab:
            per_topic_off_pcts.append(off_pct)

    weighted = (
        100.0 * n_off_topic_total / n_findings_audited_total
        if n_findings_audited_total
        else 0.0
    )
    simple = statistics.mean(per_topic_off_pcts) if per_topic_off_pcts else 0.0
    mean_precision = (
        statistics.mean(r["precision"] for r in per_topic_rows if r["n_labeled"])
        if any(r["n_labeled"] for r in per_topic_rows)
        else 0.0
    )
    mean_recall = (
        statistics.mean(r["recall"] for r in per_topic_rows if r["n_original_on"])
        if any(r["n_original_on"] for r in per_topic_rows)
        else 0.0
    )

    return {
        "date": date,
        "run": run,
        "n_findings_audited": n_findings_audited_total,
        "n_off_topic": n_off_topic_total,
        "weighted_off_topic_pct": round(weighted, 2),
        "simple_mean_off_topic_pct": round(simple, 2),
        "mean_per_topic_precision": round(mean_precision, 4),
        "mean_per_topic_recall": round(mean_recall, 4),
        "per_topic": per_topic_rows,
    }


# ---------------------------------------------------------------------------
# Per-bundle labels — cache across runs
# ---------------------------------------------------------------------------


def _all_per_bundle_labels(date: str, bundle_indices: list[int]) -> dict[int, dict[str, int]]:
    return {bi: _load_audit_csv(date, bi) for bi in bundle_indices}


# ---------------------------------------------------------------------------
# Day-level audit
# ---------------------------------------------------------------------------


def _audit_one_day(date: str) -> dict:
    bundle_indices = _audited_bundle_indices(date)[:TOP_K_TOPICS]
    print(f"\n== auditing {date} — top-{len(bundle_indices)} bundles ==")
    bundle_to_topic_idx = _map_bundle_to_topic_idx(date, bundle_indices)
    per_bundle_labels = _all_per_bundle_labels(date, bundle_indices)
    runs: list[dict] = []
    for r in range(1, RUNS_PER_DATE + 1):
        run = _audit_one_run(date, r, bundle_to_topic_idx, per_bundle_labels)
        runs.append(run)
        print(
            f"  [{date} run-{r}] weighted off-topic = "
            f"{run['weighted_off_topic_pct']:.2f}% "
            f"(simple-mean {run['simple_mean_off_topic_pct']:.2f}%, "
            f"audited={run['n_findings_audited']}, off={run['n_off_topic']})"
        )
    # Day aggregate with spread
    weighted_vals = [r["weighted_off_topic_pct"] for r in runs]
    simple_vals = [r["simple_mean_off_topic_pct"] for r in runs]
    return {
        "date": date,
        "bundle_indices": bundle_indices,
        "bundle_to_topic_idx": bundle_to_topic_idx,
        "runs": runs,
        "spread": {
            "weighted_off_topic_pct": {
                "mean": round(statistics.mean(weighted_vals), 3),
                "min": min(weighted_vals),
                "max": max(weighted_vals),
                "spread_pp": round(max(weighted_vals) - min(weighted_vals), 3),
            },
            "simple_mean_off_topic_pct": {
                "mean": round(statistics.mean(simple_vals), 3),
                "min": min(simple_vals),
                "max": max(simple_vals),
                "spread_pp": round(max(simple_vals) - min(simple_vals), 3),
            },
        },
    }


# ---------------------------------------------------------------------------
# Gravity-trap case studies
# ---------------------------------------------------------------------------


def _gravity_trap_case_studies(per_day: dict[str, dict]) -> list[dict]:
    """For each named gravity trap, surface the per-run off-topic rate
    + the assigned cluster set (so the architect can see which clusters
    drove the drift, if any)."""
    out: list[dict] = []
    for trap in GRAVITY_TRAPS:
        date = trap["date"]
        bi = trap["bundle_idx"]
        if date not in per_day:
            continue
        day = per_day[date]
        ti = day["bundle_to_topic_idx"].get(bi)
        if ti is None:
            continue
        runs_summary = []
        for run_data in day["runs"]:
            # Find the per-topic row for this bundle
            row = next(
                (r for r in run_data["per_topic"] if r["bundle_idx"] == bi),
                None,
            )
            if row is None:
                continue
            # Load the LLM record to see assigned cluster IDs
            llm = _load_smoke_run_assignments_llm(date, run_data["run"])
            assigned_cluster_ids = [
                a["cluster_id"]
                for a in (llm.get("assignments") or [])
                if ti in (a.get("topic_indices") or [])
            ]
            runs_summary.append({
                "run": run_data["run"],
                "n_new_assigned": row["n_new_assigned"],
                "n_labeled": row["n_labeled"],
                "n_unlabeled_new": row["n_unlabeled_new"],
                "on_topic": row["on_topic"],
                "off_topic": row["off_topic"],
                "off_topic_pct": row["off_topic_pct"],
                "n_clusters_assigned": len(assigned_cluster_ids),
                "assigned_cluster_ids": assigned_cluster_ids,
            })
        out.append({
            "date": date,
            "bundle_idx": bi,
            "topic_idx": ti,
            "label": trap["label"],
            "description": trap["description"],
            "runs": runs_summary,
        })
    return out


def _sport_cluster_per_run_fate(per_day: dict[str, dict]) -> dict | None:
    """Track the Sport-Wochenende cluster's per-run assignment fate."""
    if SPORT_DATE not in per_day:
        return None
    day = per_day[SPORT_DATE]
    topics = _load_smoke_topics(SPORT_DATE)
    out: dict[str, Any] = {
        "cluster_id": SPORT_CLUSTER_ID,
        "date": SPORT_DATE,
        "context": (
            f"The Sport-Wochenende cluster ({SPORT_CLUSTER_ID}, "
            f"{SPORT_DATE}) is the architectural pivot from the cluster-"
            f"level gravitation brief — under deterministic T=0.55 it "
            f"landed wholesale on topic-09 (Barcelona LaLiga). This "
            f"section tracks the LLM's per-run decision on the same "
            f"cluster."
        ),
        "per_run": [],
    }
    pre_clusters_record = _load_smoke_pre_clusters(SPORT_DATE)
    pre_clusters = list(pre_clusters_record.get("clusters") or [])
    cluster_record = next(
        (c for c in pre_clusters if c.get("id") == SPORT_CLUSTER_ID),
        None,
    )
    out["cluster_size"] = cluster_record.get("size") if cluster_record else None
    for run_data in day["runs"]:
        llm = _load_smoke_run_assignments_llm(SPORT_DATE, run_data["run"])
        entry = next(
            (a for a in (llm.get("assignments") or []) if a.get("cluster_id") == SPORT_CLUSTER_ID),
            None,
        )
        if entry is None:
            out["per_run"].append({
                "run": run_data["run"],
                "fate": "orphan",
                "topic_indices": [],
                "topic_titles": [],
            })
        else:
            ti_list = entry.get("topic_indices") or []
            titles = [
                (topics[ti].get("title") or "")[:80] if 0 <= ti < len(topics) else ""
                for ti in ti_list
            ]
            out["per_run"].append({
                "run": run_data["run"],
                "fate": "assigned",
                "topic_indices": ti_list,
                "topic_titles": titles,
            })
    return out


# ---------------------------------------------------------------------------
# Cross-day aggregation + Markdown rendering
# ---------------------------------------------------------------------------


def _render_audit_md(
    per_day: dict[str, dict],
    cross_day: dict,
    baseline: dict,
    case_studies: list[dict],
    sport_case: dict | None,
) -> str:
    lines: list[str] = []
    lines.append("# Cluster-LLM-assignment audit — cross-day summary")
    lines.append("")
    lines.append(
        "TASK-CLUSTER-LLM-ASSIGNMENT Phase 2 — audit of the 9 smoke runs "
        "against the 2,542-label ground truth from "
        "`docs/cluster-quality-audit/audit-2026-05-16/`. Each row reports "
        "the new pipeline's `curator_topic_assignments` intersected with "
        "the audit's labels per topic; pairs not in the audit label set "
        "(i.e. new assignments outside the V1 top-10 audit space) are "
        "excluded from the aggregate per the brief's documented constraint."
    )
    lines.append("")

    # ── Headline comparison ───────────────────────────────────────────
    base_x = baseline["cross_day_aggregate"]["weighted_off_topic_pct"]
    base_simple = baseline["cross_day_aggregate"]["simple_mean_off_topic_pct_per_topic"]
    llm_x = cross_day["weighted_off_topic_pct"]
    llm_x_min = cross_day["weighted_min"]
    llm_x_max = cross_day["weighted_max"]
    llm_spread = cross_day["weighted_spread_pp"]

    lines.append("## Headline — LLM 9-run pool vs Brief 5b baseline")
    lines.append("")
    lines.append("| Metric | Brief 5b (T=0.55 V1) | LLM 9-run mean | LLM min | LLM max | Spread (pp) | Δ mean vs baseline |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| **Weighted off-topic %** | **{base_x:.2f} %** | "
        f"**{llm_x:.2f} %** | {llm_x_min:.2f} % | {llm_x_max:.2f} % | "
        f"{llm_spread:.2f} | {llm_x - base_x:+.2f} pp |"
    )
    lines.append(
        f"| Simple-mean off-topic % | {base_simple:.2f} % | "
        f"{cross_day['simple_mean']:.2f} % | "
        f"{cross_day['simple_min']:.2f} % | "
        f"{cross_day['simple_max']:.2f} % | "
        f"{cross_day['simple_spread_pp']:.2f} | "
        f"{cross_day['simple_mean'] - base_simple:+.2f} pp |"
    )
    lines.append("")

    win_by = base_x - llm_x
    if llm_x < base_x and llm_x_max < base_x:
        lines.append(
            f"**Verdict (mechanical):** the LLM mean ({llm_x:.2f} %) "
            f"beats Brief 5b's baseline ({base_x:.2f} %) by **{win_by:.2f} pp**, "
            f"and even the worst-of-9 run ({llm_x_max:.2f} %) sits below "
            f"the baseline. The win survives the spread."
        )
    elif llm_x < base_x:
        lines.append(
            f"**Verdict (mechanical):** the LLM mean ({llm_x:.2f} %) "
            f"beats Brief 5b's baseline ({base_x:.2f} %) by **{win_by:.2f} pp**, "
            f"but the worst-of-9 run ({llm_x_max:.2f} %) exceeds the "
            f"baseline by {llm_x_max - base_x:+.2f} pp. The win does NOT "
            f"survive the spread."
        )
    else:
        lines.append(
            f"**Verdict (mechanical):** the LLM mean ({llm_x:.2f} %) "
            f"does NOT beat Brief 5b's baseline ({base_x:.2f} %); "
            f"deficit {llm_x - base_x:+.2f} pp."
        )
    lines.append("")

    # ── Per-run table ─────────────────────────────────────────────────
    lines.append("## Per-run audit (9 rows)")
    lines.append("")
    lines.append("| Date | Run | n_audited | n_off | Weighted off % | Simple-mean off % | Mean precision | Mean recall |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for date, day in per_day.items():
        for r in day["runs"]:
            lines.append(
                f"| {date} | {r['run']} | {r['n_findings_audited']} | "
                f"{r['n_off_topic']} | **{r['weighted_off_topic_pct']:.2f} %** | "
                f"{r['simple_mean_off_topic_pct']:.2f} % | "
                f"{r['mean_per_topic_precision']:.3f} | "
                f"{r['mean_per_topic_recall']:.3f} |"
            )
    lines.append("")

    # ── Per-day spread ────────────────────────────────────────────────
    lines.append("## Per-day spread")
    lines.append("")
    lines.append(
        "Spread is the load-bearing signal — large spread between runs "
        "indicates the LLM is making materially different judgements "
        "run-to-run, which has implications for production stability."
    )
    lines.append("")
    lines.append("| Date | Baseline (Brief 5b) | LLM mean | LLM min | LLM max | Spread (pp) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for day_baseline in baseline["per_day"]:
        date = day_baseline["date"]
        base_off = day_baseline["weighted_off_topic_pct"]
        if date in per_day:
            sp = per_day[date]["spread"]["weighted_off_topic_pct"]
            lines.append(
                f"| {date} | {base_off:.2f} % | **{sp['mean']:.2f} %** | "
                f"{sp['min']:.2f} % | {sp['max']:.2f} % | {sp['spread_pp']:.2f} |"
            )
    lines.append("")

    # ── Per-topic detail ──────────────────────────────────────────────
    lines.append("## Per-topic detail (30 audited topics × 3 LLM runs + baseline)")
    lines.append("")
    lines.append(
        "For each of the 30 audited topics (10 per day): per-run "
        "off-topic %, baseline off-topic % at Brief 5b, mean precision "
        "+ recall."
    )
    lines.append("")

    # Build baseline per-topic lookup
    baseline_per_topic: dict[tuple[str, int], dict] = {}
    for day_baseline in baseline["per_day"]:
        date = day_baseline["date"]
        for t in day_baseline.get("topics") or []:
            baseline_per_topic[(date, t["bundle_idx"])] = t

    for date, day in per_day.items():
        lines.append(f"### {date}")
        lines.append("")
        lines.append("| Bundle | Topic title (truncated) | Baseline off % | Run 1 off % | Run 2 off % | Run 3 off % | LLM mean off % | LLM spread (pp) |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|---:|")
        for bi in day["bundle_indices"]:
            base_off = baseline_per_topic.get((date, bi), {}).get("off_topic_pct", 0.0)
            row_offs: list[float] = []
            row_title: str = ""
            for run_data in day["runs"]:
                row = next(
                    (r for r in run_data["per_topic"] if r["bundle_idx"] == bi),
                    None,
                )
                if row is None:
                    continue
                row_offs.append(row["off_topic_pct"])
                row_title = row["topic_title"]
            mean_off = statistics.mean(row_offs) if row_offs else 0.0
            spread = (max(row_offs) - min(row_offs)) if row_offs else 0.0
            lines.append(
                f"| topic-{bi:02d} | {row_title[:60]} | "
                f"{base_off:.2f} % | "
                f"{(row_offs[0] if len(row_offs) > 0 else 0):.2f} % | "
                f"{(row_offs[1] if len(row_offs) > 1 else 0):.2f} % | "
                f"{(row_offs[2] if len(row_offs) > 2 else 0):.2f} % | "
                f"**{mean_off:.2f} %** | "
                f"{spread:.2f} |"
            )
        lines.append("")

    # ── Gravity-trap case studies ─────────────────────────────────────
    lines.append("## Gravity-trap case studies")
    lines.append("")
    lines.append("Three known gravity-trap topics where deterministic "
                 "T=0.55 V1 either succeeds or hovers near the acceptance "
                 "boundary. The LLM's per-run behaviour is reported below.")
    lines.append("")
    for case in case_studies:
        lines.append(f"### {case['date']} topic-{case['bundle_idx']:02d} — "
                     f"{case['label']}")
        lines.append("")
        lines.append(f"_{case['description']}_")
        lines.append("")
        lines.append("| Run | n_new_assigned | n_labeled | n_unlabeled_new | on | off | off % | n_clusters_assigned |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in case["runs"]:
            lines.append(
                f"| {r['run']} | {r['n_new_assigned']} | {r['n_labeled']} | "
                f"{r['n_unlabeled_new']} | {r['on_topic']} | {r['off_topic']} | "
                f"**{r['off_topic_pct']:.2f} %** | {r['n_clusters_assigned']} |"
            )
        lines.append("")

    # ── Sport-Wochenende specific case ────────────────────────────────
    if sport_case:
        lines.append("## Sport-Wochenende cluster mc-04 fate (architectural canary)")
        lines.append("")
        lines.append(sport_case["context"])
        lines.append("")
        if sport_case.get("cluster_size") is not None:
            lines.append(f"Cluster size: **{sport_case['cluster_size']}** findings.")
            lines.append("")
        lines.append("| Run | Fate | Assigned topics |")
        lines.append("|---:|---|---|")
        for r in sport_case["per_run"]:
            if r["fate"] == "orphan":
                lines.append(f"| {r['run']} | **orphan** — LLM left mc-04 unassigned | — |")
            else:
                titles_str = "; ".join(
                    f"topic-{ti:02d}: {title!r}"
                    for ti, title in zip(r["topic_indices"], r["topic_titles"])
                )
                lines.append(f"| {r['run']} | assigned | {titles_str} |")
        lines.append("")

    lines.append("## Honest framing")
    lines.append("")
    lines.append(
        "The LLM audit numbers are themselves stochastic across runs. "
        "Architect-decision rule (per brief watch-item 4): the LLM mean "
        "must beat 8.23 % **by enough that the win survives the spread** "
        "— a mean of 6 % with spread 3–9 % is a different proposition "
        "from a mean of 6 % with spread 5.5–6.5 %. The spread column "
        "above is the load-bearing one for that judgement."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print("== Auditing LLM-cluster-assignment smoke runs ==")
    print(f"  Smoke root: {SMOKE_ROOT.relative_to(REPO_ROOT)}")
    print(f"  Output:     {OUT_ROOT.relative_to(REPO_ROOT)}")
    t0 = time.monotonic()

    per_day: dict[str, dict] = {}
    for date in DATES:
        per_day[date] = _audit_one_day(date)

    # Cross-day aggregate over all 9 runs
    all_runs = [r for day in per_day.values() for r in day["runs"]]
    n_audited_pool = sum(r["n_findings_audited"] for r in all_runs)
    n_off_pool = sum(r["n_off_topic"] for r in all_runs)
    weighted_pool = (100.0 * n_off_pool / n_audited_pool) if n_audited_pool else 0.0

    weighted_per_run = [r["weighted_off_topic_pct"] for r in all_runs]
    simple_per_run = [r["simple_mean_off_topic_pct"] for r in all_runs]

    cross_day = {
        "n_runs": len(all_runs),
        "n_findings_audited_pool": n_audited_pool,
        "n_off_topic_pool": n_off_pool,
        "weighted_off_topic_pct": round(weighted_pool, 2),
        "weighted_min": round(min(weighted_per_run), 2) if weighted_per_run else 0.0,
        "weighted_max": round(max(weighted_per_run), 2) if weighted_per_run else 0.0,
        "weighted_spread_pp": round(
            max(weighted_per_run) - min(weighted_per_run), 2
        ) if weighted_per_run else 0.0,
        "simple_mean": round(statistics.mean(simple_per_run), 3)
        if simple_per_run else 0.0,
        "simple_min": round(min(simple_per_run), 3) if simple_per_run else 0.0,
        "simple_max": round(max(simple_per_run), 3) if simple_per_run else 0.0,
        "simple_spread_pp": round(
            max(simple_per_run) - min(simple_per_run), 3
        ) if simple_per_run else 0.0,
    }

    baseline = _load_baseline_summary()
    case_studies = _gravity_trap_case_studies(per_day)
    sport_case = _sport_cluster_per_run_fate(per_day)

    # Render the Markdown
    md = _render_audit_md(per_day, cross_day, baseline, case_studies, sport_case)
    (OUT_ROOT / "README.md").write_text(md, encoding="utf-8")

    # Per-day Markdown
    for date, day in per_day.items():
        lines: list[str] = []
        lines.append(f"# Cluster-LLM-assignment audit — {date}")
        lines.append("")
        for r in day["runs"]:
            lines.append(f"## Run {r['run']}")
            lines.append("")
            lines.append(f"- Weighted off-topic: **{r['weighted_off_topic_pct']:.2f} %**")
            lines.append(f"- Simple-mean off-topic: {r['simple_mean_off_topic_pct']:.2f} %")
            lines.append(f"- Audited: {r['n_findings_audited']}, off: {r['n_off_topic']}")
            lines.append(f"- Mean precision: {r['mean_per_topic_precision']:.3f}")
            lines.append(f"- Mean recall: {r['mean_per_topic_recall']:.3f}")
            lines.append("")
            lines.append("| Bundle | Topic title | n_new_assigned | n_labeled | n_unlabeled_new | on | off | off % | precision | recall |")
            lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
            for row in r["per_topic"]:
                lines.append(
                    f"| topic-{row['bundle_idx']:02d} | {row['topic_title'][:70]} | "
                    f"{row['n_new_assigned']} | {row['n_labeled']} | "
                    f"{row['n_unlabeled_new']} | {row['on_topic']} | "
                    f"{row['off_topic']} | {row['off_topic_pct']:.2f} % | "
                    f"{row['precision']:.3f} | {row['recall']:.3f} |"
                )
            lines.append("")
        (OUT_ROOT / f"{date}.md").write_text("\n".join(lines), encoding="utf-8")

    # Machine-readable audit.json with everything
    audit_json = {
        "audit_date": "2026-05-17",
        "task": "TASK-CLUSTER-LLM-ASSIGNMENT — Phase 2 audit",
        "methodology": (
            "Fixed audit-2026-05-16 topic-set input to AssignClustersStage. "
            "Cross-reference (finding, topic) pairs from the smoke runs "
            "against the 2,542 audit labels; pairs not in the audit set "
            "are excluded from the aggregate (V1 top-10 audit space "
            "constraint, same as Brief 5b)."
        ),
        "baseline": {
            "source": "docs/cluster-quality-audit/audit-2026-05-16-recalibrated/",
            "weighted_off_topic_pct": baseline["cross_day_aggregate"]["weighted_off_topic_pct"],
            "simple_mean_off_topic_pct_per_topic": baseline["cross_day_aggregate"]["simple_mean_off_topic_pct_per_topic"],
            "n_findings_audited": baseline["cross_day_aggregate"]["n_findings_audited"],
            "n_topics_audited": baseline["cross_day_aggregate"]["n_topics_audited"],
        },
        "llm_cross_day_aggregate": cross_day,
        "per_day": {
            date: {
                "bundle_indices": day["bundle_indices"],
                "bundle_to_topic_idx": {
                    str(bi): ti for bi, ti in day["bundle_to_topic_idx"].items()
                },
                "spread": day["spread"],
                "runs": day["runs"],
            }
            for date, day in per_day.items()
        },
        "gravity_trap_case_studies": case_studies,
        "sport_cluster_case": sport_case,
    }
    (OUT_ROOT / "audit.json").write_text(
        json.dumps(audit_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    wall = time.monotonic() - t0
    print("\n== Cross-day aggregate ==")
    print(f"  Findings audited pool: {n_audited_pool}")
    print(f"  Off-topic pool:        {n_off_pool}")
    print(f"  Weighted %:            {cross_day['weighted_off_topic_pct']:.2f}")
    print(f"    min / max:           {cross_day['weighted_min']:.2f} / {cross_day['weighted_max']:.2f}")
    print(f"    spread (pp):         {cross_day['weighted_spread_pp']:.2f}")
    print(f"  Baseline (Brief 5b):   {baseline['cross_day_aggregate']['weighted_off_topic_pct']:.2f} %")
    print(f"  Wall: {wall:.1f}s")
    print(f"  Wrote {(OUT_ROOT / 'README.md').relative_to(REPO_ROOT)}")
    print(f"  Wrote {(OUT_ROOT / 'audit.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
