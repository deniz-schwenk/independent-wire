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
    EditorStage,
    ResearcherPlanStage,
    _assign_ids_and_slugs,
    _attach_raw_data_from_curated,
    _enrich_curator_output,
    _parse_agent_output,
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


def test_enrich_curator_output_source_diversity_from_outlet_registry(monkeypatch):
    """Post 2026-05-29 migration: source_diversity reads tier and
    editorial_independence from the outlet registry by lookup_outlet(
    finding['source_url']), not from sources.json by source_name."""
    from src import outlet_registry
    outlet_registry._load_registry.cache_clear()
    monkeypatch.setattr(
        outlet_registry,
        "_load_registry",
        lambda: {
            "reuters.com": {
                "outlet": "Reuters",
                "tier": 1,
                "editorial_independence": "independent",
            },
        },
    )
    findings = [
        {
            "region": "x",
            "language": "en",
            "source_name": "Reuters",
            "source_url": "https://www.reuters.com/world/article.html",
        },
    ]
    topics = [{"title": "T", "source_ids": ["finding-0"]}]
    out = _enrich_curator_output(topics, findings)
    diversity = out[0]["source_diversity"]
    assert diversity == [
        {"name": "Reuters", "tier": 1, "editorial_independence": "independent"},
    ]


def test_enrich_curator_output_unknown_hostname_is_graceful(monkeypatch):
    """A finding whose source_url hostname is not in the registry gets
    tier and editorial_independence at None — graceful, not crashing."""
    from src import outlet_registry
    outlet_registry._load_registry.cache_clear()
    monkeypatch.setattr(outlet_registry, "_load_registry", lambda: {})
    findings = [
        {
            "region": "x",
            "language": "en",
            "source_name": "Unknown",
            "source_url": "https://unknown-site.example/article",
        },
    ]
    topics = [{"title": "T", "source_ids": ["finding-0"]}]
    out = _enrich_curator_output(topics, findings)
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
    ConsolidatorStage,
    HydrationPhase1Stage,
    HydrationPhase2Stage,
    PerspectiveStage,
    ResearcherAssembleStage,
    ResearcherHydratedPlanStage,
    WriterStage,
    _build_bias_card_for_agent_input,
    _extract_date_from_url,
)
from src.bus import (  # noqa: E402
    Correction,
    HydrationPhase2Corpus,
    HydrationPreDossier,
    ResearcherAssembleDossier,
    SourceBalance,
    WhatIsMissing,
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
            # Test fixture continues to emit ``coverage_gaps`` to
            # confirm ResearcherAssembleStage silently drops it
            # (HydrationPhase2 single source of truth, 2026-05-21).
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
    # ResearcherAssembleStage no longer populates coverage_gaps; the
    # field stays on the dossier model with its default empty list
    # so the legacy non-hydrated stage list still type-checks.
    assert dossier.coverage_gaps == []


def test_researcher_assemble_empty_output():
    fake = FakeAgent(structured={"sources": [], "preliminary_divergences": [], "coverage_gaps": []})
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    stage = ResearcherAssembleStage(fake)
    tb_after = _run(stage, tb, _ro())
    assert tb_after.researcher_assemble_dossier.sources == []


# ---------------------------------------------------------------------------
# ResearcherAssemble empty-output retry — DeepSeek cache-cold mitigation
# ---------------------------------------------------------------------------


class _SequencedAssembleAgent:
    """FakeAgent variant returning successive pre-baked AgentResults from
    a queue. Used to drive the empty-retry path in ResearcherAssembleStage."""

    def __init__(self, results: list[AgentResult]):
        self._results = list(results)
        self.name = "fake-research-assemble"
        self.model = "deepseek/deepseek-v4-flash"
        self.temperature = 0.5
        self.max_tokens = 160000
        self.reasoning = "none"
        self.calls: list[dict] = []

    async def run(self, message: str = "", context: dict | None = None, **kwargs):
        self.calls.append({"message": message, "context": context, **kwargs})
        if not self._results:
            raise AssertionError(
                "_SequencedAssembleAgent exhausted — too many calls"
            )
        return self._results.pop(0)


def _assemble_empty_result(response_id: str, tokens: int = 8000) -> AgentResult:
    return AgentResult(
        content="",
        structured={"sources": [], "preliminary_divergences": [], "coverage_gaps": []},
        cost_usd=0.001,
        tokens_used=tokens,
        response_id=response_id,
    )


def _assemble_nonempty_result(
    *, n_sources: int = 2, response_id: str = "resp-ok"
) -> AgentResult:
    return AgentResult(
        content="",
        structured={
            "sources": [
                {
                    "url": f"https://outlet{i}.example/2026/05/01/story",
                    "outlet": f"Outlet {i}",
                    "language": "en",
                    "country": "United States",
                    "summary": f"summary {i}",
                    "actors_quoted": [],
                }
                for i in range(n_sources)
            ],
            "preliminary_divergences": [],
            "coverage_gaps": [],
        },
        cost_usd=0.003,
        tokens_used=15_000,
        response_id=response_id,
    )


def _make_assemble_tb_rb():
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(title="t", selection_reason="r")
    )
    tb.researcher_search_results = [{"query": "x", "results": "..."}]
    rb = RunBus()
    rb.run_date = "2026-05-01"
    return tb, rb


def test_researcher_assemble_retry_empty_empty_nonempty(caplog):
    import logging

    agent = _SequencedAssembleAgent([
        _assemble_empty_result(response_id="resp-1"),
        _assemble_empty_result(response_id="resp-2"),
        _assemble_nonempty_result(n_sources=3, response_id="resp-3"),
    ])
    stage = ResearcherAssembleStage(agent)
    tb, rb = _make_assemble_tb_rb()

    with caplog.at_level(logging.WARNING, logger="src.agent_stages"):
        tb_after = _run(stage, tb, rb.as_readonly())

    dossier = tb_after.researcher_assemble_dossier
    assert len(dossier.sources) == 3
    assert dossier.sources[0]["id"] == "research-rsrc-001"
    assert tb_after.researcher_assemble_n_attempts == 3
    assert len(agent.calls) == 3

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(warns) == 2
    msgs = " ".join(r.getMessage() for r in warns)
    assert "ResearcherAssembleStage" in msgs
    assert "attempt 1/3" in msgs
    assert "attempt 2/3" in msgs
    assert "resp-1" in msgs
    assert "resp-2" in msgs
    assert errs == []


def test_researcher_assemble_retry_all_three_empty_fires_postcondition(caplog):
    """All 3 attempts empty → empty dossier, ERROR logged, and the
    writes-postcondition on `researcher_assemble_dossier` (no
    optional_write, no mirrors_from) fires loud — verifies the
    downstream gate, not just the wrapper's internal assertion."""
    import logging

    from src.stage import StagePostconditionError, validate_postconditions

    agent = _SequencedAssembleAgent([
        _assemble_empty_result(response_id="resp-1"),
        _assemble_empty_result(response_id="resp-2"),
        _assemble_empty_result(response_id="resp-3"),
    ])
    stage = ResearcherAssembleStage(agent)
    tb, rb = _make_assemble_tb_rb()
    rb_ro_before = rb.as_readonly()

    with caplog.at_level(logging.WARNING, logger="src.agent_stages"):
        tb_after = _run(stage, tb, rb_ro_before)

    dossier = tb_after.researcher_assemble_dossier
    assert dossier.sources == []
    assert dossier.preliminary_divergences == []
    assert dossier.coverage_gaps == []
    assert tb_after.researcher_assemble_n_attempts == 3
    assert len(agent.calls) == 3

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(warns) == 2
    assert len(errs) == 1
    assert "all 3 attempts" in errs[0].getMessage()

    # Downstream gate: the writes-postcondition on the empty dossier slot
    # raises StagePostconditionError.
    import pytest
    with pytest.raises(StagePostconditionError) as exc:
        validate_postconditions(
            stage,
            tb,
            tb_after,
            run_bus_before=rb_ro_before,
            run_bus_after=rb.as_readonly(),
        )
    assert "researcher_assemble_dossier" in str(exc.value)


def test_researcher_assemble_retry_non_empty_first_call_no_retry(caplog):
    import logging

    agent = _SequencedAssembleAgent([
        _assemble_nonempty_result(n_sources=2, response_id="resp-ok"),
    ])
    stage = ResearcherAssembleStage(agent)
    tb, rb = _make_assemble_tb_rb()

    with caplog.at_level(logging.WARNING, logger="src.agent_stages"):
        tb_after = _run(stage, tb, rb.as_readonly())

    dossier = tb_after.researcher_assemble_dossier
    assert len(dossier.sources) == 2
    assert tb_after.researcher_assemble_n_attempts == 1
    assert len(agent.calls) == 1

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert warns == []
    assert errs == []


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
    enrichment (pc-NNN, regions, languages, n_*) is the
    `enrich_perspective_clusters` topic-stage's job and runs immediately
    after this wrapper. Wrapper output must NOT carry those fields."""
    fake = FakeAgent(
        structured={
            "position_clusters": [
                {
                    "position_label": "Pro",
                    "position_summary": "supports",
                    "source_ids": ["src-001", "src-002"],
                    "actor_ids": ["actor-001"],
                },
                {
                    "position_label": "Anti",
                    "position_summary": "opposes",
                    "source_ids": ["src-003"],
                    "actor_ids": ["actor-002"],
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
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    stage = PerspectiveStage(fake)
    tb_after = _run(stage, tb, _ro())
    clusters = tb_after.perspective_clusters
    assert len(clusters) == 2
    # Raw shape only — agent emits position_label, position_summary, source_ids, actor_ids
    assert clusters[0] == {
        "position_label": "Pro",
        "position_summary": "supports",
        "source_ids": ["src-001", "src-002"],
        "actor_ids": ["actor-001"],
    }
    # No enrichment fields on the wrapper output
    assert "id" not in clusters[0]
    assert "regions" not in clusters[0]
    assert "languages" not in clusters[0]
    assert "n_sources" not in clusters[0]
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
        {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]}
    ]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
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
        {"id": "pc-001", "actor_ids": [], "source_ids": ["src-001"]}
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
        {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
        {"id": "pc-002", "actor_ids": [], "source_ids": ["src-002"]},
    ]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    tb.qa_divergences = [{"type": "factual"}]
    bc = _build_bias_card_for_agent_input(tb)
    assert bc["article_summary"] == "my summary"
    assert bc["source_balance"]["total"] == 2
    assert bc["perspectives"]["cluster_count"] == 2
    assert bc["perspectives"]["distinct_actor_count"] == 1
    assert "representation_distribution" not in bc["perspectives"]
    assert bc["factual_divergences"] == [{"type": "factual"}]
    # Consolidator refactor: both keys removed from the bias-card input.
    # The Bias-Detector prompt no longer reads gap or missing-position
    # commentary; that surface moved to the Consolidator stage.
    assert "missing_positions" not in bc["perspectives"]
    assert "coverage_gaps" not in bc


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
    assert tb_after.hydration_phase1_n_attempts_per_chunk == []
    # Agent should NOT have been called
    assert len(fake.calls) == 0


# ---------------------------------------------------------------------------
# HydrationPhase1 empty-output retry — DeepSeek cache-cold mitigation
# ---------------------------------------------------------------------------


class _SequencedPhase1Agent:
    """FakeAgent variant returning a queue of pre-baked AgentResults.

    Used for the single-chunk Phase-1 retry-path tests."""

    def __init__(self, results: list[AgentResult]):
        self._results = list(results)
        self.name = "fake-phase1"
        self.model = "deepseek/deepseek-v4-pro"
        self.temperature = 0.3
        self.max_tokens = 32000
        self.reasoning = "none"
        self.calls: list[dict] = []

    async def run(self, message: str = "", context: dict | None = None, **kwargs):
        self.calls.append({"message": message, "context": context or {}})
        if not self._results:
            raise AssertionError(
                "_SequencedPhase1Agent exhausted — too many calls"
            )
        return self._results.pop(0)


def _phase1_response(*, n_articles: int, actors_per: int) -> AgentResult:
    """Build a strict-mode Phase-1 response with the given content
    density. ``actors_per=0`` is the empty-mode signal (every article
    analysis returns 0 quoted actors)."""
    return AgentResult(
        content="",
        structured={
            "article_analyses": [
                {
                    "article_index": i,
                    "summary": f"summary {i}",
                    "actors_quoted": [
                        {
                            "name": f"Actor {i}-{k}",
                            "role": "spokesperson",
                            "type": "government",
                            "position": "p",
                            "evidence_type": "stated",
                            "verbatim_quote": None,
                        }
                        for k in range(actors_per)
                    ],
                }
                for i in range(n_articles)
            ]
        },
        cost_usd=0.01,
        tokens_used=20_000,
        response_id=f"resp-{actors_per}",
    )


def _make_phase1_tb(n_articles: int = 1) -> TopicBus:
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.hydration_fetch_results = [
        {
            "url": f"https://outlet{i}.example/article/{i}",
            "status": "success",
            "title": f"Article {i}",
            "outlet": f"Outlet {i}",
            "language": "en",
            "country": "United States",
            "extracted_text": f"Body of article {i}.",
        }
        for i in range(n_articles)
    ]
    return tb


def test_hydration_phase1_retry_empty_empty_nonempty(caplog):
    """Single chunk (1 article). Empty / empty / non-empty → 3 calls,
    2 WARNINGs, n_attempts_per_chunk=[3]."""
    import logging

    agent = _SequencedPhase1Agent([
        _phase1_response(n_articles=1, actors_per=0),  # empty
        _phase1_response(n_articles=1, actors_per=0),  # empty
        _phase1_response(n_articles=1, actors_per=2),  # non-empty
    ])
    stage = HydrationPhase1Stage(agent)
    tb = _make_phase1_tb(n_articles=1)

    with caplog.at_level(logging.WARNING, logger="src.agent_stages"):
        tb_after = _run(stage, tb, _ro())

    analyses = tb_after.hydration_phase1_analyses
    assert len(analyses) == 1
    assert len(analyses[0]["actors_quoted"]) == 2
    assert tb_after.hydration_phase1_n_attempts_per_chunk == [3]
    assert len(agent.calls) == 3

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    # 2 empty-retry WARNINGs for chunk 1
    empty_warns = [
        r for r in warns if "empty output on attempt" in r.getMessage()
    ]
    assert len(empty_warns) == 2
    msgs = " ".join(r.getMessage() for r in empty_warns)
    assert "chunk 1" in msgs
    assert "attempt 1/3" in msgs
    assert "attempt 2/3" in msgs
    assert errs == []


def test_hydration_phase1_retry_all_three_empty_falls_through(caplog):
    """All 3 attempts empty → ERROR logged, empty analyses written (no
    actors_quoted on the single article), n_attempts_per_chunk=[3].
    Phase-2 (downstream) is robust to zero-actor article analyses —
    there is no postcondition gate that fires loud on this case; the
    ERROR log and the new per-chunk attempts list are the audit
    signals."""
    import logging

    agent = _SequencedPhase1Agent([
        _phase1_response(n_articles=1, actors_per=0),
        _phase1_response(n_articles=1, actors_per=0),
        _phase1_response(n_articles=1, actors_per=0),
    ])
    stage = HydrationPhase1Stage(agent)
    tb = _make_phase1_tb(n_articles=1)

    with caplog.at_level(logging.WARNING, logger="src.agent_stages"):
        tb_after = _run(stage, tb, _ro())

    analyses = tb_after.hydration_phase1_analyses
    assert len(analyses) == 1
    assert analyses[0]["actors_quoted"] == []
    assert tb_after.hydration_phase1_n_attempts_per_chunk == [3]
    assert len(agent.calls) == 3

    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errs) == 1
    msg = errs[0].getMessage()
    assert "chunk 1" in msg
    assert "all 3 attempts" in msg


def test_hydration_phase1_retry_non_empty_first_call_no_retry(caplog):
    """Non-empty on first call → exactly one agent.run(), no WARNINGs
    or ERRORs from the empty-output retry path. n_attempts_per_chunk=[1]."""
    import logging

    agent = _SequencedPhase1Agent([
        _phase1_response(n_articles=1, actors_per=3),
    ])
    stage = HydrationPhase1Stage(agent)
    tb = _make_phase1_tb(n_articles=1)

    with caplog.at_level(logging.WARNING, logger="src.agent_stages"):
        tb_after = _run(stage, tb, _ro())

    analyses = tb_after.hydration_phase1_analyses
    assert len(analyses) == 1
    assert len(analyses[0]["actors_quoted"]) == 3
    assert tb_after.hydration_phase1_n_attempts_per_chunk == [1]
    assert len(agent.calls) == 1

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    empty_warns = [
        r for r in warns if "empty output on attempt" in r.getMessage()
    ]
    assert empty_warns == []
    assert errs == []


def test_hydration_phase1_retry_mixed_three_chunks_independent(caplog):
    """Three parallel chunks with independent retry counts.

    Forces 3 chunks via 21 articles (``_distribute_chunks`` formula
    ceil(N/10)). Mock dispatches by inspecting which article URLs are
    in the chunk's payload:
      - chunk 1 (articles 0-6):  clean first attempt → n_attempts=1
      - chunk 2 (articles 7-13): empty, empty, non-empty → n_attempts=2
      - chunk 3 (articles 14-20): empty on all 3 → n_attempts=3.

    Asserts the new `n_attempts_per_chunk` list captures
    `[1, 2, 3]` and that the parallel gather did not let chunk 3's
    failure prevent chunks 1 and 2 from producing content."""
    import logging

    chunk2_call_count = 0
    chunk3_call_count = 0

    class _ChunkAwareAgent:
        name = "fake-mixed-phase1"
        model = "deepseek/deepseek-v4-pro"
        temperature = 0.3
        max_tokens = 32000
        reasoning = "none"

        def __init__(self):
            self.calls: list[dict] = []

        async def run(self, message: str = "", context: dict | None = None, **kwargs):
            nonlocal chunk2_call_count, chunk3_call_count
            self.calls.append({"message": message, "context": context or {}})
            ctx = context or {}
            articles = ctx.get("articles") or []
            urls = [a.get("url") or "" for a in articles if isinstance(a, dict)]
            first_url = urls[0] if urls else ""
            n_remaining = len(articles)

            if first_url.startswith("https://chunk1-"):
                return _phase1_response(n_articles=n_remaining, actors_per=2)

            if first_url.startswith("https://chunk2-"):
                chunk2_call_count += 1
                actors = 0 if chunk2_call_count == 1 else 2
                # Chunk 2 succeeds on its 2nd attempt; the 2nd call
                # returns a complete non-empty payload.
                return _phase1_response(n_articles=n_remaining, actors_per=actors)

            if first_url.startswith("https://chunk3-"):
                chunk3_call_count += 1
                return _phase1_response(n_articles=n_remaining, actors_per=0)

            raise AssertionError(f"Unexpected article URL: {first_url!r}")

    agent = _ChunkAwareAgent()
    stage = HydrationPhase1Stage(agent)

    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    # 21 articles → ceil(21/10) = 3 chunks of 7 each
    # chunk 1: articles 0-6 (urls chunk1-N), chunk 2: 7-13 (chunk2-N),
    # chunk 3: 14-20 (chunk3-N).
    tb.hydration_fetch_results = [
        {
            "url": f"https://chunk1-{i}.example/article",
            "status": "success",
            "title": f"Chunk1 article {i}",
            "outlet": "Outlet",
            "language": "en",
            "country": "US",
            "extracted_text": f"Body {i}.",
        }
        for i in range(7)
    ] + [
        {
            "url": f"https://chunk2-{i}.example/article",
            "status": "success",
            "title": f"Chunk2 article {i}",
            "outlet": "Outlet",
            "language": "en",
            "country": "US",
            "extracted_text": f"Body {i}.",
        }
        for i in range(7)
    ] + [
        {
            "url": f"https://chunk3-{i}.example/article",
            "status": "success",
            "title": f"Chunk3 article {i}",
            "outlet": "Outlet",
            "language": "en",
            "country": "US",
            "extracted_text": f"Body {i}.",
        }
        for i in range(7)
    ]

    with caplog.at_level(logging.WARNING, logger="src.agent_stages"):
        tb_after = _run(stage, tb, _ro())

    # Independent retries: [1, 2, 3].
    assert tb_after.hydration_phase1_n_attempts_per_chunk == [1, 2, 3]
    # Chunks 1 and 2 produced quoted-actor content; chunk 3 stayed empty.
    analyses = tb_after.hydration_phase1_analyses
    assert len(analyses) == 21
    # Articles 0-6: from chunk 1 → 2 actors each.
    assert all(len(a["actors_quoted"]) == 2 for a in analyses[0:7])
    # Articles 7-13: from chunk 2 (after 1 retry) → 2 actors each.
    assert all(len(a["actors_quoted"]) == 2 for a in analyses[7:14])
    # Articles 14-20: chunk 3 stayed empty.
    assert all(a["actors_quoted"] == [] for a in analyses[14:21])

    # Total calls: chunk 1 (1) + chunk 2 (2) + chunk 3 (3) = 6.
    assert len(agent.calls) == 6
    assert chunk2_call_count == 2
    assert chunk3_call_count == 3

    # WARNINGs from chunks 2 (1 retry) and 3 (2 retries) + 1 ERROR
    # from chunk 3's exhausted retries.
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    errs = [r for r in caplog.records if r.levelno == logging.ERROR]
    empty_warns = [
        r for r in warns if "empty output on attempt" in r.getMessage()
    ]
    assert len(empty_warns) == 3  # chunk2:1 + chunk3:2
    assert len(errs) == 1
    err_msg = errs[0].getMessage()
    assert "chunk 3" in err_msg
    assert "all 3 attempts" in err_msg


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
# ConsolidatorStage — owns what_is_missing (Consolidator refactor)
# ===========================================================================


def test_consolidator_metadata():
    s = ConsolidatorStage(FakeAgent())
    m = get_stage_meta(s)
    assert m.kind == "topic"
    assert m.reads == ("perspective_missing_positions", "merged_coverage_gaps")
    assert m.writes == ("what_is_missing",)


def test_consolidator_builds_context_and_writes_what_is_missing():
    """Wrapper builds the two-array context the consolidator agent
    expects (matching its INSTRUCTIONS contract) and writes the parsed
    output to ``what_is_missing`` as a typed :class:`WhatIsMissing`."""
    voices_emitted = [
        "Iraqi government and media voices",
        "International humanitarian organizations (ICRC, MSF, UNHCR)",
    ]
    topics_emitted = [
        "Humanitarian dimension of the US oil blockade",
    ]
    fake = FakeAgent(
        structured={
            "voices_missing": voices_emitted,
            "topics_missing": topics_emitted,
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.perspective_missing_positions = [
        {"type": "government", "description": "Iraqi government"},
        {"type": "international_org", "description": "Humanitarian orgs"},
    ]
    tb.merged_coverage_gaps = [
        "No humanitarian-dimension coverage of US oil blockade",
    ]
    stage = ConsolidatorStage(fake)
    tb_after = _run(stage, tb, _ro())

    assert isinstance(tb_after.what_is_missing, WhatIsMissing)
    assert tb_after.what_is_missing.voices_missing == voices_emitted
    assert tb_after.what_is_missing.topics_missing == topics_emitted

    # Context shape matches the prompt's input contract (the two array
    # names the INSTRUCTIONS reference).
    ctx = fake.calls[0]["context"]
    assert ctx["perspective_missing_positions"] == [
        {"type": "government", "description": "Iraqi government"},
        {"type": "international_org", "description": "Humanitarian orgs"},
    ]
    assert ctx["merged_coverage_gaps"] == [
        "No humanitarian-dimension coverage of US oil blockade",
    ]


def test_consolidator_drops_non_string_entries_defensively():
    """Defensive filter — if the LLM emits non-string list entries
    (schema-illegal but observed under JSON-repair fallbacks), the
    wrapper drops them rather than corrupting the typed slot."""
    fake = FakeAgent(
        structured={
            "voices_missing": ["valid voice", "", None, 42, "another voice"],
            "topics_missing": [None, "valid topic"],
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.perspective_missing_positions = [{"type": "x", "description": "y"}]
    tb.merged_coverage_gaps = ["z"]

    tb_after = _run(ConsolidatorStage(fake), tb, _ro())

    assert tb_after.what_is_missing.voices_missing == ["valid voice", "another voice"]
    assert tb_after.what_is_missing.topics_missing == ["valid topic"]


def test_consolidator_empty_inputs_write_empty_output():
    """Both inputs empty → wrapper still calls the agent once (the
    prompt is robust to empty arrays per its OUTPUT FORMAT field-notes)
    and writes whatever the agent emits."""
    fake = FakeAgent(structured={"voices_missing": [], "topics_missing": []})
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    # perspective_missing_positions and merged_coverage_gaps default to [].
    tb_after = _run(ConsolidatorStage(fake), tb, _ro())

    assert tb_after.what_is_missing.voices_missing == []
    assert tb_after.what_is_missing.topics_missing == []
    assert len(fake.calls) == 1


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
        "qa_corrections",
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
            "qa_corrections": [
                {"proposed_correction": "Replace X with Y.", "correction_needed": True}
            ],
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
    assert len(tb_after.qa_corrections) == 1
    assert tb_after.qa_corrections[0].proposed_correction == "Replace X with Y."
    assert tb_after.qa_corrections[0].correction_needed is True
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
            "qa_corrections": [],
            # `article` field absent — V2 prompt omits it on clean runs
            "divergences": [],
        }
    )
    tb = _make_qa_topicbus()
    stage = QaAnalyzeStage(fake)
    tb_after = _run(stage, tb, _ro())

    assert tb_after.qa_problems_found == []
    assert tb_after.qa_corrections == []
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
            "qa_corrections": [],
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
            "qa_corrections": [],
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
            "qa_corrections": [{"proposed_correction": "fix", "correction_needed": True}],
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
    assert "qa_corrections" in QA_ANALYZE_SCHEMA["required"]
    assert "divergences" in QA_ANALYZE_SCHEMA["required"]
    # Sanity: article still defined as a property (just optional)
    assert "article" in QA_ANALYZE_SCHEMA["properties"]


def test_qa_analyze_all_retractions_omits_corrected_article():
    """Every entry has correction_needed=False → wrapper does NOT write
    qa_corrected_article (mirror fills from writer_article downstream)."""
    fake = FakeAgent(
        structured={
            "problems_found": [
                {"article_excerpt": "x", "problem": "p", "explanation": "e"},
                {"article_excerpt": "y", "problem": "p", "explanation": "e"},
            ],
            "qa_corrections": [
                {"proposed_correction": "retract: source mislabel", "correction_needed": False},
                {"proposed_correction": "retract: duplicate", "correction_needed": False},
            ],
            # `article` field could be present or absent — wrapper must ignore
            # it when no correction_needed=True is set.
            "article": {"headline": "X", "subheadline": "X", "body": "X", "summary": "X"},
            "divergences": [],
        }
    )
    tb = _make_qa_topicbus()
    stage = QaAnalyzeStage(fake)
    tb_after = _run(stage, tb, _ro())

    assert len(tb_after.qa_corrections) == 2
    assert all(not c.correction_needed for c in tb_after.qa_corrections)
    # qa_corrected_article stays at empty default (mirror handles downstream)
    assert tb_after.qa_corrected_article == WriterArticle()


def test_qa_analyze_mixed_corrections_emits_corrected_article():
    """At least one correction_needed=True → wrapper writes qa_corrected_article."""
    fake = FakeAgent(
        structured={
            "problems_found": [
                {"article_excerpt": "x", "problem": "p", "explanation": "e"},
                {"article_excerpt": "y", "problem": "p", "explanation": "e"},
            ],
            "qa_corrections": [
                {"proposed_correction": "retract", "correction_needed": False},
                {"proposed_correction": "real fix", "correction_needed": True},
            ],
            "article": {
                "headline": "Corrected H",
                "subheadline": "Corrected S",
                "body": "Corrected B",
                "summary": "Corrected Sm",
            },
            "divergences": [],
        }
    )
    tb = _make_qa_topicbus()
    stage = QaAnalyzeStage(fake)
    tb_after = _run(stage, tb, _ro())

    assert tb_after.qa_corrected_article.headline == "Corrected H"
    assert any(c.correction_needed for c in tb_after.qa_corrections)


def test_correction_model_field_order_is_load_bearing():
    """The strict-mode JSON Schema reflects field declaration order.
    proposed_correction must precede correction_needed so Sonnet writes the
    text before committing to the boolean."""
    fields = list(Correction.model_fields.keys())
    assert fields == ["proposed_correction", "correction_needed"], (
        f"Correction field order drifted: {fields}. Sonnet streams output in "
        "declared order; the boolean must arrive after the text."
    )
