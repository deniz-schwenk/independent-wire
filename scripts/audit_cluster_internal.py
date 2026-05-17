"""Cluster-internal-coherence audit — top-10 micro-clusters per day.

Authoritative reference: TASK-CLUSTER-INTERNAL-AUDIT.md.

This audit is the **precondition test** for Phase B (cluster-level
gravitational assignment, where the cluster centroid would be the
similarity comparator instead of the individual finding). The question
under test is whether Brief 1's micro-clusters are internally coherent
enough to act as semantic anchors — i.e. whether assigning a whole
cluster to a topic is a sound substitute for assigning each of its
findings individually.

For each of the three eval state files this harness:

  1. Replays Brief 1's ``pre_cluster_findings`` against the persisted
     ``curator_findings`` slot. Deterministic, no LLM.
  2. Sorts the resulting clusters by size descending and selects the
     top 10.
  3. Dumps per-cluster JSON bundles (full title + summary + description
     for every finding in the cluster) to
     ``_data/{date}/cluster-NN.json``.
  4. Stubs per-cluster ``cluster-NN.audit.csv`` (blank judgements) and
     ``cluster-NN.hypothesis.txt`` (blank one-sentence anchor) for the
     auditor to fill — see the brief's methodology section.
  5. ``render`` reads the filled CSVs + hypothesis sidecars + bundles
     and produces per-day Markdown reports + an aggregate
     ``summary.json`` carrying both weighted and simple-mean off-topic
     rates and the count of clusters whose hypothesis was non-singular.

Subcommands:
    replay   — phase 1: replay pre_cluster + dump bundles + stub CSVs
               and hypothesis sidecars. Idempotent — existing
               judgements + hypotheses are preserved if present.
    render   — phase 2: read filled CSVs + bundles + hypotheses, emit
               per-day Markdown + aggregate summary.json.
    all      — runs replay then render.

Usage:
    python scripts/audit_cluster_internal.py replay
    python scripts/audit_cluster_internal.py render

Pre-cluster output is also cached under ``_cache/{date}.preclusters.json``
so iterative ``render`` passes don't re-embed. ``.gitignore``d.
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

from src.bus import RunBus  # noqa: E402
from src.stages.pre_cluster import (  # noqa: E402
    DISTANCE_THRESHOLD,
    LINKAGE,
    METRIC,
    pre_cluster_findings,
)
from src.stages.coherence import (  # noqa: E402
    FASTEMBED_VERSION_REQUIRED,
    MODEL_NAME,
)


DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}


AUDIT_DATE = _date.today().isoformat()
OUT_ROOT = REPO_ROOT / "docs" / "cluster-internal-audit" / f"audit-{AUDIT_DATE}"
DATA_ROOT = OUT_ROOT / "_data"
CACHE_ROOT = OUT_ROOT / "_cache"

TOP_K_CLUSTERS = 10


# ── Helpers ──────────────────────────────────────────────────────────────


def _finding_text_full(f: dict) -> str:
    """Same convention as the topic-quality audit harness — concatenate
    title | summary | description with ' | ' as separator. Used for the
    auditor's reading view."""
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
    """Findings are positional in ``curator_findings`` — canonical id is
    ``finding-{index}``. Honour an explicit id if present."""
    out: dict[str, dict] = {}
    for idx, f in enumerate(findings):
        sid = f.get("source_id") or f.get("id") or f"finding-{idx}"
        out[sid] = f
    return out


def top_k_clusters_by_size(clusters: list[dict], k: int = TOP_K_CLUSTERS) -> list[dict]:
    """Pure helper — sort by ``size`` descending, then by the cluster's
    smallest contained finding-index ascending for tie-stable output
    (matches ``_format_clusters`` in src/stages/pre_cluster.py). Drops
    empty clusters defensively."""
    def _first_finding_idx(c: dict) -> int:
        sids = list(c.get("source_ids") or [])
        if not sids:
            return 10**9
        return min(int(s.split("finding-")[-1]) for s in sids)

    ranked = sorted(
        [c for c in clusters if int(c.get("size") or 0) > 0],
        key=lambda c: (-int(c.get("size") or 0), _first_finding_idx(c)),
    )
    return ranked[:k]


# ── Replay phase ─────────────────────────────────────────────────────────


async def replay_pre_cluster_for_day(date: str, state_path: Path) -> tuple[list[dict], dict]:
    """Run pre_cluster_findings against the persisted findings; return
    (findings, pre_cluster_record). Cache the pre_cluster record to
    ``_cache/{date}.preclusters.json`` to avoid re-embedding on
    subsequent ``replay``s."""
    findings = _load_findings(state_path)
    cache_path = CACHE_ROOT / f"{date}.preclusters.json"
    if cache_path.exists():
        record = json.loads(cache_path.read_text(encoding="utf-8"))
        if record.get("n_findings_clustered") == len(findings):
            print(
                f"  [{date}] cache hit — {len(findings)} findings, "
                f"{record.get('n_clusters')} clusters (skip embed)"
            )
            return findings, record
    print(f"  [{date}] {len(findings)} findings — running pre_cluster_findings ...")
    rb = RunBus(run_id=f"audit-internal-{date}", run_date=date, curator_findings=findings)
    t0 = time.monotonic()
    rb = await pre_cluster_findings(rb)
    wall = round(time.monotonic() - t0, 2)
    record = dict(rb.curator_pre_clusters or {})
    record["wall_seconds_audit"] = wall
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"  [{date}] {wall}s — {record.get('n_clusters')} clusters, "
        f"top sizes {[c['size'] for c in record.get('clusters', [])[:10]]}"
    )
    return findings, record


def write_replay_bundles(date: str, findings: list[dict], record: dict) -> list[Path]:
    """Persist top-K clusters + every assigned finding's text to JSON
    bundles. Stub an empty audit CSV and an empty hypothesis sidecar
    alongside each bundle iff they don't already exist (preserves any
    in-progress audit work)."""
    day_dir = DATA_ROOT / date
    day_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "state_file": str(DATASETS[date].relative_to(REPO_ROOT)),
        "embed_model_name": record.get("model_name", MODEL_NAME),
        "fastembed_version": record.get("fastembed_version", FASTEMBED_VERSION_REQUIRED),
        "pre_cluster_params": record.get("params") or {
            "distance_threshold": DISTANCE_THRESHOLD,
            "linkage": LINKAGE,
            "metric": METRIC,
        },
        "n_findings": len(findings),
        "n_clusters_total": int(record.get("n_clusters") or 0),
        "wall_seconds_pre_cluster": record.get("wall_seconds"),
        "wall_seconds_audit_replay": record.get("wall_seconds_audit"),
        "top_k": TOP_K_CLUSTERS,
    }
    (day_dir / "_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    by_id = _findings_by_id(findings)
    top_k = top_k_clusters_by_size(list(record.get("clusters") or []), TOP_K_CLUSTERS)

    paths: list[Path] = []
    for idx, c in enumerate(top_k):
        sids = list(c.get("source_ids") or [])
        cluster_findings: list[dict] = []
        for sid in sids:
            f = by_id.get(sid)
            if f is None:
                cluster_findings.append({"source_id": sid, "missing": True})
                continue
            cluster_findings.append(
                {
                    "source_id": sid,
                    "title": f.get("title") or "",
                    "summary": f.get("summary") or "",
                    "description": f.get("description") or "",
                    "language": f.get("language") or "",
                    "outlet": f.get("outlet_name") or f.get("source_name") or "",
                    "text": _finding_text_full(f),
                }
            )

        bundle = {
            "cluster_rank": idx,
            "cluster_id": c.get("id") or f"mc-{idx:03d}",
            "size": int(c.get("size") or 0),
            "n_findings": len(cluster_findings),
            "findings": cluster_findings,
        }
        bpath = day_dir / f"cluster-{idx:02d}.json"
        bpath.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
        paths.append(bpath)

        csv_path = day_dir / f"cluster-{idx:02d}.audit.csv"
        if not csv_path.exists():
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["finding_id", "is_on_topic", "reasoning_note"])
                for cf in cluster_findings:
                    w.writerow([cf["source_id"], "", ""])

        hyp_path = day_dir / f"cluster-{idx:02d}.hypothesis.txt"
        if not hyp_path.exists():
            hyp_path.write_text("", encoding="utf-8")

        print(
            f"    cluster-{idx:02d} ({bundle['cluster_id']}) "
            f"n={len(cluster_findings)} first-title="
            f"{(cluster_findings[0].get('title') or '')[:80]!r}"
        )
    return paths


async def replay_all() -> None:
    print(
        f"== Cluster-internal audit replay — {len(DATASETS)} dataset(s) ==\n"
        f"   Output: {OUT_ROOT.relative_to(REPO_ROOT)}/\n"
        f"   pre_cluster params: T={DISTANCE_THRESHOLD}, linkage={LINKAGE}, metric={METRIC}\n"
    )
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    for date, path in DATASETS.items():
        if not path.exists():
            print(f"  [{date}] state-missing: {path}")
            continue
        findings, record = await replay_pre_cluster_for_day(date, path)
        write_replay_bundles(date, findings, record)


# ── Render phase ─────────────────────────────────────────────────────────


def _load_audit_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _hypothesis_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _hypothesis_is_non_singular(text: str) -> bool:
    """The brief specifies the non-singular sentinel pattern verbatim
    ('no apparent single story'). Treat the presence of that phrase
    (case-insensitive) as the marker — auditors write the hypothesis
    free-prose otherwise."""
    if not text:
        return False
    return "no apparent single story" in text.lower()


def _bundle_paths(date: str) -> list[Path]:
    return sorted((DATA_ROOT / date).glob("cluster-*.json"))


def render_day(date: str) -> dict:
    day_dir = DATA_ROOT / date
    if not day_dir.exists():
        return {"date": date, "error": "no-replay-data"}
    meta_path = day_dir / "_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    md: list[str] = []
    md.append(f"# Cluster-internal audit — {date}")
    md.append("")
    md.append(
        "Top-10 micro-clusters from `pre_cluster_findings` "
        f"(T={meta.get('pre_cluster_params', {}).get('distance_threshold', DISTANCE_THRESHOLD)}, "
        f"linkage={meta.get('pre_cluster_params', {}).get('linkage', LINKAGE)}, "
        f"metric={meta.get('pre_cluster_params', {}).get('metric', METRIC)}). "
        "For each cluster the auditor read every finding title, formed a one-sentence "
        "hypothesis of the cluster's apparent story, then labelled every finding inside "
        "the cluster as on-topic / off-topic against that hypothesis. Conservative rule: "
        "same-actor-different-story, tangential mention, multi-topic roundup → off-topic."
    )
    md.append("")
    md.append("## Run summary")
    md.append("")
    md.append(f"- State file: `{meta.get('state_file', DATASETS[date].relative_to(REPO_ROOT))}`")
    md.append(f"- Embedder: `{meta.get('embed_model_name', '?')}` (fastembed `{meta.get('fastembed_version', '?')}`)")
    md.append(f"- n_findings: {meta.get('n_findings', '?')}")
    md.append(f"- n_clusters_total: {meta.get('n_clusters_total', '?')}")
    md.append(f"- clusters_audited (top-{meta.get('top_k', TOP_K_CLUSTERS)} by size): {len(_bundle_paths(date))}")
    md.append(f"- pre_cluster wall: {meta.get('wall_seconds_pre_cluster', '?')}s")
    md.append("")
    md.append("## Per-cluster results")
    md.append("")
    md.append("| # | cluster_id | size | on | off | off % | hypothesis singular? |")
    md.append("|---:|---|---:|---:|---:|---:|:---:|")

    per_cluster_rows: list[dict] = []
    bundle_paths = _bundle_paths(date)
    n_findings_audited_day = 0
    n_off_topic_day = 0
    per_cluster_off_pcts: list[float] = []
    n_clusters_non_singular = 0
    n_clusters_audited = 0

    for bpath in bundle_paths:
        bundle = json.loads(bpath.read_text(encoding="utf-8"))
        idx = int(bundle.get("cluster_rank", -1))
        cluster_id = bundle.get("cluster_id", "?")
        size = int(bundle.get("size", 0))

        csv_path = day_dir / f"cluster-{idx:02d}.audit.csv"
        hyp_path = day_dir / f"cluster-{idx:02d}.hypothesis.txt"
        rows = _load_audit_csv(csv_path)
        labeled = [
            r for r in rows if (r.get("is_on_topic") or "").strip() in ("0", "1")
        ]
        on = sum(1 for r in labeled if r["is_on_topic"].strip() == "1")
        off = sum(1 for r in labeled if r["is_on_topic"].strip() == "0")
        n_lab = on + off
        off_pct = (100.0 * off / n_lab) if n_lab else 0.0
        hypothesis = _hypothesis_text(hyp_path)
        non_singular = _hypothesis_is_non_singular(hypothesis)

        md.append(
            f"| {idx} | {cluster_id} | {size} | {on} | {off} | "
            f"{off_pct:.1f}% | {'no' if non_singular else 'yes' if hypothesis else '_pending_'} |"
        )

        if n_lab:
            n_clusters_audited += 1
            n_findings_audited_day += n_lab
            n_off_topic_day += off
            per_cluster_off_pcts.append(off_pct)
            if non_singular:
                n_clusters_non_singular += 1

        per_cluster_rows.append(
            {
                "cluster_rank": idx,
                "cluster_id": cluster_id,
                "size": size,
                "n_labeled": n_lab,
                "on_topic": on,
                "off_topic": off,
                "off_topic_pct": round(off_pct, 2),
                "hypothesis_was_singular": (
                    None if not hypothesis else (not non_singular)
                ),
                "hypothesis_text": hypothesis,
                "csv_file": str(csv_path.relative_to(OUT_ROOT)),
                "hypothesis_file": str(hyp_path.relative_to(OUT_ROOT)),
            }
        )

    md.append("")
    weighted = (
        100.0 * n_off_topic_day / n_findings_audited_day if n_findings_audited_day else 0.0
    )
    simple = mean(per_cluster_off_pcts) if per_cluster_off_pcts else 0.0

    md.append("## Aggregate for this day")
    md.append("")
    md.append(f"- Clusters audited: **{n_clusters_audited}** of {len(bundle_paths)}")
    md.append(f"- Findings audited: **{n_findings_audited_day}**")
    md.append(f"- Off-topic: **{n_off_topic_day}**")
    md.append(f"- Weighted off-topic rate (per-finding): **{weighted:.2f} %**")
    md.append(f"- Simple-mean off-topic rate (per-cluster average): **{simple:.2f} %**")
    md.append(f"- Clusters with non-singular hypothesis: **{n_clusters_non_singular}** of {n_clusters_audited}")
    md.append("")
    md.append("## Per-cluster hypotheses and detail")
    md.append("")
    for row in per_cluster_rows:
        idx = row["cluster_rank"]
        md.append(f"### cluster-{idx:02d} — `{row['cluster_id']}` (size {row['size']})")
        md.append("")
        if row["hypothesis_text"]:
            md.append("**Hypothesis:** " + row["hypothesis_text"])
        else:
            md.append("**Hypothesis:** _pending_")
        md.append("")
        if row["n_labeled"]:
            md.append(
                f"On-topic: {row['on_topic']}  ·  "
                f"Off-topic: {row['off_topic']}  ·  "
                f"Off %: {row['off_topic_pct']:.2f} %  ·  "
                f"Singular hypothesis: "
                f"{'yes' if row['hypothesis_was_singular'] else 'no'}"
            )
        else:
            md.append("_Audit pending — no rows labelled yet._")
        md.append("")
        md.append(
            f"Per-finding labels + reasoning notes: "
            f"[`{row['csv_file']}`]({row['csv_file']}). "
            f"Cluster-bundle finding text: "
            f"[`_data/{date}/cluster-{idx:02d}.json`](_data/{date}/cluster-{idx:02d}.json)."
        )
        md.append("")

    (OUT_ROOT / f"{date}.md").write_text("\n".join(md), encoding="utf-8")

    return {
        "date": date,
        "n_findings_population": int(meta.get("n_findings", 0)),
        "n_clusters_total": int(meta.get("n_clusters_total", 0)),
        "n_clusters_in_top_k": len(bundle_paths),
        "n_clusters_audited": n_clusters_audited,
        "n_findings_audited": n_findings_audited_day,
        "n_off_topic": n_off_topic_day,
        "weighted_off_topic_pct": round(weighted, 2),
        "simple_mean_off_topic_pct": round(simple, 2),
        "n_clusters_non_singular_hypothesis": n_clusters_non_singular,
        "clusters": per_cluster_rows,
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
    per_cluster_pcts: list[float] = []
    cross_non_singular = 0
    cross_clusters_audited = 0
    per_cluster_raw: list[dict] = []
    for d in per_day:
        for c in d.get("clusters", []):
            if c.get("n_labeled", 0):
                per_cluster_pcts.append(c["off_topic_pct"])
                cross_clusters_audited += 1
                if c.get("hypothesis_was_singular") is False:
                    cross_non_singular += 1
            per_cluster_raw.append(
                {
                    "cluster_id": c["cluster_id"],
                    "day": d["date"],
                    "size": c["size"],
                    "off_topic_count": c["off_topic"],
                    "off_topic_pct": c["off_topic_pct"],
                    "hypothesis_was_singular": c.get("hypothesis_was_singular"),
                }
            )
    cross_simple = mean(per_cluster_pcts) if per_cluster_pcts else 0.0

    summary = {
        "audit_date": AUDIT_DATE,
        "audit_label": "cluster-internal-coherence",
        "task_brief": "TASK-CLUSTER-INTERNAL-AUDIT.md",
        "datasets": list(DATASETS.keys()),
        "pre_cluster_params": {
            "distance_threshold": DISTANCE_THRESHOLD,
            "linkage": LINKAGE,
            "metric": METRIC,
            "embed_model_name": MODEL_NAME,
            "fastembed_version": FASTEMBED_VERSION_REQUIRED,
        },
        "top_k_clusters_per_day": TOP_K_CLUSTERS,
        "cross_day_aggregate": {
            "n_findings_audited": total_findings,
            "n_off_topic": total_off,
            "weighted_off_topic_pct": round(cross_weighted, 2),
            "simple_mean_off_topic_pct_per_cluster": round(cross_simple, 2),
            "n_clusters_audited": cross_clusters_audited,
            "n_clusters_non_singular_hypothesis": cross_non_singular,
        },
        "per_day": per_day,
        "per_cluster_raw": per_cluster_raw,
    }
    (OUT_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n== Cross-day aggregate ==")
    print(f"  Findings audited:                {total_findings}")
    print(f"  Off-topic:                       {total_off}")
    print(f"  Weighted off-topic %:            {cross_weighted:.2f}")
    print(f"  Simple-mean off-topic %:         {cross_simple:.2f}")
    print(f"  Clusters audited:                {cross_clusters_audited}")
    print(f"  Clusters non-singular hypothesis:{cross_non_singular}")
    print(f"  Wrote {(OUT_ROOT / 'summary.json').relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subcommand", choices=("replay", "render", "all"))
    args = ap.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    if args.subcommand == "replay":
        asyncio.run(replay_all())
    elif args.subcommand == "render":
        render_all()
    else:
        asyncio.run(replay_all())
        render_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
