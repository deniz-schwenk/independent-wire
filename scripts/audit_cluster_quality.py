"""Cluster-quality audit harness — top-10 topics per day, all findings.

Authoritative reference: TASK-CLUSTER-QUALITY-AUDIT.md.

For each of the three eval state files, this harness:

  1. Replays the new triple-stage Curator pipeline (pre_cluster →
     CuratorTopicDiscoveryStage → gravitational_assign →
     assemble_curator_topics) starting from the persisted
     ``curator_findings`` slot. Real LLM call, real fastembed.
  2. Sorts ``curator_topics_unsliced`` by ``source_count`` descending
     and takes the top 10 (or fewer if the day has fewer non-zero
     topics).
  3. Dumps per-topic JSON bundles to ``_data/{date}/topic-NN.json``
     containing the topic centre (title + summary) and every assigned
     finding with the same text the embedding pipeline used
     (``title + summary + description``).
  4. Loads per-topic audit CSVs at
     ``_data/{date}/topic-NN.audit.csv`` if present (one row per
     finding: ``finding_id, is_on_topic, reasoning_note``). These are
     hand-written by CC against the rubric in the brief.
  5. Renders per-day Markdown reports + aggregate ``summary.json``.

Subcommands:
    replay   — phase 1: replay pipeline + dump JSON bundles + stub
               CSVs (with blank judgements) for the auditor to fill.
    render   — phase 2: read filled CSVs + bundles + emit reports.
    all      — runs replay then render in one pass (useful when the
               CSVs already exist and you just want to refresh
               aggregates).

Usage:
    python scripts/audit_cluster_quality.py replay
    python scripts/audit_cluster_quality.py render
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from datetime import date as _date
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agent_stages import CuratorTopicDiscoveryStage  # noqa: E402
from src.bus import RunBus  # noqa: E402
from src.stages.gravitational_assign import gravitational_assign  # noqa: E402
from src.stages.pre_cluster import pre_cluster_findings  # noqa: E402
from src.stages.run_stages import assemble_curator_topics  # noqa: E402

from scripts.run import create_agents  # noqa: E402


DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}


AUDIT_DATE = _date.today().isoformat()
OUT_ROOT = REPO_ROOT / "docs" / "cluster-quality-audit" / f"audit-{AUDIT_DATE}"
DATA_ROOT = OUT_ROOT / "_data"

TOP_K_TOPICS = 10


def _finding_text(f: dict) -> str:
    """Same convention as src/stages/pre_cluster.py::_finding_text."""
    parts = [
        (f.get("title") or "").strip(),
        (f.get("summary") or "").strip(),
        (f.get("description") or "").strip(),
    ]
    return " | ".join(p for p in parts if p)


def _load_findings(state_path: Path) -> list[dict]:
    with state_path.open() as fh:
        data = json.load(fh)
    return list(data.get("curator_findings") or [])


def _findings_by_id(findings: list[dict]) -> dict[str, dict]:
    """Findings are positional in curator_findings; the canonical id
    is ``finding-{index}``. Honour any explicit id field if present
    for forward compatibility."""
    out: dict[str, dict] = {}
    for idx, f in enumerate(findings):
        sid = f.get("source_id") or f.get("id") or f"finding-{idx}"
        out[sid] = f
    return out


async def replay_pipeline(
    date: str, state_path: Path, agent
) -> tuple[list[dict], list[dict], dict]:
    findings = _load_findings(state_path)
    print(f"  [{date}] {len(findings)} findings — running new pipeline ...")
    rb = RunBus(
        run_id=f"audit-{date}",
        run_date=date,
        curator_findings=findings,
    )
    t0 = time.monotonic()
    rb = await pre_cluster_findings(rb)
    rb = await CuratorTopicDiscoveryStage(agent)(rb)
    rb = await gravitational_assign(rb)
    rb = await assemble_curator_topics(rb)
    wall = round(time.monotonic() - t0, 2)
    topics = list(rb.curator_topics_unsliced or [])
    meta = {
        "wall_seconds": wall,
        "llm_cost_usd": float(
            (rb.curator_discovered_topics or {}).get("llm_cost_usd", 0.0) or 0.0
        ),
        "n_findings": len(findings),
        "n_micro_clusters": int(
            (rb.curator_pre_clusters or {}).get("n_clusters", 0) or 0
        ),
        "n_discovered_topics": int(
            (rb.curator_discovered_topics or {}).get("n_topics", 0) or 0
        ),
        "n_topics_after_assemble": len(topics),
        "n_orphans": int((rb.curator_topic_assignments or {}).get("n_orphans", 0) or 0),
        "agent_name": agent.name,
        "agent_model": agent.model,
    }
    print(
        f"  [{date}] wall {wall}s, "
        f"{meta['n_topics_after_assemble']} topics, "
        f"orphans {meta['n_orphans']}/{len(findings)}, "
        f"${meta['llm_cost_usd']:.4f}"
    )
    return findings, topics, meta


def write_replay_bundles(
    date: str, findings: list[dict], topics: list[dict], meta: dict
) -> list[Path]:
    """Persist top-K topics + every assigned finding's text to JSON
    bundles. Stub an empty audit CSV alongside each bundle if none
    already exists — the auditor fills these by hand."""
    day_dir = DATA_ROOT / date
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # Cache the raw topics list so we can rebuild bundles without
    # another LLM call if the bundle schema changes.
    (day_dir / "_topics.json").write_text(
        json.dumps(topics, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    by_id = _findings_by_id(findings)
    ranked = sorted(
        topics,
        key=lambda t: (-int(t.get("source_count") or 0), t.get("title") or ""),
    )
    top_k = [t for t in ranked if int(t.get("source_count") or 0) > 0][:TOP_K_TOPICS]

    paths: list[Path] = []
    for idx, t in enumerate(top_k):
        title = t.get("title") or ""
        summary = t.get("summary") or ""
        sids = list(t.get("source_ids") or [])
        topic_findings: list[dict] = []
        for sid in sids:
            f = by_id.get(sid)
            if f is None:
                topic_findings.append({"source_id": sid, "missing": True})
                continue
            topic_findings.append(
                {
                    "source_id": sid,
                    "title": f.get("title") or "",
                    "summary": f.get("summary") or "",
                    "description": f.get("description") or "",
                    "language": f.get("language") or "",
                    "outlet": f.get("outlet_name")
                    or f.get("source_name")
                    or "",
                    "text": _finding_text(f),
                }
            )
        bundle = {
            "topic_index": idx,
            "topic_title": title,
            "topic_summary": summary,
            "source_count": int(t.get("source_count") or 0),
            "geographic_coverage": list(t.get("geographic_coverage") or []),
            "languages": list(t.get("languages") or []),
            "n_findings": len(topic_findings),
            "findings": topic_findings,
        }
        path = day_dir / f"topic-{idx:02d}.json"
        path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
        paths.append(path)

        # Stub the audit CSV with blank judgements (only if not already
        # written — preserves any audit work in progress).
        csv_path = day_dir / f"topic-{idx:02d}.audit.csv"
        if not csv_path.exists():
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["finding_id", "is_on_topic", "reasoning_note"])
                for tf in topic_findings:
                    w.writerow([tf["source_id"], "", ""])
        print(
            f"    topic-{idx:02d} n={len(topic_findings)} "
            f"title={title[:70]!r}"
        )
    return paths


def _load_audit_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        for row in r:
            rows.append(row)
    return rows


def _bundle_paths(date: str) -> list[Path]:
    return sorted((DATA_ROOT / date).glob("topic-*.json"))


def render_day(date: str) -> dict:
    day_dir = DATA_ROOT / date
    if not day_dir.exists():
        return {"date": date, "error": "no-replay-data"}
    meta_path = day_dir / "_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    per_topic_rows: list[dict] = []
    all_findings_audited = 0
    all_off_topic = 0
    sum_off_pct_per_topic: list[float] = []

    md: list[str] = []
    md.append(f"# Cluster-quality audit — {date}")
    md.append("")
    md.append("## Run summary")
    md.append("")
    md.append(f"- State file: `{DATASETS[date].relative_to(REPO_ROOT)}`")
    md.append(
        f"- Pipeline agent: `{meta.get('agent_name', '?')}` "
        f"(`{meta.get('agent_model', '?')}`)"
    )
    md.append(f"- Wall: {meta.get('wall_seconds', '?')}s")
    md.append(f"- LLM cost: ${meta.get('llm_cost_usd', 0.0):.4f}")
    md.append(f"- n_findings: {meta.get('n_findings', '?')}")
    md.append(f"- n_micro_clusters: {meta.get('n_micro_clusters', '?')}")
    md.append(f"- n_topics_after_assemble: {meta.get('n_topics_after_assemble', '?')}")

    bundle_paths = _bundle_paths(date)
    n_topics_audited = 0
    md.append(f"- topics_audited (top by source_count): {len(bundle_paths)}")
    md.append("")

    md.append("## Per-topic results")
    md.append("")
    md.append(
        "| # | Topic title | n_src | on | off | off % | qualitative note |"
    )
    md.append("|---:|---|---:|---:|---:|---:|---|")

    topic_summaries: list[dict] = []

    for bpath in bundle_paths:
        bundle = json.loads(bpath.read_text(encoding="utf-8"))
        csv_path = bpath.with_suffix("").with_suffix(".audit.csv")
        rows = _load_audit_csv(csv_path)
        # Filter to rows with a usable label
        labeled = [
            r for r in rows if (r.get("is_on_topic") or "").strip() in ("0", "1")
        ]
        on = sum(1 for r in labeled if r["is_on_topic"].strip() == "1")
        off = sum(1 for r in labeled if r["is_on_topic"].strip() == "0")
        n_lab = on + off
        off_pct = (100.0 * off / n_lab) if n_lab else 0.0
        # Qualitative note — pulled from the CSV header sidecar if present
        note_sidecar = bpath.with_suffix("").with_suffix(".note.txt")
        qual = (
            note_sidecar.read_text(encoding="utf-8").strip()
            if note_sidecar.exists()
            else ""
        )
        if not qual and not n_lab:
            qual = "_audit pending_"
        title = (bundle.get("topic_title") or "")[:80]
        md.append(
            f"| {bundle.get('topic_index', '?')} | {title} | "
            f"{bundle.get('source_count', 0)} | {on} | {off} | "
            f"{off_pct:.1f}% | {qual} |"
        )
        if n_lab:
            n_topics_audited += 1
            all_findings_audited += n_lab
            all_off_topic += off
            sum_off_pct_per_topic.append(off_pct)
        topic_summaries.append(
            {
                "topic_index": bundle.get("topic_index"),
                "topic_title": bundle.get("topic_title"),
                "source_count": bundle.get("source_count"),
                "n_labeled": n_lab,
                "on_topic": on,
                "off_topic": off,
                "off_topic_pct": round(off_pct, 2),
                "qualitative_note": qual,
                "csv_file": str(csv_path.relative_to(OUT_ROOT)),
            }
        )

    md.append("")
    weighted = (
        100.0 * all_off_topic / all_findings_audited if all_findings_audited else 0.0
    )
    simple = mean(sum_off_pct_per_topic) if sum_off_pct_per_topic else 0.0
    md.append("## Aggregate for this day")
    md.append("")
    md.append(f"- Topics audited: **{n_topics_audited}** of {len(bundle_paths)}")
    md.append(f"- Findings audited: **{all_findings_audited}**")
    md.append(f"- Off-topic: **{all_off_topic}**")
    md.append(
        f"- Weighted off-topic rate (per-finding): **{weighted:.2f} %**"
    )
    md.append(
        f"- Simple-mean off-topic rate (per-topic average): **{simple:.2f} %**"
    )
    md.append("")
    md.append("## Per-finding traces")
    md.append("")
    md.append("Per-topic audit CSVs live alongside this report at `_data/{date}/topic-NN.audit.csv`.")
    md.append("")

    (OUT_ROOT / f"{date}.md").write_text("\n".join(md), encoding="utf-8")
    return {
        "date": date,
        "n_topics_audited": n_topics_audited,
        "n_topics_in_top_k": len(bundle_paths),
        "n_findings_audited": all_findings_audited,
        "n_off_topic": all_off_topic,
        "weighted_off_topic_pct": round(weighted, 2),
        "simple_mean_off_topic_pct": round(simple, 2),
        "topics": topic_summaries,
        "meta": meta,
    }


def render_all() -> None:
    per_day: list[dict] = []
    for date in DATASETS:
        per_day.append(render_day(date))
    total_findings = sum(d.get("n_findings_audited", 0) for d in per_day)
    total_off = sum(d.get("n_off_topic", 0) for d in per_day)
    cross_weighted = (
        100.0 * total_off / total_findings if total_findings else 0.0
    )
    per_topic_pcts: list[float] = []
    for d in per_day:
        for t in d.get("topics", []):
            if t.get("n_labeled", 0):
                per_topic_pcts.append(t.get("off_topic_pct", 0.0))
    cross_simple = mean(per_topic_pcts) if per_topic_pcts else 0.0

    summary = {
        "audit_date": AUDIT_DATE,
        "datasets": list(DATASETS.keys()),
        "cross_day_aggregate": {
            "n_findings_audited": total_findings,
            "n_off_topic": total_off,
            "weighted_off_topic_pct": round(cross_weighted, 2),
            "simple_mean_off_topic_pct_per_topic": round(cross_simple, 2),
            "n_topics_audited": len(per_topic_pcts),
        },
        "per_day": per_day,
    }
    (OUT_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("\n== Cross-day aggregate ==")
    print(f"  Findings audited: {total_findings}")
    print(f"  Off-topic:        {total_off}")
    print(f"  Weighted % :       {cross_weighted:.2f}")
    print(f"  Simple-mean %:     {cross_simple:.2f}")
    print(f"  Topics audited:    {len(per_topic_pcts)}")
    print(f"  Wrote {(OUT_ROOT / 'summary.json').relative_to(REPO_ROOT)}")


async def replay_all() -> None:
    agents = create_agents()
    agent = agents.get("curator_topic_discovery")
    if agent is None:
        raise RuntimeError("curator_topic_discovery agent not registered")
    print(
        f"== Cluster-quality audit replay — {len(DATASETS)} dataset(s) ==\n"
        f"   Agent: {agent.name} ({agent.model}, temp {agent.temperature})\n"
        f"   Output: {OUT_ROOT.relative_to(REPO_ROOT)}/"
    )
    for date, path in DATASETS.items():
        if not path.exists():
            print(f"  [{date}] state-missing: {path}")
            continue
        findings, topics, meta = await replay_pipeline(date, path, agent)
        write_replay_bundles(date, findings, topics, meta)


def rebuild_bundles() -> None:
    """Rebuild bundles from the cached topics list + state-file
    findings without another LLM call. Used when the bundle schema
    changes (e.g. id-lookup fix) but the topic set is already on
    disk."""
    for date, state_path in DATASETS.items():
        day_dir = DATA_ROOT / date
        topics_path = day_dir / "_topics.json"
        meta_path = day_dir / "_meta.json"
        if not topics_path.exists() or not state_path.exists():
            print(f"  [{date}] missing cached topics or state file — skip")
            continue
        topics = json.loads(topics_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        findings = _load_findings(state_path)
        print(f"  [{date}] rebuilding bundles from {len(topics)} cached topics ...")
        # Remove any stale topic-NN.json + .audit.csv with empty CSVs
        # so the new bundle (with valid id lookups) repopulates.
        for stale_csv in day_dir.glob("topic-*.audit.csv"):
            rows = _load_audit_csv(stale_csv)
            has_labels = any((r.get("is_on_topic") or "").strip() in ("0", "1") for r in rows)
            if not has_labels:
                stale_csv.unlink()
        write_replay_bundles(date, findings, topics, meta)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "subcommand", choices=("replay", "rebuild", "render", "all")
    )
    args = ap.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    if args.subcommand == "replay":
        asyncio.run(replay_all())
    elif args.subcommand == "rebuild":
        rebuild_bundles()
    elif args.subcommand == "render":
        render_all()
    else:
        asyncio.run(replay_all())
        render_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
