# Independent Wire — Task Tracker

**Created:** 2026-03-30
**Updated:** 2026-04-22 (Session 12 — max_tokens uniform 32000, T4 A/B compare orchestrator, chunked two-phase Aggregator, Phase 2 promoted to Opus 4.6 @ temp 0.1)
**Purpose:** Living document — updated after each session

---

## Completed Work Packages

| WP | Status | Description |
|----|--------|-------------|
| WP-AGENT | ✅ | Agent class: async LLM calls, tool loop, retry logic |
| WP-TOOLS | ✅ | Tool system: web_search, web_fetch, file_ops, ToolRegistry |
| WP-TOOLS-v2 | ✅ | Multi-provider search: Perplexity, Brave, Grok, DuckDuckGo |
| WP-TOOLS-v3 | ✅ | Ollama integration: local, ollama_cloud, x_search_tool |
| WP-PIPELINE | ✅ | Pipeline: sequential steps, state persistence, error isolation |
| WP-STRUCTURED-RETRY | ✅ | Retry logic for failed JSON parsing |
| WP-AGENTS | ✅ | System prompts for Collector, Curator, Editor, Writer |
| WP-INTEGRATION | ✅ | First end-to-end pipeline run (2/3 topics produced) |
| WP-RSS | ✅ | RSS/API feeds: 72 sources in config/sources.json, fetch_feeds.py |
| WP-DEBUG-OUTPUT | ✅ | Step-by-step debug JSON per pipeline step |
| WP-REASONING | ✅ | Configurable reasoning effort per agent || WP-RESEARCH | ✅ | Research Agent: multilingual deep research between Editor and Writer |
| WP-PARTIAL-RUN | ✅ | `--from`/`--topic`/`--reuse` flags for run.py |
| WP-QA | ✅ | QA-Analyze + Writer-Correction + Python-Verify |
| WP-PERSPEKTIV | ✅ | Perspektiv Agent: stakeholder map, missing voices, framing divergences |
| WP-RESEARCHER-SPLIT | ✅ | Two-phase Researcher: Plan → Python search → Assemble |
| WP-BIAS | ✅ | Hybrid Bias Card: Python aggregation + LLM language analysis |
| WP-MODEL-EVAL | ✅ | 90+ eval calls, 14 models, all 8 pipeline roles, 5 reasoning levels. Final: 3 models (Gemini 3 Flash, Opus 4.6, Sonnet 4.6). GLM 5 removed from all roles. |
| WP-EVAL-GAP | ✅ | Direct evaluation of Editor, Perspektiv, QA-Analyze, Bias Language. 32 calls, 4 models, 2 reasoning levels. GLM 5 failed 3/4 roles. |
| TASK-FINAL-INTEGRATION | ✅ | Swapped last 3 GLM 5 agents: Researcher Plan/Assemble → Gemini 3 Flash, Writer → Opus 4.6. No GLM 5 left. |
| WP-QA-FIX-MERGE | ✅ | QA+Fix: merged QA-Analyze + Writer-Correction into single Sonnet call. Eliminated 3× Opus retry loop. Input filtering for all agents. |
| WP-RENDERING | ✅ | Topic Package → HTML renderer. 12 sections: Header, Metadata Bar, Radial Source Network, Reader Note, Article, Perspectives, Missing Voices, Divergences, Bias Card, Coverage Gaps, Sources Table, Transparency Trail. Self-contained HTML, no JS, stdlib-only Python. |
| WP-WEBSITE | ✅ | Publication site: publish.py generates index.html + feed.xml from rendered TPs. Brutalist design system (Space Mono + Space Grotesk). GitHub Actions deployment workflow. |
| WP-CURATOR-CAPACITY | ✅ | Curator targets 10-20 topics. max_topics=10 (Editor sees), max_produce=3 (pipeline produces). Debug: 02-curator-topics-unsliced.json written before slice. Dead prompts deleted (CLUSTER.md, SCORE.md). |
| WP-SOURCE-RECENCY | ✅ | URL date extraction (_extract_date_from_url). Search results enriched with url_dates. Pipeline date passed to Assembler context. Assembler prompt updated: estimated_date field, recency-aware selection, age notes in coverage_gaps. Pipeline logs warnings for sources >30 days old. Dead prompt deleted (researcher/AGENTS.md). |
| WP-HYDRATION-T1 | ✅ | `src/hydration.py`: async fetch-and-extract module. aiohttp + trafilatura, user-agent `Independent-Wire-Bot/1.0`, per-domain rate limit 1 req/s, robots.txt respected, 7 status classifications (success, partial, bot_blocked, robots_disallowed, http_error, connection_error, timeout). Smoke test on Lauf-19 URLs: 68.6% success rate, matches Spike B within tolerance. All 6 Anadolu Agency URLs recovered via aiohttp. |
| WP-HYDRATION-T2 | ✅ | `src/hydration_aggregator.py`: four public functions — Aggregator LLM call, build_prepared_dossier, build_coverage_summary, merge_dossiers. Hydration-Aggregator model: google/gemini-3-flash-preview (Spike C winner). Pre-dossier in Researcher-Assembler shape. Coverage summary is 5 fields (total_sources, languages_covered, countries_covered, stakeholder_types_present, coverage_gaps). Merge dedupes Web-Search URLs against Pre-Dossier URL blocklist, concatenates Pre first then Web, reindexes rsrc-NNN. Smoke test: 3 topics × 11-12 articles, ~46K tokens, ~$0.04. |
| WP-HYDRATION-T2-FOLLOWUP | ✅ | Preserved `verbatim_quote` across pipeline instead of dropping. Canonical five-field actor shape {name, role, type, position, verbatim_quote} applied in `build_prepared_dossier` (pass-through from Aggregator) and `merge_dossiers` (Web-Search-side normalization to null). No changes to Researcher Assembler prompt — normalization happens in Python. Verified: 11 of 15 pre-dossier actors on test topic carry real verbatim quotes, all 4 web-search actors carry null. |
| WP-HYDRATION-T3 | ✅ | `src/pipeline_hydrated.py` subclass: overrides `_research_two_phase` to chain T1 fetch → T2 Aggregator → pre-dossier → coverage summary → hydrated planner → web search → JSON/plaintext blocklist filter → Assembler → T2 merge. Debug output routed under `output/{date}/test_hydration/`. Orchestrator `scripts/test_hydration_pipeline.py`. Lauf-19 run: 3/3 TPs, 24–29 sources/topic, 36 verbatim quotes preserved. |
| WP-HYDRATION-T3-FU | ✅ | Retroactive Principle-1 fixes: Writer placeholder `[[COVERAGE_STATEMENT]]` substituted by Python after final source array is known; Editor `selection_reason` forbidden from numeric/outlet-brand claims; country-name normalization (USA→United States, UK→United Kingdom, etc.) + None-filter on `missing_from_dossier`. Module-level `LANGUAGE_NAMES` + `COUNTRY_ALIASES` in `src/pipeline.py`. |
| WP-AGENTRESULT-COST | ✅ | Extended `AgentResult` with `cost_usd` populated from OpenRouter `usage.cost`. `Agent.run()` accumulates per-call cost across the tool loop, emits a single warning when the provider does not report cost, and exposes the total on the result. Unblocks Hydration A/B compare and future budget controls. |
| WP-WRITER-SOURCES | ✅ | Writer emits minimal source references `{id, rsrc_id}`. `_merge_writer_sources` in `src/pipeline.py` resolves each `rsrc_id` against the Researcher dossier and produces the full source object (url, outlet, language, country, estimated_date, actors_quoted incl. verbatim_quote). QA+Fix receives the merged full objects; Writer debug file preserves the minimal refs. |
| WP-PERSPEKTIV-SYNC | ✅ | New Perspektiv-Sync agent runs between QA+Fix and coverage-statement substitution in the hydrated pipeline. V3 prompt emits delta-only output `{stakeholder_updates[]}`; `merge_perspektiv_deltas` in `src/pipeline_hydrated.py` deep-copies the original map and applies deltas via field-presence semantics (null removes, absence leaves untouched). Smoke script `scripts/test_perspektiv_sync.py` reruns against Lauf-19 cached inputs. |
| WP-PIPELINE-HYGIENE | ✅ | Three retroactive Principle-1 fixes in `src/pipeline.py` (mirrored into the hydrated override): Fix 1 — sequential `src-NNN` renumbering with unreferenced-source pruning and atomic citation rewrite; Fix 2 — top-level `gaps[]` and `transparency.framing_divergences` no longer populated (canonical fields live under `bias_analysis`); Fix 3 — `stakeholders[*].source_ids` converted from `rsrc-NNN` to final `src-NNN` via internal `rsrc_id` stash, orphaned entries dropped, stakeholders retained even when source_ids becomes empty. Smoke `scripts/test_pipeline_hygiene.py`. |
| WP-MAX-TOKENS-UNIFORM | ✅ | Uniform max_tokens=32000 default in src/agent.py. All per-agent overrides removed (scripts/run.py, src/pipeline.py curator override, src/pipeline_hydrated.py perspektiv_sync). Max observed QA output across 28 production runs was ~10K tokens — 32K carries ~3x headroom. Prevents context-window overflow without per-agent config complexity. |
| WP-T4-COMPARE | ✅ | A/B compare orchestrator `scripts/compare_pipelines.py`. Runs shared Curator+Editor once, then Production and Hydrated pipelines in parallel on identical assignments. Extracts deterministic metrics per topic (source count, unique outlets, languages, countries, stakeholders, verbatim quotes, word count, cost via `cost_usd`, fetch success rate for Hydrated). Writes markdown report for qualitative review in separate Claude Project. Also fixes `Pipeline._track_agent` to record `cost_usd`. |
| WP-HTTP-TIMEOUT | ✅ | Explicit httpx.Timeout(connect=30, read=300, write=30, pool=30) on AsyncOpenAI client in src/agent.py. First T4 smoke hung 25+ min on a streaming-stalled QA response before SIGTERM; bounded read timeout makes the failure mode deterministic. |
| WP-AGGREGATOR-CHUNKING | ✅ | Two-phase chunked Hydration Aggregator. Phase 1 (per-article extraction, Gemini 3 Flash, `agents/hydration_aggregator/PHASE1.md`) parallel chunks ceil(N/10), each 5-10 articles. Intelligent retry per chunk (max 2) sends only missing indices back as smaller call. Phase 2 (cross-corpus reducer, `agents/hydration_aggregator/PHASE2.md`) single call over merged analyses produces `preliminary_divergences[]` + `coverage_gaps[]`. Counting is deterministic in Python, never delegated to LLM. Eliminates Rule 1 violations on ≥17-article inputs. Old `AGENTS.md` retained as deprecated revert target. |
| WP-PHASE2-REDUCER | ✅ | Phase 2 reducer promoted to `anthropic/claude-opus-4.6` @ temperature 0.1, reasoning=none. 5-variant blind eval (Opus 4.7, Opus 4.6, Sonnet 4.6, Gemini 3.1 Pro low, Gemini 3.1 Pro high) scored Opus 4.6 at 114/120 — second only to Opus 4.7 reference (117/120). Temperature sub-eval on cheaper candidates (Sonnet @ 0.1, Gemini low/high @ 0.1/0.5) confirmed no cheaper option closes the gap. Temp 0.1 aligns Phase 2 with production synthesis agents. Opus 4.7 deferred — see WP-OPUS-4.7-MIGRATION. |
| WP-PHASE2-REDUCER | ✅ | Phase 2 reducer of chunked Hydration Aggregator promoted to anthropic/claude-opus-4.6 @ temperature 0.1, reasoning=none. Eval evidence: variant B scored 114/120 in blind 3-topic eval (Opus 4.7 @ 0.3 reference: 117/120). Temperature 0.1 aligns with production synthesis agents (Perspektiv, QA+Fix, Bias Language). Opus 4.7 migration deferred to dedicated workstream (removes temperature parameter, replaces reasoning levels with output_config.effort). |

## Completed Fixes

| Fix | Status | Description |
|-----|--------|-------------|
| Feed-Fixes | ✅ | 8 broken feeds fixed. All Google News proxies removed. |
| P-01–P-05 | ✅ | Collector: date-awareness, YouTube/Wiki/social ban, multilingual, no dup URLs. Writer: Wikipedia only for background |
| P-06 | ✅ | `divergences` and `gaps` populated by QA-Analyze |
| P-07 | ✅ | Wikipedia rule added as RULE 5 to QA-Analyze |
| P-08 | ✅ | Python sets source count in meta-transparency paragraph |
| F-01–F-05 | ✅ | 30s delay, date in Editor message, code-fence parsing, model correction, language diversity warning |
| QF-01–QF-04 | ✅ | max_tokens raised (8192→32768→65536), token tracking, empty-output warning |
| QF-08 | ✅ | output_schema for QA-Analyze structured retry |
| Curator-Cleanup | ✅ | 4 output fields only (title, relevance_score, summary, source_ids). Python computes geographic_coverage, missing_perspectives, topic_slug |
| Curator-Model | ✅ | minimax-m2.7 (D-Tier) → google/gemini-3-flash-preview (A-Tier), reasoning=none |
| FIX-NULL-SANITIZE | ✅ | _sanitize_null_strings() normalizes LLM string "null"/"None"/"N/A" to Python None. Applied after Perspektiv output. Defense-in-depth guard in render.py build_perspectives(). |
| FIX-PRIORITY-FILTER | ✅ | Pipeline filters priority <= 0 after Editor output. Rejected topics stay in debug (03-editor-assignments.json) but don't enter production. Applied in both run() and run_partial(). |
| FIX-DATE-RESTORE | ✅ | estimated_date restored from Assembler dossier onto Writer's sources via URL lookup in _produce_single(). Writer-added sources (web_search) get date via URL extraction. |
| FIX-AUTO-DEPLOY | ✅ | run.py --publish now git add + commit + push site/ after publish.py. GitHub Actions deploys automatically. |
| FIX-WRITER-PROMPT | ✅ | Pipeline conditionals removed, redundancies deduplicated (99→77 lines, ~30% reduction). Prose structure guidance added. |
| FIX-BIAS-COLLAPSE | ✅ | Bias card: reader_note stays prominent, findings + bar chart behind native details/summary element. Summary line shows count + severity. |
## Model Evaluation Status (April 2026)

### Directly Evaluated

| Agent | Model | Tier | Reasoning Tested | Production Reasoning |
|-------|-------|------|------------------|---------------------|
| Curator | Gemini 3 Flash | **A** | ✅ none/minimal/low/medium/high | **none** (explicit) |
| Researcher Plan | Gemini 3 Flash | **A** | ✅ 5 models tested | **none** |
| Researcher Assemble | Gemini 3 Flash | **A** | ✅ 5 models tested. GLM 5 disqualified (fabricates actors) | **none** |
| Writer | Opus 4.6 | **A** | ✅ 5 models tested. Best journalism quality ($4.10/article) | **none** |

### WP-EVAL-GAP Results (April 2026) — All Agents Now Evaluated

GLM 5 proxy assumption OVERTURNED. Direct evaluation showed GLM 5 fails 3 of 4 roles.

| Agent | Old Model | New Model | Reasoning | Score | Key Finding |
|-------|-----------|-----------|-----------|-------|-------------|
| **Editor** | ~~GLM 5~~ | **Opus 4.6** | none | 8.5/10 | Best editorial reasoning. Gemini r-none scored 2/10! |
| **Perspektiv** | ~~GLM 5~~ | **Opus 4.6** | none | 8.5/10 | Deepest stakeholder analysis, best missing voices |
| **QA-Analyze** | ~~GLM 5~~ | **Sonnet 4.6** | none | 8/10 | Broadest error coverage, pipeline-aware. Sonnet r-medium crashes! |
| **Bias Language** | ~~GLM 5~~ | **Opus 4.6** | none | 9/10 | GLM 5 copies input verbatim (2-3/10) |

Key cross-cutting findings:
- Sonnet r-medium crashes 50% of the time (2/4 roles) — hard reliability veto
- Gemini r-medium is viable budget alternative but ceiling is lower (6-7.5/10)
- Gemini r-none catastrophically fails on editor (swapped topics) — reasoning=medium mandatory for Gemini
- GLM 5 not recommended for any of these 4 roles

## Upcoming Work Packages

| WP | Priority | Description | Status |
|----|----------|-------------|--------|
| WP-RENDERING | ✅ Done | Topic Package → HTML rendering. Radial source network, 12-section layout, CSS hover, self-contained HTML. | **Done** |
| WP-WEBSITE | ✅ Done | Publication site: publish.py, index.html, feed.xml, GitHub Actions. Brutalist design. | **Done** |
| WP-LAUF-10 | ✅ Done | Full pipeline run with all eval-validated models. 3/3 topics, $7.84, 47 min. | **Done** |
| WP-QA-FIX-MERGE | ✅ Done | QA+Fix merged, input filtering, retry loop eliminated. Lauf 11: 25 min, ~495K tokens. | **Done** |
| WP-MEMORY | ✅ Done | Agent Memory Loading/Saving (Editor knows past coverage) | **Done** (Lauf 13) |
| WP-CURATOR-CAPACITY | ✅ Done | Curator 10-20 topics, Editor sees 10, max_produce=3, priority filter | **Done** (Lauf 14) |
| WP-SOURCE-RECENCY | ✅ Done | URL date extraction, estimated_date, pipeline warnings | **Done** (Lauf 14) |
| WP-SEO | 🔴 High | Meta-Tags, OpenGraph, Sitemap — required before LinkedIn launch | Open |
| WP-HYDRATION | ✅ Done | Parallel Hydrated pipeline (Etappe 2). T1 fetch+extract, T2 aggregator+merge, T3 integration all shipped. Lauf-19 end-to-end green (3/3 TPs). A/B compare report deferred to follow-up WP. | **Done** (Session 11) |
| WP-AGENTRESULT-COST | ✅ Done | `cost_usd` sourced from OpenRouter `usage.cost`, accumulated across tool loop, exposed on `AgentResult`. Unblocks Hydration A/B compare and future budget controls. | **Done** (Session 11) |
| WP-T4-COMPARE | ✅ Done | Production vs Hydrated A/B compare orchestrator with deterministic metrics + markdown report. Fixed Pipeline._track_agent to record cost_usd. | **Done** (Session 12) |
| WP-MAX-TOKENS-UNIFORM | ✅ Done | Uniform max_tokens=32000 default across all agents. | **Done** (Session 12) |
| WP-AGGREGATOR-CHUNKING | ✅ Done | Two-phase chunked Hydration Aggregator with intelligent retry. Phase 1 per-article extraction (Gemini 3 Flash, parallel chunks). Phase 2 cross-corpus reducer. | **Done** (Session 12) |
| WP-PHASE2-REDUCER | ✅ Done | Phase 2 reducer on Opus 4.6 @ temp 0.1 reasoning=none after 5-variant blind eval + temperature sub-eval. | **Done** (Session 12) |
| WP-OPUS-4.7-MIGRATION | 🟡 Medium | Migrate all Opus 4.6 agents (Editor, Perspektiv, Writer, Bias Language, Phase 2 reducer) to Opus 4.7 simultaneously. Requires src/agent.py refactor: drop temperature/top_p/top_k on 4.7 calls (400 error on non-default), replace reasoning-level mapping with output_config.effort (low/medium/high/xhigh/max), verify OpenRouter pass-through semantics. Per-agent effort-level eval needed before cutover. | Open |
| WP-FEED-EXPAND | 🟡 Medium | Scale from 72 to 100+ feeds. At 200+, reactivate Collector as pre-filter. | Open |
| WP-CACHING | 🟢 Low | Prompt Caching via OpenRouter | Open |
## Future Work Packages

### Production Hardening

| WP | Priority | Description | Status |
|----|----------|-------------|--------|
| WP-CLI | 🟡 Medium | Installable CLI: `iw run`, `iw publish`, `iw fetch` via pyproject.toml entry points. Replace `source .venv/bin/activate && source .env && python scripts/run.py` | Open |
| WP-CONFIG | 🟡 Medium | Config file (`iw.yaml`): models, providers, max_topics, max_produce. Model presets (cost-optimized, quality-max). `iw run --preset cost-optimized --topics 5` | Open |
| WP-ONBOARDING | 🟢 Low | `iw init` setup wizard: API keys, provider preference, feed selection. "First dossier in 5 minutes" for non-developers. Depends on WP-CLI + WP-CONFIG | Open |
| WP-BUDGET-LIMITS | 🔴 High | max_cost_per_run parameter, token-cost accumulator in Pipeline, abort on threshold. Prevents runaway costs from loops or bugs. | Open |
| WP-OUTPUT-SAFETY | 🔴 High | Post-Writer LLM check for defamation, discrimination, harmful content. Small Sonnet/Haiku call. Reputational risk mitigation for public newsroom. | Open |
| WP-INPUT-SANITIZE | 🟡 Medium | RSS feed title/summary validation against prompt injection. Manipulated feeds could attempt to hijack Curator or Editor. | Open |
| WP-CONTINUOUS-EVAL | 🟢 Low | Weekly Claude-judge scoring of dossier quality: source diversity, perspective breadth, writing quality. Trend detection over 30+ days. | Open |
| WP-MONITORING | 🟢 Low | Historical run stats dashboard: cost trends, source diversity over time, quality metrics. Anomaly alerts (double costs, halved diversity). | Open |

### Features

| WP | Description | Status |
|----|-------------|--------|
| WP-TELEGRAM | Telegram notifications + Gating (gate_handler hook is ready) | Open |
| WP-VISUALS | generate-visuals.py integration (Mermaid diagrams from Topic Packages) | Open |
| WP-SOCIAL | Social media agent: separate source enrichment (X, YouTube, Instagram) | Open |
| WP-MCP-SERVER | MCP Server: Topic Packages as structured data for Claude/ChatGPT. Reference Instance building block. See WP-MCP-SERVER.md | Open |
| WP-DNS | DNS configuration Cloudflare + .de/.eu domains | Open |

### Known Bugs

No open production bugs as of Session 11.

## Eval Infrastructure

| File | Purpose | Location |
|------|---------|----------|
| test_models.py | Multi-model eval with reasoning support | scripts/ |
| test_clustering.py | Python TF-IDF vs LLM clustering comparison | scripts/ |
| test_curator_twostage.py | Two-Stage vs One-Pass curator eval (4 modes, 9 models) | scripts/ |
| test_eval_gap.py | Editor/Perspektiv/QA/Bias eval (4 models × 2 reasoning) | scripts/ |
| test_researcher_writer.py | Researcher/Writer eval (5 models × 3 roles) | scripts/ |
| EVAL-SYSTEM-PROMPT.md | Blind evaluation prompt for Claude project | repo root |
| EVAL-RESULTS.md | All eval results consolidated (Eval 1+2+3) | output/eval/2026-04-07/ |

## Pipeline Run History

### Lauf 1-2 (2026-03-30/31)
Data: 39-483 findings → 3 topics. Duration: ~19 min. Models: minimax-m2.7 + glm-5.

### Lauf 3 (2026-04-05) — with Research Agent
3/3 topics produced. Researcher: 5-8 languages/topic, 18-38 sources, 76-85% non-English.

### Lauf 5 (2026-04-06) — QA simplified
QA-Analyze: 1 correction, 3 divergences, 4 gaps. Writer-Correction: all applied first attempt.

### Lauf 7 (2026-04-07) — Researcher crash
2/3 produced. Hormuz topic: 85K token Researcher crash → triggered WP-RESEARCHER-SPLIT.

### Lauf 9 (2026-04-07) — first complete architecture
3/3 produced, 0 failures. 391K tokens, 47.7 min. Two-phase Researcher, Bias Cards, Writer-Correction.
All 6 corrections applied on first attempt. Bias Cards all "low" severity (GLM 5 may be too lenient).

### Lauf 10 (2026-04-09) — first eval-validated run
3/3 produced, 0 failures. 47 min, $7.84. All new models: Gemini 3 Flash (Curator, Researcher), Opus 4.6 (Editor, Perspektiv, Writer, Bias), Sonnet 4.6 (QA).
Topics: US-Iran Ceasefire, Trump/NATO, Russia-Ukraine War. Writer: 5-14 web_search calls/article.
Writer-Correction: Topic 3 had 5/6 corrections not applied after 3 retries (pipeline completed).
Cost breakdown: ~$2.61/topic avg. Estimated $19 was too high — actual $7.84 (59% under estimate).

### Lauf 11 (2026-04-13) — QA+Fix merged, input filtering
3/3 produced, 0 failures. 25 min (-47%), ~495K tokens (-54% vs Lauf 10).
Topics: US Naval Blockade Iran, Magyar Ousts Orbán, Trump vs Pope Leo XIV.
QA+Fix: Single Sonnet call per topic replaces QA + 3× Writer-Correction. ~15K tokens/call vs ~170K old.
Topic 3: QA+Fix output not parseable (raw output lost) — Writer original kept, pipeline handled gracefully.
Input filtering: All agents now receive only needed context keys. No more **assignment_data spread.

### Lauf 12 (2026-04-13) — _extract_dict fix verified (partial run: QA+Fix only)
3/3 QA+Fix calls succeeded including Topic 3 (which failed in Lauf 11).
Fixes verified: robust _extract_dict (JSON fallback parsing) + max_tokens 16384→32768.
No RAW.txt fallback files written — all outputs parsed successfully.

### Lauf 13 (2026-04-14) — WP-MEMORY-V1 live, follow-up detection
3/3 produced, 0 failures. 26.5 min, ~$0.90. Previous coverage scan: 4 TPs from April 13.
Follow-up detection: tp-001 + tp-002 correctly identified as follow-ups to tp-2026-04-13-001.
FOLLOWUP.md addendum loaded and passed to Writer for both.
tp-003 (Hungary/Orbán): Writer + QA both failed JSON parsing due to unescaped `"` in Hungarian
source title (`„Az EU költségvetése nem ATM": több...`). Manually repaired — 22 sources, 6 languages,
6 divergences recovered from RAW output.

### Lauf 14 (2026-04-15) — Curator capacity, priority filter, source recency live
3/3 produced, 0 failures. 30 min, €3.30 (~521K tokens).
First run with: Curator 20→10→3 pipeline, priority-0 filter, null sanitizing, source recency.
Curator: 20 topics produced (unsliced), top 10 to Editor. Previous max: 3.
Editor: 8 accepted (priority 2-9), 2 rejected (Hungary duplicate, Congress scandal). Full range used.
Production: Top 3 by priority (9, 8, 7). Budget cap saved ~€2.20 on 5 unpublished accepted topics.
Follow-ups: 2/3 (tp-001→Iran blockade, tp-003→IMF downgrade). tp-002 (Israel-Lebanon) standalone.
Source recency: estimated_date present on all 15 Assembler sources. Restored to TP via URL lookup.
Pipeline warnings: 2 old sources flagged (Le Monde 86 days, Bank of Israel 45 days).
Null sanitizing: 0 string-"null" across 18 perspectives — fix confirmed working.
Topics: Iran Reparations + Blockade (17 src, 6 lang), Israel-Lebanon Talks (13 src, 5 lang),
IMF Growth Downgrade (15 src, 8 lang).

### Session 11 (2026-04-21) — Perspektiv-Sync V3 calibration
Perspektiv-Sync V3 operated conservatively on Lauf-19 cached inputs: 1 `position_summary`
delta across 3 topics vs V1's 4. Independent eval agent confirmed Hypothesis A — V3 is
correctly calibrated, V1 was over-eager. Cost: ~$0.14 for 3 topics under V3 (delta-only)
vs ~$0.40 under V1 (full map rewrite). No prompt adjustment required.

### Session 12 (2026-04-22) — Infrastructure hardening + Aggregator chunking + Phase 2 model
Five deliverables in one session. (1) `max_tokens` uniform at 32000 in `src/agent.py` —
per-agent overrides removed, based on empirical measurement across 28 QA output files
(max observed ~10K tokens). (2) T4 A/B compare orchestrator `scripts/compare_pipelines.py`
with deterministic metric extraction and markdown report. Fixed `Pipeline._track_agent` to
record `cost_usd`. (3) Explicit `httpx.Timeout(read=300)` on AsyncOpenAI client after first
T4 smoke hung 25+ min on a streaming-stalled QA call. (4) Two-phase chunked Hydration
Aggregator: Phase 1 parallel chunks of ceil(N/10), intelligent retry per chunk (max 2),
Phase 2 single reducer call for divergences+gaps. Counting is deterministic in Python.
Eliminated Rule 1 violations on ≥17-article inputs. (5) Phase 2 reducer on Opus 4.6 @
temp 0.1 after 5-variant blind eval (114/120 vs Opus 4.7 reference 117/120) + temperature
sub-eval confirming no cheaper candidate closes the gap. Opus 4.7 migration deferred to
dedicated workstream due to breaking API changes (temperature removed, reasoning levels
replaced by output_config.effort).

### Session 13 (2026-04-23 → 2026-04-27) — S13 prompt rewrite + pipeline audit

WP-PROMPT-REWRITE-PYTHON-FOLLOWUPS shipped (commit 9acddf7). All thirteen production agents migrated to the two-file SYSTEM.md + INSTRUCTIONS.md convention. agent.py three-block User layout (`<context>` / `<memory>` / `<instructions>`) live. Perspektiv V2 active end-to-end: `pc-NNN` ids, `position_clusters[]`, `src-NNN` body citations, `qa_proposed_corrections`, no V1 stubs. Pipeline refactor complete: rsrc-NNN/pc-NNN assignment in Python, renumbering moved before QA+Fix, source_id invariant strengthened (sequential, gapless, every citation backed, every source cited). Three deterministic pipeline bugfixes shipped (commit 3e81468): verbatim quotes restored to TPs, Phase 2 coverage_gaps wired through, country/language normalization hardened. Curator schema fix shipped (commit 37f0ec0): `cluster_assignments` is a flat array of `int|null`, length matches input findings; `_recover_truncated_cluster_assignments` added as defensive recovery for Gemini Flash mid-array truncation. End-to-end pipeline audit produced (`docs/AUDIT-PIPELINE-S13-2026-04-27.md`, 693 lines): per-agent input/output verification, prompt-quality assessment, ten ranked recommendations.

### Session 14 (2026-04-28) — WP-STRUCTURED-OUTPUTS shipped + drift resolution

Strict-mode JSON schemas via OpenRouter `response_format` shipped end-to-end across all eight active production agents. Five commits: 13cc76a (Phases 0+1+2 — agent.py wiring, src/schemas.py created, researcher_plan pilot), d56ff32 (Phase 3 — Curator, Editor, Researcher Assemble, Perspektiv, QA+Fix, Bias), 15ebc81 (Phase 4 — Writer with anyOf source shapes), 71b1138 (research-note status marked shipped), 091a7b2 (Editor explicit-unwrap refactor for consistency with Researcher PLAN call site). Three live smokes confirmed 9/9 TPs with zero parse failures. Defense-in-depth (`_extract_dict`, `_extract_list`, `_parse_json`, `json_repair`, `_parse_or_retry_structured`) preserved as fallback per spec.

Three prompt-vs-schema drift points surfaced during review and resolved on disk: (1) Editor INSTRUCTIONS.md rewritten by the Engineer to the V2 two-file convention — the legacy single-file format with IDENTITY-AND-PURPOSE block and verbose target-audience prose is gone; only `id` and `topic_slug` references removed per Originary-Output-Prinzip. (2) QA+Fix INSTRUCTIONS.md trimmed: `article.sources` removed from OUTPUT FORMAT (Python owns the field); input-side references retained because sources remain input cross-check material. (3) Perspektiv-Sync prompt-vs-schema drift (omit-vs-null) parked — hydrated-only, not currently wired in `scripts/run.py`, no production conflict; resolution deferred to whichever workstream activates the hydrated pipeline next.

Pipeline cost: live runs in S14 confirmed €1-3 per topic with strict mode active. No measured regression in article quality across the three smokes. Schema-as-code now enforces the Originary-Output-Prinzip structurally — agents are mechanically incapable of emitting Python-owned fields (`id`, `topic_slug`, `rsrc_id`, `pc_id`), where previously the principle relied on prompt discipline only.

### Session 15 (2026-04-29) — Audit-recs closed, Hydrated activated, V2 architected

Three workstreams shipped, one architecture decision taken.

**Audit-recommendations closed.** All seven open recommendations from `docs/AUDIT-PIPELINE-S13-2026-04-27.md` shipped via deterministic Python:
- rsrc-/src- universal sweep over the entire final TP (replacing the partial Fix-3-on-perspectives-only)
- coverage_gaps validated against final source_balance (drops Pre-research statements falsified by web-search expansion)
- actor.region field removed (was source-country, semantically meaningless per-actor)
- bias_analysis.factual_divergences removed (Python copy of qa_analysis.divergences — duplication eliminated)
- selection_reason stale-quantifier strip (Editor-time "only two outlets" no longer survives downstream research)
Plus three structural cleanups uncovered during eval review. Five commits across S15: ac13fd2, be2382b, f6a4c14, 92fb5ef.

**Hydrated pipeline activated.** `scripts/run.py --hydrated` flag added. Eleven hydrated agents wired with strict-mode JSON schemas. Output isolation: production stays at `output/{date}/`, hydrated at `output/{date}/test_hydration/`. Three legacy permissive `output_schema={"type":"object"}` overrides removed (Phase 1 aggregator, Phase 2 reducer, hydrated planner) — HYDRATION_PHASE1_SCHEMA, HYDRATION_PHASE2_SCHEMA, RESEARCHER_PLAN_SCHEMA now reach the LLM at every call site. Commits 4b8cf94, eb43727→d786d8c, 69fb8b8.

**Hydrated-vs-Production 1:1 eval.** King Charles III State Visit topic produced on both pipelines with all S15 fixes applied. Side-by-side comparison from on-disk TPs:

| Signal | Production | Hydrated |
|---|---|---|
| Body words | ~890 | ~846 |
| Sources | 16 | 16 |
| Perspectives | 6 | 7 |
| Divergences | 3 | 4 |
| Gaps | 2 | 9 |

Hydrated outperforms Production at multi-perspective depth despite 50% T1 fetch loss on this topic (SCMP bot-blocked). Eval feedback flagged five aggregation bugs which were closed in subsequent commits.

**V2 Bus-architecture decided.** `docs/ARCH-V2-BUS-SCHEMA.md` captures the structural answer to the recurring S14/S15 aggregation bugs. Architecture: RunBus + N TopicBuses, hierarchical separation of run-scoped and topic-scoped state. Granular slots with empty-then-fill mirror pattern as the universal modification convention. Render layer is selection from the Bus driven by visibility schema-metadata. Bias card surfaces all five Vision dimensions (language, source, geographical, selection, framing) as a multi-slot derived view. Big-bang migration with `v1-final` git tag as rollback baseline. Anglicises `perspektiv` → `perspective` consistently across code, prompts, and folders. Implementation begins in a subsequent session.

**Three INSTRUCTIONS.md restorations.** S14 surgical edits had silently truncated `agents/qa_analyze/INSTRUCTIONS.md` (71 → 10 lines) and `agents/editor/INSTRUCTIONS.md` (also corrupted). Restored from V2 baselines via Engineer round-trip + CC pre-commit verification. Memory-edit added: no more architect-side surgical prompt edits — all prompt/code edits go through CC's stricter pre-commit verification (git status, diff --cached --numstat, line-count delta sanity).

## Known Issue: LLM JSON Output with Multilingual Quotes

**Status:** Mitigated — `json-repair` fallback active since Lauf 13
**Severity:** Medium — causes silent data loss when unescaped quotes break JSON parsing
**Observed:** Lauf 13 tp-003, Hungarian source title with `„..."` containing unescaped ASCII `"`

When LLM agents output JSON containing non-Latin source titles with quotation marks (Hungarian `„"`,
French `«»`, Chinese `「」`), the closing quote sometimes uses ASCII `"` which breaks the JSON parser.
All existing fallbacks (strip fences, brace extraction, trailing comma removal) cannot fix this.

**Mitigation path:**
1. ✅ Implemented: `json-repair` library as Attempt 4 fallback in _extract_dict and _extract_list
2. If insufficient: consider XML output from agents, converted to JSON by Python.
   XML handles embedded quotes naturally via `&quot;` entities.
3. Monitor frequency across future runs before escalating to XML.

---

*This document is updated after each session. Changes are tracked via git.*