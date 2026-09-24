# CONFIRM-QA2 — second confirmation, qa_analyze, 2026-09-13/14/15

Method, arms, blinding, premise evidence: `reports/METHOD.md`.
Raw numbers: `reports/aggregate.json`, `reports/invariants.json`,
`reports/charges.json`, `reports/pooled.json`. Calls: `logs/calls.jsonl`.

## Smoke (reported first)

09-13 t0, arm F_M: `z-ai/glm-5.3-flash`, provider **Z.AI**, `level: max`,
schema-valid (7 problems / 7 corrections / 8 divergences, corrected article
present), **$0.0253 / 238.7 s**. Champion on the same case: $0.0348.
Wiring confirmed on the new dates before the batch ran.

## Premise check — 9/9, nothing excluded

All nine instances ran `z-ai/glm-5.2` as primary with `qa_fallback_used: false`
and `status: success`. Per-instance rows: `reports/premise-check.jsonl`, read
from each day's frozen stage log. Nothing reconstructed; **n = 9**.

## Verdict — NOT CONFIRMED

| | n | Δ (F_M − C) | CI95 | W/T/L |
|---|--:|--:|---|:--:|
| **confirm-2 (this batch, 09-13/14/15)** | **9** | **+0.444** | **[−0.146, +1.035]** | **6/1/2** |
| confirm-1 (09-09/10/11) | 8 | +0.656 | [−0.093, +1.405] | 6/1/1 |
| addendum (09-06/07/08) | 9 | +0.667 | [+0.282, +1.051] | 6/3/0 |

Pre-registered criterion: positive Δ **and** CI95 excluding zero, on this fresh
data alone. Δ is positive; the interval includes zero. **NOT CONFIRMED.**

Per-case deltas: `+1.0, −0.5, +0.5, +1.0, +1.0, −1.0, +1.0, +1.0, 0.0`.

Arm summary: C abs **3.556**, pass 0.882, 5 firsts of 18 judge rankings;
F_M abs **4.000**, pass 0.922, **13 firsts of 18**.

This is the **second** consecutive failure of the criterion for qa_analyze, and
the point estimate has now moved down three batches running (+0.667 → +0.656 →
+0.444). Two of the three batches produced a loss case; the addendum produced
none. The direction has been positive every time; the magnitude has not been
stable, and that is the finding.

### Secondary (explicitly not the verdict)

Pooled across all three qa batches — per-case **deltas** only, never absolute
scores, since each delta was paired against a C judged in its own session:

**n = 26, Δ +0.587, CI95 [+0.300, +0.874], W/T/L 18/5/3** — excludes zero.

The pre-registered criterion is decided on confirm-2 alone and it fails. The
pooled reading is reported because three independent batches carry more
information than the one in front of you, and quoting only the latest would be
its own kind of selection. It is not a substitute for the criterion, and the
right way to read the pair is: the effect is probably real and positive, and it
is smaller and noisier than any single batch's point estimate suggested.

## Fabrications (Honest-Detector, 2-of-2)

All 9 cases were double-judged, so every charge had a chance to be confirmed.

| | charges raised (both judges) | **confirmed 2-of-2** |
|---|--:|--:|
| C | 5 | **1** |
| F_M | 4 | **1** |

One each, and neither is trivial. The confirmed C charge (09-13 t0) attributes
a "precise and direct" characterisation to three sources when only src-001
carries it. The confirmed F_M charge (09-14 t2) asserts src-003 calls Musk
owner/founder of xAI when src-003's actor entry says "Owner of SpaceXAI" — the
output misattributes the very formulation it claims distinguishes another
source. Both are source-misdescription, the R3 failure mode.

The fabrication advantage F_M held in the earlier batches (8 vs 15 on phase2;
0 vs 1 on qa in confirm-1) **does not appear here**: the arms are level at 1–1.

## Deterministic invariants — level, both arms clean

`reports/invariants.json`, computed in Python, no judge involved:

| | R4 (correspondence) | R5 (article iff needed) | mean problems | mean divergences |
|---|--:|--:|--:|--:|
| C | 9/9 | 9/9 | 2.89 | 4.11 |
| F_M | 9/9 | 9/9 | **4.44** | **6.11** |

Batch 1's single champion R5 violation did not recur — on these days the
champion is mechanically clean. F_M continues to flag ~1.5× more problems and
~1.5× more divergences; the judges scored that as slightly better on average
(pass 0.922 vs 0.882) but not decisively, and the two loss cases are where the
extra volume read as noise rather than yield.

## Cost

| | total (9 cases) | per case |
|---|--:|--:|
| C | $1.5372 | $0.0348 … $0.4657 |
| F_M | **$0.1889** | $0.0167 … $0.0308 |

**−88%**, matching confirm-1's −89%. The ratio is not uniform: it is 1.4× on the
cheapest case and **24×** on 09-15 t1. F_M's cost is nearly flat across inputs
($0.017–$0.031) while the champion's spans 13×, so the saving is largest exactly
where the champion is most expensive. Judging cost $0.00 (subagents).

## Hygiene

- 9 F_M calls, **0 errors**; all `z-ai/glm-5.3-flash` / provider `Z.AI` /
  `level: max` (`logs/calls.jsonl`). Mean 212.9 s.
- **$0.1889** against the $10 cap.
- Inter-judge agreement over 18 double-scored outputs: mean |j1−j2| **0.444**,
  18/18 within 1 point, 10/18 exact. Neither judge alone reaches the criterion
  (judge 1 Δ +0.556 [−0.003, +1.114]; judge 2 Δ +0.333 [−0.332, +0.999]), so the
  verdict does not hinge on one judge — it is the same answer either way.
- Production state byte-identical before and after: 351 files
  (`reports/PRE-manifest.txt` vs `POST-manifest.txt`). No `--reuse` was run.
- `git status` clean, checkout on `main`, no commits, no production files touched.

## Recommendation

Do not swap qa_analyze on this evidence. Two pre-registered confirmations have
now failed in a row, and the point estimate is drifting down rather than
stabilising — which is what you would expect if the true effect is around
+0.4–0.6 and the addendum's +0.667 with zero losses was the optimistic tail.

What the three batches jointly support is a genuine but modest quality gain
(pooled +0.587, 18/26 wins) at −88% cost, with fabrications level and both arms
mechanically clean. That is a defensible cost-led swap, but it is an owner
judgement about price versus a small quality edge — it is NOT the "confirmed
better" the criterion was written to establish, and it should not be recorded
as one. If the goal is to satisfy the criterion rather than to decide on cost,
the honest route is more days, not a re-reading of these nine.
