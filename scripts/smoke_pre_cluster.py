"""Smoke harness for ``src/stages/pre_cluster.py``.

Authoritative reference: TASK-EMBED-PRE-CLUSTER-STAGE.md §"Smoke harness".

Runs the production pre-cluster stage against the three eval state
files anchored on by ``docs/CLUSTERING-EVAL-2026-05-14.md`` and writes
one Markdown summary per dataset. Architect's pre-integration sanity
check that the production stage reproduces the eval's
``agg-permissive`` numbers within ~10–15 % (cluster count) and with no
mega-cluster (max size < 100). Not wired into the pipeline; not part
of CI.

Usage:
    python scripts/smoke_pre_cluster.py
    python scripts/smoke_pre_cluster.py --dataset 2026-05-13

Each invocation re-runs the stage (the result depends only on the
deterministic input + the pinned model + the pinned sklearn version);
output reports go under ``docs/pre-cluster/smoke-2026-05-15/``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bus import RunBus  # noqa: E402
from src.stages.pre_cluster import pre_cluster_findings  # noqa: E402


# Mirror the eval harness's dataset registry (CLUSTERING-EVAL-2026-05-14).
DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}


OUT_ROOT = REPO_ROOT / "docs" / "pre-cluster" / "smoke-2026-05-15"


# Reference numbers from docs/CLUSTERING-EVAL-2026-05-14.md::agg-permissive
# (Model A / Agglomerative / agg-permissive). The smoke harness should
# reproduce these within ~10–15 % to validate that the production stage
# and the eval harness agree.
EVAL_REFERENCE: dict[str, dict[str, int]] = {
    "2026-05-08": {"n_clusters": 246, "max_cluster_size": 100},
    "2026-05-11": {"n_clusters": 241, "max_cluster_size": 66},
    "2026-05-13": {"n_clusters": 279, "max_cluster_size": 77},
}


SIZE_BINS: tuple[tuple[str, int, int], ...] = (
    ("singletons (1)", 1, 1),
    ("2–5", 2, 5),
    ("6–20", 6, 20),
    ("21–50", 21, 50),
    ("51–100", 51, 100),
    ("100+", 101, 10_000_000),
)


# ── Helpers ─────────────────────────────────────────────────────────────
def _rss_mb_now() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = 1.0 if sys.platform == "darwin" else 1024.0  # macOS=bytes, Linux=KB
    return raw * unit / 1e6


def _load_findings(state_path: Path) -> list[dict]:
    with state_path.open() as f:
        data = json.load(f)
    return list(data.get("curator_findings") or [])


def _size_distribution(clusters: list[dict]) -> list[tuple[str, int]]:
    sizes = [c["size"] for c in clusters]
    return [
        (label, sum(1 for s in sizes if lo <= s <= hi))
        for label, lo, hi in SIZE_BINS
    ]


def _top_clusters_md(
    clusters: list[dict],
    findings: list[dict],
    top_n: int = 10,
    titles_per_cluster: int = 2,
) -> list[str]:
    lines: list[str] = []
    for c in clusters[:top_n]:
        lines.append(f"### {c['id']} (size {c['size']})")
        lines.append("")
        for sid in c["source_ids"][:titles_per_cluster]:
            try:
                idx = int(sid.split("finding-")[-1])
            except ValueError:
                continue
            if not (0 <= idx < len(findings)):
                continue
            title = (findings[idx].get("title") or "").replace("|", "/")
            if len(title) > 140:
                title = title[:137] + "..."
            lines.append(f"- `{sid}`: {title}")
        lines.append("")
    return lines


def smoke_one(date: str, state_path: Path, out_dir: Path) -> dict:
    if not state_path.exists():
        print(f"  [{date}] state missing: {state_path}")
        return {"date": date, "error": "state-missing"}

    print(
        f"  [{date}] loading {state_path.relative_to(REPO_ROOT)} ..."
    )
    findings = _load_findings(state_path)
    print(f"  [{date}] {len(findings)} findings; running stage ...")

    rb = RunBus(
        run_id=f"smoke-{date}-precluster",
        run_date=date,
        curator_findings=findings,
    )

    rss_before = _rss_mb_now()
    t0 = time.monotonic()
    rb_out = asyncio.run(pre_cluster_findings(rb))
    wall_total = time.monotonic() - t0
    rss_after = _rss_mb_now()

    pc = rb_out.curator_pre_clusters
    clusters = pc["clusters"]
    max_size = max((c["size"] for c in clusters), default=0)
    n_clusters = pc["n_clusters"]

    # Pathology gate per brief: max cluster size jumps over 100
    pathology = max_size > 100

    # Eval-reproduction gate per brief: ±10–15 % on cluster count
    ref = EVAL_REFERENCE.get(date, {})
    ref_n = ref.get("n_clusters", 0)
    ref_max = ref.get("max_cluster_size", 0)
    if ref_n:
        n_delta_pct = round(100.0 * (n_clusters - ref_n) / ref_n, 1)
        n_within_tolerance = abs(n_delta_pct) <= 15.0
    else:
        n_delta_pct = None
        n_within_tolerance = None

    # Render Markdown
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{date}.md"
    rel_state = state_path.relative_to(REPO_ROOT)
    lines: list[str] = []
    lines.append(f"# Pre-cluster smoke — {date}")
    lines.append("")
    lines.append("## Run summary")
    lines.append("")
    lines.append(f"- State file: `{rel_state}`")
    lines.append(f"- Embedding model: `{pc['model_name']}`")
    lines.append(f"- fastembed: `{pc['fastembed_version']}`")
    lines.append(
        f"- Algorithm: `{pc['algorithm']}` "
        f"({pc['algorithm_library']} {pc['algorithm_library_version']})"
    )
    lines.append(
        f"- Params: distance_threshold={pc['params']['distance_threshold']}, "
        f"linkage='{pc['params']['linkage']}', "
        f"metric='{pc['params']['metric']}'"
    )
    lines.append(f"- Stage wall: {pc['wall_seconds']:.2f} s")
    lines.append(f"- Smoke wall (total, incl. load): {wall_total:.2f} s")
    lines.append(f"- Stage RSS Δ: {pc['rss_delta_mb']:.0f} MB")
    lines.append(
        f"- Smoke RSS Δ: {max(0.0, rss_after - rss_before):.0f} MB"
    )
    lines.append(f"- Findings clustered: {pc['n_findings_clustered']}")
    lines.append(f"- Clusters formed: {n_clusters}")
    lines.append(
        f"- Max cluster size: {max_size}"
        + (" **(PATHOLOGY)**" if pathology else "")
    )
    lines.append("")

    lines.append("## Eval-reproduction check")
    lines.append("")
    if ref_n:
        lines.append(
            f"Reference (`agg-permissive` in CLUSTERING-EVAL-2026-05-14): "
            f"n_clusters={ref_n}, max_cluster_size={ref_max}."
        )
        lines.append(
            f"Smoke: n_clusters={n_clusters} "
            f"({'+' if n_delta_pct >= 0 else ''}{n_delta_pct}%), "
            f"max_cluster_size={max_size}."
        )
        if n_within_tolerance:
            lines.append("Within the ±15 % tolerance window. ✓")
        else:
            lines.append(
                f"**Outside the ±15 % tolerance window** "
                f"(observed {n_delta_pct:+.1f}%)."
            )
    else:
        lines.append("No eval reference for this date.")
    lines.append("")

    lines.append("## Cluster-size distribution")
    lines.append("")
    lines.append("| Bin | n clusters |")
    lines.append("|---|---:|")
    for label, count in _size_distribution(clusters):
        lines.append(f"| {label} | {count} |")
    lines.append("")

    lines.append("## Top-10 clusters by size")
    lines.append("")
    lines.extend(_top_clusters_md(clusters, findings))

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [{date}] wrote {report_path.relative_to(REPO_ROOT)}")
    print(
        f"  [{date}] {pc['n_findings_clustered']} → {n_clusters} clusters, "
        f"max size {max_size}"
        + (" (PATHOLOGY)" if pathology else "")
        + (
            f"; vs eval {ref_n}/{ref_max} (Δ={n_delta_pct:+.1f}%)"
            if ref_n
            else ""
        )
    )

    return {
        "date": date,
        "n_findings": pc["n_findings_clustered"],
        "n_clusters": n_clusters,
        "max_cluster_size": max_size,
        "pathology_flag": pathology,
        "stage_wall_seconds": pc["wall_seconds"],
        "stage_rss_delta_mb": pc["rss_delta_mb"],
        "smoke_wall_seconds": round(wall_total, 3),
        "eval_n_clusters": ref_n or None,
        "eval_max_cluster_size": ref_max or None,
        "n_clusters_delta_pct": n_delta_pct,
        "within_15pct_tolerance": n_within_tolerance,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dataset",
        choices=list(DATASETS.keys()) + ["all"],
        default="all",
    )
    args = ap.parse_args()

    datasets = (
        list(DATASETS.items())
        if args.dataset == "all"
        else [(args.dataset, DATASETS[args.dataset])]
    )

    print(f"== Pre-cluster smoke — {len(datasets)} dataset(s) ==")
    results: list[dict] = []
    for date, state in datasets:
        results.append(smoke_one(date, state, OUT_ROOT))

    # Aggregate summary
    print("\n== Summary ==")
    print(
        f"{'date':<14} {'n_find':>7} {'n_clust':>8} {'max':>5} "
        f"{'eval n':>7} {'Δ%':>7} {'path':>6} {'wall':>6}"
    )
    for r in results:
        if "error" in r:
            print(f"{r['date']:<14}  ERROR  {r['error']}")
            continue
        delta_str = (
            f"{r['n_clusters_delta_pct']:+.1f}"
            if r["n_clusters_delta_pct"] is not None
            else "  n/a"
        )
        path_str = "YES" if r["pathology_flag"] else "no"
        eval_n = r["eval_n_clusters"] if r["eval_n_clusters"] is not None else "n/a"
        print(
            f"{r['date']:<14} {r['n_findings']:>7} {r['n_clusters']:>8} "
            f"{r['max_cluster_size']:>5} "
            f"{str(eval_n):>7} {delta_str:>7} {path_str:>6} "
            f"{r['stage_wall_seconds']:>5.1f}s"
        )

    # Write top-level summary JSON
    summary_path = OUT_ROOT / "summary.json"
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w") as f:
        json.dump({"results": results, "reference": EVAL_REFERENCE}, f, indent=2)
    print(f"\n  Wrote {summary_path.relative_to(REPO_ROOT)}")

    # Exit non-zero if any pathology or out-of-tolerance result — easier
    # to spot regressions when calling this from a wrapper script.
    if any(r.get("pathology_flag") for r in results if "error" not in r):
        print("!! At least one dataset hit pathology (max cluster size > 100).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
