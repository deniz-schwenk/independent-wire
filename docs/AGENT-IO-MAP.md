# Agent IO Map (V2)

## Grundprinzip (Deniz, Session 6)

> Für jeden Agent bestimmen: A) was braucht er, B) was soll er erzeugen. Den Rest leiten wir immer mit Python weiter. Wenn ein Agent "durchreicht", erzeugt er Tokens ohne Mehrwert.

The V2 architecture hardens this principle into structural enforcement. Each agent reads from declared input Bus slots, emits its agent-local output, and the agent-stage wrapper in `src/agent_stages.py` writes only the originary fields into the Bus. Pipeline-derived fields (IDs, slugs, dates, counts, source enrichment, citation rewriting) are computed by deterministic stages in `src/stages/topic_stages.py` (per-topic) or `src/stages/run_stages.py` (per-run).

A ✅ in the **Originär** column means only the LLM can produce the field (judgement, prose, classification). A ❌ would flag a leftover that should be moved to Python.

Each section also lists **the deterministic stages** that read or write related slots, so the data routing is fully traceable.

Last updated: 2026-05-05 (post-Researcher-Polish + Phase-0-Eval cleanup; latest commit 8f48804).

---

## 1. Curator (Gemini 3 Flash, run-stage, 1×/Run)

**Wrapper:** `src/agent_stages.py:CuratorStage`
**Reads:** `run_bus.curator_findings`
**Writes:** `run_bus.curator_topics_unsliced`, `run_bus.curator_topics`

### INPUT (after `fetch_findings` deterministic run-stage populates `curator_findings`)

```
{
  findings: [
    {id: "finding-N", title, source_name, summary?}
  ]
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `topics[].title` | ✅ | ✅ | Topic label (not headline) |
| `topics[].relevance_score` | ✅ | ✅ | 1-10 editorial judgement |
| `topics[].summary` | ✅ | ✅ | 1-3 sentences derived from input findings |
| `cluster_assignments[]` | ✅ | ✅ | Flat `int|null` array, length matches `findings`. Each entry is the topic-index that finding maps to (or null for unclustered). |

### Python adds (downstream of Curator, in `CuratorStage` wrapper before slot write)

| Field | Where computed |
| --- | --- |
| `topics[].source_ids` (e.g. `["finding-3","finding-7"]`) | `CuratorStage` rebuilds from `cluster_assignments` (collapses cluster_assignments per topic) |
| `topics[].geographic_coverage`, `languages`, `source_count`, `missing_regions`, `missing_languages`, `source_diversity`, `missing_perspectives` | `CuratorStage` enrichment helpers |

### Variants
- **Production:** `curator_topics_unsliced` is sliced to top-10 by `relevance_score` to produce `curator_topics` (Editor sees 10).
- **Hydrated:** identical Curator stage — diverges only at the `attach_hydration_urls_to_assignments` run-stage that runs between Editor and `select_topics`.

**Status:** ✅ Pass-through clean. No Python-derivable field in the LLM output. The Curator INSTRUCTIONS.md was sharpened in commit 8f48804 (STEPS step 5: explicit null-default; RULE 1: anchored to "concrete event, decision, conflict, or development").

---

## 2. Editor (Opus 4.6, run-stage, 1×/Run)

**Wrapper:** `src/agent_stages.py:EditorStage`
**Reads:** `run_bus.curator_topics`, `run_bus.previous_coverage`
**Writes:** `run_bus.editor_assignments`

### INPUT

```
{
  topics: [<Curator output, fully enriched>],
  previous_coverage: [{tp_id, date, headline, slug, summary}]   # last ~7 days
}
```

`previous_coverage` is populated at `init_run` time by a deterministic helper that scans `output/{date}/` directories.

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `[].title` | ✅ | ✅ | May refine the Curator title |
| `[].priority` | ✅ | ✅ | 0-10. 0 = rejected (kept in output for transparency) |
| `[].selection_reason` | ✅ | ✅ | Editorial reasoning. Forbidden from numeric/outlet-brand claims (Principle-1 fix). Cleaned via `strip_stale_quantifiers` helper at `compose_transparency_card` time. |
| `[].follow_up` | ✅ | ✅ | Reference to a `previous_coverage` entry when applicable. |
| `[].follow_up_reason` | ✅ | ✅ | Why this is a follow-up (when `follow_up` is set). |

### Python adds (downstream of Editor, in `EditorStage` wrapper)

| Field | Where computed |
| --- | --- |
| `[].id` | `EditorStage` derives from title slugification |
| `[].topic_slug` | `EditorStage` |
| `[].raw_data` | `EditorStage` carries forward Curator's source_ids + (in hydrated) hydration_urls |

**Status:** ✅ Pass-through clean.

---

## 3. attach_hydration_urls_to_assignments — deterministic run-stage (hydrated only)

**Function:** `src/stages/run_stages.py:attach_hydration_urls_to_assignments`
**Reads:** `run_bus.editor_assignments`, `run_bus.curator_topics_unsliced`
**Writes:** `run_bus.editor_assignments[].raw_data.hydration_urls` (in-place mutation)

For each editor assignment, walks `curator_topics_unsliced` to find the matching cluster (by token overlap on title), reads the cluster's source URLs from underlying findings, and attaches them to the assignment under `raw_data.hydration_urls`. This is a **run-stage** — it operates on the full assignments list (cross-topic), not on a single TopicBus.

Helpers in `src/stages/run_stages.py`: `_hydration_tokens`, `_match_cluster`, `_load_country_lookup`, `_build_hydration_urls_for_cluster`.

Production variant skips this stage entirely — the production stage list does not include it.

---

## 4. select_topics — deterministic run-stage

**Function:** `src/stages/run_stages.py:select_topics`
**Reads:** `run_bus.editor_assignments`, `run_bus.max_produce`
**Writes:** populates the list of selected assignments that the runner will instantiate as TopicBuses

Sorts `editor_assignments` by priority desc, takes top `max_produce` (default 3), and produces the list. The runner then instantiates one TopicBus per selected assignment with `editor_selected_topic` populated.

---

## 5. Hydration phase 1 — `hydration_aggregator_phase1` (Gemini 3 Flash, topic-stage, hydrated only)

**Wrapper:** `src/agent_stages.py:HydrationPhase1Stage`
**Reads:** `topic_bus.hydration_fetch_results` (filtered to `status="success"`)
**Writes:** `topic_bus.hydration_phase1_analyses`

### INPUT

Successful fetch records: `[{url, title, outlet, language, country, extracted_text, ...}]`. The wrapper splits articles into chunks of 5–10 (`ceil(N/10)` chunks), runs phase-1 calls in parallel via `asyncio.gather`, and retries up to 2 times per chunk re-requesting only missing indices.

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `article_analyses[].article_index` | ✅ | ✅ | Chunk-local index (re-mapped to global by Python in `_merge_phase1_results`) |
| `article_analyses[].summary` | ✅ | ✅ | Per-article extraction |
| `article_analyses[].actors_quoted[]` | ✅ | ✅ | Five-field actor: `{name, role, type, position, verbatim_quote}`. Type validated against `_ACTOR_TYPE_ENUM` (10 values) by Python. |

### Python adds (in `HydrationPhase1Stage` wrapper, internalised from V1 `hydration_aggregator.py` in V2-11a)

| Step | Where computed |
| --- | --- |
| Chunk distribution | `_distribute_chunks` (private helper in `src/agent_stages.py`) |
| Per-article preparation | `_prepare_article` |
| Phase-1 call wrapper | `_call_phase1` |
| Output validation (Rule 1, Rule 6) | `_validate_phase1_output` |
| Cross-chunk index re-mapping | `_merge_phase1_results` |

**Status:** ✅ Pass-through clean. Counting and indexing are entirely deterministic.

---

## 6. Hydration phase 2 — `hydration_aggregator_phase2` (Opus 4.6, topic-stage, hydrated only)

**Wrapper:** `src/agent_stages.py:HydrationPhase2Stage`
**Reads:** `topic_bus.hydration_phase1_analyses`, `topic_bus.hydration_fetch_results` (for metadata)
**Writes:** `topic_bus.hydration_phase2_corpus`

### INPUT

```
{
  assignment: {title, selection_reason},
  article_analyses: [<phase 1 output>],
  article_metadata: [{article_index, language, country, outlet}]   # built by Python
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `preliminary_divergences[]` | ✅ | ✅ | Cross-corpus contradictions, framing differences |
| `coverage_gaps[]` | ✅ | ✅ | Pre-research gap statements (validated against final source pool downstream by `validate_coverage_gaps_stage`) |

### Python adds

| Step | Where computed |
| --- | --- |
| `article_metadata` input | `_build_article_metadata` (private helper in `src/agent_stages.py`) |
| Phase-2 call wrapper | `_run_phase2_reducer` |

**Status:** ✅ Pass-through clean.

---

## 7. assemble_hydration_dossier — deterministic topic-stage (hydrated only)

**Function:** `src/stages/topic_stages.py:assemble_hydration_dossier`
**Reads:** `topic_bus.hydration_phase1_analyses`, `topic_bus.hydration_phase2_corpus`, `topic_bus.hydration_fetch_results`
**Writes:** `topic_bus.hydration_pre_dossier`

Combines phase 1 + phase 2 + fetch metadata into the pre-research dossier. Each source carries `hydrate-rsrc-NNN` IDs (later renumbered to `src-NNN` by `renumber_sources`). Calls the V2-11a-internalised `_build_coverage_summary` helper to populate the coverage statistics consumed by the hydrated researcher planner.

---

## 8. Researcher Plan (Gemini 3 Flash, topic-stage)

**Production wrapper:** `src/agent_stages.py:ResearcherPlanStage`
**Hydrated wrapper:** `src/agent_stages.py:ResearcherHydratedPlanStage`
**Reads:** `topic_bus.editor_selected_topic`, plus (hydrated only) `topic_bus.hydration_pre_dossier`
**Writes:** `topic_bus.researcher_plan_queries`

The two wrappers differ only in input — hydrated reads the pre-dossier coverage summary to drive gap-aware queries; production plans cold from the assignment alone.

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `queries[].query` | ✅ | ✅ | Search query string |
| `queries[].language` | ✅ | ✅ | ISO language code for the query |

**Status:** ✅ Pass-through clean.

---

## 9. researcher_search — deterministic topic-stage

**Function:** `src/stages/topic_stages.py:make_researcher_search` (factory taking a `web_search_tool`)
**Reads:** `topic_bus.researcher_plan_queries`
**Writes:** `topic_bus.researcher_search_results`

Executes each query via the registered web-search tool (Brave Search in production), deduplicates results across queries (`_deduplicate_search_results`), enriches with extracted URL dates (`_enrich_url_dates`, `_extract_date_from_url_local`).

The factory pattern is used because the `web_search_tool` is injected — tests pass a fake.

---

## 10. Researcher Assemble (Gemini 3 Flash, topic-stage)

**Wrapper:** `src/agent_stages.py:ResearcherAssembleStage`
**Reads:** `topic_bus.researcher_search_results`, `topic_bus.editor_selected_topic`
**Writes:** `topic_bus.researcher_assemble_dossier`

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `sources[].id` | ✅ | (transitional) | LLM-emitted IDs use `research-rsrc-NNN` form. Python reassigns to `src-NNN` in `renumber_sources` topic-stage. |
| `sources[].url, title, outlet, language, country` | ✅ | ✅ | Source metadata extracted from search results |
| `sources[].summary` | ✅ | ✅ | Per-source summary |
| `sources[].estimated_date` | ✅ | ✅ | Recency-aware (set to `None` if undeterminable) |
| `sources[].actors_quoted[]` | ✅ | ✅ | Five-field actor shape with `verbatim_quote: null` (web-snippets cannot reliably yield direct quotes) |
| `preliminary_divergences[]` | ✅ | ✅ | Cross-source contradictions |
| `coverage_gaps[]` | ✅ | ✅ | Gap statements |

**Status:** ✅ Pass-through clean (LLM-emitted `research-rsrc-NNN` IDs are normalised by Python downstream). `source.country` defaults to `'unknown'` (never null) per `assemble_hydration_dossier` defence-in-depth (commit 59f46fc).

---

## 11. merge_sources / renumber_sources / normalize_pre_research — deterministic topic-stages

**Functions:**
- `src/stages/topic_stages.py:merge_sources`
- `src/stages/topic_stages.py:renumber_sources`
- `src/stages/topic_stages.py:normalize_pre_research`

**`merge_sources`:** concatenates `hydration_pre_dossier.sources` (production: empty) and `researcher_assemble_dossier.sources` into `merged_sources_pre_renumber`. Also concatenates and dedupes the `preliminary_divergences[]` and `coverage_gaps[]` lists.

**`renumber_sources`:** assigns final `src-001`, `src-002`, ... `src-NNN` IDs via `_build_source_index` and `_rewrite_ids_in_value`. Populates `final_sources` (the canonical source list) and `id_rename_map` (dictionary from pre-renumber IDs to `src-NNN`).

**`normalize_pre_research`:** rewrites all `hydrate-rsrc-NNN` and `research-rsrc-NNN` references in `merged_preliminary_divergences` and `merged_coverage_gaps` to `src-NNN` via `id_rename_map`.

After these three stages, every downstream consumer sees only `src-NNN`. This is the **ID normalisation invariant** documented in `docs/ARCH-V2-BUS-SCHEMA.md` §7.

### prune_unused_sources_and_clusters — strict-drop deterministic topic-stage

**Function:** `src/stages/topic_stages.py:prune_unused_sources_and_clusters`
**Reads:** `topic_bus.final_sources`, `topic_bus.perspective_clusters_synced`,
  `topic_bus.qa_divergences`, `topic_bus.merged_preliminary_divergences`,
  `topic_bus.qa_corrected_article`, `topic_bus.writer_article`,
  `topic_bus.bias_language_findings`, `topic_bus.coverage_gaps_validated`
**Writes:** `topic_bus.final_sources`, `topic_bus.perspective_clusters_synced`

Drops sources whose IDs are not referenced anywhere downstream — body, clusters, divergences, gaps, bias findings. Reference set is computed by helper `_collect_referenced_src_ids` which scans every slot that may carry an `src-NNN` token (string-form `[src-NNN]` regex over article bodies and prose; structured `source_ids[]` over collection slots).

Drop rule (commit a8b40e3, strict): a source is dropped if its `id` is not in the reference set. No content-based reprieve — the previous heuristic kept any source with non-empty summary/actors_quoted, which let off-topic Researcher-Assembler-dumped findings survive.

Cluster drop rule unchanged: a cluster is dropped only when both `actors[]` and `source_ids[]` are empty.

Each drop logs an INFO line with id, outlet, and a 60-char summary snippet.

---

## 12. Perspective (Opus 4.6, topic-stage)

**Wrapper:** `src/agent_stages.py:PerspectiveStage`
**Reads:** `topic_bus.final_sources`, `topic_bus.merged_preliminary_divergences`, `topic_bus.merged_coverage_gaps`, `topic_bus.editor_selected_topic`
**Writes:** `topic_bus.perspective_clusters`, `topic_bus.perspective_missing_positions`

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `position_clusters[].id` | ✅ | ✅ | `pc-NNN` format, agent-emitted (V2 PerspectiveV2 schema) |
| `position_clusters[].position_label` | ✅ | ✅ | Short cluster label |
| `position_clusters[].position_summary` | ✅ | ✅ | Cluster prose |
| `position_clusters[].source_ids[]` | ✅ | ✅ | References to `src-NNN` IDs from `final_sources` |
| `position_clusters[].actors[]` | ✅ | ✅ | Actors aligned to this position cluster |
| `missing_positions[]` | ✅ | ✅ | Stakeholder voices the dossier could not source |

**Status:** ✅ Pass-through clean.

---

## 13. enrich_perspective_clusters — deterministic topic-stage

**Function:** `src/stages/topic_stages.py:enrich_perspective_clusters`
**Reads:** `topic_bus.perspective_clusters`, `topic_bus.final_sources`
**Writes:** `topic_bus.perspective_clusters` (in-place enrichment), `topic_bus.source_balance` (initial pass — finalised by `compute_source_balance`)

Attaches per-cluster `regions[]`, `languages[]`, and `representation` (proportional source share) to each cluster. Pure Python computation from `final_sources` + the cluster's declared `source_ids`.

Helper logic in `src/stages/topic_stages.py:_enrich_position_clusters_logic`.

---

## 14. mirror_perspective_synced — deterministic topic-stage (runs 1× production, 2× hydrated)

**Function:** `src/stages/topic_stages.py:mirror_perspective_synced`
**Reads:** `topic_bus.perspective_clusters`, `topic_bus.perspective_clusters_synced` (target)
**Writes:** `topic_bus.perspective_clusters_synced`

Empty-then-fill mirror, **per-element granularity** (per `docs/ARCH-V2-BUS-SCHEMA.md` §3.3 (b)). For each cluster in `perspective_clusters`: if a delta exists in `perspective_clusters_synced` (matched by `id`), apply delta fields on top of the source cluster. Otherwise copy source cluster verbatim.

The stage is **idempotent** — running it twice in hydrated (once after `enrich_perspective_clusters` for 1:1 fill, once after `perspective_sync` for delta merge) produces the correct final state. Logic in `src/stages/run_stages.py:mirror_stage` (the generic mirror engine that reads `mirrors_from` schema metadata).

---

## 15. Writer (Opus 4.6, topic-stage)

**Wrapper:** `src/agent_stages.py:WriterStage`
**Reads:** `topic_bus.final_sources`, `topic_bus.perspective_clusters_synced`, `topic_bus.perspective_missing_positions`, `topic_bus.merged_coverage_gaps`, `topic_bus.editor_selected_topic`
**Writes:** `topic_bus.writer_article`

### INPUT

The wrapper passes `final_sources` directly — Writer reads `src-NNN` IDs and emits `[src-NNN]` citations directly.

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `headline` | ✅ | ✅ | Article headline |
| `subheadline` | ✅ | ✅ | One-sentence summary |
| `body` | ✅ | ✅ | Article body. Citations inline as `[src-NNN]` referencing `final_sources` (post-V2-09e symmetric ID flow). |
| `summary` | ✅ | ✅ | Newsletter-grade short summary |
| `sources[].src_id` | ✅ | (transitional) | Schema field renamed from `rsrc_id` to `src_id` in V2-09e. WriterStage validates that emitted IDs match `final_sources`. |

**Status:** ✅ Pass-through clean. `[src-NNN]` symmetry with QA verified by V2-09e + V2-10c smoke (all 5 V2-10b bugs closed).

V2-09c2 disabled `tools=[web_search_tool]` for this agent to close `[web-N]` Bug-1 (Writer was citing search results bypassing the source pool). Writer now operates strictly within the dossier.

---

## 16. QA-Analyze (Sonnet 4.6, topic-stage)

**Wrapper:** `src/agent_stages.py:QaAnalyzeStage`
**Reads:** `topic_bus.writer_article`, `topic_bus.final_sources`, `topic_bus.perspective_clusters_synced`
**Writes:** `topic_bus.qa_problems_found`, `topic_bus.qa_corrections`, `topic_bus.qa_corrected_article`, `topic_bus.qa_divergences`

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `problems_found[]` | ✅ | ✅ | List of factual problems with article excerpt + explanation. Citations in `[src-NNN]` form symmetric with Writer (V2-09e). |
| `qa_corrections[]` | ✅ | ✅ | Each item is a Correction object: `{proposed_correction: str, correction_needed: bool}`. The list is 1:1 length-equal with `problems_found` by index. Schema declaration order is load-bearing — Sonnet streams in order. The `qa_corrected_article` field is emitted iff `any(c.correction_needed)`; when all corrections are retractions (all false), the article is omitted and the `mirror_qa_corrected` stage backfills from `writer_article`. Schema rename `qa_proposed_corrections` → `qa_corrections` in commit e2e7efd; `--reuse` on pre-rename snapshots requires manual migration. |
| `article` | ✅ (conditional) | ✅ | **Slot-level mirror semantics:** emitted only when `any(qa_corrections[i].correction_needed)`; omitted when all corrections are retractions (all false) or when `qa_corrections` is empty. `mirror_qa_corrected` fills from `writer_article` in the omit case. Citations in `[src-NNN]` form. Explanations in `problems_found` are constrained to one-to-three sentences (commit 813c4e4) and `max_tokens` lifted to 64000. |
| `divergences[]` | ✅ | ✅ | Cross-source factual disagreements identified by QA. References to source IDs already in `src-NNN` form. |

**Status:** ✅ Pass-through clean. Schema (`QA_ANALYZE_SCHEMA`) marks `article` as **optional** at the top level so strict-mode validation accepts outputs without an `article` field — the prerequisite for slot-level mirror semantics (§3.3 (a)).

---

## 17. mirror_qa_corrected — deterministic topic-stage

**Function:** `src/stages/topic_stages.py:mirror_qa_corrected`
**Reads:** `topic_bus.writer_article`, `topic_bus.qa_corrected_article`
**Writes:** `topic_bus.qa_corrected_article`

Empty-then-fill mirror, **slot-level granularity** (`§3.3 (a)`). If `qa_corrected_article` is empty (QA omitted it because all corrections were retractions, or because no problems were found), fill all four fields from `writer_article`. If non-empty (QA emitted a corrected article because at least one correction had `correction_needed: true`), keep as-is.

After this stage `qa_corrected_article` always has all four fields populated. Render layers read `qa_corrected_article` directly with no conditional fallback.

---

## 18. compute_source_balance / validate_coverage_gaps_stage — deterministic topic-stages

**Functions:**
- `src/stages/topic_stages.py:compute_source_balance`
- `src/stages/topic_stages.py:validate_coverage_gaps_stage` (delegates to `src/stages/_helpers.py:validate_coverage_gaps`)

**`compute_source_balance`:** aggregates `final_sources` into `{by_country: {}, by_language: {}, represented: [], missing_from_dossier: []}`. Country names normalised via `normalise_country` helper (USA → United States, UK → United Kingdom, etc.). Language codes normalised via `normalise_language`. None-filter applied to `missing_from_dossier`.

**`validate_coverage_gaps_stage`:** filters `merged_coverage_gaps` against the realised `source_balance` to drop gap statements empirically refuted by the final source pool (e.g. "no UK-language sources" when UK is present). Tokenisation-driven match via `_gap_tokens`.

---

## 19. Bias Language (Opus 4.6, topic-stage)

**Wrapper:** `src/agent_stages.py:BiasLanguageStage`
**Reads:** `topic_bus.qa_corrected_article` (NOT `writer_article` — V2 always reads the corrected version)
**Writes:** `topic_bus.bias_language_findings`, `topic_bus.bias_reader_note`

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `findings[].excerpt` | ✅ | ✅ | Quoted phrase from the article |
| `findings[].issue` | ✅ | ✅ | Type of linguistic bias |
| `findings[].explanation` | ✅ | ✅ | Why this is biased |
| `reader_note` | ✅ | ✅ | One-paragraph reader-facing note |

**Status:** ✅ Pass-through clean. Other bias dimensions (source, geographical, selection, framing) are derived at render time by `compose_bias_card` from existing slots — not separate agent calls. See `docs/ARCH-V2-BUS-SCHEMA.md` §4B.12.

---

## 20. Perspective-Sync (Opus 4.6, topic-stage, hydrated only)

**Wrapper:** `src/agent_stages.py:PerspectiveSyncStage`
**Reads:** `topic_bus.perspective_clusters` (the source slot, not the synced target), `topic_bus.qa_corrected_article`, `topic_bus.qa_problems_found`, `topic_bus.qa_proposed_corrections`
**Writes:** `topic_bus.perspective_clusters_synced` (delta-only — `mirror_perspective_synced` then merges)

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `cluster_updates[].id` | ✅ | ✅ | The `pc-NNN` ID of the cluster being updated |
| `cluster_updates[].position_label` (optional) | ✅ | ✅ | Only when changed |
| `cluster_updates[].position_summary` (optional) | ✅ | ✅ | Only when changed |

**Status:** ✅ Pass-through clean. **Per-element mirror semantics:** the agent emits only changed clusters with only changed fields. The downstream `mirror_perspective_synced` stage merges deltas onto the existing `perspective_clusters_synced` (which has been 1:1-filled by the first invocation of the same mirror stage post-`enrich_perspective_clusters`).

---

## 21. compose_transparency_card — deterministic topic-stage

**Function:** `src/stages/topic_stages.py:compose_transparency_card`
**Reads:** `topic_bus.editor_selected_topic`, `topic_bus.writer_article`, `topic_bus.qa_corrected_article`, `topic_bus.qa_problems_found`, `topic_bus.qa_corrections`, `run_bus.run_id`, `run_bus.run_date`
**Writes:** `topic_bus.transparency_card`

Aggregates the transparency block. `selection_reason` cleaned via `strip_stale_quantifiers` helper. `article_original` populated only if QA modified the article (mirror semantics: `qa_corrected_article != writer_article` element-wise). `pipeline_run` carries `run_id` and `date` from the read-only RunBus reference.

---

## 22. Render and finalize — deterministic post-run stages

**Render functions in `src/render.py`:**
- `render_tp_public(topic_bus, run_bus) -> dict` — default Topic Package on disk
- `render_mcp_response(topic_bus, run_bus) -> dict` — MCP server response shape
- `render_rss_entry(topic_bus, run_bus) -> dict` — RSS feed entry
- `render_internal_debug(topic_bus, run_bus) -> dict` — full debug snapshot, no filtering
- `compose_bias_card(topic_bus) -> dict` — multi-slot derived view (Vision §4B.12)

Render is selection. Filtering is generic via the schema-level `visibility` metadata (`tp`, `mcp`, `rss`, `internal`) on each Bus slot — see `src/bus.py` for the Pydantic model definitions.

**`finalize_run`** (`src/stages/run_stages.py:make_finalize_run`): writes the final `run_stage_log` and `run_topic_manifest` summary entries into the RunBus and persists the run state to disk under `output/{date}/_state/{run_id}/`.

---

## 23. Other deterministic helpers (no Bus interface)

These live in `src/stages/_helpers.py` and are called by the deterministic topic-stages above:

- `normalise_country(name)` — Country name normalisation. Backed by `_load_country_lookup` in `src/stages/run_stages.py`.
- `normalise_language(code)` — ISO language code normalisation.
- `validate_coverage_gaps(gaps, source_balance)` — Coverage-gap empirical validation logic.
- `strip_stale_quantifiers(text)` — Removes outdated numeric/outlet-brand quantifiers from selection reasons.
- `_gap_tokens(gap_text)` — Tokenisation for gap matching.

---

## 24. Schema-driven JSON enforcement

Every agent has its `output_schema` registered at agent-creation time in `scripts/run.py` (production) or `scripts/run.py:create_agents_hydrated` (hydrated). The schemas live in `src/schemas.py`:

- `CURATOR_SCHEMA`
- `EDITOR_SCHEMA`
- `RESEARCHER_PLAN_SCHEMA`
- `RESEARCHER_ASSEMBLE_SCHEMA`
- `PERSPECTIVE_SCHEMA`
- `WRITER_SCHEMA` (V2-09e: `sources[].src_id`)
- `QA_ANALYZE_SCHEMA` (V2: `article` optional; mirror semantics; `qa_corrections` renamed in e2e7efd; Correction shape: `{proposed_correction: str, correction_needed: bool}`)
- `BIAS_DETECTOR_SCHEMA`
- `HYDRATION_PHASE1_SCHEMA`
- `HYDRATION_PHASE2_SCHEMA`
- `PERSPECTIVE_SYNC_SCHEMA`

OpenRouter's `response_format` strict mode enforces schema compliance at decode time. Defense-in-depth: `_extract_dict` / `_extract_list` in `src/agent.py` provide fallback parsing for malformed responses (regex-strip, `json-repair` 4th-fallback). Any agent output that violates its schema raises a structured error — the runner does not silently accept partial output.

---

## 25. Outlet Registry and source enrichment

**Files:**
- `config/outlet_registry.json` — community-contributable mapping of `{hostname → {outlet, country}}`. 118 entries as of 2026-05-05.
- `src/outlet_registry.py` — `lookup_outlet(url)` with hostname normalisation; helper `register_outlet(hostname, outlet, country)`.

**Hydration enrichment** in `src/hydration.py:_hydrate_one`:
- After fetch, looks up the URL's hostname in the outlet registry.
- Sets `record["country"]` from registry; defaults to `"unknown"` (never null) if no match.
- Extracts `record["published_date"]` via three-tier fallback: trafilatura's metadata extraction → `Last-Modified` HTTP header → URL-pattern regex (`/YYYY/MM/DD/...` or `/YYYYMMDD/...`).

**`assemble_hydration_dossier`** consumes both fields and propagates them into the `final_sources` slot:
- `country` falls back to `"unknown"` (defence-in-depth) so a stale `--reuse` snapshot never propagates literal null.
- `estimated_date` is the raw `record.get("published_date")` value — may be absent on regional outlets without discoverable pubdates (legitimate; outlets such as Armenpress, ArmInfo, EVN Report do not surface metadata).

**Status:** The Hydrated variant achieves ~80-100% country coverage (registry lookup) and ~38-84% date coverage (depending on outlet mix per topic). Researcher-Assemble inherits the country-defaulting behaviour but emits dates only when reasonably extracted.

---

## Summary: data-routing principle

The V2 architecture makes data routing **structural rather than convention-based**:

- Every Bus slot has exactly one **owner** (declared in `src/bus.py`).
- Mirror-pattern slots have a `mirrors_from` schema attribute.
- Visibility-driven render uses schema metadata.
- Stage execution is logged in `run_bus.run_stage_log` with explicit `scope` (`"run"` or `"topic:{slug}"`).

When something doesn't work as expected, three probes:

1. **Which stage owns the slot?** Check the §X table above and `src/bus.py`.
2. **Did the stage actually run?** Check `run_bus.run_stage_log`.
3. **Is the slot's content originary or pass-through?** ✅ in this map = LLM-only; routing happens elsewhere.
