# Agent I/O Map

Pipeline-stage inventory mapping every V2 stage to its LLM configuration (for agent stages) and Bus I/O contract (for all stages). Bus I/O content authoritative against HEAD `e2d917f` on 2026-05-28 (post Consolidator refactor `3f59ab9` + public-surface cleanup). **§1 and every per-stage Model / Params / Prompt line reconciled against `scripts/run.py`, `src/flash_stage_fallback.py`, `src/planner_fallback.py` and `src/bias_composite.py` at HEAD `1039383` on 2026-09-24**; Bus I/O lines were not re-audited in that pass.

Sources of truth: `src/runner/stage_lists.py` (stage order), `scripts/run.py` (agent registrations), `src/agent_stages.py` (wrapper reads/writes), `src/stages/run_stages.py` + `src/stages/topic_stages.py` (deterministic stages), `src/bus.py` (slot definitions), `src/schemas.py` (LLM output schemas).

## §1 Quick-Reference: LLM Configuration

> The table reflects the **hydrated** pipeline (`create_agents_hydrated()`, the production runner's variant) plus `researcher_plan`, which only the non-hydrated variant uses. Every row is what `scripts/run.py` constructs at HEAD. "Level" is the literal `reasoning` string shipped; "omitted" means the parameter is not sent. The DeepSeek and GLM-5.3 rungs run `structured_output_mode="json_object"` (no strict decoding on those routes), so schema conformance is checked locally by the wrapper, and a schema-invalid final answer counts as a failure that engages the next rung.

| Agent | Primary (model · route) | Temp | Level | max_tokens | Fallback rung(s) |
|---|---|---|---|---|---|
| curator_topic_discovery | `deepseek/deepseek-v4.1-flash` · channel A | 0.5 | medium | 128000 | channel C @ medium |
| editor | `z-ai/glm-5.2` · OpenRouter fp8 pin, strict schema | 0.3 | xhigh | 120000 | `anthropic/claude-sonnet-5` (temp omitted, `{enabled, effort: high}`, 64000) |
| researcher_hydrated_plan | `deepseek-v4-pro` · channel C (`deepseek_direct`) | omitted | low | 24000 | ① `deepseek/deepseek-v4-pro-0813` · OpenRouter pinned `deepseek` @ low, 24000 → ② `anthropic/claude-opus-4.6` (0.5, none, 16384) |
| researcher_plan *(non-hydrated only)* | `anthropic/claude-opus-4.6` · OpenRouter, strict schema | 0.5 | none | 32000 (Agent default) | — |
| researcher_assemble | `deepseek/deepseek-v4.1-flash` · channel A | 0.5 | low | 128000 | channel C @ low |
| resolve_actor_aliases | `deepseek/deepseek-v4.1-flash` · channel A | 0.5 | low | 16000 | channel C @ low |
| hydration_aggregator_phase1 | `deepseek/deepseek-v4.1-flash` · channel A | 0.3 | medium | 160000 | channel C @ medium |
| hydration_aggregator_phase2 | `z-ai/glm-5.3-flash` · Z.AI pin | 1.0 (top_p 0.95) | max | 120000 | `anthropic/claude-opus-4.6` (0.1, none, 32000) |
| perspective | draft `z-ai/glm-5.3` (temp omitted, high, 40000) → verify `z-ai/glm-5.3-flash` (1.0 / top_p 0.95, high, 24000) · both Z.AI pin | see cell | high | see cell | `anthropic/claude-sonnet-5` (temp omitted, `{enabled, effort: high}`, 64000); verify is skipped when the fallback serves |
| writer | `z-ai/glm-5.2` · OpenRouter fp8 pin, strict schema | 0.3 | xhigh | 120000 | `anthropic/claude-opus-4.6` (0.3, none, 32000) |
| qa_analyze | `z-ai/glm-5.3-flash` · Z.AI pin | 1.0 (top_p 0.95) | max | 120000 | `anthropic/claude-sonnet-5` (temp omitted, `{enabled: true}`, 64000) |
| consolidator | `deepseek/deepseek-v4.1-flash` · channel A | 0.3 | minimal | 32000 | channel C @ minimal |
| bias_language | composite, see below | — | — | — | per sub-agent |
| ↳ bias_candidate_extractor | `deepseek/deepseek-v4.1-flash` · channel A, ×3 passes (+1 adaptive) | 0.8 | minimal | 32000 | channel C @ minimal |
| ↳ bias_judge | `z-ai/glm-5.3` · Z.AI pin, ×2 votes | omitted | high | 32000 | `anthropic/claude-opus-4.6` (0.1, none, 32000) |

**Routes.**
- **Channel A** is OpenRouter pinned to the vendor's own endpoint: `DEEPSEEK_NATIVE_ROUTING = {"order": ["deepseek"], "allow_fallbacks": false}`.
- **Channel C** is `api.deepseek.com` direct (`provider="deepseek_direct"`) on the vendor's undated alias `deepseek-v4-flash`.
- **Z.AI pin** is `{"order": ["z-ai"], "allow_fallbacks": false}`.
- **GLM-5.2 fp8 pins** (editor and writer, each its own constant) are `order ["baidu/fp8", "ambient/fp8", "venice/fp8"]`, `allow_fallbacks: false`, `quantizations: ["fp8"]`.
- `top_p` has no Agent parameter; it is sent via `extra_body_override={"top_p": 0.95}`.

**The six flash stages** (curator_topic_discovery, researcher_assemble, resolve_actor_aliases, hydration_aggregator_phase1, consolidator, bias_candidate_extractor) run `FlashStageWithFallback` over `_flash_primary` / `_flash_transport_fallback` (TASK-FLASH-CHANNEL-PIN, 2026-09-18). That swapped the two rungs' roles:
- **Primary:** channel A on `deepseek/deepseek-v4.1-flash`. This is a **named substitution**: the config states the vendor's current first-party flash build so `model_used` can be checked against it and every call carries a measured cost. It is not backed by a per-stage quality eval.
- **Rung 2:** channel C is a **transport** fallback — a different endpoint, auth and failure surface to the same vendor. Its undated alias is unverifiable, so no identity with the primary is claimed. Its calls are unpriced, so a fired rung 2 explains a $0.00 flash call in a stage row.
- **Levels:** each stage's level string is passed unchanged to both rungs.

`scripts/run.py::create_agents` also registers `assign_clusters` (`google/gemini-3-flash-preview`) for the experimental `build_production_stages_llm_assignment` list, which is in neither canonical pipeline. Two-file prompt convention: every agent has `agents/{name}/SYSTEM.md` + `INSTRUCTIONS.md`; researcher variants use `PLAN-*.md` / `ASSEMBLE-*.md`, and hydration uses `PHASE1-*.md` / `PHASE2-*.md`.

### §1.1 Failure handling, degradation and validation (overview)

- **One-shot ladders, loud.** Every wrapper (`FlashStageWithFallback`, `EditorWithFallback`, `WriterWithFallback`, `QaAnalyzeWithFallback`, `HydrationPhase2WithFallback`, `PerspectiveDraftVerifyChain`, `PlannerWithFallbackLadder`) makes exactly one attempt per further rung after the primary finally fails. The planner's order is channel C → dated OpenRouter id → Opus 4.6, and a transport failure on that last rung propagates. A primary counts as finally failed on a transport error after Agent's own retries, or on a schema-invalid final answer. What served is written into the stage row of `run_stage_log.jsonl` as `model_used` / `provider_used` plus a `*_fallback_used` marker (e.g. `planner_fallback_used`, `qa_fallback_used`, `hydration_phase2_fallback_used`, `curator_topic_discovery_fallback_used`).
- **Perspective chain.** A schema-invalid draft gets exactly one logged repair attempt on the draft model before escalating to the fallback. A transport failure escalates immediately. When the fallback serves, the verify pass is skipped.
- **Empty-output escalation.** Four stages call through `_call_with_empty_retry`: CuratorTopicDiscovery, ResearcherAssemble, Consolidator and ResolveActorAliases. Each retries an empty answer for up to 3 attempts, and each attempt goes through the stage's ladder.
  - If every rung is still empty, the stage is **degraded**: its row is recorded as `status: "degraded"` + `degraded_reason` instead of `success` (2026-09-15). For the resolver, `canonical_actors` is then the unmerged input.
  - For `resolve_actor_aliases`, whether an empty answer is plausible is decided deterministically from the input (`merge_candidates_present`). With no merge candidates, an empty result is accepted as correct and never retried (TASK-ALIAS-GATE-TRIGGER).
- **Publish-time degradation gate.** `src/runner/runner.py::fire_degradation_gate` runs at publish decision time, immediately before render. It logs every degraded row at ERROR ("DEGRADATION GATE …", then one "DEGRADED: stage at topic — reason" line each). It does **not** block publishing: a degraded Topic Package is published and flagged, not dropped.
- **Merge-validation detector.** `validate_merges` runs inside `ResolveActorAliasesStage` **before** the union-find.
  - It flags proposed alias pairs with no tangible link between the two actors (`merge_signals`).
  - Shipped mode is `MERGE_VALIDATION_MODE = "detector"`: flagged pairs are counted and logged (collapse shapes of ≥3 aliases onto one canonical get their own `COLLAPSE-SHAPE` prefix), and **every merge still proceeds**.
  - The stage row gains `merges_rejected` / `merges_rejected_detail` / `merge_validation_mode` only when something is flagged.
  - `"reject"` mode (drop flagged pairs) exists but is not enabled.
- **Bias telemetry (compound, per sub-agent).**
  - The `bias_language` row's `model_used` is a compound label naming every call, e.g. `deepseek/deepseek-v4.1-flash x3 -> z-ai/glm-5.3 x2`; a mixed leg keeps every distinct value, joined with `|`.
  - `extra_log_fields` carry `<agent>_model_used`, `<agent>_provider_used` and `<agent>_fallback_used` under each sub-agent's own registered name (`bias_candidate_extractor`, `bias_judge`).
  - Also recorded: `extractor_fallback_passes`, `bias_judge_fallback_votes`, `extraction_passes`, `extractor_extra_pass`, the union/lexicon counts and confirmed/borderline/cleared counts.

## §2 Pipeline I/O Map

Hydrated is treated as canonical. Stages that run in only one variant are flagged inline. Per `src/runner/stage_lists.py`: production runs 8 run-stages + 24 topic-stages; hydrated runs 9 run-stages + 29 topic-stages. The runner appends `RenderStage` + `FinalizeRunStage` after both variants. `mirror_perspective_synced` runs once per topic in both variants. Stage names are listed in dispatch order (hydrated first, then the one production-only stage placed at its production position).

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

#### §2.2b pre_cluster_findings — **wired**

- **Status:** WIRED (Brief 5 cutover, `docs/ADR-CURATOR-TRIPLE-STAGE.md`). Runs after `fetch_findings`, before `CuratorTopicDiscoveryStage` (§2.2d) in both `build_production_stages` and `build_hydrated_stages`.
- **Kind:** deterministic (Python)
- **Source:** `src/stages/pre_cluster.py::make_pre_cluster_findings`
- **Model (embedding, pinned):** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` — shared singleton with §2.3b via `src/stages/coherence.py::_get_default_embedder` (one ONNX session per process)
- **Library (clustering, pinned):** `scikit-learn>=1.3` (floor pin) — promoted in `docs/ADR-COHERENCE-STAGE-DEPENDENCY-ADDENDUM-2026-05-15.md`
- **Algorithm:** Agglomerative clustering, `distance_threshold=0.7`, `linkage='average'`, `metric='cosine'` — calibrated by `docs/CLUSTERING-EVAL-2026-05-14.md::agg-permissive`
- **Reads (Bus):** `curator_findings` — RunBus
- **Writes (Bus):** `curator_pre_clusters` — RunBus
- **Pass-through:** the stage does not mutate `curator_findings` — load-bearing test `tests/test_pre_cluster_stage.py::test_passthrough_curator_findings_byte_identical`.
- **Output shape:** one dict per micro-cluster — `id` (`mc-NNN`), `size`, `source_ids[]` (`finding-NNN` referencing `run_bus.curator_findings[NNN]`). Sorted size desc with smallest-finding-index tie-break. Run-level metadata: model name, fastembed version, algorithm, library + version, params, wall, RSS Δ, n_findings_clustered, n_clusters.
- **No persisted embeddings.** Stage 2 (LLM topic-discovery) doesn't need them; the gravitational-assignment stage in Brief 2 re-embeds in its own pass.
- **Smoke (2026-05-15):** bit-identical reproduction of `agg-permissive` on the three eval datasets — `docs/pre-cluster/smoke-2026-05-15/`. 2026-05-08: 246/100, 2026-05-11: 241/66, 2026-05-13: 279/77 (all Δ=+0.0 % on cluster count).
- **Performance budget (TASK-EMBED-PRE-CLUSTER-STAGE):** embedding ~9 s (bounded by the existing coherence-stage cost; re-uses cached model weights), clustering <1 s for ~1200 findings on commodity CPU. Measured smoke totals: 60–82 s including JSON load + asyncio dispatch.
- **Dependency cost:** scikit-learn 46 MB + scipy 97 MB + joblib 2.4 MB + threadpoolctl 0.1 MB = +146 MB site-packages — see `docs/ADR-COHERENCE-STAGE-DEPENDENCY-ADDENDUM-2026-05-15.md` for the ceiling-raise rationale (400 MB → 600 MB).

#### §2.2c gravitational_assign — **wired**

- **Status:** WIRED (Brief 5 cutover, `docs/ADR-CURATOR-TRIPLE-STAGE.md`). Runs after `CuratorTopicDiscoveryStage` (§2.2d) and before `assemble_curator_topics` (§2.2e) in both `build_production_stages` and `build_hydrated_stages`. The Brief 5 reroute changed the topic-centre input slot from `curator_topics_unsliced` (legacy V1) to `curator_discovered_topics` (the new Curator's output).
- **Kind:** deterministic (Python)
- **Source:** `src/stages/gravitational_assign.py::make_gravitational_assign`
- **Model (embedding, pinned):** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` — shared singleton with §2.2b and §2.3b via `src/stages/coherence.py::_get_default_embedder` (one ONNX session per process)
- **Library (similarity):** `numpy` — cosine similarity on L2-normalised vectors is a single matrix dot product; no sklearn dependency
- **Algorithm:** cosine threshold + top-K with deterministic tie-break (similarity descending, topic-index ascending). Implemented via `np.lexsort` for stability under future numpy / sklearn changes.
- **Reads (Bus):** `curator_findings`, `curator_discovered_topics` — RunBus (Brief 5 cutover rerouted from the legacy `curator_topics_unsliced` to the new Curator's `curator_discovered_topics` slot)
- **Writes (Bus):** `curator_topic_assignments` — RunBus
- **Pass-through:** the stage does not mutate either upstream slot — load-bearing test `tests/test_gravitational_assign_stage.py::test_passthrough_byte_identical`.
- **Pinned constants (recalibrated):** `GRAVITATIONAL_THRESHOLD = 0.55`, `PER_FINDING_CAP = 3`, tie-break `similarity desc, topic-index asc`. **Recalibrated 2026-05-17** under `TASK-GRAVITATIONAL-RECALIBRATION` (Brief 5b) against the 2,542-label audit set from `TASK-CLUSTER-QUALITY-AUDIT` — sweep over T ∈ {0.30…0.55} × V ∈ {title+summary, title-only} selected T=0.55 V1 (title+summary). Aggregate weighted off-topic rate 8.23 % vs. 69.59 % at the provisional T=0.30; zero topics above 50 % off-topic. At T=0.55 the cap does not bind (3,404 / 598 / 5 / 0 / 0 findings in the 0/1/2/3/4+ buckets across 4,007 findings of the three eval days). See `docs/gravitational-recalibration-2026-05-16/sweep.md` for the 12-config sweep, `samples/` for the qualitative basis of the architect's pick, and `docs/cluster-quality-audit/audit-2026-05-16-recalibrated/` for the validation. Brief 2's earlier 504-label calibration at T=0.30 is **superseded** (`docs/gravitational-assign/_calibration-2026-05-15.md` retained as historical record).
- **Output shape:** topics list mirrors `curator_discovered_topics` element-for-element (matched by `topic_index`); each topic carries its `assignments[]` of `{source_id, similarity}`. Flat `orphans[]` list — one entry per finding with no above-threshold match, recording `best_similarity` and `best_topic_index` for transparency. Assignments within a topic sorted by similarity descending with finding-index ascending tie-break; orphans sorted by source_id ascending.
- **Smoke (2026-05-15):** `docs/gravitational-assign/smoke-2026-05-15/` — provisional pre-cutover smoke at T=0.30 V1. Superseded by the recalibrated audit at `docs/cluster-quality-audit/audit-2026-05-16-recalibrated/`.
- **Performance budget (TASK-GRAVITATIONAL-ASSIGN-STAGE):** embedding ~9 s for ~1200 findings + ~0.1 s for 10–20 topic-centres; similarity matrix + selection <0.1 s. Memory ~50 MB for the float matrix. Smoke wall observed: 39–82 s (dominated by fastembed across the three eval datasets).
- **Dependency cost:** none new — numpy + fastembed already production deps.

#### §2.2d CuratorTopicDiscoveryStage — **wired**

- **Status:** WIRED (Brief 5 cutover, `docs/ADR-CURATOR-TRIPLE-STAGE.md`). The only Curator-side LLM in the new architecture. Runs after `pre_cluster_findings` (§2.2b) and before `gravitational_assign` (§2.2c) in both `build_production_stages` and `build_hydrated_stages`. The legacy single-pass `CuratorStage`, the `curator` agent registration, and the `CURATOR_SCHEMA` were removed in the same cutover commits.
- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::CuratorTopicDiscoveryStage`
- **Agent:** `curator_topic_discovery` (registered in `scripts/run.py`)
- **Model:** `deepseek/deepseek-v4.1-flash` via channel A (OpenRouter pinned `deepseek`, since 2026-09-18, TASK-FLASH-CHANNEL-PIN); one-shot transport fallback on channel C (`deepseek_direct`, undated alias `deepseek-v4-flash`) via `FlashStageWithFallback`, marker `curator_topic_discovery_fallback_used`. RUN-LEVEL: a final failure kills the day's run. (History: `google/gemini-3-flash-preview` → `deepseek/deepseek-v4-flash` 2026-05-19, `docs/curator-variance-2026-05-19/curator-variance-report.md`.)
- **Params:** temp=0.5, reasoning=`medium`, max_tokens=128000, `structured_output_mode=json_object` (schema checked locally by the wrapper)
- **Prompt:** `agents/curator/SYSTEM.md` + `INSTRUCTIONS.md` (new prompts committed in the PE round preceding Brief 4)
- **Output schema (checked locally, `json_object` route):** `CURATOR_TOPIC_DISCOVERY_SCHEMA` in `src/schemas.py` — `{topics: [{title, summary}]}`. `additionalProperties: false` at every level so the LLM cannot silently invent legacy fields (`cluster_assignments`, `relevance_score`, `source_ids`).
- **Compression (deterministic, K-pinned):** `SAMPLE_TITLES_PER_CLUSTER = 8`. For each pre-cluster: embed members via the shared fastembed singleton (one ONNX session, shared with §2.2b, §2.2c, §2.3b), compute the cluster centroid, pick the top-K findings by cosine similarity to centroid (sim desc, finding-index asc tie-break), extract titles. Clusters with size ≤ K pass through complete; clusters with empty titles get a placeholder marker.
- **Reads (Bus):** `curator_findings`, `curator_pre_clusters` — RunBus
- **Writes (Bus):** `curator_discovered_topics` — RunBus
- **Pass-through:** the stage does not mutate either upstream slot — load-bearing test `tests/test_curator_topic_discovery_stage.py::test_passthrough_upstream_slots_byte_identical`.
- **Output shape:** `{model_name, params, sample_titles_per_cluster, wall_seconds, llm_cost_usd, tokens_used, n_micro_clusters_input, n_topics, topics: [{title, summary}]}`. Topics are emitted in the LLM's order; Brief 5 attaches `source_ids` (via `gravitational_assign`) and runs the deterministic enrichment on top to produce the final `curator_topics_unsliced`.
- **Smoke (2026-05-16):** `docs/curator-topic-discovery/smoke-2026-05-16/` runs the stage end-to-end against the three eval-anchor state files with real LLM + real fastembed. Result: 15 / 15 / 18 topics across the three days, $0.057 total LLM cost, 30–33 K tokens per call. Topics are specific stories (named actors, named events), zero category-shapes, zero catch-all titles. The V1 pathology decomposition is visible: the 1004-finding Iran mega-cluster from 2026-05-11 splits into multiple specific Iran-war angles.
- **Performance budget (TASK-CURATOR-TOPIC-DISCOVERY-STAGE):** embedding ~9 s (shared singleton, already cached after the run started); compression <1 s; LLM 15–60 s. Smoke observed: ~75 s topic-discovery wall (LLM-dominated, no breach).
- **Dependency cost:** none new — fastembed + numpy + openai are existing production deps. Adds the `curator_topic_discovery` entry to `create_agents()`; the legacy `curator` registration was removed in the same Brief 5 cutover.

#### §2.2e assemble_curator_topics — **wired**

- **Status:** WIRED (Brief 5 cutover, `docs/ADR-CURATOR-TRIPLE-STAGE.md`). Runs after `gravitational_assign` (§2.2c), before `EditorStage` (§2.4) in both `build_production_stages` and `build_hydrated_stages`.
- **Kind:** deterministic (Python). No LLM.
- **Source:** `src/stages/run_stages.py::assemble_curator_topics`
- **Reads (Bus):** `curator_findings`, `curator_discovered_topics` (§2.2d), `curator_topic_assignments` (§2.2c) — RunBus
- **Writes (Bus):** `curator_topics_unsliced`, `curator_topics` — RunBus (same slot shape the legacy `CuratorStage` wrote; Editor input is unchanged)
- **Behaviour:** integration glue. Attaches `source_ids[]` by positional `topic_index` match between `curator_discovered_topics.topics[i]` and `curator_topic_assignments.topics[i]`, calls `src/agent_stages.py::_enrich_curator_output` to derive `geographic_coverage`, `languages`, `source_count`, `missing_regions`, `missing_languages`, `missing_perspectives`, `source_diversity`, sorts by `source_count` descending with title ascending tie-break, slices to `DEFAULT_MAX_TOPICS = 10` for `curator_topics`.
- **Transparency:** topics with zero assignments (gravitational found no above-threshold findings) surface with `source_count = 0` rather than silently drop — the Editor sees the whole list and writes a rejection reason.
- **No new dependencies.**

#### §2.3 ~~CuratorStage~~ — REMOVED (Brief 5 cutover)

The single-pass V1 Curator was removed in the Brief 5 cutover (`docs/ADR-CURATOR-TRIPLE-STAGE.md`). Its functionality is decomposed across §2.2b / §2.2c / §2.2d / §2.2e. Five V1-era calibration scripts that imported `CuratorStage`'s helpers (`smoke_curator`, `smoke_curator_preprod_2026-05-12`, `curator_shadow`, `audit_v4pro_variance`, `eval_curator_models`) were deleted in the same commit. Filename references to historical `run_bus.CuratorStage.json` state files persist in scripts that read those files (historical state names do not auto-rename).

#### §2.3b measure_cluster_coherence — REMOVED FROM PRODUCTION (source retained for fastembed singleton)

- **Status:** Stage callable removed in the Brief 5 cutover (`docs/ADR-CURATOR-TRIPLE-STAGE.md`). The **source file `src/stages/coherence.py` is retained** because three production stages (§2.2b, §2.2c, §2.2d) import the fastembed singleton + `_cosine_normalised` helper from it — one ONNX session per process across all consumers. The legacy `curator_coherence_scores` RunBus slot is left declared (no writer) in case a future calibration brief revives a passive-coherence stage on the new topic-centres.
- **What was removed:** `make_measure_cluster_coherence` factory, the module-level `measure_cluster_coherence` instance, `write_daily_report` + its histogram helpers, the stage-only Bus-write tests in `tests/test_coherence_stage.py`.
- **What stays:** `MODEL_NAME` (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`), `FASTEMBED_VERSION_REQUIRED` (`0.8.0`), `DEFAULT_BATCH_SIZE`, `FastembedEmbedder`, `Embedder` protocol, `_get_default_embedder` (the singleton), `_cosine_normalized`. Singleton-surface tests in `tests/test_coherence_stage.py` cover these.

#### §2.4 EditorStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::EditorStage`
- **Model:** `z-ai/glm-5.2` @ xhigh, OpenRouter fp8 pin `GLM_5_2_EDITOR_FP8_ROUTING`, strict schema; one-shot fallback `anthropic/claude-sonnet-5` (temp omitted, reasoning `{enabled: true, effort: high}`, max_tokens 64000) via `EditorWithFallback`, marker `editor_fallback_used`
- **Params:** temp=0.3, reasoning=`xhigh`, max_tokens=120000
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
- **Model:** `deepseek/deepseek-v4.1-flash` via channel A; one-shot transport fallback on channel C via `FlashStageWithFallback`, marker `hydration_phase1_fallback_used`
- **Params:** temp=0.3, reasoning=`medium`, max_tokens=160000, `structured_output_mode=json_object`
- **Prompt:** `agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md`
- **Reads (Bus):** `editor_selected_topic`, `hydration_fetch_results` (success-only) — TopicBus
- **Writes (Bus):** `hydration_phase1_analyses` — TopicBus, per-article extraction sorted by global `article_index` 0..N-1.
- **Originarity check:**
  - Fields the LLM produces: per-article `summary`, `actors_quoted[]` (`name`, `role`, `type`, `position`, `verbatim_quote`, `evidence_type`)
  - Fields the wrapper merges in deterministically: chunking + global-`article_index` rewrite in `_merge_phase1_results` (article_index is a routing key, not pass-through data). URL/outlet/language/country live on the fetch records, not in the LLM output.

#### §2.10 HydrationPhase2Stage (hydrated-only)

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::HydrationPhase2Stage`
- **Model:** `z-ai/glm-5.3-flash` @ max, Z.AI pin `GLM_5_3_FLASH_HYDRATION_P2_ZAI_ROUTING` (since 2026-09-17, TASK-SWAP-FM-BUNDLE); one-shot fallback `anthropic/claude-opus-4.6` (temp 0.1, reasoning none, max_tokens 32000) via `HydrationPhase2WithFallback`, marker `hydration_phase2_fallback_used`
- **Params:** temp=1.0, top_p=0.95 (via `extra_body_override`), reasoning=`max`, max_tokens=120000, `structured_output_mode=json_object`
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
- **Model:** `deepseek-v4-pro` on channel C (`deepseek_direct`) primary → `deepseek/deepseek-v4-pro-0813` on OpenRouter pinned `deepseek` → `anthropic/claude-opus-4.6` (temp 0.5, none, 16384), via `PlannerWithFallbackLadder` (`src/planner_fallback.py`), marker `planner_fallback_used`
- **Params:** DeepSeek rungs: temp omitted, reasoning=`low`, max_tokens=24000, `structured_output_mode=json_object`
- **Prompt:** `agents/researcher_hydrated/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md`
- **Reads (Bus):** `editor_selected_topic`, `hydration_pre_dossier` — TopicBus
- **Writes (Bus):** `researcher_plan_queries` — TopicBus, gap-aware multilingual queries.
- **Originarity check:**
  - Fields the LLM produces: `query`, `language` per item
  - Fields the wrapper merges in deterministically: `coverage_summary` (language/country/stakeholder counts) computed from the dossier and supplied as context. No pass-through fields detected.

#### §2.13 ResearcherPlanStage (production-only)

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::ResearcherPlanStage`
- **Model:** `anthropic/claude-opus-4.6` (no fallback)
- **Params:** temp=0.5, reasoning=none, max_tokens=32000 (Agent default)
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
- **Model:** `deepseek/deepseek-v4.1-flash` via channel A; one-shot transport fallback on channel C via `FlashStageWithFallback`, marker `researcher_assemble_fallback_used`. (History: migrated from `google/gemini-3-flash-preview` 2026-05-18, `docs/cost-efficiency-sweep-2026-05-18/researcher_assemble-report.md`.)
- **Params:** temp=0.5, reasoning=`low`, max_tokens=128000, `structured_output_mode=json_object`
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
- **Model:** `deepseek/deepseek-v4.1-flash` via channel A; one-shot transport fallback on channel C via `FlashStageWithFallback`, marker `resolve_actor_aliases_fallback_used`. Empty-answer escalation, degradation and the merge-validation detector: §1.1. (History: migrated from `google/gemini-3-flash-preview` 2026-05-19, `docs/cost-efficiency-sweep-wave-2-2026-05-18/resolve_actor_aliases-report.md`.)
- **Params:** temp=0.5, reasoning=`low`, max_tokens=16000, `structured_output_mode=json_object`
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
- **Model:** draft → verify chain `PerspectiveDraftVerifyChain` (`src/perspective_chain.py`, TASK-PERSPECTIVE-SWAP): draft `z-ai/glm-5.3` → verify `z-ai/glm-5.3-flash`, both on Z.AI pin `GLM_5_3_PERSPECTIVE_ZAI_ROUTING`; fallback `anthropic/claude-sonnet-5` (temp omitted, `{enabled: true, effort: high}`, 64000), marker `perspective_fallback_used`. `model_used` names the leg that authored the output.
- **Params:** draft temp omitted, reasoning=`high`, max_tokens=40000; verify temp=1.0 + top_p=0.95, reasoning=`high`, max_tokens=24000; both `structured_output_mode=json_object`
- **Prompt:** draft + fallback `agents/perspective/SYSTEM.md` + `INSTRUCTIONS.md`; verify `agents/perspective_verify/SYSTEM.md` + `INSTRUCTIONS.md`
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
- **Writes (Bus):** `perspective_clusters_synced` — TopicBus, per-element 1:1 copy. Runs once per topic in both variants. The second hydrated dispatch (element-delta merge after `PerspectiveSyncStage`) was removed with `PerspectiveSyncStage` in the Consolidator refactor (`3f59ab9`).

#### §2.27 WriterStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::WriterStage`
- **Model:** `z-ai/glm-5.2` @ xhigh, OpenRouter fp8 pin `GLM_5_2_WRITER_FP8_ROUTING`, strict schema; one-shot fallback `anthropic/claude-opus-4.6` (temp 0.3, none, 32000) via `WriterWithFallback`, marker `writer_fallback_used`
- **Params:** temp=0.3, reasoning=`xhigh`, max_tokens=120000
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
- **Model:** `z-ai/glm-5.3-flash` @ max, Z.AI pin `GLM_5_3_FLASH_QA_ZAI_ROUTING` (since 2026-09-17, TASK-SWAP-FM-BUNDLE); one-shot fallback `anthropic/claude-sonnet-5` (temp omitted, `{enabled: true}`, 64000) via `QaAnalyzeWithFallback`, marker `qa_fallback_used`
- **Params:** temp=1.0, top_p=0.95 (via `extra_body_override`), reasoning=`max`, max_tokens=120000, `structured_output_mode=json_object`
- **Prompt:** `agents/qa_analyze/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `writer_article`, `final_sources`, `perspective_clusters_synced`, `merged_preliminary_divergences` — TopicBus
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

#### §2.30 ConsolidatorStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::ConsolidatorStage`
- **Model:** `deepseek/deepseek-v4.1-flash` via channel A; one-shot transport fallback on channel C via `FlashStageWithFallback`, marker `consolidator_fallback_used`
- **Params:** temp=0.3, reasoning=`minimal`, max_tokens=32000, `structured_output_mode=json_object`
- **Prompt:** `agents/consolidator/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `perspective_missing_positions`, `merged_coverage_gaps` — TopicBus
- **Writes (Bus):** `what_is_missing` — TopicBus (a `WhatIsMissing` carrying two compact-English string arrays, `voices_missing[]` + `topics_missing[]`)
- **Behaviour:** single LLM call, no chunking (both inputs are small, typically <20 entries combined). Classifies each gap entry as a missing voice (stakeholder, region, language, media sphere) or a missing topic (aspect, dimension, angle), and dedupes semantic overlaps across the two inputs. Collapses three stages removed in `3f59ab9`: `PerspectiveSyncStage` (LLM, produced no substantial deltas in practice), `validate_coverage_gaps_stage` (deterministic keyword matcher — over-aggressive; false-falsified a real Cuba gap on 2026-05-23), and `consolidate_missing_coverage` (Jaccard dedup — redundant once the LLM owns dedup). This is the first deliberate exception to "validation is deterministic": whether a gap is real and whether it is voice- or topic-shaped is genuinely semantic.
- **Originarity check:**
  - Fields the LLM produces: `voices_missing[]`, `topics_missing[]` (string arrays)
  - Fields the wrapper merges in deterministically: none — the wrapper only filters out non-string entries.
  - No pass-through fields detected.

#### §2.31 prune_unused_sources_and_clusters

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::prune_unused_sources_and_clusters`
- **Reads (Bus):** `final_sources`, `perspective_clusters_synced`, `writer_article`, `qa_corrected_article`, `qa_divergences`, `merged_preliminary_divergences` — TopicBus
- **Writes (Bus):** `final_sources`, `perspective_clusters_synced`, `prune_dropped_sources`, `prune_dropped_clusters` — TopicBus, strict-drop of unreferenced sources and empty-bodied clusters.
- **Position note (2026-05-12 reorder):** prune was moved earlier in the chain — formerly between BiasLanguageStage and compose_transparency_card — so that `compute_source_balance` and `BiasLanguageStage` operate on the post-prune source set. The `bias_language_findings` read was dropped from the citation harvest in the same change; the bias agent and the gap validator produce secondary commentary, not source-authority, and empirically (V1+V2 2026-05-11 baselines) emit no inline `[src-NNN]` markers. The contract test `test_bias_and_gaps_emit_no_inline_src_markers` codifies this assumption — a future prompt change reintroducing markers fails loudly.

#### §2.32 cleanup_stale_references

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::cleanup_stale_references`
- **Reads (Bus):** `final_sources`, `canonical_actors`, `canonical_actors_stated`, `canonical_actors_reported`, `canonical_actors_mentioned`, `actor_alias_mapping`, `perspective_clusters_synced`, `merged_preliminary_divergences`, `merged_coverage_gaps`, `qa_divergences` — TopicBus
- **Writes (Bus):** `canonical_actors`, `canonical_actors_stated`, `canonical_actors_reported`, `canonical_actors_mentioned`, `actor_alias_mapping`, `perspective_clusters_synced`, `merged_preliminary_divergences`, `merged_coverage_gaps`, `qa_divergences` — TopicBus, filtered against the post-prune `cited_src_ids` set.
- **Filter rules:** per-actor `source_ids[]` and `quotes[]` filtered to surviving sources (actor dropped if `source_ids[]` becomes empty); the three evidence-partitioned pools drop actors that were dropped or that no longer have surviving quotes carrying that pool's `evidence_type`; alias entries whose `canonical_id` references a dropped actor are removed; cluster `source_ids[]` / `actor_ids[]` / `stated`/`reported`/`mentioned` sub-lists filtered against surviving sources + actors (cluster dropped if `source_ids[]` becomes empty); divergence and gap entries with empty surviving `source_ids[]` are dropped.

#### §2.33 compute_source_balance

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::compute_source_balance`
- **Reads (Bus):** `final_sources` — TopicBus
- **Writes (Bus):** `source_balance` — TopicBus, language/country counts + represented-countries set. Now operates on post-prune, post-cleanup `final_sources` so counts match what the rendered TP shows.

#### §2.34 ~~validate_coverage_gaps_stage~~ — REMOVED (Consolidator refactor `3f59ab9`)

Removed in the Consolidator refactor. Its responsibility (falsifying coverage gaps against `source_balance`, collapsing near-duplicates) is now owned by `ConsolidatorStage` (§2.30) as part of the LLM's semantic dedup + classification. The deterministic keyword matcher was over-aggressive — it false-falsified a real Cuba gap on 2026-05-23. The `coverage_gaps_validated` Bus slot was removed in the same change; `what_is_missing` replaces it.

#### §2.35 BiasLanguageStage

- **Kind:** agent (LLM)
- **Source:** `src/agent_stages.py::BiasLanguageStage`
- **Model:** `BiasComposite` (`src/bias_composite.py`): extractor `deepseek/deepseek-v4.1-flash` ×3 passes (+1 adaptive pass when one pass is an outlier-thin pass) on channel A with channel C transport fallback (marker `extractor_fallback_used`) → Python union + lexicon → judge `z-ai/glm-5.3` ×2 votes on Z.AI pin `GLM_5_3_BIAS_JUDGE_ZAI_ROUTING` with one-shot `anthropic/claude-opus-4.6` fallback (temp 0.1, none; marker `bias_judge_fallback_used`) → Python tier assignment. Compound `model_used` + per-sub-agent telemetry: §1.1.
- **Params:** extractor temp=0.8, reasoning=`minimal`, max_tokens=32000; judge temp omitted, reasoning=`high`, max_tokens=32000; both `structured_output_mode=json_object`
- **Prompt:** `agents/bias_candidate_extractor/SYSTEM.md` + `INSTRUCTIONS.md`; `agents/bias_judge/SYSTEM.md` + `INSTRUCTIONS.md`
- **Reads (Bus):** `qa_corrected_article`, `final_sources`, `canonical_actors`, `perspective_clusters_synced`, `qa_problems_found`, `qa_corrections`, `qa_divergences` — TopicBus. (`perspective_missing_positions` and `coverage_gaps_validated` were dropped in the Consolidator refactor + reader_note scope-narrowing, `3f59ab9`: the reader_note no longer comments on coverage gaps.) All inputs are post-prune + post-cleanup, so the `reader_note` source/country counts match what the rendered TP carries.
- **Writes (Bus):** `bias_language_findings`, `bias_reader_note` — TopicBus
- **Originarity check:**
  - Fields the LLM produces: `language_bias.findings[]` (`excerpt`, `issue`, `explanation`, `finding_valid`), `reader_note`. The mandatory `finding_valid: bool` field (since 2026-05-19 commit `6f59fb4`) lets the agent self-retract a finding mid-draft when the `explanation` reveals the finding does not hold (excerpt not in `article_body`, legitimate-practice case, etc.). Retracted findings (`finding_valid: false`) persist in the TP JSON as the audit trail; the renderer drops them from the published HTML.
  - Fields the wrapper merges in deterministically: bias-card context assembled via `_build_bias_card_for_agent_input` and supplied as context (not echoed back).
  - No pass-through fields detected.

#### §2.36 compose_transparency_card

- **Kind:** deterministic (Python)
- **Source:** `src/stages/topic_stages.py::compose_transparency_card`
- **Reads (Bus):** `editor_selected_topic`, `qa_problems_found`, `qa_corrections`, `writer_article`, `qa_corrected_article`, `prune_dropped_sources`, `prune_dropped_clusters` — TopicBus (plus RunBus `run_id`, `run_date`)
- **Writes (Bus):** `transparency_card` — TopicBus.

## §3 Open Items

- `⚠` `WRITER_SCHEMA.sources[].src_id` in `src/schemas.py` is a required output field but `WriterStage` (`src/agent_stages.py`) discards it on parse — only `headline`, `subheadline`, `body`, `summary` survive into the `WriterArticle` slot. Either drop the schema field (pure cleanup) or validate that the LLM-echoed `src_id` set matches the inline `[src-NNN]` citations in `body`. Current behaviour is silently lossy.

## §4 Methodology

Code is the source of truth for this map. Model / parameter / fallback content (§1, §1.1 and every per-stage Model / Params / Prompt line) last reconciled against HEAD `1039383` on 2026-09-24. Bus I/O content last reconciled against HEAD `e2d917f` on 2026-05-28 (post Consolidator refactor `3f59ab9`: removed `PerspectiveSyncStage` + `validate_coverage_gaps_stage`, added `ConsolidatorStage`, corrected `mirror_perspective_synced` to single-dispatch, refreshed BiasLanguage reads). When models, parameters, or Bus slots change, this document is updated in the same commit as the code change. The two-file prompt convention for every agent under `agents/` (`SYSTEM.md` + `INSTRUCTIONS.md`, with researcher and hydration using phase-named pairs `PLAN-*.md` / `ASSEMBLE-*.md` / `PHASE1-*.md` / `PHASE2-*.md`) was previously documented in `docs/AGENT-INVENTORY.md`, since archived.
