# Independent Wire — Open Source Roadmap

**Created:** 2026-03-26
**Updated:** 2026-05-02 (V2 big-bang architecture work-stream complete; documentation reconciled)
**Status:** Living document — strategic overview.
**Basis:** Vision paper (March 2026) + PoC experience (Sessions 1–12) + Model Evals (Sessions 4–5) + Cost Optimization (Session 6) + Rendering + Website (Session 7) + V2 architecture (April–May 2026)

---

## Three Horizons

| Horizon | Timeframe | Goal |
|---------|-----------|------|
| **H1 — Foundation** | Weeks 1–2 | Framework, schema, style, repo structure |
| **H2 — First Milestone** | Weeks 3–6 | Public live demo: one transparent daily report that proves the thesis |
| **H3 — Architecture, Polish, and Community** | After | Architectural maturity, content quality, community participation, additional formats, funding |

---

## H1 — Foundation (Weeks 1–2) ✅ Complete

- [x] **H1.1** — Set up architect project (Claude project as permanent planning partner)
- [x] **H1.2** — Validate pipeline on M1 (PoC pipeline runs on MacBook Air M1)
- [x] **H1.3** — Core decisions (name, domain, repo, license, language)
- [x] **H1.4** — Output schema (Topic Package v1)
- [x] **H1.5** — Designer pivot (no AI images → deterministic Mermaid diagrams)
- [x] **H1.6** — Editorial style guide
- [x] **H1.7** — Framework architecture (Agent + Pipeline + Tool — V1 framing; V2 replaced Pipeline with Bus + Stage)
- [x] **H1.8** — GitHub repo with docs, schema, and concept

---

## H2 — Framework + First Milestone (Weeks 3–6) ✅ Complete

### H2.1 — Build Framework (Work Packages)

Core framework operational. Pipeline produces Topic Packages with multilingual research, perspective analysis, QA, and bias transparency cards.

| WP | Name | Status |
|----|------|--------|
| WP-AGENT | Agent Abstraction | ✅ Done |
| WP-TOOLS | Tool System (multi-provider search, web_fetch, file_ops) | ✅ Done |
| WP-PIPELINE | V1 Pipeline Orchestration | ✅ Done — superseded by V2 |
| WP-STRUCTURED-RETRY | JSON parsing retry logic | ✅ Done |
| WP-AGENTS | Agent Prompts (Collector, Curator, Editor, Writer) | ✅ Done |
| WP-INTEGRATION | End-to-End pipeline run | ✅ Done |
| WP-REASONING | Configurable reasoning effort per agent | ✅ Done |
| WP-RSS | RSS/API feed ingestion (72 sources) | ✅ Done |
| WP-DEBUG-OUTPUT | Step-by-step debug output per pipeline step | ✅ Done |
| WP-RESEARCH | Multilingual research agent (per topic) | ✅ Done |
| WP-PARTIAL-RUN | CLI flags for partial pipeline runs (`--from`, `--to`, `--topic`, `--reuse`) | ✅ Done |
| WP-QA | QA-Analyze + Writer-Correction + Python-Verify | ✅ Done |
| WP-PERSPEKTIV | Perspective Agent (stakeholder map, missing voices, framing divergences) | ✅ Done — anglicised in V2 |
| WP-RESEARCHER-SPLIT | Two-phase Researcher: Plan → Search → Assemble | ✅ Done |
| WP-BIAS | Hybrid Bias Card: Python aggregation + LLM language analysis | ✅ Done |
| WP-MODEL-EVAL | 90+ eval calls; final model set: Gemini 3 Flash, Opus 4.6, Sonnet 4.6 | ✅ Done |
| WP-RENDERING | Topic Package → HTML renderer | ✅ Done |
| WP-WEBSITE | Publication site `independent-wire.org` | ✅ Done |
| WP-HYDRATION-T1/T2/T3 | Hydration variant: aiohttp fetch + two-phase aggregator + hydrated pipeline | ✅ Done |
| WP-S13 | Two-file prompt convention; three-block User layout | ✅ Done |
| WP-STRUCTURED-OUTPUTS | Strict-mode JSON schemas via OpenRouter `response_format` (all 11 agents) | ✅ Done |

### H2.2 — Public live demo

✅ Daily publication operational at `independent-wire.org`. Three Topic Packages per day. 72 sources. 20+ languages. Pipeline cost ~€3.30 per run (€~1 for production variant alone), ~€30/month for daily operation.

---

## H3 — Architecture, Polish, and Community

### H3.1 — V2 Architecture (April–May 2026) ✅ Complete

**Goal:** make the pipeline architecturally clean enough that future content quality work can happen without fighting the structure.

V1 had aggregation surface as the source of all five S14/S15 bug classes (ID-consistency, aggregation duplications, pre-research artefacts surviving downstream, per-actor metadata grafted from wrong dimensions, editor-time selection_reason becoming false). V2 replaced aggregation with a **Bus + Stage architecture**: one RunBus, N TopicBuses, one stage list per variant, one render layer that filters by visibility metadata.

| WP | Status |
|----|--------|
| WP-V2-BUS-ARCHITECTURE | ✅ Complete — V2-01 through V2-11b shipped April 30 – May 1 2026. V1 deleted in commit 19348f3. Source-level closed. Documentation reconciled in V2-DOC-RECONCILE (this commit). |

**Key architectural changes:**
- Granular Bus slots with declared owner, visibility, and mirrors_from metadata.
- Empty-then-fill mirror pattern (slot-level for monolithic slots, per-element for collections).
- Hierarchical Bus separation (run-scoped vs. topic-scoped state).
- Render is selection — output formats are pure functions over Bus state.
- ID-flow symmetric end-to-end: `final_sources` carries `src-NNN`, every downstream agent reads and emits in `src-NNN`.

Full architectural specification: `docs/ARCH-V2-BUS-SCHEMA.md`. Decision log: same document §10.

### H3.2 — Content Quality Polish (Researcher-Polish) — next

V2 made the pipeline architecturally clean. The next emphasis is content depth and quality.

**Observation:** with the architecture stable, the limiting factor for TP quality is now the **Researcher Plan** stage. The Plan agent's queries determine what evidence reaches the Writer. Current plan is somewhat shape-uniform across topic types (Quantitative-claim, Stakeholder-conflict, Policy/regulatory, Crisis/emergency, Tech/business, Cultural/social). Different story shapes warrant different research strategies.

| Task | Description | Effort |
|------|-------------|--------|
| TASK-RESEARCHER-POLISH (iteration 1) | Inline 6-shape Story-Shape-Targeting in Plan-INSTRUCTIONS for both production and hydrated variants. SYSTEM.md mini-touch on breadth + depth dual mandate. Switch `researcher_plan` and `researcher_hydrated_plan` to `anthropic/claude-opus-4.6` (~+€55/month, Assemble stays on Gemini Flash for cost reasons). Pre/post smoke-eval to verify quality lift. | 1 session |
| TASK-RESEARCHER-POLISH (iteration 2) | Deterministic Pre-Plan stage that classifies story shape before the LLM plans. Deferred — needs to be universally applicable, not just for the 6 shapes from iteration 1. | After iteration 1 evaluated |

### H3.3 — Architecture-quality follow-ups (catalogued, queued)

These items improve V2 further but don't block any current capability:

| Task | Description |
|------|-------------|
| TASK-BIAS-LANGUAGE-RENDER-SHAPE | ✅ Closed (commit `2a41570`): root cause was in the `BiasLanguageStage` wrapper (`src/agent_stages.py`), not `src/render.py` — the original ticket title misnamed the location. Severity field removed end-to-end. |
| WP-OPUS-4.7-MIGRATION | Opus 4.6 → 4.7 across all Opus-using agents. `src/agent.py` refactor for `output_config.effort`. Per-agent effort-level eval. |
| WP-STRUCTURED-OUTPUTS-V2 | After Researcher-Polish. Migration of `response_format` patterns where structured outputs improve robustness. |
| WP-TOPIC-STAGE-PARALLELISATION | Run multiple TopicBuses concurrently. Architecturally trivial in V2 (no cross-TopicBus dependency). |
| WP-SPENDING-CAP-REDESIGN | Pre-call spending cap rather than post-phase check. V2-10 came near €5 before tripping post-phase guard — pre-call check catches overruns earlier. |
| TASK-FUTURE-RESEARCH-DEPTH | Direct institutional source fetch via curated registry (RSS/API endpoints per source-category), bypassing LLM-Planner. Prerequisite: Researcher-Polish iteration 1 evaluated. |

### H3.4 — Production-hardening (catalogued)

| Task | Description |
|------|-------------|
| CLI tool packaging | `independent-wire` as installable command. |
| Config file | `config/pipeline.yaml` for runtime parameters. |
| Output safety checks | Pre-publish schema validators. |
| Crash-recovery / per-stage snapshots | JSONL append-on-disk per stage; `run_bus.run_stage_log` already provides the substrate. |

### H3.5 — Source coverage and feeds

| Task | Description |
|------|-------------|
| WP-FEED-EXPAND | 72 → 100+ feeds. Prioritise underrepresented regions (Latin America, sub-Saharan Africa, Southeast Asia). Community contribution path. |
| WP-COLLECTOR-REACTIVATION | Reactivate the Collector agent (currently commented out in `scripts/run.py:create_agents`) when scaling to 200+ feeds — needed as Curator pre-filter. |

### H3.6 — Community and external interfaces

| Task | Description |
|------|-------------|
| WP-MCP-SERVER | MCP server providing Topic Packages as structured data to Claude, ChatGPT, and other LLM clients. See `docs/WP-MCP-SERVER.md`. |
| WP-SEO | SEO improvements for `independent-wire.org`. See `docs/WP-SEO.md`. |
| Open API | RESTful endpoint surfacing Topic Packages as JSON for external use. |
| Community-reviewed agent prompts | Prompt library where community-proposed prompts can be versioned and reviewed. |
| Collaboratively-maintained source catalog | Especially from underrepresented regions. |
| Trust network | Community-based evaluation of sources and agents. |
| Docker deployment | One-click self-hosting. |
| Setup wizard | Onboarding for non-developers wanting to run their own newsroom. |

### H3.7 — Narrative tracking

Long-form: tracking how a narrative evolves across days and weeks. Architecturally enabled by the `previous_coverage` slot in the RunBus and the Editor's follow-up logic; could be extended into a multi-run analysis layer.

---

## Sustainability and funding

No commercial model. No advertising. No investor equity. Operating cost target: under €1 per run, approximately €30 per month for daily operation. Funding paths: community sponsorship, public interest grants, institutional partnerships. The system is designed so that its operating costs never create pressure to compromise editorial independence.

---

## Vision alignment

Each work-stream above traces back to the Vision paper (March 2026). The five-dimensional Bias Card (language, source, geographical, selection, framing) is implemented as a multi-slot derived view at render time — see `docs/ARCH-V2-BUS-SCHEMA.md` §4B.12 for the explicit mapping of Vision dimensions to TopicBus slots. The transparency-first principle is structurally enforced via the visibility metadata system: nothing reaches the public TP that hasn't been explicitly marked `tp` in the schema.

What still doesn't exist:
- Investigative journalism — AI cannot replace humans on the ground. The system relieves routine work; investigative work stays human.
- Real bias elimination — RLHF carries bias forward; the goal is bias **transparency**, not bias absence.
- Author voice — AI cannot have lived experience; the system finds its own deliberately-flat style instead.
- Relevance judgement — what matters to whom is contextual; the system makes structural distortion visible rather than claiming objective relevance.

These limits are not arguments against the system. They are arguments for honesty about what AI can and cannot do. A system that knows and communicates its limits is more trustworthy than one that promises objectivity.
