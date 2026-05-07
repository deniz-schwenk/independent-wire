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
import re
from typing import Any, Callable, Optional

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
# 10b. filter_media_actors_quoted
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("final_sources",),
    writes=("final_sources",),
)
async def filter_media_actors_quoted(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Drop ``type: media`` entries from every source's ``actors_quoted``.

    Phase 1 (Flash) classifies outlets — Al Jazeera, Channel 14, Israeli
    Broadcasting Corporation, Tasnim News Agency, etc. — as ``type=media``
    in the per-article actor extraction. Outlets are sources of
    attribution, not policy actors with positions, and shouldn't appear
    in actor lists rendered downstream or harvested into perspective
    clusters by ``enrich_perspective_clusters``.

    Sources without an ``actors_quoted`` field, with an empty list, or
    whose list contains zero ``type=media`` entries pass through
    unchanged. Non-dict actor entries are preserved as-is. Sources whose
    ``actors_quoted`` becomes empty after filtering remain in
    ``final_sources`` — empty actors_quoted is fine, the source is still
    a source.

    Logs one INFO line per topic with the tally of dropped entries.
    """
    final_sources = list(topic_bus.final_sources or [])
    if not final_sources:
        return topic_bus

    new_sources: list = []
    dropped_total = 0
    sources_touched = 0
    for source in final_sources:
        if not isinstance(source, dict):
            new_sources.append(source)
            continue
        actors = source.get("actors_quoted")
        if not isinstance(actors, list) or not actors:
            new_sources.append(source)
            continue
        kept: list = []
        dropped_here = 0
        for entry in actors:
            if isinstance(entry, dict) and entry.get("type") == "media":
                dropped_here += 1
                continue
            kept.append(entry)
        if dropped_here == 0:
            new_sources.append(source)
            continue
        new_source = copy.deepcopy(source)
        new_source["actors_quoted"] = kept
        new_sources.append(new_source)
        dropped_total += dropped_here
        sources_touched += 1

    if dropped_total:
        logger.info(
            "filter_media_actors_quoted: dropped %d actors of type=media "
            "across %d source(s)",
            dropped_total,
            sources_touched,
        )

    return topic_bus.model_copy(update={"final_sources": new_sources})


# ---------------------------------------------------------------------------
# 10b'. propagate_outlet_metadata
# ---------------------------------------------------------------------------


import json as _json
from pathlib import Path as _Path

_SOURCES_CONFIG_PATH = (
    _Path(__file__).resolve().parents[2] / "config" / "sources.json"
)
_OUTLET_LOOKUP_CACHE: dict[str, dict] | None = None


def _load_outlet_lookup() -> dict[str, dict]:
    """Load and cache the outlet → metadata lookup from
    ``config/sources.json``.

    Cached at module level so a 72-feed JSON parse runs once per
    process rather than once per topic. The cache stays valid across
    pipeline runs in a long-lived process; tests that mutate the file
    can reset by setting ``_OUTLET_LOOKUP_CACHE = None``.
    """
    global _OUTLET_LOOKUP_CACHE
    if _OUTLET_LOOKUP_CACHE is not None:
        return _OUTLET_LOOKUP_CACHE
    try:
        raw = _json.loads(_SOURCES_CONFIG_PATH.read_text())
    except FileNotFoundError:
        logger.warning(
            "propagate_outlet_metadata: %s not found; lookup empty",
            _SOURCES_CONFIG_PATH,
        )
        _OUTLET_LOOKUP_CACHE = {}
        return _OUTLET_LOOKUP_CACHE
    feeds = raw.get("feeds") or []
    lookup: dict[str, dict] = {}
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        name = feed.get("name")
        if not isinstance(name, str) or not name:
            continue
        lookup[name] = {
            "tier": feed.get("tier"),
            "editorial_independence": feed.get("editorial_independence"),
            "bias_note": feed.get("bias_note"),
        }
    _OUTLET_LOOKUP_CACHE = lookup
    return lookup


@topic_stage_def(
    reads=("final_sources",),
    writes=("final_sources",),
)
async def propagate_outlet_metadata(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Copy ``tier`` / ``editorial_independence`` / ``bias_note`` from
    ``config/sources.json`` onto each ``final_sources[i]`` whose
    ``outlet`` matches a feed name.

    These three fields exist in the feed configuration but were never
    propagated through the pipeline — render layers had no way to
    surface editorial-independence indicators or bias notes per outlet.

    Researcher-hydrated third-party citations (outlets not in
    ``config/sources.json``) remain unmatched: their three fields stay
    ``None`` and the renderer surfaces a "not yet categorized"
    indicator per Decision 6 of TASK-RENDER-RESTRUCTURE-V2.

    Logs one INFO line per topic with the match tally.
    """
    final_sources = list(topic_bus.final_sources or [])
    if not final_sources:
        return topic_bus

    lookup = _load_outlet_lookup()

    new_sources: list = []
    matched = 0
    total = 0
    for source in final_sources:
        if not isinstance(source, dict):
            new_sources.append(source)
            continue
        total += 1
        outlet = source.get("outlet")
        meta = lookup.get(outlet) if isinstance(outlet, str) else None
        new_source = copy.deepcopy(source)
        if meta is not None:
            matched += 1
            new_source["tier"] = meta.get("tier")
            new_source["editorial_independence"] = meta.get(
                "editorial_independence"
            )
            new_source["bias_note"] = meta.get("bias_note")
        else:
            # Defensive: explicitly set to None when no match so the
            # rendered TP shape is consistent across all sources.
            new_source.setdefault("tier", None)
            new_source.setdefault("editorial_independence", None)
            new_source.setdefault("bias_note", None)
        new_sources.append(new_source)

    logger.info(
        "propagate_outlet_metadata: matched %d of %d sources",
        matched,
        total,
    )

    return topic_bus.model_copy(update={"final_sources": new_sources})


# ---------------------------------------------------------------------------
# 10c. consolidate_actors
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("final_sources",),
    writes=("final_actors",),
)
async def consolidate_actors(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Flatten ``final_sources[].actors_quoted[]`` into a deduped
    ``final_actors[]`` list with stable ``actor-NNN`` IDs.

    Runs after ``filter_media_actors_quoted`` (so ``type=media`` entries
    are already gone) and before ``PerspectiveStage`` (which receives the
    flat list and emits per-cluster ``actor_ids[]``).

    Dedup is exact-string-match on the actor's ``name`` field
    (case-sensitive, no normalisation). "Donald Trump" / "President
    Trump" / "Trump" therefore yield three distinct entries — alias
    resolution is a deferred future workstream.

    For role/type conflicts (the same actor name classified differently
    across sources) the first encountered value wins. Quote records
    accumulate one entry per source-membership; ``verbatim`` may be
    ``None`` when the source paraphrases.

    Phase-1 schema per TASK-PERSPECTIVE-ACTOR-SCOPING §1.1::

        {
            "id": "actor-NNN",
            "name": str,
            "role": str,
            "type": str,
            "source_ids": [str, ...],
            "quotes": [
                {"source_id": str, "verbatim": str | None, "position": str},
                ...
            ],
        }
    """
    final_sources = list(topic_bus.final_sources or [])
    if not final_sources:
        return topic_bus

    # Insertion-ordered dict from name -> actor record so we can both
    # dedup and preserve first-appearance order for ID assignment.
    by_name: dict[str, dict] = {}
    sources_seen = 0
    for source in final_sources:
        if not isinstance(source, dict):
            continue
        sources_seen += 1
        sid = source.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        actors = source.get("actors_quoted")
        if not isinstance(actors, list) or not actors:
            continue
        for entry in actors:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            role = entry.get("role") or ""
            atype = entry.get("type") or ""
            position = entry.get("position") or ""
            verbatim = entry.get("verbatim_quote")
            if not isinstance(verbatim, str) or not verbatim:
                verbatim = None

            record = by_name.get(name)
            if record is None:
                record = {
                    "id": "",  # filled after the dedup loop
                    "name": name,
                    "role": role,
                    "type": atype,
                    "source_ids": [],
                    "quotes": [],
                }
                by_name[name] = record
            # source_ids accumulates one entry per distinct source the
            # actor appears in (a single source contributing two
            # paraphrased and verbatim entries shouldn't double-count).
            if sid not in record["source_ids"]:
                record["source_ids"].append(sid)
            record["quotes"].append(
                {
                    "source_id": sid,
                    "verbatim": verbatim,
                    "position": position,
                }
            )

    final_actors: list[dict] = []
    for i, record in enumerate(by_name.values(), start=1):
        record["id"] = f"actor-{i:03d}"
        final_actors.append(record)

    logger.info(
        "consolidate_actors: %d unique actors across %d sources",
        len(final_actors),
        sources_seen,
    )

    return topic_bus.model_copy(update={"final_actors": final_actors})


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
# 12b. enrich_perspective_clusters  (deterministic, runs after PerspectiveStage)
# ---------------------------------------------------------------------------


def _build_source_index(sources: list) -> dict[str, dict]:
    """Map source id → source dict for O(1) lookup during enrichment."""
    out: dict[str, dict] = {}
    for src in sources or []:
        if isinstance(src, dict):
            sid = src.get("id")
            if isinstance(sid, str) and sid:
                out[sid] = src
    return out


def _build_actor_index(actors: list) -> dict[str, dict]:
    """Map actor id → actor dict for O(1) lookup during enrichment."""
    out: dict[str, dict] = {}
    for actor in actors or []:
        if isinstance(actor, dict):
            aid = actor.get("id")
            if isinstance(aid, str) and aid:
                out[aid] = actor
    return out


def _enrich_position_clusters_logic(
    perspective_analysis: dict,
    final_sources: list,
    canonical_actors: list,
) -> dict:
    """Attach deterministic fields to the agent's raw cluster output.

    Cluster→actor assignment is an agent decision (per-cluster
    ``actor_ids[]`` emitted by PerspectiveStage), not a source-membership
    fan-out — that prior leak loop is gone.

    What this stage adds, deterministically:

    - ``id`` — sequential ``pc-NNN``
    - ``regions`` / ``languages`` — derived from the cited sources
    - ``n_actors`` / ``n_sources`` / ``n_regions`` / ``n_languages`` —
      objective counts replacing the prior ``representation``
      bucket (which reproduced the bias the system aims to surface and
      was arithmetically inconsistent against the post-prune source set)

    Validation: every ``actor_ids`` entry the agent emitted must reference
    an ID present in ``canonical_actors[]`` (the post-resolution actor
    list); invalid IDs are dropped and a WARNING is logged so the smoke
    run flags hallucinations. Aliased IDs that PerspectiveStage may have
    referenced (rare — Perspective receives canonical_actors as input,
    so this is a defensive guard) are also dropped here.
    """
    import copy as _copy

    if not perspective_analysis or not isinstance(perspective_analysis, dict):
        return perspective_analysis

    by_id = _build_source_index(final_sources)
    actor_index = _build_actor_index(canonical_actors)

    enriched = _copy.deepcopy(perspective_analysis)
    for cluster_idx, cluster in enumerate(
        enriched.get("position_clusters", []) or [], start=1
    ):
        if not isinstance(cluster, dict):
            continue
        cluster["id"] = f"pc-{cluster_idx:03d}"
        source_ids = [
            s for s in (cluster.get("source_ids") or []) if isinstance(s, str)
        ]

        regions_seen: set[str] = set()
        languages_seen: set[str] = set()
        for sid in source_ids:
            src = by_id.get(sid)
            if not src:
                continue
            country = normalise_country(src.get("country"))
            language = normalise_language(src.get("language"))
            if country:
                regions_seen.add(country)
            if language:
                languages_seen.add(language)

        # Validate agent-assigned actor_ids against the canonical
        # canonical_actors[] list (post alias resolution). Invalid IDs
        # (hallucinations, stale references, or aliased IDs that
        # disappeared post-merge) are dropped and logged so the smoke
        # flags them.
        raw_actor_ids = [
            a for a in (cluster.get("actor_ids") or []) if isinstance(a, str)
        ]
        valid_actor_ids: list[str] = []
        seen_aids: set[str] = set()
        for aid in raw_actor_ids:
            if aid in actor_index and aid not in seen_aids:
                valid_actor_ids.append(aid)
                seen_aids.add(aid)
            elif aid not in actor_index:
                logger.warning(
                    "enrich_perspective_clusters: cluster %s referenced "
                    "unknown actor_id %r; dropping",
                    cluster["id"],
                    aid,
                )

        cluster["actor_ids"] = valid_actor_ids
        cluster["regions"] = sorted(regions_seen)
        cluster["languages"] = sorted(languages_seen)
        cluster["n_actors"] = len(valid_actor_ids)
        cluster["n_sources"] = len(source_ids)
        cluster["n_regions"] = len(regions_seen)
        cluster["n_languages"] = len(languages_seen)

    return enriched


@topic_stage_def(
    reads=("perspective_clusters", "final_sources", "canonical_actors"),
    writes=("perspective_clusters",),
)
async def enrich_perspective_clusters(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Attach deterministic enrichment fields to the raw cluster output
    written by PerspectiveStage. Runs immediately after the agent stage
    in both production and hydrated variants.

    Reads `perspective_clusters` (raw shape from PerspectiveStage:
    `[{position_label, position_summary, source_ids, actor_ids}]`),
    `final_sources`, and `canonical_actors` (the post alias-resolution
    actor list). Writes `perspective_clusters` enriched with `pc-NNN`,
    validated `actor_ids` (joined against `canonical_actors`), regions,
    languages, and the count summary `n_actors / n_sources / n_regions /
    n_languages` computed against canonical-actor membership.

    No-op when `perspective_clusters` is empty (PerspectiveStage may have
    failed or emitted nothing). The post-validator accepts the empty case
    via the slot's optional_write annotation.
    """
    raw = list(topic_bus.perspective_clusters or [])
    if not raw:
        return topic_bus

    enriched = _enrich_position_clusters_logic(
        {"position_clusters": raw},
        list(topic_bus.final_sources or []),
        list(topic_bus.canonical_actors or []),
    )
    return topic_bus.model_copy(
        update={
            "perspective_clusters": list(
                enriched.get("position_clusters") or []
            )
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
# 19a. prune_unused_sources_and_clusters
# ---------------------------------------------------------------------------


_SRC_CITATION_RE = re.compile(r"\[(src-\d+)\]")


def _collect_referenced_src_ids(topic_bus: TopicBus) -> set[str]:
    """Walk every downstream consumer of ``final_sources`` and return the
    set of ``src-NNN`` IDs that are actually referenced somewhere.

    Reference sites scanned:

    - ``perspective_clusters_synced[i].source_ids[]``
    - ``qa_divergences[i].source_ids[]``
    - ``merged_preliminary_divergences[i].source_ids[]``
    - ``qa_corrected_article`` and ``writer_article`` (body/headline/
      subheadline/summary), via inline ``[src-NNN]`` citations
    - ``bias_language_findings[i]`` excerpt + issue + explanation prose
      (any inline ``[src-NNN]`` citation echoed from the article)
    - ``coverage_gaps_validated[i]`` strings (any inline ``[src-NNN]``
      reference)

    Items that fail the expected shape are skipped with a
    ``logger.warning`` rather than crashing the stage — the schema is V2
    typed but defensive scanning costs nothing.
    """
    referenced: set[str] = set()

    def _harvest_source_ids(items, label: str) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                logger.warning(
                    "prune: unexpected non-dict item in %s: %r", label, type(item),
                )
                continue
            for sid in item.get("source_ids") or []:
                if isinstance(sid, str):
                    referenced.add(sid)

    _harvest_source_ids(topic_bus.perspective_clusters_synced, "perspective_clusters_synced")
    _harvest_source_ids(topic_bus.qa_divergences, "qa_divergences")
    _harvest_source_ids(topic_bus.merged_preliminary_divergences, "merged_preliminary_divergences")

    # Article bodies carry [src-NNN] inline citations. qa_corrected_article
    # is post-mirror so it carries the active body; writer_article is the
    # defence-in-depth fallback for the case where qa_corrected is empty.
    for article in (topic_bus.qa_corrected_article, topic_bus.writer_article):
        if article is None:
            continue
        for field in ("body", "headline", "subheadline", "summary"):
            value = getattr(article, field, "") or ""
            if isinstance(value, str):
                referenced.update(_SRC_CITATION_RE.findall(value))

    # Bias language findings can echo article excerpts that include citations.
    for finding in topic_bus.bias_language_findings or []:
        if not isinstance(finding, dict):
            logger.warning(
                "prune: unexpected non-dict item in bias_language_findings: %r",
                type(finding),
            )
            continue
        for key in ("excerpt", "issue", "explanation"):
            text = finding.get(key) or ""
            if isinstance(text, str):
                referenced.update(_SRC_CITATION_RE.findall(text))

    # coverage_gaps_validated entries are descriptive strings; they may
    # still contain inline [src-NNN] references when the gap names a
    # specific source-coverage shortfall.
    for gap in topic_bus.coverage_gaps_validated or []:
        if isinstance(gap, str):
            referenced.update(_SRC_CITATION_RE.findall(gap))
        elif isinstance(gap, dict):
            for key in ("description", "explanation", "gap"):
                text = gap.get(key) or ""
                if isinstance(text, str):
                    referenced.update(_SRC_CITATION_RE.findall(text))
            for sid in gap.get("source_ids") or []:
                if isinstance(sid, str):
                    referenced.add(sid)

    return referenced


@topic_stage_def(
    reads=(
        "final_sources",
        "perspective_clusters_synced",
        "writer_article",
        "qa_corrected_article",
        "qa_divergences",
        "bias_language_findings",
        "merged_preliminary_divergences",
        "coverage_gaps_validated",
    ),
    writes=(
        "final_sources",
        "perspective_clusters_synced",
        "prune_dropped_sources",
        "prune_dropped_clusters",
    ),
)
async def prune_unused_sources_and_clusters(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Drop dead-weight sources and empty position clusters.

    Source drop rule (strict): a source is dropped when its ``id`` is not
    referenced anywhere downstream. The reference set spans
    ``perspective_clusters_synced``, ``qa_divergences``,
    ``merged_preliminary_divergences``, the article bodies
    (``qa_corrected_article`` first, ``writer_article`` fallback),
    ``bias_language_findings``, and ``coverage_gaps_validated`` —
    see :func:`_collect_referenced_src_ids` for the full list.
    Content (summary, actors_quoted) is no longer a keep-reprieve: if
    the synthesis stack chose not to use a source, it is off-topic and
    drops out of the published TP.

    A cluster is dropped when both ``actor_ids`` and ``source_ids`` are
    empty — a cluster the agent emitted but for which neither a speaker
    nor a source-level grounding came through is dead weight in the
    published TP.

    Each drop logs a single INFO line so reviewers can trace which
    entries were removed on a smoke run.
    """
    final_sources = list(topic_bus.final_sources or [])
    clusters = list(topic_bus.perspective_clusters_synced or [])

    referenced = _collect_referenced_src_ids(topic_bus)

    kept_sources: list = []
    dropped_sources: list[dict] = []
    for source in final_sources:
        if not isinstance(source, dict):
            kept_sources.append(source)
            continue
        sid = source.get("id")
        is_referenced = isinstance(sid, str) and sid in referenced
        if is_referenced:
            kept_sources.append(source)
        else:
            summary_snippet = (source.get("summary") or "").strip()[:60]
            logger.info(
                "prune_unused_sources_and_clusters: dropped source %s "
                "(not referenced in body, clusters, divergences, gaps, or "
                "bias_findings): outlet=%s summary=%r",
                sid,
                source.get("outlet"),
                summary_snippet,
            )
            dropped_sources.append(
                {
                    "id": sid or "",
                    "outlet": source.get("outlet") or "",
                    "summary": summary_snippet,
                }
            )

    kept_clusters: list = []
    dropped_clusters: list[dict] = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            kept_clusters.append(cluster)
            continue
        actor_ids = cluster.get("actor_ids") or []
        source_ids = cluster.get("source_ids") or []
        if actor_ids or source_ids:
            kept_clusters.append(cluster)
        else:
            logger.info(
                "prune_unused_sources_and_clusters: dropped cluster %s "
                "(empty actor_ids and empty source_ids): label=%s",
                cluster.get("id") or cluster.get("position_label"),
                cluster.get("position_label"),
            )
            dropped_clusters.append(
                {
                    "id": cluster.get("id") or "",
                    "position_label": cluster.get("position_label") or "",
                }
            )

    return topic_bus.model_copy(
        update={
            "final_sources": kept_sources,
            "perspective_clusters_synced": kept_clusters,
            "prune_dropped_sources": dropped_sources,
            "prune_dropped_clusters": dropped_clusters,
        }
    )


# ---------------------------------------------------------------------------
# 20. compose_transparency_card
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=(
        "editor_selected_topic",
        "qa_problems_found",
        "qa_corrections",
        "writer_article",
        "qa_corrected_article",
        "prune_dropped_sources",
        "prune_dropped_clusters",
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
    - qa_problems_found / qa_corrections: copied through.
    - dropped_sources / dropped_clusters: passed through from the
      `prune_dropped_*` staging slots populated by
      `prune_unused_sources_and_clusters`. Both arrays are
      present-but-empty when nothing was dropped.
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
        qa_corrections=copy.deepcopy(topic_bus.qa_corrections),
        dropped_sources=copy.deepcopy(list(topic_bus.prune_dropped_sources or [])),
        dropped_clusters=copy.deepcopy(list(topic_bus.prune_dropped_clusters or [])),
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
# 7 (hydrated). hydration_fetch — make_hydration_fetch factory
# ---------------------------------------------------------------------------


def make_hydration_fetch(fetcher: Optional[Callable] = None) -> Callable:
    """Build a `hydration_fetch` topic-stage closing over a fetcher callable.

    Reads:  hydration_urls (populated by attach_hydration_urls).
    Writes: hydration_fetch_results.

    The fetcher signature is `async (entries: list[dict]) -> list[dict]`.
    Default fetcher is :func:`src.hydration.hydrate_urls` (aiohttp +
    trafilatura). Tests inject a fake to avoid network I/O.

    Per ARCH §5.2 stage 7. The post-validator enforces non-empty
    `hydration_fetch_results`; runs with no URLs will fail loud at
    `attach_hydration_urls` upstream.
    """

    async def _default_fetcher(entries: list[dict]) -> list[dict]:
        from src.hydration import hydrate_urls

        return await hydrate_urls(entries)

    fn = fetcher or _default_fetcher

    @topic_stage_def(
        reads=("hydration_urls",),
        writes=("hydration_fetch_results",),
    )
    async def hydration_fetch(
        topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        urls = list(topic_bus.hydration_urls or [])
        results = await fn(urls)
        return topic_bus.model_copy(
            update={"hydration_fetch_results": list(results or [])}
        )

    return hydration_fetch


hydration_fetch = make_hydration_fetch()


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
                # Defence-in-depth: hydrate_urls now resolves country from
                # the outlet registry (or sets it to "unknown" explicitly),
                # but we keep this nullable-coalesce so a stale fetch
                # snapshot reused via --reuse never propagates a literal
                # null to final_sources.
                "country": record.get("country") or "unknown",
                "summary": analysis.get("summary", ""),
                "estimated_date": record.get("published_date"),
                "actors_quoted": actors_out,
            }
        )

    pre_dossier = type(topic_bus.hydration_pre_dossier)(
        sources=sources,
        preliminary_divergences=list(phase2.preliminary_divergences or []),
        coverage_gaps=list(phase2.coverage_gaps or []),
    )
    return topic_bus.model_copy(update={"hydration_pre_dossier": pre_dossier})


# ---------------------------------------------------------------------------
# researcher_search — pure-Python topic-stage (V2-06)
# ---------------------------------------------------------------------------


import re as _re

_URL_PATTERN = _re.compile(r"^\s{3}(https?://\S+)", _re.MULTILINE)
_ENTRY_PATTERN = _re.compile(
    r"^\d+\.\s+(.+)\n\s{3}(https?://\S+)\n\s{3}(.+?)(?=\n\d+\.\s|\nResults for:|\Z)",
    _re.MULTILINE | _re.DOTALL,
)


def _extract_date_from_url_local(url: str) -> Optional[str]:
    """Local copy of date extraction — duplicate of the helper in
    src/agent_stages.py to keep topic_stages.py independent of agent_stages.
    Both come from V1 src/pipeline.py:71-103."""
    if not url:
        return None
    m = _re.search(r"/(\d{4})[/-](\d{2})[/-](\d{2})(?:/|[^0-9])", url)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2020 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _re.search(r"/(\d{4})(\d{2})(\d{2})(?:/|[^0-9]|$)", url)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2020 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _re.search(r"/(\d{4})[/-](\d{2})(?:/|[^0-9])", url)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 2020 <= y <= 2030 and 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-01"
    return None


def _deduplicate_search_results(search_results: list[dict]) -> list[dict]:
    """Deduplicate search results by URL, merging found_by query annotations.
    V1 reference: src/pipeline.py:222-303."""
    url_map: dict[str, dict] = {}
    for sr in search_results:
        raw = sr.get("results", "")
        query_str = sr.get("query", "")
        for match in _ENTRY_PATTERN.finditer(raw):
            title = match.group(1).strip()
            url = match.group(2).strip()
            snippet = match.group(3).strip()
            if url in url_map:
                url_map[url]["found_by"].append(query_str)
                if len(snippet) > len(url_map[url]["snippet"]):
                    url_map[url]["snippet"] = snippet
                    url_map[url]["title"] = title
            else:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "found_by": [query_str],
                }

    deduped: list[dict] = []
    seen_urls: set[str] = set()
    for sr in search_results:
        raw = sr.get("results", "")
        query_str = sr.get("query", "")
        new_lines: list[str] = []
        entry_num = 1
        for match in _ENTRY_PATTERN.finditer(raw):
            url = match.group(2).strip()
            if url in seen_urls:
                continue
            seen_urls.add(url)
            info = url_map.get(url, {})
            title = info.get("title", match.group(1).strip())
            snippet = info.get("snippet", match.group(3).strip())
            found_by = info.get("found_by", [query_str])
            found_by_note = ""
            if len(found_by) > 1:
                other_queries = [q for q in found_by if q != query_str]
                found_by_note = f"\n   [Also found by: {'; '.join(other_queries)}]"
            new_lines.append(
                f"{entry_num}. {title}\n   {url}\n   {snippet}{found_by_note}"
            )
            entry_num += 1
        if new_lines:
            header = f"Results for: {query_str}"
            new_entry = dict(sr)
            new_entry["results"] = header + "\n\n" + "\n\n".join(new_lines)
            deduped.append(new_entry)
        elif not _ENTRY_PATTERN.search(raw):
            deduped.append(sr)

    duplicates = sum(
        len(v["found_by"]) - 1 for v in url_map.values() if len(v["found_by"]) > 1
    )
    if duplicates:
        logger.info(
            "researcher_search: deduplicated %d cross-query URL duplicates",
            duplicates,
        )
    return deduped


def _enrich_url_dates(search_results: list[dict]) -> None:
    """Attach url_dates to each search result entry, in-place."""
    for sr in search_results:
        raw = sr.get("results", "")
        urls_with_dates: list[dict] = []
        for url_match in _URL_PATTERN.finditer(raw):
            url = url_match.group(1)
            est_date = _extract_date_from_url_local(url)
            if est_date:
                urls_with_dates.append({"url": url, "estimated_date": est_date})
        if urls_with_dates:
            sr["url_dates"] = urls_with_dates


def make_researcher_search(web_search_tool: Any) -> Callable:
    """Build a researcher_search topic-stage closing over an injected
    `web_search_tool`. The tool object must expose
    `async def execute(query: str) -> str` returning a plain-text result
    block in V1's `N. title\\n   url\\n   snippet` shape.
    """

    @topic_stage_def(
        reads=("researcher_plan_queries",),
        writes=("researcher_search_results",),
    )
    async def researcher_search(
        topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        queries = list(topic_bus.researcher_plan_queries or [])
        if not queries:
            return topic_bus

        search_results: list[dict] = []
        for q in queries:
            if not isinstance(q, dict):
                continue
            query_str = q.get("query", "")
            if not query_str:
                continue
            try:
                result_text = await web_search_tool.execute(query=query_str)
                search_results.append(
                    {
                        "query": query_str,
                        "language": q.get("language", "en"),
                        "results": result_text,
                    }
                )
            except Exception as e:
                logger.warning(
                    "researcher_search: query %r failed: %s", query_str, e
                )
                search_results.append(
                    {
                        "query": query_str,
                        "language": q.get("language", "en"),
                        "results": f"Error: {e}",
                    }
                )

        successful = sum(
            1 for r in search_results if not r["results"].startswith("Error")
        )
        logger.info(
            "researcher_search: %d/%d queries returned results",
            successful,
            len(search_results),
        )

        deduped = _deduplicate_search_results(search_results)
        _enrich_url_dates(deduped)

        return topic_bus.model_copy(update={"researcher_search_results": deduped})

    return researcher_search


__all__ = [
    "assemble_hydration_dossier",
    "attach_hydration_urls",
    "compose_transparency_card",
    "compute_source_balance",
    "consolidate_actors",
    "enrich_perspective_clusters",
    "filter_media_actors_quoted",
    "make_researcher_search",
    "merge_sources",
    "mirror_qa_corrected",
    "mirror_perspective_synced",
    "normalize_pre_research",
    "propagate_outlet_metadata",
    "renumber_sources",
    "validate_coverage_gaps_stage",
]
