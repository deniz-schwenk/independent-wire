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
from src.agent import AgentResult
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


def test_researcher_plan_wrappers_pass_run_date_into_context():
    """Both Plan wrappers must surface run_bus.run_date in the agent context
    under key `today`. Closes the date-anchor drift documented in
    SMOKE-POST-POLISH-2026-05-02.md (Plan queries fell back to training
    cutoff because the wrapper never delivered the date)."""
    rb = RunBus()
    rb.run_date = "2026-05-02"

    # Production ResearcherPlanStage
    fake_prod = FakeAgent(structured={"queries": [{"query": "q", "language": "en"}]})
    tb_prod = TopicBus(
        editor_selected_topic=EditorAssignment(
            title="t", selection_reason="r", raw_data={"x": 1}
        )
    )
    _run(ResearcherPlanStage(fake_prod), tb_prod, rb.as_readonly())
    ctx_prod = fake_prod.calls[0]["context"]
    assert ctx_prod.get("today") == "2026-05-02"

    # Hydrated ResearcherHydratedPlanStage
    fake_hy = FakeAgent(structured={"queries": [{"query": "q", "language": "en"}]})
    tb_hy = TopicBus(
        editor_selected_topic=EditorAssignment(
            title="t", selection_reason="r", raw_data={"x": 1}
        )
    )
    tb_hy.hydration_pre_dossier = HydrationPreDossier(
        sources=[], preliminary_divergences=[], coverage_gaps=[]
    )
    _run(ResearcherHydratedPlanStage(fake_hy), tb_hy, rb.as_readonly())
    ctx_hy = fake_hy.calls[0]["context"]
    assert ctx_hy.get("today") == "2026-05-02"


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


# ===========================================================================
# V2-06: ResearcherAssembleStage
# ===========================================================================


from src.agent_stages import (  # noqa: E402
    BiasLanguageStage,
    HydrationPhase1Stage,
    HydrationPhase2Stage,
    PerspectiveStage,
    PerspectiveSyncStage,
    ResearcherAssembleStage,
    ResearcherHydratedPlanStage,
    WriterStage,
    _build_bias_card_for_agent_input,
    _extract_date_from_url,
    _merge_perspective_deltas,
)
from src.bus import (  # noqa: E402
    HydrationPhase2Corpus,
    HydrationPreDossier,
    ResearcherAssembleDossier,
    SourceBalance,
    WriterArticle,
)


def test_researcher_assemble_metadata():
    s = ResearcherAssembleStage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert m.reads == ("editor_selected_topic", "researcher_search_results")
    assert m.writes == ("researcher_assemble_dossier",)


def test_researcher_assemble_assigns_research_rsrc_ids_and_dates():
    """V2 deviation: emits `research-rsrc-NNN` per ARCH §4B.3 (V1 used bare
    rsrc-NNN). estimated_date filled from URL when missing."""
    fake = FakeAgent(
        structured={
            "sources": [
                {
                    "url": "https://reuters.example/2026/04/30/story",
                    "outlet": "Reuters",
                    "language": "en",
                    "country": "United States",
                    "summary": "x",
                    "actors_quoted": [],
                },
                {
                    "url": "https://lemonde.example/no-date-here",
                    "outlet": "Le Monde",
                    "language": "fr",
                    "country": "France",
                    "summary": "y",
                    "actors_quoted": [],
                },
            ],
            "preliminary_divergences": [{"description": "div"}],
            "coverage_gaps": ["gap"],
        }
    )
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(title="t", selection_reason="r")
    )
    tb.researcher_search_results = [{"query": "x", "results": "..."}]
    rb = RunBus()
    rb.run_date = "2026-04-30"
    stage = ResearcherAssembleStage(fake)
    tb_after = _run(stage, tb, rb.as_readonly())

    dossier = tb_after.researcher_assemble_dossier
    assert dossier.sources[0]["id"] == "research-rsrc-001"
    assert dossier.sources[0]["estimated_date"] == "2026-04-30"
    assert dossier.sources[1]["id"] == "research-rsrc-002"
    # No date in URL → estimated_date stays absent
    assert "estimated_date" not in dossier.sources[1] or dossier.sources[1].get("estimated_date") is None
    assert dossier.preliminary_divergences == [{"description": "div"}]
    assert dossier.coverage_gaps == ["gap"]


def test_researcher_assemble_empty_output():
    fake = FakeAgent(structured={"sources": [], "preliminary_divergences": [], "coverage_gaps": []})
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    stage = ResearcherAssembleStage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.researcher_assemble_dossier.sources == []


def test_extract_date_from_url():
    assert _extract_date_from_url("https://x.example/2026/04/30/story") == "2026-04-30"
    assert _extract_date_from_url("https://x.example/2026-04-30/story") == "2026-04-30"
    assert _extract_date_from_url("https://x.example/20260430/story") == "2026-04-30"
    assert _extract_date_from_url("https://x.example/2026/04/story") == "2026-04-01"
    assert _extract_date_from_url("https://x.example/no-date") is None
    assert _extract_date_from_url("") is None


# ===========================================================================
# V2-06: PerspectiveStage
# ===========================================================================


def test_perspective_metadata():
    s = PerspectiveStage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert "final_sources" in m.reads
    assert m.writes == ("perspective_clusters", "perspective_missing_positions")


def test_perspective_stage_writes_raw_clusters_only():
    """PerspectiveStage writes the agent's raw output verbatim. Deterministic
    enrichment (pc-NNN, actors, regions, languages, representation) is the
    `enrich_perspective_clusters` topic-stage's job and runs immediately
    after this wrapper. Wrapper output must NOT carry those fields."""
    fake = FakeAgent(
        structured={
            "position_clusters": [
                {
                    "position_label": "Pro",
                    "position_summary": "supports",
                    "source_ids": ["src-001", "src-002"],
                },
                {
                    "position_label": "Anti",
                    "position_summary": "opposes",
                    "source_ids": ["src-003"],
                },
            ],
            "missing_positions": [{"label": "civilians"}],
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.final_sources = [
        {"id": "src-001", "country": "United States", "language": "en"},
        {"id": "src-002", "country": "United States", "language": "en"},
        {"id": "src-003", "country": "Iran", "language": "fa"},
    ]
    stage = PerspectiveStage(fake)
    tb_after = _run(stage, tb, _ro())
    clusters = tb_after.perspective_clusters
    assert len(clusters) == 2
    # Raw shape only — agent emits position_label, position_summary, source_ids
    assert clusters[0] == {
        "position_label": "Pro",
        "position_summary": "supports",
        "source_ids": ["src-001", "src-002"],
    }
    # No enrichment fields on the wrapper output
    assert "id" not in clusters[0]
    assert "actors" not in clusters[0]
    assert "regions" not in clusters[0]
    assert "languages" not in clusters[0]
    assert "representation" not in clusters[0]
    assert tb_after.perspective_missing_positions == [{"label": "civilians"}]


def test_perspective_stage_empty_clusters_safe_via_optional_write():
    """Agent emits no clusters → wrapper writes empty list. The slot has
    optional_write=True so post-validation accepts the empty case for
    perspective_clusters specifically. (perspective_missing_positions is
    populated here so post-validation doesn't trip on the other write.)"""
    fake = FakeAgent(
        structured={
            "position_clusters": [],
            "missing_positions": [{"label": "civilians"}],
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    stage = PerspectiveStage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.perspective_clusters == []
    assert tb_after.perspective_missing_positions == [{"label": "civilians"}]
    # Post-validation accepts empty perspective_clusters via optional_write.
    rb_before = _ro()
    rb_after = _ro()
    validate_postconditions(
        stage, tb, tb_after, run_bus_before=rb_before, run_bus_after=rb_after
    )


# ===========================================================================
# V2-06: WriterStage
# ===========================================================================


def test_writer_metadata():
    s = WriterStage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert "perspective_clusters_synced" in m.reads
    assert m.writes == ("writer_article",)


def test_writer_happy_path_no_followup():
    fake = FakeAgent(
        structured={
            "headline": "Headline H",
            "subheadline": "Subhead",
            "body": "Body [src-001]. [[COVERAGE_STATEMENT]]",
            "summary": "Summary",
        }
    )
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(
            title="t", selection_reason="r", follow_up_to=None
        )
    )
    tb.final_sources = [{"id": "src-001"}]
    tb.perspective_clusters_synced = [{"id": "pc-001"}]
    stage = WriterStage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.writer_article.headline == "Headline H"
    assert tb_after.writer_article.body == "Body [src-001]. [[COVERAGE_STATEMENT]]"
    # No follow_up in context
    assert "follow_up" not in fake.calls[0]["context"]


def test_writer_loads_followup_addendum_when_follow_up_to_set(tmp_path: Path):
    followup_path = tmp_path / "FOLLOWUP.md"
    followup_path.write_text("Follow-up extra instructions.", encoding="utf-8")

    fake = FakeAgent(
        structured={"headline": "H", "subheadline": "S", "body": "B", "summary": "Sm"}
    )
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(
            title="t",
            follow_up_to="tp-2026-04-29-001",
            follow_up_reason="enforcement deadline",
        )
    )
    rb = RunBus()
    rb.run_date = "2026-04-30"
    rb.previous_coverage = [
        {"tp_id": "tp-2026-04-29-001", "headline": "Prior coverage headline"}
    ]
    stage = WriterStage(fake, followup_path=followup_path)
    tb_after = _run(stage, tb, rb.as_readonly())
    # Addendum was passed
    assert fake.calls[0].get("instructions_addendum") == "Follow-up extra instructions."
    # Previous headline pulled from RunBus, not disk
    fu = fake.calls[0]["context"]["follow_up"]
    assert fu["previous_headline"] == "Prior coverage headline"
    assert fu["reason"] == "enforcement deadline"
    assert tb_after.writer_article.headline == "H"


def test_writer_followup_missing_addendum_file_is_logged_but_not_fatal(tmp_path: Path):
    """FOLLOWUP.md not yet on disk → wrapper logs WARNING but proceeds."""
    fake = FakeAgent(
        structured={"headline": "H", "subheadline": "S", "body": "B", "summary": "Sm"}
    )
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(
            title="t",
            follow_up_to="tp-2026-04-29-001",
        )
    )
    nonexistent = tmp_path / "missing.md"
    stage = WriterStage(fake, followup_path=nonexistent)
    tb_after = _run(stage, tb, _ro())
    # Addendum is None when file missing
    assert fake.calls[0].get("instructions_addendum") is None
    assert tb_after.writer_article.headline == "H"


# ===========================================================================
# V2-06: BiasLanguageStage
# ===========================================================================


def test_bias_language_metadata():
    s = BiasLanguageStage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert "qa_corrected_article" in m.reads
    assert m.writes == ("bias_language_findings", "bias_reader_note")


def test_bias_language_happy_path():
    fake = FakeAgent(
        structured={
            "language_bias": {
                "findings": [
                    {"excerpt": "x", "issue": "loaded", "explanation": "y"}
                ],
            },
            "reader_note": "Three sources across three languages.",
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.qa_corrected_article = WriterArticle(
        headline="H", body="B", summary="Sm"
    )
    tb.final_sources = [
        {"id": "src-001", "country": "United States", "language": "en"},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "representation": "dominant", "actors": [{"name": "A", "role": "r"}]}
    ]
    stage = BiasLanguageStage(fake)
    tb_after = _run(stage, tb, _ro())
    assert len(tb_after.bias_language_findings) == 1
    assert tb_after.bias_reader_note == "Three sources across three languages."

    # bias_card was passed in context
    bias_card_ctx = fake.calls[0]["context"]["bias_card"]
    assert bias_card_ctx["source_balance"]["total"] == 1
    assert bias_card_ctx["perspectives"]["cluster_count"] == 1


def test_bias_language_stage_extracts_nested_findings():
    """BiasLanguageStage extracts findings from language_bias.findings
    nested array, not from the language_bias dict itself (which would
    yield the dict's keys ['findings'] — buggy pre-V2-12 behaviour)."""
    findings_emitted = [
        {
            "excerpt": "the devastating attack",
            "issue": "evaluative_adjective",
            "explanation": "'Devastating' characterizes severity in the article's own voice.",
        },
        {
            "excerpt": "the regime announced",
            "issue": "loaded_term",
            "explanation": "'Regime' carries implicit judgment about legitimacy.",
        },
    ]
    fake = FakeAgent(
        structured={
            "language_bias": {"findings": findings_emitted},
            "reader_note": "Two-sentence reader note.",
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.qa_corrected_article = WriterArticle(
        headline="H", body="B", summary="Sm"
    )
    tb.final_sources = [
        {"id": "src-001", "country": "United States", "language": "en"},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "representation": "dominant", "actors": []}
    ]
    stage = BiasLanguageStage(fake)
    tb_after = _run(stage, tb, _ro())

    assert tb_after.bias_language_findings == findings_emitted
    assert tb_after.bias_reader_note == "Two-sentence reader note."
    # Negative assertion: regression guard against the V2-04 bug
    assert tb_after.bias_language_findings != ["findings"]


def test_build_bias_card_for_agent_input_aggregates():
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.qa_corrected_article = WriterArticle(summary="my summary")
    tb.final_sources = [
        {"id": "src-001", "country": "US", "language": "en"},
        {"id": "src-002", "country": "France", "language": "fr"},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "representation": "dominant", "actors": [{"name": "A", "role": "r"}]},
        {"id": "pc-002", "representation": "marginal", "actors": []},
    ]
    tb.qa_divergences = [{"type": "factual"}]
    tb.coverage_gaps_validated = ["a gap"]
    bc = _build_bias_card_for_agent_input(tb)
    assert bc["article_summary"] == "my summary"
    assert bc["source_balance"]["total"] == 2
    assert bc["perspectives"]["cluster_count"] == 2
    assert bc["perspectives"]["distinct_actor_count"] == 1
    assert bc["perspectives"]["representation_distribution"] == {
        "dominant": 1, "substantial": 0, "marginal": 1
    }
    assert bc["factual_divergences"] == [{"type": "factual"}]
    assert bc["coverage_gaps"] == ["a gap"]


# ===========================================================================
# V2-06: ResearcherHydratedPlanStage
# ===========================================================================


def test_researcher_hydrated_plan_metadata():
    s = ResearcherHydratedPlanStage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert m.reads == ("editor_selected_topic", "hydration_pre_dossier")
    assert m.writes == ("researcher_plan_queries",)


def test_researcher_hydrated_plan_includes_coverage_summary():
    fake = FakeAgent(structured={"queries": [{"query": "q1", "language": "en"}]})
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(
            title="t", selection_reason="r", raw_data={"x": 1}
        )
    )
    tb.hydration_pre_dossier = HydrationPreDossier(
        sources=[
            {"id": "hydrate-rsrc-001", "language": "en", "country": "US", "outlet": "BBC",
             "actors_quoted": [{"name": "A", "type": "official"}]},
        ],
        preliminary_divergences=[],
        coverage_gaps=[],
    )
    rb = RunBus()
    rb.run_date = "2026-04-30"
    stage = ResearcherHydratedPlanStage(fake)
    tb_after = _run(stage, tb, rb.as_readonly())
    assert len(tb_after.researcher_plan_queries) == 1
    # coverage_summary was added to context
    assert "coverage_summary" in fake.calls[0]["context"]


# ===========================================================================
# V2-06: HydrationPhase1Stage
# ===========================================================================


def test_hydration_phase1_metadata():
    s = HydrationPhase1Stage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert m.reads == ("editor_selected_topic", "hydration_fetch_results")
    assert m.writes == ("hydration_phase1_analyses",)


def test_hydration_phase1_skips_when_no_successful_fetches():
    """Zero success records → skip the LLM call and write []."""
    fake = FakeAgent(structured={"article_analyses": []})
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.hydration_fetch_results = [
        {"url": "x", "status": "bot_blocked"},
        {"url": "y", "status": "error"},
    ]
    stage = HydrationPhase1Stage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.hydration_phase1_analyses == []
    # Agent should NOT have been called
    assert len(fake.calls) == 0


# ===========================================================================
# V2-06: HydrationPhase2Stage
# ===========================================================================


def test_hydration_phase2_metadata():
    s = HydrationPhase2Stage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert "hydration_phase1_analyses" in m.reads
    assert m.writes == ("hydration_phase2_corpus",)


def test_hydration_phase2_skips_when_no_analyses():
    fake = FakeAgent(structured={})
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.hydration_phase1_analyses = []
    stage = HydrationPhase2Stage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.hydration_phase2_corpus == HydrationPhase2Corpus()
    assert len(fake.calls) == 0


def test_hydration_phase2_calls_reducer():
    fake = FakeAgent(
        structured={
            "preliminary_divergences": [{"description": "d"}],
            "coverage_gaps": ["g"],
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.hydration_phase1_analyses = [
        {"article_index": 0, "summary": "s", "actors_quoted": []},
    ]
    tb.hydration_fetch_results = [
        {"url": "x", "status": "success", "language": "en", "country": "US", "outlet": "BBC"},
    ]
    stage = HydrationPhase2Stage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.hydration_phase2_corpus.preliminary_divergences == [{"description": "d"}]
    assert tb_after.hydration_phase2_corpus.coverage_gaps == ["g"]


# ===========================================================================
# V2-06: PerspectiveSyncStage  (eligibility-gate logic)
# ===========================================================================


def test_perspective_sync_metadata():
    s = PerspectiveSyncStage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert "qa_corrected_article" in m.reads
    assert m.writes == ("perspective_clusters_synced",)


def test_perspective_sync_eligibility_gate_skips_when_no_corrections():
    """qa_proposed_corrections empty → wrapper skips agent call, leaves
    perspective_clusters_synced empty so the V2-03b mirror produces 1:1."""
    fake = FakeAgent(structured={"position_cluster_updates": []})
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.perspective_clusters = [{"id": "pc-001", "position_label": "A"}]
    tb.qa_proposed_corrections = []  # gate fires → skip
    stage = PerspectiveSyncStage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.perspective_clusters_synced == []  # mirror handles it
    assert len(fake.calls) == 0


def test_perspective_sync_runs_when_qa_corrections_present():
    fake = FakeAgent(
        structured={
            "position_cluster_updates": [
                {"id": "pc-001", "position_label": "Strongly Pro"}
            ]
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.perspective_clusters = [
        {"id": "pc-001", "position_label": "Pro", "position_summary": "supports"},
        {"id": "pc-002", "position_label": "Anti", "position_summary": "opposes"},
    ]
    tb.qa_corrected_article = WriterArticle(body="corrected body")
    tb.qa_proposed_corrections = ["replace X with Y"]
    stage = PerspectiveSyncStage(fake)
    tb_after = _run(stage, tb, _ro())
    synced = tb_after.perspective_clusters_synced
    # Delta applied to pc-001, pc-002 unchanged
    assert synced[0]["position_label"] == "Strongly Pro"
    assert synced[0]["position_summary"] == "supports"
    assert synced[1]["position_label"] == "Anti"


def test_merge_perspective_deltas_unknown_id_skipped():
    original = {"position_clusters": [{"id": "pc-001", "position_label": "A"}]}
    updates = {
        "position_cluster_updates": [
            {"id": "pc-999", "position_label": "Ghost"}  # not in original
        ]
    }
    out = _merge_perspective_deltas(original, updates)
    assert out["position_clusters"][0]["position_label"] == "A"


def test_merge_perspective_deltas_null_value_skipped():
    original = {"position_clusters": [{"id": "pc-001", "position_label": "A"}]}
    updates = {
        "position_cluster_updates": [
            {"id": "pc-001", "position_label": None}  # null → no-op
        ]
    }
    out = _merge_perspective_deltas(original, updates)
    assert out["position_clusters"][0]["position_label"] == "A"


# ===========================================================================
# V2-06: QaAnalyzeStage  +  schema change in src/schemas.py
# ===========================================================================


from src.agent_stages import QaAnalyzeStage  # noqa: E402
from src.stages.run_stages import mirror_stage  # noqa: E402


def test_qa_analyze_metadata():
    s = QaAnalyzeStage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert m.reads == (
        "writer_article",
        "final_sources",
        "perspective_clusters_synced",
        "merged_preliminary_divergences",
    )
    assert m.writes == (
        "qa_problems_found",
        "qa_proposed_corrections",
        "qa_corrected_article",
        "qa_divergences",
    )


def _make_qa_topicbus() -> TopicBus:
    """Fixture TopicBus populated for QA: writer_article + final_sources +
    perspective_clusters_synced + merged_preliminary_divergences."""
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.writer_article = WriterArticle(
        headline="Original headline",
        subheadline="Original sub",
        body="Original body [src-001].",
        summary="Original summary",
    )
    tb.final_sources = [
        {"id": "src-001", "outlet": "Reuters", "language": "en"},
        {"id": "src-002", "outlet": "AFP", "language": "fr"},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "A", "source_ids": ["src-001"]}
    ]
    tb.merged_preliminary_divergences = [
        {"description": "casualty figures differ", "source_ids": ["src-001"]}
    ]
    return tb


def test_qa_analyze_problems_found_path():
    """QA found problems and emitted a corrected article. Wrapper writes
    all four slots; qa_corrected_article carries the corrected version."""
    fake = FakeAgent(
        structured={
            "problems_found": [
                {
                    "article_excerpt": "Original body [src-001].",
                    "problem": "factually_incorrect",
                    "explanation": "Source src-001 reports differently.",
                }
            ],
            "proposed_corrections": ["Replace X with Y."],
            "article": {
                "headline": "Corrected headline",
                "subheadline": "Corrected sub",
                "body": "Corrected body [src-001].",
                "summary": "Corrected summary",
            },
            "divergences": [
                {
                    "type": "factual",
                    "description": "deadline differs",
                    "source_ids": ["src-001"],
                    "resolution": "partially_resolved",
                    "resolution_note": "both attributed",
                }
            ],
        }
    )
    tb = _make_qa_topicbus()
    stage = QaAnalyzeStage(fake)
    tb_after = _run(stage, tb, _ro())

    assert len(tb_after.qa_problems_found) == 1
    assert tb_after.qa_proposed_corrections == ["Replace X with Y."]
    assert tb_after.qa_corrected_article.headline == "Corrected headline"
    assert tb_after.qa_corrected_article.body == "Corrected body [src-001]."
    assert len(tb_after.qa_divergences) == 1
    # Writer article remains the original (not mutated)
    assert tb_after.writer_article.headline == "Original headline"


def test_qa_analyze_clean_run_omits_article_leaves_slot_empty():
    """QA finds no problems and the V2 prompt omits `article` entirely.
    Wrapper writes empty arrays and leaves qa_corrected_article at its
    typed empty default — the V2-03b mirror_qa_corrected stage fills
    it downstream from writer_article."""
    fake = FakeAgent(
        structured={
            "problems_found": [],
            "proposed_corrections": [],
            # `article` field absent — V2 prompt omits it on clean runs
            "divergences": [],
        }
    )
    tb = _make_qa_topicbus()
    stage = QaAnalyzeStage(fake)
    tb_after = _run(stage, tb, _ro())

    assert tb_after.qa_problems_found == []
    assert tb_after.qa_proposed_corrections == []
    assert tb_after.qa_divergences == []
    # Slot stays at empty WriterArticle default
    assert tb_after.qa_corrected_article == WriterArticle()


def test_qa_analyze_clean_run_passes_post_validation():
    """The slot has mirrors_from="writer_article" so post-validation skips
    the non-empty check on qa_corrected_article. Without that exception,
    leaving the slot empty would trip StagePostconditionError."""
    fake = FakeAgent(
        structured={
            "problems_found": [],
            "proposed_corrections": [],
            "divergences": [],
        }
    )
    tb = _make_qa_topicbus()
    stage = QaAnalyzeStage(fake)
    tb_after = _run(stage, tb, _ro())

    rb_before_proxy = _ro()
    rb_after_proxy = _ro()
    # Must NOT raise
    validate_postconditions(
        stage,
        tb,
        tb_after,
        run_bus_before=rb_before_proxy,
        run_bus_after=rb_after_proxy,
    )


def test_qa_analyze_then_mirror_fills_corrected_article_from_writer():
    """End-to-end QA-clean-run: wrapper leaves qa_corrected_article empty,
    mirror_stage from V2-03a fills it from writer_article. After both
    stages run, qa_corrected_article equals writer_article."""
    fake = FakeAgent(
        structured={
            "problems_found": [],
            "proposed_corrections": [],
            "divergences": [],
        }
    )
    tb = _make_qa_topicbus()
    stage = QaAnalyzeStage(fake)
    tb_after_qa = _run(stage, tb, _ro())

    # qa_corrected_article is empty WriterArticle()
    assert tb_after_qa.qa_corrected_article == WriterArticle()

    # Run the V2-03b mirror logic directly
    mirror_stage(
        "qa_corrected_article",
        "writer_article",
        tb_after_qa,
        granularity="slot",
    )

    # After mirror: equal to writer_article
    assert tb_after_qa.qa_corrected_article == tb_after_qa.writer_article
    assert tb_after_qa.qa_corrected_article.headline == "Original headline"


def test_qa_analyze_problems_found_path_passes_post_validation():
    """Sanity: when the agent emits a corrected article, post-validation
    also passes (slot is non-empty)."""
    fake = FakeAgent(
        structured={
            "problems_found": [{"article_excerpt": "x", "problem": "p", "explanation": "e"}],
            "proposed_corrections": ["fix"],
            "article": {"headline": "C", "subheadline": "S", "body": "B", "summary": "Sm"},
            "divergences": [],
        }
    )
    tb = _make_qa_topicbus()
    stage = QaAnalyzeStage(fake)
    tb_after = _run(stage, tb, _ro())

    rb_before_proxy = _ro()
    rb_after_proxy = _ro()
    validate_postconditions(
        stage,
        tb,
        tb_after,
        run_bus_before=rb_before_proxy,
        run_bus_after=rb_after_proxy,
    )


def test_qa_analyze_schema_does_not_require_article():
    """Regression guard: the schema change ships atomic with this wrapper.
    QA_ANALYZE_SCHEMA's top-level required list must NOT include 'article'."""
    from src.schemas import QA_ANALYZE_SCHEMA

    assert "article" not in QA_ANALYZE_SCHEMA["required"], (
        "QA_ANALYZE_SCHEMA still requires 'article' — V2 prompt omits it on "
        "clean runs and the schema must allow that."
    )
    # Sanity: the other three are still required
    assert "problems_found" in QA_ANALYZE_SCHEMA["required"]
    assert "proposed_corrections" in QA_ANALYZE_SCHEMA["required"]
    assert "divergences" in QA_ANALYZE_SCHEMA["required"]
    # Sanity: article still defined as a property (just optional)
    assert "article" in QA_ANALYZE_SCHEMA["properties"]
