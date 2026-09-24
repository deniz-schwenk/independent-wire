# TASK-EVAL-DSV41-FLASH-PLANNER (Batch 1) — REPORT

Two-arm judged comparison on `researcher_hydrated_plan` over the frozen
production state of 2026-09-06 / 07 / 08, n=9 topic instances.

- **C** = champion `deepseek-v4-pro` @ `low`, channel C
- **F** = `deepseek/deepseek-v4.1-flash` @ `low`, OpenRouter + vendor pin

Identity evidence, arms, deviations: `reports/METHOD.md`.
Machine-readable: `reports/aggregate.json`, `reports/charges.json`.

## VERDICT — C. Keep deepseek-v4-pro. F fails non-inferiority.

| reading | n | paired Δ (F − C, rubric mean D1–D6) | CI95 | W/T/L |
|---|--:|--:|---|:--:|
| **all cases, both judges** | 9 | **−0.481** | [−1.042, +0.079] | 2/0/7 |
| all cases, judge 1 only | 9 | −0.500 | [−0.996, −0.004] | 2/0/7 |
| 09-07/08 only (champion is untouched production) | 6 | −0.333 | [−1.239, +0.572] | 2/0/4 |

F is **not superior** on any reading, and **not non-inferior**: the CI lower
bound is **−1.04**, which fails against any sensible non-inferiority margin
(T5b's raised bar for a swap of this kind was a CI lower bound above −0.10).
The point estimate is negative on all three readings, F loses 7 of 9 paired
cases, and it is behind the champion on **all six dimensions**.

**An honest note on significance.** On judge 1 alone the interval excluded zero
(−0.996, −0.004). Folding in the second judges — dispatched for the
Honest-Detector pass, not to change the score — widened it to include zero. So
the direction is consistent and the magnitude is large, but at n=9 the two arms
are **not statistically separated**. The verdict rests on the failed
non-inferiority bound plus the unanimous dimension sweep, not on a p-value.

## Per-dimension (mean over both judges)

| dim | C | F | Δ |
|---|--:|--:|--:|
| D1 gap coverage | 3.429 | 3.357 | −0.07 |
| **D2 angle distinctness** | 3.714 | **2.786** | **−0.93** |
| D3 specificity | 3.571 | 3.357 | −0.21 |
| **D4 prioritisation** | 3.429 | **2.929** | **−0.50** |
| D5 no-invention | 4.429 | 4.071 | −0.36 |
| D6 language balance | 3.643 | 3.286 | −0.36 |

## The mechanism: F buys volume, not angles

This is the translation-matrix anti-pattern `PLAN-INSTRUCTIONS.md` forbids by
name, and the rubric's mandatory `angle_groups` partition is what exposes it.

| | C | F |
|---|--:|--:|
| queries per plan | 14.2 | **18.1 (+27%)** |
| distinct angle groups | 12.4 | 13.6 (+10%) |
| **queries per angle group** | **1.14** | **1.33** |
| languages per plan (deterministic) | 9.7 | **12.3** |
| `named_absences` — gaps the plan does NOT target | **3.21** | **3.21** |

F spends 27% more of a fixed search budget and leaves **exactly the same number
of dossier gaps untargeted**. D1 is effectively tied (−0.07) for that reason:
the extra queries are not reaching new ground, they are re-rendering ground
already covered in more languages. One judge counted five of eighteen F queries
as one angle — outside reaction to the same headline in Russian, Chinese,
Japanese, Uzbek and French with no change of stakeholder — consuming 28% of that
plan's budget.

D4 follows from the same behaviour: F funds peripheral language communities at
scale while each central gap gets one query. The extra languages are the tell —
F's spread includes Uzbek ×6, Swahili ×9, Japanese ×5 where C has Uzbek ×1,
Swahili ×4, Japanese ×1, and in at least one case F carried Uzbek while dropping
Farsi on a story where Iran is quoted in the corpus and Uzbekistan is not
involved at all.

## Deterministic checks (all 18 judged plans, free)

- **Native script: 0 violations on both arms** — 60/60 script-required queries
  correct for C, 71/71 for F (ar, fa, ur, he, ru, uk, zh, ko, th, hi, ne, bn).
  Whatever else F does, it does not transliterate.
- **Exact duplicate queries: 0 on both arms.** F's redundancy is semantic, which
  is precisely why it needs the judges' angle partition and not a string check.
- Mean query length is essentially equal (C 8.60 words, F 8.31), so the volume
  difference is more queries, not longer ones.

## Fabrication (Honest-Detector, 2-of-2 confirmed)

| arm | charges raised (judge 1) | **CONFIRMED by two judges** |
|---|--:|--:|
| C | 4 | **3** |
| F | 8 | **6** |

Five cases carried charges and every one was fully double-judged; no confirmed
charge rests on a single judge. F carries twice the champion's confirmed rate.
Both arms' charges are overwhelmingly *unsupported presupposition* rather than
invented entities — queries that presuppose an event the dossier does not carry,
so a search would seek confirmation rather than test it. No arm invented a
non-existent institution.

## Cost and latency (measured, per topic instance)

| arm | mean cost | mean tokens | mean latency |
|---|--:|--:|--:|
| C (`deepseek-v4-pro`, channel C) | $0.0152 | 14 373 | 56.4 s |
| **F (`v4.1-flash`, vendor pin)** | **$0.0027 (−82%)** | 12 703 | **12.4 s (4.5× faster)** |

F is genuinely much cheaper and much faster. At 3 topics/run the planner line
goes $0.046 → $0.008. **That saving is real and it is not enough**: the planner
is already 0.4% of a $3.58 hydrated run, so the absolute saving is about
$0.038/run, bought at −0.48 rubric points and double the confirmed
presuppositions on the stage whose entire output is the search budget for
everything downstream.

## Verification and hygiene

- **12 candidate calls, 0 errors.** All 9 arm-F rows carry
  `model_used: deepseek/deepseek-v4.1-flash`, `provider_used: DeepSeek`; all 3
  `Cstar` rows carry `deepseek-v4-pro` / `deepseek_direct`. No non-vendor host
  served any call, so no call is invalidated.
- **API total $0.0702** against the $10 cap. Judging $0.00 (subagents).
- **Production state byte-identical**: 351 files hashed before and after,
  manifests identical. `--reuse` never run, no production file touched.
- `git status` clean, on `main`, before and after. No commits.
- **Inter-judge agreement**: 10 double-scored outputs, mean |j1−j2| on the
  rubric mean = **0.217**, all 10 within 0.5. Advisory-mean self-consistency
  mismatches: **0 of 28** (every judge's own `mean` matched the recomputation).

## Limits

1. **The rubric scores the PLAN, not the harvest** — carried forward verbatim
   from T5a, and it is the single largest caveat. No search was executed. F could
   in principle retrieve better with worse-looking plans; nothing here measures
   that, and the correlation remains unmeasured.
2. **n=9, and not statistically separated.** See the significance note above.
3. **3 of 9 champion instances were reconstructed**, because 2026-09-06's
   production run shipped Opus-4.6, not the champion. The n=6 un-deviated subset
   is reported alongside and points the same way with a wider interval.
4. **Single judge on 4 of 9 cases.** The five charged cases are double-judged;
   the other four carry one judge's draw.
5. `deepseek-flash` on channel C was **not** tested. If a future task can
   establish that alias as v4.1, channel C would be the cheaper route and this
   verdict does not speak to it — but the quality result would be unchanged,
   since route does not change weights.

## If the owner wants to revisit

The one thing that could overturn this is the limitation in §1: a harvest test.
F's failure mode is redundant breadth, and redundant breadth is exactly the
failure a plan-only rubric punishes hardest and a real search index might
forgive — a blunt query in a fifth language sometimes retrieves what a precise
one does not. That would be a different task with a different instrument
(execute both plans, compare what comes back), not a re-judge of these plans.
