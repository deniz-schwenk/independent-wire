"""Structural invariants for src/bus.py.

Six invariants per TASK-V2-01 §4:

1. Pre-initialisation completeness
2. Visibility metadata coverage
3. mirrors_from coverage and consistency
4. Read-only enforcement (frozen + deep-copy isolation)
5. is_empty semantics
6. Slot-count regression guard
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.bus import (
    EditorAssignment,
    HydrationPhase2Corpus,
    HydrationPreDossier,
    ResearcherAssembleDossier,
    RunBus,
    RunBusReadOnly,
    Slot,
    SourceBalance,
    TopicBus,
    TransparencyCard,
    WriterArticle,
    is_empty,
)

ALLOWED_VISIBILITIES = {"tp", "mcp", "rss", "internal"}
ALLOWED_GRANULARITIES = {"slot", "element"}


# ---------------------------------------------------------------------------
# Invariant 1 — Pre-initialisation completeness
# ---------------------------------------------------------------------------


def test_runbus_constructs_with_all_typed_empty_defaults():
    """A fresh RunBus has every declared field present at its typed empty default."""
    rb = RunBus()

    expected = {
        "run_id": "",
        "run_date": "",
        "run_variant": "",
        "max_produce": 3,
        "run_stage_log": [],
        "run_topic_manifest": [],
        "curator_findings": [],
        "curator_topics_unsliced": [],
        "curator_topics": [],
        "previous_coverage": [],
        "editor_assignments": [],
        "selected_assignments": [],
    }
    assert set(expected) == set(RunBus.model_fields), "RunBus fields drifted from expectation"
    for name, default in expected.items():
        assert getattr(rb, name) == default, f"{name} != {default!r}"


def test_topicbus_constructs_with_all_typed_empty_defaults():
    """A fresh TopicBus() has every declared field at its typed empty default."""
    tb = TopicBus()

    expected_simple = {
        "hydration_urls": [],
        "hydration_fetch_results": [],
        "hydration_phase1_analyses": [],
        "researcher_plan_queries": [],
        "researcher_search_results": [],
        "merged_sources_pre_renumber": [],
        "final_sources": [],
        "id_rename_map": {},
        "merged_preliminary_divergences": [],
        "merged_coverage_gaps": [],
        "perspective_clusters": [],
        "perspective_missing_positions": [],
        "qa_problems_found": [],
        "qa_proposed_corrections": [],
        "qa_divergences": [],
        "perspective_clusters_synced": [],
        "bias_language_findings": [],
        "bias_reader_note": "",
        "coverage_gaps_validated": [],
    }
    for name, default in expected_simple.items():
        assert getattr(tb, name) == default, f"{name} != {default!r}"

    # Sub-model defaults
    assert tb.editor_selected_topic == EditorAssignment()
    assert tb.hydration_phase2_corpus == HydrationPhase2Corpus()
    assert tb.hydration_pre_dossier == HydrationPreDossier()
    assert tb.researcher_assemble_dossier == ResearcherAssembleDossier()
    assert tb.writer_article == WriterArticle()
    assert tb.qa_corrected_article == WriterArticle()
    assert tb.source_balance == SourceBalance()
    assert tb.transparency_card == TransparencyCard()


def test_topicbus_accepts_explicit_editor_selected_topic():
    """A fresh TopicBus with a populated editor_selected_topic constructs cleanly.

    Mirrors how `instantiate_topic_buses` will build it: pass the assignment dict
    in at construction time, every other slot at its typed empty default.
    """
    assignment = EditorAssignment(
        id="tp-2026-04-30-001",
        topic_slug="example-topic",
        title="Example Topic",
        priority=8,
        selection_reason="strong cross-language coverage",
    )
    tb = TopicBus(editor_selected_topic=assignment)
    assert tb.editor_selected_topic == assignment
    assert tb.writer_article == WriterArticle()


# ---------------------------------------------------------------------------
# Invariant 2 — Visibility metadata coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", [RunBus, TopicBus])
def test_every_field_has_visibility_metadata(model):
    """Every slot on RunBus and TopicBus carries a visibility annotation."""
    for name, field in model.model_fields.items():
        extra = field.json_schema_extra
        assert isinstance(extra, dict), f"{model.__name__}.{name} missing json_schema_extra"
        assert "visibility" in extra, f"{model.__name__}.{name} missing visibility"

        viz = extra["visibility"]
        # Accept list of tags or a single tag string
        if isinstance(viz, str):
            tags = [viz]
        else:
            assert isinstance(viz, (list, tuple)), (
                f"{model.__name__}.{name} visibility wrong type: {type(viz)}"
            )
            tags = list(viz)
        assert len(tags) >= 1, f"{model.__name__}.{name} visibility is empty"
        for tag in tags:
            assert tag in ALLOWED_VISIBILITIES, (
                f"{model.__name__}.{name} visibility {tag!r} not in {ALLOWED_VISIBILITIES}"
            )


# ---------------------------------------------------------------------------
# Invariant 3 — mirrors_from coverage and consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", [RunBus, TopicBus])
def test_mirrors_from_is_consistent(model):
    """Every slot with mirrors_from declares mirror_granularity, the source field
    exists on the same Bus, and the source field has a compatible type.
    """
    for name, field in model.model_fields.items():
        extra = field.json_schema_extra or {}
        if "mirrors_from" not in extra:
            assert "mirror_granularity" not in extra, (
                f"{model.__name__}.{name} declares mirror_granularity without mirrors_from"
            )
            continue

        source_name = extra["mirrors_from"]
        granularity = extra.get("mirror_granularity")

        assert granularity in ALLOWED_GRANULARITIES, (
            f"{model.__name__}.{name} bad mirror_granularity {granularity!r}"
        )
        assert source_name in model.model_fields, (
            f"{model.__name__}.{name} mirrors_from non-existent slot {source_name!r}"
        )

        # Type compatibility: same outer Python type at the annotation level.
        target_ann = field.annotation
        source_ann = model.model_fields[source_name].annotation
        assert target_ann is source_ann, (
            f"{model.__name__}.{name} type {target_ann} incompatible with "
            f"source {source_name} type {source_ann}"
        )


def test_qa_corrected_article_mirrors_from_writer_article_slot_level():
    """Specific check for §4B.7."""
    extra = TopicBus.model_fields["qa_corrected_article"].json_schema_extra
    assert extra["mirrors_from"] == "writer_article"
    assert extra["mirror_granularity"] == "slot"


def test_perspective_clusters_synced_mirrors_from_perspective_clusters_per_element():
    """Specific check for §4B.8."""
    extra = TopicBus.model_fields["perspective_clusters_synced"].json_schema_extra
    assert extra["mirrors_from"] == "perspective_clusters"
    assert extra["mirror_granularity"] == "element"


# ---------------------------------------------------------------------------
# Invariant 4 — Read-only enforcement
# ---------------------------------------------------------------------------


def test_readonly_proxy_field_assignment_raises():
    """Writing to a slot on the frozen proxy raises Pydantic ValidationError."""
    rb = RunBus()
    rb.run_id = "run-001"
    rb.curator_findings = [{"id": "f-001"}]

    ro = rb.as_readonly()
    assert ro.run_id == "run-001"
    assert ro.curator_findings == [{"id": "f-001"}]

    with pytest.raises(ValidationError):
        ro.run_id = "tampered"

    with pytest.raises(ValidationError):
        ro.curator_findings = []


def test_readonly_proxy_inplace_mutation_does_not_propagate():
    """Deep-copy on construction isolates inner mutables; in-place mutation on the
    proxy must not affect the source RunBus."""
    rb = RunBus()
    rb.curator_findings = [{"id": "f-001"}]
    rb.run_stage_log = [{"stage": "init_run", "status": "ok"}]

    ro = rb.as_readonly()

    # Pydantic V2 frozen=True does NOT block in-place list mutation; the
    # invariant we promise is isolation via deep-copy at construction.
    ro.curator_findings.append({"id": "leaked"})
    ro.run_stage_log[0]["status"] = "tampered"

    assert rb.curator_findings == [{"id": "f-001"}], "proxy leaked into source list"
    assert rb.run_stage_log == [{"stage": "init_run", "status": "ok"}], (
        "proxy leaked into source dict element"
    )


def test_readonly_proxy_class_is_frozen():
    """Sanity: the read-only proxy class is configured frozen at the model level."""
    assert RunBusReadOnly.model_config.get("frozen") is True


# ---------------------------------------------------------------------------
# Invariant 5 — is_empty semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, True),
        ("", True),
        ([], True),
        ({}, True),
        ((), True),
        (0, False),
        (False, False),
        (True, False),
        (1, False),
        ("populated", False),
        ([0], False),
        ([None], False),
        ({"k": "v"}, False),
        ({"k": None}, False),
    ],
)
def test_is_empty_primitive(value, expected):
    assert is_empty(value) is expected


def test_is_empty_submodel_default_is_empty_when_all_fields_empty():
    """WriterArticle() is empty (all four strings default to "")."""
    assert is_empty(WriterArticle()) is True


def test_is_empty_submodel_with_one_field_populated_is_not_empty():
    assert is_empty(WriterArticle(headline="something")) is False


def test_is_empty_editor_assignment_default_is_not_empty_due_to_priority_zero():
    """priority=0 is data per spec (numeric zero is not 'empty'); a fresh
    EditorAssignment is therefore not is_empty even with all string/optional
    fields at defaults."""
    assert is_empty(EditorAssignment()) is False


def test_is_empty_writer_article_after_full_population_is_not_empty():
    art = WriterArticle(headline="H", subheadline="S", body="B", summary="Sm")
    assert is_empty(art) is False


def test_is_empty_nested_submodel_propagates():
    """TransparencyCard with article_original=None and other fields default → empty."""
    assert is_empty(TransparencyCard()) is True

    populated = TransparencyCard(article_original=WriterArticle(headline="x"))
    assert is_empty(populated) is False


# ---------------------------------------------------------------------------
# Invariant 6 — Slot-count regression guard
# ---------------------------------------------------------------------------


def test_runbus_slot_count_regression_guard():
    """Hard-coded expectation. Any change in slot count without architect approval
    fails this test and forces review. Source of truth: ARCH-V2-BUS-SCHEMA §4A.

    Expected: 12 slots across 3 phases plus selection (4A.1 metadata=6,
    4A.2 curator=3, 4A.3 editor=2, selection=1 — selected_assignments
    written by select_topics per ARCH §5.1 stage 4).
    """
    assert len(RunBus.model_fields) == 12


def test_topicbus_slot_count_regression_guard():
    """Hard-coded expectation. Source: ARCH-V2-BUS-SCHEMA §4B.1–§4B.11.

    Expected: 27 slots across 11 phases.
    Phase counts: 4B.1=1, 4B.2=5, 4B.3=3, 4B.4=5, 4B.5=2, 4B.6=1, 4B.7=4,
    4B.8=1, 4B.9=2, 4B.10=1, 4B.11=2.
    """
    assert len(TopicBus.model_fields) == 27


# ---------------------------------------------------------------------------
# Slot helper validation (defensive)
# ---------------------------------------------------------------------------


def test_slot_rejects_unknown_visibility():
    with pytest.raises(ValueError, match="unknown visibility"):
        Slot("", visibility="public")  # type: ignore[arg-type]


def test_slot_requires_granularity_with_mirrors_from():
    with pytest.raises(ValueError, match="mirror_granularity"):
        Slot(default_factory=list, visibility="internal", mirrors_from="other")


def test_slot_rejects_granularity_without_mirrors_from():
    with pytest.raises(ValueError, match="mirrors_from"):
        Slot(
            default_factory=list,
            visibility="internal",
            mirror_granularity="slot",
        )


def test_slot_requires_default_or_factory():
    with pytest.raises(ValueError, match="default"):
        Slot(visibility="internal")  # type: ignore[call-arg]


def test_slot_rejects_both_default_and_factory():
    with pytest.raises(ValueError, match="default OR default_factory"):
        Slot("", visibility="internal", default_factory=list)
