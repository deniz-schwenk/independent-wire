# Agent Prompt Inventory

Authoritative mapping of every prompt file under `agents/` to its agent-stage class, agent configuration, and lifecycle status. Updated whenever a prompt is added, archived, or its load site changes.

Last updated: 2026-05-02 (V2 big-bang work-stream complete; V1 deleted in commit 19348f3)

## Two-file prompt convention

Every active agent's prompt is a pair of files:

- **`agents/{name}/SYSTEM.md`** — the agent's identity. Loaded into the `<system_prompt>` block of the `role: system` message. Contains the agent's role, purpose, and rules. Stable across runs.
- **`agents/{name}/INSTRUCTIONS.md`** — the per-run task spec. Loaded into the `<instructions>` block of the User turn. Describes inputs, outputs, the JSON schema, and step-by-step procedure. Read before every run.

Researcher and Hydration Aggregator have phase-named pairs (`PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md`, `ASSEMBLE-SYSTEM.md` + `ASSEMBLE-INSTRUCTIONS.md`, `PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md`, `PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md`). The convention is otherwise uniform.

`agents/writer/FOLLOWUP.md` is the only single-file survivor — it is an addendum, not a stand-alone agent (see Conditional section below).

## User-turn three-block layout

`Agent.run()` composes the User turn from three sequential blocks, separated by blank lines:

```
<context>
{message + JSON-formatted context (omitted entirely when both are empty)}
</context>

<memory>
{memory_path content (omitted entirely when memory is unset or empty)}
</memory>

<instructions>
{INSTRUCTIONS.md content}

{instructions_addendum, when present}
</instructions>
```

The `<instructions>` block is always present. The other two are conditional on their inputs. The addendum (e.g. Writer FOLLOWUP.md) is appended **inside** the closing `</instructions>` tag, separated from INSTRUCTIONS.md by exactly one blank line. The system message is just `<system_prompt>{SYSTEM.md}</system_prompt>` — nothing else.

---

## Active prompts (V2)

In V2, every agent is invoked by an **agent-stage wrapper class** in `src/agent_stages.py`. The wrapper class reads the relevant Bus slots, formats the agent's input, calls the registered `Agent` instance, and writes the agent's output to the relevant Bus slots. Agent registration (model, temperature, tools, max_tokens, output_schema) happens in `scripts/run.py:create_agents` (production) and `scripts/run.py:create_agents_hydrated` (hydrated, extends production with four hydrated-only agents).

### Production + Hydrated (both pipelines)

Loaded by `scripts/run.py:create_agents` and inherited by `create_agents_hydrated` with identical configs.

| File pair | Agent name | Wrapper class | Model | Temp | Reasoning | max_tokens | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `agents/curator/SYSTEM.md` + `INSTRUCTIONS.md` | `curator` | `CuratorStage` (run-stage) | `google/gemini-3-flash-preview` | 0.2 | `none` | 64000 | `tools=[]`. 64000 max_tokens because the `{topics, cluster_assignments}` envelope on ~1400 findings overflows the 32000 default. Schema: `CURATOR_SCHEMA`. |
| `agents/editor/SYSTEM.md` + `INSTRUCTIONS.md` | `editor` | `EditorStage` (run-stage) | `anthropic/claude-opus-4.6` | 0.3 | `none` | 32000 | `tools=[]`. Reads `previous_coverage` for follow-up decisions. Schema: `EDITOR_SCHEMA`. |
| `agents/researcher/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md` | `researcher_plan` | `ResearcherPlanStage` (topic-stage) | `google/gemini-3-flash-preview` | 0.5 | `none` | 32000 | `tools=[]`. Emits multilingual search query plan. Schema: `RESEARCHER_PLAN_SCHEMA`. |
| `agents/researcher/ASSEMBLE-SYSTEM.md` + `ASSEMBLE-INSTRUCTIONS.md` | `researcher_assemble` | `ResearcherAssembleStage` (topic-stage) | `google/gemini-3-flash-preview` | 0.2 | `none` | 32000 | `tools=[]`. Emits research dossier with `research-rsrc-NNN` IDs (renumbered to `src-NNN` by Python in `renumber_sources` topic-stage). Schema: `RESEARCHER_ASSEMBLE_SCHEMA`. |
| `agents/perspective/SYSTEM.md` + `INSTRUCTIONS.md` | `perspective` | `PerspectiveStage` (topic-stage) | `anthropic/claude-opus-4.6` | 0.1 | `none` | 32000 | `tools=[]`. Emits position clusters; `pc-NNN` IDs and source-balance derivations attached by `enrich_perspective_clusters` deterministic topic-stage. Reads `final_sources` (already in `src-NNN` form). Schema: `PERSPECTIVE_SCHEMA`. |
| `agents/writer/SYSTEM.md` + `INSTRUCTIONS.md` | `writer` | `WriterStage` (topic-stage) | `anthropic/claude-opus-4.6` | 0.3 | `none` | 32000 | `tools=[]` (web_search disabled in V2-09c2 to close `[web-N]` Bug-1). Reads `final_sources`, emits `[src-NNN]` citations directly in `body`. Schema: `WRITER_SCHEMA` (`sources[].src_id` post-V2-09e). |
| `agents/qa_analyze/SYSTEM.md` + `INSTRUCTIONS.md` | `qa_analyze` | `QaAnalyzeStage` (topic-stage) | `anthropic/claude-sonnet-4.6` | 0.1 | `none` | 32000 | `tools=[]`. Never use `r-medium` (crashes 2/4 in eval). Reads `final_sources` and emits `[src-NNN]` citations symmetric with Writer. Slot-level mirror semantics: emits full `article` only when corrections apply, otherwise omits. Schema: `QA_ANALYZE_SCHEMA`. |
| `agents/bias_detector/SYSTEM.md` + `INSTRUCTIONS.md` | `bias_language` | `BiasLanguageStage` (topic-stage) | `anthropic/claude-opus-4.6` | 0.1 | `none` | 32000 | Filename is `bias_detector/`; the registered agent name is `bias_language`. `tools=[]`. Reads `qa_corrected_article`. Schema: `BIAS_DETECTOR_SCHEMA`. |

### Hydrated only

Loaded only by `scripts/run.py:create_agents_hydrated` (additive on top of `create_agents`).

| File pair | Agent name | Wrapper class | Model | Temp | Reasoning | max_tokens | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `agents/researcher_hydrated/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md` | `researcher_hydrated_plan` | `ResearcherHydratedPlanStage` (topic-stage) | `google/gemini-3-flash-preview` | 0.5 | `none` | 16384 | `tools=[]`. Gap-aware plan reads `hydration_pre_dossier` coverage summary (computed by deterministic helper `_build_coverage_summary` internalised into `src/agent_stages.py` in V2-11a). Schema: `RESEARCHER_PLAN_SCHEMA` (same shape as production planner). |
| `agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md` | `hydration_aggregator_phase1` | `HydrationPhase1Stage` (topic-stage) | `google/gemini-3-flash-preview` | 0.3 | `none` | 32000 | `tools=[]`. Per-article extraction, parallel chunked (`ceil(N/10)` chunks of 5–10 articles). Up to 2 retries per chunk that re-request only missing indices. Schema: `HYDRATION_PHASE1_SCHEMA`. |
| `agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md` | `hydration_aggregator_phase2` | `HydrationPhase2Stage` (topic-stage) | `anthropic/claude-opus-4.6` | 0.1 | `none` | 32000 | `tools=[]`. Cross-corpus reducer over phase1 analyses. Eval-validated at 114/120 (Opus 4.6 @ temp 0.1). Schema: `HYDRATION_PHASE2_SCHEMA`. |
| `agents/perspective_sync/SYSTEM.md` + `INSTRUCTIONS.md` | `perspective_sync` | `PerspectiveSyncStage` (topic-stage) | `anthropic/claude-opus-4.6` | 0.1 | `none` | 32000 | `tools=[]`. Per-element mirror semantics: emits cluster deltas (id + only changed fields). The `mirror_perspective_synced` deterministic stage merges deltas onto `perspective_clusters_synced`. Schema: `PERSPECTIVE_SYNC_SCHEMA`. |

### Conditional addendum

Not a stand-alone agent — appended inside the Writer's `<instructions>` block when the topic is a follow-up.

| File | Used by | Trigger | Notes |
| --- | --- | --- | --- |
| `agents/writer/FOLLOWUP.md` | `WriterStage` | `editor_selected_topic.follow_up` is non-empty | Loaded as `instructions_addendum` parameter to `Agent.run()`. Single-file survivor of the two-file convention. |

### Deactivated (configuration kept commented in source)

The Collector agent is deactivated in `scripts/run.py:create_agents` — RSS feeds provide sufficient coverage at current scale. The two-file pair `agents/collector/PLAN-SYSTEM.md` + `INSTRUCTIONS.md` and `ASSEMBLE-SYSTEM.md` + `INSTRUCTIONS.md` remain on disk. Reactivate when scaling to 200+ feeds as pre-filter for the Curator.

---

## Archived prompts

Located under `agents/_archive/`. Not loaded by any active code path. Preserved for historical reference and revert paths during eval.

The V2 work-stream anglicised two German agent names (per `docs/ARCH-V2-BUS-SCHEMA.md` §10 decision-log entry of 2026-04-29):

| Folder | Reason for archival | Replaced by |
| --- | --- | --- |
| `agents/_archive/perspektiv/` | Anglicised during V2 implementation | `agents/perspective/` |
| `agents/_archive/perspektiv_sync/` | Anglicised during V2 implementation | `agents/perspective_sync/` |

Other historical archived prompts may exist; consult `agents/_archive/` directly.

---

## Architectural principle

Each entry above shows what the agent emits. **Pipeline-derived fields (IDs, slugs, dates, counts, source enrichment) are routed by Python in `src/stages/topic_stages.py` or `src/stages/run_stages.py`, never by the LLM.** See `docs/AGENT-IO-MAP.md` for the per-agent input/output contract and the corresponding deterministic stages.

The two named architectural principles (formalised in `docs/ARCH-V2-BUS-SCHEMA.md` §3.1 and §3.2):

1. **Originary output** — every Bus slot has exactly one owner; agents do not write to slots owned by other agents. Pass-through fields are routed by Python after the LLM call.
2. **Agents are isolated from the Bus schema** — agents emit structures local to their task in their own contract; the agent-stage wrappers in `src/agent_stages.py` map those structures onto Bus slots. Agents are reusable across pipeline variants without prompt changes.

---

## Agent invocation lifecycle (V2)

The code path for any agent invocation:

1. **Pipeline runner** (`src/runner/runner.py:PipelineRunner`) picks up the next stage from the active stage list (`src/runner/stage_lists.py:build_production_stages` or `build_hydrated_stages`).
2. **Stage dispatch.** Run-stages call `stage(run_bus)`, topic-stages call `stage(topic_bus, run_bus)`. Agent-stage wrappers are instances of classes in `src/agent_stages.py` (e.g. `WriterStage(agents["writer"])`); deterministic stages are pure functions in `src/stages/`.
3. **Agent-stage wrapper** reads the declared input slots from the bus, formats them as a JSON-encoded `context` dict, and calls `agent.run(context=...)`.
4. **`Agent.run()`** (`src/agent.py`) composes the three-block User turn (context / memory / instructions), sends to OpenRouter with strict-mode `output_schema` enforcement, handles tool calls in a loop if the agent has tools registered, and returns an `AgentResult` (defined in `src/agent.py` post-V2-11b; previously in deleted `src/models.py`).
5. **Wrapper extraction.** The wrapper extracts the `structured` dict from `AgentResult`, performs any agent-local post-processing (e.g. merging schema-required fields with pass-through fields), and writes to the declared output slots.
6. **Pipeline runner** advances to the next stage. Stage execution is logged into `run_bus.run_stage_log` with `started_at`, `ended_at`, status, and scope.

For deterministic stages (steps 3–5 above), the agent invocation is replaced by a pure Python function call. The bus interface and logging are identical.
