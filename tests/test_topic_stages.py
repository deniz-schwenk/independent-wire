"""Tests for src/stages/topic_stages.py and the select_topics run-stage.

One happy-path test per stage plus key edge cases per V1 contract.
Property-style tests for the source-id renumbering invariant.
"""

from __future__ import annotations

import asyncio
import re

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
    cleanup_stale_references,
    compose_transparency_card,
    compute_source_balance,
    consolidate_missing_coverage,
    derive_single_voices,
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
        "canonical_actors_stated",
        "canonical_actors_reported",
        "canonical_actors_mentioned",
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
    cluster citing the source is gone. cluster.actor_ids is derived from
    the agent-classified sub-lists; regions and languages still derive
    from cited sources deterministically.
    """
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001", "src-002"],
            "stated": ["actor-001"],
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
            "stated": ["actor-001", "actor-002"],
        },
        {
            "position_label": "Med",
            "source_ids": ["src-004"],
            "stated": ["actor-003"],
        },
        {"position_label": "None", "source_ids": [], "stated": []},
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
# consolidate_missing_coverage — token-Jaccard dedup of voices vs gaps
# ---------------------------------------------------------------------------


def test_consolidate_drops_gap_matching_missing_position_description():
    """Missing-position description and gap text overlap above the
    Jaccard threshold → the gap is dropped from the consolidated
    `missing_topic_dimensions` (the structured missing-position wins).
    The two source slots persist unchanged as the audit trail."""
    tb = TopicBus()
    tb.perspective_missing_positions = [
        {
            "type": "industry",
            "description": (
                "oil traders, shipping companies, and insurance "
                "underwriters affected by Strait of Hormuz disruption"
            ),
        },
    ]
    tb.coverage_gaps_validated = [
        "oil traders, shipping companies, insurance underwriters",
        "European Union diplomatic response to the crisis",
    ]

    tb_after = _run(consolidate_missing_coverage, tb, _ro())
    consolidated = tb_after.consolidated_missing_coverage
    voices = consolidated["missing_stakeholder_voices"]
    dimensions = consolidated["missing_topic_dimensions"]

    # The structured missing-position survives intact.
    assert len(voices) == 1
    assert voices[0]["type"] == "industry"
    assert "oil traders" in voices[0]["description"]

    # The matching gap was dropped; the non-overlapping gap survives.
    assert len(dimensions) == 1
    assert "European Union" in dimensions[0]
    assert all("oil traders" not in g for g in dimensions)

    # Audit trail: source slots are unchanged.
    assert len(tb_after.perspective_missing_positions) == 1
    assert len(tb_after.coverage_gaps_validated) == 2


def test_consolidate_keeps_non_overlapping_gap():
    """A gap whose tokens do not exceed the Jaccard threshold against
    any missing_position description survives into
    `missing_topic_dimensions`."""
    tb = TopicBus()
    tb.perspective_missing_positions = [
        {
            "type": "civil_society",
            "description": (
                "Iranian civil-society organisations and student "
                "groups responding to the crisis"
            ),
        },
    ]
    tb.coverage_gaps_validated = [
        "European Union diplomatic response to the crisis",
    ]

    tb_after = _run(consolidate_missing_coverage, tb, _ro())
    consolidated = tb_after.consolidated_missing_coverage

    # Voice survives (no input dropped).
    assert len(consolidated["missing_stakeholder_voices"]) == 1
    # Non-overlapping gap is preserved in the dimensions axis.
    assert consolidated["missing_topic_dimensions"] == [
        "European Union diplomatic response to the crisis",
    ]


def test_consolidate_empty_inputs_yield_empty_view():
    tb = TopicBus()
    tb.perspective_missing_positions = []
    tb.coverage_gaps_validated = []
    tb_after = _run(consolidate_missing_coverage, tb, _ro())
    consolidated = tb_after.consolidated_missing_coverage
    assert consolidated == {
        "missing_stakeholder_voices": [],
        "missing_topic_dimensions": [],
    }


# ---------------------------------------------------------------------------
# derive_single_voices — deterministic bracket for orphan protagonists
# ---------------------------------------------------------------------------


def test_single_voices_orphan_with_two_sources_qualifies_stated_tier():
    """Acceptance criterion: a single orphan actor (≥ 2 sources) with at
    least one verbatim quote lands in the bracket's `actors_stated`
    sub-list. Region/language counts are derived from the matching
    `final_sources[]` entries."""
    tb = TopicBus()
    tb.canonical_actors = [
        {
            "id": "actor-001",
            "name": "DR Congo Health Minister",
            "role": "Health Minister",
            "type": "government",
            "source_ids": ["src-001", "src-002"],
            "quotes": [
                {"source_id": "src-001",
                 "position": "Declared a national outbreak.",
                 "verbatim": "We are mobilising every district hospital."},
                {"source_id": "src-002",
                 "position": "Outlined containment plan.",
                 "verbatim": None},
            ],
        },
    ]
    tb.perspective_clusters_synced = []  # actor-001 in no cluster → orphan
    tb.final_sources = [
        {"id": "src-001", "country": "Democratic Republic of the Congo",
         "language": "fr"},
        {"id": "src-002", "country": "United States", "language": "en"},
    ]
    tb_after = _run(derive_single_voices, tb, _ro())
    sv = tb_after.single_voices

    assert sv["position_label"] == "Single voices"
    assert "unique positions" in sv["summary"]
    assert sv["actors_stated"] == ["actor-001"]
    assert sv["actors_reported"] == []
    assert sv["actors_mentioned"] == []
    assert sv["actor_ids"] == ["actor-001"]
    assert sv["source_ids"] == ["src-001", "src-002"]
    assert sv["counts"] == {
        "actors": 1,
        "sources": 2,
        "regions": 2,   # DR Congo + United States
        "languages": 2, # fr + en
    }


def test_single_voices_orphan_with_one_source_excluded():
    """Acceptance criterion: an orphan whose source set has size 1
    stays out of the bracket — single-source actors are tangential
    mentions, not structurally central. The bracket renders with empty
    `actor_ids[]` (which the renderer treats as "section omitted")."""
    tb = TopicBus()
    tb.canonical_actors = [
        {
            "id": "actor-001",
            "name": "Tangential Witness",
            "role": "Bystander",
            "type": "individual",
            "source_ids": ["src-005"],
            "quotes": [
                {"source_id": "src-005",
                 "position": "Said something brief.",
                 "verbatim": None},
            ],
        },
    ]
    tb.perspective_clusters_synced = []
    tb.final_sources = [
        {"id": "src-005", "country": "France", "language": "fr"},
    ]
    tb_after = _run(derive_single_voices, tb, _ro())
    sv = tb_after.single_voices
    assert sv["actor_ids"] == []
    assert sv["actors_stated"] == []
    assert sv["actors_reported"] == []
    assert sv["actors_mentioned"] == []
    assert sv["counts"]["actors"] == 0


def test_single_voices_three_orphans_at_different_tiers():
    """Acceptance criterion: three qualifying orphans land in their
    respective tier sub-lists per the verbatim/position derivation
    rule. Tier rule:
      - any quote with non-empty `verbatim` → stated
      - else any quote with non-empty `position` → reported
      - else → mentioned
    """
    tb = TopicBus()
    tb.canonical_actors = [
        {
            "id": "actor-001",
            "name": "Has Verbatim",
            "role": "r",
            "type": "government",
            "source_ids": ["src-001", "src-002"],
            "quotes": [
                {"source_id": "src-001", "position": "p",
                 "verbatim": "v"},
            ],
        },
        {
            "id": "actor-002",
            "name": "Paraphrase Only",
            "role": "r",
            "type": "government",
            "source_ids": ["src-001", "src-003"],
            "quotes": [
                {"source_id": "src-001", "position": "paraphrased",
                 "verbatim": None},
                {"source_id": "src-003", "position": "more paraphrase",
                 "verbatim": ""},
            ],
        },
        {
            "id": "actor-003",
            "name": "Named Only",
            "role": "r",
            "type": "government",
            "source_ids": ["src-002", "src-003"],
            "quotes": [
                {"source_id": "src-002", "position": "", "verbatim": None},
                {"source_id": "src-003", "position": None, "verbatim": ""},
            ],
        },
    ]
    tb.perspective_clusters_synced = []
    tb.final_sources = [
        {"id": "src-001", "country": "X", "language": "en"},
        {"id": "src-002", "country": "Y", "language": "en"},
        {"id": "src-003", "country": "Z", "language": "fr"},
    ]
    tb_after = _run(derive_single_voices, tb, _ro())
    sv = tb_after.single_voices
    assert sv["actors_stated"] == ["actor-001"]
    assert sv["actors_reported"] == ["actor-002"]
    assert sv["actors_mentioned"] == ["actor-003"]
    # actor_ids flat union ordered stated → reported → mentioned.
    assert sv["actor_ids"] == ["actor-001", "actor-002", "actor-003"]
    assert sv["counts"]["actors"] == 3
    assert sv["counts"]["regions"] == 3
    assert sv["counts"]["languages"] == 2


def test_single_voices_actor_in_cluster_is_not_orphan():
    """An actor present in any cluster's `actor_ids[]` is not an orphan
    and must not appear in the bracket, even when their source set has
    size ≥ 2."""
    tb = TopicBus()
    tb.canonical_actors = [
        {"id": "actor-001", "name": "Clustered", "role": "r", "type": "t",
         "source_ids": ["src-001", "src-002"], "quotes": []},
        {"id": "actor-002", "name": "Orphan", "role": "r", "type": "t",
         "source_ids": ["src-001", "src-002"], "quotes": []},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
    ]
    tb.final_sources = []
    tb_after = _run(derive_single_voices, tb, _ro())
    sv = tb_after.single_voices
    assert "actor-001" not in sv["actor_ids"]
    assert sv["actor_ids"] == ["actor-002"]


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


def test_assemble_hydration_dossier_threads_evidence_type():
    """Regression: evidence_type from Hydration-Phase-1's actors_quoted
    must be threaded through onto the rebuilt source's actors_quoted
    entry, otherwise the downstream partition stage receives all-None
    evidence_types and defaults every actor to the `reported` pool."""
    tb = TopicBus()
    tb.hydration_fetch_results = [
        {"url": "x", "status": "success", "outlet": "X"},
    ]
    tb.hydration_phase1_analyses = [
        {
            "article_index": 0,
            "summary": "X summary",
            "actors_quoted": [
                {
                    "name": "Alice",
                    "role": "PM",
                    "type": "government",
                    "position": "stated_pos",
                    "evidence_type": "stated",
                    "verbatim_quote": None,
                },
                {
                    "name": "Bob",
                    "role": "Minister",
                    "type": "government",
                    "position": "reported_pos",
                    "evidence_type": "reported",
                    "verbatim_quote": None,
                },
                {
                    "name": "Carol",
                    "role": "Analyst",
                    "type": "academia",
                    "position": "mentioned_pos",
                    "evidence_type": "mentioned",
                    "verbatim_quote": None,
                },
            ],
        },
    ]
    tb.hydration_phase2_corpus = HydrationPhase2Corpus()
    tb_after = _run(assemble_hydration_dossier, tb, _ro())
    aq = tb_after.hydration_pre_dossier.sources[0]["actors_quoted"]
    et_by_name = {a["name"]: a.get("evidence_type") for a in aq}
    assert et_by_name == {
        "Alice": "stated",
        "Bob": "reported",
        "Carol": "mentioned",
    }


def test_assemble_hydration_dossier_normalises_unknown_evidence_type_to_none():
    """An unexpected evidence_type value (model deviation from the
    enum) is normalised to None rather than propagated, so the
    partition stage's default-to-reported policy handles it cleanly."""
    tb = TopicBus()
    tb.hydration_fetch_results = [
        {"url": "x", "status": "success", "outlet": "X"},
    ]
    tb.hydration_phase1_analyses = [
        {
            "article_index": 0,
            "summary": "X",
            "actors_quoted": [
                {
                    "name": "Alice",
                    "role": "PM",
                    "type": "government",
                    "position": "p",
                    "evidence_type": "speculated",  # out-of-enum
                    "verbatim_quote": None,
                },
            ],
        },
    ]
    tb.hydration_phase2_corpus = HydrationPhase2Corpus()
    tb_after = _run(assemble_hydration_dossier, tb, _ro())
    aq = tb_after.hydration_pre_dossier.sources[0]["actors_quoted"]
    assert aq[0]["evidence_type"] is None


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


def test_prune_drops_source_referenced_only_in_bias_findings():
    """Post-reorder, bias_language_findings is no longer scanned by
    prune (the bias agent produces secondary commentary, not
    source-authority; see ``_collect_referenced_src_ids`` docstring).
    A source cited only in a bias finding's prose drops, even when an
    inline ``[src-NNN]`` marker is present. The contract test
    ``test_bias_and_gaps_emit_no_inline_src_markers`` ensures the bias
    agent doesn't actually emit such markers."""
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

    assert tb_after.final_sources == []
    assert tb_after.prune_dropped_sources[0]["id"] == "src-031"


def test_prune_drops_source_referenced_only_in_coverage_gaps():
    """Post-reorder, coverage_gaps_validated is no longer scanned by
    prune (descriptive commentary, not source-authority). A source
    cited only in a gap description drops."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-050", "outlet": "Y", "summary": "", "actors_quoted": []},
    ]
    tb.coverage_gaps_validated = [
        "Iranian state media not represented; only [src-050] partially covers the angle.",
    ]

    tb_after = _run(prune_unused_sources_and_clusters, tb, _ro())

    assert tb_after.final_sources == []
    assert tb_after.prune_dropped_sources[0]["id"] == "src-050"


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


# ---------------------------------------------------------------------------
# cleanup_stale_references
# ---------------------------------------------------------------------------


def _cleanup_fixture_topic_bus() -> TopicBus:
    """Build a TopicBus with 3 surviving sources and a mix of valid +
    stale source-id references across every slot cleanup_stale_references
    touches. Used by multiple tests below."""
    tb = TopicBus()
    # Three surviving sources after prune.
    tb.final_sources = [
        {"id": "src-001", "outlet": "BBC"},
        {"id": "src-002", "outlet": "Reuters"},
        {"id": "src-003", "outlet": "Al Jazeera"},
    ]
    # Actors:
    # - actor-001 cites only valid sources → survives.
    # - actor-002 cites a mix; surviving quotes are stated + reported.
    # - actor-003 cites only stale sources → dropped entirely.
    tb.canonical_actors = [
        {
            "id": "actor-001", "name": "Alice", "role": "diplomat", "type": "person",
            "source_ids": ["src-001"],
            "quotes": [
                {"source_id": "src-001", "verbatim": "...", "position": "p",
                 "evidence_type": "stated"},
            ],
        },
        {
            "id": "actor-002", "name": "Bob", "role": "analyst", "type": "person",
            "source_ids": ["src-002", "src-999", "src-003"],
            "quotes": [
                {"source_id": "src-002", "verbatim": "x", "position": "p",
                 "evidence_type": "stated"},
                {"source_id": "src-999", "verbatim": "stale", "position": "p",
                 "evidence_type": "mentioned"},
                {"source_id": "src-003", "verbatim": "y", "position": "p",
                 "evidence_type": "reported"},
            ],
        },
        {
            "id": "actor-003", "name": "Carol", "role": "minister", "type": "person",
            "source_ids": ["src-998", "src-997"],
            "quotes": [
                {"source_id": "src-998", "verbatim": "z", "position": "p",
                 "evidence_type": "stated"},
            ],
        },
    ]
    # Three partitioned pools mirroring partition_canonical_actors_by_evidence.
    tb.canonical_actors_stated = [
        {"id": "actor-001", "name": "Alice", "source_ids": ["src-001"],
         "quotes": [{"source_id": "src-001", "evidence_type": "stated"}]},
        {"id": "actor-002", "name": "Bob", "source_ids": ["src-002"],
         "quotes": [{"source_id": "src-002", "evidence_type": "stated"}]},
        {"id": "actor-003", "name": "Carol", "source_ids": ["src-998"],
         "quotes": [{"source_id": "src-998", "evidence_type": "stated"}]},
    ]
    tb.canonical_actors_reported = [
        {"id": "actor-002", "name": "Bob", "source_ids": ["src-003"],
         "quotes": [{"source_id": "src-003", "evidence_type": "reported"}]},
    ]
    tb.canonical_actors_mentioned = [
        # actor-002 had a mentioned quote, but the source (src-999) is stale →
        # pool entry must drop because surviving filtered quotes no longer
        # carry the mentioned tier.
        {"id": "actor-002", "name": "Bob", "source_ids": ["src-999"],
         "quotes": [{"source_id": "src-999", "evidence_type": "mentioned"}]},
    ]
    # Alias mapping: actor-003 was the canonical for alias actor-099.
    # actor-003 drops → alias entry drops. actor-001 ↔ actor-088 stays.
    tb.actor_alias_mapping = [
        {"alias_id": "actor-088", "alias_name": "Alicia",
         "canonical_id": "actor-001"},
        {"alias_id": "actor-099", "alias_name": "Caroline",
         "canonical_id": "actor-003"},  # canonical dropped
    ]
    # Perspective clusters:
    # - pc-001: all valid → kept (actor-001 + 002).
    # - pc-002: only stale src → dropped.
    # - pc-003: mixed src + actor-003 (dropped) → kept but filtered.
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "L1", "position_summary": "s1",
         "source_ids": ["src-001", "src-002"],
         "actor_ids": ["actor-001", "actor-002"],
         "stated": ["actor-001", "actor-002"], "reported": [], "mentioned": []},
        {"id": "pc-002", "position_label": "L2", "position_summary": "s2",
         "source_ids": ["src-998", "src-999"],
         "actor_ids": ["actor-003"],
         "stated": ["actor-003"], "reported": [], "mentioned": []},
        {"id": "pc-003", "position_label": "L3", "position_summary": "s3",
         "source_ids": ["src-003", "src-999"],
         "actor_ids": ["actor-002", "actor-003"],
         "stated": ["actor-003"], "reported": ["actor-002"], "mentioned": []},
    ]
    # Divergences and gaps.
    tb.merged_preliminary_divergences = [
        {"id": "div-001", "topic": "T1", "source_ids": ["src-001", "src-002"]},
        {"id": "div-002", "topic": "T2", "source_ids": ["src-998"]},  # all stale → drop
    ]
    tb.merged_coverage_gaps = [
        {"description": "g1", "source_ids": ["src-003"]},
        {"description": "g2", "source_ids": ["src-997"]},  # stale → drop
    ]
    tb.qa_divergences = [
        {"id": "qad-001", "claim": "c1", "source_ids": ["src-001", "src-997"]},
        {"id": "qad-002", "claim": "c2", "source_ids": ["src-996"]},  # stale → drop
    ]
    return tb


def test_cleanup_stale_references_filters_all_slots():
    """End-to-end filter: actors, alias mapping, clusters, divergences,
    gaps, and qa_divergences all get filtered against cited_src_ids."""
    tb = _cleanup_fixture_topic_bus()
    out = _run(cleanup_stale_references, tb, _ro())

    # canonical_actors: actor-003 dropped (all sources stale).
    assert [a["id"] for a in out.canonical_actors] == ["actor-001", "actor-002"]
    # actor-002 source_ids and quotes filtered to surviving sources.
    bob = [a for a in out.canonical_actors if a["id"] == "actor-002"][0]
    assert set(bob["source_ids"]) == {"src-002", "src-003"}
    assert {q["source_id"] for q in bob["quotes"]} == {"src-002", "src-003"}

    # perspective_clusters_synced: pc-002 dropped (all sources stale).
    cluster_ids = [c["id"] for c in out.perspective_clusters_synced]
    assert cluster_ids == ["pc-001", "pc-003"]
    pc003 = [c for c in out.perspective_clusters_synced if c["id"] == "pc-003"][0]
    assert pc003["source_ids"] == ["src-003"]
    # actor-003 dropped from cluster actor_ids and from the stated sub-list.
    assert pc003["actor_ids"] == ["actor-002"]
    assert pc003["stated"] == []
    assert pc003["reported"] == ["actor-002"]

    # divergences/gaps: stale-only entries dropped; mixed entries filtered.
    assert [d["id"] for d in out.merged_preliminary_divergences] == ["div-001"]
    assert [g["description"] for g in out.merged_coverage_gaps] == ["g1"]
    qad = out.qa_divergences
    assert [q["id"] for q in qad] == ["qad-001"]
    assert qad[0]["source_ids"] == ["src-001"]  # src-997 filtered out


def test_cleanup_alias_mapping_drops_when_canonical_dropped():
    """An alias whose canonical_id points at a dropped actor must be
    removed from actor_alias_mapping."""
    tb = _cleanup_fixture_topic_bus()
    out = _run(cleanup_stale_references, tb, _ro())

    canonical_ids = {e["canonical_id"] for e in out.actor_alias_mapping}
    assert "actor-003" not in canonical_ids, "alias pointing at dropped canonical survived"
    # The surviving alias (actor-088 → actor-001) is kept.
    assert any(
        e["canonical_id"] == "actor-001" for e in out.actor_alias_mapping
    )
    assert len(out.actor_alias_mapping) == 1


def test_cleanup_pools_drop_when_actor_dropped_and_when_tier_no_longer_present():
    """An actor dropped from canonical_actors must be absent from all
    three pools. An actor surviving canonical_actors but with no
    quotes left in a given tier must be absent from that tier's pool."""
    tb = _cleanup_fixture_topic_bus()
    out = _run(cleanup_stale_references, tb, _ro())

    # actor-003 dropped from canonical_actors → absent from every pool.
    for pool_attr in (
        "canonical_actors_stated",
        "canonical_actors_reported",
        "canonical_actors_mentioned",
    ):
        pool = getattr(out, pool_attr)
        assert all(a.get("id") != "actor-003" for a in pool), (
            f"dropped actor-003 still present in {pool_attr}"
        )

    # actor-002 had one mentioned quote on src-999 (stale) → after
    # cleanup, no mentioned quotes survive, so the pool entry drops.
    assert all(a.get("id") != "actor-002" for a in out.canonical_actors_mentioned)
    # actor-002 still has stated + reported tiers in its surviving
    # quotes, so its entries in those pools are kept.
    assert any(a.get("id") == "actor-002" for a in out.canonical_actors_stated)
    assert any(a.get("id") == "actor-002" for a in out.canonical_actors_reported)


def test_cleanup_no_op_when_no_stale_refs():
    """Empty input slots and zero stale references → no drops, no crash."""
    tb = TopicBus()
    tb.final_sources = [{"id": "src-001", "outlet": "X"}]
    tb.canonical_actors = [
        {
            "id": "actor-001", "name": "A", "role": "", "type": "",
            "source_ids": ["src-001"],
            "quotes": [{"source_id": "src-001", "verbatim": "",
                        "position": "", "evidence_type": "stated"}],
        },
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "source_ids": ["src-001"], "actor_ids": ["actor-001"],
         "stated": ["actor-001"], "reported": [], "mentioned": []},
    ]
    # All other slots left as empty defaults.
    out = _run(cleanup_stale_references, tb, _ro())

    assert len(out.canonical_actors) == 1
    assert len(out.perspective_clusters_synced) == 1
    assert out.actor_alias_mapping == []
    assert out.merged_preliminary_divergences == []
    assert out.merged_coverage_gaps == []
    assert out.qa_divergences == []


def test_cleanup_after_prune_smoke_state_has_zero_stale_actor_refs():
    """Smoke: drive prune + cleanup over the V2 2026-05-11 TP-001
    pre-prune state and assert the rendered TP would have zero actors
    with stale source_ids. Uses the existing baseline state on disk."""
    import json as _json
    from pathlib import Path as _Path
    bus_path = _Path(
        "output/2026-05-11/_state/run-2026-05-11-722571ae/"
        "topic_buses.BiasLanguageStage.0.json"
    )
    if not bus_path.exists():
        pytest.skip("baseline state file not present")
    state = _json.loads(bus_path.read_text(encoding="utf-8"))

    tb = TopicBus.model_validate(state)
    tb_pruned = _run(prune_unused_sources_and_clusters, tb, _ro())
    tb_clean = _run(cleanup_stale_references, tb_pruned, _ro())

    cited_src_ids = {
        s["id"] for s in tb_clean.final_sources
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }

    # Zero actors with stale source_ids after cleanup.
    stale_actors = [
        a for a in tb_clean.canonical_actors
        if isinstance(a, dict)
        and not (set(a.get("source_ids") or []) <= cited_src_ids)
    ]
    assert stale_actors == [], (
        f"{len(stale_actors)} actor(s) still have stale source_ids after cleanup"
    )

    # Sanity: actor count should be much lower than 100 (V2 baseline
    # has 100 actors pre-cleanup; expected ≤ 20 by the task brief).
    assert len(tb_clean.canonical_actors) <= 30, (
        f"unexpected actor count {len(tb_clean.canonical_actors)} after cleanup"
    )


# ---------------------------------------------------------------------------
# Contract: bias findings and gap entries do not emit inline [src-NNN] markers
# ---------------------------------------------------------------------------


_INLINE_SRC_RE = re.compile(r"\[src-\d+\]")


def _scan_for_src_markers(items: list, fields: tuple[str, ...]) -> list[str]:
    """Return any inline [src-NNN] tokens found in the named fields of
    a list of dicts (and in any plain-string entries)."""
    hits: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            hits.extend(_INLINE_SRC_RE.findall(item))
        elif isinstance(item, dict):
            for field in fields:
                v = item.get(field)
                if isinstance(v, str):
                    hits.extend(_INLINE_SRC_RE.findall(v))
    return hits


def test_bias_and_gaps_emit_no_inline_src_markers():
    """Contract test: the bias agent and coverage-gap validator produce
    secondary commentary, not source-authority. Their prose must never
    carry inline ``[src-NNN]`` markers. Verified against the
    V2 2026-05-11 TP-001 baseline state. If a future prompt change
    reintroduces such markers, this fails loudly — at which point
    either roll back the prompt change, or consciously restore the
    bias/gaps citation harvest in ``_collect_referenced_src_ids``."""
    import json as _json
    from pathlib import Path as _Path
    bus_path = _Path(
        "output/2026-05-11/_state/run-2026-05-11-722571ae/"
        "topic_buses.BiasLanguageStage.0.json"
    )
    if not bus_path.exists():
        pytest.skip("baseline state file not present")
    bus = _json.loads(bus_path.read_text(encoding="utf-8"))

    bias_hits = _scan_for_src_markers(
        bus.get("bias_language_findings") or [],
        ("excerpt", "issue", "explanation"),
    )
    gaps_hits = _scan_for_src_markers(
        bus.get("coverage_gaps_validated") or [],
        ("description", "explanation", "gap"),
    )

    assert bias_hits == [], (
        f"bias_language_findings carry inline [src-NNN] markers: {bias_hits}. "
        "Prompt change has reintroduced source-authority commentary; either "
        "roll back the prompt or restore the harvest in "
        "_collect_referenced_src_ids and revisit the prune-reorder design."
    )
    assert gaps_hits == [], (
        f"coverage_gaps_validated carry inline [src-NNN] markers: {gaps_hits}. "
        "See bias-marker assertion message above."
    )


def test_bias_and_gaps_contract_test_fails_on_positive_case():
    """Adversarial check: synthesise a bus state where bias_language_findings
    DOES carry an inline ``[src-NNN]`` marker and assert the scan flags it.
    Codifies that the contract test above isn't trivially-passing on
    empty data."""
    synthetic_bias = [
        {"excerpt": "..", "issue": "loaded_term",
         "explanation": "framing flagged in [src-031]; see source."},
    ]
    synthetic_gaps = [
        "No Hezbollah voice; [src-099] partially covers the angle.",
    ]
    bias_hits = _scan_for_src_markers(
        synthetic_bias, ("excerpt", "issue", "explanation")
    )
    gaps_hits = _scan_for_src_markers(
        synthetic_gaps, ("description", "explanation", "gap")
    )
    assert bias_hits == ["[src-031]"]
    assert gaps_hits == ["[src-099]"]
