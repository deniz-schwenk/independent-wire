"""Isolated clustering-eval harness.

Phase 2 (embeddings) + Phase 3 (clustering matrix) + Phase 4 (per-run metrics)
of TASK-CLUSTERING-EVAL. Production code paths (`src/stages/coherence.py`,
`pyproject.toml` dependencies list, production model pin) are NOT touched.
hdbscan + scikit-learn are eval-only dependencies declared under
``pyproject.toml [optional-dependencies] eval``.

Model B (multilingual-e5-small) is registered via fastembed.add_custom_model
inside this script only — same isolation pattern as scripts/eval_embedding_models.py.

Usage:
    python scripts/eval_clustering.py            # full pipeline (embed → cluster → evaluate)
    python scripts/eval_clustering.py --phase embed
    python scripts/eval_clustering.py --phase cluster
    python scripts/eval_clustering.py --phase evaluate
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np

# ── Paths and configuration ──────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO_ROOT / "output" / "eval" / "clustering-2026-05-14"
LABEL_ROOT = REPO_ROOT / "docs" / "coherence-filter" / "manual-labels"

MODEL_A = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_B = "intfloat/multilingual-e5-small"

# For e5 family: model docs recommend "query: " prefix on all texts for
# non-retrieval tasks (STS, clustering). We embed findings for clustering
# (not asymmetric query→passage retrieval), so "query: " is correct.
MODEL_B_PREFIX = "query: "

DATE_STATE: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}

# Per-date labelled-cluster map: list of (cluster_index_in_curator_topics_unsliced,
# label CSV basenames as a tuple — extension CSVs merged transparently).
DATE_LABEL_MAP: dict[str, list[tuple[int, tuple[str, ...]]]] = {
    "2026-05-11": [
        (0, ("cluster-0.csv", "cluster-0-ext.csv")),
        (1, ("cluster-1.csv",)),
        (3, ("cluster-3.csv",)),
    ],
    "2026-05-13": [
        (1, ("cluster-1.csv", "cluster-1-ext.csv")),
        (0, ("cluster-0.csv",)),
        (11, ("cluster-11.csv",)),
    ],
}

# Clustering matrix — 4 HDBSCAN configs + 3 Agglomerative configs.
HDBSCAN_CONFIGS: dict[str, dict] = {
    "hdb-conservative": {
        "min_cluster_size": 20, "min_samples": 10, "cluster_selection_epsilon": 0.0,
    },
    "hdb-balanced": {
        "min_cluster_size": 10, "min_samples": 5, "cluster_selection_epsilon": 0.10,
    },
    "hdb-permissive": {
        "min_cluster_size": 5, "min_samples": 1, "cluster_selection_epsilon": 0.20,
    },
    "hdb-strict-noise": {
        "min_cluster_size": 15, "min_samples": 15, "cluster_selection_epsilon": 0.0,
    },
}

AGG_CONFIGS: dict[str, dict] = {
    "agg-strict": {"distance_threshold": 0.3, "linkage": "average"},
    "agg-balanced": {"distance_threshold": 0.5, "linkage": "average"},
    "agg-permissive": {"distance_threshold": 0.7, "linkage": "average"},
}

# Pathology threshold — clusters bigger than this are mega-clusters
PATHOLOGY_MAX_CLUSTER_SIZE = 200


# ── Fastembed runner (model loader) ──────────────────────────────────────
class FastembedRunner:
    def __init__(self, *, model_name: str, prefix: str = "") -> None:
        self.model_name = model_name
        self.prefix = prefix
        self._model = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from fastembed import TextEmbedding

        if self.model_name == MODEL_B:
            self._register_e5_small()
        self._model = TextEmbedding(model_name=self.model_name)

    @staticmethod
    def _register_e5_small() -> None:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

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
            description="Multilingual E5 small (eval-only)",
            license="mit",
            size_in_gb=0.47,
        )

    def embed(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        self._ensure_loaded()
        prefixed = (
            [f"{self.prefix}{t}" for t in texts] if self.prefix else list(texts)
        )
        out: Iterable[np.ndarray] = self._model.embed(prefixed, batch_size=batch_size)
        return np.vstack(list(out))


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return matrix / norms


def _finding_text(finding: dict) -> str:
    """Same concatenation rule as the production coherence stage."""
    return (
        (finding.get("title") or "")
        + " "
        + (finding.get("summary") or "")
        + " "
        + (finding.get("description") or "")
    ).strip()


def load_state(path: Path) -> tuple[list[dict], list[dict]]:
    with path.open() as f:
        data = json.load(f)
    return list(data.get("curator_findings") or []), list(
        data.get("curator_topics_unsliced") or []
    )


# ── Phase 2: embeddings ──────────────────────────────────────────────────
def phase_embed() -> None:
    embed_root = OUT_ROOT / "embeddings"
    embed_root.mkdir(parents=True, exist_ok=True)
    for date, state_path in DATE_STATE.items():
        if not state_path.exists():
            print(f"  [embed/{date}] state missing — skipping")
            continue
        findings, _ = load_state(state_path)
        finding_texts = [_finding_text(f) for f in findings]
        out_dir = embed_root / date
        out_dir.mkdir(parents=True, exist_ok=True)
        ids_path = out_dir / "finding_ids.txt"
        ids_path.write_text(
            "\n".join(f"finding-{i}" for i in range(len(findings))) + "\n"
        )
        for label, model_name, prefix in (
            ("A", MODEL_A, ""),
            ("B", MODEL_B, MODEL_B_PREFIX),
        ):
            out_path = out_dir / f"{label}.npy"
            if out_path.exists():
                print(f"  [embed/{date}/{label}] cached at {out_path.name}")
                continue
            t0 = time.monotonic()
            runner = FastembedRunner(model_name=model_name, prefix=prefix)
            mat = _normalize_rows(runner.embed(finding_texts))
            np.save(out_path, mat.astype(np.float32))
            print(
                f"  [embed/{date}/{label}] shape={mat.shape} "
                f"wall={time.monotonic() - t0:.1f}s"
            )


# ── Phase 3: clustering ──────────────────────────────────────────────────
def _run_hdbscan(embeddings: np.ndarray, params: dict) -> np.ndarray:
    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=params["min_cluster_size"],
        min_samples=params["min_samples"],
        cluster_selection_epsilon=params["cluster_selection_epsilon"],
        metric="euclidean",  # cosine == euclidean on L2-normalised vectors
        core_dist_n_jobs=1,  # deterministic, single-threaded
    )
    return clusterer.fit_predict(embeddings)


def _run_agglomerative(embeddings: np.ndarray, params: dict) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering

    clusterer = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=params["distance_threshold"],
        linkage=params["linkage"],
        metric="cosine",
    )
    return clusterer.fit_predict(embeddings)


def _structural_metrics(embeddings: np.ndarray, labels: np.ndarray) -> dict:
    """Cluster sizes, silhouette + davies-bouldin (non-noise points only)."""
    from sklearn.metrics import davies_bouldin_score, silhouette_score

    out: dict = {}
    n_total = len(labels)
    noise_mask = labels == -1
    out["n_total"] = n_total
    out["noise_count"] = int(noise_mask.sum())
    out["noise_rate"] = round(float(noise_mask.mean()), 4) if n_total else 0.0

    non_noise_labels = labels[~noise_mask]
    unique = sorted(set(non_noise_labels.tolist()))
    sizes = [int((non_noise_labels == c).sum()) for c in unique]
    out["n_clusters"] = len(unique)
    if sizes:
        out["cluster_size_min"] = min(sizes)
        out["cluster_size_max"] = max(sizes)
        out["cluster_size_mean"] = round(statistics.fmean(sizes), 2)
        out["cluster_size_median"] = float(statistics.median(sizes))
        out["cluster_size_p90"] = float(
            np.percentile(np.asarray(sizes), 90)
        )
    else:
        out["cluster_size_min"] = out["cluster_size_max"] = out[
            "cluster_size_mean"
        ] = out["cluster_size_median"] = out["cluster_size_p90"] = 0

    # Silhouette / Davies-Bouldin require at least 2 unique non-noise clusters
    if len(unique) >= 2 and (~noise_mask).sum() >= 3:
        non_noise_emb = embeddings[~noise_mask]
        try:
            out["silhouette_score"] = round(
                float(silhouette_score(non_noise_emb, non_noise_labels, metric="cosine")),
                4,
            )
        except Exception as exc:  # pragma: no cover - safety
            out["silhouette_score"] = None
            out["silhouette_error"] = str(exc)
        try:
            out["davies_bouldin_score"] = round(
                float(davies_bouldin_score(non_noise_emb, non_noise_labels)), 4
            )
        except Exception as exc:  # pragma: no cover
            out["davies_bouldin_score"] = None
            out["davies_bouldin_error"] = str(exc)
    else:
        out["silhouette_score"] = None
        out["davies_bouldin_score"] = None

    return out


def _pathology(out: dict) -> dict:
    mega = out["cluster_size_max"] > PATHOLOGY_MAX_CLUSTER_SIZE
    # Findings in clusters > pathology threshold:
    mega_count = 0  # filled by caller from cluster sizes
    return {
        "max_cluster_size": out["cluster_size_max"],
        "pathology_flag": bool(mega),
    }


def phase_cluster() -> None:
    embed_root = OUT_ROOT / "embeddings"
    runs_root = OUT_ROOT / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    n_runs = 0
    n_total = 2 * sum(1 for d in DATE_STATE if (embed_root / d).exists()) * (
        len(HDBSCAN_CONFIGS) + len(AGG_CONFIGS)
    )
    print(f"  Total runs queued: {n_total}")

    for date in DATE_STATE:
        date_dir = embed_root / date
        if not (date_dir / "A.npy").exists():
            print(f"  [cluster/{date}] embeddings missing — skipping")
            continue
        for model_label in ("A", "B"):
            embeddings = np.load(date_dir / f"{model_label}.npy")
            embeddings = embeddings.astype(np.float64)  # sklearn happier
            cfgs: list[tuple[str, str, dict]] = [
                ("hdbscan", lbl, p) for lbl, p in HDBSCAN_CONFIGS.items()
            ] + [
                ("agglomerative", lbl, p) for lbl, p in AGG_CONFIGS.items()
            ]
            for algo, cfg_label, params in cfgs:
                run_dir = runs_root / date / model_label / cfg_label
                run_dir.mkdir(parents=True, exist_ok=True)
                t0 = time.monotonic()
                if algo == "hdbscan":
                    cluster_labels = _run_hdbscan(embeddings, params)
                else:
                    cluster_labels = _run_agglomerative(embeddings, params)
                wall = time.monotonic() - t0
                struct = _structural_metrics(embeddings, cluster_labels)
                # Compute pathology-rate (noise + mega-clusters)
                noise_count = struct["noise_count"]
                mega_count = sum(
                    int(s) for s in (
                        [int((cluster_labels == c).sum()) for c in set(cluster_labels.tolist()) if c != -1]
                    )
                    if int(s) > PATHOLOGY_MAX_CLUSTER_SIZE
                )
                struct["noise_or_pathology_rate"] = round(
                    (noise_count + mega_count) / max(1, len(cluster_labels)), 4
                )
                struct["max_cluster_size_pathology"] = struct["cluster_size_max"] > PATHOLOGY_MAX_CLUSTER_SIZE

                # Persist labels + meta
                np.save(run_dir / "labels.npy", cluster_labels.astype(np.int32))
                meta = {
                    "date": date,
                    "model": model_label,
                    "model_id": MODEL_A if model_label == "A" else MODEL_B,
                    "algorithm": algo,
                    "config": cfg_label,
                    "params": params,
                    "wall_seconds": round(wall, 3),
                    **struct,
                }
                with (run_dir / "meta.json").open("w") as f:
                    json.dump(meta, f, indent=2)
                n_runs += 1
                print(
                    f"  [cluster {n_runs}/{n_total}] {date}/{model_label}/{cfg_label}: "
                    f"n_clusters={struct['n_clusters']} noise={struct['noise_rate']:.3f} "
                    f"max={struct['cluster_size_max']} wall={wall:.1f}s"
                )
    print(f"  Phase 3 complete: {n_runs} runs.")


# ── Phase 4: per-TP recovery + ground-truth alignment ────────────────────
def _load_labels(date: str, csv_names: tuple[str, ...]) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in csv_names:
        p = LABEL_ROOT / date / name
        with p.open(newline="") as f:
            for row in csv.DictReader(f):
                out[row["finding_id"]] = int(row["is_on_topic"])
    return out


def _fid_to_index(fid: str) -> int:
    return int(str(fid).split("finding-")[-1])


def _per_tp_recovery(
    cluster_labels: np.ndarray,
    labelled_findings: dict[str, int],
    *,
    tp_cluster_index: int,
) -> dict:
    """For one original TP cluster, compute:
    - Which new cluster(s) contain the on-topic labelled findings (largest share = "recovered cluster")
    - Recall: fraction of on-topic that landed in the recovered cluster
    - Precision: fraction of recovered-cluster's labelled findings that are on-topic for this TP
    - F1
    - Off-topic placement table
    """
    on_topic_indices: list[int] = []
    off_topic_indices: list[int] = []
    for fid, lab in labelled_findings.items():
        idx = _fid_to_index(fid)
        if not (0 <= idx < len(cluster_labels)):
            continue
        if lab == 1:
            on_topic_indices.append(idx)
        else:
            off_topic_indices.append(idx)

    if not on_topic_indices:
        # No on-topic findings labelled for this TP — recovery is undefined.
        # Off-topic placement is still meaningful but we mark recovery as None.
        return {
            "tp_cluster_index": tp_cluster_index,
            "n_on_topic": 0,
            "n_off_topic": len(off_topic_indices),
            "recovered_cluster_id": None,
            "recall": None,
            "precision": None,
            "f1": None,
            "off_topic_placement": _off_topic_placement(
                cluster_labels, off_topic_indices, recovered_cluster_id=None
            ),
        }

    # Find the dominant new cluster for on-topic findings.
    on_topic_cluster_counts = Counter(cluster_labels[i] for i in on_topic_indices)
    # The recovered cluster is the most-populated new cluster among on-topic
    # findings, EXCLUDING -1 (noise). A best-case "ideal" recovery would
    # have all on-topic findings in one non-noise cluster.
    non_noise_pairs = [
        (cid, cnt) for cid, cnt in on_topic_cluster_counts.items() if cid != -1
    ]
    if non_noise_pairs:
        recovered_cluster_id = int(max(non_noise_pairs, key=lambda kv: kv[1])[0])
        tp_in_recovered = int(on_topic_cluster_counts[recovered_cluster_id])
    else:
        # All on-topic findings landed in noise — recovery failed at the
        # cluster-formation step. We treat this as zero recovery.
        recovered_cluster_id = -1
        tp_in_recovered = 0

    n_on_topic = len(on_topic_indices)
    recall = tp_in_recovered / n_on_topic if n_on_topic else 0.0

    # Precision: among the labelled findings sitting in the recovered cluster,
    # what share are on-topic for this TP?
    if recovered_cluster_id == -1:
        precision = 0.0
    else:
        in_recovered_on = sum(
            1 for i in on_topic_indices if int(cluster_labels[i]) == recovered_cluster_id
        )
        in_recovered_off = sum(
            1 for i in off_topic_indices if int(cluster_labels[i]) == recovered_cluster_id
        )
        denom = in_recovered_on + in_recovered_off
        precision = in_recovered_on / denom if denom else 0.0

    f1 = (
        (2 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "tp_cluster_index": tp_cluster_index,
        "n_on_topic": n_on_topic,
        "n_off_topic": len(off_topic_indices),
        "recovered_cluster_id": recovered_cluster_id,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "off_topic_placement": _off_topic_placement(
            cluster_labels, off_topic_indices, recovered_cluster_id=recovered_cluster_id
        ),
    }


def _off_topic_placement(
    cluster_labels: np.ndarray,
    off_topic_indices: list[int],
    *,
    recovered_cluster_id: int | None,
) -> dict:
    """Categorise where the off-topic findings landed."""
    n = len(off_topic_indices)
    if not n:
        return {"n": 0}
    in_noise = sum(1 for i in off_topic_indices if int(cluster_labels[i]) == -1)
    co_located = (
        sum(1 for i in off_topic_indices if int(cluster_labels[i]) == recovered_cluster_id)
        if recovered_cluster_id is not None
        else 0
    )
    in_other = n - in_noise - co_located
    return {
        "n": n,
        "n_in_noise": in_noise,
        "n_co_located_with_on_topic": co_located,
        "n_in_other_clusters": in_other,
        "pct_in_noise": round(100 * in_noise / n, 1),
        "pct_co_located": round(100 * co_located / n, 1),
        "pct_in_other": round(100 * in_other / n, 1),
    }


def phase_evaluate() -> None:
    runs_root = OUT_ROOT / "runs"
    all_runs: list[dict] = []
    for date in DATE_STATE:
        date_dir = runs_root / date
        if not date_dir.exists():
            continue
        for model_dir in sorted(date_dir.iterdir()):
            for cfg_dir in sorted(model_dir.iterdir()):
                meta_path = cfg_dir / "meta.json"
                labels_path = cfg_dir / "labels.npy"
                if not meta_path.exists() or not labels_path.exists():
                    continue
                meta = json.loads(meta_path.read_text())
                cluster_labels = np.load(labels_path)

                # Per-TP recovery (only for dates with manual labels)
                per_tp: list[dict] = []
                weighted_f1_num = 0.0
                weighted_f1_den = 0
                if date in DATE_LABEL_MAP:
                    for ci, csv_names in DATE_LABEL_MAP[date]:
                        labels_map = _load_labels(date, csv_names)
                        rec = _per_tp_recovery(
                            cluster_labels, labels_map, tp_cluster_index=ci
                        )
                        per_tp.append(rec)
                        if rec["f1"] is not None:
                            n_lab = rec["n_on_topic"] + rec["n_off_topic"]
                            weighted_f1_num += rec["f1"] * n_lab
                            weighted_f1_den += n_lab
                weighted_f1 = (
                    weighted_f1_num / weighted_f1_den if weighted_f1_den else 0.0
                )

                meta["per_tp_recovery"] = per_tp
                meta["aggregate_f1"] = round(weighted_f1, 4)
                meta["has_ground_truth"] = date in DATE_LABEL_MAP
                with meta_path.open("w") as f:
                    json.dump(meta, f, indent=2)
                all_runs.append(meta)

    # Headline table — sort by aggregate F1 desc
    all_runs.sort(key=lambda r: -r["aggregate_f1"])
    table_rows = [
        {
            "rank": i + 1,
            "model": r["model"],
            "algorithm": r["algorithm"],
            "config": r["config"],
            "date": r["date"],
            "aggregate_f1": r["aggregate_f1"],
            "n_clusters": r["n_clusters"],
            "noise_rate": r["noise_rate"],
            "max_cluster_size": r["cluster_size_max"],
            "pathology_flag": r["max_cluster_size_pathology"],
            "silhouette": r["silhouette_score"],
            "davies_bouldin": r["davies_bouldin_score"],
        }
        for i, r in enumerate(all_runs)
    ]
    summary_path = OUT_ROOT / "summary.json"
    with summary_path.open("w") as f:
        json.dump(
            {
                "n_runs": len(all_runs),
                "models": ["A", "B"],
                "datasets": list(DATE_STATE.keys()),
                "hdbscan_configs": list(HDBSCAN_CONFIGS.keys()),
                "agglomerative_configs": list(AGG_CONFIGS.keys()),
                "headline_table": table_rows,
                "all_runs": all_runs,
            },
            f,
            indent=2,
        )
    print(f"  Wrote {summary_path}")
    # Print top 5
    print("\n  Top 5 runs by aggregate F1:")
    for r in table_rows[:5]:
        print(
            f"    {r['rank']:2d}. "
            f"{r['model']}/{r['algorithm']:13s}/{r['config']:17s}/{r['date']}: "
            f"F1={r['aggregate_f1']:.3f} n_clusters={r['n_clusters']:3d} "
            f"noise={r['noise_rate']:.2f} max={r['max_cluster_size']:5d} "
            f"path={'YES' if r['pathology_flag'] else ' no'}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--phase",
        choices=("embed", "cluster", "evaluate", "all"),
        default="all",
    )
    args = ap.parse_args()

    if args.phase in ("embed", "all"):
        print("== Phase 2: embeddings ==")
        phase_embed()
    if args.phase in ("cluster", "all"):
        print("\n== Phase 3: clustering matrix ==")
        phase_cluster()
    if args.phase in ("evaluate", "all"):
        print("\n== Phase 4: per-run evaluation ==")
        phase_evaluate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
