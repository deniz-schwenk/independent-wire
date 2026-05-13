"""Isolated embedding-model eval harness.

Compares Model A (production: ``sentence-transformers/paraphrase-multilingual-
MiniLM-L12-v2``) against Model B (candidate: ``intfloat/multilingual-e5-small``)
on the 224-finding ground-truth set (89 from 2026-05-11 + 135 from 2026-05-13).

Per TASK-EMBEDDING-MODEL-EVAL.md. Does NOT touch production code paths
(`src/stages/coherence.py`, `pyproject.toml`). Model B is registered via
fastembed's `add_custom_model` API inside this script only.

Outputs:
    output/eval/embedding-2026-05-13/scores/{model}/{date}/cluster-{N}.json
    output/eval/embedding-2026-05-13/metrics.json

Determinism: fastembed ONNX is bit-deterministic per pinned version
(fastembed==0.8.0). Re-running produces identical scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Iterable

import numpy as np

# ── Configuration ────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO_ROOT / "output" / "eval" / "embedding-2026-05-13"
LABEL_ROOT = REPO_ROOT / "docs" / "coherence-filter" / "manual-labels"

MODEL_A = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_B = "intfloat/multilingual-e5-small"
MODEL_B_SIZE_GB = 0.47

# Per-date input state file
DATE_STATE: dict[str, Path] = {
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}

# Per-date labelled clusters: {date: [(cluster_index, label_csv_basename), ...]}
DATE_LABEL_MAP: dict[str, list[tuple[int, str]]] = {
    "2026-05-11": [(0, "cluster-0.csv"), (1, "cluster-1.csv"), (3, "cluster-3.csv")],
    "2026-05-13": [(1, "cluster-1.csv"), (0, "cluster-0.csv"), (11, "cluster-11.csv")],
}

# Decision thresholds (brief: ≥0.10 = clear win; 0.05–0.10 = ambiguous; <0.05 = no win)
WIN_DELTA = 0.10
AMBIGUOUS_DELTA = 0.05


# ── Embedder wrappers ────────────────────────────────────────────────────
class FastembedRunner:
    """Thin wrapper around fastembed.TextEmbedding. Caches the loaded model
    for the process lifetime. Adds an optional symmetric e5 ``query:`` prefix.
    """

    def __init__(self, *, model_name: str, prefix: str = "") -> None:
        self.model_name = model_name
        self.prefix = prefix
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        from fastembed import TextEmbedding

        if self.model_name == MODEL_B:
            self._register_e5_small()
        self._model = TextEmbedding(model_name=self.model_name)

    @staticmethod
    def _register_e5_small() -> None:
        """Register ``intfloat/multilingual-e5-small`` as a custom model.

        e5 family: MEAN pooling, L2-normalised outputs, 384-dim, ~470 MB
        fp32 ONNX. Model docs recommend the ``query:`` prefix on both texts
        for symmetric semantic-similarity tasks — we follow that
        convention. Source: HF official intfloat repo.
        """
        from fastembed import TextEmbedding
        from fastembed.common.model_description import (
            ModelSource,
            PoolingType,
        )

        # Idempotent: if already registered, skip.
        for m in TextEmbedding.list_supported_models():
            if m.get("model") == MODEL_B:
                return

        TextEmbedding.add_custom_model(
            model=MODEL_B,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf="intfloat/multilingual-e5-small"),
            dim=384,
            model_file="onnx/model.onnx",
            description=(
                "Multilingual E5 small, 384-dim, 12-layer, ~100 languages, "
                "MIT, ONNX fp32. Registered for the isolated embedding-eval "
                "harness; not used in production."
            ),
            license="mit",
            size_in_gb=MODEL_B_SIZE_GB,
        )

    def embed(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        self._load()
        prefixed = (
            [f"{self.prefix}{t}" for t in texts] if self.prefix else list(texts)
        )
        out: Iterable[np.ndarray] = self._model.embed(prefixed, batch_size=batch_size)
        return np.vstack(list(out))


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise rows in place-safe form. fastembed e5 wrapper already
    normalises; the MiniLM model emits raw vectors. Applying again to an
    already-unit-norm vector is idempotent."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return matrix / norms


# ── Data loading ─────────────────────────────────────────────────────────
def load_state(path: Path) -> tuple[list[dict], list[dict]]:
    with path.open() as f:
        data = json.load(f)
    return list(data.get("curator_findings") or []), list(
        data.get("curator_topics_unsliced") or []
    )


def load_labels(date: str, csv_name: str) -> dict[str, int]:
    """Return {finding_id: label} for the named cluster CSV."""
    p = LABEL_ROOT / date / csv_name
    out: dict[str, int] = {}
    with p.open(newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            out[row["finding_id"]] = int(row["is_on_topic"])
    return out


def _cluster_text(cluster: dict) -> str:
    return ((cluster.get("title") or "") + " " + (cluster.get("summary") or "")).strip()


def _finding_text(finding: dict) -> str:
    # Brief: title + summary + description. Description is empty in current
    # finding schema — concatenation collapses to title + summary in practice.
    return (
        (finding.get("title") or "")
        + " "
        + (finding.get("summary") or "")
        + " "
        + (finding.get("description") or "")
    ).strip()


def _finding_id_to_index(source_id: str) -> int | None:
    try:
        return int(str(source_id).split("finding-")[-1])
    except (ValueError, IndexError):
        return None


# ── Metric primitives ────────────────────────────────────────────────────
THRESHOLD_GRID: tuple[float, ...] = tuple(round(0.05 * i, 2) for i in range(1, 20))
# i.e. 0.05, 0.10, ..., 0.95 — covers the brief's 0.05–0.80 floor + e5 tail


def confusion(scores: list[float], labels: list[int], thr: float) -> dict[str, int]:
    tp = fp = tn = fn = 0
    for s, y in zip(scores, labels):
        pred = 1 if s >= thr else 0
        if pred == 1 and y == 1:
            tp += 1
        elif pred == 1 and y == 0:
            fp += 1
        elif pred == 0 and y == 0:
            tn += 1
        else:
            fn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def prf(c: dict[str, int]) -> tuple[float, float, float]:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def roc_auc(scores: list[float], labels: list[int]) -> float:
    """Mann-Whitney U formulation. With ties: 0.5 contribution."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def threshold_sweep(
    scores: list[float], labels: list[int]
) -> tuple[list[dict], dict]:
    """For each threshold compute confusion + P/R/F1. Pick F1-optimal."""
    rows = []
    for thr in THRESHOLD_GRID:
        c = confusion(scores, labels, thr)
        p, r, f = prf(c)
        rows.append(
            {
                "threshold": thr,
                "tp": c["tp"], "fp": c["fp"], "tn": c["tn"], "fn": c["fn"],
                "precision": round(p, 4),
                "recall": round(r, 4),
                "f1": round(f, 4),
            }
        )
    best = max(rows, key=lambda r: r["f1"])
    return rows, best


# ── Eval loop ────────────────────────────────────────────────────────────
def run_one(model_name: str, prefix: str, label: str) -> dict:
    """Embed and score for one model across both dates. Returns per-cluster
    metrics + per-finding scores."""
    runner = FastembedRunner(model_name=model_name, prefix=prefix)
    out_root = OUT_ROOT / "scores" / label
    out_root.mkdir(parents=True, exist_ok=True)

    model_summary: dict = {
        "model": model_name,
        "label": label,
        "prefix": prefix,
        "dates": {},
    }

    for date, state_path in DATE_STATE.items():
        if not state_path.exists():
            print(f"  [{label}/{date}] state file missing: {state_path}", flush=True)
            continue
        findings, topics = load_state(state_path)

        # Embed all findings + all in-scope cluster headlines for this date.
        in_scope = DATE_LABEL_MAP[date]
        cluster_indices = [ci for ci, _ in in_scope]
        cluster_texts = [_cluster_text(topics[ci]) for ci in cluster_indices]
        finding_texts = [_finding_text(f) for f in findings]

        t0 = time.monotonic()
        cluster_matrix = _normalize(runner.embed(cluster_texts))
        finding_matrix = _normalize(runner.embed(finding_texts, batch_size=64))
        wall = time.monotonic() - t0

        date_clusters: list[dict] = []
        for slot_i, (ci, csv_name) in enumerate(in_scope):
            cluster_vec = cluster_matrix[slot_i]
            labels_map = load_labels(date, csv_name)

            per_finding: list[dict] = []
            scores: list[float] = []
            labels: list[int] = []
            for fid, lab in sorted(labels_map.items(), key=lambda kv: kv[0]):
                idx = _finding_id_to_index(fid)
                if idx is None or not (0 <= idx < len(finding_matrix)):
                    print(
                        f"  [{label}/{date}/cluster-{ci}] missing finding {fid}",
                        flush=True,
                    )
                    continue
                sim = float(np.dot(cluster_vec, finding_matrix[idx]))
                scores.append(sim)
                labels.append(lab)
                per_finding.append(
                    {"finding_id": fid, "label": lab, "score": round(sim, 6)}
                )

            sweep, best = threshold_sweep(scores, labels)
            auc = roc_auc(scores, labels)
            cluster_row = {
                "cluster_index": ci,
                "cluster_title": (topics[ci].get("title") or "")[:200],
                "cluster_size": len(topics[ci].get("source_ids") or []),
                "labelled_n": len(labels),
                "n_on_topic": sum(labels),
                "n_off_topic": len(labels) - sum(labels),
                "score_mean": round(statistics.fmean(scores), 4) if scores else 0.0,
                "score_stdev": round(statistics.pstdev(scores), 4) if len(scores) > 1 else 0.0,
                "roc_auc": round(auc, 4) if not math.isnan(auc) else None,
                "best_threshold": best["threshold"],
                "best_precision": best["precision"],
                "best_recall": best["recall"],
                "best_f1": best["f1"],
                "best_confusion": {k: best[k] for k in ("tp", "fp", "tn", "fn")},
                "wall_seconds_total_embed": round(wall, 3),
            }

            # Persist per-finding scores + full sweep
            disk = {
                "model": model_name,
                "date": date,
                "cluster_index": ci,
                "cluster_title": cluster_row["cluster_title"],
                "metrics": cluster_row,
                "threshold_sweep": sweep,
                "per_finding_scores": per_finding,
            }
            (out_root / date).mkdir(parents=True, exist_ok=True)
            with (out_root / date / f"cluster-{ci}.json").open("w") as f:
                json.dump(disk, f, indent=2)

            date_clusters.append(cluster_row)

        # Per-date aggregates
        f1s = [c["best_f1"] for c in date_clusters]
        aucs = [c["roc_auc"] for c in date_clusters if c["roc_auc"] is not None]
        model_summary["dates"][date] = {
            "n_clusters_labelled": len(date_clusters),
            "n_findings_labelled_total": sum(c["labelled_n"] for c in date_clusters),
            "macro_f1": round(statistics.fmean(f1s), 4) if f1s else 0.0,
            "mean_roc_auc": round(statistics.fmean(aucs), 4) if aucs else 0.0,
            "clusters": date_clusters,
        }
        print(
            f"  [{label}/{date}] n={sum(c['labelled_n'] for c in date_clusters)} "
            f"macro-F1={model_summary['dates'][date]['macro_f1']:.3f} "
            f"meanAUC={model_summary['dates'][date]['mean_roc_auc']:.3f} "
            f"wall={wall:.1f}s",
            flush=True,
        )

    # Overall aggregates per model (pooled across all labelled findings + both dates)
    all_scores: list[float] = []
    all_labels: list[int] = []
    for date in model_summary["dates"]:
        for cl in model_summary["dates"][date]["clusters"]:
            pass  # handled below from disk for the pooled run
    # Pool from disk
    for date, info in model_summary["dates"].items():
        for cl in info["clusters"]:
            ci = cl["cluster_index"]
            with (out_root / date / f"cluster-{ci}.json").open() as f:
                disk = json.load(f)
            for r in disk["per_finding_scores"]:
                all_scores.append(r["score"])
                all_labels.append(r["label"])
    sweep_pool, best_pool = threshold_sweep(all_scores, all_labels)
    auc_pool = roc_auc(all_scores, all_labels)
    model_summary["pooled"] = {
        "n_findings": len(all_scores),
        "n_on_topic": sum(all_labels),
        "n_off_topic": len(all_labels) - sum(all_labels),
        "roc_auc": round(auc_pool, 4) if not math.isnan(auc_pool) else None,
        "best_threshold": best_pool["threshold"],
        "best_precision": best_pool["precision"],
        "best_recall": best_pool["recall"],
        "best_f1": best_pool["f1"],
        "best_confusion": {k: best_pool[k] for k in ("tp", "fp", "tn", "fn")},
        "threshold_sweep": sweep_pool,
    }
    macro_f1_over_dates = statistics.fmean(
        [info["macro_f1"] for info in model_summary["dates"].values()]
    )
    mean_auc_over_dates = statistics.fmean(
        [info["mean_roc_auc"] for info in model_summary["dates"].values()]
    )
    model_summary["overall"] = {
        "macro_f1_dates": round(macro_f1_over_dates, 4),
        "mean_roc_auc_dates": round(mean_auc_over_dates, 4),
    }
    return model_summary


# ── Verdict ──────────────────────────────────────────────────────────────
def verdict_band(delta: float) -> str:
    if delta >= WIN_DELTA:
        return "clear-win-B"
    if delta >= AMBIGUOUS_DELTA:
        return "ambiguous"
    if delta <= -WIN_DELTA:
        return "clear-win-A"
    if delta <= -AMBIGUOUS_DELTA:
        return "ambiguous-A"
    return "no-win"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["A", "B"], help="run only one model")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: dict = {}

    targets = [
        ("A", MODEL_A, ""),
        ("B", MODEL_B, "query: "),
    ]
    if args.only:
        targets = [t for t in targets if t[0] == args.only]

    for label, model_name, prefix in targets:
        print(f"== {label}: {model_name} (prefix={prefix!r}) ==", flush=True)
        results[label] = run_one(model_name=model_name, prefix=prefix, label=label)

    # Pairwise delta if both models ran
    if "A" in results and "B" in results:
        delta_macro = (
            results["B"]["overall"]["macro_f1_dates"]
            - results["A"]["overall"]["macro_f1_dates"]
        )
        delta_pool = (
            results["B"]["pooled"]["best_f1"] - results["A"]["pooled"]["best_f1"]
        )
        results["comparison"] = {
            "delta_macro_f1": round(delta_macro, 4),
            "delta_pooled_f1": round(delta_pool, 4),
            "verdict_band_macro": verdict_band(delta_macro),
            "verdict_band_pooled": verdict_band(delta_pool),
            "thresholds": {"clear_win": WIN_DELTA, "ambiguous": AMBIGUOUS_DELTA},
        }
        # Per-cluster delta table (Model B − Model A)
        per_cluster: list[dict] = []
        for date in DATE_STATE:
            for ci, _ in DATE_LABEL_MAP[date]:
                row_a = next(
                    c for c in results["A"]["dates"][date]["clusters"]
                    if c["cluster_index"] == ci
                )
                row_b = next(
                    c for c in results["B"]["dates"][date]["clusters"]
                    if c["cluster_index"] == ci
                )
                per_cluster.append(
                    {
                        "date": date,
                        "cluster_index": ci,
                        "cluster_title": row_a["cluster_title"][:80],
                        "labelled_n": row_a["labelled_n"],
                        "A_f1": row_a["best_f1"],
                        "A_auc": row_a["roc_auc"],
                        "B_f1": row_b["best_f1"],
                        "B_auc": row_b["roc_auc"],
                        "f1_delta": round(row_b["best_f1"] - row_a["best_f1"], 4),
                        "auc_delta": round(
                            (row_b["roc_auc"] or 0) - (row_a["roc_auc"] or 0), 4
                        ),
                    }
                )
        results["comparison"]["per_cluster"] = per_cluster

    metrics_path = OUT_ROOT / "metrics.json"
    with metrics_path.open("w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {metrics_path}")
    print(json.dumps(results.get("comparison", {}), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
