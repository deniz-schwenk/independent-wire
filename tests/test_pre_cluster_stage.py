"""Tests for ``src/stages/pre_cluster.py`` — the embed-pre-cluster stage.

Required behavioural assertions per TASK-EMBED-PRE-CLUSTER-STAGE §Tests:

- Determinism (bit-identical labels on identical input)
- Pass-through of curator_findings (byte-identical)
- Synthetic separation (three well-separated topic groups → three clusters)
- Empty findings list (no crash, n_clusters=0)
- Single finding (one cluster of size 1)
- Multilingual sanity using the real fastembed model (covers the
  production language set in practice — same convention as
  tests/test_coherence_stage.py::test_multilingual_ranking_real_model)

The real-model test loads fastembed
(``paraphrase-multilingual-MiniLM-L12-v2``) once per session. First run
downloads ~240 MB to the fastembed cache; subsequent runs are cached.
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Sequence

import numpy as np

from src.bus import RunBus
from src.stage import get_stage_meta
from src.stages.pre_cluster import (
    ALGORITHM,
    DISTANCE_THRESHOLD,
    LINKAGE,
    METRIC,
    _finding_text,
    _format_clusters,
    _run_agglomerative,
    make_pre_cluster_findings,
    pre_cluster_findings,
)


# ---------------------------------------------------------------------------
# Fake embedder: three well-separated topic groups in 4-dim space.
# Mirrors tests/test_coherence_stage.py::IranPeaceTrumpEmbedder pattern.
# ---------------------------------------------------------------------------


class ThreeGroupEmbedder:
    """Deterministic 4-dim embedder. Each finding's text hits exactly
    one signal dim:

    - dim 0: ``iran`` tokens (across EN / KR / AR / FA)
    - dim 1: ``climate`` tokens (across EN / KR / AR / FA)
    - dim 2: ``sports`` tokens (across EN / KR / AR / FA)
    - dim 3: noise fallback

    L2-normalised, cosine-distance between groups is √2; between same-
    group findings it is 0. Cluster boundaries are crisp at any
    distance_threshold in (0, √2) ≈ (0, 1.41)."""

    model_name = "fake-three-group"

    _SIGNALS: dict[int, tuple[str, ...]] = {
        0: ("iran", "이란", "إيران", "ایران"),
        1: ("climate", "기후", "مناخ", "اقلیم"),
        2: ("sports", "축구", "كرة", "ورزش"),
    }

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        out: list[list[float]] = []
        for t in texts:
            tl = t.lower()
            v = [0.0, 0.0, 0.0, 0.0]
            for dim, kws in self._SIGNALS.items():
                for kw in kws:
                    if kw.lower() in tl:
                        v[dim] = 1.0
                        break
            if v == [0.0, 0.0, 0.0, 0.0]:
                v[3] = 1.0
            out.append(v)
        return np.asarray(out, dtype=np.float64)


def _make_rb(findings: list[dict], run_date: str = "2026-05-15") -> RunBus:
    return RunBus(
        run_id="run-2026-05-15-test1234",
        run_date=run_date,
        curator_findings=findings,
    )


def _run_stage(stage, rb: RunBus) -> RunBus:
    return asyncio.run(stage(rb))


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------


def test_determinism_two_runs():
    """Two consecutive stage runs on identical input produce identical
    cluster assignments. Bit-identical — strip timing fields before
    comparison."""
    findings = [
        {"title": "Iran peace deal", "summary": ""},
        {"title": "Climate accord signed", "summary": ""},
        {"title": "Sports match upset", "summary": ""},
        {"title": "Iran sanctions response", "summary": ""},
        {"title": "Climate funding announced", "summary": ""},
        {"title": "Sports league changes", "summary": ""},
    ]
    stage = make_pre_cluster_findings(
        embedder=ThreeGroupEmbedder(),
        distance_threshold=0.5,  # tuned for 4-dim fake (cross-group dist √2)
    )
    rb1 = _make_rb(copy.deepcopy(findings))
    rb2 = _make_rb(copy.deepcopy(findings))
    out1 = _run_stage(stage, rb1)
    out2 = _run_stage(stage, rb2)

    def _stable(c: dict) -> dict:
        return {k: v for k, v in c.items() if k not in {"wall_seconds", "rss_delta_mb"}}

    assert _stable(out1.curator_pre_clusters) == _stable(out2.curator_pre_clusters)


# ---------------------------------------------------------------------------
# 2. Pass-through of curator_findings
# ---------------------------------------------------------------------------


def test_passthrough_curator_findings_byte_identical():
    """The stage adds the new slot but does not mutate the upstream
    input. ``curator_findings`` is byte-identical before and after."""
    findings = [
        {"title": "Iran rejects deal", "summary": "tensions"},
        {"title": "Climate accord", "summary": "Paris"},
        {"title": "Sports match", "summary": "upset"},
    ]
    rb = _make_rb(findings)
    findings_snapshot = copy.deepcopy(rb.curator_findings)
    findings_json_before = json.dumps(findings_snapshot, sort_keys=True)

    stage = make_pre_cluster_findings(
        embedder=ThreeGroupEmbedder(), distance_threshold=0.5
    )
    rb_out = _run_stage(stage, rb)

    assert json.dumps(rb_out.curator_findings, sort_keys=True) == findings_json_before
    assert rb_out.curator_pre_clusters
    assert rb_out.curator_pre_clusters["n_clusters"] == 3
    # JSON-serialisable result
    json.dumps(rb_out.curator_pre_clusters)


# ---------------------------------------------------------------------------
# 3. Synthetic separation — three well-separated topic groups
# ---------------------------------------------------------------------------


def test_synthetic_three_groups_separate():
    """Three groups of two findings each → three clusters of size 2 each.
    Each cluster's members are from the same topic group."""
    findings = [
        # Iran (indices 0, 1)
        {"title": "Iran peace deal", "summary": ""},
        {"title": "Iran sanctions", "summary": ""},
        # Climate (indices 2, 3)
        {"title": "Climate accord", "summary": ""},
        {"title": "Climate report", "summary": ""},
        # Sports (indices 4, 5)
        {"title": "Sports league change", "summary": ""},
        {"title": "Sports match upset", "summary": ""},
    ]
    stage = make_pre_cluster_findings(
        embedder=ThreeGroupEmbedder(), distance_threshold=0.5
    )
    out = _run_stage(stage, _make_rb(findings))
    pc = out.curator_pre_clusters
    assert pc["n_clusters"] == 3, pc
    assert sorted(c["size"] for c in pc["clusters"]) == [2, 2, 2]
    expected_groups = ({0, 1}, {2, 3}, {4, 5})
    seen = set()
    for cluster in pc["clusters"]:
        indices = frozenset(
            int(sid.split("finding-")[-1]) for sid in cluster["source_ids"]
        )
        assert set(indices) in expected_groups, indices
        seen.add(indices)
    assert len(seen) == 3, seen


# ---------------------------------------------------------------------------
# 4. Empty findings list
# ---------------------------------------------------------------------------


def test_empty_findings_list_no_crash():
    """A run with no findings populates the slot with n_clusters=0
    and an empty cluster list — no embedder call, no crash."""

    class _CrashEmbedder:
        model_name = "should-not-be-called"

        def embed_batch(self, texts):  # pragma: no cover
            raise AssertionError("embedder must not be called when no findings")

    stage = make_pre_cluster_findings(embedder=_CrashEmbedder())
    out = _run_stage(stage, _make_rb([]))
    pc = out.curator_pre_clusters
    assert pc["n_findings_clustered"] == 0
    assert pc["n_clusters"] == 0
    assert pc["clusters"] == []
    # Metadata still populated
    assert pc["algorithm"] == ALGORITHM
    assert pc["params"]["distance_threshold"] == DISTANCE_THRESHOLD


# ---------------------------------------------------------------------------
# 5. Single finding
# ---------------------------------------------------------------------------


def test_single_finding_one_cluster():
    """One finding → one cluster of size 1 (sklearn won't fit n=1, so
    the stage short-circuits to a hand-rolled label array)."""
    rb = _make_rb([{"title": "Solo finding about Iran", "summary": ""}])
    stage = make_pre_cluster_findings(
        embedder=ThreeGroupEmbedder(), distance_threshold=0.5
    )
    out = _run_stage(stage, rb)
    pc = out.curator_pre_clusters
    assert pc["n_findings_clustered"] == 1
    assert pc["n_clusters"] == 1
    cluster = pc["clusters"][0]
    assert cluster["id"] == "mc-000"
    assert cluster["size"] == 1
    assert cluster["source_ids"] == ["finding-0"]


# ---------------------------------------------------------------------------
# 6. Multilingual sanity — real fastembed model
# ---------------------------------------------------------------------------


def test_multilingual_clustering_real_model():
    """The real fastembed model groups a non-Latin-script Iran-related
    finding with its Latin-script semantic equivalent, and keeps the
    off-topic Hantavirus finding in a separate cluster — under the
    production distance_threshold (0.7)."""
    # Default factory → singleton shared with coherence.py. The first
    # call across the test session downloads ~240 MB; subsequent calls
    # reuse the cached model.
    stage = make_pre_cluster_findings()

    findings = [
        {
            "title": "US-Iran peace talks fail",
            "summary": "Trump rejects Iranian proposal; tensions rise across the Gulf.",
        },
        {
            "title": "이란, 미국의 평화 제안 거부",
            "summary": "트럼프의 제안에 강경 대응하며 긴장이 고조되고 있다.",
        },
        {
            "title": "Hantavirus cruise outbreak",
            "summary": "French passenger evacuated after symptoms onset on a cruise.",
        },
    ]
    rb = _make_rb(findings)
    out = _run_stage(stage, rb)
    clusters = out.curator_pre_clusters["clusters"]

    fid_to_cluster: dict[int, str] = {}
    for c in clusters:
        for sid in c["source_ids"]:
            fid_to_cluster[int(sid.split("finding-")[-1])] = c["id"]

    # The EN-Iran and KR-Iran findings cluster together under the
    # production threshold; off-topic does not co-cluster with them.
    assert fid_to_cluster[0] == fid_to_cluster[1], (
        f"EN-Iran and KR-Iran did not merge: {fid_to_cluster}"
    )
    assert fid_to_cluster[2] != fid_to_cluster[0], (
        f"Hantavirus co-clustered with Iran: {fid_to_cluster}"
    )


# ---------------------------------------------------------------------------
# 7. Stage metadata
# ---------------------------------------------------------------------------


def test_stage_metadata():
    """The default stage closure carries the expected reads/writes
    so the runner can introspect it."""
    meta = get_stage_meta(pre_cluster_findings)
    assert meta.kind == "run"
    # curator_findings_clustering added by TASK-CLUSTER-TRANSLATE-SIDECAR — the
    # stage embeds the English-normalised text when the flag-gated sidecar
    # populated that slot, else falls through to native curator_findings.
    assert set(meta.reads) == {"curator_findings", "curator_findings_clustering"}
    assert meta.writes == ("curator_pre_clusters",)


# ---------------------------------------------------------------------------
# 8. Bus slot metadata
# ---------------------------------------------------------------------------


def test_bus_slot_metadata():
    """The new RunBus slot is internal-visibility and optional-write."""
    from src.bus import RunBus as _RB

    field = _RB.model_fields["curator_pre_clusters"]
    extra = field.json_schema_extra or {}
    assert extra.get("visibility") == ["internal"]
    assert extra.get("optional_write") is True


# ---------------------------------------------------------------------------
# 9. Output ordering — size desc, smallest-finding-index tie-break
# ---------------------------------------------------------------------------


def test_clusters_sorted_size_desc_with_id_tiebreak():
    """Clusters in the output are sorted by size desc, with smallest-
    finding-index as the tie-break. mc-IDs reflect that ordering."""
    findings = [
        # Climate group: 2 findings (indices 0, 1) — earliest start
        {"title": "Climate report", "summary": ""},
        {"title": "Climate funding", "summary": ""},
        # Iran group: 3 findings (indices 2, 3, 4) — largest cluster
        {"title": "Iran peace", "summary": ""},
        {"title": "Iran sanctions", "summary": ""},
        {"title": "Iran response", "summary": ""},
        # Sports group: 2 findings (indices 5, 6) — same size as climate
        {"title": "Sports match", "summary": ""},
        {"title": "Sports league", "summary": ""},
    ]
    stage = make_pre_cluster_findings(
        embedder=ThreeGroupEmbedder(), distance_threshold=0.5
    )
    out = _run_stage(stage, _make_rb(findings))
    clusters = out.curator_pre_clusters["clusters"]

    # mc-000: Iran (size 3)
    assert clusters[0]["id"] == "mc-000"
    assert clusters[0]["size"] == 3
    assert clusters[0]["source_ids"] == ["finding-2", "finding-3", "finding-4"]

    # mc-001: Climate (size 2, smaller-index tiebreak vs Sports)
    assert clusters[1]["id"] == "mc-001"
    assert clusters[1]["size"] == 2
    assert clusters[1]["source_ids"] == ["finding-0", "finding-1"]

    # mc-002: Sports (size 2)
    assert clusters[2]["id"] == "mc-002"
    assert clusters[2]["size"] == 2
    assert clusters[2]["source_ids"] == ["finding-5", "finding-6"]


# ---------------------------------------------------------------------------
# 10. Pure-helper unit tests
# ---------------------------------------------------------------------------


def test_finding_text_matches_eval_harness():
    """The concatenation rule is identical to the eval harness so the
    production stage's embeddings are bit-equivalent to the eval's."""
    f = {"title": "T", "summary": "S", "description": "D"}
    assert _finding_text(f) == "T S D"
    # On real RSS findings (description absent): identical to title + summary
    assert _finding_text({"title": "T", "summary": "S"}) == "T S"
    # Empty fields tolerated
    assert _finding_text({"title": "", "summary": "", "description": ""}) == ""


def test_run_agglomerative_returns_int_labels():
    rng = np.random.default_rng(7)
    e = rng.normal(0.0, 1.0, size=(20, 8))
    e = e / np.linalg.norm(e, axis=1, keepdims=True)
    labels = _run_agglomerative(e, distance_threshold=0.5)
    assert labels.shape == (20,)
    # All cluster labels are non-negative integers (no noise concept in
    # Agglomerative — every point belongs to a cluster)
    assert all(int(x) >= 0 for x in labels)


def test_format_clusters_sorts_by_size_then_smallest_index():
    labels = np.array([1, 1, 0, 1, 0, 0, 0], dtype=np.int32)
    # cluster 0: indices 2, 4, 5, 6 (size 4)
    # cluster 1: indices 0, 1, 3 (size 3)
    out = _format_clusters(labels)
    assert out[0] == {
        "id": "mc-000",
        "size": 4,
        "source_ids": ["finding-2", "finding-4", "finding-5", "finding-6"],
    }
    assert out[1] == {
        "id": "mc-001",
        "size": 3,
        "source_ids": ["finding-0", "finding-1", "finding-3"],
    }


def test_pinned_params():
    """The production parameters are the calibrated targets from
    CLUSTERING-EVAL-2026-05-14.md::agg-permissive — pinned at module
    level."""
    assert DISTANCE_THRESHOLD == 0.7
    assert LINKAGE == "average"
    assert METRIC == "cosine"
    assert ALGORITHM == "agglomerative"
