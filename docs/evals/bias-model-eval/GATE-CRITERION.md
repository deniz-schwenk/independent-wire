# Phase 0 stability gate — formalized criterion (frozen BEFORE any spend)

Binding source: `docs/BIAS-LANGUAGE-MODEL-EVAL-2026-06-28.md` §2 (bar),
§4 (the observed instability signatures), §5 (root cause). This file
transcribes that method into an exact, machine-checkable criterion and
records the Phase-0 article manifest. Nothing here is tuned after seeing
results.

## What the 2026-06-28 doc actually killed on

Not cost, not coverage, not over-flagging. The disqualifier was
**run-to-run instability of the calibration verdict on identical input**:

- DeepSeek: "one fixture swung **4→16 findings**" (total-count instability).
- GLM reasoning-ON: "over-flag 1.73→1.60→1.93, **max per-fixture swing Δ5**".
- GLM one-pass v2: "the count is steady; **which spans confirm is not** …
  3–13 borderline own-voice-verb spans flip true/false/absent per fixture
  across cold runs." → the `finding_valid` verdict set churns.

The incumbent Opus 4.6 "holds a lean (~3.0 valid/topic), **stable**,
calibrated rate." → **the incumbent's own measured cold-to-cold variance is
the bar**, not an abstract threshold (brief: "the incumbent sets the bar").

## Schema reconciliation (brief predates a schema change)

The brief lists "severity distribution" as a variance axis. `severity` was
removed from `BIAS_DETECTOR_SCHEMA` on 2026-06-02 (commit `2a41570`). The
current per-finding fields are `excerpt`, `issue` (6-way category),
`explanation`, `finding_valid`. Mapping:
- "finding count" → total findings emitted, and **valid** findings
  (`finding_valid != false`) tracked separately — the valid count is the
  calibration verdict the doc's root-cause is about.
- "severity distribution" → **`issue`-category distribution** (the 6
  categories) — the nearest structured analog to the removed severity.
- "span overlap between repeats" → Jaccard over the set of flagged
  `excerpt` strings (verbatim), computed on **all** flagged spans and on
  **valid-only** spans.

## Per-article variance metrics (3 cache-cold repeats r1,r2,r3)

For arm `m`, article `a`, with repeats i∈{1,2,3}:
- `Vi` = set of `excerpt` strings with `finding_valid != false` in repeat i
  (the confirmed/valid span set — the calibration verdict).
- `Ai` = set of all `excerpt` strings in repeat i (valid or retracted).

Metrics:
1. **valid-count spread** `C(m,a) = max_i|Vi| − min_i|Vi|`
   (the "4→16", "Δ5" axis, restricted to the confirmed verdict).
2. **valid-span instability** `J(m,a) = 1 − mean_{i<j} Jaccard(Vi,Vj)`,
   range [0,1], 0 = identical confirmed-span set all three runs
   (the "which spans confirm flips" axis — the doc's stated root cause).
   Jaccard(∅,∅)≡1 (two empty verdict sets are perfectly stable).
3. **total-count spread** `Ctot(m,a) = max_i|Ai| − min_i|Ai|` (secondary).
4. **category-distribution instability** `D(m,a)` = mean pairwise L1
   distance of the normalized `issue`-histogram over valid findings /2,
   range [0,1] (the "severity distribution" analog; secondary/context).

Aggregate per arm across the 5 articles: mean and max of each.

## THE GATE (frozen)

Let `inc` = incumbent Opus-4.6 measured on the same 5 articles, same 3×
cold protocol. A candidate `m` **passes** iff, on BOTH binding calibration
axes, it is no worse than the incumbent's own measured variance:

> **PASS ⇔  Jbar(m) ≤ Jbar(inc)  AND  Cmax(m) ≤ Cmax(inc).**

- `Jbar` = mean over the 5 articles of the valid-span instability J — the
  average verdict-set churn (the doc's root cause, aggregated).
- `Cmax` = max over the 5 articles of the valid-count spread C — the
  worst-case calibration swing (the doc killed on worst-case fixtures:
  "one fixture swung 4→16", "max per-fixture swing Δ5").

Both must hold. Ctot and D are **reported** for context but are not gates
(the doc explicitly notes count can look steady while the verdict churns —
J is the load-bearing axis). A candidate that produces a **truncated /
schema-invalid / empty-emission** output on any of the 15 calls fails a
hard precondition (the doc treated truncation and empty-emission as gate
failures) and is reported as such regardless of J/C.

Ties (candidate exactly equal to incumbent) **pass** — "no worse than".

## fp4-confound resolution (DeepSeek)

The 2026-06-28 DeepSeek run was at UNKNOWN quantization (possible fp4).
This eval pins DeepSeek V4 Pro to fp8 via `order:[baidu/fp8, wandb/fp8,
parasail/fp8]`, `allow_fallbacks:false`, `quantizations:["fp8"]`. Every
call records `AgentResult.provider` (served fingerprint). The confound is
**resolved** iff all DeepSeek calls are served by a pinned fp8 provider
(loud failure otherwise) — then any instability observed is intrinsic to
DeepSeek-at-fp8, not an fp4 artifact.

## Operating points (per arm)

Temperature is held at the incumbent's production value (0.1) across all
arms *that accept it*, to isolate the model's intrinsic verdict
determinism rather than a temperature difference. Sonnet-5 is the sole
exception: the 5-family 400s on any non-default temperature, so
temperature is omitted (the one documented deviation, same as the
perspective swap).

| arm | model | temp | reasoning | max_tokens | provider pin |
|---|---|---|---|---|---|
| incumbent | anthropic/claude-opus-4.6 | 0.1 | none | 32000 (prod default) | — (openrouter) |
| glm | z-ai/glm-5.2 | 0.1 | effort:xhigh | 120000 | baidu/ambient/venice fp8 |
| deepseek | deepseek/deepseek-v4-pro | 0.1* | effort:xhigh | 120000 | baidu/wandb/parasail fp8 |
| sonnet5 | anthropic/claude-sonnet-5 | none | enabled,effort:high | 64000 | — (Anthropic-served) |

\* if DeepSeek V4 Pro rejects a non-default temperature under xhigh
reasoning, temperature is dropped and the deviation recorded (probed
before the full run). Prompts (`agents/bias_detector/{SYSTEM,INSTRUCTIONS}.md`)
and `BIAS_DETECTOR_SCHEMA` are identical across all arms.

## Phase-0 article manifest (5, in-window, disjoint from the Phase-1 recent-21)

Window start 2026-05-28 (last prompt commit `0d66d56`; schema last changed
2026-05-19 `6f59fb4`). These 5 are all in-window (05-29→06-27) and are
deliberately disjoint from the 21 most-recent topics used for Phase-1
quality (06-28→07-04), so the gate set and the quality set do not overlap.

| # | date | topic idx | body chars | domain | incumbent stored nf/valid |
|---|---|---|---|---|---|
| 1 | 2026-06-13 | 0 | 3633 | diplomacy/religion (Pope Leo XIV, Spain) | 6 / 4 |
| 2 | 2026-06-17 | 1 | 5200 | legal/politics (Eduardo Bolsonaro sentence) | 7 / 2 |
| 3 | 2026-06-02 | 2 | 6589 | tech/business (Anthropic IPO) | 9 / 6 |
| 4 | 2026-06-22 | 2 | 7339 | health/humanitarian (DRC Ebola >1000) | 7 / 6 |
| 5 | 2026-06-20 | 0 | 7838 | war/diplomacy (US-Iran talks, Hezbollah) | 7 / 3 |

Length gradient 3633→7838; six distinct domains; incumbent finding counts
span the observed range. Read-only: inputs are reconstructed from stored
`topic_buses.BiasLanguageStage.N.json` snapshots; production is never run.
