# Independent Wire — Task Tracker

**Created:** 2026-03-30
**Updated:** 2026-05-02 (V2 big-bang architecture work-stream complete; V1 deleted in commit 19348f3)
**Purpose:** Living document — updated after each session

---

## Completed Work Packages

| WP | Status | Description |
|----|--------|-------------|
| WP-AGENT | ✅ | Agent class: async LLM calls, tool loop, retry logic |
| WP-TOOLS | ✅ | Tool system: web_search, web_fetch, file_ops, ToolRegistry |
| WP-TOOLS-v2 | ✅ | Multi-provider search: Perplexity, Brave, Grok, DuckDuckGo |
| WP-TOOLS-v3 | ✅ | Ollama integration: local, ollama_cloud, x_search_tool |
| WP-PIPELINE | ✅ | V1 Pipeline: sequential steps, state persistence, error isolation. **Superseded by WP-V2-BUS-ARCHITECTURE.** |
| WP-STRUCTURED-RETRY | ✅ | Retry logic for failed JSON parsing |
| WP-AGENTS | ✅ | System prompts for Collector, Curator, Editor, Writer |
| WP-INTEGRATION | ✅ | First end-to-end pipeline run (2/3 topics produced) |
| WP-RSS | ✅ | RSS/API feeds: 72 sources in `config/sources.json`, `fetch_feeds.py` |
| WP-DEBUG-OUTPUT | ✅ | Step-by-step debug JSON per pipeline step |
| WP-REASONING | ✅ | Configurable reasoning effort per agent |
| WP-RESEARCH | ✅ | Research Agent: multilingual deep research between Editor and Writer |
| WP-PARTIAL-RUN | ✅ | `--from`/`--topic`/`--reuse` flags for `run.py`. Re-engineered in V2 to operate on stage names. |
| WP-QA | ✅ | QA-Analyze + Writer-Correction + Python-Verify (V1). **Replaced in V2 by mirror-pattern QA+Fix.** |
| WP-PERSPEKTIV | ✅ | Perspektiv Agent: stakeholder map, missing voices, framing divergences (V1). **Anglicised to Perspective in V2 (commit history per ARCH-V2-BUS-SCHEMA.md §10 entry 2026-04-29).** |
| WP-RESEARCHER-SPLIT | ✅ | Two-phase Researcher: Plan → Python search → Assemble |
| WP-BIAS | ✅ | Hybrid Bias Card: Python aggregation + LLM language analysis |
| WP-MODEL-EVAL | ✅ | 90+ eval calls, 14 models, all 8 pipeline roles, 5 reasoning levels. Final: 3 models (Gemini 3 Flash, Opus 4.6, Sonnet 4.6). GLM 5 removed from all roles. |
| WP-EVAL-GAP | ✅ | Direct evaluation of Editor, Perspektiv, QA-Analyze, Bias Language. 32 calls, 4 models, 2 reasoning levels. GLM 5 failed 3/4 roles. |
| TASK-FINAL-INTEGRATION | ✅ | Swapped last 3 GLM 5 agents: Researcher Plan/Assemble → Gemini 3 Flash, Writer → Opus 4.6. No GLM 5 left. |
| WP-QA-FIX-MERGE | ✅ | QA+Fix: merged QA-Analyze + Writer-Correction into single Sonnet call (V1). **In V2 the merger is structural via mirror-pattern.** |
| WP-RENDERING | ✅ | Topic Package → HTML renderer in `scripts/render.py`. 12 sections; brutalist design system; stdlib-only Python. |
| WP-WEBSITE | ✅ | Publication site: `publish.py` generates `index.html` + `feed.xml` from rendered TPs. GitHub Actions deployment workflow. |
| WP-CURATOR-CAPACITY | ✅ | Curator targets 10-20 topics. `max_topics=10` (Editor sees), `max_produce=3` (pipeline produces). Debug: `02-curator-topics-unsliced.json` written before slice. Dead prompts deleted (`CLUSTER.md`, `SCORE.md`). |
| WP-SOURCE-RECENCY | ✅ | URL date extraction. Search results enriched with `url_dates`. Pipeline date passed to Assembler context. Assembler prompt updated: `estimated_date` field, recency-aware selection, age notes in `coverage_gaps`. Pipeline logs warnings for sources >30 days old. |
| WP-HYDRATION-T1 | ✅ | `src/hydration.py`: async fetch-and-extract module. aiohttp + trafilatura, user-agent `Independent-Wire-Bot/1.0`, per-domain rate limit 1 req/s, robots.txt respected, 7 status classifications. |
| WP-HYDRATION-T2 | ✅ | Hydration aggregator (V1 location: `src/hydration_aggregator.py`; V2 internalised into `src/agent_stages.py` private helpers in V2-11a). Two-phase chunked execution. |
| WP-HYDRATION-T3 | ✅ | Hydrated pipeline (V1 location: `src/pipeline_hydrated.py`; V2 location: `build_hydrated_stages` in `src/runner/stage_lists.py`). Chains T1 fetch → T2 phase1+phase2 → assemble dossier → hydrated planner → web search → assemble → merge. |
| WP-AGENTRESULT-COST | ✅ | Extended `AgentResult` with `cost_usd` populated from OpenRouter `usage.cost`. `Agent.run()` accumulates per-call cost across the tool loop. (V2-11b: `AgentResult` relocated from `src/models.py` to `src/agent.py`.) |
| WP-WRITER-SOURCES | ✅ | Writer emits minimal source references. (V2-09e: schema field renamed `rsrc_id` → `src_id` for ID-flow symmetry; Writer reads `src-NNN` IDs from `final_sources` and emits `[src-NNN]` citations directly.) |
| WP-PERSPEKTIV-SYNC | ✅ | New Perspektiv-Sync agent (V1). **In V2: anglicised to Perspective-Sync; runs only in hydrated variant; per-element mirror granularity.** |
| WP-PIPELINE-HYGIENE | ✅ | Three retroactive Principle-1 fixes in V1 (sequential renumbering, top-level gaps removal, source-id conversion). **Made structurally redundant by V2's `renumber_sources` invariant per ARCH-V2-BUS-SCHEMA.md §7.** |
| WP-MAX-TOKENS-UNIFORM | ✅ | Uniform `max_tokens=32000` default in `src/agent.py`. Per-agent overrides only where genuinely needed (Curator 64000, Hydrated Planner 16384). |
| WP-T4-COMPARE | ✅ | A/B compare orchestrator `scripts/compare_pipelines.py` (V1). **Deleted in V2-11b along with other V1 spike scripts.** |
| WP-HTTP-TIMEOUT | ✅ | Explicit `httpx.Timeout(connect=30, read=300, write=30, pool=30)` on `AsyncOpenAI` client in `src/agent.py`. |
| WP-AGGREGATOR-CHUNKING | ✅ | Two-phase chunked Hydration Aggregator. Phase 1 parallel chunks `ceil(N/10)`, each 5-10 articles. Intelligent retry per chunk (max 2). Phase 2 single cross-corpus reducer. Counting deterministic in Python. |
| WP-PHASE2-REDUCER | ✅ | Phase 2 reducer promoted to `anthropic/claude-opus-4.6` @ temp 0.1. Eval-validated 114/120. |
| WP-S13 | ✅ | S13 prompt rewrite: every active agent split into SYSTEM.md + INSTRUCTIONS.md two-file convention. `agent.py` three-block User layout (context / memory / instructions). |
| WP-STRUCTURED-OUTPUTS | ✅ | Strict-mode JSON schemas via OpenRouter `response_format` across all 8 production agents (and 3 hydrated-only agents). Schemas live in `src/schemas.py`. |
| WP-V2-BUS-ARCHITECTURE | ✅ | **V2 big-bang architecture work-stream (April–May 2026).** Replaced V1 aggregation-based Pipeline with RunBus + TopicBus + Stage architecture. Full migration sequence per `docs/ARCH-V2-BUS-SCHEMA.md` §10 decision-log entries V2-01 through V2-11b. Closed at source level in commit 19348f3 with V1 deleted. |

---

## V2 work-stream sub-tasks (all ✅, source level closed)

The V2 big-bang work-stream broke into eleven sequential CC tasks. Listed here for traceability — see `docs/ARCH-V2-BUS-SCHEMA.md` §10 decision-log for the full architectural narrative.

| Task | Date | Description |
|------|------|-------------|
| V2-01 | 2026-04-30 | Bus classes (`src/bus.py`): RunBus + TopicBus + read-only proxy logic. Pydantic models with all slots + `visibility` + `mirrors_from` metadata. |
| V2-02 | 2026-04-30 | Stage interface (`src/stage.py`): typed `run_stage` and `topic_stage` signatures, precondition / postcondition validation, frozen-model proxy enforcement. |
| V2-03 | 2026-04-30 | Deterministic stages (`src/stages/run_stages.py`, `src/stages/topic_stages.py`): `init_run`, `select_topics`, merge / renumber / normalize source helpers, mirror engine, transparency-card composer. |
| V2-04 | 2026-04-30 | Hydration deterministic stages: `attach_hydration_urls`, `make_hydration_fetch`, `assemble_hydration_dossier`, `attach_hydration_urls_to_assignments`. |
| V2-05 | 2026-04-30 | Agent-stage wrappers (`src/agent_stages.py`): 12 wrapper classes (Curator, Editor, ResearcherPlan, ResearcherAssemble, Perspective, Writer, QaAnalyze, BiasLanguage, ResearcherHydratedPlan, HydrationPhase1, HydrationPhase2, PerspectiveSync). |
| V2-06 | 2026-04-30 | Render layer (`src/render.py`): visibility-driven filter, five render functions, `compose_bias_card` multi-slot view. |
| V2-06b | 2026-04-30 | Stage-order fix: `mirror_perspective_synced` runs twice in hydrated (once after `enrich_perspective_clusters` for 1:1 fill, once after `perspective_sync` for delta merge). |
| V2-07 | 2026-04-30 | Anglicisation: `agents/perspektiv/` → `agents/perspective/`, `perspektiv_sync/` → `perspective_sync/`, schema renames, code references. |
| V2-08 | 2026-04-30 | Runner package (`src/runner/`): `PipelineRunner` (replaces V1 `Pipeline.run`), `stage_lists.py` (`build_production_stages`, `build_hydrated_stages`), `state.py`. |
| V2-09 | 2026-04-30 | `scripts/run.py` integration: V2 runner wired in, `--from`/`--to`/`--reuse` flags re-engineered for stage names, `--max-produce` flag added. |
| V2-09b | 2026-04-30 | `attach_hydration_urls_to_assignments` finalised as a run-stage between Editor and `select_topics`. 333 V2 tests green at this point. |
| V2-09c, V2-09c2 | 2026-05-01 | V2-10 / V2-10b smoke bug fixes: Bug-1 (`[web-N]` Writer-citation leak), Bug-2 (`run_stage_log` empty), Bug-3 (`[[COVERAGE_STATEMENT]]` template-marker leak), Bug-4 (Curator silent-zero token logging). |
| V2-09e | 2026-05-01 | Bug-5 fix: `WRITER_SCHEMA.sources[].rsrc_id` → `src_id`; Writer + QA prompts corrected to consistent `[src-NNN]` ID form. ID-flow now fully symmetric end-to-end. |
| V2-10c | 2026-05-01 | Re-smoke: 18 verification items PASS; all 5 bugs closed; spend €0.55. V2 architecture confirmed end-to-end. |
| V2-11a | 2026-05-01 | `src/agent_stages.py` internalised the 7 helpers V2 needed from `src/hydration_aggregator.py` plus transitive helpers and module-level constants. Pure refactor. V2 became standalone of all V1-era modules. |
| V2-11b | 2026-05-01 | V1 source code, V1 tests, V1 spike scripts deleted. AgentResult dataclass relocated from `src/models.py` to `src/agent.py`. 25 files changed, +17/-11,084. The V2 big-bang work-stream closes here at source level. |
| V2-DOC-RECONCILE | 2026-05-02 | Phase A: 8 targeted patches in `docs/ARCH-V2-BUS-SCHEMA.md` + `docs/ARCHITECTURE.md` + `scripts/render.py` (commit 9af09ca). Phase B: 4 living documents rewritten (this commit). |

---

## Active / Queued

### Researcher-Polish (next)

| Task | Status | Description |
|------|--------|-------------|
| TASK-RESEARCHER-POLISH | 🔵 Queued | Iteration 1 (locked plan): three outputs — Prompt-Engineer-Briefings for `agents/researcher/PLAN-INSTRUCTIONS.md` + `agents/researcher_hydrated/PLAN-INSTRUCTIONS.md` with inline 6-shape Story-Shape-Targeting (Quantitative-claim, Stakeholder-conflict, Policy/regulatory, Crisis/emergency, Tech/business, Cultural/social — heuristic, not rigid); SYSTEM.md light role-sharpening (breadth + depth dual mandate); CC mini-task to switch `researcher_plan` and `researcher_hydrated_plan` to `anthropic/claude-opus-4.6` (~+€55/month, Assemble stays on Gemini Flash). Plus pre/post smoke-eval. |

### Pre-Researcher-Polish small patches

| Task | Status | Description |
|------|--------|-------------|
| TASK-BIAS-LANGUAGE-RENDER-SHAPE | 🔵 Queued | Small code-patch in `src/render.py`: `bias_analysis.language` currently rendered as a list `["findings", "severity"]` rather than nested object. Pre-existing since V2-04, surfaced by V2-10b §3.4 review. ~10 lines. |

### Future work-streams (catalogued, not actively running)

| Task | Status | Description |
|------|--------|-------------|
| TASK-FUTURE-RESEARCH-DEPTH | 🔵 Future | Direct institutional source fetch via curated registry (RSS/API endpoints per source-category), bypassing LLM-Planner. Prerequisite: Researcher-Polish iteration 1 evaluated. |
| WP-OPUS-4.7-MIGRATION | 🔵 Future | Opus 4.6 → 4.7 swap. `src/agent.py` refactor for `output_config.effort` (low/medium/high/xhigh/max). Breaking changes: `temperature`/`top_p`/`top_k` removed; reasoning levels replaced. All current Opus 4.6 agents swap simultaneously when migration lands. |
| WP-STRUCTURED-OUTPUTS-V2 | 🔵 Future | After Researcher-Polish settles. Migration of `response_format` patterns where structured outputs improve robustness further. Research documented in `docs/RESEARCH-OPENROUTER-STRUCTURED-OUTPUTS.md`. |
| WP-TOPIC-STAGE-PARALLELISATION | 🔵 Future | Run multiple TopicBuses concurrently rather than serially. Architecturally trivial in V2 (no cross-TopicBus dependency); deferred for stability. |
| WP-SPENDING-CAP-REDESIGN | 🔵 Future | Pre-call spending cap rather than post-phase check. V2-10 came near €5 before tripping the post-phase guard — pre-call check would catch budget overruns at the moment they would happen. |
| WP-FEED-EXPAND | 🔵 Future | Expand `config/sources.json` from 72 to 100+ feeds. Prioritise underrepresented regions (Latin America, sub-Saharan Africa, Southeast Asia). Community contribution path. |
| WP-CACHING | 🔵 Future | Cache layer for repeated queries within a run (e.g. when retry happens). Cost reduction for failure modes. |
| WP-MCP-SERVER | 🔵 Future | MCP server providing Topic Packages as structured data to Claude, ChatGPT, and other LLM clients. Documented separately in `docs/WP-MCP-SERVER.md`. |
| WP-SEO | 🔵 Future | SEO improvements for `independent-wire.org`. Documented separately in `docs/WP-SEO.md`. |
| WP-COLLECTOR-REACTIVATION | 🔵 Future | Reactivate the Collector agent (currently commented out in `scripts/run.py:create_agents`) when scaling to 200+ feeds — needed as pre-filter for the Curator. |

---

## Production-hardening roadmap (catalogued)

These items improve operational reliability but are not architectural work. Documented for completeness; will be picked up between feature work-streams.

- **CLI tool packaging** — `independent-wire` as installable command rather than `python scripts/run.py`.
- **Config file** — `config/pipeline.yaml` for runtime parameters currently spread across CLI flags and per-agent settings.
- **Output safety checks** — pre-publish validators that flag schema-malformed TPs before they reach the public site.
- **Crash-recovery / per-stage snapshots** — JSONL append-on-disk per-stage to enable resume-after-crash and richer postmortem debugging. Architecturally cheap in V2 (`run_bus.run_stage_log` already tracks per-stage state).

---

## Two named architectural principles (active in V2)

Formalised in `docs/ARCH-V2-BUS-SCHEMA.md` §3.1 and §3.2:

1. **Originary output** — every Bus slot has exactly one owner; pass-through fields are routed by Python.
2. **Agents are isolated from the Bus schema** — agents emit structures local to their task; the agent-stage wrappers map them onto Bus slots.

The **Audit Commitment** sub-section in `docs/ARCHITECTURE.md` (now deprecated for pipeline architecture but retained as historical reference) describes the 6-step procedure for evaluating an agent's IO contract against these principles. Researcher-Polish is the next planned application of this audit procedure (Writer was first; queued for second visit post-Researcher-Polish).
