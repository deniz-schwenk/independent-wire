# Bias-Language Model Eval — DeepSeek V4 Pro & GLM-5.2 vs Opus 4.6

Consolidates five improvement loops (TASK-BIAS-DEEPSEEK-LOOP, TASK-BIAS-GLM52-LOOP,
TASK-BIAS-GLM52-1TURN-REASONING, TASK-BIAS-GLM52-ONEPASS-V2, TASK-BIAS-GLM52-QA-STAGE2).
Isolated bench harness (`~/iw-stage-bench/`); production paths
(`agents/bias_detector/*`, `config.json`) untouched throughout — verified clean
working tree, `agents/bias_detector/*` mtime 2026-06-02. No commit made by any
loop. Every sealed holdout left unopened (no candidate cleared the mandatory train
stability gate).

## 1. Verdict

**Keep Opus 4.6 on `bias_language`.** Both open-weight candidates were tested
exhaustively — across cost tiers, reasoning off/on, 1/2/3 turns, a ground-up
one-pass redesign, and a dedicated verify turn — and rejected. The shared
disqualifier is **not** cost and (after the redesign) no longer over-flagging: it
is **run-to-run instability of the calibration verdict on the heart-stage**, which
no lever brings to Opus's lean, stable rate. The GLM one-pass redesign (v2) was a
real advance — first open-weight config to break the over-flagging wall and touch
the bar — but it still swings cold-to-cold, and a verify turn meant to stabilize it
proved non-deterministic on identical input. This is a deliberate, documented
acceptance of one commercial dependency on this stage, justified by the Vision
Paper's own standard: an unstable detector destroys the credibility it exists to
protect.

## 2. Setup (shared)

| | Reference | Candidate A | Candidate B |
|---|---|---|---|
| **Model** | `anthropic/claude-opus-4.6` | `deepseek/deepseek-v4-pro` | `z-ai/glm-5.2` |
| **Provider** | OpenRouter | DeepSeek direct | OpenRouter → pinned **WandB fp8** |
| **Reasoning** | none | none | none **and** `effort:high/max/xhigh` |
| **Temp** | 0.1 | 0.0 | 0.0 (sweep 0.3/0.7) |
| **Anchor** | 20.1 s · $0.046/topic · 3.0 valid findings/topic · 38% valid-rate | — | — |

Fixtures: 10 train / 5 holdout, sealed (`fixtures/MANIFEST.json`). Judge: blind
CC subagents, frozen rubric (`judge/rubric.md` + `judge_prompt.txt`), pairwise
both A/B orders, disagreement = tie. Opus reference frozen once, reused across
loops. Bar: 1-turn = at-least-equivalent (cheaper+faster justifies parity);
≥2-turn = must beat (relaxed to at-least-equivalent for the verify turn, since
2 GLM calls ≈ $0.024 < Opus and its job is to stabilize, not raise quality);
**calibration ≥ tie and 3× cache-cold stability non-negotiable at every stage**;
deterministic gate (verbatim/schema, 0 empty-emission, 0 out-of-text actor) +
time gate (no >100 s tail) before any holdout.

## 3. Candidate A — DeepSeek V4 Pro

Architecture: `find_audit_note` 3-turn, reasoning off. Deterministic gate met
throughout (0 step1/schema/empty/out-of-text actor).

| measure | result vs Opus |
|---|---|
| Holdout overall | 2W / 1T / 2L = **net 0** (bar needs Wins > Losses) ✗ |
| Holdout calibration | 1W / 2T / 2L = **net −1**, loses outright ✗ |
| Over-flagging | ~1.9–2.4× (baseline 2.6–3.0×); structural floor under prompting |
| Stability (3× cache-cold) | unstable — one fixture swung 4→16 findings |
| Cost / latency | $0.011/topic (¼ Opus), 40–52 s — economics fine |

**Verdict: did not beat.** Coverage never lost (it finds the bias), but the
over-flagging floor is structural and run-to-run unstable; prompting cannot hold
it to Opus's lean rate, and calibration is the wall. Out across reasoning-off,
1/2/3-turn. Primary: `shadow/deepseek-loop/judge/iter-630/holdout/reconciled.json`,
`shadow/deepseek-loop/LOOP-REPORT.md`.

## 4. Candidate B — GLM-5.2 @ WandB fp8

### 4a. Reasoning OFF — staircase
- **1-turn**: calibration coin-flips across draws (iter-700 tie → 701 −2 → 710 −1),
  over-flag swings 5→13. Quality unstable.
- **2-turn**: the AUDIT call rubber-stamps the generous FIND draft → over-flags
  *more* (2.0–2.5×). Not judged.
- **3-turn**: best quality (iter-810 net +4 / calib tie) but **time gate FAIL** —
  190.2 s tail, mean 35 s > Opus.

### 4b. Reasoning ON (sanctioned exception to reasoning=none)
- **effort:high, full 10** (iter-750): economics excellent (11.9 s, $0.012/topic,
  reasoning 686 tok/topic bounded) but quality **net −1** (3W/3T/4L), calibration
  **net −1** (1W/7T/2L), over-flag 1.73× — identical to reasoning-off.
- **Stability (3× cache-cold 750/752/753): FAIL** — over-flag 1.73→1.60→1.93,
  max per-fixture swing Δ5. **Hypothesis refuted: reasoning does not smooth it.**
- **effort:max** (iter-751): 4 gates fail — 71.5 s / 237 s tail, $0.046 = Opus,
  1 truncation + 1 empty-emission. **xhigh** worse (184 s, $0.142, truncates).
- **Tightening** (iter-760): overshoots to 0.57× under-flag. No stable operating
  point between over- and under-flagging.

### 4c. One-pass redesign (PE-authored, the breakthrough)
A ground-up single-call prompt that flags generously, then forces examine-then-judge
via field order (`explanation` before `finding_valid`), carrying rejected candidates
as `finding_valid:false` rather than dropping them.
- **v1** (iter-770): broke the over-flag wall — 0.83× Opus, but overshot to
  **18% valid-rate** (under-confirm); the false-carry lever over-fired.
- **v2** (iter-780): sharpened carrier test (attribution of the surrounding fact
  no longer clears an own-voice framing word) + de-templated example. **Best
  open-weight config to date**: valid-rate **32%**, over-flag 1.27× (no relapse),
  leak-clean, 0 zero-confirmed, and — a first — **passed the train bar** on run 1
  (overall net 0 / 8 win-or-tie, calibration tie). Removed the attributed-quote
  precision losses that sank every prior config.
- **Stability (3× cache-cold 780/781/782): FAIL.** Aggregate looks stable
  (over-flag 1.27/1.33/1.33) but the calibration verdict swings tie → loss → loss;
  3–13 borderline own-voice-verb spans flip true/false/absent per fixture across
  cold runs. The count is steady; *which* spans confirm is not. Run 1 was a
  favorable draw.

### 4d. Stage-2 verify turn (the targeted fix for 4c's instability)
A second reasoning-off call verifying each finding's `explanation` against
`article_body` (verification, not re-rating), run only over the frozen iter-780
Stage 1. Two independent failures:
- **Does not correct**: 0 verdict flips while rewriting 103/119 explanations — it
  rubber-stamps, re-narrating to justify the verdict already carried.
- **Not self-deterministic**: over *identical fixed input* it returns 119/119/105
  findings (run 3 wiped a fixture → empty-emission), calibration verdict swings
  +1/−1/−1. All swing is Stage 2's own nondeterminism. The verify-turn approach is
  exhausted — and this was the easier test; combined Stage1+Stage2 can only be worse.

**Verdict: no swap across every tested mode.** Primary:
`shadow/glm-loop/judge/iter-{700,701,710,810,750,780}/train/reconciled.json`,
`shadow/glm-loop/{LOOP-REPORT,REASONING-LOOP-REPORT,ONEPASS-V2-REPORT,QA-STAGE2-REPORT}.md`,
`shadow/GLM52-EVAL.md`.

## 5. Root cause (shared)

Both open-weight models fail the same way: **run-to-run instability of the
calibration verdict** on the heart-stage. The redesign isolated it cleanly. The
problem is no longer over-flagging (GLM v2 holds a lean 32% rate) — it is that the
model cannot judge the borderline own-voice-framing words deterministically. The
same article, judged cold three times, confirms a different subset each time, and
that subset carries the verdict. This survives every lever: prompting, stage-split,
reasoning, a clean one-pass design, and a pure verification turn that is itself
non-deterministic on fixed input. It is a property of the model on this task, not a
prompt defect. Opus holds a lean (~3.0 valid/topic), stable, calibrated rate at
~20 s and $0.046/topic. The instability — not cost, not coverage, not over-flagging
— is the disqualifier.

## 6. Decision & open items

**Production unchanged.** `bias_language` stays `anthropic/claude-opus-4.6`
(temp 0.1, reasoning none). `config.json` and `agents/bias_detector/*` untouched.

For a future model that picks up the thread: GLM-5.2 one-pass **v2**
(`shadow/glm-loop/candidate/prompts/ONEPASS-*`) is the best open-weight standing —
lean rate, broke the over-flag wall, touched the bar — failing only on cold-to-cold
calibration determinism. That prompt is the right starting point; the test that
matters is the 3× cache-cold stability gate, not median quality.

Open backlog (not scheduled here):
1. **Architectural prune-turn** — a *deterministic* Python post-filter capping
   over-flagging (NOT an LLM turn), per deterministic-before-LLM. Now lower value:
   v2 already solved over-flagging; the wall is verdict variance, which a prune
   filter does not address. → `BACKLOG`, deprioritized.
2. **passive_obscuring carry-over** — the bench prompts name an actor only when
   `article_body` states it (model-independent improvement). The production Opus
   prompt may carry the same weakness; carry-over check + port pending. Independent
   of this model decision — the one concrete production improvement from the work.
3. **Bench guards** — the excerpt heal-snap + single_call drop guard
   (`candidate/code/runner.py`) — assess whether either belongs in the production runner.

## 7. Cost ledger
DeepSeek loop $2.06 · GLM staircase $2.33 · GLM reasoning loop $3.55 · ONEPASS v2 +
QA Stage-2 $4.33 (shared ledger, cumulative). Judge free (blind CC subagents). All
under the $10 per-loop cap. Cost was never the constraint.
