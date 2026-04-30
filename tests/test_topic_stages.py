"""Tests for src/stages/topic_stages.py and the select_topics run-stage.

One happy-path test per stage plus key edge cases per V1 contract.
Property-style tests for the source-id renumbering invariant.
"""

from __future__ import annotations

import asyncio

import pytest

from src.bus import (
    EditorAssignment,
    HydrationPhase2Corpus,
    HydrationPreDossier,
    ResearcherAssembleDossier,
    RunBus,
    SourceBalance,
    TopicBus,
    WriterArticle,
)
from src.stage import get_stage_meta
from src.stages._helpers import (
    normalise_country,
    normalise_language,
    strip_stale_quantifiers,
    validate_coverage_gaps,
)
from src.stages.run_stages import make_topic_bus, select_topics
from src.stages.topic_stages import (
    assemble_hydration_dossier,
    attach_hydration_urls,
    compose_transparency_card,
    compute_source_balance,
    merge_sources,
    mirror_perspective_synced,
    mirror_qa_corrected,
    normalize_pre_research,
    renumber_sources,
    validate_coverage_gaps_stage,
)


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus = None):
    return (rb or RunBus()).as_readonly()


# ---------------------------------------------------------------------------
# select_topics  (run-stage)
# ---------------------------------------------------------------------------


def test_select_topics_filters_priority_zero_and_slices_to_max_produce():
    rb = RunBus()
    rb.max_produce = 2
    rb.editor_assignments = [
        {"id": "tp-A", "title": "A", "priority": 9, "raw_data": {"source_ids": [1, 2, 3]}},
        {"id": "tp-B", "title": "B", "priority": 0, "raw_data": {}},  # rejected
        {"id": "tp-C", "title": "C", "priority": 9, "raw_data": {"source_ids": [1, 2, 3, 4]}},
        {"id": "tp-D", "title": "D", "priority": 5, "raw_data": {"source_ids": [1]}},
    ]

    rb = _run(select_topics, rb)

    # Sort: priority desc; tiebreaker source-count desc → C, A, D
    # max_produce=2 → top two: C, A
    assert [a["id"] for a in rb.selected_assignments] == ["tp-C", "tp-A"]
    # Original editor_assignments preserved
    assert len(rb.editor_assignments) == 4


def test_select_topics_metadata():
    meta = get_stage_meta(select_topics)
    assert meta.kind == "run"
    assert meta.reads == ("editor_assignments", "max_produce")
    assert meta.writes == ("selected_assignments",)


def test_select_topics_empty_when_all_rejected():
    rb = RunBus()
    rb.editor_assignments = [{"id": "x", "priority": 0}]
    rb = _run(select_topics, rb)
    assert rb.selected_assignments == []


# ---------------------------------------------------------------------------
# make_topic_bus helper
# ---------------------------------------------------------------------------


def test_make_topic_bus_from_dict():
    rb = RunBus()
    rb.run_id = "run-2026-04-30-abc"
    rb.run_date = "2026-04-30"
    assignment = {
        "id": "tp-2026-04-30-001",
        "topic_slug": "hello-world",
        "title": "Hello World",
        "priority": 8,
        "selection_reason": "matters",
    }
    tb = make_topic_bus(assignment, rb)
    assert isinstance(tb, TopicBus)
    assert tb.editor_selected_topic.id == "tp-2026-04-30-001"
    # Other slots remain at typed empty defaults
    assert tb.writer_article == WriterArticle()


def test_make_topic_bus_from_editor_assignment_instance():
    ea = EditorAssignment(id="x", title="t", priority=5)
    tb = make_topic_bus(ea, RunBus())
    assert tb.editor_selected_topic == ea


# ---------------------------------------------------------------------------
# merge_sources
# ---------------------------------------------------------------------------


def test_merge_sources_concatenates_in_order():
    tb = TopicBus()
    tb.hydration_pre_dossier = HydrationPreDossier(
        sources=[{"id": "hydrate-rsrc-001", "outlet": "BBC"}],
        preliminary_divergences=[{"description": "h-div"}],
        coverage_gaps=["h-gap"],
    )
    tb.researcher_assemble_dossier = ResearcherAssembleDossier(
        sources=[
            {"id": "research-rsrc-001", "outlet": "Reuters"},
            {"id": "research-rsrc-002", "outlet": "AFP"},
        ],
        preliminary_divergences=[{"description": "r-div"}],
        coverage_gaps=["r-gap-1", "r-gap-2"],
    )

    tb_after = _run(merge_sources, tb, _ro())

    assert [s["id"] for s in tb_after.merged_sources_pre_renumber] == [
        "hydrate-rsrc-001",
        "research-rsrc-001",
        "research-rsrc-002",
    ]
    assert tb_after.merged_preliminary_divergences == [
        {"description": "h-div"},
        {"description": "r-div"},
    ]
    assert tb_after.merged_coverage_gaps == ["h-gap", "r-gap-1", "r-gap-2"]


def test_merge_sources_production_variant_hydration_empty():
    """Production: hydration_pre_dossier stays at typed-empty default;
    merge_sources is effectively a copy from researcher_assemble_dossier."""
    tb = TopicBus()
    tb.researcher_assemble_dossier = ResearcherAssembleDossier(
        sources=[{"id": "research-rsrc-001"}],
        preliminary_divergences=[],
        coverage_gaps=[],
    )

    tb_after = _run(merge_sources, tb, _ro())

    assert len(tb_after.merged_sources_pre_renumber) == 1
    assert tb_after.merged_preliminary_divergences == []
    assert tb_after.merged_coverage_gaps == []


def test_merge_sources_does_not_mutate_input_bus():
    tb = TopicBus()
    tb.researcher_assemble_dossier = ResearcherAssembleDossier(
        sources=[{"id": "research-rsrc-001"}],
    )

    _ = _run(merge_sources, tb, _ro())
    # Input bus's slots remain as before — model_copy idiom
    assert tb.merged_sources_pre_renumber == []


# ---------------------------------------------------------------------------
# renumber_sources
# ---------------------------------------------------------------------------


def test_renumber_sources_assigns_gapless_src_nnn():
    tb = TopicBus()
    tb.merged_sources_pre_renumber = [
        {"id": "hydrate-rsrc-001", "outlet": "BBC"},
        {"id": "research-rsrc-001", "outlet": "Reuters"},
        {"id": "research-rsrc-002", "outlet": "AFP"},
    ]

    tb_after = _run(renumber_sources, tb, _ro())

    assert [s["id"] for s in tb_after.final_sources] == [
        "src-001",
        "src-002",
        "src-003",
    ]
    assert tb_after.id_rename_map == {
        "hydrate-rsrc-001": "src-001",
        "research-rsrc-001": "src-002",
        "research-rsrc-002": "src-003",
    }


def test_renumber_sources_preserves_non_id_fields():
    tb = TopicBus()
    tb.merged_sources_pre_renumber = [
        {
            "id": "hydrate-rsrc-001",
            "outlet": "BBC",
            "language": "en",
            "country": "United Kingdom",
        }
    ]
    tb_after = _run(renumber_sources, tb, _ro())
    assert tb_after.final_sources[0]["outlet"] == "BBC"
    assert tb_after.final_sources[0]["language"] == "en"
    assert tb_after.final_sources[0]["country"] == "United Kingdom"


def test_renumber_sources_invariant_property_no_gaps():
    """Invariant: for any non-empty merged input, final_sources carries
    src-001..src-NNN gaplessly."""
    for n in [1, 5, 17, 100]:
        tb = TopicBus()
        tb.merged_sources_pre_renumber = [
            {"id": f"x-{i:03d}"} for i in range(n)
        ]
        tb_after = _run(renumber_sources, tb, _ro())
        ids = [s["id"] for s in tb_after.final_sources]
        assert ids == [f"src-{i + 1:03d}" for i in range(n)]


# ---------------------------------------------------------------------------
# normalize_pre_research
# ---------------------------------------------------------------------------


def test_normalize_pre_research_rewrites_ids_in_divergences_and_gaps():
    tb = TopicBus()
    tb.id_rename_map = {
        "hydrate-rsrc-001": "src-001",
        "research-rsrc-001": "src-002",
    }
    tb.merged_preliminary_divergences = [
        {
            "type": "factual",
            "description": "Casualty figures differ",
            "source_ids": ["hydrate-rsrc-001", "research-rsrc-001"],
        }
    ]
    tb.merged_coverage_gaps = [
        # Coverage gaps are strings in V2 (per V1 _validate_coverage_gaps signature)
        # but if a future shape carries source_ids, the rewriter should walk it.
        {"text": "no UK domestic outlets", "source_ids": ["hydrate-rsrc-001"]},
    ]

    tb_after = _run(normalize_pre_research, tb, _ro())
    assert tb_after.merged_preliminary_divergences[0]["source_ids"] == [
        "src-001",
        "src-002",
    ]
    assert tb_after.merged_coverage_gaps[0]["source_ids"] == ["src-001"]


def test_normalize_pre_research_only_rewrites_exact_matches():
    """Strings that merely *contain* an old id token must not be rewritten —
    only exact-match strings do."""
    tb = TopicBus()
    tb.id_rename_map = {"hydrate-rsrc-001": "src-001"}
    tb.merged_preliminary_divergences = [
        {"description": "BBC reported (hydrate-rsrc-001) — see also story"},
    ]
    tb_after = _run(normalize_pre_research, tb, _ro())
    # Substring inside a longer description string is NOT rewritten
    assert (
        tb_after.merged_preliminary_divergences[0]["description"]
        == "BBC reported (hydrate-rsrc-001) — see also story"
    )


def test_normalize_pre_research_no_op_with_empty_rename_map():
    tb = TopicBus()
    tb.id_rename_map = {}
    tb.merged_preliminary_divergences = [{"description": "x"}]
    tb_after = _run(normalize_pre_research, tb, _ro())
    assert tb_after is tb  # exact identity — early return


# ---------------------------------------------------------------------------
# mirror_perspective_synced
# ---------------------------------------------------------------------------


def test_mirror_perspective_synced_production_1_to_1_copy():
    """Production: perspective_clusters_synced starts empty; mirror copies
    perspective_clusters verbatim (per-element with no deltas)."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"id": "pc-001", "position_label": "A"},
        {"id": "pc-002", "position_label": "B"},
    ]
    tb_after = _run(mirror_perspective_synced, tb, _ro())
    assert tb_after.perspective_clusters_synced == tb.perspective_clusters


def test_mirror_perspective_synced_hydrated_merges_deltas():
    """Hydrated: perspective_sync emitted deltas for some clusters; the
    mirror merges those deltas with the source clusters."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"id": "pc-001", "position_label": "Pro", "position_summary": "supports"},
        {"id": "pc-002", "position_label": "Anti", "position_summary": "opposes"},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "Strongly Pro"},
    ]
    tb_after = _run(mirror_perspective_synced, tb, _ro())
    result = tb_after.perspective_clusters_synced
    assert len(result) == 2
    assert result[0]["position_label"] == "Strongly Pro"
    assert result[0]["position_summary"] == "supports"  # source preserved
    assert result[1] == {"id": "pc-002", "position_label": "Anti", "position_summary": "opposes"}


# ---------------------------------------------------------------------------
# mirror_qa_corrected
# ---------------------------------------------------------------------------


def test_mirror_qa_corrected_clean_run_fills_from_writer():
    """Clean QA run: qa_corrected_article is empty (default WriterArticle);
    mirror copies writer_article into it."""
    tb = TopicBus()
    tb.writer_article = WriterArticle(
        headline="H", subheadline="S", body="B", summary="Sm"
    )
    # qa_corrected_article starts at WriterArticle() — empty

    tb_after = _run(mirror_qa_corrected, tb, _ro())
    assert tb_after.qa_corrected_article == tb.writer_article


def test_mirror_qa_corrected_qa_emitted_corrected_no_op():
    """QA found problems and emitted a corrected article; mirror is a no-op."""
    tb = TopicBus()
    tb.writer_article = WriterArticle(headline="orig", body="orig")
    tb.qa_corrected_article = WriterArticle(headline="fixed", body="fixed")

    tb_after = _run(mirror_qa_corrected, tb, _ro())
    assert tb_after.qa_corrected_article.headline == "fixed"
    assert tb_after.qa_corrected_article.body == "fixed"


# ---------------------------------------------------------------------------
# compute_source_balance
# ---------------------------------------------------------------------------


def test_compute_source_balance_normalises_country_aliases():
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "NYT", "language": "en", "country": "US"},
        {"id": "src-002", "outlet": "BBC", "language": "en", "country": "UK"},
        {"id": "src-003", "outlet": "Reuters", "language": "en", "country": "United States"},
        {"id": "src-004", "outlet": "Le Monde", "language": "French", "country": "France"},
    ]
    tb_after = _run(compute_source_balance, tb, _ro())
    sb = tb_after.source_balance
    assert sb.by_country == {
        "United States": 2,
        "United Kingdom": 1,
        "France": 1,
    }
    assert sb.by_language == {"en": 3, "fr": 1}
    assert sb.represented == ["France", "United Kingdom", "United States"]
    assert sb.missing_from_dossier == []


def test_compute_source_balance_handles_missing_metadata():
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001"},  # no language, no country
        {"id": "src-002", "country": "Germany"},
    ]
    tb_after = _run(compute_source_balance, tb, _ro())
    sb = tb_after.source_balance
    assert sb.by_country.get("Germany") == 1
    assert sb.by_country.get("unknown") == 1
    assert sb.by_language.get("unknown") == 2


# ---------------------------------------------------------------------------
# validate_coverage_gaps_stage
# ---------------------------------------------------------------------------


def test_validate_coverage_gaps_stage_drops_falsified_gaps():
    tb = TopicBus()
    tb.merged_coverage_gaps = [
        "No French-language sources in the dossier",  # falsified
        "Civilian survivors are absent from the coverage",  # qualitative — kept
    ]
    tb.source_balance = SourceBalance(
        by_language={"fr": 1, "en": 5},
        by_country={"France": 1},
    )

    tb_after = _run(validate_coverage_gaps_stage, tb, _ro())
    kept = tb_after.coverage_gaps_validated
    assert len(kept) == 1
    assert "Civilian survivors" in kept[0]


def test_validate_coverage_gaps_stage_dedupes_jaccard():
    tb = TopicBus()
    tb.merged_coverage_gaps = [
        "Civilian voices are missing from the coverage of the conflict",
        "Civilian voices missing from the conflict coverage entirely",  # near-dup
        "Independent analysts have not been quoted",  # different
    ]
    tb.source_balance = SourceBalance()

    tb_after = _run(validate_coverage_gaps_stage, tb, _ro())
    kept = tb_after.coverage_gaps_validated
    assert len(kept) == 2  # near-duplicate dropped


# ---------------------------------------------------------------------------
# compose_transparency_card
# ---------------------------------------------------------------------------


def test_compose_transparency_card_clean_run_no_article_original():
    """No QA problems → article_original stays None."""
    rb = RunBus()
    rb.run_id = "run-2026-04-30-abc"
    rb.run_date = "2026-04-30"

    tb = TopicBus(
        editor_selected_topic=EditorAssignment(
            id="tp-001", selection_reason="strong cross-language coverage"
        )
    )
    tb.writer_article = WriterArticle(headline="H", body="B")
    tb.qa_problems_found = []
    tb.qa_proposed_corrections = []

    tb_after = _run(compose_transparency_card, tb, rb.as_readonly())
    card = tb_after.transparency_card
    assert card.selection_reason == "strong cross-language coverage"
    assert card.pipeline_run == {"run_id": "run-2026-04-30-abc", "date": "2026-04-30"}
    assert card.article_original is None
    assert card.qa_problems_found == []


def test_compose_transparency_card_stale_quantifier_strip():
    """selection_reason carrying an Editor-time quantifier gets cleaned."""
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(
            selection_reason="Only two outlets covered it. The framing is contested."
        )
    )
    tb.writer_article = WriterArticle(headline="H", body="B")

    tb_after = _run(compose_transparency_card, tb, _ro())
    cleaned = tb_after.transparency_card.selection_reason
    assert "Only two outlets" not in cleaned
    assert "framing is contested" in cleaned


def test_compose_transparency_card_qa_changed_carries_article_original():
    tb = TopicBus(editor_selected_topic=EditorAssignment(selection_reason="x"))
    tb.writer_article = WriterArticle(headline="orig-H", body="orig-B")
    tb.qa_problems_found = [{"problem": "factually_incorrect", "excerpt": "..."}]
    tb.qa_proposed_corrections = ["replace X with Y"]

    tb_after = _run(compose_transparency_card, tb, _ro())
    card = tb_after.transparency_card
    assert card.article_original is not None
    assert card.article_original.headline == "orig-H"
    assert card.qa_problems_found == [{"problem": "factually_incorrect", "excerpt": "..."}]
    assert card.qa_proposed_corrections == ["replace X with Y"]


# ---------------------------------------------------------------------------
# attach_hydration_urls (hydrated)
# ---------------------------------------------------------------------------


def test_attach_hydration_urls_lifts_from_raw_data():
    tb = TopicBus(
        editor_selected_topic=EditorAssignment(
            id="tp-001",
            raw_data={
                "hydration_urls": [
                    {"url": "https://a.example/1", "outlet": "A"},
                    {"url": "https://b.example/2", "outlet": "B"},
                ]
            },
        )
    )
    tb_after = _run(attach_hydration_urls, tb, _ro())
    assert len(tb_after.hydration_urls) == 2
    assert tb_after.hydration_urls[0]["url"] == "https://a.example/1"


def test_attach_hydration_urls_handles_missing_raw_data_key():
    tb = TopicBus(editor_selected_topic=EditorAssignment(id="x", raw_data={}))
    tb_after = _run(attach_hydration_urls, tb, _ro())
    assert tb_after.hydration_urls == []


# ---------------------------------------------------------------------------
# assemble_hydration_dossier (hydrated)
# ---------------------------------------------------------------------------


def test_assemble_hydration_dossier_builds_from_phase1_and_phase2():
    tb = TopicBus()
    tb.hydration_fetch_results = [
        {
            "url": "https://a.example/1",
            "outlet": "BBC",
            "language": "en",
            "country": "United Kingdom",
            "title": "Story A",
            "status": "success",
        },
        {
            "url": "https://b.example/2",
            "outlet": "Le Monde",
            "language": "fr",
            "country": "France",
            "title": "Story B",
            "status": "success",
        },
        {"url": "https://blocked.example/3", "status": "bot_blocked"},  # excluded
    ]
    tb.hydration_phase1_analyses = [
        {
            "article_index": 0,
            "summary": "BBC summary",
            "actors_quoted": [
                {
                    "name": "PM",
                    "role": "Prime Minister",
                    "type": "official",
                    "position": "supports policy",
                    "verbatim_quote": "We will act.",
                }
            ],
        },
        {
            "article_index": 1,
            "summary": "Le Monde summary",
            "actors_quoted": [],
        },
    ]
    tb.hydration_phase2_corpus = HydrationPhase2Corpus(
        preliminary_divergences=[{"description": "Casualty figures differ"}],
        coverage_gaps=["No civil-society voices"],
    )

    tb_after = _run(assemble_hydration_dossier, tb, _ro())
    pre = tb_after.hydration_pre_dossier
    assert len(pre.sources) == 2
    assert pre.sources[0]["id"] == "hydrate-rsrc-001"
    assert pre.sources[0]["outlet"] == "BBC"
    assert pre.sources[0]["summary"] == "BBC summary"
    assert pre.sources[0]["actors_quoted"][0]["name"] == "PM"
    assert pre.sources[1]["id"] == "hydrate-rsrc-002"
    assert pre.preliminary_divergences == [{"description": "Casualty figures differ"}]
    assert pre.coverage_gaps == ["No civil-society voices"]


def test_assemble_hydration_dossier_filters_failed_fetches():
    """Only status==success records become hydrate-rsrc-NNN sources."""
    tb = TopicBus()
    tb.hydration_fetch_results = [
        {"url": "x", "status": "bot_blocked"},
        {"url": "y", "status": "success", "outlet": "Y"},
    ]
    tb.hydration_phase1_analyses = [
        {"article_index": 0, "summary": "Y summary"},
    ]
    tb.hydration_phase2_corpus = HydrationPhase2Corpus()
    tb_after = _run(assemble_hydration_dossier, tb, _ro())
    assert len(tb_after.hydration_pre_dossier.sources) == 1
    assert tb_after.hydration_pre_dossier.sources[0]["outlet"] == "Y"


# ---------------------------------------------------------------------------
# Helper unit tests (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("US", "United States"),
        ("USA", "United States"),
        ("u.s.", "United States"),
        ("UK", "United Kingdom"),
        ("Britain", "United Kingdom"),
        ("Hungary/Germany", ""),  # multi-country marker rejected
        ("Hungary and Germany", ""),
        (None, ""),
        ("", ""),
        ("Belgium", "Belgium"),  # not in alias table → echoed
    ],
)
def test_normalise_country(raw, expected):
    assert normalise_country(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("en", "en"),
        ("English", "en"),
        ("FRENCH", "fr"),
        ("zh-Hant", "zh-hant"),  # custom tag survives
        (None, ""),
        ("", ""),
    ],
)
def test_normalise_language(raw, expected):
    assert normalise_language(raw) == expected


def test_strip_stale_quantifiers_preserves_when_fully_stale():
    """If every sentence ends up dropped (residual <3 words ≥3 chars each),
    fall back to the original."""
    # Each sentence's residual after stripping has fewer than 3 content words
    # of length >=3, so both get dropped → fallback to the original.
    text = "Only two outlets. Few sources."
    out = strip_stale_quantifiers(text)
    assert out == text


def test_strip_stale_quantifiers_keeps_residual_when_substantive():
    """If the residual after stripping has >=3 content words, the cleaned
    sentence is kept."""
    text = "Only two outlets covered the regional protest movement."
    out = strip_stale_quantifiers(text)
    assert "Only two outlets" not in out
    assert "covered the regional protest movement" in out


def test_validate_coverage_gaps_keeps_qualitative():
    kept, dropped = validate_coverage_gaps(
        [
            "No civilian-survivor testimony in the coverage",
            "No French-language sources",
        ],
        {"by_language": {"fr": 2}, "by_country": {}},
    )
    assert len(kept) == 1
    assert "civilian-survivor" in kept[0]
    assert "French-language" in dropped[0]


# ---------------------------------------------------------------------------
# model_copy correctness — input bus is not mutated
# ---------------------------------------------------------------------------


def test_compute_source_balance_does_not_mutate_input():
    tb = TopicBus()
    tb.final_sources = [{"id": "src-001", "country": "Germany", "language": "de"}]
    original_sb = tb.source_balance
    _ = _run(compute_source_balance, tb, _ro())
    assert tb.source_balance is original_sb  # unchanged on input bus
    assert tb.source_balance.by_country == {}


def test_renumber_sources_does_not_mutate_input():
    tb = TopicBus()
    tb.merged_sources_pre_renumber = [{"id": "x-001"}, {"id": "x-002"}]
    _ = _run(renumber_sources, tb, _ro())
    assert tb.final_sources == []  # input bus unchanged
    assert tb.merged_sources_pre_renumber[0]["id"] == "x-001"
