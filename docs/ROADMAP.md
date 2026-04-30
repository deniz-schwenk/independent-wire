# Independent Wire — Open Source Roadmap

**Created:** 2026-03-26
**Updated:** 2026-04-28 (Session 14 — WP-STRUCTURED-OUTPUTS shipped: strict-mode JSON schemas via OpenRouter response_format across all 8 production agents)
**Status:** Living document — strategic overview.
**Basis:** Vision paper (March 2026) + PoC experience (Sessions 1–12) + Model Evals (Sessions 4–5) + Cost Optimization (Session 6) + Rendering + Website (Session 7)

---

## Three Horizons

| Horizon | Timeframe | Goal |
|---------|-----------|------|
| **H1 — Foundation** | Weeks 1–2 | Framework, schema, style, repo structure |
| **H2 — First Milestone** | Weeks 3–6 | Public live demo: one transparent daily report that proves the thesis |
| **H3 — Community & Growth** | After | Visibility, participation, additional formats, funding |

---

## H1 — Foundation (Weeks 1–2) ✅ Complete

- [x] **H1.1** — Set up architect project (Claude project as permanent planning partner)
- [x] **H1.2** — Validate pipeline on M1 (PoC pipeline runs on MacBook Air M1)
- [x] **H1.3** — Core decisions (name, domain, repo, license, language)
- [x] **H1.4** — Output schema (Topic Package v1)
- [x] **H1.5** — Designer pivot (no AI images → deterministic Mermaid diagrams)
- [x] **H1.6** — Editorial style guide
- [x] **H1.7** — Framework architecture (Agent + Pipeline + Tool)
- [x] **H1.8** — GitHub repo with docs, schema, and concept
## H2 — Framework + First Milestone (Weeks 3–6)

### H2.1 — Build Framework (Work Packages)

Core framework operational. Pipeline produces Topic Packages with multilingual research, perspective analysis, QA, and bias transparency cards.

| WP | Name | Status |
|----|------|--------|
| WP-AGENT | Agent Abstraction | ✅ Done |
| WP-TOOLS | Tool System (multi-provider search, web_fetch, file_ops) | ✅ Done |
| WP-PIPELINE | Pipeline Orchestration | ✅ Done |
| WP-STRUCTURED-RETRY | JSON parsing retry logic | ✅ Done |
| WP-AGENTS | Agent Prompts (Collector, Curator, Editor, Writer) | ✅ Done |
| WP-INTEGRATION | End-to-End pipeline run | ✅ Done |
| WP-REASONING | Configurable reasoning effort per agent | ✅ Done |
| WP-RSS | RSS/API feed ingestion (72 sources) | ✅ Done |
| WP-DEBUG-OUTPUT | Step-by-step debug output per pipeline step | ✅ Done |
| WP-RESEARCH | Multilingual research agent (per topic) | ✅ Done |
| WP-PARTIAL-RUN | CLI flags for partial pipeline runs (--from, --to, --topic, --reuse) | ✅ Done |
| WP-QA | QA-Analyze + Writer-Correction + Python-Verify | ✅ Done |
| WP-PERSPEKTIV | Perspective Agent (stakeholder map, missing voices, framing divergences) | ✅ Done |
| WP-RESEARCHER-SPLIT | Two-phase researcher: Plan → Python search → Assemble | ✅ Done |
| WP-BIAS | Bias Transparency Card (Python aggregation + LLM language analysis) | ✅ Done |
| WP-MODEL-EVAL | Model evaluation across 14 models, all 8 roles, reasoning tests. 90+ eval calls. | ✅ Done |
| WP-TELEGRAM | Telegram Interface | ⬜ Planned |
| WP-MEMORY | Agent Memory (Editor coverage continuity) | ✅ Done |
| WP-CURATOR-CAPACITY | Curator 10-20 topics, Editor sees 10, max_produce=3 | ✅ Done |
| WP-SOURCE-RECENCY | URL date extraction, estimated_date on sources, age warnings | ✅ Done |
| WP-HYDRATION | Parallel Hydrated pipeline (Etappe 2): fetch cluster URLs, extract full-text, aggregate via LLM, merge with web-search dossier. T1 fetch+extract, T2 aggregator+merge, T3 integration all shipped. A/B compare report deferred. | ✅ Done |
| WP-AGGREGATOR-CHUNKING | Chunked two-phase aggregation. Phase 1 (per-article extraction, Gemini 3 Flash) parallel chunks ceil(N/10) with intelligent retry. Phase 2 (cross-corpus reducer, Opus 4.6 @ temp 0.1 reasoning=none) single call over all analyses. Eliminates Rule 1 violations on ≥17-article inputs. | ✅ Done |
| WP-T4-COMPARE | Production vs Hydrated A/B compare orchestrator. scripts/compare_pipelines.py runs both pipelines on shared editor assignments, extracts deterministic metrics per topic, produces markdown report for qualitative review. Also bounds HTTP read timeout at 300s to prevent streaming stalls. | ✅ Done |
| WP-MAX-TOKENS-UNIFORM | Uniform max_tokens=32000 default across all agents in src/agent.py. Removes per-agent overrides (curator, writer, qa_analyze, perspektiv_sync). Prevents context-window overflow; max observed QA output across 28 production runs was ~10K tokens. | ✅ Done |
| WP-STRUCTURED-OUTPUTS | Strict-mode JSON schemas via OpenRouter response_format. All 8 active production agents (Curator, Editor, Researcher PLAN, Researcher Assemble, Perspektiv, Writer, QA+Fix, Bias Detector) now route through src/schemas.py. Provider-side decoder constraint replaces post-hoc parsing as primary path; defense-in-depth (_extract_dict, _extract_list, _parse_json, json_repair) retained as fallback. Originary-Output-Prinzip now structurally enforced — agents mechanically cannot emit Python-owned fields. | ✅ Done |
| WP-SEO | Meta-Tags, OpenGraph, Sitemap (pre-launch) | ⬜ Planned |
| WP-CACHING | Prompt caching via OpenRouter | ⬜ Planned |
| WP-OPUS-4.7-MIGRATION | Migrate all current Opus 4.6 agents (Editor, Perspektiv, Writer, Bias Language, Phase 2 reducer) to Opus 4.7 simultaneously. Requires src/agent.py refactor: drop temperature/top_p/top_k for 4.7 calls, add output_config.effort mapping to replace current reasoning-level logic, verify OpenRouter pass-through. Per-agent effort-level eval needed before cutover. | ⬜ Planned |

### H2.2b — Rendering ✅ Complete

Topic Package → HTML renderer (`scripts/render.py`). Self-contained HTML, no JavaScript, stdlib-only Python.

**12-section layout:** Header → Metadata Bar → Radial Source Network → Reader Note → Article (with resolved source refs) → Perspectives (stakeholder cards) → Missing Voices → Divergences → Bias Card (language findings + source balance chart) → Coverage Gaps → Sources Table → Transparency Trail.

**Radial Source Network:** SVG visualization showing source distribution across 8 fixed world regions. Country nodes sized by source count, positioned in fixed regional sectors. Empty sectors communicate coverage gaps. CSS-only hover reveals country names. Country badges below as mobile fallback.

**Design system:** Flat colors, muted semantic palette (teal/amber/dark-red for representation/significance/severity), slate typography, 740px max-width, mobile-responsive at 768px breakpoint. Non-Latin scripts (Farsi RTL, CJK) handled with proper `lang` and `dir` attributes.
### H2.2 — Pipeline Agents ✅ Complete

All pipeline agent slots are filled. Model assignments validated through 90+ eval calls across 14 models (April 2026).

| Agent | Model | Reasoning | Eval Status | Tier |
|-------|-------|-----------|-------------|------|
| Collector (Planner) | — (disabled) | — | RSS feeds provide sufficient coverage | — |
| Collector (Assembler) | — (disabled) | — | — | — |
| **Curator** | **Gemini 3 Flash** | **none** | ✅ 14 models, 5 reasoning levels | **A** |
| **Editor** | **Opus 4.6** | **none** | ✅ 4 models, 2 reasoning levels | **8.5/10** |
| **Researcher (Planner)** | **Gemini 3 Flash** | **none** | ✅ 5 models, A-Tier | **A** |
| **Researcher (Assembler)** | **Gemini 3 Flash** | **none** | ✅ 5 models, A-Tier. GLM 5 disqualified (fabricates actors) | **A** |
| **Perspektiv** | **Opus 4.6** | **none** | ✅ 4 models, 2 reasoning levels | **8.5/10** |
| **Writer** | **Opus 4.6** | **none** | ✅ 5 models, A-Tier. Best journalism quality, 80K tokens (many web_search calls) | **A** |
| **QA+Fix** | **Sonnet 4.6** | **none** | ✅ 4 models, 2 reasoning levels. Now combined analyze+fix role | **8/10** |
| **Bias Language** | **Opus 4.6** | **none** | ✅ 4 models, 2 reasoning levels | **9/10** |
| **Hydration Aggregator Phase 1** | **Gemini 3 Flash** | **none** | Per-article extraction; chunks ceil(N/10); production since Session 12 | — |
| **Hydration Aggregator Phase 2** | **Opus 4.6** | **none** | Cross-corpus reducer; 5-variant blind eval scored 114/120 (A Opus 4.7 ref=117, C Sonnet 4.6=108, D Gemini Pro=75-90); temp 0.1 aligns with other synthesis agents | **114/120** |

**Phase 2 Reducer Eval (April 22 2026):** Five models tested blindly on 3 topics × 4 dimensions (Divergence Specificity, Groundedness, Gap Substance, Bias-card Utility). Opus 4.7 @ temp 0.3 ref = 117/120. Opus 4.6 @ temp 0.3 = 114/120. Sonnet 4.6 @ temp 0.3 = 108/120 (two factual errors on large corpora). Gemini 3.1 Pro low/high = 75-90/120 (structural divergence-output ceiling, unaffected by temperature 0.1/0.3/0.5 in sub-eval). Temperature sub-eval confirmed: Sonnet @ 0.1 shifts error pattern without eliminating it; Gemini has a model-in-role ceiling. Integrated Opus 4.6 @ temp 0.1 (aligns with other synthesis agents). Opus 4.7 deferred to dedicated migration workstream.

**WP-EVAL-GAP Results (April 2026):** Direct evaluation overturned the Assembler-proxy assumption. GLM 5 failed 3 of 4 roles — bias_language (copies input verbatim, 2-3/10), editor (misses critical issues), qa_analyze (too conservative). Opus 4.6 is the quality leader for editorial/analytical tasks. Sonnet 4.6 r-none wins qa_analyze. Sonnet r-medium crashes 50% of the time — never use. Gemini r-medium is the budget alternative across all roles but requires reasoning=medium (r-none catastrophically fails on editor).

**Researcher + Writer Eval (April 2026):** Gemini 3 Flash is A-Tier on both Researcher Plan and Assembler at ~$0.006 combined — replaces GLM 5. Critical finding: GLM 5 fabricates actors in the Assembler role (invented "Amir Nasirzadeh" not present in input) — disqualifying for journalism. Haiku 4.5 has systemic JSON compliance issues (code fences, control characters) — disqualified. Writer: Opus 4.6 is the quality leader (~$4.10/article, 80K tokens from extensive web_search). Sonnet 4.6 is A-Tier alternative (~$1.71, 90% quality). Pipeline cost: ~$19/run (3 topics).

**Curator Model History:**
- Lauf 1–9: minimax/minimax-m2.7 (D-Tier, catastrophic over-clustering)
- Session 4 Eval: DeepSeek V3.2 recommended (B-Tier), but overflowed at full-feed input (164K limit)
- Session 4 Eval: GLM 5 Two-Stage clustering recommended (A-Tier, 100% coverage) — later rejected
- April 2026 Eval: Two-Stage architecture tested and **rejected** (hurt quality)
- April 2026 Eval: One-Pass Gemini 3 Flash selected (A-Tier, $0.33/run, reasoning=none)
### H2.3 — Globalize Source Base
From ~10 tech/business sources to 72 diverse, global sources. ✅ Done (sources.json v0.3).

**Source Tiering:** Each source receives a quality tier based on editorial reliability:
- **Tier 1 — Wire services / primary sources:** Reuters, AP, AFP, Bloomberg, official government sources
- **Tier 2 — Established outlets:** BBC, Guardian, Al Jazeera, NHK, SCMP, NPR
- **Tier 3 — Specialized sources:** Bellingcat, Foreign Policy, Defense One, The Diplomat
- **Tier 4 — Aggregators / niche sources:** Google News, analyst blogs, regional aggregators

**State affiliation flagging:** Sources with known state ties are included and tagged with a `state_affiliated` flag. The flag is transparency, not exclusion.

**Editorial independence taxonomy (4-level scale):**
- `independent` — No state funding or influence.
- `publicly_funded_autonomous` — State/public funding with structural independence guarantees. Examples: BBC, DW, NHK.
- `state_influenced` — State funding with visible editorial influence. Examples: TRT, Anadolu Agency.
- `state_directed` — Editorial line directly set by government. Examples: RT, CGTN, Xinhua, IRNA.

### H2.4 — OSINT Analysis Layer
Source divergence, gap analysis, geographic distribution. Partially implemented via Perspektiv Agent + deterministic enrichment.

### H2.5 — Reference Website ✅ Complete
Minimal static site (GitHub Pages). Brutalist design system. publish.py generates index + RSS. GitHub Actions deployment workflow. Custom domain configured: independentwire.org (Cloudflare DNS → GitHub Pages).

### H2.6 — Live Demo ✅ Live
Pipeline operational, publishing dossiers at independentwire.org. 13+ runs completed. Editor memory (coverage continuity) implemented. Follow-up detection working.

### H2.7 — README + Docs for Launch
Vision, architecture diagram, quick-start, contribution guide.
## H3 — Community & Growth (After Milestone)

### H3.0 — Production Hardening
- **H3.0.1** — CLI tool: `iw run`, `iw publish`, `iw fetch` via pyproject.toml entry points
- **H3.0.2** — Config file: `iw.yaml` for models, providers, max_topics, max_produce. Model presets (`cost-optimized`, `quality-max`)
- **H3.0.3** — User onboarding: `iw init` setup wizard (API keys, provider, feeds)
- **H3.0.4** — Budget limits: max_cost_per_run parameter, token-cost accumulator with abort on threshold
- **H3.0.5** — Output safety check: post-Writer LLM call to flag defamation, discrimination, harmful content
- **H3.0.6** — Input sanitizing: RSS feed title/summary validation against prompt injection
- **H3.0.7** — Continuous evals: weekly Claude-judge scoring of dossier quality (source diversity, perspective breadth, writing quality)
- **H3.0.8** — Monitoring dashboard: historical run stats, cost trends, quality metrics over time

### H3.1 — Visibility
- Hacker News, Fediverse, Reddit, conferences
- **H3.2** — Community infrastructure (Discussions, Issues, prompt library)
- **H3.3** — Sustainability
  - No commercial model. No advertising. No investor equity.
  - Operating cost target: <$1/run (~$30/month for daily operation)
  - Funding paths: community sponsorship (GitHub Sponsors), public interest grants (Prototype Fund, Mozilla Foundation, Knight Foundation), institutional partnerships
  - Reference Instance hosting: dedicated funding track (see WP-MCP-SERVER.md)
- **H3.4** — Additional output formats
  - Topic Package JSON is the primary output format. HTML rendering (independent-wire.org) is one rendering of this data.
  - Alternative renderings (Markdown, PDF, newsletter, podcast script) can be built against the documented schema.
  - Community-contributed renderings are welcome — the pipeline produces structured data, not a specific visual format.
  - Planned: API, podcast, newsletter, localization
- **H3.4b** — MCP Server: Topic Packages as structured data for Claude, ChatGPT, and other MCP-capable clients. First building block of the Reference Instance strategy (see WP-MCP-SERVER.md)
- **H3.5** — Technical evolution (Docker, parallelization, narrative tracking)
- **H3.6** — Structured event data: Evaluate ACLED and GDELT as supplementary signal sources
- **H3.7** — Telegram OSINT ingestion: Direct Telegram API integration for curated OSINT channels

---

## Principles

1. **Openness over perfection** — publish early, iterate
2. **Transparency as feature** — document every design decision
3. **Simplicity over complexity** — one person must be able to set it up
4. **Honesty about limits** — communicate what the system cannot do
5. **Community over control** — make decisions that enable participation

---

## Architecture Decisions (April 2026)

| Decision | Detail | Date |
|----------|--------|------|
| Source tiering | 4-tier system (Wire → Established → Specialized → Aggregator) | 2026-04-04 |
| State affiliation | Transparency flag, not exclusion | 2026-04-04 |
| Editorial independence | 4-level scale: independent → publicly_funded → state_influenced → state_directed | 2026-04-04 |
| Collector deduplication | Exact duplicates only (>95%) — framing differences are analytically valuable | 2026-04-04 |
| World Monitor as reference | Feed catalog as research starting point, no code import | 2026-04-04 |
| Two-phase agents | Researcher and Collector split into Plan → Python search → Assemble | 2026-04-07 |
| Collector disabled | RSS feeds (72 sources) provide sufficient coverage | 2026-04-07 |
| Bias Card as hybrid | Python aggregates upstream data; slim LLM call adds language analysis + reader note | 2026-04-07 || Writer-Correction retry | Max 3 attempts with Python-Verify gate. Only unapplied corrections re-sent | 2026-04-07 |
| Planner models | Gemini 3 Flash for planners (replaced GLM-5, which needed multilingual competence but fabricated actors) | 2026-04-09 |
| Curator: MiniMax replaced | MiniMax M2.7 D-Tier → Gemini 3 Flash A-Tier. One-pass, all findings with summaries | 2026-04-09 |
| Curator: Two-Stage rejected | Two-Stage (cluster→score) tested with 10 models. Hurt quality: mega-clusters in Pass 1, loss of source_ids. One-Pass superior | 2026-04-09 |
| Curator: Reasoning OFF | Reasoning levels tested (none→high). none/minimal=A-Tier. Higher levels degrade output (mega-topics, truncation, rule violations) | 2026-04-09 |
| Curator: Python clustering rejected | Both TF-IDF (mega-cluster) and Jaccard (85% singletons) fail catastrophically on news titles. Semantic similarity needed, not lexical | 2026-04-09 |
| Reasoning OFF globally | Eval 2 showed no quality improvement from reasoning for any role (Planner, Assembler, Writer). All structured-extraction tasks perform best without reasoning | 2026-04-08 |
| GLM 5 provider risk | Z.ai no longer listed as direct provider on OpenRouter. 15 third-party providers with 204K context. Monitoring needed | 2026-04-08 |
| Qwen excluded | Qwen models collect prompt/completion data — incompatible with Independent Wire's transparency principles | 2026-04-08 |
| Deterministic enrichment | Python computes geographic_coverage, missing_regions, languages, source_diversity, topic_slug. LLM does not compute metadata | 2026-04-08 |
| GLM 5 removed globally | Fabricates actors (Assembler), copies input verbatim (Bias), misses critical issues (Editor, QA). Replaced by Opus 4.6, Sonnet 4.6, Gemini 3 Flash | 2026-04-09 |
| Final model assignments | 3 models: Gemini 3 Flash (Curator, Researcher), Opus 4.6 (Editor, Perspektiv, Writer, Bias), Sonnet 4.6 (QA). All reasoning=none. | 2026-04-09 |
| Haiku 4.5 disqualified | Systemic JSON compliance issues (code fences, unparseable control characters). Not suitable for any pipeline role | 2026-04-09 |
| Sonnet r-medium: hard veto | Crashes 2/4 agents (50% failure rate). Never use Sonnet with medium reasoning | 2026-04-09 |
| Pipeline cost baseline | Lauf 10: $7.84/run. Lauf 11 (QA+Fix): €3.27/run (-58%). Monthly: ~€98 at daily runs | 2026-04-13 |
| QA+Fix merge | QA-Analyze + Writer-Correction merged into single Sonnet call. Eliminated 3× Opus retry loop. -54% tokens, -47% runtime | 2026-04-13 |
| Agent input filtering | Each agent receives only needed context keys. No more **assignment_data spread or unfiltered dossier pass-through | 2026-04-13 |
| Agent output discipline | Agents output only fields they create. Assembler no longer outputs topic_id/research_queries. No pass-through of upstream data | 2026-04-13 |
| WP-RENDERING complete | render.py: TP JSON → self-contained HTML. 12 sections, radial source network SVG, CSS-only hover, no JS | 2026-04-13 |
| SVG world map rejected | Pre-made SVG maps have unreliable country IDs. Dot map lacked geographic context. Radial network graph chosen instead | 2026-04-13 |
| No JavaScript in rendered output | All interactivity via CSS :hover on SVG groups. Native SVG <title> tooltips as fallback. Country badges below graph for mobile | 2026-04-13 |
| Flat color design | Gradients and bézier curves tested and rejected for visual consistency. Flat fills matching badge colors, straight connection lines | 2026-04-13 |
| Brutalist design system | Space Mono (monospace) + Space Grotesk (sans). Black 3px borders, no border-radius, no shadows. Single Google Fonts import as only external dependency | 2026-04-14 |
| Publication site architecture | publish.py generates static site from rendered TPs. No SSG (Jekyll/Hugo). index.html + feed.xml + reports/*.html. GitHub Actions deploys site/ to Pages | 2026-04-14 |
| React prototyping workflow | Visual design decisions made via React artifacts (instant feedback), then translated to Python. Faster than iterating through Claude Code for visual work | 2026-04-14 |
| No JavaScript in output | All interactivity via CSS :hover on SVG groups. JS appendChild approach tested and reverted (breaks CSS hover). One future exception: cross-section hover (P5) | 2026-04-14 |
| Site live | GitHub Pages deployed with custom domain independentwire.org via Cloudflare DNS | 2026-04-14 |
| WP-MEMORY-V1 | Editor coverage continuity + follow-up detection. Editor sees previous 7 days of TPs. Writer gets minimal follow-up context (headline + reason only). Articles must stand alone. | 2026-04-14 |
| Reference Instance strategy | Two-track approach: (A) Community adapts pipeline for open-source models, (B) Funded reference instance provides TPs via MCP/API to all. Tracks are complementary, not exclusive. | 2026-04-14 |
| Curator capacity separation | max_topics=10 (Editor sees), max_produce=3 (pipeline produces). Curator targets 10-20 clusters. Cheap steps work broad, expensive steps work selective. | 2026-04-15 |
| Priority-0 filter | Editor rejects topics with priority 0. Pipeline filters them before production — no API spend on rejected topics. | 2026-04-15 |
| Tiebreaker for production | Priority desc → source_count desc → array position. Editor decides, Python executes. No Python second-guessing of editorial judgment. | 2026-04-15 |
| LLM null-string sanitizing | Recursive normalizer converts string "null"/"None"/"N/A"/"" to actual None. Defense in depth: render.py also guards against display. | 2026-04-15 |
| Source recency awareness | URL date extraction in Python. Assembler prompt includes estimated_date field. Pipeline warns on sources >30 days old. Flag, never filter — old sources may be the only voice from a critical region. | 2026-04-15 |
| Bias card collapse | Reader note stays prominent. Detailed findings + source balance behind native HTML details/summary. No JavaScript. Reduces alarm fatigue. | 2026-04-15 |
| Writer prompt tightened | Pipeline conditionals removed (perspective_analysis always present). Redundancies deduplicated. Prose structure guidance added. 99→77 lines, ~30% reduction. | 2026-04-15 |
| Dead prompts cleaned | curator/CLUSTER.md, curator/SCORE.md (Two-Stage), researcher/AGENTS.md (monolithic) deleted. Only active prompts remain in agents/. | 2026-04-15 |
| Auto-deploy | run.py --publish now git add + commit + push site/ after publish.py. GitHub Actions triggers automatically. | 2026-04-15 |
| Hydration pipeline (Etappe 2) architecture | Parallel pipeline, not modification of production. `src/pipeline_hydrated.py` will be a copy with Hydration steps inserted between Editor and Researcher. Production pipeline stays untouched; A/B comparison becomes the validation path. | 2026-04-20 |
| Hydration fetch client: aiohttp over httpx | Empirically chosen in Spike B. aiohttp tolerates Anadolu Agency's non-conformant Transfer-Encoding headers that httpx rejects. Recovered +6 URLs (+11.8pp success rate) on the Lauf-19 URL set. | 2026-04-20 |
| Hydration scraping ethics | Identifiable user-agent (`Independent-Wire-Bot/1.0 +https://independentwire.org`), 1 req/s per domain, robots.txt respected, no Cloudflare/CAPTCHA/paywall circumvention. Full-text used only as LLM context, never reproduced verbatim in published article. Equivalent moral weight to existing Perplexity reliance; ownership and transparency shifted to us. | 2026-04-20 |
| Hydration Aggregator model | `google/gemini-3-flash-preview`. 100% structural compliance in Spike C vs flash-lite's 11/12 (Rule-1 disqualification). ~$0.015 per topic. | 2026-04-20 |
| Hydration Aggregator fetch filter | Only records with T1 `status == "success"` are passed to the Aggregator. Partial/bot_blocked/error records excluded. Aggregator prompt was tuned on full-text inputs and partial stubs would degrade analysis quality. | 2026-04-20 |
| Hydration Planner input: coverage_summary | Hydrated Research Planner receives a 5-field Python-computed coverage summary (`total_sources`, `languages_covered`, `countries_covered`, `stakeholder_types_present`, `coverage_gaps`) instead of the full pre-dossier. Agent gets only what it needs; Python does the aggregation. Applies Principles 1 and 2 at the prompt boundary. | 2026-04-20 |
| Merge URL blocklist | Web-search results are filtered in Python against the set of pre-dossier URLs (with status=success) before entering the Assembler. Blocked URLs that failed T1 fetch (paywalls, Cloudflare) are NOT in the blocklist — web-search may still surface them via syndication or caching. | 2026-04-20 |
| Merge source order | Pre-dossier sources first (rsrc-001..N, full-text based), web-search sources after (rsrc-N+1..M, snippet based). Writer can infer source quality from position. | 2026-04-20 |
| Canonical actor shape: five fields | All actor objects across the Hydration pipeline carry {name, role, type, position, verbatim_quote}. verbatim_quote is populated from hydrated full-text via the Aggregator; it is null for web-search-derived actors (snippets cannot produce trustworthy verbatim quotes). Python normalizes the web-search side before merge. Researcher Assembler prompt remains unchanged (four-field output); normalization is a Python concern. | 2026-04-20 |
| Contract discipline as project-wide rule | Output schemas from task briefs are complete specifications, not starting points. Unlisted fields are not added silently; useful telemetry is surfaced as a question. Established after T1 `fetch_started_at` drift and applied from T2 forward. | 2026-04-20 |
| Principle 2 extended to Perspektiv-Sync | Perspektiv-Sync emits delta-only output (`stakeholder_updates[]`), not full map rewrite. Python merges deltas into a deep-copied original map. Field-absence vs null carries semantic weight: absence = do not touch, null = remove. Checks use `"field" in delta`, never `delta.get(...) is None`. | 2026-04-21 |
| Writer-Sources contract | Writer emits only `{id, rsrc_id}` references. Python (`_merge_writer_sources`) merges full metadata (url, outlet, language, country, estimated_date, actors_quoted incl. verbatim_quote) from the Researcher dossier. QA+Fix receives merged full source objects; the Writer never handles pass-through source metadata. | 2026-04-21 |
| Source-ID invariant strengthened | Final Topic Package guarantees: (a) sequential `src-NNN` starting at src-001 with no gaps; (b) every `[src-NNN]` in body/headline/subheadline/summary has a matching entry in `sources[]`; (c) every `sources[]` entry is cited at least once. Unreferenced sources are dropped (not preserved as orphans); an empty-result collapse falls back to the pre-fix state with a warning. | 2026-04-21 |
| Perspectives source_ids use src-NNN | `stakeholders[*].source_ids` use `src-NNN` (matching the rest of the TP), not `rsrc-NNN`. Stakeholders whose only backing source dropped out of the final array are retained with empty `source_ids` — they remain stakeholders in the landscape even without a currently-cited article. | 2026-04-21 |
| TP schema duplicate removal | Canonical locations: `bias_analysis.framing_divergences` and `bias_analysis.perspectives.missing_voices`. Previously-duplicated `transparency.framing_divergences` and top-level `gaps[]` are no longer populated. Renderer reads from canonical locations only. | 2026-04-21 |
| Writer Rule 8: single JSON output | Writer explicitly forbidden from emitting revision attempts, chain-of-thought commentary, or second JSON blocks. Mitigation against parser fragility observed after the Writer-sources refactor (Writer occasionally emitted two JSON objects with "Wait, I need to fix…" interludes). | 2026-04-21 |
| Editor selection_reason qualitative only | Editor does not emit numeric source counts, language counts, or specific outlet brand names in `selection_reason`. Numeric discipline lives in Python — counting is Python's job per Principle 1. Regional attribution ("French outlets", "Russian state media") remains permitted. | 2026-04-21 |
| max_tokens uniform at 32000 | Single module-level default in src/agent.py. All per-agent overrides in scripts/run.py, src/pipeline.py, src/pipeline_hydrated.py removed. Prior 65536 default risked context-window overflow on large inputs; 32K carries ~3x headroom on the empirically measured ~10K max QA output across 28 production runs. | 2026-04-22 |
| HTTP read timeout 300s | AsyncOpenAI client in src/agent.py uses explicit httpx.Timeout(connect=30, read=300, write=30, pool=30). Default 10-minute read timeout allowed streaming stalls to hang pipeline indefinitely; 300s read bound makes stalled responses fail deterministically. Surfaced by a T4 smoke hang on a Sonnet QA streaming response. | 2026-04-22 |
| Aggregator chunking | ceil(N/10) chunks, distributed evenly, each chunk 5-10 articles. Phase 1 chunk calls run in parallel via asyncio.gather. Intelligent retry per chunk (max 2) sends only the missing article indices back as a smaller new input. Hard crash if chunk still incomplete after 2 retries — silent data loss is worse than failure. Eliminates the off-by-one Rule 1 violations Gemini 3 Flash exhibited on ≥17-article inputs. Scales to arbitrary N without architectural change. | 2026-04-22 |
| Aggregator two-phase reducer | Phase 1 (per-chunk, parallel) produces only `article_analyses[]`. Phase 2 (single call, sequential after Phase 1) takes the merged analyses plus per-article metadata and produces `preliminary_divergences[]` + `coverage_gaps[]`. Cross-linguistic divergences require seeing the full corpus, which chunked extraction cannot. Phase 2 input is compact (summaries, not full-text) so attention load is low regardless of N. | 2026-04-22 |
| Counting is Python's job, always | Prompt engineer correction during Phase 1 prompt review. Aggregator prompts never ask the LLM to count its output, self-verify array length, or enforce expected_count. Deterministic validation happens in src/hydration_aggregator.py after each LLM response; missing indices trigger retry. Generalizes Principle 1 ("deterministic before LLM") into prompt-design discipline. | 2026-04-22 |
| Phase 2 model: Opus 4.6 @ temp 0.1 | Selected after 5-variant blind eval (Opus 4.7, Opus 4.6, Sonnet 4.6, Gemini Pro low, Gemini Pro high) and a temperature sub-eval on cheaper candidates. Score: 114/120 (A Opus 4.7 ref=117). Temp 0.1 matches all other synthesis agents (Perspektiv, QA+Fix, Perspektiv-Sync, Bias Language). Opus 4.7 deferred — breaking API changes require dedicated migration workstream. | 2026-04-22 |
| Gemini 3.1 Pro disqualified for synthesis | Eval evidence: structural divergence-output ceiling ~3-4 per topic regardless of temperature or reasoning level. OpenRouter rejects reasoning=none (400 error), silently remaps reasoning=medium (officially unsupported on Pro). High-reasoning intermittently returns empty streamed responses on small inputs. Not suitable for reducer/synthesis roles. | 2026-04-22 |
| Strict-mode JSON schemas | Eight production agents emit via OpenRouter `response_format: {type: "json_schema", strict: true}`. OpenRouter applies Anthropic `structured-outputs-2025-11-13` beta header automatically. `provider.require_parameters: true` set in extra_body to avoid silent fallback to providers that ignore the schema. `_parse_or_retry_structured` retry path explicitly suppresses schema (`output_schema=None`) so corrective prompt does not fight constrained decoding. | 2026-04-28 |
| Schema-as-code | All eight agent schemas live in `src/schemas.py` as a single source of truth. `scripts/run.py` imports them and passes `output_schema=` to each Agent constructor. Schemas use `additionalProperties: false` on every object node and list every property in `required`; optional fields modelled as `["string","null"]` and emitted as `null` by the model when not applicable. | 2026-04-28 |
| Editor INSTRUCTIONS.md V2 format | Editor prompt migrated from legacy single-file format (IDENTITY-AND-PURPOSE block, target-audience prose, 8 STEPS, 9 RULES) to the V2 two-file convention (compact TASK / STEPS / OUTPUT FORMAT / RULES; identity content lives in SYSTEM.md). Resolves Audit-Recommendation #1 from `docs/AUDIT-PIPELINE-S13-2026-04-27.md` (Editor pipeline-architecture leaks). | 2026-04-28 |
| Audit-Recs 1-7 closed | All seven recommendations from the S13 audit shipped as deterministic Python: rsrc-/src- universal sweep over the final TP, coverage_gaps validated against final source_balance, actor.region drop, bias_analysis.factual_divergences drop, selection_reason stale-quantifier strip, plus three structural cleanups uncovered during eval review. Commits ac13fd2, be2382b, f6a4c14, 92fb5ef. | 2026-04-29 |
| Hydrated pipeline active | `scripts/run.py --hydrated` switch added. Eleven hydrated agents wired (seven production-shared + researcher_hydrated_plan, hydration_aggregator_phase1, hydration_aggregator_phase2, perspektiv_sync). Output isolated to `output/{date}/test_hydration/`. Three legacy permissive `output_schema={"type":"object"}` overrides removed; HYDRATION_PHASE1/2 + RESEARCHER_PLAN schemas now strict-mode-active end-to-end. Commits 4b8cf94, eb43727→d786d8c, 69fb8b8. | 2026-04-29 |
| Hydrated-vs-Production 1:1 eval | King-Charles state-visit topic produced on both pipelines with all S15 fixes applied. Hydrated outperformed Production: 7 vs 6 perspectives, 4 vs 3 divergences, 9 vs 2 coverage gaps. Hydrated produced more depth from the same source set despite 50% T1 fetch loss (SCMP bot-blocked). Eval finding: hydrated is the production candidate going forward; eval feedback drove the V2 architecture decision. | 2026-04-29 |
| V2 Bus architecture decided | `docs/ARCH-V2-BUS-SCHEMA.md` captures the structural answer to S14/S15 aggregation bugs. RunBus + N TopicBuses, granular slots with mirror-and-modify pattern, render-as-selection via visibility metadata, bias-card as multi-slot derived view. Big-bang migration with `v1-final` git tag as rollback. Anglicises `perspektiv` → `perspective` consistently across code, prompts, and folders. | 2026-04-29 |