"""Calibration harness for the gravitational threshold + per-finding cap.

Authoritative reference: TASK-GRAVITATIONAL-ASSIGN-STAGE.md §Calibration.

Runs against the two labelled-day Curator state files:

    output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json
    output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json

For each day:
  1. Embed every finding via the fastembed singleton from coherence.py
     (Model A, paraphrase-multilingual-MiniLM-L12-v2, L2-normalised).
  2. Embed each cluster's ``title + summary`` (V1 headlines) — these are
     the topic-centre proxies pending Brief 4's real Stage-2 output.
  3. For the labelled (finding, cluster) pairs, compute cosine similarity
     between the finding and the cluster's headline embedding.
  4. As a cross-check (per brief's V1-noise hedge): build a finding-
     centroid alternative — mean of on-topic-labelled embeddings per
     cluster, L2-normalised — and recompute similarities.

For each threshold in 0.10 to 0.85 (step 0.05):
  - Per-cluster ROC: TP/FP/FN/TN, precision, recall, F1
  - Pooled ROC across all 504 labels (V1 headlines)
  - Pooled ROC under the finding-centroid alternative
  - Full-population assignments-per-finding distribution (0 / 1 / 2 / 3 / 4+)
  - Full-population orphan rate

Output:
  - output/eval/grav-calib-2026-05-15/calibration.json
    (raw data — the calibration report Markdown reads this)
  - output/eval/grav-calib-2026-05-15/embeddings/{date}/findings.npy
    (cached so re-runs are fast)

Usage:
    python scripts/calibrate_gravitational.py
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.stages.coherence import (  # noqa: E402
    FASTEMBED_VERSION_REQUIRED,
    MODEL_NAME,
    _cosine_normalized,
    _get_default_embedder,
)


# ── Configuration ───────────────────────────────────────────────────────
DATES: tuple[str, ...] = ("2026-05-11", "2026-05-13")

STATE_PATHS: dict[str, Path] = {
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}

LABEL_ROOT = REPO_ROOT / "docs" / "coherence-filter" / "manual-labels"

# (cluster_idx_in_curator_topics_unsliced, label_csv_basenames, cluster_label)
DATE_LABEL_MAP: dict[str, list[tuple[int, tuple[str, ...], str]]] = {
    "2026-05-11": [
        (0, ("cluster-0.csv", "cluster-0-ext.csv"),
         "Iran (1004 findings — mega-cluster)"),
        (1, ("cluster-1.csv",),
         "Hantavirus (8 findings)"),
        (3, ("cluster-3.csv",),
         "Russia-Ukraine (31 findings)"),
    ],
    "2026-05-13": [
        (1, ("cluster-1.csv", "cluster-1-ext.csv"),
         "Iran-war (180 findings)"),
        (0, ("cluster-0.csv",),
         "Trump-Xi (45 findings)"),
        (11, ("cluster-11.csv",),
         "Sudan (40 findings)"),
    ],
}

# Threshold sweep 0.10 to 0.85 by 0.05
THRESHOLDS: tuple[float, ...] = tuple(round(0.05 * i, 2) for i in range(2, 18))

OUT_ROOT = REPO_ROOT / "output" / "eval" / "grav-calib-2026-05-15"
EMBED_CACHE_ROOT = OUT_ROOT / "embeddings"


# ── Helpers ─────────────────────────────────────────────────────────────
def _finding_text(finding: dict) -> str:
    """Match the pre_cluster stage's concatenation rule for reproducibility
    against Brief 1's smoke + the clustering eval."""
    return (
        (finding.get("title") or "")
        + " "
        + (finding.get("summary") or "")
        + " "
        + (finding.get("description") or "")
    ).strip()


def _topic_text(topic: dict) -> str:
    """Production stage's topic-centre text. Must stay aligned with the
    rule the gravitational_assign stage uses or calibration drifts."""
    return ((topic.get("title") or "") + " " + (topic.get("summary") or "")).strip()


def _load_labels(date: str, csv_names: tuple[str, ...]) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in csv_names:
        with (LABEL_ROOT / date / name).open(newline="") as f:
            for row in csv.DictReader(f):
                out[row["finding_id"]] = int(row["is_on_topic"])
    return out


def _fid_to_index(fid: str) -> int:
    return int(fid.split("finding-")[-1])


def _embed_findings_cached(date: str, findings: list[dict]) -> np.ndarray:
    cache = EMBED_CACHE_ROOT / date / "findings.npy"
    if cache.exists():
        return np.load(cache).astype(np.float64)
    print(f"  [{date}] embedding {len(findings)} findings ...")
    t0 = time.monotonic()
    emb = _get_default_embedder()
    texts = [_finding_text(f) for f in findings]
    matrix = _cosine_normalized(emb.embed_batch(texts))
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, matrix.astype(np.float32))
    print(f"  [{date}] embedded in {time.monotonic() - t0:.1f}s")
    return matrix


def _embed_topics(topics: list[dict]) -> np.ndarray:
    emb = _get_default_embedder()
    texts = [_topic_text(t) for t in topics]
    return _cosine_normalized(emb.embed_batch(texts))


def _metrics(scores: list[float], labels: list[int], threshold: float) -> dict:
    """Precision / recall / F1 against ground truth at a single threshold."""
    tp = fp = fn = tn = 0
    for s, lab in zip(scores, labels):
        pred = 1 if s >= threshold else 0
        if pred == 1 and lab == 1:
            tp += 1
        elif pred == 1 and lab == 0:
            fp += 1
        elif pred == 0 and lab == 1:
            fn += 1
        else:
            tn += 1
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {
        "n": tp + fp + fn + tn,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
    }


def _assignments_per_finding_dist(
    sim_matrix: np.ndarray, threshold: float
) -> dict[str, int]:
    """How many topics each finding exceeds the threshold for, binned."""
    counts = (sim_matrix >= threshold).sum(axis=1)
    return {
        "0": int((counts == 0).sum()),
        "1": int((counts == 1).sum()),
        "2": int((counts == 2).sum()),
        "3": int((counts == 3).sum()),
        "4+": int((counts >= 4).sum()),
    }


def _orphan_rate(sim_matrix: np.ndarray, threshold: float) -> float:
    n_total = sim_matrix.shape[0]
    if not n_total:
        return 0.0
    n_orphans = int((sim_matrix.max(axis=1) < threshold).sum())
    return round(n_orphans / n_total, 4)


# ── Main ────────────────────────────────────────────────────────────────
def calibrate() -> dict:
    """Run the full calibration sweep. Returns a dict with raw data the
    Markdown report will consume."""
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Pooled label rows across both days (one entry per labelled
    # (finding, cluster) pair).
    pooled_v1_rows: list[tuple[str, int, str, int, float, int]] = []
    pooled_centroid_rows: list[tuple[str, int, str, int, float, int]] = []

    # Per-cluster row containers indexed by (date, cluster_idx).
    per_cluster_v1_rows: dict[tuple[str, int], list[tuple[float, int]]] = {}
    per_cluster_centroid_rows: dict[tuple[str, int], list[tuple[float, int]]] = {}

    # Per-date population data for assignments-per-finding + orphan-rate.
    population: dict[str, dict] = {}

    # Cluster label metadata for the report.
    cluster_meta: dict[tuple[str, int], dict] = {}

    for date in DATES:
        state = json.load(STATE_PATHS[date].open())
        findings = state.get("curator_findings") or []
        topics = state.get("curator_topics_unsliced") or []

        finding_matrix = _embed_findings_cached(date, findings)
        topic_v1_matrix = _embed_topics(topics)

        # Population similarity matrix — (n_findings, n_topics)
        pop_sim_v1 = (finding_matrix @ topic_v1_matrix.T).astype(np.float64)
        population[date] = {
            "n_findings": len(findings),
            "n_topics": len(topics),
            "sim_v1_summary": {
                "min": float(pop_sim_v1.min()),
                "max": float(pop_sim_v1.max()),
                "mean": float(pop_sim_v1.mean()),
            },
        }
        # Persist population sims so the report can interrogate them later.
        np.save(EMBED_CACHE_ROOT / date / "population_sims_v1.npy", pop_sim_v1.astype(np.float32))

        # Process labelled clusters
        labelled: dict[int, tuple[dict[str, int], str]] = {}
        for cluster_idx, csv_names, cname in DATE_LABEL_MAP[date]:
            labels_dict = _load_labels(date, csv_names)
            labelled[cluster_idx] = (labels_dict, cname)

            n_on = sum(1 for v in labels_dict.values() if v == 1)
            n_off = sum(1 for v in labels_dict.values() if v == 0)
            cluster_meta[(date, cluster_idx)] = {
                "cluster_idx": cluster_idx,
                "cluster_label": cname,
                "title": topics[cluster_idx].get("title", ""),
                "summary": (topics[cluster_idx].get("summary") or "")[:240],
                "n_labels": len(labels_dict),
                "n_on": n_on,
                "n_off": n_off,
            }

            topic_vec_v1 = topic_v1_matrix[cluster_idx]
            for fid, lab in labels_dict.items():
                fi = _fid_to_index(fid)
                if not (0 <= fi < len(findings)):
                    continue
                sim = float(np.dot(finding_matrix[fi], topic_vec_v1))
                pooled_v1_rows.append((date, cluster_idx, fid, fi, sim, lab))
                per_cluster_v1_rows.setdefault((date, cluster_idx), []).append((sim, lab))

        # Finding-centroid alternative for each labelled cluster.
        for cluster_idx, (labels_dict, _) in labelled.items():
            on_indices = [
                _fid_to_index(fid) for fid, lab in labels_dict.items()
                if lab == 1 and 0 <= _fid_to_index(fid) < len(findings)
            ]
            if not on_indices:
                # Can't form a centroid with zero on-topic labels.
                cluster_meta[(date, cluster_idx)]["centroid_supported"] = False
                continue
            centroid = finding_matrix[on_indices].mean(axis=0)
            norm = float(np.linalg.norm(centroid))
            if norm == 0.0:
                cluster_meta[(date, cluster_idx)]["centroid_supported"] = False
                continue
            centroid = centroid / norm
            cluster_meta[(date, cluster_idx)]["centroid_supported"] = True
            cluster_meta[(date, cluster_idx)]["centroid_n_on_used"] = len(on_indices)
            for fid, lab in labels_dict.items():
                fi = _fid_to_index(fid)
                if not (0 <= fi < len(findings)):
                    continue
                sim = float(np.dot(finding_matrix[fi], centroid))
                pooled_centroid_rows.append((date, cluster_idx, fid, fi, sim, lab))
                per_cluster_centroid_rows.setdefault((date, cluster_idx), []).append((sim, lab))

        # Save population sims into the population dict for downstream use
        population[date]["pop_sim_v1"] = pop_sim_v1

    # Build per-threshold results
    sweep_results: list[dict] = []
    for t in THRESHOLDS:
        # Pooled F1 — V1 headlines
        pooled_v1 = _metrics(
            [r[4] for r in pooled_v1_rows],
            [r[5] for r in pooled_v1_rows],
            t,
        )
        # Pooled F1 — finding centroid (leakage-prone — diagnostic only)
        pooled_centroid = _metrics(
            [r[4] for r in pooled_centroid_rows],
            [r[5] for r in pooled_centroid_rows],
            t,
        )
        # Per-cluster F1 (V1 headlines)
        per_cluster_v1: list[dict] = []
        for (date, ci), rows in per_cluster_v1_rows.items():
            m = _metrics([s for s, _ in rows], [lab for _, lab in rows], t)
            per_cluster_v1.append({
                "date": date,
                "cluster_idx": ci,
                "cluster_label": cluster_meta[(date, ci)]["cluster_label"],
                **m,
            })
        per_cluster_centroid: list[dict] = []
        for (date, ci), rows in per_cluster_centroid_rows.items():
            m = _metrics([s for s, _ in rows], [lab for _, lab in rows], t)
            per_cluster_centroid.append({
                "date": date,
                "cluster_idx": ci,
                "cluster_label": cluster_meta[(date, ci)]["cluster_label"],
                **m,
            })

        # Population distribution + orphan rate (pooled across dates)
        pop_dists: dict[str, dict] = {}
        pop_orphan: dict[str, float] = {}
        combined_dist = {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
        n_pop_total = 0
        n_pop_orphans = 0
        for date in DATES:
            sm = population[date]["pop_sim_v1"]
            dist = _assignments_per_finding_dist(sm, t)
            orphan_rate = _orphan_rate(sm, t)
            pop_dists[date] = dist
            pop_orphan[date] = orphan_rate
            for k, v in dist.items():
                combined_dist[k] += v
            n_pop_total += sm.shape[0]
            n_pop_orphans += dist["0"]
        combined_orphan_rate = round(n_pop_orphans / n_pop_total, 4) if n_pop_total else 0.0

        sweep_results.append({
            "threshold": t,
            "pooled_v1": pooled_v1,
            "pooled_centroid": pooled_centroid,
            "per_cluster_v1": per_cluster_v1,
            "per_cluster_centroid": per_cluster_centroid,
            "population_assignments_distribution": {
                "per_date": pop_dists,
                "combined": combined_dist,
            },
            "population_orphan_rate": {
                "per_date": pop_orphan,
                "combined": combined_orphan_rate,
            },
        })

    # Strip the population sim matrices (large) from the persisted dict
    population_persistable = {
        d: {k: v for k, v in p.items() if k != "pop_sim_v1"}
        for d, p in population.items()
    }

    return {
        "methodology": {
            "embedder_model": MODEL_NAME,
            "fastembed_version": FASTEMBED_VERSION_REQUIRED,
            "label_count_pooled": len(pooled_v1_rows),
            "label_count_centroid": len(pooled_centroid_rows),
            "thresholds_swept": list(THRESHOLDS),
            "dates": list(DATES),
            "state_paths": {d: str(p.relative_to(REPO_ROOT)) for d, p in STATE_PATHS.items()},
            "topic_centre_source": "V1 Curator headlines (title + summary). Finding-centroid alternative computed leakage-prone — diagnostic only.",
        },
        "cluster_meta": {
            f"{d}__{ci}": v for (d, ci), v in cluster_meta.items()
        },
        "population": population_persistable,
        "sweep": sweep_results,
    }


def main() -> int:
    print("== Gravitational-threshold calibration ==")
    result = calibrate()
    out_path = OUT_ROOT / "calibration.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"  Wrote {out_path.relative_to(REPO_ROOT)}")

    # Print a compact F1 sweep table
    print("\n  Pooled F1 sweep (V1 headlines / finding-centroid):")
    print(f"    {'thr':>5} {'pooled_v1 F1':>14} {'centroid F1':>14}  pop_dist (0/1/2/3/4+)   orphan%")
    for r in result["sweep"]:
        cd = r["population_assignments_distribution"]["combined"]
        orph = r["population_orphan_rate"]["combined"]
        print(
            f"    {r['threshold']:>5.2f} {r['pooled_v1']['f1']:>14.3f} "
            f"{r['pooled_centroid']['f1']:>14.3f}  "
            f"{cd['0']:>4}/{cd['1']:>3}/{cd['2']:>3}/{cd['3']:>3}/{cd['4+']:>3}  "
            f"{orph * 100:>6.1f}"
        )

    # Identify F1 peaks
    v1_peak = max(result["sweep"], key=lambda r: r["pooled_v1"]["f1"])
    centroid_peak = max(result["sweep"], key=lambda r: r["pooled_centroid"]["f1"])
    print(
        f"\n  V1 F1 peak: {v1_peak['pooled_v1']['f1']:.3f} at threshold "
        f"{v1_peak['threshold']:.2f}  ({v1_peak['pooled_v1']})"
    )
    print(
        f"  Centroid F1 peak: {centroid_peak['pooled_centroid']['f1']:.3f} at "
        f"threshold {centroid_peak['threshold']:.2f}"
    )

    # STOP-gate diagnostic
    if v1_peak["pooled_v1"]["f1"] < 0.6 and centroid_peak["pooled_centroid"]["f1"] < 0.6:
        print("\n  !! STOP gate: F1 plateaus below 0.6 on BOTH V1 headlines and "
              "finding-centroid. The architecture's premise needs review before "
              "the brief proceeds.")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
