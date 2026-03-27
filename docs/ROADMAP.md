# Independent Wire — Open Source Roadmap

**Created:** 2026-03-26
**Updated:** 2026-03-27
**Status:** Living document

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

| WP | Name | Description | Depends On |
|----|------|-------------|------------|
| WP-AGENT | Agent Abstraction | `src/agent.py` — LLM call via OpenRouter, prompt loading, tool loop | — |
| WP-TOOLS | Tool System | `src/tools/` — web_search, file_ops + ToolRegistry | WP-AGENT |
| WP-PIPELINE | Pipeline Orchestration | `src/pipeline.py` — sequential steps, validation, gating | WP-AGENT |
| WP-TELEGRAM | Telegram Interface | `src/telegram.py` — status updates + gating | WP-PIPELINE |
| WP-MEMORY | Agent Memory | Memory loading/saving in Agent.run() | WP-AGENT |
| WP-AGENTS | Agent Prompts | All AGENTS.md rewritten for Independent Wire | WP-AGENT |
| WP-INTEGRATION | End-to-End | Full pipeline run → Topic Package JSON | All |

### H2.2 — New Agents
- **Perspektiv-Agent:** Researches spectrum of positions per topic
- **Bias-Detektor:** Analyzes text for bias across 5 dimensions

### H2.3 — Globalize Source Base
From ~10 tech/business sources to 40+ diverse, global sources.

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

---

## Principles

1. **Openness over perfection** — publish early, iterate
2. **Transparency as feature** — document every design decision
3. **Simplicity over complexity** — one person must be able to set it up
4. **Honesty about limits** — communicate what the system cannot do
5. **Community over control** — make decisions that enable participation
