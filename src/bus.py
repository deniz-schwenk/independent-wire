"""V2 Bus schemas — RunBus, TopicBus, sub-models, read-only proxy, is_empty helper.

Authoritative reference: docs/ARCH-V2-BUS-SCHEMA.md Section 4. Slot inventory,
owners, visibility, mirrors_from, and mirror_granularity all trace back to that
document. The Pydantic schema in this module is the runtime source of truth;
the doc tables are explanatory.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo

VisibilityTag = Literal["tp", "mcp", "rss", "internal"]
MirrorGranularity = Literal["slot", "element"]

_ALLOWED_VISIBILITIES: frozenset[str] = frozenset({"tp", "mcp", "rss", "internal"})

_MISSING = object()


def Slot(
    default: Any = _MISSING,
    *,
    visibility: list[VisibilityTag] | VisibilityTag,
    mirrors_from: Optional[str] = None,
    mirror_granularity: Optional[MirrorGranularity] = None,
    optional_write: bool = False,
    default_factory: Optional[Callable[[], Any]] = None,
    description: Optional[str] = None,
) -> FieldInfo:
    """Field wrapper attaching Bus schema metadata to a Pydantic field.

    The metadata lives in `json_schema_extra` so it is discoverable at runtime
    via `Model.model_fields[name].json_schema_extra`.

    `optional_write=True` marks a slot whose owning stage may legitimately
    leave it at its typed empty default. The post-condition validator in
    `src/stage.py` skips the non-empty check for such slots — analogous to
    the mirror-target exception, but the rationale is "this slot can have
    no content yet" (e.g. previous_coverage on the first-ever run) rather
    than "a later mirror stage will fill it".
    """
    if isinstance(visibility, str):
        viz_list: list[str] = [visibility]
    else:
        viz_list = list(visibility)
    for v in viz_list:
        if v not in _ALLOWED_VISIBILITIES:
            raise ValueError(f"unknown visibility tag: {v!r}")
    if mirrors_from is not None and mirror_granularity is None:
        raise ValueError("mirrors_from declared without mirror_granularity")
    if mirror_granularity is not None and mirrors_from is None:
        raise ValueError("mirror_granularity declared without mirrors_from")

    extra: dict[str, Any] = {"visibility": viz_list}
    if mirrors_from is not None:
        extra["mirrors_from"] = mirrors_from
        extra["mirror_granularity"] = mirror_granularity
    if optional_write:
        extra["optional_write"] = True

    field_kwargs: dict[str, Any] = {"json_schema_extra": extra}
    if description is not None:
        field_kwargs["description"] = description
    if default_factory is not None:
        if default is not _MISSING:
            raise ValueError("pass default OR default_factory, not both")
        field_kwargs["default_factory"] = default_factory
    elif default is not _MISSING:
        field_kwargs["default"] = default
    else:
        raise ValueError("Slot requires default or default_factory")
    return Field(**field_kwargs)


def is_empty(value: Any) -> bool:
    """Canonical empty-test for the empty-then-fill mirror pattern.

    Empty: None, "", [], {}, and Pydantic sub-models whose every field is empty.
    Not empty: 0, False, populated strings/lists/dicts/sub-models.

    The asymmetry between numeric/boolean falsiness and "empty" is deliberate —
    `0` and `False` are valid data, not absence-markers (Section 3.3).
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    if isinstance(value, BaseModel):
        return all(is_empty(getattr(value, name)) for name in value.__class__.model_fields)
    return False


# ---------------------------------------------------------------------------
# Sub-models (Section 4 single-object structured slots)
# ---------------------------------------------------------------------------


class _StrictSubModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditorAssignment(_StrictSubModel):
    """One row of `editor_assignments`; also the shape of `editor_selected_topic`.

    Field set traces to ARCH-V2 §4A.3 (LLM-emitted: title, priority,
    selection_reason, follow_up_to, follow_up_reason; Python-added: id,
    topic_slug) plus §4B.2's reference to `editor_selected_topic.raw_data`.
    """

    id: str = ""
    topic_slug: str = ""
    title: str = ""
    priority: int = 0
    selection_reason: str = ""
    follow_up_to: Optional[str] = None
    follow_up_reason: Optional[str] = None
    raw_data: dict = Field(default_factory=dict)


class WriterArticle(_StrictSubModel):
    """ARCH-V2 §4B.6."""

    headline: str = ""
    subheadline: str = ""
    body: str = ""
    summary: str = ""


class Correction(_StrictSubModel):
    """One QA correction entry. Field-order is load-bearing: Sonnet streams
    output in declared order, so `proposed_correction` (free text) must come
    before `correction_needed` (the boolean conclusion). The model writes
    its way to a verdict in the text before committing to the flag.
    """

    proposed_correction: str = ""
    correction_needed: bool = False


class SourceBalance(_StrictSubModel):
    """ARCH-V2 §4B.11."""

    by_country: dict = Field(default_factory=dict)
    by_language: dict = Field(default_factory=dict)
    represented: list = Field(default_factory=list)
    missing_from_dossier: list = Field(default_factory=list)


class HydrationPreDossier(_StrictSubModel):
    """ARCH-V2 §4B.2."""

    sources: list = Field(default_factory=list)
    preliminary_divergences: list = Field(default_factory=list)
    coverage_gaps: list = Field(default_factory=list)


class ResearcherAssembleDossier(_StrictSubModel):
    """ARCH-V2 §4B.3."""

    sources: list = Field(default_factory=list)
    preliminary_divergences: list = Field(default_factory=list)
    coverage_gaps: list = Field(default_factory=list)


class HydrationPhase2Corpus(_StrictSubModel):
    """ARCH-V2 §4B.2."""

    preliminary_divergences: list = Field(default_factory=list)
    coverage_gaps: list = Field(default_factory=list)


class TransparencyCard(_StrictSubModel):
    """ARCH-V2 §4B.11. `pipeline_run` is `{run_id, date}` per the doc.

    `dropped_sources` and `dropped_clusters` surface the strict-drop
    decisions made by `prune_unused_sources_and_clusters` so readers can
    see why a TP's `final_sources[].id` sequence has gaps. Both arrays
    are present-but-empty when nothing was dropped.
    """

    selection_reason: str = ""
    pipeline_run: dict = Field(default_factory=dict)
    article_original: Optional[WriterArticle] = None
    qa_problems_found: list = Field(default_factory=list)
    qa_corrections: list[Correction] = Field(default_factory=list)
    dropped_sources: list = Field(default_factory=list)
    dropped_clusters: list = Field(default_factory=list)


# ---------------------------------------------------------------------------
# RunBus — 11 slots across 3 phases (ARCH-V2 §4A)
# ---------------------------------------------------------------------------


class _RunBusFields(BaseModel):
    """Shared field definitions for the mutable RunBus and the frozen RunBusReadOnly."""

    # 4A.1 Pipeline metadata (6 slots)
    run_id: str = Slot("", visibility=["tp", "mcp", "internal"])
    run_date: str = Slot("", visibility=["tp", "mcp", "internal"])
    run_variant: str = Slot("", visibility="internal")
    max_produce: int = Slot(
        3,
        visibility="internal",
        description=(
            "Number of TopicBuses this run intends to dispatch. "
            "Default 3 — the meaningful production-fleet default. "
            "Populated by init_run from the --max-produce CLI flag."
        ),
    )
    run_stage_log: list = Slot(default_factory=list, visibility="internal")
    run_topic_manifest: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )

    # 4A.2 Curator phase (3 slots)
    curator_findings: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )
    curator_topics_unsliced: list = Slot(default_factory=list, visibility="internal")
    curator_topics: list = Slot(default_factory=list, visibility="internal")

    # 4A.3 Editor phase (2 slots — including previous_coverage as the 11th run-scoped slot)
    previous_coverage: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )
    editor_assignments: list = Slot(default_factory=list, visibility="internal")

    # Selection phase (1 slot — written by select_topics, read by the runner
    # to instantiate one TopicBus per entry). Not part of ARCH §4A's
    # documented inventory but required by ARCH §5.1 stage 4 to communicate
    # the trimmed/sorted subset to the runner without overwriting
    # editor_assignments.
    selected_assignments: list = Slot(default_factory=list, visibility="internal")


class RunBus(_RunBusFields):
    """Mutable RunBus written by run-stages."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    def as_readonly(self) -> "RunBusReadOnly":
        """Construct a deep-copied frozen proxy.

        Inner mutables (lists, dicts, sub-models) are deep-copied so in-place
        mutation on the proxy does not propagate back to the original RunBus.
        Field assignment on the proxy raises Pydantic ValidationError.
        """
        return RunBusReadOnly.model_validate(copy.deepcopy(self.model_dump()))


class RunBusReadOnly(_RunBusFields):
    """Frozen read-only RunBus proxy. Constructed via `RunBus.as_readonly()`."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# TopicBus — 27 slots across 11 phases (ARCH-V2 §4B.1–§4B.11)
# ---------------------------------------------------------------------------


class TopicBus(BaseModel):
    """Topic-scoped state for the production of one Topic Package."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # 4B.1 Topic identity (1 slot)
    editor_selected_topic: EditorAssignment = Slot(
        default_factory=EditorAssignment,
        visibility="internal",
    )

    # 4B.2 Hydration phase — hydrated variant only (5 slots)
    hydration_urls: list = Slot(default_factory=list, visibility="internal")
    hydration_fetch_results: list = Slot(default_factory=list, visibility="internal")
    hydration_phase1_analyses: list = Slot(default_factory=list, visibility="internal")
    hydration_phase2_corpus: HydrationPhase2Corpus = Slot(
        default_factory=HydrationPhase2Corpus,
        visibility="internal",
    )
    hydration_pre_dossier: HydrationPreDossier = Slot(
        default_factory=HydrationPreDossier,
        visibility="internal",
    )

    # 4B.3 Researcher phase (3 slots)
    researcher_plan_queries: list = Slot(default_factory=list, visibility="internal")
    researcher_search_results: list = Slot(default_factory=list, visibility="internal")
    researcher_assemble_dossier: ResearcherAssembleDossier = Slot(
        default_factory=ResearcherAssembleDossier,
        visibility="internal",
    )

    # 4B.4 Source merge and renumbering (5 slots)
    merged_sources_pre_renumber: list = Slot(default_factory=list, visibility="internal")
    final_sources: list = Slot(
        default_factory=list,
        visibility=["tp", "mcp"],
        description=(
            "Canonical source list referenced everywhere downstream. "
            "Each entry is a dict carrying at least `id`, `outlet`, "
            "`title`, `url`, `language`, `country`, `summary`, "
            "`actors_quoted[]`. Three optional fields populated by "
            "`propagate_outlet_metadata` when the outlet appears in "
            "`config/sources.json`: `tier` (1-4 or None), "
            "`editorial_independence` "
            "(independent / publicly_funded_autonomous / state_directed / "
            "state_influenced or None), `bias_note` (free text or None). "
            "Researcher-hydrated third-party citations leave the three "
            "fields at None — the renderer surfaces a 'not yet "
            "categorized' indicator."
        ),
    )
    id_rename_map: dict = Slot(default_factory=dict, visibility="internal")
    merged_preliminary_divergences: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )
    merged_coverage_gaps: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )

    # 4B.4b Actor consolidation (1 slot). Written by `consolidate_actors`
    # — flattens all `final_sources[].actors_quoted[]` into a single
    # deduped list keyed by `actor-NNN`. Exact-string-match dedup only;
    # the same real-world entity under multilingual or paraphrased name
    # variants appears as multiple entries here. The cross-variant
    # alias resolver `ResolveActorAliasesStage` runs after this stage
    # and produces the consumer-facing `canonical_actors[]` slot below.
    #
    # **Read/write contract (Phase 2 of TASK-RESOLVE-ACTOR-ALIASES):**
    # - Writers: `consolidate_actors` populates this slot.
    # - Readers (behavior code): NONE. All consumers read
    #   `canonical_actors[]` instead. This slot is audit-only post
    #   Phase 2 — kept in the rendered TP JSON as the pre-resolution
    #   snapshot, parallel to the `transparency.dropped_sources[]`
    #   audit pattern from §7.1 (Strict-drop and source ID gaps).
    final_actors: list = Slot(
        default_factory=list,
        visibility=["tp", "mcp"],
        optional_write=True,
    )

    # 4B.4c Actor alias resolution (2 slots). Written by
    # `ResolveActorAliasesStage` — runs after `consolidate_actors` and
    # before `PerspectiveStage`. The Flash-driven agent identifies
    # actors whose `name` field is a variant of the same real-world
    # entity (cross-language, cross-translation, cross-phrasing). The
    # stage applies first-source-wins canonical selection (smaller
    # numeric ID wins) deterministically and produces:
    #
    # - `canonical_actors[]`: merged actor records mirroring the
    #   `final_actors[]` shape plus `is_anonymous: bool`. Aliased IDs
    #   disappear (gaps in the numeric sequence are intentional —
    #   parallel to the source strict-drop pattern in §7.1; the
    #   actor-side §7.2 documents the same dual-list design).
    # - `actor_alias_mapping[]`: audit trail of every merge decision,
    #   `[{alias_id, alias_name, canonical_id}]`. Empty array when no
    #   merges. Connects pre- (`final_actors[]`) and post-
    #   (`canonical_actors[]`) state for transparency-curious readers.
    #
    # **Read/write contract (Phase 2):** `canonical_actors[]` is the
    # consumer-facing actor slot. `PerspectiveStage`,
    # `enrich_perspective_clusters`, `WriterStage`, `BiasLanguageStage`,
    # the Actors-section render, and the Sources-section actor-refs all
    # read from this slot. `final_actors[]` is audit-only.
    #
    # `optional_write=True` — smoke runs that bypass the resolver leave
    # both slots at their typed empty defaults.
    canonical_actors: list = Slot(
        default_factory=list,
        visibility=["tp", "mcp"],
        optional_write=True,
    )
    actor_alias_mapping: list = Slot(
        default_factory=list,
        visibility=["tp", "mcp"],
        optional_write=True,
    )

    # 4B.4d Evidence-partitioned canonical-actor pools (3 slots).
    # Written by `partition_canonical_actors_by_evidence` — runs after
    # `resolve_actor_aliases` and before `PerspectiveStage`. The
    # deterministic stage walks every canonical actor's `quotes[]` and
    # splits the population into three pools by the per-quote
    # `evidence_type` (`stated` / `reported` / `mentioned`) that
    # Hydration-Phase-1 emits at extraction time.
    #
    # An actor appears in a pool only if at least one of their quotes
    # carries the matching `evidence_type`. The pool entry mirrors the
    # canonical_actor shape (`id`, `name`, `role`, `type`,
    # `is_anonymous`) but filters `quotes[]` and `source_ids[]` to the
    # subset matching that evidence_type. An actor with cross-form
    # coverage in the dossier therefore appears in more than one pool,
    # each entry holding the quote subset of the matching form.
    #
    # **Read/write contract:** `PerspectiveStage` reads the three pools
    # (not `canonical_actors[]`) and assigns cluster membership
    # pool-by-pool — the sub-list of origin equals the pool of origin.
    # `enrich_perspective_clusters` validates that every ID in a
    # cluster's `stated` sub-list appears in `canonical_actors_stated`,
    # and analogously for `reported` / `mentioned`. All other consumers
    # (Renderer, Bias-Card, Writer) continue to read the unified
    # `canonical_actors[]` slot.
    #
    # `optional_write=True` — smoke runs that bypass the partition stage
    # leave all three slots at their typed empty defaults.
    canonical_actors_stated: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )
    canonical_actors_reported: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )
    canonical_actors_mentioned: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )

    # 4B.5 Perspective phase (2 slots). perspective_clusters is written
    # twice: PerspectiveStage emits raw clusters, then enrich_perspective_
    # clusters (deterministic) attaches pc-NNN, actors, regions, languages,
    # representation. optional_write=True covers the case where the agent
    # produced no clusters (empty list passes both writes through).
    #
    # Each cluster element carries: `position_label`, `position_summary`,
    # `source_ids` (`src-NNN` references into `final_sources`), and the
    # three-level actor classification — `stated`, `reported`, and
    # `mentioned`, the disjoint sub-lists agent-emitted and validated by
    # enrich_perspective_clusters. The flat `actor_ids[]` field is
    # **derived** by enrich_perspective_clusters as the sorted union of
    # the three cleaned sub-lists (not agent-emitted); every entry in
    # `actor_ids` appears in exactly one of the three sub-lists by
    # construction. The sub-lists carry the evidentiary tier of each
    # actor's relationship to the cluster's position: `stated` = the
    # actor's own words; `reported` = sources describe the actor as
    # holding the position; `mentioned` = the actor's actions align with
    # the position without statement or third-party attribution.
    # enrich_perspective_clusters drops unknown actor IDs, dedupes
    # within and across tiers (priority stated > reported > mentioned),
    # and asserts the pairwise-disjoint partition invariant.
    perspective_clusters: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )
    perspective_missing_positions: list = Slot(default_factory=list, visibility="internal")

    # 4B.6 Writer phase (1 slot)
    writer_article: WriterArticle = Slot(
        default_factory=WriterArticle,
        visibility="internal",
    )

    # 4B.7 QA+Fix phase (4 slots; qa_corrected_article is a slot-level mirror).
    # The three list slots carry optional_write=True — on clean runs the V2 QA
    # prompt produces empty arrays for all three (no problems → no corrections,
    # and divergences are scoped to cross-source disagreements which can also
    # be absent). qa_corrected_article uses the mirror exception instead.
    qa_problems_found: list = Slot(
        default_factory=list,
        visibility=["tp", "mcp"],
        optional_write=True,
    )
    qa_corrections: list[Correction] = Slot(
        default_factory=list,
        visibility=["tp", "mcp"],
        optional_write=True,
    )
    qa_corrected_article: WriterArticle = Slot(
        default_factory=WriterArticle,
        visibility=["tp", "mcp", "rss"],
        mirrors_from="writer_article",
        mirror_granularity="slot",
    )
    qa_divergences: list = Slot(
        default_factory=list,
        visibility=["tp", "mcp"],
        optional_write=True,
    )

    # 4B.8 Perspective-Sync phase — per-element mirror (1 slot).
    # Each cluster element mirrors the shape documented on
    # `perspective_clusters` above: `position_label`,
    # `position_summary`, `source_ids`, the three sub-lists `stated` /
    # `reported` / `mentioned`, and the derived flat `actor_ids[]`. In
    # hydrated, perspective_sync emits `position_cluster_updates` with
    # merged `position_label` / `position_summary` text; the sub-lists
    # and derived `actor_ids[]` pass through unchanged from the upstream
    # `perspective_clusters` slot.
    perspective_clusters_synced: list = Slot(
        default_factory=list,
        visibility=["tp", "mcp"],
        mirrors_from="perspective_clusters",
        mirror_granularity="element",
    )

    # 4B.9 Bias Detector phase (2 slots)
    bias_language_findings: list = Slot(default_factory=list, visibility=["tp", "mcp"])
    bias_reader_note: str = Slot("", visibility=["tp", "mcp"])

    # 4B.10 Coverage gaps (1 slot)
    coverage_gaps_validated: list = Slot(default_factory=list, visibility=["tp", "mcp"])

    # 4B.10b Strict-drop staging slots written by
    # `prune_unused_sources_and_clusters` and read by
    # `compose_transparency_card`. Internal because they're surfaced to
    # readers via `transparency_card.dropped_{sources,clusters}` instead.
    prune_dropped_sources: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )
    prune_dropped_clusters: list = Slot(
        default_factory=list,
        visibility="internal",
        optional_write=True,
    )

    # 4B.11 Source balance and rendered transparency (2 slots)
    source_balance: SourceBalance = Slot(
        default_factory=SourceBalance,
        visibility=["tp", "mcp"],
    )
    transparency_card: TransparencyCard = Slot(
        default_factory=TransparencyCard,
        visibility=["tp", "mcp"],
    )


__all__ = [
    "EditorAssignment",
    "HydrationPhase2Corpus",
    "HydrationPreDossier",
    "MirrorGranularity",
    "ResearcherAssembleDossier",
    "RunBus",
    "RunBusReadOnly",
    "Slot",
    "SourceBalance",
    "TopicBus",
    "TransparencyCard",
    "VisibilityTag",
    "WriterArticle",
    "is_empty",
]
