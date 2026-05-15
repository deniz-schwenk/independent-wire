"""Smoke harness for ``src/stages/gravitational_assign.py``.

Authoritative reference: TASK-GRAVITATIONAL-ASSIGN-STAGE.md §"Smoke harness".

Runs the production gravitational-assign stage against the three
clustering-eval state files (2026-05-08, 2026-05-11-v1-baseline,
2026-05-13) using each day's V1 Curator topics as topic-centre proxies.
Writes one Markdown summary per dataset plus a summary.json under
``docs/gravitational-assign/smoke-2026-05-15/``. Architect's pre-
integration sanity check that:
  - The orphan rate + assignments-per-finding distribution observed
    in production agree with the calibration measurements at the same
    threshold and cap.
  - For the labelled clusters (the six (date, cluster_idx) pairs the
    ground-truth set covers), the per-cluster confusion matrix at the
    chosen threshold matches the calibration's expectations.

Not wired into the pipeline; not part of CI.

Usage:
    python scripts/smoke_gravitational_assign.py
    python scripts/smoke_gravitational_assign.py --dataset 2026-05-13
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import resource
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bus import RunBus  # noqa: E402
from src.stages.gravitational_assign import (  # noqa: E402
    GRAVITATIONAL_THRESHOLD,
    PER_FINDING_CAP,
    TIE_BREAK_RULE,
    gravitational_assign,
)


DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}


LABEL_ROOT = REPO_ROOT / "docs" / "coherence-filter" / "manual-labels"

# Labelled-cluster index per date. Aligned with the eval and calibration harnesses.
DATE_LABEL_MAP: dict[str, list[tuple[int, tuple[str, ...], str]]] = {
    "2026-05-11": [
        (0, ("cluster-0.csv", "cluster-0-ext.csv"), "Iran mega-cluster"),
        (1, ("cluster-1.csv",), "Hantavirus"),
        (3, ("cluster-3.csv",), "Russia-Ukraine"),
    ],
    "2026-05-13": [
        (1, ("cluster-1.csv", "cluster-1-ext.csv"), "Iran-war"),
        (0, ("cluster-0.csv",), "Trump-Xi"),
        (11, ("cluster-11.csv",), "Sudan"),
    ],
}


OUT_ROOT = REPO_ROOT / "docs" / "gravitational-assign" / "smoke-2026-05-15"


# ── Helpers ─────────────────────────────────────────────────────────────
def _rss_mb_now() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = 1.0 if sys.platform == "darwin" else 1024.0
    return raw * unit / 1e6


def _load_state(state_path: Path) -> tuple[list[dict], list[dict]]:
    with state_path.open() as f:
        data = json.load(f)
    return (
        list(data.get("curator_findings") or []),
        list(data.get("curator_topics_unsliced") or []),
    )


def _load_labels(date: str, csv_names: tuple[str, ...]) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in csv_names:
        with (LABEL_ROOT / date / name).open(newline="") as f:
            for row in csv.DictReader(f):
                out[row["finding_id"]] = int(row["is_on_topic"])
    return out


def _assignments_per_finding_histogram(ca: dict) -> dict[str, int]:
    n = ca["n_findings"]
    if not n:
        return {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
    counts = [0] * n
    for topic in ca["topics"]:
        for a in topic["assignments"]:
            fi = int(a["source_id"].split("finding-")[-1])
            if 0 <= fi < n:
                counts[fi] += 1
    bins = Counter()
    for c in counts:
        if c >= 4:
            bins["4+"] += 1
        else:
            bins[str(c)] += 1
    return {k: int(bins.get(k, 0)) for k in ("0", "1", "2", "3", "4+")}


def _per_topic_stats(ca: dict, top_n: int = 10) -> list[dict]:
    rows = []
    for topic in ca["topics"]:
        sims = [a["similarity"] for a in topic["assignments"]]
        rows.append({
            "topic_index": topic["topic_index"],
            "topic_title": topic["topic_title"],
            "n_assigned": topic["n_assigned"],
            "mean_sim": round(sum(sims) / len(sims), 4) if sims else None,
            "min_sim": min(sims) if sims else None,
            "max_sim": max(sims) if sims else None,
        })
    rows.sort(key=lambda r: -r["n_assigned"])
    return rows[:top_n]


def _confusion_matrix(
    ca: dict,
    date: str,
    cluster_idx: int,
    labels: dict[str, int],
) -> dict:
    """For a labelled cluster: among the labelled findings, what's the
    predicted vs actual on-topic split at the production threshold?

    The 'predicted on-topic' set is the set of finding-IDs the stage
    assigned to topic cluster_idx. The confusion matrix counts how that
    overlaps with the labelled on/off ground truth."""
    # Stage's predicted on-topic set for this cluster
    predicted_on: set[str] = set()
    for topic in ca["topics"]:
        if topic["topic_index"] == cluster_idx:
            predicted_on = {a["source_id"] for a in topic["assignments"]}
            break

    tp = fp = fn = tn = 0
    for fid, lab in labels.items():
        if fid in predicted_on and lab == 1:
            tp += 1
        elif fid in predicted_on and lab == 0:
            fp += 1
        elif fid not in predicted_on and lab == 1:
            fn += 1
        else:
            tn += 1
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {
        "n_labels": len(labels),
        "n_labels_on_topic": sum(1 for v in labels.values() if v == 1),
        "n_predicted_on_topic": tp + fp,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
    }


def smoke_one(date: str, state_path: Path, out_dir: Path) -> dict:
    if not state_path.exists():
        print(f"  [{date}] state missing: {state_path}")
        return {"date": date, "error": "state-missing"}

    findings, topics = _load_state(state_path)
    print(f"  [{date}] {len(findings)} findings × {len(topics)} topics; running stage ...")

    rb = RunBus(
        run_id=f"smoke-{date}-grav",
        run_date=date,
        curator_findings=findings,
        curator_topics_unsliced=topics,
    )

    rss_before = _rss_mb_now()
    t0 = time.monotonic()
    rb_out = asyncio.run(gravitational_assign(rb))
    wall_total = time.monotonic() - t0
    rss_after = _rss_mb_now()

    ca = rb_out.curator_topic_assignments
    hist = _assignments_per_finding_histogram(ca)
    top_topics = _per_topic_stats(ca, top_n=10)

    # Per-labelled-cluster confusion matrices
    per_cluster_cm: list[dict] = []
    if date in DATE_LABEL_MAP:
        for cluster_idx, csv_names, cname in DATE_LABEL_MAP[date]:
            labels = _load_labels(date, csv_names)
            cm = _confusion_matrix(ca, date, cluster_idx, labels)
            per_cluster_cm.append({
                "cluster_idx": cluster_idx,
                "cluster_label": cname,
                **cm,
            })

    # Render Markdown
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{date}.md"
    rel_state = state_path.relative_to(REPO_ROOT)

    lines: list[str] = []
    lines.append(f"# Gravitational-assign smoke — {date}")
    lines.append("")
    lines.append("## Run summary")
    lines.append("")
    lines.append(f"- State file: `{rel_state}`")
    lines.append(f"- Embedding model: `{ca['model_name']}`")
    lines.append(f"- fastembed: `{ca['fastembed_version']}`")
    lines.append(f"- Library: `{ca['algorithm_library']} {ca['algorithm_library_version']}`")
    lines.append(
        f"- Params: threshold={ca['params']['gravitational_threshold']}, "
        f"cap={ca['params']['per_finding_cap']}, tie-break='{ca['params']['tie_break']}'"
    )
    lines.append(f"- Stage wall: {ca['wall_seconds']:.2f} s")
    lines.append(f"- Smoke wall (total): {wall_total:.2f} s")
    lines.append(f"- Stage RSS Δ: {ca['rss_delta_mb']:.0f} MB")
    lines.append(f"- Smoke RSS Δ: {max(0.0, rss_after - rss_before):.0f} MB")
    lines.append(f"- Topics: {ca['n_topics']}")
    lines.append(f"- Findings: {ca['n_findings']}")
    lines.append(f"- Findings assigned: {ca['n_findings_assigned']}")
    lines.append(f"- Orphans: {ca['n_orphans']} "
                 f"({round(100 * ca['n_orphans'] / max(1, ca['n_findings']), 1)} %)")
    lines.append(f"- Mean assignments / finding: {ca['mean_assignments_per_finding']}")
    lines.append("")

    lines.append("## Assignments-per-finding histogram")
    lines.append("")
    lines.append("| n_topics_assigned | n_findings |")
    lines.append("|---|---:|")
    for k in ("0", "1", "2", "3", "4+"):
        lines.append(f"| {k} | {hist[k]} |")
    lines.append("")

    lines.append("## Top-10 topics by n_assigned")
    lines.append("")
    lines.append("| topic_index | n_assigned | mean_sim | min_sim | max_sim | title |")
    lines.append("|---:|---:|---:|---:|---:|---|")
    for r in top_topics:
        title = (r["topic_title"] or "").replace("|", "/")
        if len(title) > 80:
            title = title[:77] + "..."
        ms = f"{r['mean_sim']:.3f}" if r["mean_sim"] is not None else "—"
        mns = f"{r['min_sim']:.3f}" if r["min_sim"] is not None else "—"
        mxs = f"{r['max_sim']:.3f}" if r["max_sim"] is not None else "—"
        lines.append(
            f"| {r['topic_index']} | {r['n_assigned']} | {ms} | {mns} | {mxs} | {title} |"
        )
    lines.append("")

    if per_cluster_cm:
        lines.append("## Per-labelled-cluster confusion matrix at production threshold")
        lines.append("")
        lines.append(f"At threshold {GRAVITATIONAL_THRESHOLD} (cap={PER_FINDING_CAP}). "
                     f"Predicted on-topic = stage assigned the finding to this cluster.")
        lines.append("")
        lines.append("| Cluster | n_labels | label on | predict on | TP | FP | FN | TN | P | R | F1 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in per_cluster_cm:
            lines.append(
                f"| {r['cluster_label']} | {r['n_labels']} | "
                f"{r['n_labels_on_topic']} | {r['n_predicted_on_topic']} | "
                f"{r['tp']} | {r['fp']} | {r['fn']} | {r['tn']} | "
                f"{r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} |"
            )
        lines.append("")
    else:
        lines.append("## Per-labelled-cluster confusion matrix")
        lines.append("")
        lines.append("No manual labels for this date — confusion matrix omitted.")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [{date}] wrote {report_path.relative_to(REPO_ROOT)}")
    print(
        f"  [{date}] {ca['n_findings_assigned']} assigned, {ca['n_orphans']} orphans "
        f"({round(100 * ca['n_orphans'] / max(1, ca['n_findings']), 1)} % orphan), "
        f"mean {ca['mean_assignments_per_finding']:.3f}"
    )

    return {
        "date": date,
        "n_findings": ca["n_findings"],
        "n_topics": ca["n_topics"],
        "n_findings_assigned": ca["n_findings_assigned"],
        "n_orphans": ca["n_orphans"],
        "orphan_pct": round(100 * ca["n_orphans"] / max(1, ca["n_findings"]), 2),
        "mean_assignments_per_finding": ca["mean_assignments_per_finding"],
        "assignments_per_finding_histogram": hist,
        "per_cluster_confusion": per_cluster_cm,
        "stage_wall_seconds": ca["wall_seconds"],
        "smoke_wall_seconds": round(wall_total, 3),
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

    print(f"== Gravitational-assign smoke — {len(datasets)} dataset(s) ==")
    print(
        f"   threshold={GRAVITATIONAL_THRESHOLD}, cap={PER_FINDING_CAP}, "
        f"tie-break='{TIE_BREAK_RULE}'"
    )
    results: list[dict] = []
    for date, state in datasets:
        results.append(smoke_one(date, state, OUT_ROOT))

    # Aggregate
    print("\n== Summary ==")
    print(f"{'date':<14} {'n_find':>7} {'n_top':>6} {'assn':>6} {'orph':>5} "
          f"{'orph%':>6} {'mean':>5}")
    for r in results:
        if "error" in r:
            print(f"{r['date']:<14}  ERROR  {r['error']}")
            continue
        print(
            f"{r['date']:<14} {r['n_findings']:>7} {r['n_topics']:>6} "
            f"{r['n_findings_assigned']:>6} {r['n_orphans']:>5} "
            f"{r['orphan_pct']:>5.1f}% {r['mean_assignments_per_finding']:>5.2f}"
        )

    summary_path = OUT_ROOT / "summary.json"
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w") as f:
        json.dump(
            {
                "threshold": GRAVITATIONAL_THRESHOLD,
                "cap": PER_FINDING_CAP,
                "tie_break_rule": TIE_BREAK_RULE,
                "results": results,
            },
            f,
            indent=2,
        )
    print(f"\n  Wrote {summary_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
