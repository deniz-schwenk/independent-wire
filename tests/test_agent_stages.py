"""Tests for src/agent_stages.py — Curator, Editor, ResearcherPlan wrappers.

No real LLM calls. A small `FakeAgent` class returns pre-baked AgentResults.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from src.agent_stages import (
    CuratorStage,
    EditorStage,
    ResearcherPlanStage,
    _assign_ids_and_slugs,
    _attach_raw_data_from_curated,
    _enrich_curator_output,
    _parse_agent_output,
    _prepare_curator_input,
    _rebuild_curator_source_ids,
    _recover_truncated_cluster_assignments,
    _slugify,
    _unwrap_list,
)
from src.bus import EditorAssignment, RunBus, TopicBus
from src.models import AgentResult
from src.stage import (
    StagePostconditionError,
    get_stage_meta,
    validate_postconditions,
)


# ---------------------------------------------------------------------------
# Fake Agent — no network, no LLM
# ---------------------------------------------------------------------------


class FakeAgent:
    """Mimics the Agent.run() contract. Returns a pre-baked AgentResult.

    The real Agent class has many other attributes; this fake only exposes
    the minimum surface used by the wrappers.
    """

    def __init__(
        self, *, structured: Any = None, content: str = "", name: str = "fake"
    ) -> None:
        self._structured = structured
        self._content = content
        self.name = name
        self.calls: list[dict] = []

    async def run(
        self, message: str = "", context: dict | None = None, **kwargs: Any
    ) -> AgentResult:
        self.calls.append({"message": message, "context": context, **kwargs})
        return AgentResult(content=self._content, structured=self._structured)


def _run(stage, *args):
    return asyncio.run(stage(*args))


def _ro(rb: RunBus | None = None):
    return (rb or RunBus()).as_readonly()


# ---------------------------------------------------------------------------
# Stage metadata — class-based stages discoverable via get_stage_meta
# ---------------------------------------------------------------------------


def test_curator_stage_metadata():
    stage = CuratorStage(FakeAgent())
    meta = get_stage_meta(stage)
    assert meta.name == "CuratorStage"
    assert meta.kind == "run"
    assert meta.reads == ("curator_findings",)
    assert meta.writes == ("curator_topics_unsliced", "curator_topics")


def test_editor_stage_metadata():
    stage = EditorStage(FakeAgent())
    meta = get_stage_meta(stage)
    assert meta.name == "EditorStage"
    assert meta.kind == "run"
    assert meta.reads == ("curator_topics", "previous_coverage")
    assert meta.writes == ("editor_assignments",)


def test_researcher_plan_stage_metadata():
    stage = ResearcherPlanStage(FakeAgent())
    meta = get_stage_meta(stage)
    assert meta.name == "ResearcherPlanStage"
    assert meta.kind == "topic"
    assert meta.reads == ("editor_selected_topic",)
    assert meta.writes == ("researcher_plan_queries",)


# ---------------------------------------------------------------------------
# CuratorStage — happy path
# ---------------------------------------------------------------------------


def test_curator_stage_happy_path(tmp_path: Path):
    """Realistic Curator output: S13 envelope with two topics + cluster
    assignments. Wrapper rebuilds source_ids, enriches, sorts, slices."""
    raw_findings = [
        {"title": "Strait fees imposed", "source_url": "https://r.example/1",
         "source_name": "Reuters", "region": "North America", "language": "en"},
        {"title": "Tehran calls move coercion", "source_url": "https://t.example/2",
         "source_name": "Tasnim", "region": "Middle East", "language": "fa"},
        {"title": "European reaction muted", "source_url": "https://l.example/3",
         "source_name": "Le Monde", "region": "Europe", "language": "fr"},
    ]
    fake = FakeAgent(
        structured={
            "topics": [
                {"title": "US transit fees", "relevance_score": 9},
                {"title": "Iranian reaction", "relevance_score": 7},
            ],
            "cluster_assignments": [0, 1, 0],
        }
    )
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(
        json.dumps({"feeds": [
            {"name": "Reuters", "tier": "tier1", "editorial_independence": "independent"},
        ]}),
        encoding="utf-8",
    )

    rb = RunBus()
    rb.curator_findings = raw_findings

    stage = CuratorStage(fake, max_topics=10, sources_json_path=sources_path)
    rb_after = _run(stage, rb)

    # Two topics, sorted by relevance_score desc — order preserved (already sorted)
    assert len(rb_after.curator_topics_unsliced) == 2
    assert rb_after.curator_topics_unsliced[0]["title"] == "US transit fees"
    # source_ids rebuilt from cluster_assignments
    assert rb_after.curator_topics_unsliced[0]["source_ids"] == [
        "finding-0",
        "finding-2",
    ]
    assert rb_after.curator_topics_unsliced[1]["source_ids"] == ["finding-1"]
    # Enrichment fields populated
    assert "geographic_coverage" in rb_after.curator_topics_unsliced[0]
    assert "languages" in rb_after.curator_topics_unsliced[0]
    assert rb_after.curator_topics_unsliced[0]["source_count"] == 2
    # Top-N slice (max_topics=10, only 2 topics → both kept)
    assert rb_after.curator_topics == rb_after.curator_topics_unsliced

    # Agent was called once with the prepared input
    assert len(fake.calls) == 1
    assert fake.calls[0]["context"]["findings"][0]["title"] == "Strait fees imposed"


def test_curator_stage_max_topics_slices():
    fake = FakeAgent(
        structured={
            "topics": [
                {"title": f"t{i}", "relevance_score": 10 - i} for i in range(8)
            ],
            "cluster_assignments": [None] * 0,  # no findings
        }
    )
    rb = RunBus()
    rb.curator_findings = []
    stage = CuratorStage(fake, max_topics=3)
    rb_after = _run(stage, rb)
    assert len(rb_after.curator_topics_unsliced) == 8
    assert len(rb_after.curator_topics) == 3
    # Sorted by relevance_score desc
    assert rb_after.curator_topics[0]["title"] == "t0"
    assert rb_after.curator_topics[2]["title"] == "t2"


def test_curator_stage_legacy_top_level_list_shape():
    """Older prompts emit a top-level array of topics with source_ids
    already attached. _rebuild_curator_source_ids passes through."""
    fake = FakeAgent(
        structured=[
            {"title": "A", "source_ids": ["finding-0"], "relevance_score": 5},
        ]
    )
    rb = RunBus()
    rb.curator_findings = [
        {"title": "f0", "source_url": "x", "source_name": "Reuters"},
    ]
    stage = CuratorStage(fake)
    rb_after = _run(stage, rb)
    assert rb_after.curator_topics_unsliced[0]["source_ids"] == ["finding-0"]


def test_curator_stage_empty_output_post_validates_to_failure():
    """Agent returns empty parsed output → both write slots are []. Combined
    with V2-02 post-validation, this raises StagePostconditionError."""
    fake = FakeAgent(structured=None, content="")
    rb = RunBus()
    rb.curator_findings = []
    stage = CuratorStage(fake)
    rb_after = _run(stage, rb)
    assert rb_after.curator_topics_unsliced == []
    assert rb_after.curator_topics == []
    # Post-validator catches the empty writes
    with pytest.raises(StagePostconditionError):
        validate_postconditions(stage, rb, rb_after)


# ---------------------------------------------------------------------------
# EditorStage — happy path
# ---------------------------------------------------------------------------


def test_editor_stage_happy_path():
    """Realistic Editor output via the schema's `{assignments: [...]}`
    envelope. Wrapper unwraps, attaches raw_data, sorts, assigns ids."""
    curated = [
        {
            "title": "US transit fees",
            "relevance_score": 9,
            "source_ids": ["finding-0", "finding-2"],
            "summary": "fees on Strait of Hormuz",
            "geographic_coverage": ["North America", "Middle East"],
            "languages": ["en", "fa"],
            "source_count": 2,
        },
        {
            "title": "Iranian reaction",
            "relevance_score": 7,
            "source_ids": ["finding-1"],
            "source_count": 1,
        },
        {
            "title": "Distraction story",
            "relevance_score": 3,
            "source_ids": [],
            "source_count": 0,
        },
    ]
    fake = FakeAgent(
        structured={
            "assignments": [
                {
                    "title": "US transit fees",
                    "priority": 9,
                    "selection_reason": "strong cross-language coverage",
                },
                {
                    "title": "Iranian reaction",
                    "priority": 7,
                    "selection_reason": "important counter-narrative",
                },
                {
                    "title": "Distraction story",
                    "priority": 0,  # rejected
                    "selection_reason": "low signal",
                },
            ]
        }
    )

    rb = RunBus()
    rb.run_date = "2026-04-30"
    rb.curator_topics = curated

    stage = EditorStage(fake)
    rb_after = _run(stage, rb)

    assignments = rb_after.editor_assignments
    assert len(assignments) == 3  # 2 survivors + 1 rejected at tail
    # Survivors sorted by priority desc, then source_count desc
    assert assignments[0]["id"] == "tp-2026-04-30-001"
    assert assignments[0]["title"] == "US transit fees"
    assert assignments[0]["topic_slug"] == "us-transit-fees"
    assert assignments[0]["raw_data"]["source_count"] == 2
    assert assignments[1]["id"] == "tp-2026-04-30-002"
    assert assignments[1]["title"] == "Iranian reaction"
    # Rejected at tail with id=""
    assert assignments[2]["id"] == ""
    assert assignments[2]["priority"] == 0


def test_editor_stage_all_rejected():
    """Every topic priority 0 → all entries appear with id=""; bus slot is
    not is_empty (the list is populated, just rejected)."""
    fake = FakeAgent(
        structured={
            "assignments": [
                {"title": "A", "priority": 0, "selection_reason": "x"},
                {"title": "B", "priority": 0, "selection_reason": "y"},
            ]
        }
    )
    rb = RunBus()
    rb.run_date = "2026-04-30"
    rb.curator_topics = [
        {"title": "A", "source_ids": []},
        {"title": "B", "source_ids": []},
    ]
    stage = EditorStage(fake)
    rb_after = _run(stage, rb)
    assert all(a["id"] == "" for a in rb_after.editor_assignments)
    assert len(rb_after.editor_assignments) == 2
    # Post-validator passes — slot is not empty even though all are rejected.
    validate_postconditions(stage, rb, rb_after)


def test_editor_stage_handles_legacy_top_level_list():
    """Older Editor schema may emit a top-level list. Wrapper falls back."""
    fake = FakeAgent(
        structured=[
            {"title": "Legacy topic", "priority": 5, "selection_reason": "x"},
        ]
    )
    rb = RunBus()
    rb.run_date = "2026-04-30"
    rb.curator_topics = [{"title": "Legacy topic", "source_ids": ["finding-0"]}]
    stage = EditorStage(fake)
    rb_after = _run(stage, rb)
    assert rb_after.editor_assignments[0]["id"] == "tp-2026-04-30-001"


# ---------------------------------------------------------------------------
# ResearcherPlanStage — happy path
# ---------------------------------------------------------------------------


def test_researcher_plan_stage_happy_path():
    """Researcher Plan emits `{queries: [...]}`; wrapper unwraps and writes."""
    fake = FakeAgent(
        structured={
            "queries": [
                {"query": "Strait of Hormuz transit fees", "language": "en"},
                {"query": "Détroit d'Ormuz frais de transit", "language": "fr"},
                {"query": "تنگه هرمز عوارض عبور", "language": "fa"},
            ]
        }
    )
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(
            id="tp-2026-04-30-001",
            title="US transit fees on Strait of Hormuz",
            selection_reason="strong cross-language coverage",
            raw_data={"source_count": 2},
        )
    )
    stage = ResearcherPlanStage(fake)
    tb_after = _run(stage, tb, _ro())
    assert len(tb_after.researcher_plan_queries) == 3
    assert tb_after.researcher_plan_queries[0]["query"] == "Strait of Hormuz transit fees"
    # Agent received the right context
    ctx = fake.calls[0]["context"]
    assert ctx["title"] == "US transit fees on Strait of Hormuz"
    assert ctx["selection_reason"] == "strong cross-language coverage"
    assert ctx["raw_data"] == {"source_count": 2}


def test_researcher_plan_stage_unwraps_envelope():
    """Whether the schema returns wrapped or raw list, wrapper produces a list."""
    # Wrapped form
    fake_wrapped = FakeAgent(structured={"queries": [{"query": "q1", "language": "en"}]})
    # Raw list form (legacy)
    fake_raw = FakeAgent(structured=[{"query": "q1", "language": "en"}])

    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    stage_w = ResearcherPlanStage(fake_wrapped)
    stage_r = ResearcherPlanStage(fake_raw)
    out_w = _run(stage_w, tb, _ro())
    out_r = _run(stage_r, tb, _ro())
    assert out_w.researcher_plan_queries == out_r.researcher_plan_queries


def test_researcher_plan_stage_empty_output_post_validates_to_failure():
    fake = FakeAgent(structured=None, content="")
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    stage = ResearcherPlanStage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.researcher_plan_queries == []
    rb_ro_before = _ro()
    rb_ro_after = _ro()
    with pytest.raises(StagePostconditionError):
        validate_postconditions(
            stage, tb, tb_after,
            run_bus_before=rb_ro_before, run_bus_after=rb_ro_after,
        )


# ---------------------------------------------------------------------------
# Helper: _prepare_curator_input
# ---------------------------------------------------------------------------


def test_prepare_curator_input_url_dedup():
    findings = [
        {"title": "A", "source_url": "https://x.example/1"},
        {"title": "Duplicate of A", "source_url": "https://x.example/1"},  # dropped
        {"title": "B", "source_url": "https://y.example/2"},
    ]
    out = _prepare_curator_input(findings)
    assert len(out) == 2
    titles = [e["title"] for e in out]
    assert titles == ["A", "B"]


def test_prepare_curator_input_skips_empty_titles():
    findings = [
        {"title": "", "source_url": "https://x.example/1"},  # dropped
        {"title": "B", "source_url": "https://y.example/2"},
    ]
    out = _prepare_curator_input(findings)
    assert len(out) == 1


def test_prepare_curator_input_summary_inclusion_logic():
    """Summary included only if it differs from title and title doesn't
    start with the first 50 chars of summary (V1 heuristic: when the title
    already contains the summary's lead, the summary is redundant)."""
    findings = [
        # Identical → skipped
        {"title": "Hello", "summary": "Hello"},
        # Different content → included
        {"title": "Short title", "summary": "Different content entirely"},
        # Title starts with summary[:50] → skipped (the title already
        # carries the summary's prefix as its lead).
        {
            "title": "short summary content followed by extra detail",
            "summary": "short summary content",
        },
    ]
    out = _prepare_curator_input(findings)
    assert "summary" not in out[0]
    assert out[1]["summary"] == "Different content entirely"
    assert "summary" not in out[2]


# ---------------------------------------------------------------------------
# Helper: _rebuild_curator_source_ids
# ---------------------------------------------------------------------------


def test_rebuild_curator_source_ids_happy_path():
    result = AgentResult(
        content="",
        structured={
            "topics": [{"title": "T1"}, {"title": "T2"}],
            "cluster_assignments": [0, 1, 0, None],
        },
    )
    findings = [{"title": f"f{i}"} for i in range(4)]
    out = _rebuild_curator_source_ids(result, findings)
    assert out[0]["source_ids"] == ["finding-0", "finding-2"]
    assert out[1]["source_ids"] == ["finding-1"]


def test_rebuild_curator_source_ids_length_mismatch():
    """cluster_assignments shorter than findings → process overlap, warn."""
    result = AgentResult(
        content="",
        structured={
            "topics": [{"title": "T"}],
            "cluster_assignments": [0],  # only one entry, 3 findings
        },
    )
    findings = [{"title": f"f{i}"} for i in range(3)]
    out = _rebuild_curator_source_ids(result, findings)
    assert out[0]["source_ids"] == ["finding-0"]


def test_rebuild_curator_source_ids_out_of_range_skipped():
    result = AgentResult(
        content="",
        structured={
            "topics": [{"title": "T"}],
            "cluster_assignments": [0, 5, 0],  # index 5 is OOR
        },
    )
    findings = [{"title": f"f{i}"} for i in range(3)]
    out = _rebuild_curator_source_ids(result, findings)
    assert out[0]["source_ids"] == ["finding-0", "finding-2"]


def test_rebuild_curator_source_ids_legacy_shape():
    """Top-level list of topics-with-source_ids passes through."""
    result = AgentResult(
        content="",
        structured=[
            {"title": "Legacy", "source_ids": ["finding-0"]},
        ],
    )
    out = _rebuild_curator_source_ids(result, [{"title": "f0"}])
    assert out == [{"title": "Legacy", "source_ids": ["finding-0"]}]


def test_rebuild_curator_source_ids_truncation_recovery():
    """Dict has topics but cluster_assignments is None — regex-recover from
    raw content."""
    raw_content = json.dumps(
        {
            "topics": [{"title": "T"}],
            "cluster_assignments": [0, 1, None, 0],
        }
    )
    result = AgentResult(
        content=raw_content,
        structured={
            "topics": [{"title": "T1"}, {"title": "T2"}],
            "cluster_assignments": None,  # repaired-out by JSON repair
        },
    )
    findings = [{"title": f"f{i}"} for i in range(4)]
    out = _rebuild_curator_source_ids(result, findings)
    # After regex recovery, source_ids reflect [0, 1, None, 0] → finding-0,
    # finding-3 belong to topic 0; finding-1 to topic 1.
    assert out[0]["source_ids"] == ["finding-0", "finding-3"]
    assert out[1]["source_ids"] == ["finding-1"]


def test_recover_truncated_cluster_assignments_handles_partial_array():
    """Standalone helper: partial trailing array recovers up to n_findings."""
    content = '{"topics":[],"cluster_assignments":[0, null, 2'
    out = _recover_truncated_cluster_assignments(content, n_findings=5)
    assert out == [0, None, 2]


def test_recover_truncated_cluster_assignments_returns_none_when_key_absent():
    assert _recover_truncated_cluster_assignments('{"topics":[]}', 5) is None


# ---------------------------------------------------------------------------
# Helper: _enrich_curator_output
# ---------------------------------------------------------------------------


def test_enrich_curator_output_computes_missing_regions(tmp_path: Path):
    findings = [
        {"region": "North America", "language": "en", "source_name": "NYT"},
        {"region": "Europe", "language": "fr", "source_name": "Le Monde"},
        {"region": "Middle East", "language": "fa", "source_name": "Tasnim"},
    ]
    topics = [
        {"title": "T1", "source_ids": ["finding-0"]},
    ]
    sources_json = tmp_path / "sources.json"
    sources_json.write_text('{"feeds": []}', encoding="utf-8")
    out = _enrich_curator_output(
        topics, findings, sources_json_path=sources_json
    )
    t = out[0]
    assert t["geographic_coverage"] == ["North America"]
    assert t["languages"] == ["en"]
    assert t["source_count"] == 1
    assert t["missing_regions"] == ["Europe", "Middle East"]
    assert t["missing_languages"] == ["fa", "fr"]
    assert "No sources from: Europe, Middle East" in t["missing_perspectives"]


def test_enrich_curator_output_source_diversity_from_sources_json(tmp_path: Path):
    findings = [{"region": "x", "language": "en", "source_name": "Reuters"}]
    topics = [{"title": "T", "source_ids": ["finding-0"]}]
    sources_json = tmp_path / "sources.json"
    sources_json.write_text(
        json.dumps({"feeds": [
            {"name": "Reuters", "tier": "tier1", "editorial_independence": "independent"},
        ]}),
        encoding="utf-8",
    )
    out = _enrich_curator_output(
        topics, findings, sources_json_path=sources_json
    )
    diversity = out[0]["source_diversity"]
    assert diversity == [
        {"name": "Reuters", "tier": "tier1", "editorial_independence": "independent"},
    ]


def test_enrich_curator_output_sources_json_missing_is_graceful(tmp_path: Path):
    findings = [{"region": "x", "language": "en", "source_name": "Unknown"}]
    topics = [{"title": "T", "source_ids": ["finding-0"]}]
    nonexistent = tmp_path / "does-not-exist.json"
    out = _enrich_curator_output(
        topics, findings, sources_json_path=nonexistent
    )
    assert out[0]["source_diversity"] == [
        {"name": "Unknown", "tier": None, "editorial_independence": None},
    ]


# ---------------------------------------------------------------------------
# Helper: _attach_raw_data_from_curated
# ---------------------------------------------------------------------------


def test_attach_raw_data_title_match():
    raw = [{"title": "US transit fees"}]
    curated = [
        {"title": "US transit fees", "source_ids": ["finding-0"], "summary": "x"}
    ]
    _attach_raw_data_from_curated(raw, curated)
    assert raw[0]["raw_data"]["source_ids"] == ["finding-0"]
    assert raw[0]["raw_data"]["summary"] == "x"


def test_attach_raw_data_slug_fallback():
    """Editor refined title; slug still matches."""
    raw = [{"title": "US Transit Fees!"}]  # different casing/punct
    curated = [{"title": "US transit fees", "source_ids": ["finding-0"]}]
    _attach_raw_data_from_curated(raw, curated)
    # Slugs match: "us-transit-fees" === "us-transit-fees"
    assert raw[0]["raw_data"]["source_ids"] == ["finding-0"]


def test_attach_raw_data_no_match_leaves_empty():
    raw = [{"title": "Completely different"}]
    curated = [{"title": "US transit fees", "source_ids": ["finding-0"]}]
    _attach_raw_data_from_curated(raw, curated)
    assert raw[0]["raw_data"] == {}


def test_attach_raw_data_slug_collision_leaves_empty():
    raw = [{"title": "Same Slug"}]
    curated = [
        {"title": "Same slug", "source_ids": ["finding-0"]},
        {"title": "Same! slug", "source_ids": ["finding-1"]},  # also slugifies to same
    ]
    _attach_raw_data_from_curated(raw, curated)
    # Slug collision → bucket size > 1 → raw_data left empty
    assert raw[0]["raw_data"] == {}


# ---------------------------------------------------------------------------
# Helper: _assign_ids_and_slugs
# ---------------------------------------------------------------------------


def test_assign_ids_and_slugs_priority_filter_and_sort():
    raws = [
        {"title": "A", "priority": 5, "raw_data": {"source_ids": [1]}},
        {"title": "B", "priority": 9, "raw_data": {"source_ids": [1, 2, 3]}},
        {"title": "C", "priority": 0, "raw_data": {"source_ids": []}},  # rejected
        {"title": "D", "priority": 9, "raw_data": {"source_ids": [1]}},  # same priority as B, fewer sources
    ]
    out = _assign_ids_and_slugs(raws, run_date="2026-04-30")
    # Survivors: B (pri9, 3 sources), D (pri9, 1 source), A (pri5)
    assert [a["title"] for a in out[:3]] == ["B", "D", "A"]
    assert out[0]["id"] == "tp-2026-04-30-001"
    assert out[1]["id"] == "tp-2026-04-30-002"
    assert out[2]["id"] == "tp-2026-04-30-003"
    # Rejected at tail
    assert out[3]["title"] == "C"
    assert out[3]["id"] == ""


def test_assign_ids_and_slugs_invalid_priority_defaults_to_5():
    raws = [
        {"title": "A", "priority": "not a number", "raw_data": {}},
    ]
    out = _assign_ids_and_slugs(raws, run_date="2026-04-30")
    assert out[0]["priority"] == 5


# ---------------------------------------------------------------------------
# _parse_agent_output / _unwrap_list defensive checks
# ---------------------------------------------------------------------------


def test_parse_agent_output_returns_structured_dict():
    r = AgentResult(content="", structured={"k": "v"})
    assert _parse_agent_output(r) == {"k": "v"}


def test_parse_agent_output_returns_structured_list():
    r = AgentResult(content="", structured=[{"a": 1}])
    assert _parse_agent_output(r) == [{"a": 1}]


def test_parse_agent_output_falls_back_to_content():
    r = AgentResult(content='{"k": "v"}', structured=None)
    assert _parse_agent_output(r) == {"k": "v"}


def test_parse_agent_output_returns_none_when_unparseable():
    r = AgentResult(content="not json", structured=None)
    assert _parse_agent_output(r) is None


def test_unwrap_list_envelope_form():
    assert _unwrap_list({"queries": [1, 2, 3]}, "queries") == [1, 2, 3]


def test_unwrap_list_raw_list_form():
    assert _unwrap_list([1, 2, 3], "queries") == [1, 2, 3]


def test_unwrap_list_returns_empty_for_none_or_other():
    assert _unwrap_list(None, "queries") == []
    assert _unwrap_list({"other": [1]}, "queries") == []
    assert _unwrap_list("not a list", "queries") == []
