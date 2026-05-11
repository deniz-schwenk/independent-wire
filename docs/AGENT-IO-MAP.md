# Agent I/O Map

Pipeline-stage inventory mapping every V2 stage to its LLM configuration (for agent stages) and Bus I/O contract (for all stages). Authoritative against HEAD `345bdfb` on 2026-05-11.

Sources of truth: `src/runner/stage_lists.py` (stage order), `scripts/run.py` (agent registrations), `src/agent_stages.py` (wrapper reads/writes), `src/stages/run_stages.py` + `src/stages/topic_stages.py` (deterministic stages), `src/bus.py` (slot definitions), `src/schemas.py` (LLM output schemas).

## §1 Quick-Reference: LLM Configuration

| Agent | Model | Temp | Reasoning | max_tokens |
|---|---|---|---|---|
| curator | `google/gemini-3-flash-preview` | 0.2 | none | 64000 |
| editor | `anthropic/claude-opus-4.6` | 0.3 | none | default |
| researcher_plan | `anthropic/claude-opus-4.6` | 0.5 | none | default |
| researcher_assemble | `google/gemini-3-flash-preview` | 0.2 | none | default |
| resolve_actor_aliases | `google/gemini-3-flash-preview` | 1.0 | medium | 66000 |
| perspective | `anthropic/claude-opus-4.6` | 0.1 | none | default |
| writer | `anthropic/claude-opus-4.6` | 0.3 | none | default |
| qa_analyze | `anthropic/claude-sonnet-4.6` | 0.1 | none | 64000 |
| bias_language | `anthropic/claude-opus-4.6` | 0.1 | none | default |
| researcher_hydrated_plan | `anthropic/claude-opus-4.6` | 0.5 | none | 16384 |
| hydration_aggregator_phase1 | `deepseek/deepseek-v4-pro` | 0.3 | none | 32000 |
| hydration_aggregator_phase2 | `anthropic/claude-opus-4.6` | 0.1 | none | 32000 |
| perspective_sync | `anthropic/claude-opus-4.6` | 0.1 | none | default |

13 agents registered (`scripts/run.py::create_agents` + `create_agents_hydrated`). `hydration_aggregator_phase1` has a Flash fallback block commented out in `scripts/run.py` per TASK-EVIDENCE-TYPE-MIGRATION A3 — DeepSeek is the active production model. Two-file prompt convention: every agent has `agents/{name}/SYSTEM.md` + `INSTRUCTIONS.md`; researcher uses `PLAN-*.md` + `ASSEMBLE-*.md` and hydration uses `PHASE1-*.md` + `PHASE2-*.md`.

## §2 Pipeline I/O Map

Hydrated is treated as canonical. Stages that run in only one variant are flagged inline. The full ordered union is 35 unique stages (production: 27, hydrated: 34; `mirror_perspective_synced` counted once even though it dispatches twice in hydrated). Stage names are listed in dispatch order (hydrated first, then the one production-only stage placed at its production position).

### Run-stages

#### §2.1 init_run

- **Kind:** deterministic (Python)
- **Source:** `src/stages/run_stages.py::make_init_run`
- **Reads (Bus):** (none)
- **Writes (Bus):** `run_id`, `run_date`, `run_variant`, `max_produce`, `previous_coverage` — RunBus

#### §2.2 fetch_findings

- **Kind:** deterministic (Python)
- **Source:** `src/stages/run_stages.py::make_fetch_findings`
- **Reads (Bus):** `run_date` — RunBus
- **Writes (Bus):** `curator_findings` — RunBus, loaded from `raw/{run_date}/feeds.json`

#### §2.3 CuratorStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::CuratorStage`
- **Model:** `google/gemini-3-flash-preview`
- **Params:** temp=0.2, reasoning=none, max_tokens=64000
- **Prompt:** `agents/curator/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `curator_findings` — RunBus
- **Writes (Bus):**
  - `curator_topics_unsliced` — RunBus, full sorted cluster list
  - `curator_topics` — RunBus, top-N slice (default 10) for the Editor
- **Originarity check:**
  - Fields the LLM produces: clusters (`title`, `relevance_score`, `summary`) + per-finding `cluster_assignments`
  - Fields the wrapper merges in deterministically: outlet/url/source_name reattached from `curator_findings` via `_rebuild_curator_source_ids` + `_enrich_curator_output` (source IDs known upstream are mapped back to raw finding records).

#### §2.4 EditorStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::EditorStage`
- **Model:** `anthropic/claude-opus-4.6`
- **Params:** temp=0.3, reasoning=none, max_tokens=default
- **Prompt:** `agents/editor/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `curator_topics`, `previous_coverage` — RunBus
- **Writes (Bus):** `editor_assignments` — RunBus
- **Originarity check:**
  - Fields the LLM produces: `title`, `priority`, `selection_reason`, `follow_up_to`, `follow_up_reason`
  - Fields the wrapper merges in deterministically: `id` (`tp-{date}-NNN`), `topic_slug`, `raw_data` (re-attached from the Curator-side cluster via title/slug match in `_attach_raw_data_from_curated`).

#### §2.5 attach_hydration_urls_to_assignments (hydrated-only)

- **Kind:** deterministic (Python)
- **Source:** `src/stages/run_stages.py::make_attach_hydration_urls_to_assignments`
- **Reads (Bus):** `editor_assignments`, `run_date`, `curator_topics_unsliced` — RunBus
- **Writes (Bus):** `editor_assignments` — RunBus, per-assignment `raw_data['hydration_urls']` enriched via token-overlap match against the Curator cluster set; reads `raw/{run_date}/feeds.json` + `config/sources.json` for URL list and country lookup.
- **Cap (source-cap workpaket, 2026-05-11):** after token-overlap matching, the candidate URL list passes through `select_diverse_hydration_urls`, which applies a stratified round-robin selection over outlets with a hard cap of `HYDRATION_URL_CAP=40` URLs per assignment and a per-outlet ceiling of `MAX_PER_OUTLET=3`. Within an outlet, candidates are recency-sorted by `published_at` (desc, None last); when all candidates lack `published_at` — current operational state pre-`TASK-FETCH-FEEDS-PUBLISHED-AT` — order falls back to input order (Curator's `source_ids` order). The cap stops the cost cascade observed in the 2026-05-11 baseline where hot-topic Curator clusters of ~1000 findings cascaded into ~$2-3 of Phase-1 hydration per assignment.

#### §2.6 select_topics

- **Kind:** deterministic (Python)
- **Source:** `src/stages/run_stages.py::select_topics`
- **Reads (Bus):** `editor_assignments`, `max_produce` — RunBus
- **Writes (Bus):** `selected_assignments` — RunBus, priority-sorted (descending), source-count tiebreaker, sliced to `max_produce`.

### Topic-stages

#### §2.7 attach_hydration_urls (hydrated-only)

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::attach_hydration_urls`
- **Reads (Bus):** `editor_selected_topic` — TopicBus
- **Writes (Bus):** `hydration_urls` — TopicBus, lifted from `editor_selected_topic.raw_data['hydration_urls']`.

#### §2.8 hydration_fetch (hydrated-only)

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::make_hydration_fetch`
- **Reads (Bus):** `hydration_urls` — TopicBus
- **Writes (Bus):** `hydration_fetch_results` — TopicBus, T1 fetched article records via `src.hydration.hydrate_urls` (or injected fetcher).

#### §2.9 HydrationPhase1Stage (hydrated-only)

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::HydrationPhase1Stage`
- **Model:** `deepseek/deepseek-v4-pro`
- **Params:** temp=0.3, reasoning=none, max_tokens=32000
- **Prompt:** `agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md`
- **Reads (Bus):** `editor_selected_topic`, `hydration_fetch_results` (success-only) — TopicBus
- **Writes (Bus):** `hydration_phase1_analyses` — TopicBus, per-article extraction sorted by global `article_index` 0..N-1.
- **Originarity check:**
  - Fields the LLM produces: per-article `summary`, `actors_quoted[]` (`name`, `role`, `type`, `position`, `verbatim_quote`, `evidence_type`)
  - Fields the wrapper merges in deterministically: chunking + global-`article_index` rewrite in `_merge_phase1_results` (article_index is a routing key, not pass-through data). URL/outlet/language/country live on the fetch records, not in the LLM output.

#### §2.10 HydrationPhase2Stage (hydrated-only)

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::HydrationPhase2Stage`
- **Model:** `anthropic/claude-opus-4.6`
- **Params:** temp=0.1, reasoning=none, max_tokens=32000
- **Prompt:** `agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md`
- **Reads (Bus):** `editor_selected_topic`, `hydration_phase1_analyses`, `hydration_fetch_results` — TopicBus
- **Writes (Bus):** `hydration_phase2_corpus` — TopicBus (`preliminary_divergences[]` + `coverage_gaps[]`).
- **Originarity check:**
  - Fields the LLM produces: cross-article divergence + coverage-gap strings
  - Fields the wrapper merges in deterministically: `article_metadata` (language/country/outlet by index) is supplied as context, not echoed; no pass-through fields detected.

#### §2.11 assemble_hydration_dossier (hydrated-only)

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::assemble_hydration_dossier`
- **Reads (Bus):** `hydration_fetch_results`, `hydration_phase1_analyses`, `hydration_phase2_corpus` — TopicBus
- **Writes (Bus):** `hydration_pre_dossier` — TopicBus, sources carry `hydrate-rsrc-NNN` IDs plus `actors_quoted[].evidence_type` threaded from Phase 1; divergences + gaps copied from Phase 2.

#### §2.12 ResearcherHydratedPlanStage (hydrated-only)

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::ResearcherHydratedPlanStage`
- **Model:** `anthropic/claude-opus-4.6`
- **Params:** temp=0.5, reasoning=none, max_tokens=16384
- **Prompt:** `agents/researcher_hydrated/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md`
- **Reads (Bus):** `editor_selected_topic`, `hydration_pre_dossier` — TopicBus
- **Writes (Bus):** `researcher_plan_queries` — TopicBus, gap-aware multilingual queries.
- **Originarity check:**
  - Fields the LLM produces: `query`, `language` per item
  - Fields the wrapper merges in deterministically: `coverage_summary` (language/country/stakeholder counts) computed from the dossier and supplied as context. No pass-through fields detected.

#### §2.13 ResearcherPlanStage (production-only)

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::ResearcherPlanStage`
- **Model:** `anthropic/claude-opus-4.6`
- **Params:** temp=0.5, reasoning=none, max_tokens=default
- **Prompt:** `agents/researcher/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md`
- **Reads (Bus):** `editor_selected_topic` — TopicBus
- **Writes (Bus):** `researcher_plan_queries` — TopicBus
- **Originarity check:**
  - Fields the LLM produces: `query`, `language` per item
  - No pass-through fields detected.

#### §2.14 researcher_search

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::make_researcher_search`
- **Reads (Bus):** `researcher_plan_queries` — TopicBus
- **Writes (Bus):** `researcher_search_results` — TopicBus, deduped Brave-search payloads with URL-date enrichment.

#### §2.15 ResearcherAssembleStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::ResearcherAssembleStage`
- **Model:** `google/gemini-3-flash-preview`
- **Params:** temp=0.2, reasoning=none, max_tokens=default
- **Prompt:** `agents/researcher/ASSEMBLE-SYSTEM.md` + `ASSEMBLE-INSTRUCTIONS.md`
- **Reads (Bus):** `editor_selected_topic`, `researcher_search_results` — TopicBus
- **Writes (Bus):** `researcher_assemble_dossier` — TopicBus
- **Originarity check:**
  - Fields the LLM produces: per-source `url`, `title`, `outlet`, `language`, `country`, `summary`, `actors_quoted[]`, plus `preliminary_divergences[]` and `coverage_gaps[]` strings
  - Fields the wrapper merges in deterministically: `id` (`research-rsrc-NNN`), `estimated_date` (derived from URL when absent from the LLM output)
  - URL/outlet/language/country are originary outputs (the agent extracts them from search-result text blocks), not pass-through copies. No flag.

#### §2.16 merge_sources

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::merge_sources`
- **Reads (Bus):** `hydration_pre_dossier`, `researcher_assemble_dossier` — TopicBus
- **Writes (Bus):** `merged_sources_pre_renumber`, `merged_preliminary_divergences`, `merged_coverage_gaps` — TopicBus.

#### §2.17 renumber_sources

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::renumber_sources`
- **Reads (Bus):** `merged_sources_pre_renumber` — TopicBus
- **Writes (Bus):** `final_sources`, `id_rename_map` — TopicBus, canonical `src-NNN` IDs assigned in array order.

#### §2.18 filter_media_actors_quoted

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::filter_media_actors_quoted`
- **Reads (Bus):** `final_sources` — TopicBus
- **Writes (Bus):** `final_sources` — TopicBus, drops `type=media` entries from every `actors_quoted[]`.

#### §2.19 propagate_outlet_metadata

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::propagate_outlet_metadata`
- **Reads (Bus):** `final_sources` — TopicBus
- **Writes (Bus):** `final_sources` — TopicBus, copies `tier` / `editorial_independence` / `bias_note` from `config/sources.json` per outlet match.

#### §2.20 consolidate_actors

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::consolidate_actors`
- **Reads (Bus):** `final_sources` — TopicBus
- **Writes (Bus):** `final_actors` — TopicBus, flattened/deduped actor list keyed by `actor-NNN` with `quotes[].evidence_type` threaded from sources.

#### §2.21 ResolveActorAliasesStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::ResolveActorAliasesStage`
- **Model:** `google/gemini-3-flash-preview`
- **Params:** temp=1.0, reasoning=medium, max_tokens=66000
- **Prompt:** `agents/resolve_actor_aliases/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `final_actors` — TopicBus
- **Writes (Bus):** `canonical_actors`, `actor_alias_mapping` — TopicBus
- **Originarity check:**
  - Fields the LLM produces: `aliases[]` (`alias_id`, `canonical_id`) + `anonymous_flags[]` (ID lists)
  - Fields the wrapper merges in deterministically: union-find canonical selection (smaller numeric ID wins) in `_resolve_canonical_groups`; `source_ids` + `quotes` merging across aliased entries; `is_anonymous` flag. The wrapper materialises `canonical_actors[]` and `actor_alias_mapping[]` records; the LLM only supplies pair / flag hints.
  - No pass-through fields detected.

#### §2.22 partition_canonical_actors_by_evidence

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::partition_canonical_actors_by_evidence`
- **Reads (Bus):** `canonical_actors` — TopicBus
- **Writes (Bus):** `canonical_actors_stated`, `canonical_actors_reported`, `canonical_actors_mentioned` — TopicBus, three pools by per-quote `evidence_type` (missing → `reported` default policy).

#### §2.23 normalize_pre_research

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::normalize_pre_research`
- **Reads (Bus):** `merged_preliminary_divergences`, `merged_coverage_gaps`, `id_rename_map` — TopicBus
- **Writes (Bus):** `merged_preliminary_divergences`, `merged_coverage_gaps` — TopicBus, agent-local IDs rewritten to canonical `src-NNN`.

#### §2.24 PerspectiveStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::PerspectiveStage`
- **Model:** `anthropic/claude-opus-4.6`
- **Params:** temp=0.1, reasoning=none, max_tokens=default
- **Prompt:** `agents/perspective/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `editor_selected_topic`, `final_sources`, `canonical_actors_stated`, `canonical_actors_reported`, `canonical_actors_mentioned`, `merged_preliminary_divergences`, `merged_coverage_gaps` — TopicBus
- **Writes (Bus):** `perspective_clusters` (raw), `perspective_missing_positions` — TopicBus
- **Originarity check:**
  - Fields the LLM produces: `position_label`, `position_summary`, `source_ids[]` (`src-NNN` references), `stated[]` / `reported[]` / `mentioned[]` actor-id sub-lists, plus `missing_positions[]`
  - Fields the wrapper merges in deterministically: none — enrichment runs in a separate downstream deterministic stage (`enrich_perspective_clusters`).
  - `source_ids` and the three actor sub-lists carry IDs known upstream — these are reference selections, not pass-through field copies. No flag.

#### §2.25 enrich_perspective_clusters

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::enrich_perspective_clusters`
- **Reads (Bus):** `perspective_clusters`, `final_sources`, `canonical_actors`, `canonical_actors_stated`, `canonical_actors_reported`, `canonical_actors_mentioned` — TopicBus
- **Writes (Bus):** `perspective_clusters` — TopicBus, attaches `pc-NNN`, cross-tier-deduped sub-lists, derived `actor_ids` (sorted union), regions, languages, count summary; enforces pool-source consistency.

#### §2.26 mirror_perspective_synced

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::mirror_perspective_synced`
- **Reads (Bus):** `perspective_clusters` — TopicBus
- **Writes (Bus):** `perspective_clusters_synced` — TopicBus, per-element mirror. Dispatches twice in hydrated (after `enrich_perspective_clusters` as 1:1 copy, after `PerspectiveSyncStage` as element-delta merge); once in production (1:1 copy only).

#### §2.27 WriterStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::WriterStage`
- **Model:** `anthropic/claude-opus-4.6`
- **Params:** temp=0.3, reasoning=none, max_tokens=default
- **Prompt:** `agents/writer/SYSTEM.md` + `INSTRUCTIONS.md` (plus optional `FOLLOWUP.md` addendum when `editor_selected_topic.follow_up_to` is set)
- **Reads (Bus):** `editor_selected_topic`, `final_sources`, `canonical_actors`, `perspective_clusters_synced`, `perspective_missing_positions`, `merged_coverage_gaps` — TopicBus
- **Writes (Bus):** `writer_article` — TopicBus (`headline`, `subheadline`, `body`, `summary`)
- **Originarity check:**
  - Fields the LLM produces: `headline`, `subheadline`, `body`, `summary`, plus a `sources[].src_id` echo required by the schema
  - Fields the wrapper merges in deterministically: none.
  - `⚠` — `WRITER_SCHEMA.sources[].src_id` is required by the schema but the wrapper discards it on parse. Schema/wrapper drift; flagged as Open Item.

#### §2.28 QaAnalyzeStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::QaAnalyzeStage`
- **Model:** `anthropic/claude-sonnet-4.6`
- **Params:** temp=0.1, reasoning=none, max_tokens=64000
- **Prompt:** `agents/qa_analyze/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `writer_article`, `final_sources`, `perspective_clusters_synced`, `merged_preliminary_divergences` (plus `perspective_missing_positions` in context for divergence checks) — TopicBus
- **Writes (Bus):** `qa_problems_found`, `qa_corrections`, `qa_corrected_article` (optional, mirror-pattern), `qa_divergences` — TopicBus
- **Originarity check:**
  - Fields the LLM produces: `problems_found[]`, `qa_corrections[]` (`proposed_correction`, `correction_needed`), optional `article` (post-correction headline/sub/body/summary), `divergences[]`
  - Fields the wrapper merges in deterministically: mirror gate — `qa_corrected_article` is left empty when no entry warrants a body fix, then filled by `mirror_qa_corrected` downstream.
  - No pass-through fields detected.

#### §2.29 mirror_qa_corrected

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::mirror_qa_corrected`
- **Reads (Bus):** `writer_article` — TopicBus
- **Writes (Bus):** `qa_corrected_article` — TopicBus, slot-level empty-then-fill.

#### §2.30 PerspectiveSyncStage (hydrated-only)

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::PerspectiveSyncStage`
- **Model:** `anthropic/claude-opus-4.6`
- **Params:** temp=0.1, reasoning=none, max_tokens=default
- **Prompt:** `agents/perspective_sync/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `perspective_clusters`, `qa_corrected_article`, `qa_problems_found`, `qa_corrections` — TopicBus
- **Writes (Bus):** `perspective_clusters_synced` — TopicBus (eligibility-gated: skipped when no correction entry warrants a body fix)
- **Originarity check:**
  - Fields the LLM produces: `position_cluster_updates[]` (deltas: `id`, `position_label`, `position_summary`)
  - Fields the wrapper merges in deterministically: per-element merge over `perspective_clusters` via `_merge_perspective_deltas` (delta IDs are routing keys, not pass-through data).
  - No pass-through fields detected.

#### §2.31 compute_source_balance

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::compute_source_balance`
- **Reads (Bus):** `final_sources` — TopicBus
- **Writes (Bus):** `source_balance` — TopicBus, language/country counts + represented-countries set.

#### §2.32 validate_coverage_gaps_stage

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::validate_coverage_gaps_stage`
- **Reads (Bus):** `merged_coverage_gaps`, `source_balance` — TopicBus
- **Writes (Bus):** `coverage_gaps_validated` — TopicBus, gaps falsified by `source_balance` dropped, near-duplicates collapsed.

#### §2.33 BiasLanguageStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::BiasLanguageStage`
- **Model:** `anthropic/claude-opus-4.6`
- **Params:** temp=0.1, reasoning=none, max_tokens=default
- **Prompt:** `agents/bias_detector/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `qa_corrected_article`, `final_sources`, `canonical_actors`, `perspective_clusters_synced`, `perspective_missing_positions`, `qa_problems_found`, `qa_corrections`, `qa_divergences`, `coverage_gaps_validated` — TopicBus
- **Writes (Bus):** `bias_language_findings`, `bias_reader_note` — TopicBus
- **Originarity check:**
  - Fields the LLM produces: `language_bias.findings[]` (`excerpt`, `issue`, `explanation`), `reader_note`
  - Fields the wrapper merges in deterministically: bias-card context assembled via `_build_bias_card_for_agent_input` and supplied as context (not echoed back).
  - No pass-through fields detected.

#### §2.34 prune_unused_sources_and_clusters

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::prune_unused_sources_and_clusters`
- **Reads (Bus):** `final_sources`, `perspective_clusters_synced`, `writer_article`, `qa_corrected_article`, `qa_divergences`, `bias_language_findings`, `merged_preliminary_divergences`, `coverage_gaps_validated` — TopicBus
- **Writes (Bus):** `final_sources`, `perspective_clusters_synced`, `prune_dropped_sources`, `prune_dropped_clusters` — TopicBus, strict-drop of unreferenced sources and empty-bodied clusters.

#### §2.35 compose_transparency_card

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::compose_transparency_card`
- **Reads (Bus):** `editor_selected_topic`, `qa_problems_found`, `qa_corrections`, `writer_article`, `qa_corrected_article`, `prune_dropped_sources`, `prune_dropped_clusters` — TopicBus (plus RunBus `run_id`, `run_date`)
- **Writes (Bus):** `transparency_card` — TopicBus.

## §3 Open Items

- `⚠` `WRITER_SCHEMA.sources[].src_id` in `src/schemas.py` is a required output field but `WriterStage` (`src/agent_stages.py`) discards it on parse — only `headline`, `subheadline`, `body`, `summary` survive into the `WriterArticle` slot. Either drop the schema field (pure cleanup) or validate that the LLM-echoed `src_id` set matches the inline `[src-NNN]` citations in `body`. Current behaviour is silently lossy.

## §4 Methodology

Code is the source of truth for this map. Document generated against HEAD `345bdfb` on 2026-05-11. When models, parameters, or Bus slots change, this document is updated in the same commit as the code change. The two-file prompt convention for every agent under `agents/` (`SYSTEM.md` + `INSTRUCTIONS.md`, with researcher and hydration using phase-named pairs `PLAN-*.md` / `ASSEMBLE-*.md` / `PHASE1-*.md` / `PHASE2-*.md`) was previously documented in `docs/AGENT-INVENTORY.md`, now archived at `docs/archive/AGENT-INVENTORY-pre-2026-05-11.md`.
