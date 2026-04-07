# Independent Wire — Open Source Roadmap

**Created:** 2026-03-26
**Updated:** 2026-04-07
**Status:** Living document — strategic overview.
**Basis:** Vision paper (March 2026) + PoC experience (Sessions 1–12)

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
| WP-RSS | RSS/API feed ingestion (21 sources, GDELT) | ✅ Done |
| WP-DEBUG-OUTPUT | Step-by-step debug output per pipeline step | ✅ Done |
| WP-RESEARCH | Multilingual research agent (per topic) | ✅ Done |
| WP-PARTIAL-RUN | CLI flags for partial pipeline runs (--from, --to, --topic, --reuse) | ✅ Done |
| WP-QA | QA-Analyze + Writer-Correction + Python-Verify | ✅ Done |
| WP-PERSPEKTIV | Perspective Agent (stakeholder map, missing voices, framing divergences) | ✅ Done |
| WP-RESEARCHER-SPLIT | Two-phase researcher: Plan → Python search → Assemble (eliminates context accumulation) | ✅ Done |
| WP-BIAS | Bias Transparency Card (Python aggregation + LLM language analysis) | ✅ Done |
| WP-TELEGRAM | Telegram Interface | ⬜ Planned |
| WP-MEMORY | Agent Memory (Editor coverage continuity) | ⬜ Planned |
| WP-CACHING | Prompt caching via OpenRouter | ⬜ Planned |

### H2.2 — Pipeline Agents ✅ Complete

All pipeline agent slots are filled:

| Agent | Model | Tools | Role |
|-------|-------|-------|------|
| Collector (Planner) | GLM-5 | none | Plans multilingual search queries (currently disabled — RSS feeds sufficient) |
| Collector (Assembler) | minimax-m2.7 | none | Structures raw search results (currently disabled) |
| Curator | minimax-m2.7 | none | Clusters and evaluates findings from RSS feeds |
| Editor | GLM-5 | none | Prioritizes topics, assigns topic IDs |
| Researcher (Planner) | GLM-5 | none | Plans multilingual research queries per topic |
| Researcher (Assembler) | GLM-5 | none | Assembles dossier with sources, actors, divergences |
| Perspektiv Agent | GLM-5 | none | Maps stakeholders, missing voices, framing divergences |
| Writer | GLM-5 | web_search | Writes multi-perspective article from dossier + perspectives |
| QA-Analyze | GLM-5 | none | Finds errors and divergences in article |
| Bias Language Analyzer | GLM-5 | none | Scans article for linguistic bias, writes reader note |

### H2.3 — Globalize Source Base
From ~10 tech/business sources to 40+ diverse, global sources.

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

**Reference research:** World Monitor (worldmonitor.app, AGPL-3.0) maintains 435+ curated RSS feeds. Their feed catalog serves as research starting point for expanding `sources.json`. No code imported.

### H2.4 — OSINT Analysis Layer
Source divergence, gap analysis, geographic distribution.

### H2.5 — Reference Website
Minimal static site (GitHub Pages). Radically transparent.

### H2.6 — Live Demo
One complete daily report. 15+ sources in 5+ languages.

### H2.7 — README + Docs for Launch
Vision, architecture diagram, quick-start, contribution guide.

## H3 — Community & Growth (After Milestone)

- **H3.1** — Visibility (Hacker News, Fediverse, Reddit, conferences)
- **H3.2** — Community infrastructure (Discussions, Issues, prompt library)
- **H3.3** — Funding (GitHub Sponsors, Prototype Fund, Mozilla/Knight Foundation)
- **H3.4** — Additional formats (API, RSS, podcast, newsletter, localization)
- **H3.5** — Technical evolution (Docker, parallelization, narrative tracking)
- **H3.6** — Structured event data: Evaluate ACLED and GDELT as supplementary signal sources.
- **H3.7** — Telegram OSINT ingestion: Direct Telegram API integration for curated OSINT channels.

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
| Two-phase agents | Researcher and Collector split into Plan → Python search → Assemble (eliminates context accumulation in tool loops) | 2026-04-07 |
| Collector disabled | RSS feeds (21 sources, 613 findings/day) provide sufficient coverage. Collector deactivated, code preserved for future use as pre-filter when scaling to 200+ feeds. | 2026-04-07 |
| Bias Card as hybrid | Not a separate analysis agent. Python aggregates upstream data (Perspektiv, QA, Researcher); slim LLM call adds language analysis + reader note. | 2026-04-07 |
| Writer-Correction retry | Max 3 attempts with Python-Verify gate. Only unapplied corrections are re-sent. | 2026-04-07 |
| Planner models | GLM-5 for planners (needs multilingual competence), minimax-m2.7 insufficient (script/calendar errors) | 2026-04-07 |
