# Independent Wire — Roadmap

**Created:** 2026-03-26
**Updated:** 2026-05-28
**Status:** Living document — strategic overview. The granular per-commit history lives in git, in [`AUDIT-TIMELINE.md`](AUDIT-TIMELINE.md), and in the architecture decision records (`docs/ADR-*.md`); this roadmap stays high-level on purpose.
**Basis:** the [vision paper](VISION-independent-wire.pdf) (March 2026), the working prototype, and the V2 architecture work (April–May 2026).

---

## Three Horizons

| Horizon | Timeframe | Goal |
|---|---|---|
| **H1 — Foundation** | Weeks 1–2 | Framework, schema, style, repo structure |
| **H2 — First Milestone** | Weeks 3–6 | A public live demo: one transparent daily report that proves the thesis |
| **H3 — Architecture, polish, and community** | Ongoing | Architectural maturity, content quality, community participation, more formats, funding |

---

## H1 — Foundation ✅ Complete

- [x] Architect planning partner set up
- [x] Pipeline validated on an M1 MacBook Air
- [x] Core decisions — name, domain, repo, license, language
- [x] Output schema (Topic Package v1)
- [x] No AI images — deterministic, data-driven diagrams only
- [x] Editorial style guide
- [x] Framework architecture (Agent + Pipeline + Tool, later evolved into the Bus + Stage model of V2)
- [x] Public GitHub repo with docs, schema, and concept

---

## H2 — Framework + First Milestone ✅ Complete

The core framework is operational and the pipeline publishes daily. It produces Topic Packages with multilingual research, perspective analysis, QA / fact-check, and bias-transparency cards — built on the Agent + Pipeline + Tool abstractions, later evolved into the Bus + Stage architecture of V2.

Highlights from this phase: a two-phase researcher (plan → search → assemble); a hybrid bias card (deterministic Python aggregation + LLM language analysis); strict-mode JSON schemas for every agent via OpenRouter; an HTML renderer and the publication site; and the hydration variant that fetches and extracts full article text. The production model set was settled empirically across 90+ evaluation calls.

**Public live demo:** ✅ daily publication at [independent-wire.org](https://independent-wire.org) — three Topic Packages per day, 66 sources across 11 language streams, operating cost a few euros per run (roughly €30/month for daily operation).

---

## H3 — Architecture, polish, and community

### H3.1 — V2 architecture + Triple-Stage Curator ✅ Complete

The first production pipeline (V1) used a single aggregation surface that turned out to be the source of an entire class of bugs — ID inconsistency, duplicated aggregation, pre-research artefacts leaking downstream, actor metadata grafted from the wrong dimension. V2 replaced that surface with a **Bus + Stage architecture**: one run-level bus, one bus per topic, an explicit ordered stage list per pipeline variant, and a render layer that is a pure function over bus state. Every field declares its owner and its visibility, so nothing reaches the public Topic Package that wasn't explicitly marked for it.

The V1 single-pass Curator was then replaced by a **Triple-Stage Curator**: deterministic agglomerative pre-clustering, a small-input LLM step that discovers specific stories (not categories), and deterministic assignment of findings to those stories. This made the old over-clustering pathology structurally impossible — the LLM no longer assigns findings, so the per-finding output pressure that produced catch-all clusters is gone. Validation against a 2,542-label audit set brought the aggregate off-topic rate down to 8.2% (from ~70% at an earlier threshold), with no topic above 50% off-topic.

Full specification: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`ARCH-V2-BUS-SCHEMA.md`](ARCH-V2-BUS-SCHEMA.md), and [`ADR-CURATOR-TRIPLE-STAGE.md`](ADR-CURATOR-TRIPLE-STAGE.md). Chronological history: [`AUDIT-TIMELINE.md`](AUDIT-TIMELINE.md).

### H3.2 — Content quality 🛠 In progress

With the architecture stable, the limiting factor for Topic Package quality is now the **research-planning** step: the queries the planner writes determine what evidence reaches the writer. A first iteration shipped story-shape-aware planning — different research strategies for, say, a quantitative-claim topic versus a stakeholder-conflict or a policy topic. A second iteration, a deterministic pre-planning classifier that is universal across story shapes rather than tuned to the initial six, is queued once the first is evaluated in production.

Recent completed work: a renderer-hygiene sweep, and the Consolidator refactor that collapsed three post-QA stages into one LLM stage owning a single, deduplicated "what is missing" view — which also retired an over-aggressive deterministic gap-validator that had been falsifying real coverage gaps.

### H3.3 — Next: architecture-quality follow-ups

These improve V2 further without blocking any current capability:

- Migrate the Opus-based agents from 4.6 to 4.7 (requires reworking how reasoning effort is configured per agent).
- Run multiple topics concurrently — architecturally trivial in V2, since topics share no state.
- A pre-call spending cap, to catch cost overruns before a call rather than after a phase.
- Direct institutional source fetch via a curated registry, bypassing the LLM planner for known endpoints.

### H3.4 — Later: production hardening

- An installable `independent-wire` command-line tool.
- A config file for runtime parameters.
- Pre-publish schema validators.
- Per-stage crash-recovery snapshots.

### H3.5 — Source coverage

- Grow from 66 to 100+ feeds, prioritising underrepresented regions (Latin America, sub-Saharan Africa, Southeast Asia), via a community contribution path.
- Reactivate the Collector agent as a Curator pre-filter when scaling past ~200 feeds.

### H3.6 — Community and external interfaces

- An MCP server providing Topic Packages as structured data to Claude, ChatGPT, and other LLM clients.
- An open REST API surfacing Topic Packages as JSON.
- A community-reviewed prompt library, and a collaboratively-maintained source catalog — especially from underrepresented regions.
- A trust network for community evaluation of sources and agents.
- Docker deployment and a setup wizard, so non-developers can run their own newsroom.

### H3.7 — Narrative tracking

Tracking how a story evolves across days and weeks — enabled by the run bus's previous-coverage slot and the Editor's follow-up logic, extendable into a multi-run analysis layer.

---

## Sustainability and funding

No commercial model. No advertising. No investor equity. Operating-cost target: a few euros per run, roughly €30/month for daily operation. Funding paths: community sponsorship, public-interest grants, institutional partnerships. The system is designed so its operating costs can never create pressure to compromise editorial independence.

---

## Vision alignment

Every work-stream above traces back to the [vision paper](VISION-independent-wire.pdf). The five-dimensional bias card (language, source, geographical, selection, framing) is implemented as a derived view assembled at render time. The transparency-first principle is structurally enforced: nothing reaches the public Topic Package that wasn't explicitly marked visible.

The external vision paper will be updated once enough production experience has accumulated under the V2 architecture; until then, this roadmap and the architecture docs are the current reference.

**What still doesn't exist — and why that is honesty, not a gap to paper over:**

- **Investigative journalism** — AI cannot replace humans on the ground. The system relieves routine work so investigative work can stay human.
- **Real bias elimination** — the models carry training bias forward; the goal is bias *transparency*, not bias absence.
- **Author voice** — AI has no lived experience; the system uses its own deliberately flat style rather than imitating one.
- **Relevance judgement** — what matters to whom is contextual; the system makes structural distortion visible rather than claiming objective relevance.

A system that knows and communicates its limits is more trustworthy than one that promises objectivity it cannot deliver.
