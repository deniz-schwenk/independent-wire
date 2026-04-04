# Independent Wire — Open Source Roadmap

**Created:** 2026-03-26
**Updated:** 2026-04-04
**Status:** Living document — strategic overview. For operational task tracking see [TASKS.md](TASKS.md).
**Basis:** Vision paper (March 2026) + PoC experience (Sessions 1–8) + World Monitor competitive analysis (April 2026)

---

## Three Horizons

| Horizon | Timeframe | Goal |
|---------|-----------|------|
| **H1 — Foundation** | Weeks 1–2 | Framework, schema, style, repo structure |
| **H2 — First Milestone** | Weeks 3–6 | Public live demo: one transparent daily report that proves the thesis |
| **H3 — Community & Growth** | After | Visibility, participation, additional formats, funding |

---

## H1 — Foundation (Weeks 1–2)

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

Core framework is operational. First successful end-to-end pipeline run completed 2026-03-30 (2/3 Topic Packages produced). For detailed task tracking, prompt fixes, and pipeline fixes see [TASKS.md](TASKS.md).

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
| WP-RESEARCH | Multilingual research agent (per topic) | 🔜 Next |
| WP-TELEGRAM | Telegram Interface | ⬜ Planned |
| WP-MEMORY | Agent Memory | ⬜ Planned |

### H2.2 — New Agents
Pipeline slots exist, prompts not yet written.
- **Perspective Agent:** Researches spectrum of positions per topic
- **Bias Detector:** Analyzes text for bias across 5 dimensions
- **QA / Fact-Check:** Verifies all factual claims against sources

### H2.3 — Globalize Source Base
From ~10 tech/business sources to 40+ diverse, global sources.

**Source Tiering:** Each source receives a quality tier based on editorial reliability:
- **Tier 1 — Wire services / primary sources:** Reuters, AP, AFP, Bloomberg, official government sources
- **Tier 2 — Established outlets:** BBC, Guardian, Al Jazeera, NHK, SCMP, NPR
- **Tier 3 — Specialized sources:** Bellingcat, Foreign Policy, Defense One, The Diplomat
- **Tier 4 — Aggregators / niche sources:** Google News, analyst blogs, regional aggregators

Tiering serves the Perspective Agent and Bias Detector as a weighting signal — not as a filter. All tiers are included; the tier flows into the transparency card.

**State affiliation flagging:** Sources with known state ties (e.g. RT, Xinhua, IRNA, TRT, CGTN) are included and tagged with a `state_affiliated` flag. The flag is transparency, not exclusion.

**Editorial independence taxonomy (4-level scale):**
- `independent` — No state funding or influence. Funded by subscriptions, ads, foundations.
- `publicly_funded_autonomous` — State/public funding with structural independence guarantees (editorial charters, broadcasting councils). Examples: BBC, DW, NHK.
- `state_influenced` — State funding with visible editorial influence, but not full control. Examples: SCMP (post-Alibaba), TRT, Anadolu Agency.
- `state_directed` — Editorial line directly set by government. No independent editorial board. Examples: RT, CGTN, Xinhua, IRNA, Press TV.

**Important caveat (must appear on transparency card):** Editorial independence describes the visible structural relationship between source and state power. It does not capture hidden funding, corporate ownership interests, ideological alignment, or advertising pressure. A structurally independent source can still be biased. A state-directed source can still report facts accurately. This field is one input among many — not a quality judgment.

**Collector deduplication:** Exact duplicates only (identical URL or >95% text similarity). Lower thresholds (e.g. 60% Jaccard) are deliberately NOT used — framing differences between outlets are analytically valuable for the Perspective Agent and Bias Detector.

**Reference research:** World Monitor (worldmonitor.app, AGPL-3.0, github.com/koala73/worldmonitor) maintains 435+ curated RSS feeds with a 4-tier system and state-affiliation flags. Their feed catalog serves as research starting point for expanding `sources.json`. No code imported — only feed URLs and categorization concepts as inspiration.

**OSINT source verification (H2 task):** World Monitor curates 26 Telegram OSINT channels (Aurora Intel, BNO News, Bellingcat, LiveUAMap etc.). Verify which offer free RSS/web alternatives; add those to `sources.json` if valuable. Direct Telegram API integration deferred to H3.

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
- **H3.6** — Structured event data: Evaluate ACLED (conflict/protest database) and GDELT (global event DB with tone analysis) as supplementary signal sources for the Collector. Both offer free API access. Potential: topic discovery triggers, geographic coverage validation, cross-referencing pipeline output against structured event data.
- **H3.7** — Telegram OSINT ingestion: Direct Telegram API integration (GramJS/MTProto) for 26+ curated OSINT channels as real-time source layer. Requires separate infrastructure (MTProto client, message polling, deduplication). Web/RSS equivalents integrated in H2 where available.

---

## Principles

1. **Openness over perfection** — publish early, iterate
2. **Transparency as feature** — document every design decision
3. **Simplicity over complexity** — one person must be able to set it up
4. **Honesty about limits** — communicate what the system cannot do
5. **Community over control** — make decisions that enable participation

---

## Decisions Made (April 2026)

| Question | Decision | Date |
|----------|----------|------|
| Source tiering | **4-tier system** (Wire → Established → Specialized → Aggregator) in `sources.json` | 2026-04-04 |
| State affiliation | **Transparency flag**, not exclusion — `state_affiliated` + `editorial_independence` fields | 2026-04-04 |
| Editorial independence taxonomy | **4-level scale**: `independent` → `publicly_funded_autonomous` → `state_influenced` → `state_directed` | 2026-04-04 |
| Collector deduplication | **Exact duplicates only** (>95%) — lower thresholds destroy analytically valuable framing differences | 2026-04-04 |
| World Monitor as reference | **Feed catalog as research starting point** for `sources.json`, no code import | 2026-04-04 |
