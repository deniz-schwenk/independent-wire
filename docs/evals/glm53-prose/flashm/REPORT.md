# EVAL-GLM53-PROSE-STAGES addendum — arm F_M (`glm-5.3-flash` @ `max`)

One candidate arm added to the Batch-1 comparison, on the same four stages and
the same nine frozen production inputs (2026-09-06/07/08).

Operating point, `max`-acceptance evidence and the drift-control design:
`reports/METHOD.md`. Machine-readable: `reports/aggregate.json`,
`reports/charges.json`.

## Smoke (reported first, as the brief asks)

Writer, 2026-09-06 t0, arm F_M: served `z-ai/glm-5.3-flash` by **Z.AI**,
schema-valid, **$0.0185, 60 400 tokens, 223 s**. Against the same case: C
$0.0149 / H $0.0679 / M $0.2937. `max` accepted and confirmed distinct (see
METHOD — reasoning tokens 132 / 286 / 1316 for low / high / max).

## Combined table — paired Δ vs champion, all four arms

Every delta is paired against a C judged in its own session, so the columns are
comparable even though the batches ran days apart.

| stage | n | H (`glm-5.3` high) | M (`glm-5.3` max) | **F_M (`flash` max)** |
|---|--:|---|---|---|
| `hydration_phase2` | 9 | +0.778 [+0.50, +1.06] | **+1.333** [+1.00, +1.67] | **+1.056** [+0.61, +1.50] · **9/0/0** |
| `qa_analyze` | 9 | +0.722 [+0.38, +1.06] | **+1.111** [+0.51, +1.71] | +0.667 [+0.28, +1.05] · 6/3/0 |
| `writer` | 9 | −0.111 [−0.53, +0.31] | **+0.833** [+0.45, +1.22] | +0.167 [−0.17, +0.50] · 3/5/1 |
| `editor` | **3** | −0.167 [−2.06, +1.73] | +0.167 [−0.55, +0.88] | −0.167 [−2.06, +1.73] · 1/1/1 |

**Verdict per stage**

- **`hydration_phase2` — F_M beats the champion decisively**, wins all 9 cases,
  16/16 judge firsts, CI well clear of zero. It lands between H and M and is
  within noise of M.
- **`qa_analyze` — F_M beats the champion**, never loses a case (6/3/0), CI
  excludes zero. Statistically indistinguishable from H; below M's point
  estimate but with overlapping intervals.
- **`writer` — no verdict for F_M.** CI straddles zero, 5 of 9 cases tie. It is
  better than H (which was negative) and clearly below M. On this stage **M
  remains the only arm that beats the champion.**
- **`editor` — no discrimination, n=3**, as in Batch 1. All three arms' intervals
  span zero by ±2. Nothing here can decide the editor.

## Judge-drift control (the brief's requirement)

C was re-judged in these fresh sessions. Its re-scores against Batch 1:

| stage | Batch-1 C | re-judge C | Δ | CI95 | mean abs drift | exact | within-1 |
|---|--:|--:|--:|---|--:|:--:|:--:|
| `hydration_phase2` | 3.056 | 2.944 | **−0.111** | [−0.53, +0.31] | 0.333 | 5/9 | 9/9 |
| `writer` | 3.667 | 3.889 | **+0.222** | [−0.06, +0.50] | 0.222 | 6/9 | 9/9 |
| `qa_analyze` | 3.222 | 3.556 | **+0.333** | [−0.21, +0.88] | 0.556 | 4/9 | 9/9 |
| `editor` | 3.833 | 4.167 | +0.333 | [−1.56, +2.23] | 0.667 | 0/3 | 3/3 |

**No material drift.** Every interval spans zero, every case is within 1 point,
and the mean absolute drift (0.22–0.67) is the same order as the within-session
inter-judge spread measured here (mean |j1−j2| = **0.237** over 38
double-scored outputs). The instrument is stable at the level the verdicts are
read at.

Two honest qualifications. The drift is **positive on three of four stages**
(+0.22, +0.33, +0.33), i.e. this round's judges scored C slightly more generously
— a small systematic component, not just noise. That inflates nothing in the
table above, because each delta is computed against the C from its own session;
it would have mattered had F_M been differenced against Batch-1's C. And
`qa_analyze` drifted +0.333 with a 0.556 mean absolute drift, the largest on a
9-case stage: F_M's qa delta (+0.667) is comfortably outside that, but a future
margin under ~0.5 on this stage should not be trusted from a single judge draw.

## Fabrication (Honest-Detector, 2-of-2 confirmed, this batch's sessions)

| stage | C raised → confirmed | F_M raised → confirmed |
|---|--:|--:|
| `hydration_phase2` | 18 → **14** | 11 → **6** |
| `writer` | 8 → **3** | 2 → **1** |
| `qa_analyze` | 1 → **1** | 2 → **1** |
| `editor` | 3 → **1** | 4 → **1** |
| **total** | **30 → 19** | **19 → 9** |

All 19 charged cases were fully double-judged; no confirmed charge rests on one
judge. F_M carries roughly half the champion's confirmed rate, driven by
phase2 and the writer.

## Deterministic checks, all arms side by side

**Writer length discipline (R8, 600–1200 words) — the brief's tracked metric:**

| arm | mean words | over-length | mean citations |
|---|--:|:--:|--:|
| C | 1087 | **3/9** | 62.4 |
| H | 1180 | 4/9 | 55.8 |
| M | 1214 | 7/9 | 72.8 |
| **F_M** | **1246** | **7/9** | **82.4** |

**F_M is the worst arm in the field on length** — highest mean, tied-worst
over-length count, and its longest article (1422 words) is the longest anything
produced in either batch. It also cites hardest (82.4 vs the champion's 62.4).
The judges saw this inside R8 and F_M still came out marginally ahead of C, but
a swap here would ship longer articles than any arm evaluated.

**Zero invented source ids**: all 9 F_M articles, every `[src-NNN]` resolves to a
real id in that topic's `final_sources` — matching C, H and M.

**QA correspondence invariants**: R4 (`len(corrections) == len(problems)`) 9/9
and R5 (corrected article present iff a fix is needed) 9/9 for F_M, as for every
other arm.

**Output volume:**

| | C | H | M | F_M |
|---|--:|--:|--:|--:|
| phase2 divergences / gaps | 6.11 / 8.44 | 7.67 / 8.33 | 9.11 / 9.33 | 8.33 / 8.11 |
| qa problems found | 2.78 | 5.00 | 6.00 | **4.11** |
| qa divergences | 4.56 | 5.33 | 7.00 | 6.44 |

F_M finds fewer QA problems than either glm-5.3 arm but still ~1.5× the
champion, and its judged score is the same as H's — consistent with the reading
that the extra problems H and M surface are real but subject to diminishing
returns.

## Cost and latency (measured, per stage instance)

| stage | C | H | M | **F_M** | F_M latency |
|---|--:|--:|--:|--:|--:|
| `editor` | $0.0276 | $0.0261 | $0.0718 | **$0.0065** | 112 s |
| `hydration_phase2` | $0.0186 | $0.0362 | $0.1237 | **$0.0068** | 100 s |
| `writer` | $0.0427 | $0.0616 | $0.3256 | **$0.0241** | 322 s |
| `qa_analyze` | $0.1161 | $0.1422 | $0.2977 | **$0.0187** | 178 s |

**Per 3-topic run, these four stages together:**

| arm | cost | vs champion |
|---|--:|--:|
| C | $0.5678 | — |
| H | $0.7458 | +31% |
| M | $2.2949 | +304% |
| **F_M** | **$0.1554** | **−73%** |

F_M is the only arm in the field that is **cheaper than the champion** — by a
factor of 3.7 — while beating it on two stages. Against M, which wins more
stages, F_M costs **1/15th**. Writer latency (322 s/topic) is its weak point but
is still 3× faster than M's 992 s.

## Verification and hygiene

- **30 candidate calls, 0 errors.** Every row logs
  `model_used: z-ai/glm-5.3-flash`, `provider_used: Z.AI`, `level: max`. No
  non-z-ai serve, no fallback in the path.
- **API total $0.4661** against the $10 cap. Judging $0.00.
- **Production state byte-identical**: 351 files hashed before and after;
  additionally the Batch-1 frozen input copy was re-verified against production
  (303 state files, 0 mismatches) before any call.
- Batch-1 artifacts read-only; all writes under `flashm/`.
- `git status` clean, on `main`, before and after. No commits.
- Inter-judge agreement this batch: mean |j1−j2| **0.237** over 38 double-scored
  outputs, 38/38 within 1 point.

## Limits

1. **Stage isolation** — unchanged from Batch 1. Every QA arm still analyses the
   CHAMPION's article, so a writer gain cannot propagate.
2. **Single judge on 11 of 30 cases** (the un-charged ones). Fabrication counts
   are unaffected by construction.
3. **n=3 on the editor**, unfixable by re-judging.
4. F_M's writer verdict is a genuine null, not a hidden win: 5 of 9 cases tied.
5. The drift control shows the instrument is stable, but it is one re-judge of
   one arm; it does not license differencing raw scores across batches, and this
   report never does.

## What this changes for the owner's decision

Batch 1's honest split was "move `qa_analyze` and `hydration_phase2`, leave the
writer" — with H at +31% run cost or M at +304%. F_M adds a third option on
exactly those two stages at **−73%**:

- On **`hydration_phase2`**, F_M is near M's quality at 1/18th of M's cost and
  1/3 of the champion's. This is the clearest result in either batch.
- On **`qa_analyze`**, F_M ties H at 1/8th of H's cost.
- On the **writer**, nothing has changed: **M is still the only arm that beats
  the champion**, and it costs 13× the champion on that stage.
