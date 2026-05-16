"""Passive cluster-coherence measurement stage.

Authoritative reference: TASK-COHERENCE-FILTER-PASSIVE.md.
Dependency rationale: docs/ADR-COHERENCE-STAGE-DEPENDENCY.md.

Runs after CuratorStage, before EditorStage. Embeds each cluster's
``title + summary`` (the cluster headline) and each finding's
``title + summary``, then computes the cosine similarity between every
finding and its cluster's headline embedding. Per-cluster aggregates and
threshold-band counts are written to the ``curator_coherence_scores``
slot; the upstream ``curator_findings`` and ``curator_topics_unsliced``
slots pass through byte-identical.

Determinism: fastembed runs ONNX inference single-threaded at
``batch_size=32`` — bit-deterministic. The fastembed version is pinned in
``pyproject.toml`` and the model name is pinned at module level — both
are load-bearing for reproducibility (the mean-pooling change in
fastembed >=0.6 silently shifted every score for this model).
"""

from __future__ import annotations

import logging
import resource
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol, Sequence

import numpy as np

from src.bus import RunBus
from src.stage import run_stage_def

logger = logging.getLogger(__name__)


# ── Pinned configuration ─────────────────────────────────────────────────
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
"""Multilingual sentence-embedding model. ~50 languages covering the full
production set (EN, DE, ES, FR, IT, PT, TR, KO, FA, RU, ZH, AR, HE, ID,
VI). Pinned together with fastembed==0.8.0 in pyproject.toml because
fastembed >=0.6 switched this model from CLS-token to mean-pooled output
— a silent fastembed upgrade would invalidate every historic coherence
score."""

FASTEMBED_VERSION_REQUIRED = "0.8.0"
"""Pinned fastembed version. Runtime mismatch logs a WARNING; scores
remain reproducible only at this exact version."""

DEFAULT_BATCH_SIZE = 32
"""ONNX inference batch size. Empirically optimal on Apple Silicon
M-series (32 < 64 < 128 on the V1-baseline 1201-finding workload). Larger
batches add memory pressure and slow overall throughput. Single-process
single-threaded; ``parallel`` multiprocess inference is slower than the
single-process path on this workload due to spawn overhead."""

THRESHOLD_BANDS: tuple[float, ...] = (
    0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70,
)
"""Candidate coherence thresholds. The stage counts how many findings in
each cluster fall below each band — gives the calibration step the data
to pick one threshold (or interpolate). The future active-filter brief
chooses based on the V1 ROC analysis."""


# ── Embedder protocol ────────────────────────────────────────────────────
class Embedder(Protocol):
    """Production: ``FastembedEmbedder``. Tests inject deterministic stubs."""

    model_name: str

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Return an array of shape ``(len(texts), dim)`` — caller normalizes."""


class FastembedEmbedder:
    """Lazy-loaded fastembed ``TextEmbedding`` wrapper. The wrapper holds
    the ONNX session for the process lifetime; a single instance is shared
    across pipeline runs in the same process."""

    model_name: str

    def __init__(
        self,
        *,
        model_name: str = MODEL_NAME,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model: Any = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            import fastembed as _fastembed
        except ImportError as exc:
            raise RuntimeError(
                "fastembed not installed. Run `pip install -e .` to pull "
                "the pinned dependency from pyproject.toml."
            ) from exc
        installed = getattr(_fastembed, "__version__", "unknown")
        if installed != FASTEMBED_VERSION_REQUIRED:
            logger.warning(
                "fastembed version mismatch: installed=%s, pinned=%s — "
                "coherence scores may not be bit-identical to historic runs.",
                installed,
                FASTEMBED_VERSION_REQUIRED,
            )
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=self.model_name)

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        self._ensure_loaded()
        vecs: Iterable[np.ndarray] = self._model.embed(
            list(texts), batch_size=self.batch_size
        )
        return np.vstack(list(vecs))


_default_embedder: Optional[FastembedEmbedder] = None


def _get_default_embedder() -> FastembedEmbedder:
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = FastembedEmbedder()
    return _default_embedder


# ── Pure helpers ─────────────────────────────────────────────────────────
def _cluster_text(cluster: dict) -> str:
    return ((cluster.get("title") or "") + " " + (cluster.get("summary") or "")).strip()


def _finding_text(finding: dict) -> str:
    title = finding.get("title") or ""
    summary = finding.get("summary") or finding.get("description") or ""
    return (title + " " + summary).strip()


def _finding_index_from_source_id(source_id: str) -> Optional[int]:
    """Cluster ``source_ids`` carry the ``finding-NNN`` prefix referring
    to ``run_bus.curator_findings[NNN]`` — same convention as V1
    hydration_urls."""
    try:
        return int(str(source_id).split("finding-")[-1])
    except (ValueError, IndexError):
        return None


def _cosine_normalized(matrix: np.ndarray) -> np.ndarray:
    """L2-normalize each row in place-safe form. Zero-norm rows pass
    through unchanged (cosine sim to anything = 0)."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return matrix / norms


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), p * 100.0))


def _aggregate_cluster_scores(scores: list[float]) -> dict[str, float]:
    if not scores:
        return {
            "mean": 0.0, "median": 0.0,
            "p10": 0.0, "p25": 0.0, "p75": 0.0, "p90": 0.0,
            "min": 0.0, "max": 0.0,
        }
    return {
        "mean": float(np.mean(scores)),
        "median": float(np.median(scores)),
        "p10": _percentile(scores, 0.10),
        "p25": _percentile(scores, 0.25),
        "p75": _percentile(scores, 0.75),
        "p90": _percentile(scores, 0.90),
        "min": float(min(scores)),
        "max": float(max(scores)),
    }


def _below_threshold_counts(scores: list[float]) -> dict[str, int]:
    return {f"{t:.2f}": sum(1 for s in scores if s < t) for t in THRESHOLD_BANDS}


def _rss_mb_now() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = 1.0 if sys.platform == "darwin" else 1024.0  # macOS=bytes, Linux=KB
    return raw * unit / 1e6





__all__ = [
    "DEFAULT_BATCH_SIZE",
    "Embedder",
    "FASTEMBED_VERSION_REQUIRED",
    "FastembedEmbedder",
    "MODEL_NAME",
    "THRESHOLD_BANDS",
    "make_measure_cluster_coherence",
    "measure_cluster_coherence",
    "write_daily_report",
]
