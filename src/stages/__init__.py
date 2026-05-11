"""V2 pipeline stages — deterministic stages and the mirror_stage helper.

Run-scoped stages live in `run_stages`; topic-scoped stages will live in
`topic_stages` (TASK-V2-03b). The generic `mirror_stage` helper consumes the
`mirrors_from` schema metadata declared in `src/bus.py` and is reused by the
topic-level mirror stages.
"""

from src.stages.run_stages import (
    MirrorMismatchError,
    RunInitConfig,
    attach_hydration_urls_to_assignments,
    fetch_findings,
    finalize_run,
    init_run,
    make_attach_hydration_urls_to_assignments,
    make_fetch_findings,
    make_finalize_run,
    make_init_run,
    make_topic_bus,
    mirror_stage,
    select_topics,
)
from src.stages.topic_stages import (
    assemble_hydration_dossier,
    attach_hydration_urls,
    compose_transparency_card,
    compute_source_balance,
    consolidate_actors,
    enrich_perspective_clusters,
    filter_media_actors_quoted,
    hydration_fetch,
    make_hydration_fetch,
    make_researcher_search,
    merge_sources,
    mirror_perspective_synced,
    mirror_qa_corrected,
    normalize_pre_research,
    partition_canonical_actors_by_evidence,
    propagate_outlet_metadata,
    prune_unused_sources_and_clusters,
    renumber_sources,
    validate_coverage_gaps_stage,
)

__all__ = [
    "MirrorMismatchError",
    "RunInitConfig",
    "assemble_hydration_dossier",
    "attach_hydration_urls",
    "attach_hydration_urls_to_assignments",
    "compose_transparency_card",
    "compute_source_balance",
    "consolidate_actors",
    "enrich_perspective_clusters",
    "fetch_findings",
    "filter_media_actors_quoted",
    "finalize_run",
    "hydration_fetch",
    "init_run",
    "make_attach_hydration_urls_to_assignments",
    "make_fetch_findings",
    "make_finalize_run",
    "make_hydration_fetch",
    "make_init_run",
    "make_researcher_search",
    "make_topic_bus",
    "merge_sources",
    "mirror_perspective_synced",
    "mirror_qa_corrected",
    "mirror_stage",
    "normalize_pre_research",
    "partition_canonical_actors_by_evidence",
    "propagate_outlet_metadata",
    "prune_unused_sources_and_clusters",
    "renumber_sources",
    "select_topics",
    "validate_coverage_gaps_stage",
]
