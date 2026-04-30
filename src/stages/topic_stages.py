"""V2 TopicBus-scoped deterministic stages.

Per ARCH-V2-BUS-SCHEMA §5.1 (production) + §5.2 (hydrated additions),
the deterministic topic-stages are:

    Production (8):
      9.  merge_sources
      10. renumber_sources
      11. normalize_pre_research
      13. mirror_perspective_synced       (also runs in production)
      16. mirror_qa_corrected             (also runs in production)
      17. compute_source_balance
      18. validate_coverage_gaps_stage
      20. compose_transparency_card

    Hydrated additions (2):
      6.  attach_hydration_urls
      10. assemble_hydration_dossier

V1 logic ports (each named in the relevant stage):
- merge_sources / renumber_sources: distilled from
  src/pipeline.py:_renumber_and_prune_sources (571-675), but the "prune
  unreferenced citations" half drops out — V2 renumbers BEFORE writer
  runs, so there is no body to prune against.
- compute_source_balance: ports the source-balance bookkeeping from
  src/pipeline.py:_build_bias_card (870-944), reading final_sources only.
- validate_coverage_gaps: src/stages/_helpers.validate_coverage_gaps
  (port of src/pipeline.py:_validate_coverage_gaps 1019-1109).
- compose_transparency_card: assembles the TransparencyCard sub-model
  from editor_selected_topic, qa_*, writer_article, run_bus metadata,
  and src/stages/_helpers.strip_stale_quantifiers (port of V1 1137-1194).
- assemble_hydration_dossier: ports
  src/hydration_aggregator.build_prepared_dossier (476-549). Source IDs
  carry the `hydrate-rsrc-NNN` prefix per ARCH §4B.2.
- attach_hydration_urls: ports the URL-extraction shape from
  src/hydration_urls.extract_urls_from_curator (function-name only —
  the actual extraction is one line: read editor_selected_topic.raw_data).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from src.bus import (
    RunBusReadOnly,
    SourceBalance,
    TopicBus,
    TransparencyCard,
    WriterArticle,
)
from src.stage import run_stage_def, topic_stage_def  # noqa: F401  (run_stage_def kept for symmetry)
from src.stages._helpers import (
    normalise_country,
    normalise_language,
    strip_stale_quantifiers,
    validate_coverage_gaps,
)
from src.stages.run_stages import mirror_stage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 9. merge_sources
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("hydration_pre_dossier", "researcher_assemble_dossier"),
    writes=(
        "merged_sources_pre_renumber",
        "merged_preliminary_divergences",
        "merged_coverage_gaps",
    ),
)
async def merge_sources(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus:
    """Concatenate hydration + researcher dossier contents into the merged
    pre-renumber slots.

    In production, hydration_pre_dossier is empty so this is effectively a
    copy from researcher_assemble_dossier. In hydrated, both contribute.
    Source IDs at this stage may carry agent-local prefixes
    (`hydrate-rsrc-NNN`, `research-rsrc-NNN`); renumber_sources rewrites
    them to canonical `src-NNN` next.
    """
    hpd = topic_bus.hydration_pre_dossier
    rad = topic_bus.researcher_assemble_dossier

    merged_sources = list(hpd.sources) + list(rad.sources)
    merged_divs = list(hpd.preliminary_divergences) + list(rad.preliminary_divergences)
    merged_gaps = list(hpd.coverage_gaps) + list(rad.coverage_gaps)

    return topic_bus.model_copy(
        update={
            "merged_sources_pre_renumber": copy.deepcopy(merged_sources),
            "merged_preliminary_divergences": copy.deepcopy(merged_divs),
            "merged_coverage_gaps": copy.deepcopy(merged_gaps),
        }
    )


# ---------------------------------------------------------------------------
# 10. renumber_sources
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("merged_sources_pre_renumber",),
    writes=("final_sources", "id_rename_map"),
)
async def renumber_sources(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Assign canonical `src-NNN` IDs to merged sources in array order.

    Builds id_rename_map (old_id -> new_id) for the downstream
    normalize_pre_research stage to use. Each source's `id` field is
    overwritten with the new value; original prefixed IDs survive only
    inside the rename map.

    Sources without an `id` field are renumbered too, mapped from
    a synthetic placeholder key `__no_id_{i}__` in the rename map (the
    map's purpose is rewriting references; an unreferenced placeholder
    is harmless).

    V2 deviation from V1 _renumber_and_prune_sources (src/pipeline.py:571):
    no pruning. V2 renumbers before writer runs, so there is no body to
    prune against. Every merged source becomes a final source.
    """
    pre = topic_bus.merged_sources_pre_renumber
    if not isinstance(pre, list):
        return topic_bus

    rename_map: dict[str, str] = {}
    new_sources: list[dict] = []
    for i, src in enumerate(pre, start=1):
        if not isinstance(src, dict):
            continue
        new_id = f"src-{i:03d}"
        old_id = src.get("id")
        if isinstance(old_id, str) and old_id:
            rename_map[old_id] = new_id
        else:
            rename_map[f"__no_id_{i}__"] = new_id
        new_src = copy.deepcopy(src)
        new_src["id"] = new_id
        new_sources.append(new_src)

    return topic_bus.model_copy(
        update={"final_sources": new_sources, "id_rename_map": rename_map}
    )


# ---------------------------------------------------------------------------
# 11. normalize_pre_research
# ---------------------------------------------------------------------------


def _rewrite_ids_in_value(value: Any, rename_map: dict[str, str]) -> Any:
    """Recursively rewrite any string token that is exactly an old-id key
    in rename_map to its new-id value. Walks lists and dicts.

    This is intentionally exact-match only (no regex sub-token rewriting)
    to avoid false positives — a string like "tp-2026-04-29-rsrc-001" is
    not an id reference and must not be rewritten.
    """
    if isinstance(value, str):
        return rename_map.get(value, value)
    if isinstance(value, list):
        return [_rewrite_ids_in_value(v, rename_map) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite_ids_in_value(v, rename_map) for k, v in value.items()}
    return value


@topic_stage_def(
    reads=(
        "merged_preliminary_divergences",
        "merged_coverage_gaps",
        "id_rename_map",
    ),
    writes=("merged_preliminary_divergences", "merged_coverage_gaps"),
)
async def normalize_pre_research(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Rewrite agent-local source IDs to canonical `src-NNN` in
    merged_preliminary_divergences and merged_coverage_gaps using
    id_rename_map.

    The two slots are read and written back; the writes are non-empty
    iff the inputs were non-empty (rewriting an empty list yields an
    empty list, which trips post-validation in low-coverage runs — the
    runner handles that case via the optional_write principle when V2-10
    extends the optional_write annotation list).
    """
    rename_map = topic_bus.id_rename_map or {}
    if not rename_map:
        return topic_bus

    new_divs = _rewrite_ids_in_value(
        list(topic_bus.merged_preliminary_divergences), rename_map
    )
    new_gaps = _rewrite_ids_in_value(
        list(topic_bus.merged_coverage_gaps), rename_map
    )
    return topic_bus.model_copy(
        update={
            "merged_preliminary_divergences": new_divs,
            "merged_coverage_gaps": new_gaps,
        }
    )


# ---------------------------------------------------------------------------
# 13. mirror_perspective_synced  (universal — production runs as 1:1 copy)
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("perspective_clusters",),
    writes=("perspective_clusters_synced",),
)
async def mirror_perspective_synced(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Per-element mirror per ARCH §3.3 (b). In hydrated, perspective_sync
    has emitted cluster deltas into perspective_clusters_synced; the
    mirror merges those deltas with the source clusters by `id`. In
    production, perspective_sync does not run, so perspective_clusters_synced
    starts empty and the mirror produces a 1:1 copy of perspective_clusters.

    Either way, the slot is fully populated after this stage runs.
    """
    new_bus = topic_bus.model_copy(deep=True)
    mirror_stage(
        "perspective_clusters_synced",
        "perspective_clusters",
        new_bus,
        granularity="element",
    )
    return new_bus


# ---------------------------------------------------------------------------
# 16. mirror_qa_corrected  (universal)
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("writer_article",),
    writes=("qa_corrected_article",),
)
async def mirror_qa_corrected(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Slot-level mirror per ARCH §3.3 (a). If qa_corrected_article is
    empty (clean QA run, the agent omitted `article`), fill it from
    writer_article. If non-empty (QA emitted a corrected article), keep
    the corrected version unchanged. Final state always has all four
    article fields populated.
    """
    new_bus = topic_bus.model_copy(deep=True)
    mirror_stage(
        "qa_corrected_article",
        "writer_article",
        new_bus,
        granularity="slot",
    )
    return new_bus


# ---------------------------------------------------------------------------
# 17. compute_source_balance
# ---------------------------------------------------------------------------


@topic_stage_def(reads=("final_sources",), writes=("source_balance",))
async def compute_source_balance(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Aggregate language and country counts from final_sources.

    V1 reference: src/pipeline.py:_build_bias_card 870-944 — the
    by_language / by_country bookkeeping. V2 reads final_sources directly
    (V1 read writer_article.sources, but in V2 writer references
    final_sources by `src-NNN` id, so the canonical set lives on
    final_sources).

    `represented` is the sorted set of normalised country names in
    final_sources. `missing_from_dossier` is left empty for V2 — V1's
    notion of "countries from research dossier dropped during writer-prune"
    has no analog in V2 (no prune step). Render-layer or future stages
    can fill it when a use-case lands.
    """
    sources = topic_bus.final_sources or []
    by_language: dict[str, int] = {}
    by_country: dict[str, int] = {}
    countries: set[str] = set()
    for s in sources:
        if not isinstance(s, dict):
            continue
        lang = normalise_language(s.get("language")) or "unknown"
        by_language[lang] = by_language.get(lang, 0) + 1
        country = normalise_country(s.get("country")) or "unknown"
        by_country[country] = by_country.get(country, 0) + 1
        if country and country != "unknown":
            countries.add(country)

    sb = SourceBalance(
        by_country=by_country,
        by_language=by_language,
        represented=sorted(countries),
        missing_from_dossier=[],
    )
    return topic_bus.model_copy(update={"source_balance": sb})


# ---------------------------------------------------------------------------
# 18. validate_coverage_gaps
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("merged_coverage_gaps", "source_balance"),
    writes=("coverage_gaps_validated",),
)
async def validate_coverage_gaps_stage(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Drop coverage-gap statements falsified by source_balance, plus
    near-duplicates. Uses the V1-ported helper.
    """
    sb = topic_bus.source_balance.model_dump() if topic_bus.source_balance else {}
    kept, _dropped = validate_coverage_gaps(
        list(topic_bus.merged_coverage_gaps or []), sb
    )
    return topic_bus.model_copy(update={"coverage_gaps_validated": kept})


# ---------------------------------------------------------------------------
# 20. compose_transparency_card
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=(
        "editor_selected_topic",
        "qa_problems_found",
        "qa_proposed_corrections",
        "writer_article",
        "qa_corrected_article",
    ),
    writes=("transparency_card",),
)
async def compose_transparency_card(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Assemble the transparency card from TopicBus state and the parent
    RunBus's run_id / run_date.

    Fields per ARCH §4B.11:
    - selection_reason: editor_selected_topic.selection_reason cleaned
      via the stale-quantifier strip helper.
    - pipeline_run: {run_id, date} pulled from the RunBus.
    - article_original: a copy of writer_article iff QA modified anything
      (qa_problems_found is non-empty); None otherwise.
    - qa_problems_found / qa_proposed_corrections: copied through.
    """
    raw_reason = topic_bus.editor_selected_topic.selection_reason or ""
    cleaned_reason = strip_stale_quantifiers(raw_reason)

    qa_changed = bool(topic_bus.qa_problems_found)
    article_original = (
        topic_bus.writer_article.model_copy(deep=True) if qa_changed else None
    )

    card = TransparencyCard(
        selection_reason=cleaned_reason,
        pipeline_run={"run_id": run_bus.run_id, "date": run_bus.run_date},
        article_original=article_original,
        qa_problems_found=copy.deepcopy(topic_bus.qa_problems_found),
        qa_proposed_corrections=copy.deepcopy(topic_bus.qa_proposed_corrections),
    )
    return topic_bus.model_copy(update={"transparency_card": card})


# ---------------------------------------------------------------------------
# 6 (hydrated). attach_hydration_urls
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("editor_selected_topic",),
    writes=("hydration_urls",),
)
async def attach_hydration_urls(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Extract hydration URLs from editor_selected_topic.raw_data.

    The Curator-side cluster matching (which V1 did via the
    `src/hydration_urls.py` module) already populated raw_data with the
    URLs at curator-prep time; the topic-stage just lifts them to a
    dedicated TopicBus slot so the agent-stage doesn't have to reach
    inside raw_data at planner construction time.
    """
    raw = topic_bus.editor_selected_topic.raw_data or {}
    urls = raw.get("hydration_urls") or []
    if not isinstance(urls, list):
        urls = []
    return topic_bus.model_copy(update={"hydration_urls": copy.deepcopy(urls)})


# ---------------------------------------------------------------------------
# 10 (hydrated). assemble_hydration_dossier
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=(
        "hydration_fetch_results",
        "hydration_phase1_analyses",
        "hydration_phase2_corpus",
    ),
    writes=("hydration_pre_dossier",),
)
async def assemble_hydration_dossier(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Build the pre-research dossier from T1 fetch records + Phase 1 +
    Phase 2 outputs.

    V1 reference: src/hydration_aggregator.py:build_prepared_dossier
    (lines 476-549). V2 deviation: source IDs carry the `hydrate-rsrc-NNN`
    prefix per ARCH §4B.2 (V1 used bare `rsrc-NNN`); merge_sources +
    renumber_sources translate to canonical `src-NNN` downstream.
    """
    fetch_results = topic_bus.hydration_fetch_results or []
    phase1 = topic_bus.hydration_phase1_analyses or []
    phase2 = topic_bus.hydration_phase2_corpus

    successful = [r for r in fetch_results if isinstance(r, dict) and r.get("status") == "success"]
    analyses_by_index: dict[int, dict] = {
        a["article_index"]: a
        for a in phase1
        if isinstance(a, dict) and isinstance(a.get("article_index"), int)
    }

    sources: list[dict] = []
    for i, record in enumerate(successful):
        analysis = analyses_by_index.get(i, {})
        actors_out: list[dict] = []
        for actor in analysis.get("actors_quoted") or []:
            if not isinstance(actor, dict):
                continue
            quote = actor.get("verbatim_quote")
            if not isinstance(quote, str) or not quote:
                quote = None
            actors_out.append(
                {
                    "name": actor.get("name", ""),
                    "role": actor.get("role", ""),
                    "type": actor.get("type", ""),
                    "position": actor.get("position", ""),
                    "verbatim_quote": quote,
                }
            )
        sources.append(
            {
                "id": f"hydrate-rsrc-{i + 1:03d}",
                "url": record.get("url"),
                "title": record.get("title"),
                "outlet": record.get("outlet"),
                "language": record.get("language"),
                "country": record.get("country"),
                "summary": analysis.get("summary", ""),
                "estimated_date": None,
                "actors_quoted": actors_out,
            }
        )

    pre_dossier = type(topic_bus.hydration_pre_dossier)(
        sources=sources,
        preliminary_divergences=list(phase2.preliminary_divergences or []),
        coverage_gaps=list(phase2.coverage_gaps or []),
    )
    return topic_bus.model_copy(update={"hydration_pre_dossier": pre_dossier})


__all__ = [
    "assemble_hydration_dossier",
    "attach_hydration_urls",
    "compose_transparency_card",
    "compute_source_balance",
    "merge_sources",
    "mirror_qa_corrected",
    "mirror_perspective_synced",
    "normalize_pre_research",
    "renumber_sources",
    "validate_coverage_gaps_stage",
]
