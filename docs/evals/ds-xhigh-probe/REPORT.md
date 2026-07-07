# WP-DS-XHIGH — DeepSeek-V4-Pro stages at reasoning `xhigh` vs production `none`

**Date:** 2026-07-05 · Read-only on production; writes only under
`scratch/ds-xhigh-probe/`; no git ops; outside the 06:00 window.
**Decision rule (inverse of the ollama probes):** `xhigh` raises cost + latency,
so the bar is **CLEAR IMPROVEMENT**, not parity. Parity/noise → KEEP `none`.

## TL;DR — per-stage verdict

| Stage (V4-Pro) | Quality vs baseline | Cost | Latency | Verdict |
|---|---|---|---|---|
| **consolidator** | parity/noise — 3W/3T/2L, +0.06 combined | ~1.7× | ~50s vs sec | **KEEP `none`** |
| **hydration_phase1** | slightly WORSE + 2× invented-actor fabrications (8 vs 4) | 3.7× | 8.8× (28→250s) | **KEEP `none`** |
| **bias_candidate_extractor** | clearly BETTER — recall +0.62, precision +0.31, 6W/0T/2L | 8.0× | 31× (8→250s) | **KEEP `none` now; only ADOPT-candidate → dedicated follow-up** |

Two of three stages fail the bar outright. The third (bias) is the one place
reasoning helps — a real recall/precision gain — but the gain is on the exact axis
its 3-pass design already hardens, it costs 8× / 31× and it induced degenerate
(empty/truncated) extractor passes on a no-fallback structured stage. Net: no
stage is a clean ADOPT today.

---

## 1. Step 0 — inventory + `xhigh` engagement (from `scripts/run.py`, not memory)

**All DeepSeek-served stages** (grep of `run.py` + `create_agents_hydrated`):

| Stage | Model | reasoning | temp | max_tok | provider pin | probed? |
|---|---|---|---|---|---|---|
| `bias_candidate_extractor` (in `bias_language` composite, ×3) | deepseek-v4-pro | **none** | 0.8 | default | `DEEPSEEK_V4_PRO_FP8_ROUTING` | **yes** |
| `consolidator` | deepseek-v4-pro | **none** | 0.3 | 32000 | `DEEPSEEK_V4_PRO_FP8_ROUTING` | **yes** |
| `hydration_aggregator_phase1` (hydrated) | deepseek-v4-pro | **none** | 0.3 | 32000 | `DEEPSEEK_V4_PRO_FP8_ROUTING` | **yes** |
| `curator_topic_discovery` | deepseek-v4-**flash** | medium | 0.5 | 160000 | `..._FLASH_FP8_ROUTING` | follow-up |
| `researcher_assemble` | deepseek-v4-**flash** | none | 0.5 | 160000 | `..._FLASH_FP8_ROUTING` | follow-up |
| `resolve_actor_aliases` | deepseek-v4-**flash** | none | 0.5 | 160000 | `..._FLASH_FP8_ROUTING` | follow-up |

`DEEPSEEK_V4_PRO_FP8_ROUTING = {"order":["baidu/fp8","wandb/fp8","parasail/fp8"],
"allow_fallbacks":False,"quantizations":["fp8"]}`. Inventory > 3 stages → per the
task, the **three V4-Pro stages are probed fully (n=8 each)**; the three V4-Flash
stages are reported here for a **follow-up wave** (a separate model tier;
`phase2` is NOT DeepSeek — it is GLM-5.2 as of TASK-HYDRATION-P2, out of scope).

### `xhigh` engagement — PROVEN, and the "structured=None pathology" is a budget artifact
Single none-vs-`xhigh` call per stage on a real input, retries forced to 0, served
by **Baidu fp8** (`deepseek/deepseek-v4-pro-20260423`) on every call:

| stage | arm | reasoning_tokens | completion_tokens | structured_ok | wall |
|---|---|---|---|---|---|
| consolidator | none | 0 | 407 | ✓ | ~2s |
| consolidator | **xhigh** | **5 698** | 6 095 | **✓** | 82s |
| phase1 (1 chunk) | none | 0 | 2 445 | ✓ | 29s |
| phase1 (1 chunk) | **xhigh** | **14 405** | 16 456 | **✓** | 252s |
| bias extractor | none | 0 | 592 | ✓ | 8s |
| bias extractor | **xhigh** | **15 881** | 16 300 | **✓** | 240s |

- **Engagement is real**: 0 → 5.7K–15.9K reasoning tokens. `xhigh` is not silently
  ignored on this endpoint (the ollama `/v1`-leniency failure mode does not apply).
- **`run.py:492` documents an "xhigh structured=None pathology" for this model.**
  It **does NOT reproduce at a raised budget.** All three `xhigh` calls returned
  valid strict-schema JSON. Reasoning consumes ~15–16K completion tokens; at
  production's `max_tokens=32000` that starves the answer → truncation → `None`.
  At **`max_tokens=64000`** (candidate budget, measured-safe; peak completion 16.5K
  ≪ 64000, zero truncation across all 24 phase1 chunk calls) the answer fits and
  structured output survives. **The pathology is budget starvation, not a hard
  incompatibility** — a reusable engineering finding independent of the adopt call.

**Candidate arm = production agent, verbatim**, with only `reasoning` → `xhigh` and
`max_tokens` → 64000 changed (same model, same fp8 pin, same temperature, same
prompts, same strict schema).

**Baseline provenance (honesty):** these stages do **not** emit `model_used`
(the loud-logging branch is parked/unlanded), so baseline provenance is
**config-derived** — no swap has touched any V4-Pro stage in the 07-03…07-05
window (git log + `run.py` confirm deepseek-v4-pro / `none` throughout). Supporting
evidence: every Step-0 + generation call was **served by Baidu fp8** with the
`deepseek/deepseek-v4-pro-20260423` signature, matching the pinned baseline route.
Consolidator + phase1 baselines are **reused unmodified** from the production
`_state` snapshots (`ConsolidatorStage.*` / `HydrationPhase1Stage.*`). **Bias has no
reusable snapshot baseline** (the composite persists only the *judged* findings, not
the raw candidate union) → **both bias arms were regenerated** (baseline = 3× `none`
passes, the production operating point). Flagged deviation, bias only.

---

## 2. Per-stage results (blind, anchor-free, 2 Opus-4.8 subagent judges/item, n=8)

### 2a. consolidator — **KEEP `none`** (parity/noise)
Ground truth = the stage's own two input arrays (`perspective_missing_positions` +
`merged_coverage_gaps`).

| axis | baseline | candidate |
|---|---|---|
| faithfulness | 5.000 | 5.000 |
| classification | 5.000 | 4.938 |
| dedup_coverage | 4.625 | 4.875 |
| **combined** | **4.875** | **4.938** (+0.06) |

Item **W/T/L 3/3/2**. Error flags: `redundant` 2→0 (candidate cleaner), all others
0/0. `xhigh` dedupes a touch more aggressively (win on 07-04#0: merged 10 voices→8,
killing baseline's 2 redundant entries) but occasionally reshuffles the
voice/topic boundary (loss on 07-03#2). **No clear improvement** — a +0.06 combined
delta inside noise for ~50s median wall (vs seconds) is not worth adopting.

### 2b. hydration_phase1 — **KEEP `none`** (slightly worse + more fabrication)
Ground truth = the fetched article `extracted_text` per topic.

| axis | baseline | candidate |
|---|---|---|
| faithfulness | 4.312 | 4.000 |
| evidence_typing | 4.188 | 4.000 |
| completeness | 4.125 | 4.312 |
| **combined** | **4.208** | **4.104** (−0.10) |

Item W/T/L 3/3/2, but the losses are severe (combined 5.0→4.0, 3.83→3.17). Artifact
matrix (counts over 8 items × 2 judges):

| flag | baseline | candidate |
|---|---|---|
| invented_actor | 4 | **8** |
| fabricated_quote | 7 | 5 |
| evidence_mislabel | 4 | 4 |
| dropped_actor | 9 | 7 |

`xhigh` trades fewer *dropped* actors for **nearly 2× more *invented* actors**. On
the worst-loss item both judges independently scored candidate faithfulness = 2
(invented actors + fabricated quotes) vs baseline 4. In a transparency pipeline
**fabrication is worse than omission** — this is a regression, at 8.8× latency
(28→250s/topic) and 3.7× cost.

### 2c. bias_candidate_extractor — clearly BETTER, but **KEEP `none`** today
Ground truth = the article body. Judges rate the candidate SET (recall-first stage;
a downstream dual Opus judge provides precision).

| axis | baseline | candidate |
|---|---|---|
| recall | 3.938 | **4.562** (+0.62) |
| precision | 3.375 | **3.688** (+0.31) |
| span_quality | 3.938 | 3.938 |

Item **W/T/L 6/0/2** (candidate wins 6 of 8). Error flags: `missed_obvious` 2→0,
`neutral_flagged` 11→8 (both better), `non_verbatim` 0/0. **This is the one stage
where `xhigh` delivers a clear quality gain** — reasoning surfaces more genuinely
loaded passages with fewer neutral false-flags.

**Why it is still KEEP, not ADOPT:**
1. **Cost 8.0×, latency 31×** — baseline $0.0086 / ~8s per article (3 `none` passes,
   concurrent); candidate $0.0689 / ~250s per article (3 `xhigh` passes). Per the
   decision rule the gain must clear this bar, and a recall bump on a stage that is
   *already* 3-pass-hardened for recall (miss prob ~1%) + dual-judged for precision
   is a shallow return for a 31× wall-clock hit.
2. **Reliability dropouts on a no-fallback structured stage** — 2/8 articles had a
   degenerate `xhigh` pass (`[25,25,3]` truncated; `[25,0,25]` empty); 2/24 passes.
   Baseline `none` passes were stable (~20–25 every pass). One `xhigh` pass also
   needed JSON-repair (truncation). Reasoning destabilises the extractor.
3. **The gain may not be reasoning-specific** — it may be "more varied sampling."
   The `xhigh` 3-pass *union* is wider than baseline's (e.g. 30 vs 19) because the
   passes diverge more, not necessarily because any pass reasons better. A cheap
   control — `none` at 4–5 passes — must be run before paying reasoning cost.

**→ Bias is the sole ADOPT-candidate, gated on a dedicated follow-up:** (a) a
`none`-N-pass control to isolate reasoning from sampling, and (b) hardening the
empty/truncated-pass failure mode. Until then, KEEP `none`.

---

## 3. Latency + cost projection for the 06:00 chain (per stage, if adopted)

| stage | baseline wall | xhigh wall (n=8 range) | cost/item base→xhigh | daily add (3 topics) |
|---|---|---|---|---|
| consolidator | ~2s | 23–95s (med ~50) | $0.005→$0.008 | +~1–2 min |
| hydration_phase1 | ~28s | 159–490s (med ~300) | $0.008→$0.029/chunk | +~5–8 min |
| bias extractor | ~8s | 192–383s (med ~250) | $0.0086→$0.069/article | +~4–12 min |

`xhigh` reasoning genuinely engaged throughout (per-call reasoning tokens 5K–30K).
Even the cheapest stage (consolidator) pays ~25× wall-clock for a noise-level delta.

---

## 4. Assertions & acceptance
- **Inventory quoted from `run.py`** (§1); **`xhigh` engagement proven per stage**
  via reasoning-token counts (§1 table) — and the structured=None pathology
  empirically characterised as budget starvation, refuted at 64000.
- **n = 8 per probed stage, no silent shrinkage.** 8 consolidator / 8 phase1 / 8
  bias items, 2 judges each = **48 blind verdicts**. Phase1 candidate analyses
  matched article counts on all 8 topics (no dropped articles at 64000). One
  phase1 topic of the initial 9-instance pool was dropped to hit n=8 (07-05#1, the
  26-article/3-chunk outlier); all other selections carried through.
- **Zero API judge calls** — all judging by spawned Opus-4.8 subagents; blindness
  grep-verified (no verdict references `anon_keys/`, `baseline`, `candidate`, or
  `xhigh`). Per [[eval-roles-subagents-not-api]].
- **Total paid API spend $1.349** (in-code `$5` cap, every paid call through the
  `SPEND` guard; never tripped): step0 $0.079 + consolidator $0.062 + phase1 $0.557
  + bias $0.620 + $0.031 wasted on one killed/re-run phase1 topic (documented). All
  candidate arms; baselines reused (consolidator/phase1) or regenerated at the
  production `none` op-point (bias).
- **Explicit ADOPT/KEEP per stage** (§TL;DR): consolidator KEEP, phase1 KEEP, bias
  KEEP-now / follow-up-candidate.

### Artifacts (for re-verification) under `scratch/ds-xhigh-probe/`
`harness.py` (candidate generator + step0 + instrumented client) · `step0/step0.json`
· `candidate/{consolidator,phase1,bias}.json` (inputs + baseline + candidate + raw
per-call reasoning/cost telemetry) · `packets/*.json` (blind A/B bundles) ·
`anon_keys/*.json` (post-hoc keys) · `verdicts/*__j{0,1}.json` (48) ·
`aggregate_{consolidator,phase1,bias}.json` · `JUDGE-{CONSOLIDATOR,PHASE1,BIAS}.md`.

**A probe, NOT a cutover.** No production file touched; tree on `main`, no git ops.
