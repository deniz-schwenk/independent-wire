# EVAL-GLM53-FM-CONFIRM — confirmation batch REPORT

Cold read of the Flash_M finding on fresh production data (2026-09-09/10/11),
two stages only. Premise-check evidence, arm config and the pre-registered
criterion: `reports/METHOD.md`. Machine-readable: `reports/aggregate.json`,
`reports/charges.json`.

## Smoke (first, as the brief asks)

QA_analyze, 2026-09-09 t0, arm F_M: served `z-ai/glm-5.3-flash` by **Z.AI** at
`level: max`, schema-valid, **$0.0150, 62 223 tokens, 135 s**. The champion on
that same case cost **$0.1389**.

## HEADLINE

| stage | n | Δ F_M vs C (fresh) | CI95 | W/T/L | addendum Δ | **verdict** |
|---|--:|--:|---|:--:|--:|---|
| `hydration_phase2` | 9 | **+0.889** | **[+0.633, +1.145]** | 8/1/0 | +1.056 | **CONFIRMED** |
| `qa_analyze` | **8** | +0.656 | **[−0.093, +1.405]** | 6/1/1 | +0.667 | **NOT CONFIRMED** |

The criterion was fixed before the data and is applied mechanically: positive Δ
**and** CI95 excluding zero. `hydration_phase2` clears it. `qa_analyze` does
not, and is reported as not confirmed without qualification.

## `hydration_phase2` — CONFIRMED, and stronger than it looks

| arm | absolute 1–5 | pass-rate | mean rank | firsts | confirmed fabrications |
|---|--:|--:|--:|--:|--:|
| C | 3.167 | 0.727 | 1.94 | 1/18 | **15** |
| **F_M** | **4.056** | **0.904** | **1.06** | **17/18** | **8** |

Δ +0.889, CI [+0.633, +1.145] — a **tighter** interval than the addendum's
[+0.607, +1.504] despite the same n, and the per-case pattern is nearly
degenerate: **eight of nine cases are exactly +1.000 and the ninth is 0.000.**
There is no case where the champion wins. F_M takes 17 of 18 judge firsts and
carries roughly half the champion's confirmed fabrications (8 vs 15), the same
ratio the addendum found (6 vs 14).

This is the most reproducible result across the whole glm-5.3 programme: two
independent batches, six days, 18 topic instances, same direction, same
magnitude, overlapping intervals.

## `qa_analyze` — NOT CONFIRMED, and the reason is precise

| arm | absolute 1–5 | pass-rate | mean rank | firsts | confirmed fabrications |
|---|--:|--:|--:|--:|--:|
| C | 3.531 | 0.842 | 1.70 | 3/10 | 1 |
| **F_M** | **4.188** | **0.953** | **1.30** | **7/10** | **0** |

**The point estimate replicated almost exactly**: +0.656 here vs +0.667 in the
addendum. What failed is the interval, and two things widened it:

1. **n fell from 9 to 8** — the premise check removed 2026-09-10 t0, which
   costs power directly.
2. **One case reversed.** Per-case deltas: `+1, +1, +1, +2, +1, −1, +0.25, 0`.
   Seven of eight are ≥ 0; the single −1.000 (2026-09-11 t0) is the entire
   reason the lower bound crosses zero. Drop it and the interval clears
   comfortably — which is exactly the post-hoc softening the criterion forbids,
   so it is named here as a diagnosis and **not** used to change the verdict.

So the honest statement is: **the qa effect did not reverse and did not shrink;
it failed to separate at n=8 with one bad case.** That is a power result, not a
refutation — and it is still NOT CONFIRMED under the stated rule.

## Fabrication (Honest-Detector, 2-of-2 confirmed)

| stage | C raised → confirmed | F_M raised → confirmed |
|---|--:|--:|
| `hydration_phase2` | 17 → **15** | 9 → **8** |
| `qa_analyze` | 1 → **1** | 1 → **0** |

All 11 charged cases were fully double-judged; no confirmed charge rests on one
judge. F_M is at or below the champion on both stages, and is the only arm with
**zero** confirmed QA fabrications on these days.

## Deterministic checks (free, all 34 outputs)

| | C | F_M |
|---|--:|--:|
| phase2 divergences / gaps | 6.56 / 8.22 | 7.44 / 8.56 |
| qa problems found | 3.50 | 3.38 |
| qa divergences | 4.50 | 5.50 |
| **qa R4** (corrections ↔ problems) | 8/8 | 8/8 |
| **qa R5** (article present iff needed) | **7/8** | **8/8** |

Two things worth the Architect's eye. **The champion broke the R5 invariant on
one of eight QA instances** on these days — F_M did not. And the champion found
*more* QA problems here (3.50) than on the addendum days (2.78), while F_M found
fewer (3.38 vs 4.11): the two arms converged on this metric, which is consistent
with the narrower judged gap.

## Cost (measured, per stage instance)

| stage | C | **F_M** | delta |
|---|--:|--:|--:|
| `hydration_phase2` | $0.0663 | **$0.0085** | **−87%** |
| `qa_analyze` | $0.1701 | **$0.0191** | **−89%** |

**Per 3-topic run, these two stages:** C $0.709 → F_M **$0.083**, a **−88%**
saving. F_M latency: 132 s (phase2) and 165 s (qa) per instance.

## Verification and hygiene

- **17 candidate calls, 0 errors.** Every row logs
  `model_used: z-ai/glm-5.3-flash`, `provider_used: Z.AI`, `level: max`. No
  non-z-ai serve; no fallback wrapper in the path.
- **API total $0.2295** against the $10 cap. Judging $0.00.
- **Production state byte-identical**: 330 files under 2026-09-09/10/11 hashed
  before and after; manifests identical. `--reuse` never run, no production file
  touched, prior-batch artifacts read-only.
- `git status` clean, on `main`, before and after. No commits.
- **Inter-judge agreement**: mean |j1−j2| **0.205** over 22 double-scored
  outputs, 22/22 within 1 point — in line with the addendum's 0.237.

## Limits

1. **Stage isolation** unchanged: every QA arm analyses the CHAMPION's article.
2. **Single judge on 6 of 17 cases** (the un-charged ones); fabrication counts
   unaffected by construction.
3. `qa_analyze` runs at **n=8**, not 9, for a reason outside this eval's control.
4. Two batches now agree on phase2 and disagree on qa's *significance* (not its
   direction). Neither batch alone is large.

## What this means for the owner's decision

- **`hydration_phase2`: the swap case is made.** Confirmed on fresh data, 8 of
  9 cases identical in magnitude, fewer fabrications, **−87% cost**. Two
  independent batches, no case lost to the champion in either.
- **`qa_analyze`: not confirmed, and should not be swapped on this evidence.**
  The effect is probably real — the point estimate replicated to within 0.011 —
  but the pre-registered bar exists precisely so that "probably real" does not
  ship. If the owner wants this stage, the cheapest honest route is more
  instances (a third batch of days at n≈9 would likely settle it), not a
  re-reading of these eight.
