"""Tests for ``CuratorTopicDiscoveryStage`` — Brief 4 of the triple-stage
Curator sequence (docs/ADR-CURATOR-TRIPLE-STAGE.md).

No real LLM calls. ``FakeAgent`` returns pre-baked AgentResults; a small
synthetic embedder injects deterministic vectors so the top-K-by-
centroid compression is exact. The real-model multilingual path is
covered by ``test_pre_cluster_stage.py`` and ``test_gravitational_
assign_stage.py`` — re-running it here would not exercise anything new.

Required behavioural assertions per TASK §Tests:

- Deterministic compression — synthetic (size 12 cluster, K=8 picks the
  eight closest to the centroid, sim-desc, finding-index-asc tie-break).
- Pass-through ≤ K (size 5 cluster with K=8 emits all 5 titles).
- Cluster ordering preserved (wrapper does not re-sort clusters).
- Sample-titles ordering with a deliberate similarity tie.
- Empty-title handling (cluster of all-empty titles emits a placeholder).
- Pass-through of both upstream slots (byte-identical).
- Schema validation: mocked 25-topic response → 25 entries in slot.
- Empty pre-clusters → no LLM call, n_topics=0.
- Stage + slot metadata.
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any, Sequence

import numpy as np

from src.agent import AgentResult
from src.agent_stages import (
    SAMPLE_TITLES_PER_CLUSTER,
    CuratorTopicDiscoveryStage,
    _compress_pre_clusters_to_llm_input,
    _top_k_by_centroid,
    _topic_discovery_finding_text,
)
from src.bus import RunBus
from src.stage import get_stage_meta


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAgent:
    """Same minimal contract as tests/test_agent_stages.py::FakeAgent.

    Captures every ``run(...)`` call so the test can assert on the
    compressed input the wrapper passed to the LLM."""

    def __init__(
        self,
        *,
        structured: Any = None,
        content: str = "",
        cost_usd: float = 0.0,
        tokens_used: int = 0,
        name: str = "fake",
        model: str = "fake-model",
    ) -> None:
        self._structured = structured
        self._content = content
        self._cost_usd = cost_usd
        self._tokens_used = tokens_used
        self.name = name
        self.model = model
        self.temperature = 0.2
        self.max_tokens = 8000
        self.reasoning = "none"
        self.calls: list[dict] = []

    async def run(
        self,
        message: str = "",
        context: dict | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        self.calls.append({"message": message, "context": context, **kwargs})
        return AgentResult(
            content=self._content,
            structured=self._structured,
            cost_usd=self._cost_usd,
            tokens_used=self._tokens_used,
        )


class HashEmbedder:
    """Deterministic 4-dim embedder. Each finding's text maps to a fixed
    unit vector by keyword presence. Convenient for cluster-coherence
    tests: same-keyword findings are identical (cosine sim = 1.0)."""

    model_name = "fake-hash"

    _KEYWORDS = {
        0: ("iran", "tehran"),
        1: ("climate", "carbon"),
        2: ("sports", "football"),
    }

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for t in texts:
            tl = t.lower()
            v = [0.0, 0.0, 0.0, 0.0]
            for dim, kws in self._KEYWORDS.items():
                if any(kw in tl for kw in kws):
                    v[dim] = 1.0
                    break
            else:
                v[3] = 1.0
            rows.append(v)
        return np.asarray(rows, dtype=np.float64)


class ExplicitVectorEmbedder:
    """For the centroid-distance + tie-break tests. Each input text is a
    ``vec:<dim>:<val>:<dim>:<val>:...`` literal that the embedder parses
    into the corresponding raw vector. Vectors are L2-normalised
    downstream by the stage exactly as fastembed output is."""

    model_name = "fake-vec"

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for t in texts:
            v = [0.0, 0.0, 0.0, 0.0]
            if t.startswith("vec:"):
                tokens = t.split(":")[1:]
                for i in range(0, len(tokens), 2):
                    v[int(tokens[i])] = float(tokens[i + 1])
            rows.append(v)
        return np.asarray(rows, dtype=np.float64)


def _make_rb(
    *,
    findings: list[dict],
    pre_clusters: list[dict],
    run_date: str = "2026-05-16",
) -> RunBus:
    return RunBus(
        run_id="run-2026-05-16-test-discovery",
        run_date=run_date,
        curator_findings=findings,
        curator_pre_clusters={
            "model_name": "fake",
            "clusters": pre_clusters,
        },
    )


def _run_stage(stage, rb: RunBus) -> RunBus:
    return asyncio.run(stage(rb))


# ---------------------------------------------------------------------------
# 1. Deterministic compression — synthetic, size 12, K=8
# ---------------------------------------------------------------------------


def _l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def test_top_k_by_centroid_size_12_k_8_picks_closest_to_centroid():
    """12 unit vectors in 4-d space; expected behaviour: top-K-by-centroid
    selects the 8 with the highest cosine similarity to the cluster's
    centroid, in similarity-descending order with finding-index ascending
    as the tie-break."""
    # 8 vectors near [1,0,0,0]; 4 farther vectors mixed in
    matrix = np.array([
        _l2(np.array([1.0, 0.05, 0.0, 0.0])),   # idx 0 — near
        _l2(np.array([1.0, 0.10, 0.0, 0.0])),   # idx 1 — near
        _l2(np.array([1.0, 0.0, 0.05, 0.0])),   # idx 2 — near
        _l2(np.array([1.0, 0.0, 0.10, 0.0])),   # idx 3 — near
        _l2(np.array([0.7, 0.7, 0.0, 0.0])),    # idx 4 — far (in dim 1)
        _l2(np.array([0.7, 0.0, 0.7, 0.0])),    # idx 5 — far (in dim 2)
        _l2(np.array([1.0, 0.0, 0.0, 0.05])),   # idx 6 — near
        _l2(np.array([1.0, 0.0, 0.0, 0.10])),   # idx 7 — near
        _l2(np.array([0.5, 0.5, 0.5, 0.5])),    # idx 8 — far (diagonal)
        _l2(np.array([0.7, 0.7, 0.0, 0.0])),    # idx 9 — far (tied with 4)
        _l2(np.array([1.0, 0.02, 0.0, 0.0])),   # idx 10 — near
        _l2(np.array([1.0, 0.03, 0.0, 0.0])),   # idx 11 — near
    ], dtype=np.float64)

    selected = _top_k_by_centroid(
        list(range(12)), matrix, k=8,
    )
    # Verify size + ordering
    assert len(selected) == 8
    sims = [s for _, s in selected]
    assert sims == sorted(sims, reverse=True), sims
    # The 4 farthest vectors (idx 4, 5, 8, 9) should be dropped
    picked = {fi for fi, _ in selected}
    for far_idx in (4, 5, 8, 9):
        assert far_idx not in picked, f"far idx {far_idx} should be dropped"


def test_top_k_by_centroid_size_below_k_returns_all():
    matrix = np.array([
        _l2(np.array([1.0, 0.0, 0.0, 0.0])),
        _l2(np.array([1.0, 0.1, 0.0, 0.0])),
        _l2(np.array([0.0, 1.0, 0.0, 0.0])),
        _l2(np.array([0.0, 0.0, 1.0, 0.0])),
        _l2(np.array([0.0, 0.0, 0.0, 1.0])),
    ], dtype=np.float64)
    selected = _top_k_by_centroid([0, 1, 2, 3, 4], matrix, k=8)
    assert len(selected) == 5  # all returned, no compression
    sims = [s for _, s in selected]
    assert sims == sorted(sims, reverse=True), sims


def test_top_k_by_centroid_size_1_single_point():
    matrix = np.array([_l2(np.array([1.0, 0.0, 0.0, 0.0]))], dtype=np.float64)
    selected = _top_k_by_centroid([0], matrix, k=8)
    assert selected == [(0, 1.0)]  # single point: cosine to its own centroid is 1.0


# ---------------------------------------------------------------------------
# 2. Sample-titles ordering — deliberate tie
# ---------------------------------------------------------------------------


def test_sample_titles_tie_break_by_finding_index_asc():
    """Construct three vectors equidistant from the centroid; with K=2
    the two lowest finding-indices win. The same np.lexsort tie-break
    Brief 2 uses for gravitational_assign."""
    # Three orthogonal unit vectors; centroid is their L2-normalised
    # mean = [1/√3, 1/√3, 1/√3, 0]. Cosine sim to each is exactly
    # 1/√3 — mathematically equal, not approximately equal.
    matrix = np.array([
        _l2(np.array([1.0, 0.0, 0.0, 0.0])),
        _l2(np.array([0.0, 1.0, 0.0, 0.0])),
        _l2(np.array([0.0, 0.0, 1.0, 0.0])),
    ], dtype=np.float64)
    selected = _top_k_by_centroid([0, 1, 2], matrix, k=2)
    # Tied similarities → lowest finding-indices win
    assert [fi for fi, _ in selected] == [0, 1]


# ---------------------------------------------------------------------------
# 3. Empty-title handling — placeholder marker
# ---------------------------------------------------------------------------


def test_empty_titles_emit_placeholder_marker():
    findings = [
        {"title": "", "summary": ""},
        {"title": "   ", "summary": ""},  # whitespace-only is empty after strip
    ]
    pre_clusters = [{"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]}]
    matrix = np.eye(2, 4, dtype=np.float64)
    micro_in = _compress_pre_clusters_to_llm_input(
        pre_clusters, findings, matrix, k=8
    )
    assert micro_in == [
        {"id": "mc-000", "size": 2, "sample_titles": ["(no titles available)"]}
    ]


def test_empty_title_filtering_in_mixed_cluster():
    findings = [
        {"title": "Iran story A"},
        {"title": ""},
        {"title": "Iran story B"},
        {"title": "   "},
    ]
    pre_clusters = [{
        "id": "mc-000",
        "size": 4,
        "source_ids": ["finding-0", "finding-1", "finding-2", "finding-3"],
    }]
    matrix = np.array([
        _l2(np.array([1.0, 0.0, 0.0, 0.0])),
        _l2(np.array([0.0, 0.0, 0.0, 1.0])),
        _l2(np.array([1.0, 0.0, 0.0, 0.0])),
        _l2(np.array([0.0, 0.0, 0.0, 1.0])),
    ], dtype=np.float64)
    micro_in = _compress_pre_clusters_to_llm_input(
        pre_clusters, findings, matrix, k=8
    )
    assert len(micro_in) == 1
    titles = micro_in[0]["sample_titles"]
    # Only the two non-empty titles survive
    assert sorted(titles) == ["Iran story A", "Iran story B"]


# ---------------------------------------------------------------------------
# 4. Cluster ordering preserved
# ---------------------------------------------------------------------------


def test_cluster_order_preserved_in_llm_input():
    findings = [{"title": f"finding {i}"} for i in range(6)]
    pre_clusters = [
        {"id": "mc-002", "size": 2, "source_ids": ["finding-0", "finding-1"]},
        {"id": "mc-000", "size": 2, "source_ids": ["finding-2", "finding-3"]},
        {"id": "mc-001", "size": 2, "source_ids": ["finding-4", "finding-5"]},
    ]
    matrix = np.eye(6, 4, dtype=np.float64)
    micro_in = _compress_pre_clusters_to_llm_input(
        pre_clusters, findings, matrix, k=8
    )
    assert [c["id"] for c in micro_in] == ["mc-002", "mc-000", "mc-001"]


# ---------------------------------------------------------------------------
# 5. Pass-through of upstream slots
# ---------------------------------------------------------------------------


def test_passthrough_upstream_slots_byte_identical():
    findings = [
        {"title": "Iran A", "summary": "tensions"},
        {"title": "Iran B", "summary": "diplomacy"},
    ]
    pre_clusters = [{"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]}]
    rb = _make_rb(findings=findings, pre_clusters=pre_clusters)
    findings_json = json.dumps(copy.deepcopy(rb.curator_findings), sort_keys=True)
    pre_clusters_json = json.dumps(copy.deepcopy(rb.curator_pre_clusters), sort_keys=True)

    fake = FakeAgent(structured={"topics": [{"title": "T", "summary": "S"}]})
    stage = CuratorTopicDiscoveryStage(fake, embedder=HashEmbedder())
    rb_out = _run_stage(stage, rb)

    assert json.dumps(rb_out.curator_findings, sort_keys=True) == findings_json
    assert json.dumps(rb_out.curator_pre_clusters, sort_keys=True) == pre_clusters_json
    # JSON-serialisable result
    json.dumps(rb_out.curator_discovered_topics)


# ---------------------------------------------------------------------------
# 6. Mocked LLM response with 25 topics → 25 entries in slot
# ---------------------------------------------------------------------------


def test_mocked_25_topic_response_yields_25_entries():
    fake_topics = [
        {"title": f"Topic {i}", "summary": f"Summary for topic {i}."}
        for i in range(25)
    ]
    fake = FakeAgent(
        structured={"topics": fake_topics},
        cost_usd=0.025,
        tokens_used=42_000,
    )
    findings = [{"title": f"Iran finding {i}"} for i in range(5)]
    pre_clusters = [{
        "id": "mc-000",
        "size": 5,
        "source_ids": [f"finding-{i}" for i in range(5)],
    }]
    rb = _make_rb(findings=findings, pre_clusters=pre_clusters)
    stage = CuratorTopicDiscoveryStage(fake, embedder=HashEmbedder())
    rb_out = _run_stage(stage, rb)

    cdt = rb_out.curator_discovered_topics
    assert cdt["n_topics"] == 25
    assert len(cdt["topics"]) == 25
    assert cdt["topics"][0] == {"title": "Topic 0", "summary": "Summary for topic 0."}
    assert cdt["llm_cost_usd"] == 0.025
    assert cdt["tokens_used"] == 42_000
    assert cdt["n_micro_clusters_input"] == 1
    assert cdt["sample_titles_per_cluster"] == SAMPLE_TITLES_PER_CLUSTER


# ---------------------------------------------------------------------------
# 7. Empty pre-clusters → no LLM call, n_topics=0
# ---------------------------------------------------------------------------


def test_empty_pre_clusters_skips_llm_call():
    class _CrashAgent(FakeAgent):
        async def run(self, message="", context=None, **kwargs):
            raise AssertionError("LLM must not be called for empty pre-clusters")

    stage = CuratorTopicDiscoveryStage(
        _CrashAgent(), embedder=HashEmbedder()
    )
    rb = _make_rb(findings=[], pre_clusters=[])
    rb_out = _run_stage(stage, rb)
    cdt = rb_out.curator_discovered_topics
    assert cdt["n_micro_clusters_input"] == 0
    assert cdt["n_topics"] == 0
    assert cdt["topics"] == []


# ---------------------------------------------------------------------------
# 8. Pass-through ≤ K — size-5 cluster with K=8 returns all 5
# ---------------------------------------------------------------------------


def test_small_cluster_passes_through_all_titles():
    findings = [
        {"title": "Iran A"},
        {"title": "Iran B"},
        {"title": "Iran C"},
        {"title": "Iran D"},
        {"title": "Iran E"},
    ]
    pre_clusters = [{
        "id": "mc-000",
        "size": 5,
        "source_ids": [f"finding-{i}" for i in range(5)],
    }]
    fake = FakeAgent(structured={"topics": []})
    stage = CuratorTopicDiscoveryStage(fake, embedder=HashEmbedder())
    _run_stage(stage, _make_rb(findings=findings, pre_clusters=pre_clusters))
    call = fake.calls[0]
    micro_in = call["context"]["micro_clusters"]
    assert len(micro_in) == 1
    assert len(micro_in[0]["sample_titles"]) == 5
    assert sorted(micro_in[0]["sample_titles"]) == sorted(
        f["title"] for f in findings
    )


# ---------------------------------------------------------------------------
# 9. Stage / slot metadata
# ---------------------------------------------------------------------------


def test_stage_metadata():
    stage = CuratorTopicDiscoveryStage(FakeAgent())
    meta = get_stage_meta(stage)
    assert meta.name == "CuratorTopicDiscoveryStage"
    assert meta.kind == "run"
    assert meta.reads == ("curator_findings", "curator_pre_clusters")
    assert meta.writes == ("curator_discovered_topics",)


def test_bus_slot_metadata():
    from src.bus import RunBus as _RB

    field = _RB.model_fields["curator_discovered_topics"]
    extra = field.json_schema_extra or {}
    assert extra.get("visibility") == ["internal"]
    assert extra.get("optional_write") is True


# ---------------------------------------------------------------------------
# 10. SAMPLE_TITLES_PER_CLUSTER pinned at K=8
# ---------------------------------------------------------------------------


def test_sample_titles_per_cluster_pinned_at_8():
    assert SAMPLE_TITLES_PER_CLUSTER == 8


# ---------------------------------------------------------------------------
# 11. Pure-helper unit tests
# ---------------------------------------------------------------------------


def test_topic_discovery_finding_text_matches_pre_cluster_rule():
    f = {"title": "T", "summary": "S", "description": "D"}
    assert _topic_discovery_finding_text(f) == "T S D"
    # On real RSS findings (description absent): identical to title+summary
    assert _topic_discovery_finding_text({"title": "T", "summary": "S"}) == "T S"


def test_compress_resolves_finding_nnn_references():
    findings = [
        {"title": "Iran A"},
        {"title": "Climate A"},
    ]
    pre_clusters = [
        {"id": "mc-000", "size": 1, "source_ids": ["finding-0"]},
        {"id": "mc-001", "size": 1, "source_ids": ["finding-1"]},
    ]
    matrix = np.eye(2, 4, dtype=np.float64)
    micro_in = _compress_pre_clusters_to_llm_input(
        pre_clusters, findings, matrix, k=8
    )
    assert micro_in[0]["sample_titles"] == ["Iran A"]
    assert micro_in[1]["sample_titles"] == ["Climate A"]


def test_compress_drops_invalid_source_ids():
    findings = [{"title": "Iran A"}]
    pre_clusters = [{
        "id": "mc-000",
        "size": 3,
        "source_ids": ["finding-0", "finding-999", "rsrc-bogus"],
    }]
    matrix = np.eye(1, 4, dtype=np.float64)
    micro_in = _compress_pre_clusters_to_llm_input(
        pre_clusters, findings, matrix, k=8
    )
    assert micro_in[0]["sample_titles"] == ["Iran A"]
