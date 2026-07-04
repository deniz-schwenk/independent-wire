# Three-tier judge — Gate v2 (confirmed-set Jbar + full-flip distance)

**Verdict: STOP + REPORT.** Both gate metrics fail. Per TASK-BIAS-TIER-MAPPING,
a full-flip count > 0 is a hard stop reported with the flipping families.

## The two metrics (5-article × 3-cache-cold grid, three-tier judge)

| article | confirmed (r0,r1,r2) | Jconf | borderline (r0,r1,r2) | Jbord | full flips |
|---|---|---|---|---|---|
| 2026-06-13#0 (Pope/Spain) | 1, 0, 0 | 0.67 | 2, 2, 2 | 0.78 | 0 |
| 2026-06-17#1 (Bolsonaro) | 0, 0, 0 | 0.00 | 2, 1, 2 | 0.83 | 0 |
| 2026-06-02#2 (Anthropic IPO) | 0, 1, 0 | 0.67 | 1, 2, 2 | 1.00 | 0 |
| 2026-06-22#2 (DRC Ebola) | 1, 2, 2 | 0.72 | 3, 3, 4 | 0.74 | 0 |
| 2026-06-20#0 (US-Iran/Hezb) | 1, 0, 0 | 0.67 | 0, 1, 1 | 1.00 | **2** |

- **PRIMARY — Jbar_exact (confirmed set) = 0.544** — FAIL (target ≤ 0.35)
- **HARD — full flips (confirmed↔cleared) = 2** — FAIL (target 0)
- borderline Jbar = 0.871 (informational — adjacent drift is not gated)
- mean confirmed 0.53/article · mean borderline 1.87/article · **$0.0683/run** (target ≤ $0.06)

### The flipping family (HARD gate)

Both flips are the **same candidate family** on 2026-06-20#0, surfacing as an
exact match and its sub-span:

- `'a deliberate test of Washington's credibility'` — **confirmed in r0, cleared in r1**
- `'a deliberate test of Washington's credibility'` (r0 confirmed) ↔ `'a deliberate test'` (r2 cleared)

On identical input the judge confirms this phrase in one cold run and clears it
in the other two — the exact confirmed↔cleared instability the three-tier design
was meant to remove. Here the judge did **not** route it to `borderline`; it
committed to opposite poles across runs.

## Reading it (for the Architect)

1. **The three-tier judge works as designed for most candidates.** Marginal
   calls now land in the honest gray zone — mean 1.87 borderline/article, and 4
   of 5 articles have **zero** full flips. The binary confirm/clear oscillation
   that dominated the dedup-fix round (Jbar 0.411, all churn in the confirm
   decision) has largely relocated to `borderline`, where the design says it is
   honest and ungated. That is real progress on the *mechanism*.
2. **But it does not clear either gate.**
   - **HARD fails** because one candidate (`a deliberate test [of Washington's
     credibility]`) still jumps the full distance confirmed→cleared instead of
     resolving to borderline. The gray zone caught most of the marginal mass but
     not this one; the judge is *confidently* split on it across cold runs.
   - **PRIMARY fails** largely as an artifact of sparsity: with confirmed counts
     collapsed to 0–2/article, a single `[1,0,0]` transition scores Jexact 0.67
     for that article, so the exact-set Jaccard is dominated by 1-vs-0 flips at
     the margin. The confirmed set is now high-precision but so thin that
     exact-set stability is brittle. (The brief anticipated "expected well below
     0.35 — only clear cases confirm now"; in practice the confirm rate fell far
     enough that the few confirmations that remain are themselves the unstable
     ones.)
3. **Cost** is $0.0683 (just over $0.06), same order as before — the judge still
   processes the full 16–24 union.

## Decision surface

The three-tier verdict + borderline gray zone is a genuine, low-risk
architectural improvement (honest tiering, additive slot, most churn now
ungated) and is committed on `feat/bias-stage-split`. It does **not** pass Gate
v2: 2 full flips remain and the sparse confirmed set is exact-unstable. Levers
the Architect may consider next (all out of scope here — prompts authoritative):
- push the residual confirmed↔cleared straddlers into `borderline` (the judge
  prompt's confirm/clear threshold is the lever);
- change the PRIMARY metric to tolerate sparsity (e.g. soft/union Jaccard, or
  score confirmed∪borderline stability rather than the exact confirmed set);
- accept borderline as the product surface for marginal calls and gate on
  full-flip only.

Reproduce: `rm -rf scratch/bias-eval/raw_composite && uv run python
scratch/bias-eval/composite_grid.py run 5 && … scorev2`. Raw cells:
`scratch/bias-eval/raw_composite/`; scored: `scratch/bias-eval/composite_gate_v2.json`.
Prior rounds: `COMPOSITE-STABILITY-RESULT.md` (split, 0.406) →
`DEDUP-FIX-STABILITY-RESULT.md` (dedup, 0.411).
