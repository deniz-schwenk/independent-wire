# Agent Prompt Inventory

Authoritative mapping of every prompt file under `agents/` to its load site, agent configuration, and lifecycle status. Updated whenever a prompt is added, archived, or its load site changes.

Last updated: 2026-04-27

## Two-file prompt convention (S13)

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

## Active prompts

### Production + Hydrated (both pipelines)

Loaded by `scripts/run.py:create_agents` *and* `scripts/test_hydration_pipeline.py:create_hydrated_agents` with identical configs (modulo `max_tokens`, which the hydrated wiring overrides locally).

| File pair | Agent name | Model | Temp | Reasoning | Notes |
| --- | --- | --- | --- | --- | --- |
| `agents/perspektiv/SYSTEM.md` + `INSTRUCTIONS.md` | `perspektiv` | `anthropic/claude-opus-4.6` | 0.1 | `none` | V2 (position clusters), `tools=[]` |
| `agents/writer/SYSTEM.md` + `INSTRUCTIONS.md` | `writer` | `anthropic/claude-opus-4.6` | 0.3 | `none` | `tools=[web_search_tool]` |
| `agents/qa_analyze/SYSTEM.md` + `INSTRUCTIONS.md` | `qa_analyze` | `anthropic/claude-sonnet-4.6` | 0.1 | `none` | `tools=[]`. Never use `r-medium` (per `run.py` docstring) |
| `agents/bias_detector/SYSTEM.md` + `INSTRUCTIONS.md` | `bias_language` | `anthropic/claude-opus-4.6` | 0.1 | `none` | Filename is `bias_detector/`; the registered agent name is `bias_language`. `tools=[]` |
| `agents/researcher/ASSEMBLE-SYSTEM.md` + `ASSEMBLE-INSTRUCTIONS.md` | `researcher_assemble` | `google/gemini-3-flash-preview` | 0.2 | `none` | `tools=[]` |

### Production only

Loaded only by `scripts/run.py:create_agents`.

| File pair | Agent name | Model | Temp | Reasoning | Notes |
| --- | --- | --- | --- | --- | --- |
| `agents/curator/SYSTEM.md` + `INSTRUCTIONS.md` | `curator` | `google/gemini-3-flash-preview` | 0.2 | `none` | `tools=[]` |
| `agents/editor/SYSTEM.md` + `INSTRUCTIONS.md` | `editor` | `anthropic/claude-opus-4.6` | 0.3 | `none` | `tools=[]` |
| `agents/researcher/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md` | `researcher_plan` | `google/gemini-3-flash-preview` | 0.5 | `none` | `tools=[]`. Hydrated pipeline uses `researcher_hydrated/PLAN-*.md` instead |

### Hydrated only

Loaded only by `scripts/test_hydration_pipeline.py:create_hydrated_agents` or by `src/pipeline_hydrated.py` itself.

| File pair | Agent name | Model | Temp | Reasoning | Notes |
| --- | --- | --- | --- | --- | --- |
| `agents/researcher_hydrated/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md` | `researcher_hydrated_plan` | `google/gemini-3-flash-preview` | 0.5 | `none` | Hydrated planner; sees pre-dossier coverage summary. `max_tokens=16384` |
| `agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md` | `hydration_aggregator_phase1` | `google/gemini-3-flash-preview` | 0.3 | `none` | Per-chunk article extraction. Registered as a proper Agent instance in `create_hydrated_agents`. Run by `_run_phase1_chunk` in `src/hydration_aggregator.py`. `max_tokens=32000` |
| `agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md` | `hydration_aggregator_phase2` | `anthropic/claude-opus-4.6` | 0.1 | `none` | Cross-corpus reducer. Registered as a proper Agent instance in `create_hydrated_agents`. Run by `_run_phase2_reducer` in `src/hydration_aggregator.py`. `max_tokens=32000` |
| `agents/perspektiv_sync/SYSTEM.md` + `INSTRUCTIONS.md` | `perspektiv_sync` | `anthropic/claude-opus-4.6` | 0.1 | `none` | **Active.** V2 sync — emits `position_cluster_updates[]` with `position_label` / `position_summary` deltas. Auto-registered by `PipelineHydrated.__init__` (`src/pipeline_hydrated.py`) when not pre-supplied. Eligibility gated on QA reporting `proposed_corrections`; runs after QA+Fix in the hydrated pipeline. `tools=[]` |

### Conditional

Prompts loaded on specific code paths only.

| File | Agent name | Trigger | Composition | Notes |
| --- | --- | --- | --- | --- |
| `agents/writer/FOLLOWUP.md` | `writer` (extension) | `assignment.follow_up_to` is truthy on the topic being produced | Read into `writer_addendum` and passed to `Agent.run(..., instructions_addendum=writer_addendum)`. Appended **inside** the User-turn `<instructions>` block, separated from INSTRUCTIONS.md by one blank line | Loaded by both `src/pipeline.py` and `src/pipeline_hydrated.py`. Both call sites log a WARNING if the file is missing; pipeline does not fail. Active-by-design — do not archive |

### Test-only

Referenced by string literal only in test/spike scripts; not loaded by any pipeline run.

| File | Reference | Notes |
| --- | --- | --- |
| `agents/collector/AGENTS.md` | `tests/test_tools.py` (6 sites) | Used as a fixture path when constructing test Agent instances. Single-file legacy form retained because the Collector pipeline step is fully disabled (see below). Companion to the disabled `collector/PLAN.md` and `collector/ASSEMBLE.md`. The Agent constructor stores both paths but does not read the file unless `.run()` is called, which these tests do not do |

## Disabled prompts

Present in the codebase but explicitly commented out at their load site. Not archived because reactivation is planned.

| File | Disabled at | Reason | Reactivation criterion |
| --- | --- | --- | --- |
| `agents/collector/PLAN.md` | `scripts/run.py` (commented `collector_plan` block) | RSS feeds suffice at current scale; Collector deactivated | 200+ RSS feeds — pre-filter for the Curator |
| `agents/collector/ASSEMBLE.md` | `scripts/run.py` (commented `collector_assemble` block) | Same | Same |

The disabled blocks reference the two-file convention (`PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md`, `ASSEMBLE-SYSTEM.md` + `ASSEMBLE-INSTRUCTIONS.md`); those files do not exist on disk yet and would need to be created if the Collector is reactivated.

## Archived prompts

Moved to `agents/_archive/` on the date below. Reason for archival: no live load site found.

| File (archived path) | Original path | Archived on | Reason |
| --- | --- | --- | --- |
| `agents/_archive/hydration_aggregator-AGENTS-2026-04-23.md` | `agents/hydration_aggregator/AGENTS.md` | 2026-04-23 | Legacy single-pass design replaced by the two-phase chunked aggregator (S12 commits `1ceac49` + `7437753`). The S12 deprecation banner expired after multiple green hydrated runs through S13 |

The `agents/_archive/` directory contains a `README.md` explaining its purpose.

## Unresolved

Files where status could not be determined automatically and require architect review before archival.

| File | Issue | Recommended action |
| --- | --- | --- |
| *None* | | |

## Reference: full canonical wiring

Source of truth for every active configuration above:

- `scripts/run.py:create_agents` — production pipeline.
- `scripts/test_hydration_pipeline.py:create_hydrated_agents` — hydrated pipeline.
- `src/hydration_aggregator.py` — Phase 1 / Phase 2 wiring inside the chunked aggregator (`PHASE_PROMPT_PATHS` constant; `run_aggregator(phase1_agent=..., phase2_agent=...)`; `_run_phase1_chunk`, `_run_phase2_reducer`).
- `src/pipeline_hydrated.py` — `perspektiv_sync` auto-registration in `PipelineHydrated.__init__`; `_run_perspektiv_sync` (V2) and `merge_perspektiv_deltas` (V2 cluster-shape merge).
- `src/pipeline.py` and `src/pipeline_hydrated.py` — `agents/writer/FOLLOWUP.md` conditional load and `instructions_addendum` plumbing.
- `src/agent.py` — `_build_system_prompt`, `_build_user_message` (three-block User-turn layout).
