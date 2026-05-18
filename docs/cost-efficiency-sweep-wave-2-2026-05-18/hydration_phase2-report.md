# Wave 2 Sweep #4 — `hydration_aggregator_phase2` re-run at `max_tokens=160000`

## Setup

Same substrate, same prompts, same 6-variant V4 Pro grid as Wave-1 Sweep #2 — the only change is `max_tokens` (Wave 1: 64,000; Wave 2: **160,000**). The intent is to test whether the Wave-1 36 % divergence-count shortfall vs Opus baseline was **reasoning-budget-bound** (in which case 160k tokens should close some of the gap) or **model-capacity-bound** (in which case 160k tokens should not meaningfully move the needle).

- **Substrate:** `topic_buses.HydrationPhase1Stage.{0,1,2}.json` (16 / 22 / 11 phase-1 analyses, ~40-50 k input tokens per call).
- **Baseline:** Opus 4.6, t=0.1, r=none, max_tokens=32000. Today's production output: **9 / 10 / 6 divergences (mean 8.3)**, 9 / 10 / 8 coverage gaps, $0.094 / topic.
- **Wave-1 best variant:** `dskpro-t07-rhigh` at 64k max_tokens — **7 / 5 / 4 divergences (mean 5.3)**.
- **Harness:** Wave-1 Option B, reused unchanged.

## Metrics (Wave 2, max_tokens=160000)

| label | cost_total | cost/topic | tokens_total | wall_mean | divs (per topic) | divs_mean | gaps (per topic) | gaps_mean | schema_valid | provider |
|---|---|---|---|---|---|---|---|---|---|---|
| **baseline** | $0.281 | $0.094 | 43,619 | n/a | **9 / 10 / 6** | **8.3** | 9 / 10 / 8 | 9.0 | 100 % | Anthropic |
| dskpro-t05-rnone | $0.0640 | $0.0213 | – | – | 6 / 5 / 4 | **5.0** | 5 / 5 / 4 | 4.7 | 100 % | AtlasCloud |
| dskpro-t05-rmedium | $0.0527 | $0.0176 | – | – | 5 / 5 / 4 | 4.7 | – | – | 100 % | AtlasCloud |
| dskpro-t05-rhigh | $0.0449 | $0.0150 | – | – | 4 / 5 / 3 | 4.0 | – | – | 100 % | AtlasCloud |
| dskpro-t07-rnone | **$0.0340** | $0.0113 | – | – | 5 / 5 / 5 | 5.0 | – | – | 100 % | AtlasCloud |
| dskpro-t07-rmedium | $0.0591 | $0.0197 | – | – | 5 / 5 / 4 | 4.7 | – | – | 100 % | AtlasCloud |
| **dskpro-t07-rhigh** | $0.0480 | $0.0160 | – | – | **5 / 6 / 5** | **5.3** | – | – | 100 % | AtlasCloud |

**Sweep total cost: $0.3028** (well under $15 per-sweep cap). Cumulative wave-2 spend so far: ~$0.41.

## Direct Wave-1 vs Wave-2 comparison (same grid, same substrate, same prompts)

| variant | Wave-1 (64k) divs | Wave-1 mean | Wave-2 (160k) divs | Wave-2 mean | Δ mean | budget-bound? |
|---|---|---|---|---|---|---|
| dskpro-t05-rnone | 5 / 5 / 4 | 4.7 | 6 / 5 / 4 | 5.0 | +0.3 | minor |
| dskpro-t05-rmedium | 5 / 3 / 3 | 3.7 | 5 / 5 / 4 | 4.7 | **+1.0** | yes (topic 1+2) |
| dskpro-t05-rhigh | 4 / 3 / 4 | 3.7 | 4 / 5 / 3 | 4.0 | +0.3 | minor (topic 1) |
| dskpro-t07-rnone | 5 / 6 / 4 | 5.0 | 5 / 5 / 5 | 5.0 | 0.0 | no |
| dskpro-t07-rmedium | 5 / 4 / 5 | 4.7 | 5 / 5 / 4 | 4.7 | 0.0 | no |
| **dskpro-t07-rhigh** | **7 / 5 / 4** | **5.3** | **5 / 6 / 5** | **5.3** | **0.0** | **no** |

## Observation

Raising `max_tokens` from 64,000 to 160,000 produced **zero change** in the best-variant mean (`dskpro-t07-rhigh`: 5.3 → 5.3) and **at most ~1.0** improvement on the weakest two variants. The shape of the per-topic distribution shifted slightly (Wave-1 `t07-rhigh`: 7/5/4; Wave-2 `t07-rhigh`: 5/6/5 — same total of 16 spread differently across the three topics), but none of the variants reaches the Opus baseline's 9/10/6 = mean 8.3 even with the 2.5× token budget. Topic 1 (densest substrate at 22 phase-1 analyses) still tops out at 6 vs baseline 10 — the same Wave-1 ceiling. The two notable budget-sensitive variants are the medium-reasoning ones at t=0.5 (Wave-1 was 3.7 mean; Wave-2 is 4.7 mean — a real lift) but those gains land them at the rnone variants' Wave-1 numbers, not at the Opus baseline. The schema validity, streaming reliability (12/12 reasoning streams returned clean), and cost (~$0.02/topic vs Opus $0.094, ~5× cheaper) all remain healthy. **The Wave-1 conclusion stands: the ~36 % divergence-count shortfall is model-capacity-bound, not reasoning-budget-bound** — more reasoning tokens don't extract more cross-source divergences from this 22-analysis substrate; the ceiling is the model's enumeration depth, which would require an architecture change (two-pass reducer, multi-call aggregation, or a different model) to lift. No production-swap recommendation in this report.
