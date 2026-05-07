"""Tests for src/stages/topic_stages.py and the select_topics run-stage.

One happy-path test per stage plus key edge cases per V1 contract.
Property-style tests for the source-id renumbering invariant.
"""

from __future__ import annotations

import asyncio

import pytest

from src.bus import (
    Correction,
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
    enrich_perspective_clusters,
    merge_sources,
    mirror_perspective_synced,
    mirror_qa_corrected,
    normalize_pre_research,
    prune_unused_sources_and_clusters,
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
# enrich_perspective_clusters  (V2-06b — split from PerspectiveStage)
# ---------------------------------------------------------------------------


def test_enrich_perspective_clusters_metadata():
    from src.stage import get_stage_meta

    meta = get_stage_meta(enrich_perspective_clusters)
    assert meta.kind == "topic"
    assert meta.reads == (
        "perspective_clusters",
        "final_sources",
        "canonical_actors",
    )
    assert meta.writes == ("perspective_clusters",)


def test_enrich_perspective_clusters_assigns_pc_nnn_in_order():
    """pc-NNN ids are assigned 1-based in the cluster array's order."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"position_label": "Pro", "source_ids": []},
        {"position_label": "Anti", "source_ids": []},
        {"position_label": "Neutral", "source_ids": []},
    ]
    tb.final_sources = []
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    assert [c["id"] for c in tb_after.perspective_clusters] == [
        "pc-001",
        "pc-002",
        "pc-003",
    ]


def test_enrich_perspective_clusters_no_longer_walks_actors_quoted():
    """The leak loop that fanned every source's actors_quoted into every
    cluster citing the source is gone. cluster.actor_ids is the validated
    agent-assigned mapping; regions and languages still derive from cited
    sources deterministically.
    """
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001", "src-002"],
            "actor_ids": ["actor-001"],
        },
    ]
    tb.final_sources = [
        {
            "id": "src-001",
            "country": "United States",
            "language": "en",
            "actors_quoted": [
                {
                    "name": "PM",
                    "role": "Prime Minister",
                    "type": "official",
                    "verbatim_quote": "We will act.",
                },
            ],
        },
        {
            "id": "src-002",
            "country": "United Kingdom",
            "language": "en",
            "actors_quoted": [
                {
                    "name": "Analyst",
                    "role": "Researcher",
                    "type": "expert",
                    "verbatim_quote": "Plausible interpretation.",
                },
            ],
        },
    ]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "PM"},
        {"id": "actor-002", "name": "Analyst"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert "actors" not in cluster
    assert cluster["actor_ids"] == ["actor-001"]
    assert cluster["regions"] == ["United Kingdom", "United States"]
    assert cluster["languages"] == ["en"]
    assert cluster["n_actors"] == 1
    assert cluster["n_sources"] == 2
    assert cluster["n_regions"] == 2
    assert cluster["n_languages"] == 1
    assert "representation" not in cluster


def test_enrich_perspective_clusters_count_fields_replace_representation():
    """The temporary `representation` bucket is gone. Counts are first-
    class deterministic outputs of the stage."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Big",
            "source_ids": ["src-001", "src-002", "src-003"],
            "actor_ids": ["actor-001", "actor-002"],
        },
        {
            "position_label": "Med",
            "source_ids": ["src-004"],
            "actor_ids": ["actor-003"],
        },
        {"position_label": "None", "source_ids": [], "actor_ids": []},
    ]
    tb.final_sources = [
        {"id": f"src-{i:03d}", "country": "X", "language": "en"} for i in range(1, 6)
    ]
    tb.canonical_actors = [
        {"id": f"actor-{i:03d}", "name": f"a{i}"} for i in range(1, 4)
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    n_sources = [c["n_sources"] for c in tb_after.perspective_clusters]
    n_actors = [c["n_actors"] for c in tb_after.perspective_clusters]
    assert n_sources == [3, 1, 0]
    assert n_actors == [2, 1, 0]
    for cluster in tb_after.perspective_clusters:
        assert "representation" not in cluster


def test_enrich_perspective_clusters_empty_dossier_does_not_warn():
    """final_sources empty: stage no longer emits a representation-warning
    (representation is gone). Counts are simply zero."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"position_label": "A", "source_ids": ["src-001"], "actor_ids": []},
        {"position_label": "B", "source_ids": [], "actor_ids": []},
    ]
    tb.final_sources = []
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    for c in tb_after.perspective_clusters:
        assert "representation" not in c


def test_enrich_perspective_clusters_missing_source_ids_is_safe():
    """Cluster with no source_ids → still gets pc-NNN, empty regions/
    languages, zero counts."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"position_label": "Orphan"},  # no source_ids field at all
    ]
    tb.final_sources = [
        {"id": "src-001", "country": "X", "language": "en", "actors_quoted": []},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["id"] == "pc-001"
    assert cluster["regions"] == []
    assert cluster["languages"] == []
    assert cluster["n_sources"] == 0
    assert cluster["n_actors"] == 0
    assert "representation" not in cluster


def test_enrich_perspective_clusters_unknown_source_id_skipped():
    """Cluster references a source not in final_sources → skipped silently
    in region/language walking; n_sources still uses the raw len(source_ids)."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"position_label": "X", "source_ids": ["src-001", "src-999"], "actor_ids": []},
    ]
    tb.final_sources = [
        {
            "id": "src-001",
            "country": "United States",
            "language": "en",
            "actors_quoted": [{"name": "A", "role": "r", "type": "t"}],
        }
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["regions"] == ["United States"]
    assert cluster["n_sources"] == 2  # raw count of source_ids
    assert cluster["n_regions"] == 1  # only matched sources counted


def test_enrich_perspective_clusters_empty_input_is_no_op():
    """No clusters → wrapper returns the bus unchanged (early exit; the
    perspective_clusters slot has optional_write so post-validation passes)."""
    tb = TopicBus()
    tb.perspective_clusters = []
    tb.final_sources = [{"id": "src-001"}]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    assert tb_after.perspective_clusters == []


def test_enrich_perspective_clusters_idempotent():
    """Running enrichment twice produces the same result — pc-NNN ids
    overwrite any existing id field, deterministic fields recomputed
    consistently."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"position_label": "A", "source_ids": ["src-001"]},
    ]
    tb.final_sources = [
        {
            "id": "src-001",
            "country": "United States",
            "language": "en",
            "actors_quoted": [
                {"name": "PM", "role": "PM", "type": "official",
                 "verbatim_quote": "Q"},
            ],
        }
    ]
    tb_once = _run(enrich_perspective_clusters, tb, _ro())
    tb_twice = _run(enrich_perspective_clusters, tb_once, _ro())
    assert tb_once.perspective_clusters == tb_twice.perspective_clusters


def test_enrich_perspective_clusters_does_not_mutate_input():
    tb = TopicBus()
    tb.perspective_clusters = [{"position_label": "A", "source_ids": []}]
    tb.final_sources = []
    _ = _run(enrich_perspective_clusters, tb, _ro())
    # Input bus unchanged — model_copy idiom
    assert "id" not in tb.perspective_clusters[0]
    assert "n_sources" not in tb.perspective_clusters[0]


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
    tb.qa_corrections = []

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
    tb.qa_corrections = [Correction(proposed_correction="replace X with Y", correction_needed=True)]

    tb_after = _run(compose_transparency_card, tb, _ro())
    card = tb_after.transparency_card
    assert card.article_original is not None
    assert card.article_original.headline == "orig-H"
    assert card.qa_problems_found == [{"problem": "factually_incorrect", "excerpt": "..."}]
    assert len(card.qa_corrections) == 1
    assert card.qa_corrections[0].proposed_correction == "replace X with Y"
    assert card.qa_corrections[0].correction_needed is True


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


# ---------------------------------------------------------------------------
# V2-06: researcher_search topic-stage
# ---------------------------------------------------------------------------


from src.stages.topic_stages import make_researcher_search  # noqa: E402


class FakeWebSearchTool:
    def __init__(self, responses: dict[str, str], fail_query: str | None = None):
        self.responses = responses
        self.fail_query = fail_query
        self.calls: list[str] = []

    async def execute(self, query: str) -> str:
        self.calls.append(query)
        if query == self.fail_query:
            raise RuntimeError("simulated search failure")
        return self.responses.get(query, "No results")


def test_researcher_search_metadata():
    stage = make_researcher_search(FakeWebSearchTool({}))
    from src.stage import get_stage_meta as _gm

    m = _gm(stage)
    assert m.kind == "topic"
    assert m.reads == ("researcher_plan_queries",)
    assert m.writes == ("researcher_search_results",)


def test_researcher_search_happy_path():
    """Three queries, web_search returns canned text, deduplication and
    url_dates enrichment work."""
    canned = {
        "Strait of Hormuz transit fees": (
            "1. Strait fees imposed\n"
            "   https://reuters.example/2026/04/30/strait-fees\n"
            "   Reuters reports US imposing transit fees.\n\n"
            "2. Tehran condemns\n"
            "   https://tasnim.example/2026/04/30/tehran-condemns\n"
            "   Tasnim covers the Iranian response."
        ),
        "Détroit d'Ormuz frais de transit": (
            "1. La France réagit\n"
            "   https://lemonde.example/2026/04/30/strait-fees-france\n"
            "   Le Monde sur les frais.\n\n"
            "2. Strait fees imposed\n"
            "   https://reuters.example/2026/04/30/strait-fees\n"
            "   The Reuters report."  # Dup URL → dedup
        ),
    }
    fake_tool = FakeWebSearchTool(canned)
    stage = make_researcher_search(fake_tool)

    tb = TopicBus()
    tb.researcher_plan_queries = [
        {"query": "Strait of Hormuz transit fees", "language": "en"},
        {"query": "Détroit d'Ormuz frais de transit", "language": "fr"},
    ]
    tb_after = _run(stage, tb, _ro())

    results = tb_after.researcher_search_results
    assert len(results) == 2
    # Tool was called for each query
    assert len(fake_tool.calls) == 2
    # url_dates attached
    assert any("url_dates" in r for r in results)
    en_result = next(r for r in results if r["language"] == "en")
    assert en_result["url_dates"][0]["estimated_date"] == "2026-04-30"


def test_researcher_search_handles_query_failure():
    """One query fails; the rest succeed; failure logged as Error: ..."""
    canned = {"good query": "1. Title\n   https://x.example/1\n   snippet"}
    fake_tool = FakeWebSearchTool(canned, fail_query="bad query")
    stage = make_researcher_search(fake_tool)

    tb = TopicBus()
    tb.researcher_plan_queries = [
        {"query": "good query", "language": "en"},
        {"query": "bad query", "language": "fr"},
    ]
    tb_after = _run(stage, tb, _ro())
    results = tb_after.researcher_search_results
    assert len(results) == 2
    error_entry = next(r for r in results if r["language"] == "fr")
    assert error_entry["results"].startswith("Error:")


def test_researcher_search_no_queries_is_no_op():
    fake_tool = FakeWebSearchTool({})
    stage = make_researcher_search(fake_tool)
    tb = TopicBus()
    tb.researcher_plan_queries = []
    tb_after = _run(stage, tb, _ro())
    # No tool calls; bus unchanged
    assert fake_tool.calls == []
    assert tb_after.researcher_search_results == []


def test_researcher_search_skips_empty_query_strings():
    fake_tool = FakeWebSearchTool({"good": "1. T\n   https://x.example/1\n   s"})
    stage = make_researcher_search(fake_tool)
    tb = TopicBus()
    tb.researcher_plan_queries = [
        {"query": "", "language": "en"},  # skipped
        {"query": "good", "language": "en"},
    ]
    tb_after = _run(stage, tb, _ro())
    assert fake_tool.calls == ["good"]
    assert len(tb_after.researcher_search_results) == 1


# ---------------------------------------------------------------------------
# prune_unused_sources_and_clusters
# ---------------------------------------------------------------------------


def test_prune_drops_unreferenced_sources_regardless_of_content():
    """Strict rule: a source is dropped iff its id is not referenced
    downstream. Content (summary, actors_quoted) is no longer a
    keep-reprieve — if the synthesis stack didn't use the source, it's
    off-topic and drops out."""
    tb = TopicBus()
    tb.final_sources = [
        # Referenced via cluster — kept.
        {"id": "src-001", "outlet": "Cited", "summary": "x", "actors_quoted": []},
        # Dead-weight: empty content, unreferenced — dropped (still).
        {"id": "src-023", "outlet": "Dead", "summary": "", "actors_quoted": []},
        # Unreferenced but content-bearing — under the strict rule, dropped.
        {"id": "src-099", "outlet": "Off-topic", "summary": "useful background",
         "actors_quoted": [{"name": "A"}]},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "P1", "actors": ["A"], "source_ids": ["src-001"]},
    ]

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    kept_ids = {s["id"] for s in tb_after.final_sources}
    assert kept_ids == {"src-001"}, (
        f"strict rule: only referenced sources kept; got {kept_ids}"
    )


def test_prune_keeps_source_referenced_only_in_article_body():
    """A source cited inline in writer body via [src-NNN] is referenced
    even when no cluster mentions it — pruning must not strip it."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-007", "outlet": "X", "summary": "", "actors_quoted": []},
    ]
    tb.writer_article = WriterArticle(
        headline="h",
        subheadline="sh",
        body="A claim is supported [src-007] in the body.",
        summary="s",
    )
    tb.perspective_clusters_synced = []

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    assert {s["id"] for s in tb_after.final_sources} == {"src-007"}


def test_prune_drops_empty_cluster_and_keeps_populated_cluster():
    """A cluster with both actor_ids and source_ids empty is dropped; one
    populated by either dimension is kept."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "X", "summary": "x", "actors_quoted": [{"name": "A"}]},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "Has actors", "actor_ids": ["actor-001"], "source_ids": []},
        {"id": "pc-002", "position_label": "Has sources", "actor_ids": [], "source_ids": ["src-001"]},
        {"id": "pc-003", "position_label": "Empty", "actor_ids": [], "source_ids": []},
    ]

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    kept_cluster_ids = {c["id"] for c in tb_after.perspective_clusters_synced}
    assert kept_cluster_ids == {"pc-001", "pc-002"}, (
        f"expected pc-001 + pc-002 kept, pc-003 dropped; got {kept_cluster_ids}"
    )


def test_prune_is_noop_when_nothing_to_drop():
    """A bus where every source is referenced and every cluster carries
    actor_ids or source_ids passes through unchanged."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "X", "summary": "x", "actors_quoted": []},
        {"id": "src-002", "outlet": "Y", "summary": "", "actors_quoted": [{"name": "A"}]},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "P", "actor_ids": ["actor-001"],
         "source_ids": ["src-001", "src-002"]},
    ]

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    assert len(tb_after.final_sources) == 2
    assert len(tb_after.perspective_clusters_synced) == 1
    # Drop-staging slots are present-but-empty when nothing was dropped.
    assert tb_after.prune_dropped_sources == []
    assert tb_after.prune_dropped_clusters == []


def test_prune_records_dropped_sources_and_clusters():
    """When prune drops anything, the staging slots
    (prune_dropped_sources / prune_dropped_clusters) carry one entry per
    drop with the fields needed by the renderer (id + outlet + summary
    snippet for sources; id + position_label for clusters)."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "Reuters", "summary": "kept", "actors_quoted": []},
        {
            "id": "src-007",
            "outlet": "Off-topic Daily",
            "summary": "An unrelated story not cited anywhere downstream.",
            "actors_quoted": [],
        },
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "Kept position",
         "actors": ["A"], "source_ids": ["src-001"]},
        # Empty cluster — strict-drop removes it.
        {"id": "pc-002", "position_label": "Dropped position",
         "actors": [], "source_ids": []},
    ]

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    # Source-side drops.
    assert len(tb_after.prune_dropped_sources) == 1
    drop = tb_after.prune_dropped_sources[0]
    assert drop["id"] == "src-007"
    assert drop["outlet"] == "Off-topic Daily"
    assert drop["summary"].startswith("An unrelated story not cited")
    # Truncated to the same 60-char window the logger uses.
    assert len(drop["summary"]) <= 60

    # Cluster-side drops.
    assert len(tb_after.prune_dropped_clusters) == 1
    cdrop = tb_after.prune_dropped_clusters[0]
    assert cdrop["id"] == "pc-002"
    assert cdrop["position_label"] == "Dropped position"


def test_compose_transparency_card_propagates_dropped_lists():
    """compose_transparency_card reads prune_dropped_sources /
    prune_dropped_clusters and forwards them onto the rendered
    TransparencyCard."""
    tb = TopicBus(editor_selected_topic=EditorAssignment(selection_reason="x"))
    tb.writer_article = WriterArticle(headline="H", body="B")
    tb.prune_dropped_sources = [
        {"id": "src-007", "outlet": "Off-topic Daily", "summary": "..."}
    ]
    tb.prune_dropped_clusters = [
        {"id": "pc-002", "position_label": "Dropped position"}
    ]

    tb_after = _run(compose_transparency_card, tb, _ro())
    card = tb_after.transparency_card
    assert card.dropped_sources == [
        {"id": "src-007", "outlet": "Off-topic Daily", "summary": "..."}
    ]
    assert card.dropped_clusters == [
        {"id": "pc-002", "position_label": "Dropped position"}
    ]


def test_compose_transparency_card_dropped_lists_default_empty():
    """No drops staged → TransparencyCard.dropped_sources and
    dropped_clusters are present-but-empty (not omitted, not None)."""
    tb = TopicBus(editor_selected_topic=EditorAssignment(selection_reason="x"))
    tb.writer_article = WriterArticle(headline="H", body="B")
    # prune_dropped_* default to []; do not populate.

    tb_after = _run(compose_transparency_card, tb, _ro())
    assert tb_after.transparency_card.dropped_sources == []
    assert tb_after.transparency_card.dropped_clusters == []


def test_prune_picks_up_qa_divergence_source_ids():
    """A source referenced only via a QA divergence (post-fix output)
    must be kept."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-005", "outlet": "Z", "summary": "", "actors_quoted": []},
    ]
    tb.qa_divergences = [
        {
            "type": "factual",
            "description": "casualty figure conflict",
            "source_ids": ["src-005"],
            "resolution": "unresolved",
            "resolution_note": "n",
        }
    ]
    tb.perspective_clusters_synced = []

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    assert {s["id"] for s in tb_after.final_sources} == {"src-005"}


def test_prune_drops_unreferenced_source_with_full_content():
    """Strict-rule regression guard: a source carrying both summary and
    actors_quoted but whose id never appears downstream is dropped."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "Cited", "summary": "x",
         "actors_quoted": [{"name": "Cited Speaker"}]},
        {"id": "src-042", "outlet": "Off-topic Anadolu",
         "summary": "Anadolu reports unrelated regional news in 240 chars of text.",
         "actors_quoted": [{"name": "An Anadolu reporter"}, {"name": "A second voice"}]},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "P", "actors": ["A"],
         "source_ids": ["src-001"]},
    ]

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    assert {s["id"] for s in tb_after.final_sources} == {"src-001"}, (
        "src-042 has content but no reference site — must be dropped"
    )


def test_prune_keeps_source_referenced_only_in_bias_findings():
    """A source's id appearing inside a bias_language_finding's
    excerpt/issue/explanation prose must be treated as referenced."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-031", "outlet": "X", "summary": "", "actors_quoted": []},
    ]
    tb.bias_language_findings = [
        {
            "excerpt": "controversial move",
            "issue": "loaded_term",
            "explanation": "framing flagged in [src-031]; see source for full quote.",
        }
    ]

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    assert {s["id"] for s in tb_after.final_sources} == {"src-031"}


def test_prune_keeps_source_referenced_only_in_coverage_gaps():
    """A source whose id appears only in a coverage_gaps_validated entry
    is referenced and must be kept."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-050", "outlet": "Y", "summary": "", "actors_quoted": []},
    ]
    tb.coverage_gaps_validated = [
        "Iranian state media not represented; only [src-050] partially covers the angle.",
    ]

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    assert {s["id"] for s in tb_after.final_sources} == {"src-050"}


def test_prune_keeps_source_referenced_only_in_writer_body_when_qa_article_is_empty():
    """Defence-in-depth: when qa_corrected_article body is empty (no QA
    fixes), the validator must still find references in writer_article.body."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-077", "outlet": "Z", "summary": "", "actors_quoted": []},
    ]
    tb.writer_article = WriterArticle(
        headline="h", subheadline="sh",
        body="A claim is supported [src-077] in the writer body.",
        summary="s",
    )
    # qa_corrected_article left at empty default — simulates the clean-run
    # path before mirror_qa_corrected fills the slot.
    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    assert {s["id"] for s in tb_after.final_sources} == {"src-077"}
