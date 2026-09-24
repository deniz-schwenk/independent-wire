# TASK-EVAL-GLM53-PROSE-STAGES — method (frozen before judging)

## Arms

| arm | model | reasoning | routing | temperature | max_tokens | structured output |
|---|---|---|---|---|---|---|
| **C** (champion) | `z-ai/glm-5.2` | `xhigh` | production fp8 pin | per-stage prod value | prod value | strict json_schema |
| **H** | `z-ai/glm-5.3` | `high` | `{"order":["z-ai"],"allow_fallbacks":false}` | OMITTED | 120000 | `json_object` + local validation |
| **M** | `z-ai/glm-5.3` | `max` | same z-ai pin | OMITTED | 120000 | `json_object` + local validation |

Arm C is **not re-generated**. It is read off the frozen post-stage bus
snapshot of each production run, with `model_used` / `provider_used` /
`cost_usd` / `tokens` taken from that day's `run_stage_log.jsonl`. Zero cost,
zero risk to production state.

**Deviation from the brief, stated:** the brief says "schemas ... unchanged".
The schema object IS unchanged and is still enforced — but the Z.AI endpoint
serves no strict `json_schema` response_format, so the candidate arms run
`structured_output_mode="json_object"` with the Agent's local schema
validation, exactly as production's own glm-5.3 stages (perspective draft,
bias_judge) do. Sending strict schema to this endpoint is not an option, so
there is no arm in which it could have been held identical.

A **bare `Agent`** is used for H and M, never the production `*WithFallback`
wrapper: a fallback serve would silently substitute another model and
invalidate the arm. Every call's served model and provider is logged.

## Stage isolation

Each candidate consumes the FROZEN production input of its stage on that day —
the bus snapshot written immediately before the stage ran:

| stage | input snapshot | instances |
|---|---|---|
| `editor` | `run_bus.assemble_curator_topics.json` | 3 (run-level, 1/day) |
| `hydration_phase2` | `topic_buses.HydrationPhase1Stage.{n}.json` | 9 |
| `writer` | `topic_buses.mirror_perspective_synced.{n}.json` | 9 |
| `qa_analyze` | `topic_buses.WriterStage.{n}.json` | 9 |

No candidate output feeds another candidate stage. In particular **every QA arm
analyses the CHAMPION's article** — a writer improvement cannot propagate into
the QA score, by design.

## Production state is untouched

The three days' `_state/` directories were copied to
`scratch/eval/glm53-prose/frozen/` and every run reads only from there.
`--reuse` was never invoked. A sha256 manifest of all 351 files under
`output/2026-09-0{6,7,8}` was taken before any call
(`logs/prod_state_manifest.PRE.txt`) and re-taken at the end.

## Judging

- **Ground truth = the exact user message the stage handed its agent**, captured
  free by `capture_inputs.py` (Agent.run stubbed out, no API call), not a
  hand-picked slot dump. Every arm and the judge look at the same material.
- **One judging session per case across all three arms** (within-run judging —
  the convention that removes cross-run judge drift).
- **Blind**: arms appear only as opaque `OUT-xxxxxx` ids from a seeded shuffle
  (`SEED = glm53-prose-2026-09-08`). The keymap is written pre-dispatch and
  lives one directory ABOVE the case dirs, so a judge reading only its own case
  cannot unblind. Judges are instructed never to speculate about model identity.
- **Anchor-free**: each output is scored against the rubric and the INPUT, never
  against another output. Ranking is reported separately from absolute scores.
- **Rubrics are prompt-transcribed and frozen before judging**:
  `rubrics/writer.md` and `rubrics/editor.md` are the existing eval rubrics
  (`docs/evals/{writer,editor}-model-eval/RUBRIC.md`); `rubrics/qa_analyze.md`
  is the frozen v2 QA rubric (`scratch/qa-shadow/judging-v2/RUBRIC.md`);
  `rubrics/hydration_phase2.md` is new, transcribed from
  `agents/hydration_aggregator/PHASE2-*.md` for this task.
- **Honest-Detector**: every case carrying at least one fabrication charge is
  fully double-judged by a second independent judge that never sees the first
  verdict. A charge is COUNTED only when both judges cite an overlapping claim
  against the SAME output; overlap is decided deterministically in
  `confirm_charges.py` (substring or Jaccard >= 0.5 on token sets), never by a
  model.
- Judges are spawned Opus-5 subagents. **No judging cost hits the API budget.**
