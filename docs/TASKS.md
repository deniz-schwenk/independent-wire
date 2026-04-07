# Independent Wire — Task Tracker

**Created:** 2026-03-30
**Updated:** 2026-04-07
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
| WP-RSS | ✅ | RSS/API feeds: 21 sources in config/sources.json, fetch_feeds.py, Pipeline merges with Collector output |
| WP-DEBUG-OUTPUT | ✅ | Step-by-step debug JSON per pipeline step (01-collector-raw.json etc.) |
| WP-REASONING | ✅ | Configurable reasoning effort per agent (None/True/False/"low"/"medium"/"high") |
| WP-RESEARCH | ✅ | Research Agent: multilingual deep research between Editor and Writer. Lauf 3: 5-8 languages/topic instead of 100% EN |
| WP-PARTIAL-RUN | ✅ | `--from`/`--topic`/`--reuse` flags for run.py. Writer-only test: 2 min instead of 30 min |
| WP-QA | ✅ | QA-Analyze (simplified) + Writer-Correction + Python-Verify. Verification Card removed, QA-Rewrite eliminated. Lauf 5: 1 correction, 3 divergences, 4 gaps. |
| WP-PERSPEKTIV | ✅ | Perspektiv Agent: researches spectrum of positions per topic. Integrated into pipeline between Researcher and Writer. |
| WP-RESEARCHER-SPLIT | ✅ | Two-phase Researcher: Plan (LLM) → Python search → Assemble (LLM). Eliminates context accumulation. Tokens dropped from 85K to ~30K. |
| WP-BIAS | ✅ | Hybrid Bias Transparency Card: Python aggregation (0 tokens) + slim LLM language analysis (~8-11K tokens). Reader note synthesizes structural + language findings. |

## Completed Fixes

| Fix | Status | Description |
|-----|--------|-------------|
| Feed-Fixes | ✅ | 8 broken feeds fixed. All Google News proxies removed. |
| P-01–P-05 | ✅ | Collector: date-awareness, YouTube/Wiki/social ban, best-effort multilingual, no dup URLs. Writer: Wikipedia only for background |
| P-06 | ✅ | `divergences` and `gaps` populated by QA-Analyze |
| P-07 | ✅ | Wikipedia rule added as RULE 5 to QA-Analyze. Writer bans Wikipedia for claims/analysis, QA checks against it. |
| P-08 | ✅ | Python sets source count in meta-transparency paragraph instead of LLM. Fixes systematic counting error (25 vs 20, 29 vs 24). |
| F-01–F-05 | ✅ | 30s delay, date in Editor message, code-fence parsing, model correction, language diversity warning |
| QF-01 | ✅ | max_tokens default raised to 32768 (was 8192) |
| QF-02 | ✅ | Token tracking: run-*-stats.json with tokens_used, duration_seconds per agent |
| QF-03 | ✅ | Warning when QA-Analyze returns empty output |
| QF-04 | ✅ | max_tokens default raised to 65536. Headroom for growing dossiers and complex topics. |
| QA-Simplify | ✅ | Verification Card removed, QA-Rewrite eliminated, Writer-Correction + Python-Verify introduced. |
| QF-08 | ✅ | output_schema added to QA-Analyze call, enables structured retry on JSON failures |

## Upcoming Work Packages

| WP | Priority | Description | Depends on |
|----|----------|-------------|------------|
| WP-RENDERING | 🔴 High | Topic Package → HTML rendering. Minimal template for article + Bias Card. Required for demo. | — |
| WP-MEMORY | 🟡 Medium | Agent Memory Loading/Saving (Editor knows past coverage) | — |
| WP-CACHING | 🟢 Low | Prompt Caching via OpenRouter. Two-phase split improves caching (system prompts are stable prefixes). | — |
| Feed expansion | 🟡 Medium | Scale from 21 to 50+ feeds using WorldMonitor catalog. At 200+, reactivate Collector as pre-filter. | — |
| Model evaluation | 🟡 Medium | Evaluate 8 models across 4 agent roles for quality and cost optimization. | — |

## Future Work Packages

| WP | Description | Status |
|----|-------------|--------|
| WP-TELEGRAM | Telegram notifications + Gating (gate_handler hook is ready) | Open |
| WP-VISUALS | generate-visuals.py integration (Mermaid diagrams from Topic Packages) | Open |
| WP-SOCIAL | Social media agent: separate agent for source enrichment (X, YouTube, Instagram) before Writer | Open |
| WP-WEBSITE | GitHub Pages for independentwire.org | Open |
| WP-DNS | DNS configuration Cloudflare + .de/.eu domains | Open |

## Pipeline Run History

### Lauf 1 (2026-03-30)
**Data:** 39 findings → 3 topics → 2 produced, 1 failed (rate limit)
**Duration:** 19 minutes | **Models:** minimax-m2.7 + glm-5 via OpenRouter

### Lauf 2 (2026-03-31)
**Data:** 38 Collector + 445 RSS = 483 findings → 3 topics → 3/3 produced, 0 failed
**Duration:** 19.5 minutes

### Lauf 3 (2026-04-05) — with Research Agent
**Data:** 3 topics → 3/3 produced, 0 failed
**Duration:** 29.6 minutes
**Researcher results:** 5-8 languages/topic, 18-38 sources, 76-85% non-English queries.

### Lauf 4 (2026-04-05) — QA (complex version, before simplification)
**Data:** 1 topic (Iran conflict), QA-only partial run
**Results:** 30 claims checked, 2 corrections (subheadline + source count)
**Problem:** QA-Analyze with Verification Card: 29,170 tokens, ~8 min. In 2/3 follow-up runs: empty `{}` (JSON parsing error due to oversized output).
**Lesson:** Verification Card was the main complexity driver → simplified in QA-Simplify.

### Lauf 5 (2026-04-06) — QA (simplified version)
**Data:** 1 topic (Hungary election), QA-only partial run against uncorrected Lauf 3 output
**Tokens:** QA-Analyze 20,049 (70s) + Writer-Correction 15,836 (32s) = 35,885 total (102s)
**Results:**
- 1 correction: "25 sources" → "20 sources" (systematic Writer counting error)
- 3 divergences: Kaczyński-Orbán connection missing (omission), diaspora framing (framing), EU funds vs. domestic politics (emphasis)
- 4 gaps: Romanian sources, Slovak/Czech, Kaczyński connection, business community
- Python-Verify: 1/1 corrections successfully applied

**Comparison old vs. new:** 29K tokens + 480s + empty output → 36K tokens + 102s + complete results.

### Lauf 7 (2026-04-07) — full 3-topic run
**Data:** 3 topics → 2/3 produced, 1 failed (Hormuz — 85K token Researcher crash)
**Lesson:** Researcher context accumulation problem → triggered WP-RESEARCHER-SPLIT.

### Lauf 9 (2026-04-07) — first complete run with new architecture
**Data:** 3 topics → 3/3 produced, 0 failures. 391,224 tokens, 47.7 minutes.
**New features tested:** Two-phase Researcher, disabled Collector, Writer-Correction retry, Bias Transparency Card.
**Results:**
- Topic 1 (US-Israel-Iran Escalation): 134K tokens — QA returned empty `{}` (fixed by QF-08)
- Topic 2 (Humanitarian Crisis Gaza): 127K tokens — 4 corrections, all applied first attempt
- Topic 3 (Iranian Retaliation): 119K tokens — 2 corrections, all applied first attempt
- Bias Cards: All 3 rated severity "low", reader notes correctly synthesize missing voices
- Writer-Correction: All 6 corrections applied on first attempt

---

*This document is updated after each session. Changes are tracked via git.*
