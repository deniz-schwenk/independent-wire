# Dual-judge — Gate v3 (full-flip + presence stability)

**Verdict: PASS on the HARD gate — zero full flips.** The confirmed↔cleared
pathology that failed Gate v2 is eliminated. This is the first passing gate
across the four rounds (split 0.406 → dedup 0.411 → tier-v2 *2 flips* →
dual-judge **0 flips**).

## What changed (TASK-BIAS-DUAL-JUDGE)

The judge now runs **twice** per article (identical input, same config: Opus 4.6,
temp 0.1, three-tier schema), and **Python** assigns the tier from the two votes:

- both `confirmed` → **confirmed**
- both `cleared` → **cleared**
- any disagreement, or any `borderline` vote → **borderline**

Deterministic-before-LLM in its purest form — the LLM only votes, the tier is
code. A single sample can't perceive that it sits on a boundary; marginality is
only observable *across* samples, so the second vote is what lands a straddler in
the (ungated) gray zone instead of flipping poles cold-to-cold.

## The 5-article × 3-cache-cold grid

| article | confirmed (r0,r1,r2) | Jconf | borderline | flips | presence |
|---|---|---|---|---|---|
| 06-13#0 Pope | 0,0,0 | 0.00 | 3,4,3 | 0 | 0/0 |
| 06-17#1 Bolsonaro | 0,0,0 | 0.00 | 4,2,2 | 0 | 0/0 |
| 06-02#2 Anthropic | 0,0,0 | 0.00 | 2,4,3 | 0 | 0/0 |
| 06-22#2 Ebola | 1,0,3 | 0.89 | 2,2,1 | 0 | 0/3 |
| 06-20#0 US-Iran | 0,0,0 | 0.00 | 2,2,0 | 0 | 0/0 |

- **HARD — full flips (confirmed↔cleared, aggregate) = 0** → **PASS** (target 0)
- **PRIMARY report — presence stability = 0/3** confirmed families are confirmed|borderline in all reps
- confirmed-set Jbar 0.178 (informational; sparse — a 1-vs-0 rep transition scores 0.67 by construction)
- mean confirmed **0.27**/article · mean borderline **2.40**/article
- **mean $ 0.1294/run** (target ≤ $0.15) → within budget

## Reading it (for the Architect)

1. **The destructive instability is gone.** No family is confirmed in one cold
   run and cleared in another — the exact failure of Gate v2. Requiring *both*
   votes to agree to leave the gray zone means a marginal candidate (which is
   marginal precisely because the two samples disagree) is now deterministically
   routed to `borderline`. 06-20's `'a deliberate test of Washington's
   credibility'` — the v2 offender — no longer reaches `confirmed` at all; it
   sits in borderline/cleared consistently. The judge disagreed on 1–2
   candidates per article, and every one of those was absorbed into borderline
   rather than flipping the confirmed set.
2. **Presence stability is 0/3 — but that is not a flip.** The only confirmed
   families (all on 06-22, counts [1,0,3]) are surfaced by the stochastic
   extractor in some reps and *absent* in others; none are *cleared* in another
   rep (that is why flips = 0). So the residual cross-rep variance in the
   confirmed set is now (a) extractor surfacing (present vs absent) and (b) the
   honest borderline zone — neither of which is the pathological confirmed↔cleared
   jump the gate targets. The confirmed set is high-precision (both judges must
   agree) but sparse (mean 0.27/article); the borderline zone carries the mass
   (mean 2.40/article), honestly labeled with its vote split.
3. **Cost** is $0.129/article (2 extractors + 2 judges), inside the $0.15 budget.

## Bottom line

Gate v3's pass/fail metric — zero full flips — **passes**. The dual-judge design
converts run-to-run judge disagreement (previously invisible to a single sample,
and the source of the confirmed↔cleared churn) into a deterministic borderline
assignment. The confirmed set is now sparse and high-precision; whether that
lean confirm rate is the desired product surface, versus surfacing more of the
borderline mass as findings, is a product call for Phase-1 quality — not a
stability question. The stability question is settled: no full flips.

Reproduce: `rm -rf scratch/bias-eval/raw_composite && uv run python
scratch/bias-eval/composite_grid.py run 5 && … scorev3`. Raw cells:
`scratch/bias-eval/raw_composite/`; scored: `scratch/bias-eval/composite_gate_v3.json`.
Prior rounds: `COMPOSITE-STABILITY-RESULT.md`, `DEDUP-FIX-STABILITY-RESULT.md`,
`TIER-MAPPING-GATE-V2-RESULT.md`.
