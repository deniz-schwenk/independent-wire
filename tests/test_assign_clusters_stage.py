"""Tests for ``AssignClustersStage`` + ``cluster_to_finding_assignments``
— TASK-CLUSTER-LLM-ASSIGNMENT (Hypothesis 2 of the cluster-level pivot).

Coverage required by the brief:

- ``AssignClustersStage`` shape — mocked LLM produces N entries; the bus
  slot contains exactly those N plus the deterministically-derived
  orphan_cluster_ids deltas.
- ``cluster_to_finding_assignments`` determinism — two runs on the same
  input produce byte-identical output.
- Translation correctness — synthetic cluster → finding membership and
  cluster → topic assignment produces the correct topic → finding
  bucket and orphan list.
- Orphan handling — cluster_id in ``orphan_cluster_ids`` produces orphan
  entries for every finding in that cluster.
- Empty cases — empty topics, empty clusters, both empty produce
  shape-valid (possibly empty) bus slots.
- End-to-end mini-smoke — synthetic ``CuratorTopicDiscoveryStage`` output
  → AssignClustersStage → cluster_to_finding_assignments →
  ``assemble_curator_topics`` consumes the result without error.

(Strict-mode schema validation for the LLM output shape itself lives
in ``tests/test_schemas.py``, in line with the established convention
for every other agent's strict schema.)

No real LLM calls. ``FakeAgent`` returns pre-baked AgentResults; a
small synthetic embedder injects deterministic vectors so the wrapper
has something to call without standing up fastembed.
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any, Sequence

import numpy as np

from src.agent import AgentResult
from src.agent_stages import AssignClustersStage
from src.bus import RunBus
from src.stage import get_stage_meta
from src.stages.cluster_to_finding_assignments import (
    ALGORITHM,
    PER_FINDING_CAP,
    cluster_to_finding_assignments,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAgent:
    """Mirror of the FakeAgent used by other agent-stage tests. Captures
    every ``run(...)`` call so tests can assert on the message + context
    the wrapper passed to the LLM."""

    def __init__(
        self,
        *,
        structured: Any = None,
        content: str = "",
        cost_usd: float = 0.0,
        tokens_used: int = 0,
        name: str = "fake",
        model: str = "fake-model",
        temperature: float = 1.0,
        max_tokens: int = 8000,
        reasoning: str = "none",
    ) -> None:
        self._structured = structured
        self._content = content
        self._cost_usd = cost_usd
        self._tokens_used = tokens_used
        self.name = name
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning = reasoning
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
    """Same minimal 4-dim deterministic embedder as the curator-topic-
    discovery test suite uses. Sample-title compression doesn't actually
    matter for the LLM-assignment stage tests since we mock the LLM
    output — the embedder is only here so the wrapper has something to
    call without standing up fastembed."""

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


def _make_rb(
    *,
    findings: list[dict],
    pre_clusters: list[dict],
    discovered_topics: list[dict],
    run_date: str = "2026-05-17",
    cluster_assignments_llm: dict | None = None,
) -> RunBus:
    rb = RunBus(
        run_id="run-2026-05-17-test-assign",
        run_date=run_date,
        curator_findings=findings,
        curator_pre_clusters={"model_name": "fake", "clusters": pre_clusters},
        curator_discovered_topics={
            "model_name": "fake-discovery",
            "topics": discovered_topics,
        },
    )
    if cluster_assignments_llm is not None:
        rb.curator_cluster_assignments_llm = cluster_assignments_llm
    return rb


def _run(stage, rb):
    return asyncio.run(stage(rb))


# ===========================================================================
# AssignClustersStage tests
# ===========================================================================


def test_stage_metadata():
    stage = AssignClustersStage(FakeAgent())
    meta = get_stage_meta(stage)
    assert meta.name == "AssignClustersStage"
    assert meta.kind == "run"
    assert meta.reads == (
        "curator_findings",
        "curator_pre_clusters",
        "curator_discovered_topics",
    )
    assert meta.writes == ("curator_cluster_assignments_llm",)


def test_bus_slot_metadata():
    field = RunBus.model_fields["curator_cluster_assignments_llm"]
    extra = field.json_schema_extra or {}
    assert extra.get("visibility") == ["internal"]
    assert extra.get("optional_write") is True


def test_assign_clusters_shape_with_5_entries():
    """Mocked LLM produces 5 cluster assignments; the bus slot contains
    exactly those 5 plus the deterministically-derived orphan deltas
    (1 input cluster left unmentioned)."""
    findings = [{"title": f"finding {i}"} for i in range(10)]
    pre_clusters = [
        {"id": f"mc-{i:03d}", "size": 2, "source_ids": [
            f"finding-{2*i}", f"finding-{2*i + 1}",
        ]}
        for i in range(6)
    ]
    discovered_topics = [
        {"title": f"Topic {i}", "summary": f"Summary {i}"} for i in range(3)
    ]
    fake = FakeAgent(
        structured={
            "assignments": [
                {"cluster_id": "mc-000", "topic_indices": [0]},
                {"cluster_id": "mc-001", "topic_indices": [1]},
                {"cluster_id": "mc-002", "topic_indices": [0, 2]},
                {"cluster_id": "mc-003", "topic_indices": [2]},
                {"cluster_id": "mc-004", "topic_indices": [1]},
                # mc-005 absent → orphan
            ]
        },
        cost_usd=0.012,
        tokens_used=4_500,
    )
    rb = _make_rb(
        findings=findings,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
    )
    stage = AssignClustersStage(fake, embedder=HashEmbedder())
    rb_out = _run(stage, rb)

    rec = rb_out.curator_cluster_assignments_llm
    assert rec["n_clusters_input"] == 6
    assert rec["n_topics_input"] == 3
    assert rec["n_clusters_assigned"] == 5
    assert rec["n_clusters_orphan"] == 1
    assert {a["cluster_id"] for a in rec["assignments"]} == {
        "mc-000", "mc-001", "mc-002", "mc-003", "mc-004",
    }
    assert rec["orphan_cluster_ids"] == ["mc-005"]
    # Multi-assignment preserved exactly
    multi = [a for a in rec["assignments"] if a["cluster_id"] == "mc-002"][0]
    assert multi["topic_indices"] == [0, 2]
    # Metadata correctness
    assert rec["llm_model"] == "fake-model"
    assert rec["llm_cost_usd"] == 0.012
    assert rec["params"]["temperature"] == 1.0
    assert rec["params"]["reasoning"] == "none"


def test_assign_clusters_drops_unknown_cluster_ids():
    """LLM hallucinates an unknown cluster ID → it's silently dropped
    (defensive parse layer). The orphan list reflects all input
    clusters minus the legitimately-assigned ones."""
    findings = [{"title": f"f{i}"} for i in range(4)]
    pre_clusters = [
        {"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]},
        {"id": "mc-001", "size": 2, "source_ids": ["finding-2", "finding-3"]},
    ]
    discovered_topics = [{"title": "T", "summary": "S"}]
    fake = FakeAgent(structured={
        "assignments": [
            {"cluster_id": "mc-000", "topic_indices": [0]},
            {"cluster_id": "mc-XXX", "topic_indices": [0]},  # hallucinated
        ]
    })
    rb = _make_rb(
        findings=findings,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
    )
    rb_out = _run(AssignClustersStage(fake, embedder=HashEmbedder()), rb)
    rec = rb_out.curator_cluster_assignments_llm
    assert [a["cluster_id"] for a in rec["assignments"]] == ["mc-000"]
    assert rec["orphan_cluster_ids"] == ["mc-001"]


def test_assign_clusters_drops_out_of_range_topic_indices():
    """LLM emits a topic_index beyond n_topics — it's dropped from the
    list; if all indices are out of range, the assignment is dropped
    and the cluster becomes orphan."""
    findings = [{"title": "f0"}]
    pre_clusters = [
        {"id": "mc-000", "size": 1, "source_ids": ["finding-0"]},
        {"id": "mc-001", "size": 1, "source_ids": ["finding-0"]},
    ]
    discovered_topics = [{"title": "T0", "summary": "S0"}]  # only index 0
    fake = FakeAgent(structured={
        "assignments": [
            {"cluster_id": "mc-000", "topic_indices": [0, 5, 9]},  # only 0 valid
            {"cluster_id": "mc-001", "topic_indices": [5, 9]},  # all invalid
        ]
    })
    rb = _make_rb(
        findings=findings,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
    )
    rb_out = _run(AssignClustersStage(fake, embedder=HashEmbedder()), rb)
    rec = rb_out.curator_cluster_assignments_llm
    assert rec["assignments"] == [{"cluster_id": "mc-000", "topic_indices": [0]}]
    assert rec["orphan_cluster_ids"] == ["mc-001"]


def test_assign_clusters_empty_pre_clusters_no_llm_call():
    """No clusters → no LLM call; record contains empty arrays and the
    correct zero counters."""

    class _CrashAgent(FakeAgent):
        async def run(self, message="", context=None, **kwargs):
            raise AssertionError("LLM must not be called for empty clusters")

    rb = _make_rb(
        findings=[],
        pre_clusters=[],
        discovered_topics=[{"title": "T", "summary": "S"}],
    )
    rb_out = _run(AssignClustersStage(_CrashAgent(), embedder=HashEmbedder()), rb)
    rec = rb_out.curator_cluster_assignments_llm
    assert rec["n_clusters_input"] == 0
    assert rec["assignments"] == []
    assert rec["orphan_cluster_ids"] == []


def test_assign_clusters_empty_topics_no_llm_call():
    """No topics → no LLM call; every input cluster becomes orphan."""

    class _CrashAgent(FakeAgent):
        async def run(self, message="", context=None, **kwargs):
            raise AssertionError("LLM must not be called for empty topics")

    pre_clusters = [
        {"id": "mc-000", "size": 1, "source_ids": ["finding-0"]},
        {"id": "mc-001", "size": 1, "source_ids": ["finding-0"]},
    ]
    rb = _make_rb(
        findings=[{"title": "f0"}],
        pre_clusters=pre_clusters,
        discovered_topics=[],
    )
    rb_out = _run(AssignClustersStage(_CrashAgent(), embedder=HashEmbedder()), rb)
    rec = rb_out.curator_cluster_assignments_llm
    assert rec["assignments"] == []
    # Empty-input path returns ids without sorting; semantics-equivalent set check
    assert set(rec["orphan_cluster_ids"]) == {"mc-000", "mc-001"}
    assert rec["n_clusters_orphan"] == 2


def test_assign_clusters_passthrough_upstream_slots_unchanged():
    """The stage must not mutate the upstream curator_findings /
    curator_pre_clusters / curator_discovered_topics slots."""
    findings = [{"title": "f0"}, {"title": "f1"}]
    pre_clusters = [
        {"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]},
    ]
    discovered_topics = [{"title": "T", "summary": "S"}]
    rb = _make_rb(
        findings=findings,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
    )
    fj_before = json.dumps(copy.deepcopy(rb.curator_findings), sort_keys=True)
    pj_before = json.dumps(copy.deepcopy(rb.curator_pre_clusters), sort_keys=True)
    dj_before = json.dumps(copy.deepcopy(rb.curator_discovered_topics), sort_keys=True)

    fake = FakeAgent(structured={
        "assignments": [{"cluster_id": "mc-000", "topic_indices": [0]}]
    })
    rb_out = _run(AssignClustersStage(fake, embedder=HashEmbedder()), rb)

    assert json.dumps(rb_out.curator_findings, sort_keys=True) == fj_before
    assert json.dumps(rb_out.curator_pre_clusters, sort_keys=True) == pj_before
    assert json.dumps(rb_out.curator_discovered_topics, sort_keys=True) == dj_before


def test_assign_clusters_passes_topics_and_micro_clusters_to_llm():
    """The wrapper hands the LLM exactly the topics list + the compressed
    micro_clusters context — no extra fields, no missing ones."""
    findings = [{"title": "Iran A"}, {"title": "Iran B"}]
    pre_clusters = [{
        "id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"],
    }]
    discovered_topics = [
        {"title": "Iran-US talks", "summary": "Diplomacy."},
        {"title": "Energy", "summary": "Oil prices."},
    ]
    fake = FakeAgent(structured={"assignments": []})
    rb = _make_rb(
        findings=findings,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
    )
    _run(AssignClustersStage(fake, embedder=HashEmbedder()), rb)
    assert len(fake.calls) == 1
    ctx = fake.calls[0]["context"]
    assert set(ctx) == {"topics", "micro_clusters"}
    assert ctx["topics"] == discovered_topics
    # Each micro-cluster gets id + size + sample_titles
    mc = ctx["micro_clusters"]
    assert len(mc) == 1
    assert mc[0]["id"] == "mc-000"
    assert mc[0]["size"] == 2
    assert sorted(mc[0]["sample_titles"]) == ["Iran A", "Iran B"]


# ===========================================================================
# cluster_to_finding_assignments tests
# ===========================================================================


def _make_rb_for_translation(
    *,
    findings_count: int,
    pre_clusters: list[dict],
    discovered_topics: list[dict],
    cluster_assignments_llm: dict,
) -> RunBus:
    findings = [{"title": f"f{i}"} for i in range(findings_count)]
    return _make_rb(
        findings=findings,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
        cluster_assignments_llm=cluster_assignments_llm,
    )


def test_translation_correctness_single_assignment_per_cluster():
    """Given 3 clusters → 3 topics in a clean 1:1 mapping, the
    translated curator_topic_assignments shows each topic bucket with
    the right finding source_ids."""
    pre_clusters = [
        {"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]},
        {"id": "mc-001", "size": 2, "source_ids": ["finding-2", "finding-3"]},
        {"id": "mc-002", "size": 1, "source_ids": ["finding-4"]},
    ]
    discovered_topics = [
        {"title": "T0", "summary": "S0"},
        {"title": "T1", "summary": "S1"},
        {"title": "T2", "summary": "S2"},
    ]
    llm_record = {
        "llm_model": "fake-model",
        "params": {"temperature": 1.0, "reasoning": "none", "top_p": None, "max_tokens": 8000},
        "n_clusters_input": 3,
        "n_topics_input": 3,
        "assignments": [
            {"cluster_id": "mc-000", "topic_indices": [0]},
            {"cluster_id": "mc-001", "topic_indices": [1]},
            {"cluster_id": "mc-002", "topic_indices": [2]},
        ],
        "orphan_cluster_ids": [],
    }
    rb = _make_rb_for_translation(
        findings_count=5,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
        cluster_assignments_llm=llm_record,
    )
    rb_out = _run(cluster_to_finding_assignments, rb)
    rec = rb_out.curator_topic_assignments

    assert rec["algorithm"] == "llm-cluster-assignment"
    assert rec["params"]["llm_model"] == "fake-model"
    assert rec["params"]["upstream_stage"] == "assign_clusters"
    assert rec["params"]["per_finding_cap"] == PER_FINDING_CAP
    assert rec["n_topics"] == 3
    assert rec["n_findings"] == 5
    assert rec["n_findings_assigned"] == 5
    assert rec["n_orphans"] == 0
    assert rec["topics"][0]["topic_index"] == 0
    assert rec["topics"][0]["topic_title"] == "T0"
    assert [a["source_id"] for a in rec["topics"][0]["assignments"]] == [
        "finding-0", "finding-1",
    ]
    # Similarity is null for every LLM-cluster assignment
    assert all(
        a["similarity"] is None
        for t in rec["topics"]
        for a in t["assignments"]
    )


def test_translation_multi_assignment_per_cluster():
    """When a cluster lands on multiple topics, every member finding
    inherits all assignments (up to the cap)."""
    pre_clusters = [
        {"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]},
    ]
    discovered_topics = [
        {"title": "T0", "summary": "S0"},
        {"title": "T1", "summary": "S1"},
        {"title": "T2", "summary": "S2"},
    ]
    llm_record = {
        "llm_model": "fake-model",
        "params": {"temperature": 1.0, "reasoning": "none"},
        "n_clusters_input": 1,
        "n_topics_input": 3,
        "assignments": [
            {"cluster_id": "mc-000", "topic_indices": [0, 2]},
        ],
        "orphan_cluster_ids": [],
    }
    rb = _make_rb_for_translation(
        findings_count=2,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
        cluster_assignments_llm=llm_record,
    )
    rb_out = _run(cluster_to_finding_assignments, rb)
    rec = rb_out.curator_topic_assignments

    # finding-0 and finding-1 each land in topics 0 and 2 (2 assignments each)
    assert [a["source_id"] for a in rec["topics"][0]["assignments"]] == [
        "finding-0", "finding-1",
    ]
    assert rec["topics"][1]["assignments"] == []
    assert [a["source_id"] for a in rec["topics"][2]["assignments"]] == [
        "finding-0", "finding-1",
    ]
    assert rec["n_findings_assigned"] == 2
    assert rec["mean_assignments_per_finding"] == 2.0


def test_translation_cap_applies_when_cluster_lands_on_more_than_cap_topics():
    """A cluster on > PER_FINDING_CAP topics → each finding picks up
    only the first PER_FINDING_CAP topics in LLM emit order."""
    pre_clusters = [
        {"id": "mc-000", "size": 1, "source_ids": ["finding-0"]},
    ]
    discovered_topics = [
        {"title": f"T{i}", "summary": f"S{i}"} for i in range(5)
    ]
    llm_record = {
        "llm_model": "fake-model",
        "params": {"temperature": 1.0, "reasoning": "none"},
        "n_clusters_input": 1,
        "n_topics_input": 5,
        # Land on 5 topics in this specific order: 4, 1, 0, 3, 2
        "assignments": [
            {"cluster_id": "mc-000", "topic_indices": [4, 1, 0, 3, 2]},
        ],
        "orphan_cluster_ids": [],
    }
    rb = _make_rb_for_translation(
        findings_count=1,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
        cluster_assignments_llm=llm_record,
    )
    rb_out = _run(cluster_to_finding_assignments, rb)
    rec = rb_out.curator_topic_assignments
    # PER_FINDING_CAP=3 → finding-0 ends up in topics 4, 1, 0 (first three)
    landed_in = [
        t["topic_index"] for t in rec["topics"]
        if any(a["source_id"] == "finding-0" for a in t["assignments"])
    ]
    assert sorted(landed_in) == [0, 1, 4]
    assert 2 not in landed_in and 3 not in landed_in


def test_translation_determinism_byte_identical_across_two_runs():
    """Two runs on identical inputs produce byte-identical translated
    bus slots."""
    pre_clusters = [
        {"id": f"mc-{i:03d}", "size": 2, "source_ids": [
            f"finding-{2*i}", f"finding-{2*i + 1}",
        ]}
        for i in range(4)
    ]
    discovered_topics = [
        {"title": f"T{i}", "summary": f"S{i}"} for i in range(3)
    ]
    llm_record = {
        "llm_model": "fake-model",
        "params": {"temperature": 1.0, "reasoning": "none"},
        "n_clusters_input": 4,
        "n_topics_input": 3,
        "assignments": [
            {"cluster_id": "mc-002", "topic_indices": [1, 2]},
            {"cluster_id": "mc-000", "topic_indices": [0]},
            {"cluster_id": "mc-001", "topic_indices": [0, 1]},
        ],
        "orphan_cluster_ids": ["mc-003"],
    }
    out_a = _run(cluster_to_finding_assignments, _make_rb_for_translation(
        findings_count=8, pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
        cluster_assignments_llm=llm_record,
    )).curator_topic_assignments
    out_b = _run(cluster_to_finding_assignments, _make_rb_for_translation(
        findings_count=8, pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
        cluster_assignments_llm=llm_record,
    )).curator_topic_assignments
    # ``wall_seconds`` is the only allowed difference — exclude it.
    for d in (out_a, out_b):
        d.pop("wall_seconds", None)
    assert json.dumps(out_a, sort_keys=True) == json.dumps(out_b, sort_keys=True)


def test_translation_orphan_cluster_yields_per_finding_orphan_entries():
    """A cluster_id in orphan_cluster_ids → every finding in that
    cluster becomes an orphan entry."""
    pre_clusters = [
        {"id": "mc-000", "size": 3, "source_ids": [
            "finding-0", "finding-1", "finding-2",
        ]},
        {"id": "mc-001", "size": 2, "source_ids": [
            "finding-3", "finding-4",
        ]},
    ]
    discovered_topics = [{"title": "T0", "summary": "S0"}]
    llm_record = {
        "llm_model": "fake-model",
        "params": {"temperature": 1.0, "reasoning": "none"},
        "n_clusters_input": 2,
        "n_topics_input": 1,
        "assignments": [
            {"cluster_id": "mc-000", "topic_indices": [0]},
        ],
        "orphan_cluster_ids": ["mc-001"],
    }
    rb = _make_rb_for_translation(
        findings_count=5,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
        cluster_assignments_llm=llm_record,
    )
    rb_out = _run(cluster_to_finding_assignments, rb)
    rec = rb_out.curator_topic_assignments
    # finding-3 and finding-4 → orphan entries (and only those)
    orphans = rec["orphans"]
    assert [o["source_id"] for o in orphans] == ["finding-3", "finding-4"]
    assert all(o["best_similarity"] is None for o in orphans)
    assert all(o["best_topic_index"] is None for o in orphans)
    # finding-0 .. finding-2 land in topic 0
    assert [a["source_id"] for a in rec["topics"][0]["assignments"]] == [
        "finding-0", "finding-1", "finding-2",
    ]


def test_translation_empty_inputs_produces_empty_record():
    """Empty assignments + empty orphan list → empty topics buckets
    (one per n_topics_input) and empty orphan list. Shape-valid."""
    discovered_topics = [
        {"title": "T0", "summary": "S0"},
        {"title": "T1", "summary": "S1"},
    ]
    llm_record = {
        "llm_model": "fake-model",
        "params": {"temperature": 1.0, "reasoning": "none"},
        "n_clusters_input": 0,
        "n_topics_input": 2,
        "assignments": [],
        "orphan_cluster_ids": [],
    }
    rb = _make_rb_for_translation(
        findings_count=0,
        pre_clusters=[],
        discovered_topics=discovered_topics,
        cluster_assignments_llm=llm_record,
    )
    rb_out = _run(cluster_to_finding_assignments, rb)
    rec = rb_out.curator_topic_assignments
    assert rec["n_topics"] == 2
    assert rec["n_findings"] == 0
    assert rec["n_findings_assigned"] == 0
    assert rec["n_orphans"] == 0
    assert len(rec["topics"]) == 2
    assert all(t["assignments"] == [] for t in rec["topics"])
    assert rec["orphans"] == []


def test_translation_leaked_cluster_treated_as_orphan_with_warning():
    """A cluster present in pre_clusters but missing from both
    assignments[] and orphan_cluster_ids is a contract violation by the
    upstream LLM stage — the translation defensively treats it as
    orphan to keep the population conserved."""
    pre_clusters = [
        {"id": "mc-000", "size": 1, "source_ids": ["finding-0"]},
        {"id": "mc-001", "size": 1, "source_ids": ["finding-1"]},  # leaked
    ]
    discovered_topics = [{"title": "T0", "summary": "S0"}]
    llm_record = {
        "llm_model": "fake-model",
        "params": {"temperature": 1.0, "reasoning": "none"},
        "n_clusters_input": 2,
        "n_topics_input": 1,
        "assignments": [
            {"cluster_id": "mc-000", "topic_indices": [0]},
        ],
        # mc-001 NOT in orphan_cluster_ids — contract violation
        "orphan_cluster_ids": [],
    }
    rb = _make_rb_for_translation(
        findings_count=2,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
        cluster_assignments_llm=llm_record,
    )
    rb_out = _run(cluster_to_finding_assignments, rb)
    rec = rb_out.curator_topic_assignments
    # finding-1 lands in orphan despite the LLM omitting mc-001 from
    # orphan_cluster_ids — population is conserved.
    assert [o["source_id"] for o in rec["orphans"]] == ["finding-1"]


# ===========================================================================
# Mode × fallback distinctness — every of (single, multi) × (orphan,
# finding_level) is conceptually possible. The brief defers the
# fallback-mode choice to ``orphan`` for the LLM stage as the canonical
# default (LLM decides; orphans stay orphan), so the four-combination
# distinctness test is the cluster-internal stage's responsibility. The
# LLM-translation stage has only one mode — verify the algorithm string
# is the documented constant.
# ===========================================================================


def test_translation_algorithm_constant():
    assert ALGORITHM == "llm-cluster-assignment"


# ===========================================================================
# End-to-end mini-smoke: AssignClustersStage → translation →
# assemble_curator_topics
# ===========================================================================


def test_end_to_end_synthetic_pipeline_consumable_by_assemble():
    """A complete synthetic mini-pipeline: AssignClustersStage produces
    LLM record → translation produces curator_topic_assignments →
    assemble_curator_topics merges discovered_topics + assignments into
    the Editor-facing curator_topics shape."""
    from src.stages.run_stages import assemble_curator_topics

    findings = [
        {"title": "Iran A", "summary": "diplomacy", "language": "en", "region": "MIDEAST"},
        {"title": "Iran B", "summary": "talks", "language": "en", "region": "MIDEAST"},
        {"title": "Climate A", "summary": "emissions", "language": "en", "region": "GLOBAL"},
        {"title": "Climate B", "summary": "carbon", "language": "en", "region": "GLOBAL"},
    ]
    pre_clusters = [
        {"id": "mc-000", "size": 2, "source_ids": ["finding-0", "finding-1"]},
        {"id": "mc-001", "size": 2, "source_ids": ["finding-2", "finding-3"]},
    ]
    discovered_topics = [
        {"title": "Iran-US talks", "summary": "Diplomacy and dialogue."},
        {"title": "Climate emissions update", "summary": "Carbon emissions reporting."},
    ]
    rb = _make_rb(
        findings=findings,
        pre_clusters=pre_clusters,
        discovered_topics=discovered_topics,
    )
    fake = FakeAgent(structured={
        "assignments": [
            {"cluster_id": "mc-000", "topic_indices": [0]},
            {"cluster_id": "mc-001", "topic_indices": [1]},
        ]
    })
    rb = _run(AssignClustersStage(fake, embedder=HashEmbedder()), rb)
    rb = _run(cluster_to_finding_assignments, rb)
    rb = _run(assemble_curator_topics, rb)

    # assemble_curator_topics produces curator_topics_unsliced sorted
    # by source_count desc with title asc tiebreak. Both topics have 2
    # findings, so the title-asc tiebreak orders them
    # "Climate emissions update" then "Iran-US talks".
    titles = [t["title"] for t in rb.curator_topics_unsliced]
    assert titles == ["Climate emissions update", "Iran-US talks"]
    for t in rb.curator_topics_unsliced:
        assert t["source_count"] == 2
        assert len(t["source_ids"]) == 2
