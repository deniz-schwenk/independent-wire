"""Retroactive calibration: run the passive coherence stage against a
historical CuratorStage state file, then derive a precision/recall/F1
ROC against the dynamic on-topic regex from ``src/curator_metrics.py``.

Required reading: TASK-COHERENCE-FILTER-PASSIVE.md §"V1-baseline
calibration". The architect reads the produced report on day 3 to decide
whether to activate filtering and at what threshold.

Default invocation reproduces the V1 baseline result:

    python scripts/coherence_calibrate.py

Custom state + output:

    python scripts/coherence_calibrate.py \\
        --state output/{date}/_state/run-{date}-{hex}/run_bus.CuratorStage.json \\
        --output docs/coherence-filter/_calibration-{date}.md

When a CSV exists at the documented manual-labels path, the script adds
a parallel ROC against manual labels. Otherwise it notes that manual
validation is pending and ships the regex-only analysis.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import Optional

from src.bus import RunBus
from src.curator_metrics import derive_on_topic_regex
from src.stages.coherence import (
    FastembedEmbedder,
    THRESHOLD_BANDS,
    _all_scores,
    _finding_index_from_source_id,
    _histogram_bars,
    make_measure_cluster_coherence,
)


DEFAULT_STATE = (
    "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/"
    "run_bus.CuratorStage.json"
)
DEFAULT_OUTPUT = "docs/coherence-filter/_calibration-v1-baseline.md"
DEFAULT_MANUAL_LABELS = "docs/coherence-filter/_manual-labels-2026-05-11.csv"


# ---------------------------------------------------------------------------
# Labelling
# ---------------------------------------------------------------------------


def _label_with_regex(findings: list[dict], cluster: dict) -> dict[str, bool]:
    """Return ``{source_id: is_on_topic}`` for every source_id in the cluster.

    Heuristic per the brief: ``~5-10 %`` FP/FN, directional not absolute.
    The regex is derived from the cluster's own title + summary and
    matches against finding title + summary + description.
    """
    pattern, _tokens = derive_on_topic_regex(
        cluster.get("title") or "", cluster.get("summary") or ""
    )
    labels: dict[str, bool] = {}
    for sid in cluster.get("source_ids") or []:
        idx = _finding_index_from_source_id(sid)
        if idx is None or not (0 <= idx < len(findings)):
            continue
        if pattern is None:
            labels[sid] = False
            continue
        f = findings[idx]
        text = " ".join([
            f.get("title") or "",
            f.get("summary") or "",
            f.get("description") or "",
        ])
        labels[sid] = pattern.search(text) is not None
    return labels


def _load_manual_labels(path: Path) -> Optional[dict[str, bool]]:
    """Read manual-label CSV rows. Schema per TASK-COHERENCE-MANUAL-LABELS-V1:

        finding_id, is_on_topic, reasoning_note

    Returns ``{finding_id: is_on_topic_bool}`` or ``None`` if the file is
    absent. The CSV is target-cluster scoped by construction — the caller
    filters by intersecting with the target cluster's ``source_ids``.
    """
    if not path.exists():
        return None
    labels: dict[str, bool] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sid = (row.get("finding_id") or "").strip()
            raw_label = (row.get("is_on_topic") or "").strip().lower()
            if not sid or raw_label not in {"1", "0"}:
                continue
            labels[sid] = raw_label == "1"
    return labels or None


def _agreement_matrix(
    regex_labels: dict[str, bool],
    manual_labels: dict[str, bool],
) -> dict:
    """2×2 confusion of regex vs manual on the manual-labelled subset.

    Cells:
      - ``rr_on_mm_on``  — regex on,  manual on  (agree, both on-topic)
      - ``rr_off_mm_off`` — regex off, manual off (agree, both off-topic)
      - ``rr_on_mm_off`` — regex on,  manual off (regex over-counts)
      - ``rr_off_mm_on`` — regex off, manual on  (regex under-counts)
    """
    cells = {
        "rr_on_mm_on": [],
        "rr_off_mm_off": [],
        "rr_on_mm_off": [],
        "rr_off_mm_on": [],
    }
    n = 0
    for sid, mm in manual_labels.items():
        if sid not in regex_labels:
            continue
        rr = regex_labels[sid]
        if rr and mm:
            cells["rr_on_mm_on"].append(sid)
        elif (not rr) and (not mm):
            cells["rr_off_mm_off"].append(sid)
        elif rr and (not mm):
            cells["rr_on_mm_off"].append(sid)
        else:
            cells["rr_off_mm_on"].append(sid)
        n += 1
    agreement = (
        len(cells["rr_on_mm_on"]) + len(cells["rr_off_mm_off"])
    ) / n if n else 0.0
    return {
        "n": n,
        "agreement": agreement,
        "rr_on_mm_on": cells["rr_on_mm_on"],
        "rr_off_mm_off": cells["rr_off_mm_off"],
        "rr_on_mm_off": cells["rr_on_mm_off"],
        "rr_off_mm_on": cells["rr_off_mm_on"],
    }


# ---------------------------------------------------------------------------
# ROC
# ---------------------------------------------------------------------------


def _confusion_matrix(
    scores_by_sid: dict[str, float],
    labels: dict[str, bool],
    threshold: float,
) -> dict[str, int]:
    """Score >= threshold → predicted-positive ("would be kept").
    Score < threshold → predicted-negative ("would be dropped")."""
    tp = fp = fn = tn = 0
    for sid, label in labels.items():
        score = scores_by_sid.get(sid)
        if score is None:
            continue
        predicted_positive = score >= threshold
        if predicted_positive and label:
            tp += 1
        elif predicted_positive and not label:
            fp += 1
        elif not predicted_positive and label:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _precision_recall_f1(cm: dict[str, int]) -> dict[str, float]:
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def _roc_table(
    scores_by_sid: dict[str, float],
    labels: dict[str, bool],
) -> list[dict]:
    rows: list[dict] = []
    for t in THRESHOLD_BANDS:
        cm = _confusion_matrix(scores_by_sid, labels, t)
        prf = _precision_recall_f1(cm)
        rows.append({
            "threshold": t,
            **cm,
            **prf,
        })
    return rows


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def _format_roc_table(title: str, rows: list[dict]) -> list[str]:
    out: list[str] = []
    out.append(f"### {title}")
    out.append("")
    out.append(
        "| threshold | TP | FP | FN | TN | precision | recall | F1 |"
    )
    out.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    best_f1_idx = max(range(len(rows)), key=lambda i: rows[i]["f1"]) if rows else None
    for i, r in enumerate(rows):
        mark = " ←" if i == best_f1_idx else ""
        out.append(
            f"| {r['threshold']:.2f} | {r['tp']} | {r['fp']} | {r['fn']} | "
            f"{r['tn']} | {r['precision']:.3f} | {r['recall']:.3f} | "
            f"{r['f1']:.3f}{mark} |"
        )
    if best_f1_idx is not None:
        best = rows[best_f1_idx]
        out.append("")
        out.append(
            f"Best F1 at threshold {best['threshold']:.2f}: "
            f"precision={best['precision']:.3f}, recall={best['recall']:.3f}, "
            f"F1={best['f1']:.3f}"
        )
    out.append("")
    return out


def write_calibration_report(
    output_path: Path,
    *,
    state_path: Path,
    coherence: dict,
    findings: list[dict],
    topics: list[dict],
    target_cluster_idx: int,
    regex_roc: list[dict],
    manual_roc: Optional[list[dict]] = None,
    manual_labels_path: Optional[Path] = None,
    agreement: Optional[dict] = None,
    scores_by_sid: Optional[dict[str, float]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_cluster = topics[target_cluster_idx]
    cluster_score_row = next(
        (c for c in coherence["clusters"] if c["cluster_index"] == target_cluster_idx),
        None,
    )

    lines: list[str] = []
    lines.append("# Coherence-stage calibration — V1 baseline")
    lines.append("")
    lines.append(f"- Source state: `{state_path}`")
    lines.append(f"- Model: `{coherence.get('model_name')}`")
    lines.append(
        f"- fastembed version (pinned): `{coherence.get('fastembed_version')}`"
    )
    lines.append(f"- Wall: {coherence.get('wall_seconds', 0.0):.2f} s")
    lines.append(f"- RSS Δ: {coherence.get('rss_delta_mb', 0.0):.0f} MB")
    lines.append(f"- Clusters scored: {coherence.get('n_clusters_scored', 0)}")
    lines.append(f"- Findings scored: {coherence.get('n_findings_scored', 0)}")
    lines.append("")

    lines.append("## Per-cluster aggregates")
    lines.append("")
    thresholds = coherence.get("thresholds") or []
    th_headers = " | ".join(f"<{t:.2f}" for t in thresholds)
    th_dashes = "|".join("---:" for _ in thresholds)
    lines.append(
        "| Cluster | n | mean | median | p10 | p90 | min | max | "
        + th_headers + " |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|" + th_dashes + "|")
    for c in coherence.get("clusters") or []:
        agg = c.get("aggregates") or {}
        btc = c.get("below_threshold_counts") or {}
        th_cells = " | ".join(str(btc.get(f"{t:.2f}", 0)) for t in thresholds)
        title = (c.get("cluster_title") or "").replace("|", "/")
        if len(title) > 80:
            title = title[:77] + "..."
        lines.append(
            f"| {title} | {c.get('n_findings', 0)} | "
            f"{agg.get('mean', 0.0):.3f} | {agg.get('median', 0.0):.3f} | "
            f"{agg.get('p10', 0.0):.3f} | {agg.get('p90', 0.0):.3f} | "
            f"{agg.get('min', 0.0):.3f} | {agg.get('max', 0.0):.3f} | "
            f"{th_cells} |"
        )
    lines.append("")

    lines.append("## Aggregate score histogram (all clusters, all findings)")
    lines.append("")
    lines.append("```")
    lines.extend(_histogram_bars(_all_scores(coherence)))
    lines.append("```")
    lines.append("")

    # Target-cluster ROC section
    lines.append("## Target-cluster ROC")
    lines.append("")
    lines.append(
        f"- Target cluster (index {target_cluster_idx}): "
        f"`{target_cluster.get('title', '')}`"
    )
    if cluster_score_row:
        lines.append(f"- n_findings: {cluster_score_row.get('n_findings', 0)}")
        agg = cluster_score_row.get("aggregates") or {}
        lines.append(
            f"- score distribution: mean={agg.get('mean', 0.0):.3f}, "
            f"median={agg.get('median', 0.0):.3f}, "
            f"p10={agg.get('p10', 0.0):.3f}, p90={agg.get('p90', 0.0):.3f}"
        )
    lines.append("")

    lines.extend(_format_roc_table(
        "ROC against the dynamic on-topic regex (`src/curator_metrics.py`)",
        regex_roc,
    ))
    lines.append(
        "Regex is the heuristic baseline per the brief: ~5–10% FP/FN, "
        "directional not absolute. The regex is derived from the target "
        "cluster's own title + summary, then matched against each "
        "finding's title + summary + description."
    )
    lines.append("")

    if manual_roc is not None:
        lines.extend(_format_roc_table(
            "ROC against manual labels (`" + str(manual_labels_path) + "`)",
            manual_roc,
        ))
        lines.append(
            "Manual labels are the ground-truth reference. When regex "
            "and manual ROCs agree on the best-F1 threshold, the regex "
            "heuristic is validated for this dataset."
        )
        lines.append("")
        # Confusion matrix at best-F1 threshold for manual labels
        if manual_roc and scores_by_sid is not None:
            best = max(manual_roc, key=lambda r: r["f1"])
            lines.append(
                f"#### Confusion matrix at F1-optimal manual threshold "
                f"({best['threshold']:.2f})"
            )
            lines.append("")
            lines.append("|  | predicted-keep | predicted-drop |")
            lines.append("|---|---:|---:|")
            lines.append(
                f"| manual on  | {best['tp']} (TP) | {best['fn']} (FN) |"
            )
            lines.append(
                f"| manual off | {best['fp']} (FP) | {best['tn']} (TN) |"
            )
            lines.append("")
    else:
        lines.append("### Manual-label ROC")
        lines.append("")
        lines.append(
            f"Manual validation is pending. No CSV found at "
            f"`{manual_labels_path or DEFAULT_MANUAL_LABELS}`. Once labels "
            "exist, re-run this script to add a parallel ROC."
        )
        lines.append("")

    if agreement is not None:
        lines.append("## Agreement matrix: regex vs manual labels")
        lines.append("")
        lines.append(
            f"On the {agreement['n']}-finding manual-label subset, regex "
            f"and manual judgement **agree on "
            f"{len(agreement['rr_on_mm_on']) + len(agreement['rr_off_mm_off'])}"
            f"/{agreement['n']} findings ({agreement['agreement']:.1%})**."
        )
        lines.append("")
        lines.append("|  | manual on | manual off |")
        lines.append("|---|---:|---:|")
        lines.append(
            f"| regex on  | {len(agreement['rr_on_mm_on'])} (both on) | "
            f"{len(agreement['rr_on_mm_off'])} (regex over-counts) |"
        )
        lines.append(
            f"| regex off | {len(agreement['rr_off_mm_on'])} (regex under-counts) | "
            f"{len(agreement['rr_off_mm_off'])} (both off) |"
        )
        lines.append("")
        if agreement["rr_on_mm_off"]:
            lines.append("**Regex says on-topic, manual says off-topic:**")
            for sid in agreement["rr_on_mm_off"]:
                idx = _finding_index_from_source_id(sid)
                tl = ""
                if idx is not None and 0 <= idx < len(findings):
                    tl = (findings[idx].get("title") or "")[:160]
                lines.append(f"- `{sid}` — {tl}")
            lines.append("")
        if agreement["rr_off_mm_on"]:
            lines.append("**Regex says off-topic, manual says on-topic:**")
            for sid in agreement["rr_off_mm_on"]:
                idx = _finding_index_from_source_id(sid)
                tl = ""
                if idx is not None and 0 <= idx < len(findings):
                    tl = (findings[idx].get("title") or "")[:160]
                lines.append(f"- `{sid}` — {tl}")
            lines.append("")
        lines.append(
            "Reading: regex agrees with manual labels in the majority. "
            "Disagreements are the heuristic's failure modes — regex "
            "over-counts when peripheral lexical matches creep into the "
            "vocabulary; regex under-counts when on-topic findings phrase "
            "the topic in vocabulary that didn't make the regex tokens. "
            "The agreement rate tells the architect how much trust to "
            "place in the daily regex-only comparator on the coherence "
            "report."
        )
        lines.append("")

    lines.append("## Reading guide")
    lines.append("")
    lines.append(
        "- TP = on-topic finding that would be kept (score ≥ threshold)"
    )
    lines.append(
        "- FP = off-topic finding that would be kept (= leakage; want low)"
    )
    lines.append(
        "- FN = on-topic finding that would be dropped (= regression; want low)"
    )
    lines.append("- TN = off-topic finding that would be dropped (= win)")
    lines.append(
        "- Best F1 marks the threshold balancing leakage vs regression."
    )
    lines.append(
        "- Single-cluster ROC: directional indicator, not final calibration. "
        "Cross-cluster sweep + multi-day production data make the final case."
    )
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _largest_cluster_index(topics: list[dict]) -> int:
    if not topics:
        return 0
    return max(
        range(len(topics)),
        key=lambda i: len(topics[i].get("source_ids") or []),
    )


async def _run_coherence(state: dict) -> tuple[dict, list[dict], list[dict]]:
    findings = state.get("curator_findings") or []
    topics = state.get("curator_topics_unsliced") or []
    rb = RunBus(
        run_id="run-calibration-2026-05-11",
        run_date="2026-05-11",
        curator_findings=findings,
        curator_topics_unsliced=topics,
        curator_topics=topics,
    )
    stage = make_measure_cluster_coherence(
        embedder=FastembedEmbedder(), write_report=False
    )
    out = await stage(rb)
    return out.curator_coherence_scores, list(rb.curator_findings), list(rb.curator_topics_unsliced)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--manual-labels", default=DEFAULT_MANUAL_LABELS,
        help="CSV with cluster_index,source_id,label (label in {on,off,1,0})",
    )
    parser.add_argument(
        "--target-cluster",
        type=int,
        default=None,
        help="Cluster index for the ROC. Defaults to the largest cluster.",
    )
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        raise SystemExit(f"state file not found: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))

    coherence, findings, topics = asyncio.run(_run_coherence(state))

    target_idx = (
        args.target_cluster
        if args.target_cluster is not None
        else _largest_cluster_index(topics)
    )
    target_cluster = topics[target_idx]
    cluster_score_row = next(
        c for c in coherence["clusters"] if c["cluster_index"] == target_idx
    )

    scores_by_sid = {
        fs["source_id"]: float(fs["score"])
        for fs in cluster_score_row["finding_scores"]
    }
    regex_labels = _label_with_regex(findings, target_cluster)
    regex_roc = _roc_table(scores_by_sid, regex_labels)

    manual_labels_path = Path(args.manual_labels)
    manual_labels = _load_manual_labels(manual_labels_path)
    # CSV is target-cluster scoped by construction (TASK-COHERENCE-
    # MANUAL-LABELS-V1) — filter to the subset that the target cluster
    # actually contains, so agreement and ROC are computed on the
    # well-defined intersection.
    target_source_id_set = {sid for sid in (target_cluster.get("source_ids") or [])}
    if manual_labels is not None:
        manual_labels = {
            sid: label for sid, label in manual_labels.items()
            if sid in target_source_id_set
        }
        if not manual_labels:
            manual_labels = None
    manual_roc = (
        _roc_table(scores_by_sid, manual_labels) if manual_labels else None
    )
    agreement = (
        _agreement_matrix(regex_labels, manual_labels) if manual_labels else None
    )

    write_calibration_report(
        Path(args.output),
        state_path=state_path,
        coherence=coherence,
        findings=findings,
        topics=topics,
        target_cluster_idx=target_idx,
        regex_roc=regex_roc,
        manual_roc=manual_roc,
        manual_labels_path=manual_labels_path,
        agreement=agreement,
        scores_by_sid=scores_by_sid,
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
