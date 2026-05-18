# Independent Wire — Framework Architecture

> **V2-RECONCILED 2026-05-17 PER `TASK-DOC-RECONCILE.md`.**
>
> This document is the project's first-principles framework reference. It carries:
>
> - The **framework decision** (why Independent Wire builds its own minimal Python framework rather than adopting OpenClaw / Hermes / Nanobot / Paperclip).
> - The **three core abstractions** — Agent, Tool, and (since V2) Stage + RunBus + TopicBus, which replaced V1's `Pipeline` class.
> - The **two named architectural principles** (deterministic-before-LLM; agents emit only originary output).
> - A V2 **stage-list summary**, **bus-slot catalogue** (Curator-side, the V2 additions), **embedding-singleton pattern**, and **triple-stage Curator** description — at the level of detail consistent with how this document previously described V1.
>
> The authoritative bus + stage schema is **`docs/ARCH-V2-BUS-SCHEMA.md`**. The authoritative stage I/O contract is **`docs/AGENT-IO-MAP.md`**. The Curator architectural decision lives in **`docs/ADR-CURATOR-TRIPLE-STAGE.md`**, the chronological audit trail in **`docs/AUDIT-TIMELINE.md`**. This document references all four for full detail.
>
> V1 source files (`src/pipeline.py`, `src/pipeline_hydrated.py`, `src/hydration_aggregator.py`, `src/hydration_urls.py`, `src/models.py`) were deleted in commit `19348f3` (V2-11b). V1-era descriptions of `Pipeline._produce_single`, `Pipeline.run`, V1 hydration aggregation, and the single-pass Curator have been replaced with V2 equivalents in the relevant sections below.

---

## Decision

Independent Wire uses its own minimal Python framework instead of OpenClaw, Hermes Agent, Nanobot, or Paperclip. The framework is purpose-built for a **deterministic multi-agent news pipeline** — not a general-purpose personal AI assistant.

### Why not an existing framework?

All evaluated frameworks (OpenClaw, Hermes, Nanobot, Paperclip) are **chat-oriented personal assistants**: a human sends a message, an agent responds, optionally using tools. Independent Wire needs something fundamentally different: a **pipeline** where specialized agents with different models, different tools, and different prompts process data sequentially, producing structured JSON output.

The three things we actually need from a framework — LLM API calls, tool execution, and Telegram notifications — are each ~50–100 lines of Python. The overhead of adapting a 3,500-line (Nanobot) or 300,000-line (OpenClaw) framework to do something it wasn't designed for exceeds the cost of building exactly what we need.

### Reference implementation

Nanobot's codebase (`agent/loop.py`, `agent/context.py`, `agent/tools/`) serves as architectural reference for how to structure LLM calls, tool registration, and context building. We don't import it — we learn from it.

---

## Three Core Abstractions

Everything in the framework is built on three abstractions. If these are right, everything else — memory, parallelization, new tools, Docker deployment — can be added without rewriting.

### 1. Agent

An Agent is a configured LLM caller. It has an identity (name, system prompt), a model assignment, allowed tools, optional memory, and temperature. It takes a message + context and returns a structured response.

```python
class Agent:
    """A configured LLM caller with identity, model, tools, and memory."""

    def __init__(
        self,
        name: str,                    # e.g. "curator_topic_discovery", "writer", "bias_language"
        model: str,                   # e.g. "anthropic/claude-opus-4.6"
        system_prompt_path: str,      # path to SYSTEM.md (identity)
        instructions_path: str,       # path to INSTRUCTIONS.md (per-run task spec)
        tools: list[Tool] = None,     # e.g. [web_search_tool] — None = no tools
        memory_path: str = None,      # optional persistent memory file
        temperature: float = 0.3,     # model temperature
        max_tokens: int = 32000,      # max response tokens
        provider: str = "openrouter", # API provider
        reasoning: str | None = None, # 'none', 'minimal', 'high' (provider-specific)
    ):
        ...

    async def run(
        self,
        message: str = "",
        context: dict = None,                   # JSON-encoded into the User-turn <context> block
        output_schema: dict = None,             # JSON Schema enforced as decoder constraint via OpenRouter response_format (strict mode). See src/schemas.py.
        instructions_addendum: str | None = None,  # appended inside the <instructions> block
    ) -> AgentResult:
        """
        Build the system message as <system_prompt>{SYSTEM.md}</system_prompt>.
        Build the User turn from three blocks: <context>, <memory>, <instructions>.
        Handle tool calls in a loop until final response.
        Return structured result.
        """
        ...


@dataclass
class AgentResult:
    """What an agent returns."""
    content: str                      # raw text response
    structured: dict = None           # parsed JSON if output_schema was provided
    tool_calls: list[dict] = None     # log of tool calls made
    tokens_used: int = 0              # total tokens consumed
    cost_usd: float = 0.0            # estimated cost
    model: str = ""                   # model that was actually used
    duration_seconds: float = 0.0     # wall clock time
```

`AgentResult` lives in `src/agent.py` since V2-11b (previously in `src/models.py`, which was deleted in the same commit).

**Key design decisions:**
- Agents are **async** (`async def run`) — enables future parallelization via `asyncio.gather()`
- Each agent has its **own model** — no global default
- **Tool calls handled inside the agent loop** — same pattern as Nanobot's `loop.py`
- **Structured output** via `output_schema`. The schema is wired as `response_format: {type: "json_schema", strict: true, schema: ...}` on the OpenRouter API call. For Anthropic models, OpenRouter applies the `anthropic-beta: structured-outputs-2025-11-13` header automatically. Decoder masks tokens that would violate the schema before sampling — agents are mechanically incapable of emitting fields outside their schema. All production agent schemas live in `src/schemas.py` as a single source of truth. Defense-in-depth (`_extract_dict`, `_extract_list`, `_parse_json`, `json_repair`, `_parse_or_retry_structured`) preserved as fallback when the schema fails to compile or a provider falls back.
- **Memory is a file path**, not a framework feature; loaded into the User-turn `<memory>` block when set
- **Two-file prompt convention** (S13): every agent has `agents/{name}/SYSTEM.md` (identity) + `agents/{name}/INSTRUCTIONS.md` (per-run task spec). Researcher and Hydration Aggregator use phase-named pairs (`PLAN-*`, `ASSEMBLE-*`, `PHASE1-*`, `PHASE2-*`).
- **User-turn three-block layout**: `<context>` (JSON-encoded input + optional message), `<memory>` (when present), `<instructions>` (always present; addendum like Writer FOLLOWUP.md appended inside the closing tag). System message contains only `<system_prompt>{SYSTEM.md}</system_prompt>`.

### 2. Stage + RunBus + TopicBus  *(replaces V1 `Pipeline`)*

V1's `Pipeline` class — an aggregating orchestrator that produced TopicPackages by calling agents in sequence and stitching their outputs together — was replaced in V2 by three primitives:

- **`Stage`** (`src/stage.py`) — a typed callable with declared `reads` / `writes` over Bus slots. Two kinds: `run_stage` (operates on a `RunBus`) and `topic_stage` (operates on a `TopicBus`). The runner walks a list of stages in order; each stage is async, each stage produces only what its `writes` declares, each stage reads only what its `reads` declares. Stage code is either deterministic Python (in `src/stages/run_stages.py` + `src/stages/topic_stages.py`) or an agent-wrapper (in `src/agent_stages.py`).
- **`RunBus`** (`src/bus.py`) — a Pydantic model holding every run-scoped slot (findings, topics, editor assignments, previous coverage, per-stage telemetry). One instance per pipeline run.
- **`TopicBus`** (`src/bus.py`) — a Pydantic model holding every topic-scoped slot (the selected topic, hydration results, research dossier, sources, perspective clusters, written article, QA verdicts, bias findings, transparency card). One instance per produced Topic Package. Carries a read-only reference to its parent RunBus.

```python
@run_stage_def(reads=("curator_findings",), writes=("curator_pre_clusters",))
async def pre_cluster_findings(run_bus: RunBus) -> RunBus:
    """Embed every finding via the shared fastembed singleton; cluster into
    ~250 micro-clusters via Agglomerative (cosine, T=0.7). Pure Python.
    Pure subset of inputs, deterministic outputs."""
    ...
```

```python
class PipelineRunner:
    """Walks a stage list, persists per-stage Bus snapshots to disk for
    resume-after-crash, enforces precondition / postcondition validation
    on the typed reads/writes contract."""

    async def run(self) -> list[TopicPackage]: ...
```

Two stage lists exist (`src/runner/stage_lists.py`):
- `build_production_stages()` — production variant: pure RSS → Editor → Researcher → Writer → QA → Bias.
- `build_hydrated_stages()` — hydrated variant: adds the Hydration sub-pipeline (T1 fetch + T2 phase1+phase2 aggregator) before the Researcher, plus a per-element `perspective_sync` step after QA.

The Editor (and any topic-stage agent) sees only the slots it reads from — it does not know whether the pipeline is production or hydrated. Variants are runner-time choices over the same agent code.

**Key design decisions:**
- Stage steps are **explicit functions** in Python, not LLM-orchestrated.
- Each Bus slot has **exactly one writer** (the originary-output principle, §Architectural Principles).
- **Mirror pattern** (empty-then-fill): slots that semantically modify earlier slots (e.g. `qa_corrected_article` mirrors `writer_article`, `perspective_clusters_synced` mirrors `perspective_clusters`) start empty; a mirror stage runs after the modifying agent and fills empty fields from the source. See `docs/ARCH-V2-BUS-SCHEMA.md` §3.3.
- **Render is selection** (`src/render.py`): output formats — `tp` (public Topic Package), `mcp` (structured tool data), `rss`, `internal` — are pure functions over Bus state, filtered by the schema-level `visibility` metadata. No format-specific re-aggregation; the visibility tags on each Bus slot drive the cut.
- Steps are async; **topic-stage parallelisation** is architecturally trivial in V2 (no cross-TopicBus dependency) — currently serial for stability, parallel rollout is catalogued as `WP-TOPIC-STAGE-PARALLELISATION`.

### 3. Tool

A Tool is a callable function that agents can use during their LLM loop.

```python
class Tool:
    """A callable function that agents can invoke during LLM interaction."""

    def __init__(self, name: str, description: str, parameters: dict, handler: Callable):
        ...

class ToolRegistry:
    """Manages available tools. Each agent gets a filtered subset."""

    def register(self, tool: Tool): ...
    def get_for_agent(self, allowed: list[str]) -> list[Tool]: ...
    def to_openai_format(self, allowed: list[str]) -> list[dict]: ...
```

**Key design decisions:**
- Tools are **swappable** — `web_search` can use Brave today and SearXNG tomorrow.
- Tool permissions are **per-agent** — strict allow-lists.
- Tools use the **OpenAI function-calling format**.
- The registry pattern means new tools require no agent code changes.

---

## V2 Bus Slot Catalogue — Curator side

The full slot catalogue with owners, visibility, mirrors-from, and initial / final shapes lives in **`docs/ARCH-V2-BUS-SCHEMA.md` §4A (RunBus) and §4B (TopicBus)**. This section summarises the Curator-side V2 additions so this document accurately reflects the V2 stage / slot picture.

| Slot | Writer | Reader(s) | Visibility | Notes |
|---|---|---|---|---|
| `curator_findings` | `fetch_findings` | `pre_cluster_findings`, `CuratorTopicDiscoveryStage`, `gravitational_assign` | `internal` | The full RSS day. Pass-through across the Curator sub-pipeline (the three stages above each read it; none mutate it). |
| `curator_pre_clusters` | `pre_cluster_findings` | `CuratorTopicDiscoveryStage` | `internal` | The ~250 micro-clusters produced by Agglomerative clustering. Compression artefact for Stage 2's LLM input — not the final cluster product. |
| `curator_discovered_topics` | `CuratorTopicDiscoveryStage` | `gravitational_assign`, `assemble_curator_topics` | `internal` | The LLM's topic list: `{topics: [{title, summary}]}` plus telemetry. No finding assignments emitted by the LLM. |
| `curator_topic_assignments` | `gravitational_assign` | `assemble_curator_topics` | `internal` | The deterministic finding-to-topic mapping at T=0.55, V1 (title+summary topic-centre). Carries per-(finding,topic) similarity, orphans with their best topic + similarity. |
| `curator_topics_unsliced` | `assemble_curator_topics` | `EditorStage`, `attach_hydration_urls_to_assignments` (hydrated) | `internal` | The Editor's input (same slot shape the legacy `CuratorStage` wrote; downstream consumers unchanged). Now built by Python composition over `curator_discovered_topics` + `curator_topic_assignments`. |
| `curator_topics` | `assemble_curator_topics` | render layer | `internal` | Identical content; legacy slot retained for render-time references. |
| `curator_coherence_scores` | *(no current writer)* | *(no current reader)* | `internal` | Legacy slot from the old `measure_cluster_coherence` stage. Stage callable was removed in the Brief 5 cutover; the source file `src/stages/coherence.py` was retained for the fastembed singleton (see §Embedding Singleton Pattern below). Slot declaration kept in `src/bus.py` in case a future calibration brief revives a passive-coherence diagnostic on the V2 topic centres. **Future revival framing: TBD.** |

All other Bus slots — RunBus init metadata, EditorAssignments, the full TopicBus slot family — are unchanged from the V2 cutover and documented in `docs/ARCH-V2-BUS-SCHEMA.md` §4A / §4B. The Curator-side additions above are the only new slots introduced across Briefs 1–5b.

---

## V2 Stage List

The full ordered stage list (production + hydrated) lives in **`docs/ARCH-V2-BUS-SCHEMA.md` §5.1 / §5.2** and the per-stage I/O contract in **`docs/AGENT-IO-MAP.md` §2.x**. Summarised here:

```
Production variant:
  init_run
  → fetch_findings
  → pre_cluster_findings               (B1, deterministic — agglomerative)
  → CuratorTopicDiscoveryStage         (B4, LLM — Gemini 3 Flash)
  → gravitational_assign               (B2, deterministic — cosine T=0.55)
  → assemble_curator_topics            (B5, deterministic — composition)
  → EditorStage
  → select_topics
  → instantiate_topic_buses
  → (per-topic stages: Researcher → Perspective → Writer → QA → Bias → transparency)
  → finalize_run

Hydrated variant:
  …everything above, PLUS:
  → attach_hydration_urls_to_assignments  (between Editor and select_topics, run-stage)
  → hydration_fetch + HydrationPhase1/2  (topic-stages before Researcher)
  → assemble_hydration_dossier
  → ResearcherHydratedPlanStage          (variant of ResearcherPlan)
  → PerspectiveSyncStage + mirror_perspective_synced (twice)
```

Curator pipeline references:
- Brief 1 (`pre_cluster_findings`) — `docs/pre-cluster/`, `docs/CLUSTERING-EVAL-2026-05-14.md`
- Brief 2 (`gravitational_assign`) — `docs/gravitational-assign/`
- Brief 4 (`CuratorTopicDiscoveryStage`) — `docs/curator-topic-discovery/`
- Brief 5 (cutover) — `docs/triple-stage-cutover/`
- Audit (`cluster-quality-audit-2026-05-16`) — `docs/cluster-quality-audit/audit-2026-05-16/`
- Brief 5b (recalibration) — `docs/gravitational-recalibration-2026-05-16/`, `docs/cluster-quality-audit/audit-2026-05-16-recalibrated/`
- Architectural decision: `docs/ADR-CURATOR-TRIPLE-STAGE.md`
- Audit trail index: `docs/AUDIT-TIMELINE.md`

---

## Triple-Stage Curator

The Curator's job — turn ~1,200 daily findings into a small set of thematic topic candidates — is now done by three stages, not one LLM pass. Each stage has the task it is structurally suited for, and two of the three are deterministic.

1. **`pre_cluster_findings`** — Embed every finding via the shared fastembed singleton (multilingual MiniLM-L12-v2), cluster into ~250 micro-clusters via Agglomerative clustering (`distance_threshold=0.7`, `linkage='average'`, `metric='cosine'`). Pure Python. Deterministic.
2. **`CuratorTopicDiscoveryStage`** — A small-input, small-output LLM call (Gemini 3 Flash, temp 0.2). Receives the ~250 micro-clusters in compressed representation (top-K-by-centroid titles, K=8) and identifies the 10–20 superordinate topics of the day. Emits **only** `{topics: [{title, summary}]}` — no per-finding assignments, no relevance scores. Removing the per-finding output pressure eliminated the over-clustering pathology that broke the V1 single-pass Curator.
3. **`gravitational_assign`** — Embed each topic's title + summary into a topic-centre vector. Embed each finding. Compute cosine similarity. A finding is assigned to every topic centre it scores above the **`GRAVITATIONAL_THRESHOLD`** of 0.55 — capped at `PER_FINDING_CAP=3` topics per finding. Below threshold for every topic → orphan. Pure Python. Deterministic.

The rationale — what V1 broke, what the empirical evidence was, what got resolved — lives in **`docs/ADR-CURATOR-TRIPLE-STAGE.md`**. The empirical validation: the cluster-quality audit at HEAD `6d8ffc4` measured a 69.59 % aggregate off-topic rate at the provisional T=0.30 calibration; the recalibration to T=0.55 (Brief 5b, HEAD `310a55d`) brings that to 8.23 % with no audited top-10 topic above 50 % off-topic. See `docs/AUDIT-TIMELINE.md` for the chronology.

---

## Embedding Singleton Pattern

`src/stages/coherence.py::_get_default_embedder` is the project's **single fastembed instance**, lazily instantiated on first call and held for the process lifetime. Four production stages consume it:

- `pre_cluster_findings` (`src/stages/pre_cluster.py`)
- `gravitational_assign` (`src/stages/gravitational_assign.py`)
- `CuratorTopicDiscoveryStage` (`src/agent_stages.py` — for the centroid-based top-K-by-similarity compression)
- The retained `measure_cluster_coherence` source code in `src/stages/coherence.py` itself (stage callable was removed in the Brief 5 cutover, but the source file and its singleton-import safety net remain so that any future passive-coherence revival reuses the same ONNX session).

**One ONNX session per process is a load-bearing invariant.** fastembed lazy-loads the ~80 MB multilingual MiniLM-L12-v2 weights into ONNX Runtime on first `.embed()` call; instantiating a second `FastembedEmbedder` doubles the resident-memory footprint and re-pays the warm-up cost. The model name (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`) and the `FASTEMBED_VERSION_REQUIRED` constant are both pinned in `src/stages/coherence.py` because fastembed ≥ 0.6 silently switched this model from CLS-token to mean-pooled output — a transparent fastembed upgrade would invalidate every historic embedding-based metric.

The dependency-promotion rationale and the 400 → 600 MB site-packages ceiling raise are documented in `docs/ADR-COHERENCE-STAGE-DEPENDENCY.md` plus the 2026-05-15 addendum.

---

## Architectural Principles

Two non-negotiable principles govern how work is divided between Python and LLM agents. They have **direct, measurable impact on both output quality and operating cost** and must be applied without exception.

Violations of these principles are architectural debt, not stylistic preference. Every LLM token spent on work Python could do deterministically is waste — both in money and in the noise it introduces into the model's reasoning. Every piece of data an agent must pass through instead of originate is a risk: the model may reformat it, drop it, or transform it silently. Python-routed data flow eliminates that entire class of failure.

These principles are also documented in machine-checkable form in `docs/ARCH-V2-BUS-SCHEMA.md` §3.1 and §3.2 — each Bus slot has a declared owner; the runner enforces that no stage writes to a slot it does not own.

### Principle 1 — Deterministic before LLM

**If a piece of work can be solved deterministically in Python, it must be solved in Python.** LLM calls are reserved for genuinely non-deterministic work (summarisation, cross-language comparison, stakeholder identification, bias analysis, topic discovery). Normalisation, ID assignment, schema compliance, counting, indexing, clustering, language-code formatting — these are Python's job.

Applied in the current V2 pipeline:
- **Curator pre-clustering and gravitational assignment** are entirely deterministic Python (`pre_cluster_findings`, `gravitational_assign`); only the topic-naming step (`CuratorTopicDiscoveryStage`) is an LLM call. The V1 single-pass Curator that asked one model to simultaneously cluster + assign + score is gone.
- **Source merge + renumber** (`merge_sources` → `renumber_sources`) lift the hydration and research dossiers into a single sequential `src-NNN` keyspace deterministically; downstream agents never see `rsrc-` IDs.
- **Coverage-gap validation** (`validate_coverage_gaps_stage`) filters LLM-emitted gap statements against the actual source pool — an LLM that claims "no Hebrew sources" while a Hebrew source is in the dossier is overruled by Python.
- **Bias-Card aggregation** (`compose_bias_card`): the public bias card is a derived render view over five Bus slots (`bias_language_findings`, `final_sources`, `source_balance`, `coverage_gaps_validated`, `transparency_card`). The bias detector emits only originary linguistic findings; the geographic / source / selection / framing dimensions are computed in Python.
- **Counting is never delegated to LLM.** The Hydration aggregator does not self-verify its array length; the chunk validator in Python catches missing `article_index` values and retries with the missing indices only.

### Principle 2 — Agents produce only originary output

**An agent must only output what it genuinely creates through its own work.** Fields that are simply passed through — URLs, outlet names, language codes, dates, titles, source IDs — should not appear in the agent's output schema. Python handles the pass-through and merges originary agent output with reference data via the Bus slot routing.

The cost of violating this principle is both tokens (input + output paid twice for no value) and architecture (agents become brittle format-translators instead of reasoning modules).

Applied in the current V2 pipeline:
- **Bias Language** agent outputs only `language_bias` findings and `reader_note` — it does not re-emit the source list or divergences, which Python aggregates from other slots at render time.
- **QA+Fix** returns corrections plus the corrected article body (the latter via the `qa_corrected_article` empty-then-fill mirror) — not the full Topic Package, which Python assembles from the merged Bus state.
- **Hydration aggregator (Phase 1)** returns `article_analyses[]` with `article_index`, `summary`, and `actors_quoted` only. URL, outlet, language, country, title, estimated_date are pass-through via Python merge keyed by `article_index`.
- **Curator Topic Discovery** emits only `{topics: [{title, summary}]}`. Source IDs, finding counts, geographic coverage, language coverage, source-diversity flags are all attached deterministically by `assemble_curator_topics` after `gravitational_assign` has produced the assignments.
- **Perspective** emits per-cluster `actor_ids[]`; the canonical actor identity is held in `final_actors` (via `consolidate_actors`) / `canonical_actors` (via `ResolveActorAliasesStage`). Render joins the two.

### Audit posture

The two principles were formalised during Session 10 (April 2026). Most V1 agents predated the formalisation; V2 wired them into the Bus slot model with declared owners, structurally enforcing the principles at the runner level (a stage that writes to a slot it does not own fails precondition validation).

A pipeline-wide audit was catalogued as an open work item in V1; in V2 the structural enforcement subsumes most of it. The remaining audit surface — checking that each agent's prompt and output schema does not redundantly emit pass-through fields — is folded into the per-agent prompt-review work (Researcher-Polish, future Writer/QA reviews). Empirical evidence of the architecture working is in the cluster-quality re-audit (`docs/cluster-quality-audit/audit-2026-05-16-recalibrated/`).

### Contract discipline

**Agent output schemas in task briefs are complete specifications.** Unlisted fields are not added silently by implementation; useful telemetry is surfaced as questions for architect review. This rule was formalised after a Session 11 incident where a Claude Code implementation added a `fetch_started_at` field to the hydration output without it being in the brief. The same discipline applies to pipeline helper functions, Bus slot definitions, and Topic Package schema: additions are decisions, not drift.

### Field-absence vs null value (delta-emitter pattern)

**When an agent emits delta output, field absence and null value carry different semantics.** Absence means "do not touch this field"; null means "set this field to null" (e.g. remove a quote). Python checks must use `"field" in delta`, never `delta.get("field") is None`. The Perspective-Sync stage in the hydrated variant is the canonical instance — its `position_cluster_updates[]` carries per-cluster delta objects whose `position_label` / `position_summary` fields are merged by `_merge_perspective_deltas` only when present in the delta.

---

## Error Handling and Retries

Agent-level exponential backoff with jitter for transient API errors (429, 5xx). Auth errors (401/403) and invalid requests (400) are raised immediately. Pipeline continues after individual topic failures — failed topics are logged and reported. Per-stage Bus snapshots are persisted to `output/{date}/_state/run-{run_id}/` after each stage for crash recovery.

## Configuration

File-based, environment-overridable, path-agnostic. API keys are **never** in the config file — config references env var names; the loader reads actual values from the environment. Profile system for model overrides (develop / demo).

## Dependencies (V2 baseline)

```toml
dependencies = [
    "openai>=1.0",          # OpenAI-compatible API client (works with OpenRouter)
    "httpx",                # async HTTP for tool implementations
    "feedparser",           # RSS feed parsing
    "json-repair",          # recovery of malformed LLM JSON output
    "trafilatura",          # article full-text extraction (Hydration variant)
    "aiohttp",              # parser-tolerant async HTTP (Hydration variant)
    "pydantic",             # RunBus / TopicBus typed models (V2)
    "fastembed==0.8.0",     # ONNX multilingual MiniLM-L12-v2 — Curator pre-clustering + gravitational assignment
    "scikit-learn>=1.3",    # Agglomerative clustering for pre-clusters (Brief 1)
    "numpy",                # cosine similarity in gravitational assignment
]
```

`pydantic` is V2's contribution (RunBus + TopicBus models). `fastembed` + `scikit-learn` + `numpy` are the Brief 1 / Brief 2 contributions, raising the site-packages ceiling from 400 → 600 MB (rationale in `docs/ADR-COHERENCE-STAGE-DEPENDENCY-ADDENDUM-2026-05-15.md`). `trafilatura` and `aiohttp` serve the Hydration variant only. No langchain. No pytorch. Production variant runs without `trafilatura` / `aiohttp` if hydration is disabled.

---

## What This Architecture Enables (Without Rewriting)

| Future Need | How It's Handled |
|-------------|-----------------|
| **Memory** | `Agent.memory_path` loads memory into the User-turn `<memory>` block at runtime |
| **Parallelization** | Topic-stages have no cross-TopicBus dependency in V2; running them under `asyncio.gather()` is a runner-only change (`WP-TOPIC-STAGE-PARALLELISATION`) |
| **New tools** | `registry.register(new_tool)` |
| **New consumers (MCP server, RSS, internal export)** | New render function in `src/render.py`, schema-driven by `visibility` metadata |
| **Docker deployment** | All config via env vars or config file |
| **Different providers** | Agent's `provider` field |
| **Structured output** | Agent's `output_schema` parameter; schema enforced at decode time via OpenRouter `response_format` |
| **Error recovery** | `PipelineRunner` resumes from last per-stage snapshot in `output/{date}/_state/run-{run_id}/` |

## Current Model Assignments (V2, post Brief 5b)

Authoritative table in `docs/AGENT-IO-MAP.md` §1; snapshot here. All via OpenRouter; reasoning none unless noted; synthesis agents at temperature 0.1; extraction agents at 0.2–0.3.

| Agent | Model | Temp | Reasoning | Notes |
|-------|-------|---:|---|---|
| curator_topic_discovery | google/gemini-3-flash-preview | 1.0 | none | Replaces the legacy V1 `curator` agent; only Curator-side LLM in V2 |
| editor | anthropic/claude-opus-4.6 | 0.3 | none | |
| researcher_plan | anthropic/claude-opus-4.6 | 0.5 | none | Opus 4.6 since Researcher-Polish iter 1 (commit `b2bec02`) |
| researcher_assemble | deepseek/deepseek-v4-flash | 0.5 | none | Migrated from `google/gemini-3-flash-preview` 2026-05-18 per Wave-1 Sweep #3 (~4.3× cheaper at $0.006/topic; 15/15/15 sources vs prior 15/12/10) |
| resolve_actor_aliases | google/gemini-3-flash-preview | 1.0 | medium | F2 alias-merge (Y-config) |
| perspective | anthropic/claude-opus-4.6 | 0.1 | none | (formerly "perspektiv" — anglicised in V2-07) |
| writer | anthropic/claude-opus-4.6 | 0.3 | none | No web_search tool in V2 (since V2-09c2) |
| qa_analyze | anthropic/claude-sonnet-4.6 | 0.1 | none | Never use `r-medium` — crashes 2/4 in eval |
| bias_language | anthropic/claude-opus-4.6 | 0.1 | none | |
| researcher_hydrated_plan | anthropic/claude-opus-4.6 | 0.5 | none | Hydrated variant of researcher_plan |
| hydration_aggregator_phase1 | deepseek/deepseek-v4-pro | 0.3 | none | Per-chunk extraction (parallel, chunked) |
| hydration_aggregator_phase2 | anthropic/claude-opus-4.6 | 0.1 | none | Cross-corpus reducer (single call) |
| perspective_sync | anthropic/claude-opus-4.6 | 0.1 | none | Hydrated-only; per-element delta-mirror |

**Migration pending:** All `anthropic/claude-opus-4.6` agents above are staged for simultaneous migration to `anthropic/claude-opus-4.7` as a single workstream (`WP-OPUS-4.7-MIGRATION`). Opus 4.7 removes `temperature`, `top_p`, `top_k` as supported parameters (returns 400 on any non-default value) and replaces discrete reasoning levels with `output_config.effort` (low / medium / high / xhigh / max, always active). This requires `src/agent.py` refactor plus per-agent effort-level evaluation before cutover — not a drop-in swap.

---

## Hydration Pipeline (Stage 2 — Integrated, Production-Ready)

The Production pipeline described above treats the Curator's clustered RSS findings as a ranking signal only: after the Editor selects the top 3 topics, the Researcher begins from zero, querying the web independently via search snippets. The RSS-cluster content — 15–25 articles per topic across 5–8 languages — is discarded. The Writer never sees the actual RSS source texts, only web-search snippets.

**Stage 2 ("Hydrated variant") adds a parallel pipeline that uses the cluster content.** After the Editor and before the Researcher, a hydration sub-pipeline fetches the cluster URLs directly via HTTP, extracts article full-text, and passes it through a two-phase chunked Aggregator LLM pipeline that produces a pre-dossier in the same shape as the Researcher Assembler output. The Researcher Assembler then extends this pre-dossier with web-search results covering gaps that the cluster did not. Python merges both dossiers and renumbers the unified source list into a single `src-NNN` keyspace.

In V2 this is no longer a separate `pipeline_hydrated.py` file; it is a different stage list (`build_hydrated_stages`) over the same Stage + RunBus + TopicBus primitives. The deterministic hydration glue lives in `src/stages/run_stages.py` and `src/stages/topic_stages.py`; the two LLM agents (`hydration_aggregator_phase1`, `hydration_aggregator_phase2`) are wrapped in `src/agent_stages.py`.

### Why it was decided

Two feasibility spikes established the empirical base:

**Spike 1 — Fetch viability (httpx + trafilatura):** 30/51 URLs from Lauf 19's produced topics extracted to full-text (58.8 %). Failures concentrated in two categories: 10 URLs in `connection_error` caused by httpx's strict HTTP parser rejecting Anadolu Agency's non-conformant Transfer-Encoding headers; 11 URLs in `bot_blocked` or `partial` from real outlet policy (FT, Axios, SCMP, Dawn, Meduza, Le Monde paywalls).

**Spike B — Parser tolerance (aiohttp):** Swapping httpx for aiohttp recovered all 6 Anadolu URLs. Success rate rose to 70.6 % (36/51). Remaining failures are structural, not tooling: Press TV unreachable from this network (`tls_error` subtype, likely sanctions-routing), and the bot-protected / paywalled outlets are not recoverable by any respectful-scraping approach.

**Spike C — Aggregator quality (two Gemini models):** The Hydration Aggregator prompt was tested on the 36 Spike-B successes across `google/gemini-3-flash-preview` and `google/gemini-3.1-flash-lite-preview`. Flash-preview: 100 % structural compliance (12/12 articles analysed per topic), avg 36–55 word summaries, 4–5 divergences and 4 gaps per topic. Flash-lite: 11/12 on one topic (Rule 1 violation — a disqualification for production), shallower summaries, fewer divergences. Decision: **Gemini 3 Flash as the Phase-1 production Aggregator model** at the time of Spike C; production cut over to `deepseek/deepseek-v4-pro` for Phase 1 in TASK-EVIDENCE-TYPE-MIGRATION A3 (Flash kept as a commented-out fallback in `scripts/run.py`). Phase 2 stayed on Opus 4.6 (selected after 5-variant blind eval).

### Scraping ethics position

The Hydration pipeline fetches article full-text from public RSS-listed URLs. This is text-and-data mining for editorial analysis, not content republication. Independent Wire's operating principles for this pipeline:

1. **Only top-3 produced topics are fetched**, not the 1,400+ full feed findings.
2. **Identifiable bot user-agent:** `Independent-Wire-Bot/1.0 +https://independent-wire.org` — outlets can see us and contact us.
3. **Per-domain rate limit:** 1 request per second maximum.
4. **Robots.txt respected** — any `Disallow` on the target path means no fetch.
5. **No circumvention** of Cloudflare, CAPTCHA, or paywalls. When an outlet blocks, we skip.
6. **Full-text used only as LLM-context** for paraphrased journalism. Never reproduced verbatim in the published article.
7. **Public documentation** in the repo README: the list of outlets regularly fetched, the user-agent string, purpose, and the Remove-My-Outlet contact.

Under this discipline, Hydration is indistinguishable in moral weight from the Production pipeline's existing reliance on web-search providers. The difference is ownership: we take the responsibility and the transparency burden directly rather than pay a third party to do it with less visibility.

### Aggregator Chunking Architecture (Session 12)

The original Aggregator was a single monolithic call: all N successfully-fetched articles entered one LLM prompt, and the model produced both per-article analyses and cross-corpus divergences/gaps in one response. This worked on small inputs (≤15 articles) but failed systematically on larger inputs: Gemini 3 Flash dropped exactly one article's analysis when N ≥ 17, triggering a Rule-1 validation crash.

The diagnosis was not that Gemini 3 Flash is unsuitable — it is excellent at per-article extraction — but that attention load on the extraction task grew with N faster than attention budget. The architectural response was to split the Aggregator into two phases and chunk the first phase:

**Phase 1 — Per-article extraction (parallel, chunked):**
- Chunk sizing: `ceil(N / 10)` chunks, distributed evenly so every chunk has between 5 and 10 articles.
- Chunks fire in parallel via `asyncio.gather`. Each chunk's LLM call runs the registered `hydration_aggregator_phase1` agent (loading `agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md`) and returns `article_analyses[]` for only its chunk's articles.
- Intelligent retry per chunk, max 2 attempts. If the response is missing some `article_index` values, the retry sends only the missing articles back as a smaller input. This both reduces the attention load on the retry and eliminates re-work for already-successful extractions in the same chunk.
- Hard crash after 2 retries of a chunk. Silent data loss is worse than pipeline failure.

**Phase 2 — Cross-corpus reducer (single call):**
- After all Phase 1 chunks complete, Python merges `article_analyses[]` into a flat sorted list by `article_index`.
- A single LLM call runs the registered `hydration_aggregator_phase2` agent (loading `agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md`) with the merged analyses plus per-article metadata (language, country, outlet). This produces `preliminary_divergences[]` and `coverage_gaps[]` in one shot.
- Cross-linguistic and cross-regional observations require a global view of the corpus, which Phase 1's chunked extraction cannot produce. The Phase 2 input is compact (summaries, not full-text), so attention load is low regardless of N.

**Counting is deterministic in Python, never delegated to LLM.** Prompt-engineer correction during PHASE1-INSTRUCTIONS.md review: the prompt does not ask the LLM to verify its output length, count its array entries, or enforce an `expected_count`. The validation happens in the Phase-1 wrapper in `src/agent_stages.py` after each response; missing indices trigger retry. This generalises Principle 1 ("deterministic before LLM") into prompt-design discipline — the LLM should never be asked to perform a task Python can perform deterministically, even as a self-check.

The chunking architecture scales to arbitrary N without code changes. 32-article topic chunks cleanly into [8,8,8,8], 15-article into [7,8], 5-article into [5].

### Pipeline shape (V2)

```
Production (V2):
  init_run → fetch_findings →
    pre_cluster_findings → CuratorTopicDiscoveryStage → gravitational_assign →
    assemble_curator_topics → EditorStage → select_topics → instantiate_topic_buses →
  ResearcherPlanStage → researcher_search → ResearcherAssembleStage →
    merge_sources → renumber_sources → filter_media_actors_quoted →
    propagate_outlet_metadata → consolidate_actors → ResolveActorAliasesStage →
    partition_canonical_actors_by_evidence → normalize_pre_research →
  PerspectiveStage → enrich_perspective_clusters → mirror_perspective_synced →
  WriterStage → QaAnalyzeStage → mirror_qa_corrected →
    prune_unused_sources_and_clusters → cleanup_stale_references →
    compute_source_balance → validate_coverage_gaps_stage →
  BiasLanguageStage → compose_transparency_card → finalize_run

Hydrated (V2):
  …same Curator + Editor head as production…
  attach_hydration_urls_to_assignments → select_topics → instantiate_topic_buses →
  attach_hydration_urls → hydration_fetch →
    HydrationPhase1Stage → HydrationPhase2Stage → assemble_hydration_dossier →
  ResearcherHydratedPlanStage → researcher_search → ResearcherAssembleStage →
    …same source-merge + actor + perspective head as production…
  mirror_perspective_synced (1st invocation — 1:1 fill) →
  WriterStage → QaAnalyzeStage → mirror_qa_corrected →
  PerspectiveSyncStage → mirror_perspective_synced (2nd invocation — per-element delta merge) →
    …same cleanup + bias + transparency tail as production…
```

The downstream agents (Researcher, Perspective, Writer, QA+Fix, Bias Language) operate on the same Bus slot contract regardless of variant. Variant differences are confined to the head of the topic-stage list. See `docs/ARCH-V2-BUS-SCHEMA.md` §5.1 / §5.2 for the full ordered lists and `docs/AGENT-IO-MAP.md` §2.x for per-stage I/O contracts.

---

## File Structure (V2)

```
independent-wire/
├── src/
│   ├── agent.py              # Agent class + AgentResult (moved from src/models.py in V2-11b)
│   ├── bus.py                # RunBus + TopicBus Pydantic models (visibility, mirrors_from metadata)
│   ├── stage.py              # Typed stage interface (run_stage / topic_stage)
│   ├── stages/
│   │   ├── coherence.py      # Embedding singleton + cosine helpers (stage callable removed B5)
│   │   ├── pre_cluster.py    # Brief 1 — Agglomerative pre-clustering
│   │   ├── gravitational_assign.py  # Brief 2 + Brief 5b — cosine-threshold assignment (T=0.55)
│   │   ├── run_stages.py     # Deterministic run-stages (init_run, fetch_findings, merge, renumber, …)
│   │   └── topic_stages.py   # Deterministic topic-stages (consolidate_actors, mirror_*, compute_source_balance, …)
│   ├── agent_stages.py       # Agent-stage wrappers (Curator, Editor, Researcher, Perspective, Writer, QA, Bias, Hydration P1/P2, PerspectiveSync, …)
│   ├── render.py             # Render layer (visibility-driven filter; tp / mcp / rss / internal)
│   ├── runner/
│   │   ├── __init__.py       # PipelineRunner
│   │   ├── stage_lists.py    # build_production_stages, build_hydrated_stages
│   │   └── state.py          # Per-stage Bus snapshot persistence
│   ├── schemas.py            # Strict-mode JSON schemas (OpenRouter response_format)
│   └── tools/
│       ├── registry.py
│       ├── web_search.py     # web_search tool (Perplexity, Brave, DuckDuckGo)
│       ├── web_fetch.py
│       └── file_ops.py
├── agents/                   # Agent prompts (two-file convention since S13)
│   ├── curator/{SYSTEM,INSTRUCTIONS}.md          # Topic-Discovery prompt (Brief 4 PE round)
│   ├── editor/{SYSTEM,INSTRUCTIONS}.md
│   ├── researcher/{PLAN,ASSEMBLE}-{SYSTEM,INSTRUCTIONS}.md
│   ├── researcher_hydrated/PLAN-{SYSTEM,INSTRUCTIONS}.md
│   ├── perspective/{SYSTEM,INSTRUCTIONS}.md      # Anglicised in V2-07 (was perspektiv/)
│   ├── perspective_sync/{SYSTEM,INSTRUCTIONS}.md
│   ├── writer/{SYSTEM,INSTRUCTIONS}.md
│   ├── writer/FOLLOWUP.md                        # Addendum (loaded conditionally)
│   ├── qa_analyze/{SYSTEM,INSTRUCTIONS}.md
│   ├── bias_detector/{SYSTEM,INSTRUCTIONS}.md    # Registered as `bias_language`
│   ├── resolve_actor_aliases/{SYSTEM,INSTRUCTIONS}.md  # F2 alias-merge
│   ├── hydration_aggregator/
│   │   ├── PHASE1-{SYSTEM,INSTRUCTIONS}.md       # Per-article extraction
│   │   └── PHASE2-{SYSTEM,INSTRUCTIONS}.md       # Cross-corpus reducer
│   └── _archive/                                 # Deprecated prompts retained for git-blame
├── config/
│   ├── sources.json          # 72 RSS feeds, with tier / editorial_independence / bias_note metadata
│   ├── outlet_registry.json  # 118+ outlets with country / language / type
│   ├── style-guide.md
│   └── profiles/             # Model profile overrides (develop, demo)
├── scripts/
│   ├── run.py                # Main pipeline entry point (V2 PipelineRunner; --from/--to/--topic/--reuse/--max-produce flags)
│   ├── render.py             # Topic Package JSON → self-contained HTML
│   ├── publish.py            # Site generator (index.html, feed.xml, sitemap.xml)
│   ├── fetch_feeds.py        # RSS feed fetcher → raw/YYYY-MM-DD/feeds.json
│   ├── audit_cluster_quality.py             # Brief 5 audit harness
│   ├── sweep_gravitational_recalibration.py # Brief 5b sweep harness
│   └── reaudit_cluster_quality_recalibrated.py  # Brief 5b re-audit harness
├── raw/                      # Raw feed data per date (YYYY-MM-DD/feeds.json)
├── output/                   # Pipeline output + per-stage state for crash recovery
│   └── {YYYY-MM-DD}/
│       ├── tp-{date}-NNN.json        # Topic Packages
│       └── _state/run-{run_id}/
│           ├── run_bus.{StageName}.json
│           ├── topic_buses.{StageName}.{N}.json
│           └── run_stage_log.jsonl   # Per-stage timing, status, cost_usd, tokens
├── schema/
│   └── topic-package-v1.json
├── docs/
│   ├── ARCHITECTURE.md                          # This document
│   ├── ARCH-V2-BUS-SCHEMA.md                    # Authoritative V2 bus + stage schema
│   ├── AGENT-IO-MAP.md                          # Authoritative per-stage I/O contract
│   ├── ADR-CURATOR-TRIPLE-STAGE.md              # The Curator architectural decision (implemented + validated)
│   ├── AUDIT-TIMELINE.md                        # Chronological index of V2 calibration / audit artefacts
│   ├── ROADMAP.md
│   ├── TASKS.md
│   ├── VISUALIZATIONS.md
│   ├── FEED-CATALOG.md
│   ├── archive/                                 # Completed tasks, WPs, briefings
│   └── handoffs/                                # Session handoff files
├── tests/                                       # 602 / 0 (V2)
├── .env.example
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── deploy-site.yml   # GitHub Pages deployment on push to site/
├── site/                     # Publication website (generated by publish.py)
│   ├── index.html
│   ├── feed.xml
│   ├── CNAME                 # Custom domain (independent-wire.org)
│   └── reports/              # Rendered TP HTML files
└── LICENSE (AGPL-3.0)
```
