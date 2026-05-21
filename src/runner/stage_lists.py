"""Stage-list builders for production and hydrated variants.

Both builders return ``(run_stages, topic_stages, post_run_stages)``
tuples ready to feed the :class:`PipelineRunner`. The lists match
``docs/ARCH-V2-BUS-SCHEMA.md`` §5.1 / §5.2 with the V2-06b post-patch
applied — `enrich_perspective_clusters` runs after `perspective`, and in
the hydrated variant `mirror_perspective_synced` runs **twice** (after
`enrich_perspective_clusters` as 1:1 copy, then after `perspective_sync`
as element-merge) so `qa_analyze` always reads a populated
`perspective_clusters_synced` slot.

The agent dict shape comes from ``scripts/run.py`` ``create_agents()`` /
``create_agents_hydrated()``. Tests inject fakes that satisfy the agent
interface used by each wrapper.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from src.agent_stages import (
    AssignClustersStage,
    BiasLanguageStage,
    CuratorTopicDiscoveryStage,
    EditorStage,
    HydrationPhase1Stage,
    HydrationPhase2Stage,
    PerspectiveStage,
    PerspectiveSyncStage,
    QaAnalyzeStage,
    ResearcherAssembleStage,
    ResearcherHydratedPlanStage,
    ResearcherPlanStage,
    ResolveActorAliasesStage,
    WriterStage,
)
from src.stages import (
    RunInitConfig,
    assemble_curator_topics,
    assemble_hydration_dossier,
    attach_hydration_urls,
    attach_hydration_urls_to_assignments,
    cleanup_stale_references,
    cluster_to_finding_assignments,
    compose_transparency_card,
    compute_source_balance,
    consolidate_actors,
    enrich_perspective_clusters,
    fetch_findings,
    filter_media_actors_quoted,
    gravitational_assign,
    init_run,
    make_attach_hydration_urls_to_assignments,
    make_hydration_fetch,
    make_init_run,
    make_researcher_search,
    merge_sources,
    mirror_perspective_synced,
    mirror_qa_corrected,
    consolidate_missing_coverage,
    derive_mentioned_actors,
    normalize_pre_research,
    partition_canonical_actors_by_evidence,
    pre_cluster_findings,
    propagate_outlet_metadata,
    prune_unused_sources_and_clusters,
    renumber_sources,
    select_topics,
    validate_coverage_gaps_stage,
)


def _wrap_researcher_search(web_search_tool: Any) -> Callable:
    if web_search_tool is None:
        return make_researcher_search(None)
    return make_researcher_search(web_search_tool)


def _init_run_for(
    variant: str,
    max_produce: Optional[int],
    output_dir: Optional[Any],
) -> Callable:
    """Build an init_run closure tuned to the requested variant + max_produce.

    Falls back to the module-level ``init_run`` (production defaults) when no
    overrides are needed, keeping equality-by-identity stable for tests that
    introspect the stage list without overrides.
    """
    if max_produce is None and variant == "production" and output_dir is None:
        return init_run
    cfg = RunInitConfig(run_variant=variant)
    if max_produce is not None:
        cfg = cfg.model_copy(update={"max_produce": max_produce})
    if output_dir is not None:
        cfg = cfg.model_copy(update={"output_dir": output_dir})
    return make_init_run(cfg)


def build_production_stages(
    agents: dict[str, Any],
    *,
    web_search_tool: Any = None,
    hydration_fetcher: Any = None,
    max_produce: Optional[int] = None,
    output_dir: Optional[Any] = None,
) -> tuple[list, list, list]:
    """Build the production variant's three stage lists.

    Returns ``(run_stages, topic_stages, post_run_stages)``.

    :param agents: Dict from ``scripts/run.py:create_agents()``. Required
        keys: ``curator_topic_discovery`` (new triple-stage Curator),
        ``editor``, ``researcher_plan``, ``researcher_assemble``,
        ``perspective``, ``writer``, ``qa_analyze``, ``bias_language``.
    :param web_search_tool: Tool injected into the researcher_search
        deterministic stage. Tests pass a fake; production passes the
        Brave-search tool.
    :param hydration_fetcher: Unused in production (no hydration). Kept
        for API symmetry.
    :param max_produce: Optional override for the ``max_produce`` RunBus
        slot. When provided, swaps the default ``init_run`` for a closure
        over ``RunInitConfig(max_produce=max_produce)``.
    :param output_dir: Optional override for the ``init_run`` config's
        ``output_dir`` (drives previous-coverage scanning).
    """
    # Triple-stage Curator architecture (docs/ADR-CURATOR-TRIPLE-STAGE.md):
    # the old single-pass CuratorStage and the passive
    # measure_cluster_coherence are both replaced by the four-stage
    # decomposition pre_cluster → topic-discovery → gravitational-assign
    # → assemble_curator_topics. The Editor's input slot
    # (curator_topics) shape is preserved — only the writer changes.
    run_stages = [
        _init_run_for("production", max_produce, output_dir),
        fetch_findings,
        pre_cluster_findings,
        CuratorTopicDiscoveryStage(agents["curator_topic_discovery"]),
        gravitational_assign,
        assemble_curator_topics,
        EditorStage(agents["editor"]),
        select_topics,
    ]

    topic_stages = [
        ResearcherPlanStage(agents["researcher_plan"]),
        _wrap_researcher_search(web_search_tool),
        ResearcherAssembleStage(agents["researcher_assemble"]),
        merge_sources,
        renumber_sources,
        filter_media_actors_quoted,
        propagate_outlet_metadata,
        consolidate_actors,
        ResolveActorAliasesStage(agents["resolve_actor_aliases"]),
        partition_canonical_actors_by_evidence,
        normalize_pre_research,
        PerspectiveStage(agents["perspective"]),
        enrich_perspective_clusters,
        mirror_perspective_synced,  # 1:1 copy because production has no perspective_sync
        WriterStage(agents["writer"]),
        QaAnalyzeStage(agents["qa_analyze"]),
        mirror_qa_corrected,
        prune_unused_sources_and_clusters,
        cleanup_stale_references,
        compute_source_balance,
        validate_coverage_gaps_stage,
        consolidate_missing_coverage,
        derive_mentioned_actors,
        BiasLanguageStage(agents["bias_language"]),
        compose_transparency_card,
    ]

    post_run_stages: list = []  # populated by the runner with RenderStage + FinalizeRunStage

    return run_stages, topic_stages, post_run_stages


def build_production_stages_llm_assignment(
    agents: dict[str, Any],
    *,
    web_search_tool: Any = None,
    hydration_fetcher: Any = None,
    max_produce: Optional[int] = None,
    output_dir: Optional[Any] = None,
) -> tuple[list, list, list]:
    """Opt-in evaluation variant: LLM-based cluster→topic assignment.

    Mirrors :func:`build_production_stages` exactly EXCEPT that the
    finding-level deterministic ``gravitational_assign`` is replaced by
    the two-stage LLM path:

        ``AssignClustersStage → cluster_to_finding_assignments``

    Used by ``scripts/smoke_cluster_llm_assignment.py`` to evaluate
    Hypothesis 2 of the cluster-level pivot (TASK-CLUSTER-LLM-
    ASSIGNMENT). **Not** installed in the default production stage list
    until / unless the architect picks Branch A in Phase 3 of that
    brief — the existing :func:`build_production_stages` and
    :func:`build_hydrated_stages` constructors remain unchanged so
    production behaviour is bit-identical to its pre-brief state.

    The agents dict must include the ``assign_clusters`` Agent (new
    registration in ``scripts/run.py``) in addition to the production
    agent set.
    """
    run_stages = [
        _init_run_for("production", max_produce, output_dir),
        fetch_findings,
        pre_cluster_findings,
        CuratorTopicDiscoveryStage(agents["curator_topic_discovery"]),
        AssignClustersStage(agents["assign_clusters"]),
        cluster_to_finding_assignments,
        assemble_curator_topics,
        EditorStage(agents["editor"]),
        select_topics,
    ]

    topic_stages = [
        ResearcherPlanStage(agents["researcher_plan"]),
        _wrap_researcher_search(web_search_tool),
        ResearcherAssembleStage(agents["researcher_assemble"]),
        merge_sources,
        renumber_sources,
        filter_media_actors_quoted,
        propagate_outlet_metadata,
        consolidate_actors,
        ResolveActorAliasesStage(agents["resolve_actor_aliases"]),
        partition_canonical_actors_by_evidence,
        normalize_pre_research,
        PerspectiveStage(agents["perspective"]),
        enrich_perspective_clusters,
        mirror_perspective_synced,
        WriterStage(agents["writer"]),
        QaAnalyzeStage(agents["qa_analyze"]),
        mirror_qa_corrected,
        prune_unused_sources_and_clusters,
        cleanup_stale_references,
        compute_source_balance,
        validate_coverage_gaps_stage,
        consolidate_missing_coverage,
        derive_mentioned_actors,
        BiasLanguageStage(agents["bias_language"]),
        compose_transparency_card,
    ]

    post_run_stages: list = []

    return run_stages, topic_stages, post_run_stages


def build_hydrated_stages(
    agents: dict[str, Any],
    *,
    web_search_tool: Any = None,
    hydration_fetcher: Any = None,
    max_produce: Optional[int] = None,
    output_dir: Optional[Any] = None,
) -> tuple[list, list, list]:
    """Build the hydrated variant's three stage lists.

    Returns ``(run_stages, topic_stages, post_run_stages)``.

    Differences from production (per ARCH §5.2 + V2-06b stage-order fix):

    - Topic-stages prepend ``attach_hydration_urls``, ``hydration_fetch``,
      ``HydrationPhase1Stage``, ``HydrationPhase2Stage``,
      ``assemble_hydration_dossier`` (5 hydration stages).
    - ``ResearcherHydratedPlanStage`` replaces ``ResearcherPlanStage``
      (gap-aware planner reads ``hydration_pre_dossier``).
    - ``PerspectiveSyncStage`` is inserted between ``mirror_qa_corrected``
      and ``compute_source_balance``.
    - ``mirror_perspective_synced`` appears **twice**: once after
      ``enrich_perspective_clusters`` (1:1 copy so ``qa_analyze`` reads a
      populated slot), once after ``perspective_sync`` (element-merge of
      cluster deltas).

    :param agents: Dict from ``scripts/run.py:create_agents_hydrated()``.
        Required keys add ``researcher_hydrated_plan``,
        ``hydration_aggregator_phase1``, ``hydration_aggregator_phase2``,
        ``perspective_sync`` to the production set.
    :param hydration_fetcher: Async ``(list[dict]) -> list[dict]`` fetcher
        injected into ``make_hydration_fetch``. Tests pass a fake;
        production defaults to ``src.hydration.hydrate_urls``.
    :param max_produce: See :func:`build_production_stages`.
    :param output_dir: See :func:`build_production_stages`.

    Hydrated variant runs an extra run-stage,
    ``attach_hydration_urls_to_assignments``, between EditorStage and
    select_topics. It walks the editor assignments, matches each to a
    Curator cluster by token overlap, and writes the cluster's URL list
    to ``assignment.raw_data['hydration_urls']`` so the topic-stage
    ``attach_hydration_urls`` can lift them to the TopicBus slot.
    """
    # Triple-stage Curator architecture, identical to production
    # (see docs/ADR-CURATOR-TRIPLE-STAGE.md). The hydrated variant
    # diverges from production only in the topic-stage chain.
    run_stages = [
        _init_run_for("hydrated", max_produce, output_dir),
        fetch_findings,
        pre_cluster_findings,
        CuratorTopicDiscoveryStage(agents["curator_topic_discovery"]),
        gravitational_assign,
        assemble_curator_topics,
        EditorStage(agents["editor"]),
        attach_hydration_urls_to_assignments,
        select_topics,
    ]

    topic_stages = [
        attach_hydration_urls,
        make_hydration_fetch(hydration_fetcher),
        HydrationPhase1Stage(agents["hydration_aggregator_phase1"]),
        HydrationPhase2Stage(agents["hydration_aggregator_phase2"]),
        assemble_hydration_dossier,
        ResearcherHydratedPlanStage(agents["researcher_hydrated_plan"]),
        _wrap_researcher_search(web_search_tool),
        ResearcherAssembleStage(agents["researcher_assemble"]),
        merge_sources,
        renumber_sources,
        filter_media_actors_quoted,
        propagate_outlet_metadata,
        consolidate_actors,
        ResolveActorAliasesStage(agents["resolve_actor_aliases"]),
        partition_canonical_actors_by_evidence,
        normalize_pre_research,
        PerspectiveStage(agents["perspective"]),
        enrich_perspective_clusters,
        mirror_perspective_synced,  # 1st: 1:1 copy after enrich (V2-06b stage-order fix)
        WriterStage(agents["writer"]),
        QaAnalyzeStage(agents["qa_analyze"]),
        mirror_qa_corrected,
        PerspectiveSyncStage(agents["perspective_sync"]),
        mirror_perspective_synced,  # 2nd: element-merge of perspective_sync deltas
        prune_unused_sources_and_clusters,
        cleanup_stale_references,
        compute_source_balance,
        validate_coverage_gaps_stage,
        consolidate_missing_coverage,
        derive_mentioned_actors,
        BiasLanguageStage(agents["bias_language"]),
        compose_transparency_card,
    ]

    post_run_stages: list = []

    return run_stages, topic_stages, post_run_stages


# ---------------------------------------------------------------------------
# Static stage-name lists (CLI-side validation; no agent instantiation)
# ---------------------------------------------------------------------------


_PRODUCTION_RUN_NAMES = (
    "init_run",
    "fetch_findings",
    "pre_cluster_findings",
    "CuratorTopicDiscoveryStage",
    "gravitational_assign",
    "assemble_curator_topics",
    "EditorStage",
    "select_topics",
)

_HYDRATED_RUN_NAMES = (
    "init_run",
    "fetch_findings",
    "pre_cluster_findings",
    "CuratorTopicDiscoveryStage",
    "gravitational_assign",
    "assemble_curator_topics",
    "EditorStage",
    "attach_hydration_urls_to_assignments",
    "select_topics",
)

_PRODUCTION_TOPIC_NAMES = (
    "ResearcherPlanStage",
    "researcher_search",
    "ResearcherAssembleStage",
    "merge_sources",
    "renumber_sources",
    "filter_media_actors_quoted",
    "propagate_outlet_metadata",
    "consolidate_actors",
    "ResolveActorAliasesStage",
    "partition_canonical_actors_by_evidence",
    "normalize_pre_research",
    "PerspectiveStage",
    "enrich_perspective_clusters",
    "mirror_perspective_synced",
    "WriterStage",
    "QaAnalyzeStage",
    "mirror_qa_corrected",
    "prune_unused_sources_and_clusters",
    "cleanup_stale_references",
    "compute_source_balance",
    "validate_coverage_gaps_stage",
    "consolidate_missing_coverage",
    "derive_mentioned_actors",
    "BiasLanguageStage",
    "compose_transparency_card",
)

_HYDRATED_TOPIC_NAMES = (
    "attach_hydration_urls",
    "hydration_fetch",
    "HydrationPhase1Stage",
    "HydrationPhase2Stage",
    "assemble_hydration_dossier",
    "ResearcherHydratedPlanStage",
    "researcher_search",
    "ResearcherAssembleStage",
    "merge_sources",
    "renumber_sources",
    "filter_media_actors_quoted",
    "propagate_outlet_metadata",
    "consolidate_actors",
    "ResolveActorAliasesStage",
    "partition_canonical_actors_by_evidence",
    "normalize_pre_research",
    "PerspectiveStage",
    "enrich_perspective_clusters",
    "mirror_perspective_synced",
    "WriterStage",
    "QaAnalyzeStage",
    "mirror_qa_corrected",
    "PerspectiveSyncStage",
    # mirror_perspective_synced runs a SECOND time after PerspectiveSyncStage
    # (V2-06b stage-order fix) — but for `--from`/`--to` matching the first
    # occurrence is what matters, so the name is not duplicated in this list.
    "prune_unused_sources_and_clusters",
    "cleanup_stale_references",
    "compute_source_balance",
    "validate_coverage_gaps_stage",
    "consolidate_missing_coverage",
    "derive_mentioned_actors",
    "BiasLanguageStage",
    "compose_transparency_card",
)


def production_stage_names() -> list[str]:
    """Return the canonical stage-name list for the production variant.

    Used by ``scripts/run.py`` to validate ``--from``/``--to`` choices
    without instantiating agents. Order matches the dispatch order of
    :func:`build_production_stages`.
    """
    return list(_PRODUCTION_RUN_NAMES + _PRODUCTION_TOPIC_NAMES)


def hydrated_stage_names() -> list[str]:
    """Return the canonical stage-name list for the hydrated variant."""
    return list(_HYDRATED_RUN_NAMES + _HYDRATED_TOPIC_NAMES)


__all__ = [
    "build_hydrated_stages",
    "build_production_stages",
    "build_production_stages_llm_assignment",
    "hydrated_stage_names",
    "production_stage_names",
]
