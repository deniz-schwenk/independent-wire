"""Embed-pre-cluster stage — deterministic micro-cluster formation.

Authoritative references:
- docs/ADR-CURATOR-TRIPLE-STAGE.md  (architectural rationale)
- TASK-EMBED-PRE-CLUSTER-STAGE.md   (this stage's contract)
- docs/CLUSTERING-EVAL-2026-05-14.md (parameter calibration)
- docs/ADR-COHERENCE-STAGE-DEPENDENCY-ADDENDUM-2026-05-15.md
                                    (scikit-learn promotion rationale)

Runs after fetch_findings and BEFORE the Curator/Topic-Discovery stage
in the eventual triple-stage Curator architecture. Embeds every
``curator_finding`` via the fastembed singleton shared with
``src/stages/coherence.py``, then groups them via Agglomerative
clustering with the parameters established by the clustering eval:
``distance_threshold=0.7``, ``linkage='average'``, ``metric='cosine'``.
No LLM.

Determinism: identical ``curator_findings`` produces bit-identical
clusters. Wall-time and RSS-delta in the output dict are timing-
dependent and stripped before any equality check.

This stage is declared but NOT YET WIRED into
``build_production_stages`` / ``build_hydrated_stages``. The integration
brief later in the triple-stage sequence does the wiring; this brief
lands the stage as a standalone callable + smoke harness.
"""

from __future__ import annotations

import logging
import resource
import sys
import time
from typing import Any, Callable, Optional

import numpy as np

from src.bus import RunBus
from src.stage import run_stage_def
from src.stages.coherence import (
    FASTEMBED_VERSION_REQUIRED,
    MODEL_NAME,
    _cosine_normalized,
    _get_default_embedder,
)

logger = logging.getLogger(__name__)


# ── Pinned algorithm parameters (calibrated CLUSTERING-EVAL-2026-05-14) ──
DISTANCE_THRESHOLD: float = 0.7
"""Cosine-distance cut for the Agglomerative tree. Calibrated against
the 504-finding ground-truth set — the ``agg-permissive`` configuration
produced mean F1 0.71 across two days, max cluster size 77, zero
pathology runs. Do not change without re-running the eval."""

LINKAGE: str = "average"
"""Linkage method. Average linkage was the only setting carried into
the final eval matrix; alternatives are out of scope at this brief."""

METRIC: str = "cosine"
"""Distance metric — cosine on the L2-normalised 384-dim fastembed
output. Mathematically equivalent to Euclidean on the normalised
vectors; exposed as ``cosine`` so sklearn picks its specialised
cosine-distance code path."""

ALGORITHM: str = "agglomerative"


# ── Pure helpers ──────────────────────────────────────────────────────────
def _finding_text(finding: dict) -> str:
    """Concatenate the fields the clustering eval embedded.

    Mirrors ``scripts/eval_clustering.py::_finding_text`` exactly so the
    production stage reproduces the eval's ``agg-permissive`` numbers
    on the same state files. On real RSS findings (where ``description``
    is empty and ``summary`` populated) the result is identical to the
    coherence stage's ``title + summary`` concatenation."""
    return (
        (finding.get("title") or "")
        + " "
        + (finding.get("summary") or "")
        + " "
        + (finding.get("description") or "")
    ).strip()


def _run_agglomerative(
    embeddings: np.ndarray,
    *,
    distance_threshold: float = DISTANCE_THRESHOLD,
    linkage: str = LINKAGE,
    metric: str = METRIC,
) -> np.ndarray:
    """Run sklearn AgglomerativeClustering and return cluster labels.

    Pure function exposed for test reuse — tests inject a synthetic
    threshold tuned for low-dim fake embeddings; production calls with
    the module defaults. Bit-identical to
    ``scripts/eval_clustering.py::_run_agglomerative`` so the eval's
    parameters reproduce here without a porting question."""
    from sklearn.cluster import AgglomerativeClustering

    clusterer = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        linkage=linkage,
        metric=metric,
    )
    return clusterer.fit_predict(embeddings)


def _format_clusters(labels: np.ndarray) -> list[dict]:
    """Convert the sklearn label array into deterministic ``mc-NNN``
    cluster entries. Sort key: size descending, tie-break smallest
    contained finding-index ascending. ``source_ids`` within each
    cluster are sorted ascending by finding-index for byte-stable
    output."""
    groups: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        groups.setdefault(int(lab), []).append(i)
    for indices in groups.values():
        indices.sort()
    cluster_tuples = sorted(
        groups.items(),
        key=lambda kv: (-len(kv[1]), kv[1][0] if kv[1] else 0),
    )
    return [
        {
            "id": f"mc-{new_id:03d}",
            "size": len(indices),
            "source_ids": [f"finding-{i}" for i in indices],
        }
        for new_id, (_label, indices) in enumerate(cluster_tuples)
    ]


def _rss_mb_now() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = 1.0 if sys.platform == "darwin" else 1024.0  # macOS=bytes, Linux=KB
    return raw * unit / 1e6


def _sklearn_version() -> str:
    try:
        import sklearn

        return getattr(sklearn, "__version__", "unknown")
    except ImportError:
        return "not-installed"


# ── Stage factory ─────────────────────────────────────────────────────────
def make_pre_cluster_findings(
    *,
    embedder: Optional[Any] = None,
    distance_threshold: float = DISTANCE_THRESHOLD,
    linkage: str = LINKAGE,
    metric: str = METRIC,
) -> Callable:
    """Build the pre-cluster run-stage.

    Tests inject a fake ``embedder`` and a synthetic ``distance_threshold``
    tuned for low-dim fake geometry. Production omits both — the stage
    falls through to the fastembed singleton in
    ``src/stages/coherence.py`` and the calibrated module defaults."""
    closure_embedder = embedder
    closure_distance = distance_threshold
    closure_linkage = linkage
    closure_metric = metric

    @run_stage_def(
        reads=("curator_findings", "curator_findings_clustering"),
        writes=("curator_pre_clusters",),
    )
    async def pre_cluster_findings(run_bus: RunBus) -> RunBus:
        from src.stages.translate_sidecar import clustering_findings

        findings = list(run_bus.curator_findings or [])
        # Translate-to-English sidecar (TASK-CLUSTER-TRANSLATE-SIDECAR): when the
        # flag-gated sidecar populated curator_findings_clustering, embed the
        # English-normalised text; otherwise fall through to native (default).
        # Index-aligned, so finding-NNN source-ids stay correct either way.
        text_source = clustering_findings(run_bus)
        if text_source is None:
            text_source = findings

        emb = closure_embedder if closure_embedder is not None else _get_default_embedder()
        model_name = getattr(emb, "model_name", MODEL_NAME)

        meta_common: dict[str, Any] = {
            "model_name": model_name,
            "fastembed_version": FASTEMBED_VERSION_REQUIRED,
            "algorithm": ALGORITHM,
            "algorithm_library": "scikit-learn",
            "algorithm_library_version": _sklearn_version(),
            "params": {
                "distance_threshold": closure_distance,
                "linkage": closure_linkage,
                "metric": closure_metric,
            },
        }

        if not findings:
            run_bus.curator_pre_clusters = {
                **meta_common,
                "wall_seconds": 0.0,
                "rss_delta_mb": 0.0,
                "n_findings_clustered": 0,
                "n_clusters": 0,
                "clusters": [],
            }
            logger.info("pre_cluster_findings: no findings; empty record")
            return run_bus

        rss_before = _rss_mb_now()
        t0 = time.monotonic()

        finding_texts = [_finding_text(f) for f in text_source]
        finding_matrix = _cosine_normalized(emb.embed_batch(finding_texts))

        # sklearn AgglomerativeClustering requires n_samples >= 2; handle 1.
        if len(findings) == 1:
            labels = np.array([0], dtype=np.int32)
        else:
            labels = _run_agglomerative(
                finding_matrix,
                distance_threshold=closure_distance,
                linkage=closure_linkage,
                metric=closure_metric,
            )

        clusters = _format_clusters(labels)

        wall = time.monotonic() - t0
        rss_after = _rss_mb_now()
        rss_delta = max(0.0, rss_after - rss_before)

        run_bus.curator_pre_clusters = {
            **meta_common,
            "wall_seconds": round(wall, 3),
            "rss_delta_mb": round(rss_delta, 1),
            "n_findings_clustered": len(findings),
            "n_clusters": len(clusters),
            "clusters": clusters,
        }
        logger.info(
            "pre_cluster_findings: %d findings → %d clusters in %.2fs (RSS Δ %.0f MB)",
            len(findings), len(clusters), wall, rss_delta,
        )
        return run_bus

    return pre_cluster_findings


pre_cluster_findings = make_pre_cluster_findings()


__all__ = [
    "ALGORITHM",
    "DISTANCE_THRESHOLD",
    "LINKAGE",
    "METRIC",
    "make_pre_cluster_findings",
    "pre_cluster_findings",
]
