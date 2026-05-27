# Independent Wire — Open Source Roadmap

**Created:** 2026-03-26
**Updated:** 2026-05-28 (post Consolidator refactor + Diagnostic A/B/C/D resolution — H3.2.8 added; three post-QA stages collapsed into one LLM-backed `ConsolidatorStage`; legacy two-surface renderer removed; zero-actor cards now carry editorial-outlet attribution; historical TPs backfilled).
**Status:** Living document — strategic overview.
**Basis:** Vision paper (March 2026) + PoC experience (Sessions 1–12) + Model Evals (Sessions 4–5) + Cost Optimization (Session 6) + Rendering + Website (Session 7) + V2 architecture (April–May 2026) + B-full canonical-actors migration + render restructure (May 2026) + Triple-Stage Curator brief sequence (May 12–17 2026, `docs/ADR-CURATOR-TRIPLE-STAGE.md` + `docs/AUDIT-TIMELINE.md`)

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

### H3.1 — V2 Architecture + Triple-Stage Curator (April–May 2026) ✅ Complete

**Goal:** make the pipeline architecturally clean enough that future content quality work can happen without fighting the structure, then layer the first round of structural content-quality wins on top.

V1 had aggregation surface as the source of all five S14/S15 bug classes (ID-consistency, aggregation duplications, pre-research artefacts surviving downstream, per-actor metadata grafted from wrong dimensions, editor-time selection_reason becoming false). V2 replaced aggregation with a **Bus + Stage architecture**: one RunBus, N TopicBuses, one stage list per variant, one render layer that filters by visibility metadata.

The V1 single-pass Curator that survived the April–May big-bang was then replaced in turn by the **Triple-Stage Curator** (Briefs 1–5b, May 12–17 2026, `docs/ADR-CURATOR-TRIPLE-STAGE.md`): deterministic Agglomerative pre-clustering, a small-input LLM topic-discovery step that emits only `{topics: [{title, summary}]}`, and deterministic gravitational assignment at cosine threshold `T = 0.55, V = title + summary`. Empirical validation against the 2,542-label audit set: **8.23 % aggregate weighted off-topic** (vs. 69.59 % at the provisional T = 0.30), zero topics above 50 % off-topic across 30 audited top-10 topics on three eval days.

| WP / Brief | Status |
|----|--------|
| `WP-V2-BUS-ARCHITECTURE` | ✅ Complete — V2-01 through V2-11b shipped April 30 – May 1 2026. V1 deleted in commit `19348f3`. Documentation reconciled in V2-DOC-RECONCILE (May 7) and again in `TASK-DOC-RECONCILE` (May 17, this brief). |
| `TASK-RENDER-RESTRUCTURE-V2` | ✅ Complete (May 5–7, commits `ced8981 → 0a4b120`). Five atomic commits restructured the rendered TP around five primary sections (Article, Positions, Actors, Sources, Bias-Card). |
| `TASK-RESOLVE-ACTOR-ALIASES` Phase 1+2 | ✅ Complete (May 5–7, commits `c20459a` + `6fe0258`). F2 (actor-name alias dedup) closed; canonical_actors[] consumer-facing slot; ARCH-V2-BUS-SCHEMA §7.2 strict-merge pattern. |
| Phase 2 Commit 2 (Flash endpoint switch) | ⚠️ Blocked — `google/gemini-flash-latest` is not a valid OpenRouter model ID. Reverted; awaiting Architect input on the actual identifier. |
| Triple-Stage Curator — Brief 1 (`TASK-EMBED-PRE-CLUSTER-STAGE`) | ✅ Complete (commit ending `9cc2957`). |
| Triple-Stage Curator — Brief 2 (`TASK-GRAVITATIONAL-ASSIGN-STAGE`) | ✅ Complete (commit ending `5189cec`). Provisional calibration at `T=0.30`; superseded by Brief 5b. |
| Triple-Stage Curator — Brief 3 (PE round: Curator + Editor prompt rewrites) | ✅ Complete (commit `03103e8`). |
| Triple-Stage Curator — Brief 4 (`TASK-CURATOR-TOPIC-DISCOVERY-STAGE`) | ✅ Complete (commit ending `3ab766c`). |
| Triple-Stage Curator — Brief 5 (`TASK-TRIPLE-STAGE-CUTOVER`) | ✅ Complete (commit ending `0135c8f`). |
| `TASK-CLUSTER-QUALITY-AUDIT` | ✅ Complete (commit `6d8ffc4`). 2,542 labels; surfaced 69.59 % aggregate off-topic at provisional T=0.30; motivated Brief 5b. |
| Triple-Stage Curator — Brief 5b (`TASK-GRAVITATIONAL-RECALIBRATION`) | ✅ Complete (commit ending `310a55d`). Pinned `T=0.55, V=title+summary`; re-audit confirms 8.23 % aggregate / 0 topics > 50 %. |
| `TASK-DOC-RECONCILE` (Brief 6) | ✅ Complete — this commit. ARCHITECTURE.md / ADR / AGENT-IO-MAP refreshed; new AUDIT-TIMELINE.md; TASKS/ROADMAP/CLAUDE marked V2-current. |

**Key architectural changes:**
- Granular Bus slots with declared owner, visibility, and mirrors_from metadata.
- Empty-then-fill mirror pattern (slot-level for monolithic slots, per-element for collections).
- Hierarchical Bus separation (run-scoped vs. topic-scoped state).
- Render is selection — output formats are pure functions over Bus state.
- ID-flow symmetric end-to-end: `final_sources` carries `src-NNN`, every downstream agent reads and emits in `src-NNN`.
- Triple-Stage Curator: deterministic pre-cluster → LLM topic-discovery → deterministic gravitational assignment. The V4-Pro over-clustering pathology is structurally impossible — the LLM no longer assigns findings, so the per-finding output pressure that produced the catch-all behaviour is gone.

Full architectural specification: `docs/ARCH-V2-BUS-SCHEMA.md` (bus + stage schema) + `docs/ARCHITECTURE.md` (first-principles + V2 stage list) + `docs/ADR-CURATOR-TRIPLE-STAGE.md` (Curator decision + resolved calibration points). Chronological audit trail: `docs/AUDIT-TIMELINE.md`. Decision log for bus + stage: `docs/ARCH-V2-BUS-SCHEMA.md` §10.

### H3.2 — Content Quality Polish (Researcher-Polish) — iteration 1 ✅ complete; iteration 2 deferred

V2 made the pipeline architecturally clean. The next emphasis is content depth and quality.

**Observation:** with the architecture stable, the limiting factor for TP quality is now the **Researcher Plan** stage. The Plan agent's queries determine what evidence reaches the Writer. Current plan is somewhat shape-uniform across topic types (Quantitative-claim, Stakeholder-conflict, Policy/regulatory, Crisis/emergency, Tech/business, Cultural/social). Different story shapes warrant different research strategies.

| Task | Description | Effort |
|------|-------------|--------|
| TASK-RESEARCHER-POLISH (iteration 1) | ✅ shipped May 2-4 2026. Inline 6-shape Story-Shape-Targeting in Plan-INSTRUCTIONS for both production and hydrated variants (commit b2bec02). SYSTEM.md mini-touch on breadth + depth dual mandate. Researcher-Plan and Researcher-Hydrated-Plan now run on anthropic/claude-opus-4.6. Date context passed in (commit bd92e44). Per-query Story-Shape obligation (commit 0b03760). Authoritative cost €0.22/Plan-call. Six-axis smoke pass. | 1 session |
| TASK-RESEARCHER-POLISH (iteration 2) | Deterministic Pre-Plan stage that classifies story shape before the LLM plans. Deferred — needs to be universally applicable, not just for the 6 shapes from iteration 1. | After iteration 1 evaluated |

### H3.2.5 — Live-pipeline observation under V2 (continuous)

The pipeline has run live at `independent-wire.org` throughout the V2 + Triple-Stage-Curator work. The F2 alias-dedup stack was validated on the 2026-05-07 → 2026-05-11 baseline runs (Writer cites canonical names, Actors-section anchors resolve, resolver Y-config stable on real multilingual coverage). The recalibrated Curator landed 2026-05-17; **multi-day production observation under the recalibrated `T=0.55 V1` is the next deferred observation task** (`TASK-POST-V2-PRODUCTION-OBSERVATION` in `docs/TASKS.md`). Watch surface: any drift on a real-world day not covered by the eval set (2026-05-08 / 11 / 13), and any topic where the higher threshold drops a multilingual cluster the editorial team would have wanted retained.

After production observation surfaces a stable post-V2 picture, the **weekly-outlet-audit cadence** (see `BACKLOG-WEEKLY-OUTLET-AUDIT.md` at repo root) and the **external Vision Paper update** (see Vision alignment below) become next-priority workstreams.

### H3.2.6 — Phase-1 LLM Plan-Model Sweep — deferred

Catalogued for future activation. 10-combination sweep against the 2026-05-05 baseline (Opus 4.6 with story-shape inline). Combinations: Sonnet 4.6 × 2 reasoning settings, Gemini 3.1 Pro Preview × 4, DeepSeek V4 Pro × 4. Substrate at `output/2026-05-05/_state/run-2026-05-05-6189fcca/topic_buses.ResearcherHydratedPlanStage.{0,1,2}.json`. Total cost ~€1. Not actively running while the live-pipeline-run validation and weekly-outlet-audit init take priority.

### H3.2.7 — Renderer-hygiene sweep ✅ Complete (2026-05-19/20)

2026-05-19/20 — Renderer-hygiene sweep across published TPs. Seven issues fixed end-to-end: actor dedup per source; structured self-retraction of invalid bias findings; per-cluster quote dedup across actor lines; per-actor source-list moved from cluster cards into the Actors-section; the cluster-formation single-actor backlog activated by a production signal (DR Congo Health Minister with 6 quotes orphaned in tp-2026-05-19-003); coverage gaps and missing stakeholder voices consolidated under a unified renderer header with deterministic dedup; Actors-section refactored into a navigation table; verbatim quotes relocated to a third-level disclosure under each source. Single-voices bracket added 2026-05-20 (`4e7da5d`) as deterministic complement to the single-actor cluster backlog, surfacing structurally-central orphan actors in their own visually-distinguished section.

### H3.2.8 — Consolidator refactor + Diagnostic-issue resolution ✅ Complete (2026-05-26/27)

2026-05-26/27 — `REPORT-DIAGNOSTIC-2026-05-23.md` identified three live issues (A: an over-aggressive deterministic `validate_coverage_gaps_stage` falsifying 5 of 5 entries on the Cuba dossier; B: non-English `role` and `position` text on non-English sources; C: visually-empty position cards where `n_actors == 0`) plus one observational follow-up (D: the page carrying two distinct "what's missing" surfaces — Bias-Card commentary plus the H3.2.7 unified header). Resolution collapsed three post-QA stages (`validate_coverage_gaps_stage`, `consolidate_missing_coverage`, `PerspectiveSyncStage`) into one LLM-backed `ConsolidatorStage` owning a new `what_is_missing` bus slot, renamed `single_voices` → `mentioned_actors` in supporting documentation (rename itself landed earlier in `7726fac`), removed both legacy renderer paths in favor of a single "What is missing" section before Sources, introduced editorial-outlet attribution on zero-actor position cards, and backfilled `what_is_missing` into 48 historical TPs via the new migration script. Bus field count dropped 40 → 39, stage-list counts 25 → 24 (production) / 32 → 29 (hydrated), net codebase reduction ~600 lines. Test suite 679 → 705 green. The diagnostic surface is fully closed; `docs/AGENT-IO-MAP.md` reconciliation explicitly deferred to a subsequent session.

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
| TASK-QA-EXPLANATION-BREVITY | ✅ Closed (commit 813c4e4): explanations one-to-three sentences; max_tokens 64000 to prevent truncation. |
| TASK-HYDRATED-SOURCE-METADATA-ENRICHMENT | ✅ Closed (commit 59f46fc): outlet registry, pubdate extraction, prune_unused_sources_and_clusters new stage. |
| TASK-QA-CORRECTION-NEEDED-FLAG | ✅ Closed (commit e2e7efd): qa_proposed_corrections → qa_corrections with explicit correction_needed flag. PerspectiveSync gate updated. |
| TASK-RATIONALE-DOC-RECONCILE-AND-REUSE-OVERWRITE-SAFETY | ✅ Closed (commit f9b4d75): obsolete rationale row removed; --force flag for --reuse safety. |
| TASK-PRUNE-VALIDATOR-STRICTER-DROP-RULE | ✅ Closed (commit a8b40e3): strict drop rule on unreferenced sources. |
| TASK-CURATOR-PROMPT-TIGHTENING | ✅ Closed (commit 8f48804): null as cluster_assignment default; topic subject anchored to concrete event/decision/conflict. |

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

**External Vision Paper update is deferred** until production-run experience accumulates under the V2 + recalibrated-Curator architecture. The internal documentation (this roadmap + `docs/ARCHITECTURE.md` + `docs/ADR-CURATOR-TRIPLE-STAGE.md` + `docs/AUDIT-TIMELINE.md`) reflects the V2 state as of 2026-05-17; the external `VISIONindependentwire.pdf` was explicitly held out of scope for the `TASK-DOC-RECONCILE` brief and is queued in `docs/TASKS.md` for activation after `TASK-POST-V2-PRODUCTION-OBSERVATION` completes.

What still doesn't exist:
- Investigative journalism — AI cannot replace humans on the ground. The system relieves routine work; investigative work stays human.
- Real bias elimination — RLHF carries bias forward; the goal is bias **transparency**, not bias absence.
- Author voice — AI cannot have lived experience; the system finds its own deliberately-flat style instead.
- Relevance judgement — what matters to whom is contextual; the system makes structural distortion visible rather than claiming objective relevance.

These limits are not arguments against the system. They are arguments for honesty about what AI can and cannot do. A system that knows and communicates its limits is more trustworthy than one that promises objectivity.
