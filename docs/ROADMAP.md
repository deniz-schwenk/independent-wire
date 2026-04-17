# Independent Wire — Open Source Roadmap

**Created:** 2026-03-26
**Updated:** 2026-04-16 (Session 10 — Sustainability principles, output format clarification, eval workflow planned)
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
| WP-SEO | Meta-Tags, OpenGraph, Sitemap (pre-launch) | ⬜ Planned |
| WP-CACHING | Prompt caching via OpenRouter | ⬜ Planned |

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