# WP-OLLAMA-1 — Quantization/quality probe: ollama-cloud vs OpenRouter fp8

**Date:** 2026-07-05 · **Scope:** read-only on production; writes only under
`scratch/ollama-probe/`; no git operations; tree on `main`, untouched.

## TL;DR — verdict per model

| model | stage | verdict | candidate vs baseline (mean quality) | W/T/L | disqualifying artifact class? | gate for WP-OLLAMA-3 |
|---|---|---|---|---|---|---|
| **GLM-5.2** (`glm-5.2:cloud`) | hydration_aggregator_phase2 | **PARITY** | **4.40** vs 4.35 | 2 / 7 / 1 | **none** (0 on both arms) | **PROCEED** (see xhigh caveat) |
| **DeepSeek-V4-Pro** (`deepseek-v4-pro:cloud`) | consolidator | **PARITY** | **5.0** vs 4.9 | 1 / 9 / 0 | **none** (candidate 0; baseline had 2) | **PROCEED** |

Neither ollama arm shows a disqualifying artifact class (numeric corruption,
repetition/degeneration, truncation, or schema violation) and neither regresses
on quality. DeepSeek's operating point was matched **exactly**; GLM's differs on
one unmatchable knob (`xhigh` → ollama's max discrete tier `high`) — see §2.

---

## 1. Score table (10 items × 2 arms × 2 judges), per pair

Blind, order-permuted per item (seed = `sha256(date#topic)`), anchor-free against
each item's own ground truth. `★` = the eval charged the GLM **baseline** a
fabrication on this topic (7 of the 10 GLM items). Quality is integer 1–5.

### Pair 1 — GLM-5.2, phase-2 (`preliminary_divergences` + `coverage_gaps`)

| topic | ★ | baseline [j0,j1] | candidate [j0,j1] | Δ mean |
|---|---|---|---|---|
| 2026-06-28#0 |  | 4, 4 | 4, 4 | +0.0 |
| 2026-06-29#2 |  | 4, 4 | 4, 4 | +0.0 |
| 2026-06-30#1 |  | 4, 4 | 4, 4 | +0.0 |
| 2026-07-01#1 | ★ | 5, 4 | 5, 4 | +0.0 |
| 2026-07-01#2 | ★ | 5, 4 | 5, 5 | +0.5 |
| 2026-07-02#0 | ★ | 4, 4 | 4, 4 | +0.0 |
| 2026-07-02#1 | ★ | 5, 5 | 4, 4 | −1.0 |
| 2026-07-03#1 | ★ | 5, 5 | 5, 5 | +0.0 |
| 2026-07-04#0 | ★ | 4, 4 | 5, 5 | +1.0 |
| 2026-07-04#1 | ★ | 5, 4 | 5, 4 | +0.0 |
| **mean** |  | **4.35** | **4.40** | **+0.05** |

The single loss (2026-07-02#1) is a minor **attribution-granularity** nuance: the
candidate lumped a Guardian source with MEE on one Sudan sub-angle; **both judges
explicitly called it "thin, not fabricated."** Not a quantization artifact.

### Pair 2 — DeepSeek-V4-Pro, consolidator (`voices_missing` + `topics_missing`)

| topic | baseline [j0,j1] | candidate [j0,j1] | Δ mean |
|---|---|---|---|
| 2026-06-30#0 | 5, 5 | 5, 5 | +0.0 |
| 2026-06-30#1 | 5, 5 | 5, 5 | +0.0 |
| 2026-07-01#1 | 4, 4 | 5, 5 | +1.0 |
| 2026-07-01#2 | 5, 5 | 5, 5 | +0.0 |
| 2026-07-02#0 | 5, 5 | 5, 5 | +0.0 |
| 2026-07-02#2 | 5, 5 | 5, 5 | +0.0 |
| 2026-07-03#0 | 5, 5 | 5, 5 | +0.0 |
| 2026-07-03#1 | 5, 5 | 5, 5 | +0.0 |
| 2026-07-04#1 | 5, 5 | 5, 5 | +0.0 |
| 2026-07-04#2 | 5, 5 | 5, 5 | +0.0 |
| **mean** | **4.9** | **5.0** | **+0.10** |

Judge agreement was high on both pairs: **no item had a ≥2-point split between
the two judges** on either arm (max observed split = 1). No third call was needed.

### Artifact-flag matrix (evidence items charged, summed over 10 items × 2 judges)

| artifact class | GLM baseline | GLM candidate | DeepSeek baseline | **DeepSeek candidate** |
|---|---|---|---|---|
| fabricated_contrast | 0 | **0** | 1 (07-01#1) | **0** |
| fabricated_actor | 0 | **0** | 0 | **0** |
| numeric_corruption | 0 | **0** | 0 | **0** |
| repetition_degeneration | 0 | **0** | 2 (07-01#1) | **0** |
| truncation | 0 | **0** | 0 | **0** |
| schema_violation | 0 | **0** | 0 | **0** |

Every artifact charged in the whole probe landed on the **DeepSeek baseline**
(a dedup slip that restated a `voices_missing` entry as a `topics_missing` entry,
plus one over-synthesized cross-border contrast — both on 07-01#1). The ollama
candidate was clean on that exact item and **outscored** the baseline there
(+1.0, the one DeepSeek "win"). The ollama arms introduced **zero** artifacts of
any class.

> Methodology note (transparency): this probe's fresh Opus-4.8 judges charged
> **0 fabrications to the GLM baseline** even on the 7 topics the earlier P2 eval
> flagged — a more conservative rubric ("only charge when confident"). The
> comparison remains valid because **both arms were judged by the same blind
> judges on the same rubric**; parity is a within-probe relative result, not a
> restatement of the P2 eval's absolute fabrication counts.

---

## 2. Operating-point delta table (what could / could not be matched on ollama)

### GLM-5.2 (phase-2)

| knob | baseline (OpenRouter, Baidu fp8) | candidate (ollama `glm-5.2:cloud`) | matched? |
|---|---|---|---|
| model version | `z-ai/glm-5.2` | `glm-5.2:cloud` (arch `glm5.2`) | ✅ same version |
| temperature | 0.1 | 0.1 | ✅ |
| output budget | `max_tokens` 120000 | `max_tokens`/`num_predict` 120000 | ✅ (0 truncations) |
| reasoning | `effort: xhigh` | `think: "high"` | ❌ **unmatchable** — ollama exposes no `xhigh`; `high` is its top discrete tier |
| prompts / input | PHASE2-SYSTEM/INSTRUCTIONS, reconstructed input | **byte-identical** (same `load_input` + `_PHASE2_USER_MESSAGE`) | ✅ |
| routing | fp8 pin `baidu→ambient→venice`, no fallback | local daemon → ollama cloud | n/a |

**Delta consequence:** the candidate ran at a *lighter* reasoning tier than the
baseline (mean 30.0s vs 41.3s wall) yet still reached quality parity. That makes
the parity finding **conservative** — GLM matched at less reasoning, not more.
The flip side: we have **not** exercised ollama GLM at production's exact `xhigh`
point because ollama cannot express it. WP-OLLAMA-2 must decide whether `high` is
an acceptable production setting or whether xhigh-equivalence is a blocker.

### DeepSeek-V4-Pro (consolidator)

| knob | baseline (OpenRouter, Baidu fp8) | candidate (ollama `deepseek-v4-pro:cloud`) | matched? |
|---|---|---|---|
| model version | `deepseek/deepseek-v4-pro` | `deepseek-v4-pro:cloud` (arch `deepseek4`) | ✅ |
| temperature | 0.3 | 0.3 | ✅ |
| output budget | `max_tokens` 32000 | `max_tokens` 32000 | ✅ |
| reasoning | `none` | `think: false` | ✅ **exact** |
| prompts / input | consolidator SYSTEM/INSTRUCTIONS, real stage message | identical (real `ConsolidatorStage` message + reconstructed inputs) | ✅ |
| routing | fp8 pin `baidu→wandb→parasail`, no fallback | local daemon → ollama cloud | n/a |

DeepSeek's operating point is matched on **every controllable knob**; the only
open variable is the (claimed) serving quantization — which is exactly what the
quality probe exists to test.

---

## 3. Claimed-quantization recon vs observed behavior

`ollama show` metadata (captured verbatim in `catalog.json`). **Claimed metadata
is not accepted as verification — the quality data is.**

| model tag | ollama-claimed quant | context | params | our baseline | observed behavior |
|---|---|---|---|---|---|
| `glm-5.2:cloud` | **(blank / unreported)** | 1,000,000 | ~756B | fp8 (Baidu pin) | parity + **0 artifacts** → consistent with a competent quant; **no low-bit degradation signature** (no numeric corruption, no degeneration, no truncation) |
| `deepseek-v4-pro:cloud` | **FP8** | 524,288 | ~1.6T | fp8 (Baidu pin) | parity (candidate cleaner) + 0 artifacts → **claim corroborated** by behavior |
| `glm-5.1:cloud` (ref) | FP8 | 202,752 | ~756B | — | not tested (5.1 ≠ our 5.2 baseline) |

Key recon point: `glm-5.2:cloud` discloses **no** quantization at all, yet behaves
at parity with our fp8 baseline. So the blank field is not evidence of a degraded
serve — the empirical screen (the whole point of this probe) clears it.

---

## 4. Ops appendix

| metric | GLM candidate | DeepSeek candidate |
|---|---|---|
| calls | 10 | 10 |
| schema-valid (strict `json_schema` via ollama `/v1`) | **10 / 10** | **10 / 10** |
| structured `None` / parse failures | 0 | 0 |
| transport errors | 0 | 0 |
| **rate-limit (429) events** | **0** | **0** |
| latency s — min / median / mean / max | 13.1 / 30.6 / 30.0 / 46.3 | 11.0 / 18.1 / 18.6 / 29.1 |
| baseline latency mean (OpenRouter fp8) | 41.3 | reused prod (not re-timed) |
| **paid API cost** | **$0.00** | **$0.00** |

- **Structured output:** ollama's OpenAI-compatible `/v1/chat/completions`
  honored the strict `json_schema` `response_format` for both models — 20/20
  valid, zero Python-validation failures, zero `additionalProperties`/type
  violations (deterministic census in `deterministic_glm.json` /
  `deterministic_deepseek.json`).
- **Rate limits / 06:00-burst relevance (WP-OLLAMA-3):** both pairs were generated
  at concurrency 3 and ran **concurrently** (≈6 simultaneous cloud calls at
  peak) with **no 429s and no throttling**. This is a favorable early signal for
  the morning burst, but note the probe issued only ~20 calls total in a ~2-min
  window — not a sustained daily-run load. WP-OLLAMA-3 should still validate the
  full 06:00 fan-out volume.
- **Latency:** ollama GLM is faster than the OpenRouter baseline (30.0s vs 41.3s
  mean) at the lighter `high` tier; DeepSeek consolidator is ~19s mean. Both are
  within production tolerances.

---

## 5. Assertions & acceptance

- **Zero API judge calls.** All judging ran as **4 spawned Opus-4.8 subagents**
  (2 per pair, each scoring all 10 packets). No judge used the OpenRouter/Anthropic
  API. Blindness verified: no verdict file references `anon_keys/` (grep-clean).
  *(The $19.85 lesson — judges are subagents, not paid calls.)*
- **Total paid API spend: $0.0000** (cap $3.00, untouched). Candidate arms are
  flat-rate ollama; baselines were reused, never regenerated. The in-code
  `account()` guard asserted the running total ≤ cap on every candidate call.
- **10 items per pair actually judged** — no silent shrinkage; every input
  reconstructed cleanly, no swaps needed. 40/40 verdicts present and well-formed.
- **≥3 fabrication-charged topics in the GLM sample:** 7 of 10 (all `★` above).

### Gate recommendation per model (for WP-OLLAMA-2/3)

- **DeepSeek-V4-Pro → PROCEED (clean).** Operating point matched exactly; parity
  with the fp8 baseline, candidate marginally cleaner; claimed fp8 corroborated.
  No caveats beyond sample size.
- **GLM-5.2 → PROCEED, with one integration question to resolve in WP-OLLAMA-2.**
  Quality parity and zero artifacts, but at ollama's `think:"high"` — production
  runs `xhigh`, which ollama cannot express. Parity at the lighter tier is
  encouraging (and conservative), but WP-OLLAMA-2 owns the decision of whether
  `high` is acceptable for the phase-2 reducer or whether xhigh-equivalence is
  required before cutover.

**Both models clear the quantization screen.** No disqualifying artifact class
for either. This is a probe result on a meaningful (not exhaustive) 10-item/pair
sample with 2 blind judges — not a cutover decision.

---

## 6. Raw artifacts (for Architect re-verification)

Under `scratch/ollama-probe/`:
- `raw/{glm,deepseek}-cand__<date>_<n>.json` — candidate outputs + per-call metrics
  (served_model, duration, schema check, degeneration screen).
- `packets/{pair}_<date>_<n>.json` — the exact blind bundles the judges saw
  (ground truth + labels A/B).
- `anon_keys/{pair}_<date>_<n>.json` — the label→arm keys (**post-hoc**; judges
  never read these).
- `verdicts/{pair}_<date>_<n>__j{0,1}.json` — the 40 raw judge outputs.
- `deterministic_{glm,deepseek}.json` — schema + degeneration census (both arms).
- `aggregate.json` — machine-readable roll-up (this report's numbers).
- `catalog.json` — verbatim `ollama show` metadata.
- GLM baselines reused read-only from `scratch/p2-eval/raw/glm__*.json`
  (OpenRouter Baidu fp8); DeepSeek baselines read-only from
  `output/*/_state/*/topic_buses.ConsolidatorStage.*.json`.
