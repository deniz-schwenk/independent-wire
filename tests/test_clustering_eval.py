"""Smoke + determinism tests for the isolated clustering-eval harness.

The harness lives in ``scripts/eval_clustering.py`` and is NOT part of the
production import graph. These tests exercise its clustering primitives
(``_run_hdbscan``, ``_run_agglomerative``) on a synthetic fixture so they
don't depend on any real-data state files.

Synthetic fixture (per TASK-CLUSTERING-EVAL §Tests): 100 findings = 3 known
Gaussian-blob clusters in embedding space + 20 uniformly-distributed noise
points. The eval harness's HDBSCAN at the ``hdb-balanced`` configuration
should recover the 3 dense clusters and assign the noise points to the noise
class. Re-running on the same input must produce bit-identical labels.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest


def _load_eval_module():
    """Import scripts/eval_clustering.py without adding it to the production
    import graph. We resolve by path so the test doesn't depend on a package
    layout that doesn't exist."""
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "eval_clustering_harness", repo / "scripts" / "eval_clustering.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eval_clustering_harness"] = mod
    spec.loader.exec_module(mod)
    return mod


def _synthetic_fixture(seed: int = 7) -> np.ndarray:
    """100 findings: 3 Gaussian blobs of 30 + 20 random noise. L2-normalised
    so cosine == euclidean on this matrix (matches the eval pipeline)."""
    rng = np.random.default_rng(seed)
    # Three well-separated centers in 16-dim space
    centers = np.array(
        [
            [4.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 4.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 4.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ],
        dtype=np.float64,
    )
    blobs = []
    for c in centers:
        blob = c + rng.normal(0.0, 0.15, size=(30, 16))
        blobs.append(blob)
    noise = rng.uniform(-1.5, 1.5, size=(20, 16))
    matrix = np.vstack(blobs + [noise])
    # L2-normalise rows
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return matrix / norms


def test_hdbscan_balanced_recovers_three_clusters():
    """HDBSCAN at hdb-balanced should recover all 3 blobs as distinct
    clusters and send most noise points to the -1 noise class."""
    mod = _load_eval_module()
    embeddings = _synthetic_fixture()
    params = mod.HDBSCAN_CONFIGS["hdb-balanced"]
    labels = mod._run_hdbscan(embeddings, params)
    # 3 blobs × 30 + 20 noise = 110 findings
    assert labels.shape == (110,)

    non_noise = labels[labels != -1]
    cluster_ids = sorted(set(non_noise.tolist()))
    assert len(cluster_ids) >= 3, (
        f"expected ≥3 non-noise clusters, got {len(cluster_ids)}: {Counter(non_noise.tolist())}"
    )

    # Each of the 3 blobs (indices 0..29, 30..59, 60..89) should be
    # dominated by a single cluster label.
    for blob_start in (0, 30, 60):
        blob_labels = labels[blob_start : blob_start + 30]
        non_noise_blob = [int(x) for x in blob_labels if x != -1]
        assert non_noise_blob, f"blob starting at {blob_start} entirely in noise"
        majority = Counter(non_noise_blob).most_common(1)[0]
        # The dominant cluster owns at least 80% of the blob's non-noise points
        assert majority[1] >= 0.8 * len(non_noise_blob), (
            f"blob starting at {blob_start} split: {Counter(non_noise_blob)}"
        )

    # Noise points (indices 90..109) should mostly land in the noise class.
    # With hdb-balanced (min_cluster_size=10, epsilon=0.10) the 20 uniformly-
    # distributed noise points are too sparse to form their own cluster — we
    # expect most to be classified as noise (-1).
    noise_assignment = labels[90:110]
    noise_in_noise_class = int((noise_assignment == -1).sum())
    assert noise_in_noise_class >= 10, (
        f"only {noise_in_noise_class}/20 noise points landed in -1; "
        f"distribution: {Counter(noise_assignment.tolist())}"
    )


def test_hdbscan_is_deterministic():
    """Re-running HDBSCAN on the same input produces bit-identical labels."""
    mod = _load_eval_module()
    embeddings = _synthetic_fixture()
    params = mod.HDBSCAN_CONFIGS["hdb-balanced"]
    labels_a = mod._run_hdbscan(embeddings, params)
    labels_b = mod._run_hdbscan(embeddings, params)
    np.testing.assert_array_equal(labels_a, labels_b)


def test_agglomerative_is_deterministic():
    """Re-running Agglomerative on the same input produces bit-identical labels."""
    mod = _load_eval_module()
    embeddings = _synthetic_fixture()
    params = mod.AGG_CONFIGS["agg-balanced"]
    labels_a = mod._run_agglomerative(embeddings, params)
    labels_b = mod._run_agglomerative(embeddings, params)
    np.testing.assert_array_equal(labels_a, labels_b)


def test_per_tp_recovery_off_topic_placement():
    """Synthetic test of the per-TP recovery primitive. Create a cluster
    assignment that gives an obvious recovery scenario and verify the
    F1/precision/recall + off-topic placement math is correct."""
    mod = _load_eval_module()
    # Cluster labels: 5 findings in cluster 0, 5 in cluster 1, 3 in noise (-1)
    cluster_labels = np.array(
        [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, -1, -1, -1], dtype=np.int32
    )
    # Labelled findings: 5 on-topic (all in cluster 0), 5 off-topic (3 in
    # cluster 1, 2 in noise)
    labelled = {
        "finding-0": 1, "finding-1": 1, "finding-2": 1, "finding-3": 1, "finding-4": 1,
        "finding-5": 0, "finding-6": 0, "finding-7": 0,  # cluster 1 (other)
        "finding-10": 0, "finding-11": 0,                  # noise
    }
    rec = mod._per_tp_recovery(cluster_labels, labelled, tp_cluster_index=99)
    assert rec["n_on_topic"] == 5
    assert rec["n_off_topic"] == 5
    assert rec["recovered_cluster_id"] == 0
    # All 5 on-topic in recovered cluster; no off-topic in it
    assert rec["recall"] == 1.0
    assert rec["precision"] == 1.0
    assert rec["f1"] == 1.0
    placement = rec["off_topic_placement"]
    assert placement["n"] == 5
    assert placement["n_co_located_with_on_topic"] == 0
    assert placement["n_in_noise"] == 2
    assert placement["n_in_other_clusters"] == 3


def test_per_tp_recovery_handles_no_on_topic():
    """If the labelled set has no on-topic findings for a TP, recovery
    fields return None but off-topic placement is still emitted."""
    mod = _load_eval_module()
    cluster_labels = np.array([0, 0, 1, -1], dtype=np.int32)
    labelled = {f"finding-{i}": 0 for i in range(4)}
    rec = mod._per_tp_recovery(cluster_labels, labelled, tp_cluster_index=0)
    assert rec["recall"] is None and rec["precision"] is None and rec["f1"] is None
    assert rec["off_topic_placement"]["n"] == 4
