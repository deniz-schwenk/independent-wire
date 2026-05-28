"""V2 TopicBus-scoped deterministic stages.

Per ARCH-V2-BUS-SCHEMA §5.1 (production) + §5.2 (hydrated additions),
the deterministic topic-stages are:

    Production:
      9.  merge_sources
      10. renumber_sources
      11. normalize_pre_research
      13. mirror_perspective_synced       (also runs in production)
      16. mirror_qa_corrected             (also runs in production)
      17. compute_source_balance
      20. compose_transparency_card

    Hydrated additions:
      6.  attach_hydration_urls
      10. assemble_hydration_dossier

The "what is missing" output of the dossier is owned by
``ConsolidatorStage`` (LLM, ``src/agent_stages.py``), which replaced
three deprecated stages (``PerspectiveSyncStage``,
``validate_coverage_gaps_stage``, ``consolidate_missing_coverage``)
in the Consolidator refactor. See ``REPORT-DIAGNOSTIC-2026-05-23.md``.

V1 logic ports (each named in the relevant stage):
- merge_sources / renumber_sources: distilled from
  src/pipeline.py:_renumber_and_prune_sources (571-675), but the "prune
  unreferenced citations" half drops out — V2 renumbers BEFORE writer
  runs, so there is no body to prune against.
- compute_source_balance: ports the source-balance bookkeeping from
  src/pipeline.py:_build_bias_card (870-944), reading final_sources only.
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
    # coverage_gaps: HydrationPhase2 single source of truth
    # (2026-05-21). ResearcherAssemble's contribution dropped so the
    # Researcher Assemble agent no longer re-reports gaps that the
    # upstream HydrationPhase2 already flagged.
    merged_gaps = list(hpd.coverage_gaps)

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
            # evidence_type is emitted by Hydration-Phase-1 per the new
            # extraction-time classification (stated / reported /
            # mentioned). Researcher-Assemble sources do not yet carry
            # this field; the downstream partition stage applies a
            # default policy when the field is absent (see
            # `partition_canonical_actors_by_evidence`).
            evidence_type = entry.get("evidence_type")
            if evidence_type not in ("stated", "reported", "mentioned"):
                evidence_type = None

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
                    "evidence_type": evidence_type,
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
# 10d. partition_canonical_actors_by_evidence
# ---------------------------------------------------------------------------


_EVIDENCE_TIERS: tuple[str, ...] = ("stated", "reported", "mentioned")
_EVIDENCE_DEFAULT: str = "reported"


@topic_stage_def(
    reads=("canonical_actors",),
    writes=(
        "canonical_actors_stated",
        "canonical_actors_reported",
        "canonical_actors_mentioned",
    ),
)
async def partition_canonical_actors_by_evidence(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Split ``canonical_actors[]`` into three evidence-tiered pools.

    Hydration-Phase-1 classifies each actor's evidence relationship to
    its article via the ``evidence_type`` field (`stated` / `reported` /
    `mentioned`). ``consolidate_actors`` threads that field onto every
    entry in ``canonical_actors[].quotes[]``. This stage walks each
    canonical actor and splits the population into three pools by
    quote evidence_type.

    Pool entry shape (mirrors the canonical_actor entry, filtered):

    - ``id``, ``name``, ``role``, ``type``, ``is_anonymous`` —
      identity fields, unchanged.
    - ``quotes`` — only the quote entries whose ``evidence_type``
      matches the pool.
    - ``source_ids`` — only the source IDs referenced by the filtered
      quotes (kept consistent with the quote subset).

    An actor with cross-form coverage in the dossier appears in
    multiple pools, each entry holding the quote subset of the matching
    form. An actor whose every quote has the same evidence_type appears
    in exactly one pool.

    **Missing evidence_type policy.** Researcher-Assemble sources do
    not yet emit ``evidence_type``; quotes from those sources arrive
    here with ``evidence_type == None``. Such quotes are
    default-assigned to ``reported`` — the neutral middle tier — so the
    pipeline operates in both production-only (researcher-sourced
    actors flow through the ``reported`` pool) and hydrated (mixed)
    runs. The default is logged once per topic with the tally of
    defaulted quotes so reviewers can spot when researcher quotes
    dominate a topic.
    """
    canonical_actors = list(topic_bus.canonical_actors or [])
    if not canonical_actors:
        return topic_bus

    pools: dict[str, list[dict]] = {tier: [] for tier in _EVIDENCE_TIERS}
    defaulted_quote_count = 0
    total_quotes = 0

    for actor in canonical_actors:
        if not isinstance(actor, dict):
            continue
        # Bucket this actor's quotes by tier.
        by_tier: dict[str, list[dict]] = {tier: [] for tier in _EVIDENCE_TIERS}
        for quote in actor.get("quotes") or []:
            if not isinstance(quote, dict):
                continue
            total_quotes += 1
            tier = quote.get("evidence_type")
            if tier not in _EVIDENCE_TIERS:
                tier = _EVIDENCE_DEFAULT
                defaulted_quote_count += 1
            by_tier[tier].append(quote)

        # Emit one pool entry per non-empty tier.
        for tier in _EVIDENCE_TIERS:
            tier_quotes = by_tier[tier]
            if not tier_quotes:
                continue
            tier_source_ids: list[str] = []
            for q in tier_quotes:
                sid = q.get("source_id")
                if isinstance(sid, str) and sid and sid not in tier_source_ids:
                    tier_source_ids.append(sid)
            pools[tier].append(
                {
                    "id": actor.get("id", ""),
                    "name": actor.get("name", ""),
                    "role": actor.get("role", ""),
                    "type": actor.get("type", ""),
                    "is_anonymous": bool(actor.get("is_anonymous", False)),
                    "source_ids": tier_source_ids,
                    "quotes": list(tier_quotes),
                }
            )

    if defaulted_quote_count:
        logger.info(
            "partition_canonical_actors_by_evidence: defaulted %d/%d "
            "quote(s) with missing evidence_type to %r tier",
            defaulted_quote_count,
            total_quotes,
            _EVIDENCE_DEFAULT,
        )
    logger.info(
        "partition_canonical_actors_by_evidence: pool sizes — "
        "stated=%d, reported=%d, mentioned=%d (from %d canonical actor(s))",
        len(pools["stated"]),
        len(pools["reported"]),
        len(pools["mentioned"]),
        len(canonical_actors),
    )

    return topic_bus.model_copy(
        update={
            "canonical_actors_stated": pools["stated"],
            "canonical_actors_reported": pools["reported"],
            "canonical_actors_mentioned": pools["mentioned"],
        }
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


_SUBLIST_TIERS: tuple[str, ...] = ("stated", "reported", "mentioned")


def _assert_partition_invariant(
    cluster_id: str,
    stated: list[str],
    reported: list[str],
    mentioned: list[str],
    actor_ids_set: set[str],
) -> None:
    """Verify the three sub-lists partition ``actor_ids`` disjointly.

    A violation here is a programming error in the validator itself, not
    an agent error: by the time this check runs, the cross-tier dedup
    in :func:`_enrich_position_clusters_logic` has repaired any
    agent-side inconsistency, and ``actor_ids`` is the derived sorted
    union of the cleaned sub-lists. Used by both the validator and a
    unit test that exercises the assertion shape with synthetic input.
    """
    stated_set = set(stated)
    reported_set = set(reported)
    mentioned_set = set(mentioned)
    union = stated_set | reported_set | mentioned_set
    if union != actor_ids_set:
        raise AssertionError(
            f"enrich_perspective_clusters: cluster {cluster_id} "
            f"sub-list union {sorted(union)!r} != actor_ids "
            f"{sorted(actor_ids_set)!r}"
        )
    if (
        stated_set & reported_set
        or stated_set & mentioned_set
        or reported_set & mentioned_set
    ):
        raise AssertionError(
            f"enrich_perspective_clusters: cluster {cluster_id} "
            f"sub-lists are not pairwise-disjoint: "
            f"stated={sorted(stated_set)!r} "
            f"reported={sorted(reported_set)!r} "
            f"mentioned={sorted(mentioned_set)!r}"
        )


def _enrich_position_clusters_logic(
    perspective_analysis: dict,
    final_sources: list,
    canonical_actors: list,
    canonical_actors_stated: list | None = None,
    canonical_actors_reported: list | None = None,
    canonical_actors_mentioned: list | None = None,
) -> dict:
    """Attach deterministic fields to the agent's raw cluster output.

    Cluster→actor assignment is an agent decision via three sub-lists
    (``stated`` / ``reported`` / ``mentioned``) classified by evidentiary
    tier upstream by ``partition_canonical_actors_by_evidence``. The
    flat ``actor_ids[]`` field is **derived** by this validator from
    the cleaned sub-list union — the agent does not emit it. The three
    sub-lists are the source of truth.

    What this stage adds, deterministically:

    - ``id`` — sequential ``pc-NNN``
    - ``regions`` / ``languages`` — derived from the cited sources
    - ``actor_ids`` — ``sorted(set(stated) | set(reported) | set(mentioned))``
      after sub-list cleaning
    - ``n_actors`` / ``n_sources`` / ``n_regions`` / ``n_languages`` —
      objective counts

    Validation, in three layers:

    1. Each sub-list entry must reference an ID present in
       ``canonical_actors[]`` (the unified list). Invalid IDs are
       dropped with a warning naming the offending tier. Per-tier
       duplicates are deduped.
    2. **Pool-source consistency** — when the per-tier canonical pools
       are populated (the post-partition_canonical_actors_by_evidence
       path), each sub-list entry must additionally come from the
       matching pool: ``cluster.stated`` IDs from
       ``canonical_actors_stated``, ``cluster.reported`` from
       ``canonical_actors_reported``, ``cluster.mentioned`` from
       ``canonical_actors_mentioned``. A violation logs a warning and
       drops the entry — the validator does NOT silently relocate the
       actor to its correct pool's sub-list. The agent must not move an
       actor across evidence levels; surface the violation so reviewers
       see it.
    3. Cross-tier duplicates are repaired with priority ``stated >
       reported > mentioned``: an ID claimed by a higher-priority tier
       is stripped from any lower-priority tier. A warning fires naming
       both tiers so reviewers can spot agent-side inconsistency.

    After repair, the partition invariant
    ``set(stated) | set(reported) | set(mentioned) == set(actor_ids)``
    holds by construction (``actor_ids`` is computed from that union),
    and pairwise-disjointness is asserted. A violation at the assertion
    is a programming error in this validator itself.

    The three pool arguments default to ``None`` for backward
    compatibility with smokes or tests that bypass the partition stage
    (the unified-list check still applies in that case; the pool-source
    layer becomes a no-op when all three pools are empty/None).
    """
    import copy as _copy

    if not perspective_analysis or not isinstance(perspective_analysis, dict):
        return perspective_analysis

    by_id = _build_source_index(final_sources)
    actor_index = _build_actor_index(canonical_actors)
    # Pool-membership lookups. Empty/None pools mean "no pool check"
    # (backward-compat for partition-stage-bypassed smokes).
    pool_indices: dict[str, set[str]] = {
        "stated": {
            a["id"] for a in (canonical_actors_stated or [])
            if isinstance(a, dict) and isinstance(a.get("id"), str)
        },
        "reported": {
            a["id"] for a in (canonical_actors_reported or [])
            if isinstance(a, dict) and isinstance(a.get("id"), str)
        },
        "mentioned": {
            a["id"] for a in (canonical_actors_mentioned or [])
            if isinstance(a, dict) and isinstance(a.get("id"), str)
        },
    }
    pools_present = any(pool_indices.values())

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

        # Filter each sub-list against canonical_actors[]: drop unknowns
        # (hallucinations, stale references, or aliased IDs that
        # disappeared post-merge) and per-tier duplicates. When the
        # per-tier pools are populated, additionally enforce the
        # pool-source consistency rule (an ID in cluster.stated must
        # come from canonical_actors_stated, etc.). Sub-list ordering
        # within each tier is preserved (insertion order from the agent).
        filtered_tiers: dict[str, list[str]] = {}
        for tier in _SUBLIST_TIERS:
            raw = cluster.get(tier)
            tier_list: list[str] = []
            seen_in_tier: set[str] = set()
            for aid in raw or []:
                if not isinstance(aid, str):
                    continue
                if aid in seen_in_tier:
                    continue
                if aid not in actor_index:
                    logger.warning(
                        "enrich_perspective_clusters: cluster %s "
                        "sub-list %r referenced unknown actor_id %r; "
                        "dropping",
                        cluster["id"],
                        tier,
                        aid,
                    )
                    continue
                if pools_present and aid not in pool_indices[tier]:
                    # Pool-source consistency violation: the agent placed
                    # an actor in a sub-list whose origin pool does not
                    # contain that actor. Drop and warn — do not silently
                    # relocate. Per the architecture, the pool of origin
                    # determines the sub-list of origin; this surfaces
                    # agent-side cross-pool drift.
                    in_pools = [
                        other for other in _SUBLIST_TIERS
                        if aid in pool_indices[other]
                    ]
                    logger.warning(
                        "enrich_perspective_clusters: cluster %s "
                        "sub-list %r contains actor_id %r which is not "
                        "in canonical_actors_%s (actually present in: "
                        "%s); dropping",
                        cluster["id"],
                        tier,
                        aid,
                        tier,
                        in_pools or ["none"],
                    )
                    continue
                tier_list.append(aid)
                seen_in_tier.add(aid)
            filtered_tiers[tier] = tier_list

        # Resolve cross-tier duplicates: priority stated > reported >
        # mentioned. An ID claimed by a higher-priority tier is stripped
        # from any lower-priority tier it also appears in. Warn naming
        # both tiers so reviewers can spot agent-side inconsistency.
        assigned_to: dict[str, str] = {}
        for tier in _SUBLIST_TIERS:
            kept: list[str] = []
            for aid in filtered_tiers[tier]:
                prior_tier = assigned_to.get(aid)
                if prior_tier is not None:
                    logger.warning(
                        "enrich_perspective_clusters: cluster %s actor "
                        "%r appears in both %r and %r; keeping in %r "
                        "(priority stated > reported > mentioned)",
                        cluster["id"],
                        aid,
                        prior_tier,
                        tier,
                        prior_tier,
                    )
                    continue
                kept.append(aid)
                assigned_to[aid] = tier
            filtered_tiers[tier] = kept

        # Compute the deterministic flat union — actor_ids is now derived,
        # not agent-emitted. Sorted for stable serialization across runs.
        actor_ids = sorted(assigned_to.keys())
        actor_ids_set = set(actor_ids)

        # Invariant: the three sub-lists partition actor_ids disjointly.
        # By construction (actor_ids is the union; cross-tier dedup
        # stripped overlaps), the union equals actor_ids and tiers are
        # pairwise disjoint. A violation here is a bug in this validator.
        _assert_partition_invariant(
            cluster["id"],
            filtered_tiers["stated"],
            filtered_tiers["reported"],
            filtered_tiers["mentioned"],
            actor_ids_set,
        )

        cluster["actor_ids"] = actor_ids
        cluster["stated"] = filtered_tiers["stated"]
        cluster["reported"] = filtered_tiers["reported"]
        cluster["mentioned"] = filtered_tiers["mentioned"]
        cluster["regions"] = sorted(regions_seen)
        cluster["languages"] = sorted(languages_seen)
        cluster["n_actors"] = len(actor_ids)
        cluster["n_sources"] = len(source_ids)
        cluster["n_regions"] = len(regions_seen)
        cluster["n_languages"] = len(languages_seen)

    return enriched


@topic_stage_def(
    reads=(
        "perspective_clusters",
        "final_sources",
        "canonical_actors",
        "canonical_actors_stated",
        "canonical_actors_reported",
        "canonical_actors_mentioned",
    ),
    writes=("perspective_clusters",),
)
async def enrich_perspective_clusters(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Attach deterministic enrichment fields to the raw cluster output
    written by PerspectiveStage. Runs immediately after the agent stage
    in both production and hydrated variants.

    Reads `perspective_clusters` (raw shape from PerspectiveStage:
    `[{position_label, position_summary, source_ids, stated, reported,
    mentioned}]`), `final_sources`, the unified `canonical_actors` (post
    alias-resolution), and the three evidence-partitioned pools written
    by `partition_canonical_actors_by_evidence`. Writes
    `perspective_clusters` enriched with `pc-NNN`, the three sub-lists
    cleaned against `canonical_actors` AND against the matching pool
    (pool-source consistency check), cross-tier-deduped, the derived
    flat `actor_ids` (the sorted union of cleaned sub-lists), regions,
    languages, and the count summary `n_actors / n_sources / n_regions
    / n_languages` computed against canonical-actor membership.

    The three pool slots may be empty (e.g. legacy smokes that bypass
    the partition stage); in that case the pool-source check becomes a
    no-op and the validator falls back to the unified-list check alone.

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
        canonical_actors_stated=list(topic_bus.canonical_actors_stated or []),
        canonical_actors_reported=list(topic_bus.canonical_actors_reported or []),
        canonical_actors_mentioned=list(topic_bus.canonical_actors_mentioned or []),
    )
    return topic_bus.model_copy(
        update={
            "perspective_clusters": list(
                enriched.get("position_clusters") or []
            )
        }
    )


# ---------------------------------------------------------------------------
# 13. mirror_perspective_synced  (universal — 1:1 copy after the Consolidator refactor)
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=("perspective_clusters",),
    writes=("perspective_clusters_synced",),
)
async def mirror_perspective_synced(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Per-element mirror per ARCH §3.3 (b). Runs once in both variants
    (after ``enrich_perspective_clusters``): the slot starts empty so
    the mirror produces a 1:1 copy of ``perspective_clusters``. Before
    the Consolidator refactor the hydrated variant ran this twice — the
    second pass merged ``PerspectiveSyncStage`` cluster deltas — but
    PerspectiveSync was removed and the second pass with it.
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
# 18. derive_mentioned_actors
# ---------------------------------------------------------------------------


# Fixed strings rendered into the bracket card. Module-level so the
# renderer and tests can refer to them without round-tripping the bus.
_MENTIONED_ACTORS_POSITION_LABEL: str = "Mentioned actors"
_MENTIONED_ACTORS_SUMMARY: str = (
    "Actors named in the corpus who are not grouped into any of the "
    "documented positions. Listed here for transparency about who "
    "appears in the source material."
)


def _derive_orphan_tier(actor: dict) -> str:
    """Tier derivation rule for non-cluster actors who lack an
    agent-assigned tier (because they sit outside every position
    cluster).

    Rule (per the mentioned-actors brief, 2026-05-21):
    - any `quotes[i].verbatim` non-empty → "stated"   (direct quote on record)
    - else any `quotes[i].position` non-empty → "reported"  (paraphrased)
    - else → "mentioned"                              (named without position)

    Note: this is independent of `quotes[i].evidence_type` — that field
    is emitted by Hydration-Phase-1 and feeds the per-evidence canonical
    actor pools, but the brief specifies the verbatim/position check
    explicitly so the rule stays interpretable from the rendered TP
    JSON alone (which omits `evidence_type` from agent quotes).
    """
    has_verbatim = False
    has_position = False
    for q in actor.get("quotes") or []:
        if not isinstance(q, dict):
            continue
        v = q.get("verbatim")
        if isinstance(v, str) and v.strip():
            has_verbatim = True
            break
        p = q.get("position")
        if isinstance(p, str) and p.strip():
            has_position = True
    if has_verbatim:
        return "stated"
    if has_position:
        return "reported"
    return "mentioned"


@topic_stage_def(
    reads=(
        "canonical_actors",
        "perspective_clusters_synced",
        "final_sources",
    ),
    writes=("mentioned_actors",),
)
async def derive_mentioned_actors(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Deterministic bracket for every non-cluster actor.

    Reads `canonical_actors[]`, `perspective_clusters_synced[]`, and
    `final_sources[]`. The rule is binary (2026-05-21 simplification —
    the prior ≥ 2-source structural-centrality floor was dropped): an
    actor qualifies for the bracket when their `id` is absent from
    every cluster's `actor_ids[]`. Every non-cluster actor regardless
    of source count is included.

    Qualifying actors get a tier assignment from `_derive_orphan_tier`.
    The bracket dict (see `mentioned_actors` slot docstring in
    `src/bus.py`) holds `position_label`, `summary`, the three tier
    sub-lists, the flat `actor_ids[]` (union, ordered stated → reported
    → mentioned and within each tier preserving canonical_actors
    emission order), the union `source_ids[]` (first-appearance order
    across included actors), and the `counts` dict (actors, sources,
    regions, languages).

    Region/language counts are derived against `final_sources[]` using
    the same `normalise_country` / `normalise_language` helpers the
    cluster-enrichment stage uses, so the count semantics match.

    When no non-cluster actor exists, the stage writes an empty bracket
    (`actor_ids=[]`, counts zero). The renderer treats both that and an
    absent slot as "section omitted entirely", so legacy / replay paths
    that bypass this stage render the page unchanged.
    """
    actors = list(topic_bus.canonical_actors or [])
    clusters = list(topic_bus.perspective_clusters_synced or [])
    sources = list(topic_bus.final_sources or [])

    # 1. Build the clustered-actor set.
    clustered_ids: set[str] = set()
    for c in clusters:
        if not isinstance(c, dict):
            continue
        for aid in c.get("actor_ids") or []:
            if isinstance(aid, str):
                clustered_ids.add(aid)

    # 2. Build source-id → source-record lookup for region/language.
    src_by_id: dict[str, dict] = {}
    for s in sources:
        if isinstance(s, dict):
            sid = s.get("id")
            if isinstance(sid, str) and sid:
                src_by_id[sid] = s

    # 3. Walk canonical_actors[] in order; collect qualifying orphans
    #    with their derived tier. Order within each tier preserves
    #    canonical_actors emission order.
    actors_by_tier: dict[str, list[str]] = {
        "stated": [],
        "reported": [],
        "mentioned": [],
    }
    qualifying_actors: list[dict] = []
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        aid = actor.get("id")
        if not isinstance(aid, str) or not aid:
            continue
        if aid in clustered_ids:
            continue
        tier = _derive_orphan_tier(actor)
        actors_by_tier[tier].append(aid)
        qualifying_actors.append(actor)

    # 4. Flat union: ordered stated → reported → mentioned.
    actor_ids: list[str] = (
        actors_by_tier["stated"]
        + actors_by_tier["reported"]
        + actors_by_tier["mentioned"]
    )

    # 5. Union source_ids across included actors, first-appearance order.
    source_ids: list[str] = []
    seen_sids: set[str] = set()
    regions_seen: set[str] = set()
    languages_seen: set[str] = set()
    for actor in qualifying_actors:
        for sid in actor.get("source_ids") or []:
            if not isinstance(sid, str) or not sid or sid in seen_sids:
                continue
            seen_sids.add(sid)
            source_ids.append(sid)
            src = src_by_id.get(sid)
            if not src:
                continue
            country = normalise_country(src.get("country"))
            language = normalise_language(src.get("language"))
            if country:
                regions_seen.add(country)
            if language:
                languages_seen.add(language)

    bracket = {
        "position_label": _MENTIONED_ACTORS_POSITION_LABEL,
        "summary": _MENTIONED_ACTORS_SUMMARY,
        "actors_stated": actors_by_tier["stated"],
        "actors_reported": actors_by_tier["reported"],
        "actors_mentioned": actors_by_tier["mentioned"],
        "actor_ids": actor_ids,
        "source_ids": source_ids,
        "counts": {
            "actors": len(actor_ids),
            "sources": len(source_ids),
            "regions": len(regions_seen),
            "languages": len(languages_seen),
        },
    }
    return topic_bus.model_copy(update={"mentioned_actors": bracket})


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
    - ``qa_corrected_article`` and ``writer_article`` (body/headline/
      subheadline/summary), via inline ``[src-NNN]`` citations

    ``merged_preliminary_divergences`` is intentionally NOT scanned. Both
    producer-side schemas (``HYDRATION_PHASE2_SCHEMA`` and
    ``RESEARCHER_ASSEMBLE_SCHEMA``) declare it as ``array of string``;
    items carry no ``source_ids[]``, so the scan can never harvest any
    ids — it was a dead hook that emitted a per-item warning for every
    (string) item.

    ``bias_language_findings`` is intentionally NOT scanned. The bias
    agent produces secondary commentary on the article, not
    source-authority, and empirically (verified on the 2026-05-11
    V1+V2 baselines) emits no inline ``[src-NNN]`` markers in its
    prose. Scanning it would create a circular dependency that
    prevents moving prune earlier in the topic chain (where
    ``bias_language_findings`` does not yet exist). The contract test
    ``test_bias_and_gaps_emit_no_inline_src_markers`` ensures a future
    prompt change reintroducing inline src-markers fails loudly.

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

    return referenced


@topic_stage_def(
    reads=(
        "final_sources",
        "perspective_clusters_synced",
        "writer_article",
        "qa_corrected_article",
        "qa_divergences",
        "merged_preliminary_divergences",
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
    ``merged_preliminary_divergences``, and the article bodies
    (``qa_corrected_article`` first, ``writer_article`` fallback) —
    see :func:`_collect_referenced_src_ids` for the full list.
    ``bias_language_findings`` is NOT scanned (secondary commentary,
    not source-authority; see ``_collect_referenced_src_ids``
    docstring). Content (summary, actors_quoted) is no longer a
    keep-reprieve: if the synthesis stack chose not to use a source,
    it is off-topic and drops out of the published TP.

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
            full_summary = (source.get("summary") or "").strip()
            summary_snippet = full_summary[:60]
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
                    "summary": full_summary,
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
# 19b. cleanup_stale_references
# ---------------------------------------------------------------------------


@topic_stage_def(
    reads=(
        "final_sources",
        "canonical_actors",
        "canonical_actors_stated",
        "canonical_actors_reported",
        "canonical_actors_mentioned",
        "actor_alias_mapping",
        "perspective_clusters_synced",
        "merged_preliminary_divergences",
        "merged_coverage_gaps",
        "qa_divergences",
    ),
    writes=(
        "canonical_actors",
        "canonical_actors_stated",
        "canonical_actors_reported",
        "canonical_actors_mentioned",
        "actor_alias_mapping",
        "perspective_clusters_synced",
        "merged_preliminary_divergences",
        "merged_coverage_gaps",
        "qa_divergences",
    ),
)
async def cleanup_stale_references(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Filter every actor, alias, perspective cluster, divergence, and
    coverage-gap entry whose source-id references no longer exist after
    ``prune_unused_sources_and_clusters``. Pure deterministic stage.

    Runs immediately after prune, before ``compute_source_balance``.
    Without this step, downstream stages compute against the pre-prune
    state and the rendered TP carries actors with stale ``source_ids``,
    alias entries pointing at dropped actors, and bias/balance counters
    that don't match ``len(final_sources)``.

    Filter rules (applied in dependency order):

    - ``canonical_actors[]``: filter ``source_ids[]`` and ``quotes[]``
      to entries referencing ``cited_src_ids``. Drop the actor entirely
      if ``source_ids[]`` becomes empty after filtering.
    - ``canonical_actors_stated / _reported / _mentioned``: drop any
      pool entry whose actor was dropped from ``canonical_actors[]``,
      or whose surviving filtered quotes no longer carry the pool's
      ``evidence_type``.
    - ``actor_alias_mapping[]``: drop entries where ``canonical_id``
      references an actor that no longer exists.
    - ``perspective_clusters_synced[]``: filter ``source_ids[]``
      against ``cited_src_ids``; filter ``actor_ids[]`` and the three
      pool sub-lists (``stated`` / ``reported`` / ``mentioned``)
      against surviving actor IDs; drop clusters whose
      ``source_ids[]`` becomes empty. ``prune`` already drops the
      narrower "both actor_ids and source_ids empty" case; this stage
      is stricter on the source_ids dimension, so a cluster with
      surviving actors but no surviving sources is dropped here.
    - ``merged_preliminary_divergences[]`` / ``merged_coverage_gaps[]``
      / ``qa_divergences[]``: filter any ``source_ids[]`` field
      against ``cited_src_ids``; drop entries whose source_ids list
      becomes empty.
    """
    final_sources = list(topic_bus.final_sources or [])
    cited_src_ids: set[str] = {
        s.get("id") for s in final_sources
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    cited_src_ids.discard("")

    # --- canonical_actors ----------------------------------------------------
    cleaned_actors: list[dict] = []
    surviving_actor_ids: set[str] = set()
    surviving_actor_evidence: dict[str, set[str]] = {}
    dropped_actor_count = 0
    for actor in topic_bus.canonical_actors or []:
        if not isinstance(actor, dict):
            cleaned_actors.append(actor)
            continue
        filtered_quotes: list[dict] = []
        filtered_evidence_types: set[str] = set()
        for q in actor.get("quotes") or []:
            if not isinstance(q, dict):
                continue
            sid = q.get("source_id")
            if isinstance(sid, str) and sid in cited_src_ids:
                filtered_quotes.append(q)
                et = q.get("evidence_type")
                if et in ("stated", "reported", "mentioned"):
                    filtered_evidence_types.add(et)
        filtered_src_ids = [
            sid for sid in (actor.get("source_ids") or [])
            if isinstance(sid, str) and sid in cited_src_ids
        ]
        if not filtered_src_ids:
            dropped_actor_count += 1
            continue
        new_actor = dict(actor)
        new_actor["source_ids"] = filtered_src_ids
        new_actor["quotes"] = filtered_quotes
        cleaned_actors.append(new_actor)
        aid = new_actor.get("id")
        if isinstance(aid, str):
            surviving_actor_ids.add(aid)
            # Surviving evidence_types include the partition default
            # ("reported" when missing) so the pool-membership filter
            # below mirrors partition_canonical_actors_by_evidence.
            if not filtered_evidence_types and filtered_quotes:
                filtered_evidence_types.add("reported")
            surviving_actor_evidence[aid] = filtered_evidence_types

    # --- canonical_actors_{stated,reported,mentioned} ------------------------
    def _filter_pool(pool: list, tier: str) -> list:
        out: list = []
        for entry in pool or []:
            if not isinstance(entry, dict):
                out.append(entry)
                continue
            aid = entry.get("id")
            if not isinstance(aid, str) or aid not in surviving_actor_ids:
                continue
            # Drop if the actor's surviving quotes no longer carry this tier.
            if tier not in surviving_actor_evidence.get(aid, set()):
                continue
            new_entry = dict(entry)
            new_entry["source_ids"] = [
                sid for sid in (entry.get("source_ids") or [])
                if isinstance(sid, str) and sid in cited_src_ids
            ]
            new_entry["quotes"] = [
                q for q in (entry.get("quotes") or [])
                if isinstance(q, dict)
                and q.get("source_id") in cited_src_ids
            ]
            out.append(new_entry)
        return out

    cleaned_stated = _filter_pool(topic_bus.canonical_actors_stated or [], "stated")
    cleaned_reported = _filter_pool(topic_bus.canonical_actors_reported or [], "reported")
    cleaned_mentioned = _filter_pool(topic_bus.canonical_actors_mentioned or [], "mentioned")

    # --- actor_alias_mapping -------------------------------------------------
    cleaned_aliases: list = []
    dropped_alias_count = 0
    for entry in topic_bus.actor_alias_mapping or []:
        if not isinstance(entry, dict):
            cleaned_aliases.append(entry)
            continue
        canonical_id = entry.get("canonical_id")
        if not isinstance(canonical_id, str) or canonical_id not in surviving_actor_ids:
            dropped_alias_count += 1
            continue
        cleaned_aliases.append(entry)

    # --- perspective_clusters_synced ----------------------------------------
    cleaned_clusters: list = []
    dropped_cluster_count = 0
    for cluster in topic_bus.perspective_clusters_synced or []:
        if not isinstance(cluster, dict):
            cleaned_clusters.append(cluster)
            continue
        filtered_src = [
            sid for sid in (cluster.get("source_ids") or [])
            if isinstance(sid, str) and sid in cited_src_ids
        ]
        if not filtered_src:
            dropped_cluster_count += 1
            continue
        filtered_actor_ids = [
            aid for aid in (cluster.get("actor_ids") or [])
            if isinstance(aid, str) and aid in surviving_actor_ids
        ]
        new_cluster = dict(cluster)
        new_cluster["source_ids"] = filtered_src
        new_cluster["actor_ids"] = filtered_actor_ids
        for sublist_key in ("stated", "reported", "mentioned"):
            sub = cluster.get(sublist_key)
            if isinstance(sub, list):
                new_cluster[sublist_key] = [
                    aid for aid in sub
                    if isinstance(aid, str) and aid in surviving_actor_ids
                ]
        cleaned_clusters.append(new_cluster)

    # --- divergence / gap slots ---------------------------------------------
    def _filter_src_id_collection(items: list, label: str) -> tuple[list, int]:
        kept: list = []
        dropped = 0
        for item in items or []:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            filtered = [
                sid for sid in (item.get("source_ids") or [])
                if isinstance(sid, str) and sid in cited_src_ids
            ]
            if not filtered:
                dropped += 1
                continue
            new_item = dict(item)
            new_item["source_ids"] = filtered
            kept.append(new_item)
        return kept, dropped

    cleaned_prelim_divs, dropped_prelim = _filter_src_id_collection(
        topic_bus.merged_preliminary_divergences or [], "merged_preliminary_divergences"
    )
    cleaned_gaps, dropped_gaps = _filter_src_id_collection(
        topic_bus.merged_coverage_gaps or [], "merged_coverage_gaps"
    )
    cleaned_qa_divs, dropped_qa_divs = _filter_src_id_collection(
        topic_bus.qa_divergences or [], "qa_divergences"
    )

    logger.info(
        "cleanup_stale_references: dropped %d actor(s), %d alias(es), %d "
        "cluster(s), %d prelim-divergence(s), %d gap(s), %d qa-divergence(s) "
        "(post-prune cited_src_ids=%d)",
        dropped_actor_count,
        dropped_alias_count,
        dropped_cluster_count,
        dropped_prelim,
        dropped_gaps,
        dropped_qa_divs,
        len(cited_src_ids),
    )

    return topic_bus.model_copy(
        update={
            "canonical_actors": cleaned_actors,
            "canonical_actors_stated": cleaned_stated,
            "canonical_actors_reported": cleaned_reported,
            "canonical_actors_mentioned": cleaned_mentioned,
            "actor_alias_mapping": cleaned_aliases,
            "perspective_clusters_synced": cleaned_clusters,
            "merged_preliminary_divergences": cleaned_prelim_divs,
            "merged_coverage_gaps": cleaned_gaps,
            "qa_divergences": cleaned_qa_divs,
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
            # evidence_type is emitted by Hydration-Phase-1 per the
            # extraction-time classification (stated / reported /
            # mentioned). Thread it through onto the source's
            # actors_quoted entry so consolidate_actors downstream
            # picks it up; the partition stage relies on this.
            evidence_type = actor.get("evidence_type")
            if evidence_type not in ("stated", "reported", "mentioned"):
                evidence_type = None
            actors_out.append(
                {
                    "name": actor.get("name", ""),
                    "role": actor.get("role", ""),
                    "type": actor.get("type", ""),
                    "position": actor.get("position", ""),
                    "evidence_type": evidence_type,
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
    "cleanup_stale_references",
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
    "partition_canonical_actors_by_evidence",
    "propagate_outlet_metadata",
    "prune_unused_sources_and_clusters",
    "renumber_sources",
    "derive_mentioned_actors",
]
