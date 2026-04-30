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

from typing import Any, Callable

from src.agent_stages import (
    BiasLanguageStage,
    CuratorStage,
    EditorStage,
    HydrationPhase1Stage,
    HydrationPhase2Stage,
    PerspectiveStage,
    PerspectiveSyncStage,
    QaAnalyzeStage,
    ResearcherAssembleStage,
    ResearcherHydratedPlanStage,
    ResearcherPlanStage,
    WriterStage,
)
from src.stages import (
    assemble_hydration_dossier,
    attach_hydration_urls,
    compose_transparency_card,
    compute_source_balance,
    enrich_perspective_clusters,
    fetch_findings,
    init_run,
    make_hydration_fetch,
    make_researcher_search,
    merge_sources,
    mirror_perspective_synced,
    mirror_qa_corrected,
    normalize_pre_research,
    renumber_sources,
    select_topics,
    validate_coverage_gaps_stage,
)


def _wrap_researcher_search(web_search_tool: Any) -> Callable:
    if web_search_tool is None:
        return make_researcher_search(None)
    return make_researcher_search(web_search_tool)


def build_production_stages(
    agents: dict[str, Any],
    *,
    web_search_tool: Any = None,
    hydration_fetcher: Any = None,
) -> tuple[list, list, list]:
    """Build the production variant's three stage lists.

    Returns ``(run_stages, topic_stages, post_run_stages)``.

    :param agents: Dict from ``scripts/run.py:create_agents()``. Required
        keys: ``curator``, ``editor``, ``researcher_plan``,
        ``researcher_assemble``, ``perspective``, ``writer``, ``qa_analyze``,
        ``bias_language``.
    :param web_search_tool: Tool injected into the researcher_search
        deterministic stage. Tests pass a fake; production passes the
        Brave-search tool.
    :param hydration_fetcher: Unused in production (no hydration). Kept
        for API symmetry.
    """
    run_stages = [
        init_run,
        fetch_findings,
        CuratorStage(agents["curator"]),
        EditorStage(agents["editor"]),
        select_topics,
    ]

    topic_stages = [
        ResearcherPlanStage(agents["researcher_plan"]),
        _wrap_researcher_search(web_search_tool),
        ResearcherAssembleStage(agents["researcher_assemble"]),
        merge_sources,
        renumber_sources,
        normalize_pre_research,
        PerspectiveStage(agents["perspective"]),
        enrich_perspective_clusters,
        mirror_perspective_synced,  # 1:1 copy because production has no perspective_sync
        WriterStage(agents["writer"]),
        QaAnalyzeStage(agents["qa_analyze"]),
        mirror_qa_corrected,
        compute_source_balance,
        validate_coverage_gaps_stage,
        BiasLanguageStage(agents["bias_language"]),
        compose_transparency_card,
    ]

    post_run_stages: list = []  # populated by the runner with RenderStage + FinalizeRunStage

    return run_stages, topic_stages, post_run_stages


def build_hydrated_stages(
    agents: dict[str, Any],
    *,
    web_search_tool: Any = None,
    hydration_fetcher: Any = None,
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
    """
    run_stages = [
        init_run,
        fetch_findings,
        CuratorStage(agents["curator"]),
        EditorStage(agents["editor"]),
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
        normalize_pre_research,
        PerspectiveStage(agents["perspective"]),
        enrich_perspective_clusters,
        mirror_perspective_synced,  # 1st: 1:1 copy after enrich (V2-06b stage-order fix)
        WriterStage(agents["writer"]),
        QaAnalyzeStage(agents["qa_analyze"]),
        mirror_qa_corrected,
        PerspectiveSyncStage(agents["perspective_sync"]),
        mirror_perspective_synced,  # 2nd: element-merge of perspective_sync deltas
        compute_source_balance,
        validate_coverage_gaps_stage,
        BiasLanguageStage(agents["bias_language"]),
        compose_transparency_card,
    ]

    post_run_stages: list = []

    return run_stages, topic_stages, post_run_stages


__all__ = [
    "build_hydrated_stages",
    "build_production_stages",
]
