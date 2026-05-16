"""Singleton-surface tests for ``src/stages/coherence.py``.

The Brief 5 triple-stage Curator cutover removed the
``measure_cluster_coherence`` stage callable and its daily-report
renderer. The **file** stays — three downstream stages
(``pre_cluster_findings``, ``gravitational_assign``,
``CuratorTopicDiscoveryStage``) import the fastembed singleton +
``_cosine_normalised`` helper from it. These tests cover that surface;
the deleted stage's behavioural tests are gone with the stage.

For end-to-end exercise of the singleton on the real fastembed model,
see ``test_pre_cluster_stage.py::test_multilingual_clustering_real_model``
and the corresponding tests in ``test_gravitational_assign_stage.py``
and ``test_curator_topic_discovery_stage.py``.
"""

from __future__ import annotations

import numpy as np

from src.stages.coherence import (
    DEFAULT_BATCH_SIZE,
    FASTEMBED_VERSION_REQUIRED,
    FastembedEmbedder,
    MODEL_NAME,
    THRESHOLD_BANDS,
    _cosine_normalized,
    _finding_index_from_source_id,
    _get_default_embedder,
)


# ---------------------------------------------------------------------------
# 1. Pinned model + version surface (load-bearing for reproducibility)
# ---------------------------------------------------------------------------


def test_pinned_model_name():
    """The model + fastembed version are part of the reproducibility
    contract — Brief 1's clustering eval and Brief 2's gravitational
    calibration are anchored on this exact (model, version) pair."""
    assert MODEL_NAME == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert FASTEMBED_VERSION_REQUIRED == "0.8.0"


def test_pinned_default_batch_size():
    """Batch size affects ONNX inference throughput; pinned for the
    deterministic per-call timing the singleton consumers reason
    about."""
    assert DEFAULT_BATCH_SIZE == 32


def test_threshold_bands_pinned():
    """THRESHOLD_BANDS are a calibration-axis constant — preserved for
    any future passive-coherence stage revival."""
    assert THRESHOLD_BANDS[0] == 0.20
    assert THRESHOLD_BANDS[-1] == 0.70
    assert all(
        THRESHOLD_BANDS[i] < THRESHOLD_BANDS[i + 1]
        for i in range(len(THRESHOLD_BANDS) - 1)
    )


# ---------------------------------------------------------------------------
# 2. Singleton — one instance per process across all four consumers
# ---------------------------------------------------------------------------


def test_get_default_embedder_returns_same_instance():
    """Calling ``_get_default_embedder()`` twice returns the same object;
    Briefs 1/2/4 all reach for this singleton so the fastembed ONNX
    session is loaded once per process."""
    a = _get_default_embedder()
    b = _get_default_embedder()
    assert a is b
    assert isinstance(a, FastembedEmbedder)


def test_default_embedder_carries_pinned_model_name():
    emb = _get_default_embedder()
    assert emb.model_name == MODEL_NAME


# ---------------------------------------------------------------------------
# 3. Cosine helper — pure function shared with all consumers
# ---------------------------------------------------------------------------


def test_cosine_normalized_unit_rows():
    m = np.array([[3.0, 4.0], [0.0, 0.0], [1.0, 0.0]])
    n = _cosine_normalized(m)
    # row 0: 3/5, 4/5
    assert np.allclose(n[0], [0.6, 0.8])
    # row 1: zero-norm passes through unchanged
    assert np.allclose(n[1], [0.0, 0.0])
    # row 2: already unit
    assert np.allclose(n[2], [1.0, 0.0])


def test_cosine_normalized_returns_l2_unit_rows():
    rng = np.random.default_rng(0)
    m = rng.normal(0.0, 1.0, size=(20, 8))
    n = _cosine_normalized(m)
    norms = np.linalg.norm(n, axis=1)
    # Every non-zero row should have unit L2 norm
    assert np.allclose(norms, 1.0, atol=1e-9)


# ---------------------------------------------------------------------------
# 4. finding-NNN → index helper (used by deleted stage; kept as harmless
#    pure utility in case future tooling reuses the convention)
# ---------------------------------------------------------------------------


def test_finding_index_from_source_id():
    assert _finding_index_from_source_id("finding-0") == 0
    assert _finding_index_from_source_id("finding-42") == 42
    assert _finding_index_from_source_id("not-a-finding") is None
    assert _finding_index_from_source_id("") is None
