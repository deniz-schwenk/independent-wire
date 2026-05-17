"""Tests for the cluster-level gravitation sweep harness.

Covers the pure helpers in `scripts/sweep_cluster_level_gravitation.py`:
- centroid math (L2-normalised mean of L2-normalised vectors)
- cluster_assign determinism + single/multi semantics
- propagate_to_findings cap behaviour
- apply_fallback for both orphan and finding_level branches
- baseline finding-level recovers Brief 5b's existing semantics
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.sweep_cluster_level_gravitation import (  # noqa: E402
    PER_FINDING_CAP,
    apply_fallback,
    baseline_finding_level,
    cluster_assign,
    compute_cluster_centroids,
    propagate_to_findings,
)


# ── compute_cluster_centroids ─────────────────────────────────────────────


def test_centroid_is_l2_normalised_mean():
    """Three known L2-normalised vectors at (1,0,0), (0,1,0), (1,1,0)/√2 — the
    arithmetic mean is ((1+0+1/√2)/3, (0+1+1/√2)/3, 0), with magnitude < 1,
    so the L2-normalised centroid must have unit norm and the expected
    direction."""
    findings_mat = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0 / np.sqrt(2), 1.0 / np.sqrt(2), 0.0],
        ]
    )
    clusters = [{"id": "mc-000", "size": 3, "source_ids": ["finding-0", "finding-1", "finding-2"]}]
    centroids = compute_cluster_centroids(findings_mat, clusters)

    assert centroids.shape == (1, 3)
    # Unit norm
    np.testing.assert_allclose(np.linalg.norm(centroids[0]), 1.0, atol=1e-12)
    # Symmetric in x/y (both inputs are biased toward those axes equally)
    assert centroids[0, 0] == pytest.approx(centroids[0, 1], abs=1e-12)
    # Third component is exactly zero
    assert centroids[0, 2] == pytest.approx(0.0, abs=1e-12)


def test_centroid_handles_empty_cluster_safely():
    """An empty cluster should produce a zero row (which we leave as the
    zero vector — the divide-by-zero guard keeps it as zeros)."""
    findings_mat = np.array([[1.0, 0.0], [0.0, 1.0]])
    clusters = [
        {"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]},
        {"id": "mc-001", "size": 0, "source_ids": []},
    ]
    centroids = compute_cluster_centroids(findings_mat, clusters)
    assert centroids.shape == (2, 2)
    np.testing.assert_allclose(np.linalg.norm(centroids[0]), 1.0, atol=1e-12)
    np.testing.assert_array_equal(centroids[1], [0.0, 0.0])


def test_centroid_per_cluster_uses_correct_indices():
    """Two clusters drawing from disjoint finding indices produce centroids
    that match each cluster's local mean — not a global mean."""
    findings_mat = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [-1.0, 0.0],
            [0.0, -1.0],
        ]
    )
    clusters = [
        {"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]},
        {"id": "mc-001", "size": 2, "source_ids": ["finding-2", "finding-3"]},
    ]
    centroids = compute_cluster_centroids(findings_mat, clusters)
    # Cluster 0 mean = (0.5, 0.5) → normalised = (1/√2, 1/√2)
    expected_0 = np.array([1.0 / np.sqrt(2), 1.0 / np.sqrt(2)])
    np.testing.assert_allclose(centroids[0], expected_0, atol=1e-12)
    # Cluster 1 mean = (-0.5, -0.5) → normalised = (-1/√2, -1/√2)
    expected_1 = -expected_0
    np.testing.assert_allclose(centroids[1], expected_1, atol=1e-12)


# ── cluster_assign ────────────────────────────────────────────────────────


# Synthetic 4-cluster × 3-topic similarity matrix used by several tests
SYNTH_SIM = np.array(
    [
        [0.90, 0.40, 0.10],  # C0: clear best at T0
        [0.70, 0.70, 0.10],  # C1: tied at T0 and T1
        [0.60, 0.40, 0.30],  # C2: best at T0
        [0.20, 0.30, 0.40],  # C3: all below 0.5
    ]
)


def test_cluster_assign_single_T_0_5():
    """Single-mode: C0→T0, C1→T0 (np.argmax breaks ties to lowest idx),
    C2→T0, C3 orphan."""
    result = cluster_assign(SYNTH_SIM, T=0.5, mode="single")
    assert result == [[0], [0], [0], []]


def test_cluster_assign_multi_T_0_5():
    """Multi-mode: C0→[0], C1→[0,1], C2→[0], C3→[]."""
    result = cluster_assign(SYNTH_SIM, T=0.5, mode="multi")
    assert result == [[0], [0, 1], [0], []]


def test_cluster_assign_high_T_orphans_all():
    """At T=0.95, only C0[T0]=0.90 is closest but still below — all orphan."""
    result_single = cluster_assign(SYNTH_SIM, T=0.95, mode="single")
    result_multi = cluster_assign(SYNTH_SIM, T=0.95, mode="multi")
    assert result_single == [[], [], [], []]
    assert result_multi == [[], [], [], []]


def test_cluster_assign_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        cluster_assign(SYNTH_SIM, T=0.5, mode="bogus")


def test_cluster_assign_deterministic_repeated_runs():
    """Two consecutive calls with identical inputs produce identical outputs."""
    r1 = cluster_assign(SYNTH_SIM, T=0.5, mode="single")
    r2 = cluster_assign(SYNTH_SIM, T=0.5, mode="single")
    r3 = cluster_assign(SYNTH_SIM, T=0.5, mode="multi")
    r4 = cluster_assign(SYNTH_SIM, T=0.5, mode="multi")
    assert r1 == r2
    assert r3 == r4


# ── propagate_to_findings + cap ──────────────────────────────────────────


SYNTH_CLUSTERS = [
    {"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]},
    {"id": "mc-001", "size": 3, "source_ids": ["finding-2", "finding-3", "finding-4"]},
    {"id": "mc-002", "size": 2, "source_ids": ["finding-5", "finding-6"]},
    {"id": "mc-003", "size": 2, "source_ids": ["finding-7", "finding-8"]},
]


def test_propagate_single_mode_assigns_clusters_findings_to_one_topic():
    """C0→T0, C1→T0, C2→T0, C3 orphan. Findings 0-6 each get [0]; 7,8 get []."""
    cluster_assignments = cluster_assign(SYNTH_SIM, T=0.5, mode="single")
    result = propagate_to_findings(
        cluster_assignments, SYNTH_CLUSTERS, n_findings=9, cluster_topic_sim=SYNTH_SIM
    )
    assert result == [[0], [0], [0], [0], [0], [0], [0], [], []]


def test_propagate_multi_mode_assigns_clusters_findings_to_all_topics():
    """C0→[0], C1→[0,1], C2→[0], C3→[]. Findings 2,3,4 inherit both T0 and T1."""
    cluster_assignments = cluster_assign(SYNTH_SIM, T=0.5, mode="multi")
    result = propagate_to_findings(
        cluster_assignments, SYNTH_CLUSTERS, n_findings=9, cluster_topic_sim=SYNTH_SIM
    )
    assert result == [[0], [0], [0, 1], [0, 1], [0, 1], [0], [0], [], []]


def test_propagate_caps_to_top_k_by_sim():
    """When multi-mode assigns more than cap=3 topics, keep the 3 highest-sim."""
    # 1 cluster × 5 topics; sims chosen so [T1, T3, T0] are the top 3 by sim
    wide_sim = np.array([[0.51, 0.95, 0.52, 0.80, 0.30]])
    clusters = [{"id": "mc-000", "size": 1, "source_ids": ["finding-0"]}]
    ca = cluster_assign(wide_sim, T=0.5, mode="multi")
    assert ca == [[0, 1, 2, 3]]  # 4 topics above 0.5
    result = propagate_to_findings(ca, clusters, n_findings=1, cluster_topic_sim=wide_sim, cap=3)
    # Top 3 by sim: T1=0.95, T3=0.80, T2=0.52 → sorted ascending: [1, 2, 3]
    assert result == [[1, 2, 3]]


# ── apply_fallback ────────────────────────────────────────────────────────


def test_fallback_orphan_keeps_zero_assignments():
    finding_to_topics = [[0], [], [1, 2], []]
    # Finding-topic sim irrelevant for orphan-fallback
    ft_sim = np.zeros((4, 3))
    result = apply_fallback(finding_to_topics, ft_sim, fallback="orphan")
    assert result == [[0], [], [1, 2], []]


def test_fallback_finding_level_re_assigns_only_orphaned_findings():
    """Finding 1 (orphaned by cluster) gets re-assigned via finding-level
    T=0.55; finding 3 stays orphan because all its individual sims are
    below 0.55."""
    finding_to_topics = [[0], [], [1, 2], []]
    ft_sim = np.array(
        [
            [0.30, 0.30, 0.30],  # finding 0 — already assigned via cluster
            [0.70, 0.40, 0.20],  # finding 1 — fallback picks T0 (0.70 ≥ 0.55)
            [0.10, 0.10, 0.10],  # finding 2 — already assigned via cluster
            [0.40, 0.40, 0.40],  # finding 3 — no individual sim ≥ 0.55, stays orphan
        ]
    )
    result = apply_fallback(finding_to_topics, ft_sim, fallback="finding_level", fallback_T=0.55)
    assert result == [[0], [0], [1, 2], []]


def test_fallback_finding_level_respects_cap_for_re_assignment():
    """A finding orphaned by cluster but with 5 above-threshold individual
    sims keeps only the top 3."""
    finding_to_topics = [[]]
    ft_sim = np.array([[0.95, 0.55, 0.80, 0.60, 0.70]])
    result = apply_fallback(finding_to_topics, ft_sim, fallback="finding_level", fallback_T=0.55, cap=3)
    # Top 3 by sim: T0=0.95, T2=0.80, T4=0.70 → sorted ascending: [0, 2, 4]
    assert result == [[0, 2, 4]]


def test_fallback_unknown_raises():
    with pytest.raises(ValueError, match="unknown fallback"):
        apply_fallback([[]], np.zeros((1, 1)), fallback="bogus")


# ── All four mode × fallback combinations are distinct on synthetic input ─


def test_four_mode_fallback_combinations_produce_distinct_outputs():
    """End-to-end: same (cluster sim, finding sim) → four (mode, fallback)
    pairs yield four different per-finding assignment lists."""
    # 4 clusters × 3 topics, same as SYNTH_SIM.
    cluster_sim = SYNTH_SIM
    # Finding-level sim — C3's findings (7,8) get individual sim ≥ 0.55 to T2,
    # so fallback=finding_level rescues them.
    ft_sim = np.array(
        [
            [0.95, 0.20, 0.10],  # f0 in C0
            [0.95, 0.20, 0.10],  # f1 in C0
            [0.70, 0.80, 0.10],  # f2 in C1
            [0.70, 0.80, 0.10],  # f3 in C1
            [0.70, 0.80, 0.10],  # f4 in C1
            [0.65, 0.30, 0.20],  # f5 in C2
            [0.65, 0.30, 0.20],  # f6 in C2
            [0.30, 0.20, 0.60],  # f7 in C3 — fallback rescues to T2
            [0.30, 0.20, 0.60],  # f8 in C3 — fallback rescues to T2
        ]
    )

    def run(mode: str, fb: str) -> list[list[int]]:
        ca = cluster_assign(cluster_sim, T=0.5, mode=mode)
        f2t = propagate_to_findings(ca, SYNTH_CLUSTERS, n_findings=9, cluster_topic_sim=cluster_sim)
        return apply_fallback(f2t, ft_sim, fallback=fb, fallback_T=0.55, cap=3)

    single_orphan = run("single", "orphan")
    single_fl = run("single", "finding_level")
    multi_orphan = run("multi", "orphan")
    multi_fl = run("multi", "finding_level")

    # Single + orphan: C3 findings orphaned
    assert single_orphan == [[0], [0], [0], [0], [0], [0], [0], [], []]
    # Single + finding_level: C3 findings rescued to T2
    assert single_fl == [[0], [0], [0], [0], [0], [0], [0], [2], [2]]
    # Multi + orphan: C1 findings get both T0 and T1
    assert multi_orphan == [[0], [0], [0, 1], [0, 1], [0, 1], [0], [0], [], []]
    # Multi + finding_level: C3 findings rescued to T2
    assert multi_fl == [[0], [0], [0, 1], [0, 1], [0, 1], [0], [0], [2], [2]]


# ── baseline matches Brief 5b semantics ───────────────────────────────────


def test_baseline_finding_level_pure_finding_assignments():
    """No cluster involvement — every finding with sim ≥ T to a topic gets
    that topic, capped at PER_FINDING_CAP, output sorted ascending."""
    ft_sim = np.array(
        [
            [0.60, 0.20, 0.10],  # f0 → [0]
            [0.60, 0.60, 0.60],  # f1 → [0,1,2]
            [0.30, 0.30, 0.30],  # f2 → []
            [0.95, 0.60, 0.55],  # f3 → [0,1,2] (all above T)
        ]
    )
    result = baseline_finding_level(ft_sim, T=0.55, cap=3)
    assert result == [[0], [0, 1, 2], [], [0, 1, 2]]


def test_baseline_caps_at_per_finding_cap():
    """A finding above T to 4 topics keeps the 3 highest-sim topics."""
    ft_sim = np.array([[0.55, 0.95, 0.80, 0.70, 0.60]])
    result = baseline_finding_level(ft_sim, T=0.55, cap=3)
    # Top 3 by sim: T1=0.95, T2=0.80, T3=0.70 → sorted ascending: [1, 2, 3]
    assert result == [[1, 2, 3]]
