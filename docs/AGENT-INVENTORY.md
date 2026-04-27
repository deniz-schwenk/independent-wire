# Agent Prompt Inventory

Authoritative mapping of every prompt file under `agents/` to its load site, agent configuration, and lifecycle status. Updated whenever a prompt is added, archived, or its load site changes.

Last updated: 2026-04-27

## Active prompts

### Production + Hydrated (both pipelines)

Loaded by `scripts/run.py:create_agents` *and* `scripts/test_hydration_pipeline.py:create_hydrated_agents` with identical configs (modulo `max_tokens`, which the hydrated wiring overrides locally).

FileAgent nameModelTempReasoningNotes`agents/perspektiv/AGENTS.mdperspektivanthropic/claude-opus-4.6`0.1`none`V2 (position clusters), `tools=[]agents/writer/AGENTS.mdwriteranthropic/claude-opus-4.6`0.3`nonetools=[web_search_tool]agents/qa_analyze/AGENTS.mdqa_analyzeanthropic/claude-sonnet-4.6`0.1`nonetools=[]`. NEVER use `r-medium` (per `run.py` docstring)`agents/bias_detector/AGENTS.mdbias_languageanthropic/claude-opus-4.6`0.1`none`Filename is `bias_detector/AGENTS.md` but the registered agent name is `bias_language`. `tools=[]agents/researcher/ASSEMBLE.mdresearcher_assemblegoogle/gemini-3-flash-preview`0.2`nonetools=[]`

### Production only

Loaded only by `scripts/run.py:create_agents`.

FileAgent nameModelTempReasoningNotes`agents/curator/AGENTS.mdcuratorgoogle/gemini-3-flash-preview`0.2`nonetools=[]agents/editor/AGENTS.mdeditoranthropic/claude-opus-4.6`0.3`nonetools=[]agents/researcher/PLAN.mdresearcher_plangoogle/gemini-3-flash-preview`0.5`nonetools=[]`. Hydrated pipeline uses `researcher_hydrated/PLAN.md` instead

### Hydrated only

Loaded only by `scripts/test_hydration_pipeline.py:create_hydrated_agents` or by `src/pipeline_hydrated.py` itself.

FileAgent nameModelTempReasoningNotes`agents/researcher_hydrated/PLAN.mdresearcher_hydrated_plangoogle/gemini-3-flash-preview`0.5`none`Hydrated planner, sees pre-dossier coverage summary. `max_tokens=16384agents/hydration_aggregator/PHASE1.mdhydration_aggregator` (clone)`google/gemini-3-flash-preview`0.3`none`Loaded via `src/hydration_aggregator.py:_make_phase_agent` (line 269). Per-chunk article extraction. Inherits config from the registered `hydration_aggregator` template (see Unresolved)`agents/hydration_aggregator/PHASE2.mdhydration_aggregator_phase2anthropic/claude-opus-4.6`0.1`none`Loaded directly in `src/hydration_aggregator.py` (line 383). Cross-corpus reducer. `max_tokens=32000agents/perspektiv_sync/AGENTS.mdperspektiv_syncanthropic/claude-opus-4.6`0.1`none`Auto-registered by `PipelineHydrated.__init__` (`src/pipeline_hydrated.py:312`) when not pre-supplied. `tools=[]`. **Currently inactive at runtime** — V2 compatibility stub in `_run_perspektiv_sync` skips when `position_clusters` is set; full V2 rewrite pending. The prompt file is still loaded by Agent construction even when the call is skipped

### Conditional

Prompts loaded on specific code paths only.

FileAgent nameTriggerCompositionNotes`agents/writer/FOLLOWUP.mdwriter` (extension)`assignment.follow_up_to` is truthy on the topic being producedRead into `writer_addendum` and passed to `Agent.run(..., instructions_addendum=writer_addendum)`. Appended inside the `<instructions>` block of the User turnLoaded by both `src/pipeline.py:1646` and `src/pipeline_hydrated.py:889`. Both call sites log a WARNING if the file is missing; pipeline does not fail. Architect note: active-by-design, do not archive

### Test-only

Referenced by string literal only in test/spike scripts; not loaded by any pipeline run.

FileReferenceNotes`agents/collector/AGENTS.mdtests/test_tools.py` (6 sites, lines 237/251/265/366/416/439)Used as a fixture `prompt_path` value when constructing test Agent instances. The Agent constructor stores the path but does not read the file unless `.run()` is called, which these tests do not do. The Collector pipeline step itself is fully disabled (see below). Companion file to the disabled `collector/PLAN.md` and `collector/ASSEMBLE.md`

## Disabled prompts

Present in the codebase but explicitly commented out at their load site. Not archived because reactivation is planned.

FileDisabled atReasonReactivation criterion`agents/collector/PLAN.mdscripts/run.py:45` (commented `collector_plan` block)RSS feeds suffice at current scale; Collector deactivated200+ RSS feeds — pre-filter for the Curator`agents/collector/ASSEMBLE.mdscripts/run.py:53` (commented `collector_assemble` block)SameSame

## Archived prompts

Moved to `agents/_archive/` on the date below. Reason for archival: no live load site found.

File (archived path)Original pathArchived onReason`agents/_archive/hydration_aggregator-AGENTS-2026-04-23.mdagents/hydration_aggregator/AGENTS.md`2026-04-23Legacy single-pass design replaced by the two-phase chunked aggregator (S12 commits `1ceac49` + `7437753`). The S12 deprecation banner ("Retained for one release cycle as revert target. Delete after next green production run.") expired after multiple green hydrated runs through S13. The `hydration_aggregator` template Agent in `create_hydrated_agents` now registers `PHASE1.md` as its default `prompt_path`; `_make_phase_agent` continues to swap to PHASE1 / PHASE2 at `.run()` time

The `agents/_archive/` directory contains a `README.md` explaining its purpose.

## Unresolved

Files where status could not be determined automatically and require architect review before archival.

FileIssueRecommended action*None*

## Reference: full canonical wiring

Source of truth for every active configuration above:

- `scripts/run.py:create_agents` (lines 29–130) — production pipeline.
- `scripts/test_hydration_pipeline.py:create_hydrated_agents` (lines 176–256) — hydrated pipeline.
- `src/hydration_aggregator.py` — Phase 1 / Phase 2 wiring inside the chunked aggregator (constants at lines 56–61, Phase 2 Agent construction at line 380, `_make_phase_agent` at line 419).
- `src/pipeline_hydrated.py:296–317` — `perspektiv_sync` auto-registration in `PipelineHydrated.__init__`.
- `src/pipeline.py:1646` and `src/pipeline_hydrated.py:889` — `agents/writer/FOLLOWUP.md` conditional load.
