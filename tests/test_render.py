"""Tests for src/render.py — visibility filter and the five render functions.

Fifteen invariants per TASK-V2-04 §4 plus a small set of defensive checks.
"""

from __future__ import annotations

import json

import pytest

from src.bus import (
    EditorAssignment,
    RunBus,
    SourceBalance,
    TopicBus,
    TransparencyCard,
    WriterArticle,
)
from src.render import (
    RSS_BASE_URL,
    compose_bias_card,
    render_internal_debug,
    render_mcp_response,
    render_rss_entry,
    render_tp_public,
    select_by_visibility,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_runbus() -> RunBus:
    rb = RunBus()
    rb.run_id = "run-2026-04-30-abc"
    rb.run_date = "2026-04-30"
    rb.run_variant = "production"
    rb.max_produce = 3
    rb.previous_coverage = [
        {
            "tp_id": "tp-2026-04-29-002",
            "date": "2026-04-29",
            "headline": "Talks Stall as Deadline Approaches",
            "slug": "talks-stall",
            "summary": "Negotiators end the round without progress.",
        }
    ]
    return rb


def _make_topicbus(
    *,
    qa_corrected: WriterArticle | None = None,
    follow_up: bool = False,
) -> TopicBus:
    """Construct a fully-populated TopicBus for render tests."""
    assignment = EditorAssignment(
        id="tp-2026-04-30-001",
        topic_slug="strait-of-hormuz-fees",
        title="United States Imposes Transit Fees on the Strait of Hormuz",
        priority=8,
        selection_reason="strong cross-language coverage",
        follow_up_to="tp-2026-04-29-002" if follow_up else None,
        follow_up_reason="enforcement deadline reached" if follow_up else None,
    )
    tb = TopicBus(editor_selected_topic=assignment)
    tb.final_sources = [
        {"id": "src-001", "outlet": "Reuters", "country": "United States", "language": "en"},
        {"id": "src-002", "outlet": "AFP", "country": "France", "language": "fr"},
        {"id": "src-003", "outlet": "Tasnim", "country": "Iran", "language": "fa"},
    ]
    tb.perspective_clusters_synced = [
        {
            "id": "pc-001",
            "position_label": "US administration",
            "position_summary": "frames as security-cost recovery",
            "actor_ids": ["actor-001"],
            "source_ids": ["src-001"],
        },
        {
            "id": "pc-002",
            "position_label": "Iranian state media",
            "position_summary": "calls move economic coercion",
            "actor_ids": ["actor-002"],
            "source_ids": ["src-003"],
        },
    ]
    tb.final_actors = [
        {"id": "actor-001", "name": "Spokesperson"},
        {"id": "actor-002", "name": "Foreign Ministry"},
    ]
    tb.perspective_missing_positions = [
        {"label": "civilian seafarers", "reason": "no direct testimony"}
    ]
    tb.writer_article = WriterArticle(
        headline="Original headline",
        subheadline="Original sub",
        body="Original body [src-001].",
        summary="Original summary",
    )
    tb.qa_corrected_article = qa_corrected if qa_corrected is not None else tb.writer_article.model_copy(deep=True)
    tb.qa_problems_found = []
    tb.qa_corrections = []
    tb.qa_divergences = [
        {
            "type": "factual",
            "description": "deadline timeline differs",
            "source_ids": ["src-001", "src-003"],
            "resolution": "partially_resolved",
            "resolution_note": "both attributed",
        }
    ]
    tb.coverage_gaps_validated = ["No civil-society voices in the dossier"]
    tb.source_balance = SourceBalance(
        by_country={"United States": 1, "France": 1, "Iran": 1},
        by_language={"en": 1, "fr": 1, "fa": 1},
        represented=["France", "Iran", "United States"],
        missing_from_dossier=[],
    )
    tb.bias_language_findings = [
        {"excerpt": "controversial move", "issue": "loaded language", "explanation": "x"}
    ]
    tb.bias_reader_note = "This report draws on three outlets across three languages."
    tb.transparency_card = TransparencyCard(
        selection_reason="strong cross-language coverage",
        pipeline_run={"run_id": "run-2026-04-30-abc", "date": "2026-04-30"},
        article_original=None,
        qa_problems_found=[],
        qa_corrections=[],
    )
    return tb


# ---------------------------------------------------------------------------
# 1-3. select_by_visibility
# ---------------------------------------------------------------------------


def test_select_by_visibility_topicbus_tp():
    """tp-tagged TopicBus slots: final_sources + qa_problems_found +
    qa_corrections + qa_corrected_article + qa_divergences +
    perspective_clusters_synced + bias_language_findings + bias_reader_note +
    coverage_gaps_validated + source_balance + transparency_card."""
    tb = _make_topicbus()
    out = select_by_visibility(tb, "tp")
    expected = {
        "final_sources",
        "qa_problems_found",
        "qa_corrections",
        "qa_corrected_article",
        "qa_divergences",
        "perspective_clusters_synced",
        "bias_language_findings",
        "bias_reader_note",
        "coverage_gaps_validated",
        "source_balance",
        "transparency_card",
    }
    assert set(out) == expected
    assert out["final_sources"] == tb.final_sources
    # Sub-models are model_dump'd
    assert out["source_balance"]["by_country"] == {"United States": 1, "France": 1, "Iran": 1}


def test_select_by_visibility_topicbus_internal():
    """Symmetric sanity: internal-tagged TopicBus slots are returned."""
    tb = TopicBus()
    out = select_by_visibility(tb, "internal")
    assert "writer_article" in out
    assert "researcher_assemble_dossier" in out
    assert "hydration_pre_dossier" in out
    assert "merged_sources_pre_renumber" in out
    # tp-only slots are NOT in the internal selection
    assert "qa_corrected_article" not in out
    assert "final_sources" not in out


def test_select_by_visibility_runbus_tp():
    """RunBus has tp-visible slots — run_id, run_date carry tp tag."""
    rb = _make_runbus()
    out = select_by_visibility(rb, "tp")
    assert set(out) == {"run_id", "run_date"}
    assert out["run_id"] == "run-2026-04-30-abc"
    assert out["run_date"] == "2026-04-30"


# ---------------------------------------------------------------------------
# 4. render_tp_public structural shape
# ---------------------------------------------------------------------------


def test_render_tp_public_shape():
    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_tp_public(tb, rb)

    expected_keys = {
        "id",
        "version",
        "status",
        "metadata",
        "sources",
        "perspectives",
        "divergences",
        "gaps",
        "article",
        "bias_analysis",
        "transparency",
    }
    assert set(out) == expected_keys

    assert out["id"] == "tp-2026-04-30-001"
    assert out["version"] == "1.0"
    assert out["status"] == "review"
    assert isinstance(out["metadata"], dict)
    assert isinstance(out["sources"], list)
    assert isinstance(out["perspectives"], dict)
    assert isinstance(out["divergences"], list)
    assert isinstance(out["gaps"], list)
    assert isinstance(out["article"], dict)
    assert isinstance(out["bias_analysis"], dict)
    assert isinstance(out["transparency"], dict)
    # No visualizations field — V2 omits it entirely
    assert "visualizations" not in out


def test_render_tp_public_metadata_fields():
    rb = _make_runbus()
    tb = _make_topicbus()
    md = render_tp_public(tb, rb)["metadata"]
    assert md["title"] == "United States Imposes Transit Fees on the Strait of Hormuz"
    assert md["date"] == "2026-04-30"
    assert md["status"] == "review"
    assert md["topic_slug"] == "strait-of-hormuz-fees"
    assert md["priority"] == 8
    assert md["selection_reason"] == "strong cross-language coverage"


# ---------------------------------------------------------------------------
# 5-6. article from qa_corrected_article — clean run vs corrected run
# ---------------------------------------------------------------------------


def test_render_tp_public_article_on_clean_run():
    """Clean run: qa_corrected_article was filled by the mirror from
    writer_article. Rendered article must equal the writer's content."""
    tb = _make_topicbus()  # default: qa_corrected = writer (mirror semantics)
    out = render_tp_public(tb, _make_runbus())
    assert out["article"]["headline"] == "Original headline"
    assert out["article"]["body"] == "Original body [src-001]."


def test_render_tp_public_article_on_corrected_run():
    """QA found problems and emitted a corrected article. Rendered article
    must equal the corrected version, NOT the writer's."""
    corrected = WriterArticle(
        headline="Corrected headline",
        subheadline="Corrected sub",
        body="Corrected body [src-001].",
        summary="Corrected summary",
    )
    tb = _make_topicbus(qa_corrected=corrected)
    out = render_tp_public(tb, _make_runbus())
    assert out["article"]["headline"] == "Corrected headline"
    assert out["article"]["body"] == "Corrected body [src-001]."
    # Writer's content stays on writer_article (not in render output)


# ---------------------------------------------------------------------------
# 7. perspectives reshape — V1 flat list → V2 dict
# ---------------------------------------------------------------------------


def test_render_tp_public_perspectives_reshape_to_dict():
    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_tp_public(tb, rb)
    persp = out["perspectives"]
    assert isinstance(persp, dict)
    assert set(persp) == {"position_clusters", "missing_positions"}
    assert persp["position_clusters"] == tb.perspective_clusters_synced
    assert persp["missing_positions"] == tb.perspective_missing_positions


# ---------------------------------------------------------------------------
# 8. follow_up handling
# ---------------------------------------------------------------------------


def test_render_tp_public_follow_up_none_when_not_set():
    out = render_tp_public(_make_topicbus(follow_up=False), _make_runbus())
    assert out["metadata"]["follow_up"] is None


def test_render_tp_public_follow_up_passthrough_when_set():
    """metadata.follow_up carries previous_headline + previous_date,
    resolved from run_bus.previous_coverage by tp_id match."""
    out = render_tp_public(_make_topicbus(follow_up=True), _make_runbus())
    fu = out["metadata"]["follow_up"]
    assert fu == {
        "previous_tp_id": "tp-2026-04-29-002",
        "reason": "enforcement deadline reached",
        "previous_headline": "Talks Stall as Deadline Approaches",
        "previous_date": "2026-04-29",
    }


def test_render_tp_public_follow_up_unmatched_tp_id_returns_empty_strings():
    """When `follow_up_to` does not match any previous_coverage entry,
    `previous_headline` / `previous_date` come through as empty strings —
    the downstream renderer treats that as "hide the DIV"."""
    rb = _make_runbus()
    rb.previous_coverage = []  # no matches
    out = render_tp_public(_make_topicbus(follow_up=True), rb)
    fu = out["metadata"]["follow_up"]
    assert fu["previous_tp_id"] == "tp-2026-04-29-002"
    assert fu["reason"] == "enforcement deadline reached"
    assert fu["previous_headline"] == ""
    assert fu["previous_date"] == ""


# ---------------------------------------------------------------------------
# 9. render_mcp_response = render_tp_public + QA reasoning
# ---------------------------------------------------------------------------


def test_render_mcp_response_extends_tp_public():
    rb = _make_runbus()
    tb = _make_topicbus()
    base = render_tp_public(tb, rb)
    mcp = render_mcp_response(tb, rb)
    # Every key from tp_public is present
    for key in base:
        assert key in mcp
    # Plus QA reasoning at top level
    assert "qa_problems_found" in mcp
    assert "qa_corrections" in mcp
    assert mcp["qa_problems_found"] == tb.qa_problems_found
    assert mcp["qa_corrections"] == [c.model_dump() for c in tb.qa_corrections]


# ---------------------------------------------------------------------------
# 10. render_rss_entry minimal shape
# ---------------------------------------------------------------------------


def test_render_rss_entry_five_keys():
    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_rss_entry(tb, rb)
    assert set(out) == {"title", "description", "link", "pubDate", "guid"}
    assert out["title"] == "Original headline"
    assert out["description"] == "Original summary"
    assert out["link"] == f"{RSS_BASE_URL}strait-of-hormuz-fees"
    assert out["pubDate"] == "2026-04-30"
    assert out["guid"] == "tp-2026-04-30-001"


# ---------------------------------------------------------------------------
# 11. render_internal_debug — no filtering
# ---------------------------------------------------------------------------


def test_render_internal_debug_includes_everything():
    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_internal_debug(tb, rb)
    assert set(out) == {"topic_bus", "run_bus"}
    assert out["topic_bus"]["editor_selected_topic"]["id"] == "tp-2026-04-30-001"
    assert out["run_bus"]["run_id"] == "run-2026-04-30-abc"
    # Internal-only slots (e.g. writer_article, hydration_*) are present
    assert "writer_article" in out["topic_bus"]
    assert "hydration_pre_dossier" in out["topic_bus"]
    assert "merged_sources_pre_renumber" in out["topic_bus"]


# ---------------------------------------------------------------------------
# 12-13. compose_bias_card shape + empty-state robustness
# ---------------------------------------------------------------------------


def test_compose_bias_card_shape():
    tb = _make_topicbus()
    card = compose_bias_card(tb)
    assert set(card) == {
        "language",
        "source",
        "geographical",
        "selection",
        "framing",
        "reader_note",
    }
    # language: list of findings
    assert card["language"] == tb.bias_language_findings
    # source: by_country + by_language + represented + total
    assert set(card["source"]) == {"by_country", "by_language", "represented", "total"}
    assert card["source"]["total"] == 3
    # geographical
    assert set(card["geographical"]) == {"represented", "by_country", "missing_from_dossier"}
    # selection
    assert set(card["selection"]) == {"coverage_gaps", "missing_positions", "qa_problems_found"}
    assert card["selection"]["coverage_gaps"] == tb.coverage_gaps_validated
    assert card["selection"]["missing_positions"] == tb.perspective_missing_positions
    # framing — representation_distribution is gone; objective counts only
    assert set(card["framing"]) == {
        "position_clusters_summary",
        "cross_source_divergences",
        "cluster_count",
        "distinct_actor_count",
    }
    summary = card["framing"]["position_clusters_summary"]
    assert len(summary) == 2
    assert set(summary[0]) == {"id", "position_label", "n_actors", "n_sources"}
    assert summary[0] == {
        "id": "pc-001",
        "position_label": "US administration",
        "n_actors": 1,
        "n_sources": 1,
    }
    # reader_note
    assert card["reader_note"] == tb.bias_reader_note


def test_compose_bias_card_empty_state_robustness():
    """Most slots at typed empty defaults — compose_bias_card returns a
    well-formed structure with empty sub-values."""
    tb = TopicBus()
    card = compose_bias_card(tb)
    assert card["language"] == []
    assert card["source"]["total"] == 0
    assert card["source"]["by_country"] == {}
    assert card["geographical"]["represented"] == []
    assert card["selection"]["coverage_gaps"] == []
    assert card["framing"]["position_clusters_summary"] == []
    assert card["framing"]["cross_source_divergences"] == []
    assert card["framing"]["cluster_count"] == 0
    assert card["framing"]["distinct_actor_count"] == 0
    assert "representation_distribution" not in card["framing"]
    assert card["reader_note"] == ""


def test_compose_bias_card_framing_aggregates_populated():
    """Cluster-aggregate fields in the framing block — populated case.

    cluster_count counts dict clusters; distinct_actor_count reads
    ``len(final_actors)`` (the canonical deduped list — no per-cluster
    walk).
    """
    tb = TopicBus()
    tb.perspective_clusters_synced = [
        {
            "id": "pc-001",
            "position_label": "Pro",
            "actor_ids": ["actor-001", "actor-002"],
            "source_ids": ["src-001"],
        },
        {
            "id": "pc-002",
            "position_label": "Skeptic",
            "actor_ids": ["actor-001", "actor-003"],
            "source_ids": ["src-002"],
        },
        {
            "id": "pc-003",
            "position_label": "Anti",
            "actor_ids": [],
            "source_ids": ["src-003"],
        },
        "not-a-dict-cluster",  # skipped
    ]
    tb.final_actors = [
        {"id": "actor-001", "name": "Alice"},
        {"id": "actor-002", "name": "Bob"},
        {"id": "actor-003", "name": "Carol"},
        {"id": "actor-004", "name": ""},  # missing name → ignored
    ]
    card = compose_bias_card(tb)
    framing = card["framing"]

    # 3 dict-shaped clusters, the string entry is skipped
    assert framing["cluster_count"] == 3

    # 3 entries in final_actors with non-empty name
    assert framing["distinct_actor_count"] == 3


# ---------------------------------------------------------------------------
# 14. Coverage check on visibility metadata
# ---------------------------------------------------------------------------


def test_render_tp_public_covers_every_tp_visible_topicbus_slot():
    """Regression guard: every `tp`-visible TopicBus slot must appear in the
    rendered output, possibly via a reshape entry. The render module's
    `_TP_RESHAPED_SLOTS` map declares which slots land where."""
    from src.render import _TP_RESHAPED_SLOTS

    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_tp_public(tb, rb)

    tp_visible = select_by_visibility(tb, "tp")
    for slot_name in tp_visible:
        # Either directly present in output, or declared as a reshape
        if slot_name in out:
            continue
        assert slot_name in _TP_RESHAPED_SLOTS, (
            f"tp-visible slot {slot_name!r} is not in render_tp_public "
            f"output and not declared as a reshape in _TP_RESHAPED_SLOTS"
        )


# ---------------------------------------------------------------------------
# 15. JSON-serialisable invariant
# ---------------------------------------------------------------------------


def test_render_tp_public_is_json_serialisable():
    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_tp_public(tb, rb)
    # Must not raise — catches Pydantic-model leaks, datetime objects, etc.
    s = json.dumps(out)
    assert isinstance(s, str)
    # Round-trip works
    assert json.loads(s) == out


def test_render_mcp_response_is_json_serialisable():
    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_mcp_response(tb, rb)
    json.dumps(out)


def test_render_rss_entry_is_json_serialisable():
    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_rss_entry(tb, rb)
    json.dumps(out)


def test_render_internal_debug_is_json_serialisable():
    rb = _make_runbus()
    tb = _make_topicbus()
    out = render_internal_debug(tb, rb)
    json.dumps(out)


def test_compose_bias_card_is_json_serialisable():
    tb = _make_topicbus()
    json.dumps(compose_bias_card(tb))


# ---------------------------------------------------------------------------
# Defensive checks
# ---------------------------------------------------------------------------


def test_select_by_visibility_accepts_runbus_readonly():
    """Read-only proxy is a Pydantic BaseModel too; the filter works on it."""
    rb = _make_runbus()
    proxy = rb.as_readonly()
    out = select_by_visibility(proxy, "tp")
    assert out == {"run_id": "run-2026-04-30-abc", "run_date": "2026-04-30"}


def test_render_tp_public_accepts_runbus_readonly():
    """Render functions operate on RunBus or RunBusReadOnly equivalently."""
    rb = _make_runbus()
    tb = _make_topicbus()
    out_writable = render_tp_public(tb, rb)
    out_readonly = render_tp_public(tb, rb.as_readonly())
    assert out_writable == out_readonly
