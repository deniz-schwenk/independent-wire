# CONFIRM-QA2 — method, identity and premise evidence

Second confirmation for `qa_analyze` only. Batch scope, arms, criterion and
cost cap are TASK-EVAL-GLM53-FM-CONFIRM-QA2.md. Everything below maps to a
file under `scratch/eval/glm53-prose/confirm-qa2/`.

## 1. Premise check — 9/9, nothing excluded

Read from each day's FROZEN copy of its production stage log
(`frozen/{day}/run_stage_log.jsonl`), not from `output/`. Full rows:
`reports/premise-check.jsonl`.

| day | topic | status | model_used | provider_used | qa_fallback_used |
|---|--:|---|---|---|---|
| 2026-09-13 | 0 | success | `z-ai/glm-5.2` | Baidu | false |
| 2026-09-13 | 1 | success | `z-ai/glm-5.2` | Baidu | false |
| 2026-09-13 | 2 | success | `z-ai/glm-5.2` | Baidu | false |
| 2026-09-14 | 0 | success | `z-ai/glm-5.2` | Venice | false |
| 2026-09-14 | 1 | success | `z-ai/glm-5.2` | Baidu | false |
| 2026-09-14 | 2 | success | `z-ai/glm-5.2` | Baidu | false |
| 2026-09-15 | 0 | success | `z-ai/glm-5.2` | Baidu | false |
| 2026-09-15 | 1 | success | `z-ai/glm-5.2` | Baidu | false |
| 2026-09-15 | 2 | success | `z-ai/glm-5.2` | Baidu | false |

All nine ran the champion as primary with no fallback, so **n = 9** and nothing
is reconstructed. The premise is re-asserted a second time per instance inside
`prepare.py::extract_champion`, which REFUSES a row whose `model_used` is not
`z-ai/glm-5.2` or whose fallback marker is true — a day that drifted could not
silently enter the batch even if this table were wrong.

Two things worth noting, neither of which affects the premise:
- 2026-09-14 t0 was served by **Venice**, the other eight by **Baidu**. Both are
  inside the production fp8 pin; the arm is the model, not the host.
- Champion cost varies 13x across the nine (`$0.032` … `$0.466`). The three
  09-15 topics and 09-14 t0 are the expensive ones. This is a property of the
  inputs, and it is why the cost comparison in the report is stated per case as
  well as in aggregate.

## 2. Arms

| arm | model | route | level | temperature | top_p | max_tokens | structured output |
|---|---|---|---|---|---|---|---|
| C | `z-ai/glm-5.2` | production, **not re-generated** | xhigh (prod) | prod | prod | prod | prod |
| F_M | `z-ai/glm-5.3-flash` | OpenRouter, pin `{"order":["z-ai"],"allow_fallbacks":false}` | `max` | 1.0 | 0.95 | 120000 | `json_object` + local validation |

Arm C is read straight off the frozen post-stage snapshot with model, provider,
cost and tokens taken from that day's stage log. It costs nothing and cannot
drift from what actually shipped.

Arm F_M reuses the addendum batch's stage table and bus loaders by import
(`harness.py` imports the batch-1 harness and rebinds only `FROZEN`), so the
plumbing cannot diverge between batches. `temperature 1.0 / top_p 0.95` is the
vendor's published pair for glm-5.3-flash and the pair the production
`perspective_verify` leg uses; the level is `max`, verified accepted on every
call (`logs/calls.jsonl`).

**Stage isolation**: each arm consumes the frozen input snapshot written
immediately before `QaAnalyzeStage` ran that day. No candidate output feeds
another candidate stage. Consequence, unchanged from every prior batch: every
QA arm analyses the CHAMPION writer's article, so this measures QA, not writing.

Inputs are the EXACT user messages, captured for free by monkeypatching
`Agent.run` to record `_build_user_message(...)` and then raise a sentinel
(`prepare.py`). The judge therefore sees the true ground truth the stage saw,
not a hand-assembled approximation, at zero API cost.

## 3. Judging

- Spawned Opus-5 subagents only. No judging went through the API.
- Blind: opaque `OUT-xxxxxx` ids from a seeded shuffle
  (`SEED = "glm53-fm-confirm-qa2-2026-09-16"`), keymap written PRE-dispatch to
  `judging/keymap.json`, one level ABOVE the case directories so no judge can
  reach it from its own working directory.
- Anchor-free: each output scored against `RUBRIC.md` and `INPUT.txt` only,
  never against the other output.
- **All 9 cases double-judged** (18 verdicts, 2 per case). Batch 1 double-judged
  only the charged cases; doing all of them here costs nothing (judges are
  subagents) and buys both the Honest-Detector requirement and a per-output
  mean over two judges, which is the noisier half of an n=9 comparison.
- Rubric is `../rubrics/qa_analyze.md`, unchanged and read-only from the prior
  batches — the same standard all three qa batches were scored against.

## 4. Statistics

Paired within session: every delta is F_M minus C on the SAME case, scored in
the same judging session. Absolute scores are never differenced across batches;
cross-run judge drift on this rubric family was measured at ~+0.667 (T5a), the
same order as the effect being measured.

Criterion, fixed before any data was seen and evaluated mechanically in
`aggregate.py` (`confirmed = m > 0 and ci_lower > 0`):

> CONFIRMED iff the paired delta is positive AND its CI95 excludes zero, on
> this fresh data alone.

A pooled reading across all three qa batches is reported SEPARATELY
(`pooled.py`, `reports/pooled.json`) and is labelled secondary everywhere it
appears. It pools per-case DELTAS only, never absolute scores, and it is not
the verdict.

## 5. Honest-Detector

A fabrication charge counts only when two independent judges cite an
overlapping claim against the SAME output. Overlap is decided deterministically
in `confirm_charges.py` — never by a model — by lowercasing, stripping
punctuation and comparing token sets: substring containment, or Jaccard >= 0.5.
The tokenizer is Unicode-aware; charges in these batches routinely quote
Arabic, Hebrew and CJK text.

## 6. Deterministic invariants

R4 (corrections correspondence) and R5 (corrected-article discipline) are
checked in Python (`invariants.py`, `reports/invariants.json`) rather than
delegated to a judge. A judge's verdict on these is a second opinion on
arithmetic, and they are the criteria a swap decision most needs certainty
about: an arm that breaks article-present-iff-needed is a downstream
correctness bug, not a quality preference.

## 7. Production state

`output/` is read-only for this task. `reports/PRE-manifest.txt` and
`reports/POST-manifest.txt` are sha256 manifests of every file under
`output/2026-09-13`, `2026-09-14`, `2026-09-15`, taken before and after. The
frozen working copy under `frozen/` holds only what this batch reads: the QA
input snapshot (`topic_buses.WriterStage.{0,1,2}.json`), the champion output
snapshot (`topic_buses.QaAnalyzeStage.{0,1,2}.json`), `run_bus.select_topics.json`
and `run_stage_log.jsonl`, per day.
