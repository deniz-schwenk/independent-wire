# Independent Wire — Task Tracker

**Created:** 2026-03-30
**Updated:** 2026-04-14 (Session 8 — WP-MEMORY-V1 live, README rewrite, site live, strategic WPs added)
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
| WP-MEMORY | 🟡 Medium | Agent Memory Loading/Saving (Editor knows past coverage) | ✅ Done (Lauf 13) |
| WP-SEO | 🔴 High | Meta-Tags, OpenGraph, Sitemap — required before LinkedIn launch | Open |
| WP-FEED-EXPAND | 🟡 Medium | Scale from 72 to 100+ feeds. At 200+, reactivate Collector as pre-filter. | Open |
| WP-CACHING | 🟢 Low | Prompt Caching via OpenRouter | Open |
## Future Work Packages

| WP | Description | Status |
|----|-------------|--------|
| WP-TELEGRAM | Telegram notifications + Gating (gate_handler hook is ready) | Open |
| WP-VISUALS | generate-visuals.py integration (Mermaid diagrams from Topic Packages) | Open |
| WP-SOCIAL | Social media agent: separate source enrichment (X, YouTube, Instagram) | Open |
| WP-MCP-SERVER | MCP Server: Topic Packages as structured data for Claude/ChatGPT. Reference Instance building block. See WP-MCP-SERVER.md | Open |
| WP-DNS | DNS configuration Cloudflare + .de/.eu domains | Open |
| FIX-RSRC-MAPPING | Perspektiv `source_ids` use `rsrc-*` IDs from Researcher dossier, but Topic Package uses `src-*` IDs. Mapping is lost during assembly → Stakeholder Cards can't link to sources. Fix: either pipeline maps rsrc→src during TP assembly, or Perspektiv Agent receives src-IDs. | Open |
| FIX-GAPS-DUPLICATE | `gaps[]` (top-level) and `bias_analysis.perspectives.missing_voices[]` contain identical data (both from Perspektiv Agent). Remove one during TP assembly in `pipeline.py`. | Open |

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

## Known Issue: LLM JSON Output with Multilingual Quotes

**Status:** Active — `json-repair` fallback pending (TASK-JSON-REPAIR)
**Severity:** Medium — causes silent data loss when unescaped quotes break JSON parsing
**Observed:** Lauf 13 tp-003, Hungarian source title with `„..."` containing unescaped ASCII `"`

When LLM agents output JSON containing non-Latin source titles with quotation marks (Hungarian `„"`,
French `«»`, Chinese `「」`), the closing quote sometimes uses ASCII `"` which breaks the JSON parser.
All existing fallbacks (strip fences, brace extraction, trailing comma removal) cannot fix this.

**Mitigation path:**
1. Immediate: `json-repair` library as additional fallback (TASK-JSON-REPAIR)
2. If insufficient: consider XML output from agents, converted to JSON by Python.
   XML handles embedded quotes naturally via `&quot;` entities.
3. Monitor frequency across future runs before escalating to XML.

---

*This document is updated after each session. Changes are tracked via git.*