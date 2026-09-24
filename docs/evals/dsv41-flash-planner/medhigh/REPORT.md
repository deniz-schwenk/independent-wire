# EVAL-DSV41-FLASH-PLANNER addendum — arms F_med / F_high — REPORT

`researcher_hydrated_plan`, frozen production inputs 2026-09-06/07/08, n=9.
Method, level evidence and a correction to Batch 1's labelling: `reports/METHOD.md`.
Machine-readable: `reports/aggregate.json`, `reports/charges.json`.
Judge rationales: `reports/judge_rationales.md` (digest) and
`judging/<case>/verdict-{1,2}.json` (source). Calls: `logs/calls.jsonl`.

## Smoke (reported first)

2026-09-07 t0, both arms, one judge pass:

| arm | sent | served | schema | queries | cost | tokens | reasoning tok | latency | smoke judge (mean) |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| F_med | `{"effort":"medium"}` | deepseek-v4.1-flash / **DeepSeek** | valid | 17 | $0.0030 | 13 323 | 1 746 | 10.7 s | 3.167 |
| F_high | `{"effort":"high"}` | deepseek-v4.1-flash / **DeepSeek** | valid | 22 | $0.0035 | 14 134 | 2 399 | 16.1 s | 3.667 |
| C (same case) | — | — | — | 16 | — | — | — | — | 3.500 |

Level acceptance: `medium` and `high` both 200 on the vendor-pinned route;
the route validates the enum (a bogus value → 400 listing
`max|xhigh|high|medium|low|minimal`) — `level_probe.json`. Smoke evidence:
`logs/smoke.log`, `candidates/planner__2026-09-07__t0__{Fmed,Fhigh}.json`,
`judging/planner__2026-09-07__t0/verdict-1.json`.

## VERDICT — Keep deepseek-v4-pro. Neither F_med nor F_high is non-inferior.

| arm (paired vs C, same session) | n | Δ | CI95 | W/T/L | NI (lower > −0.10) |
|---|--:|--:|---|:--:|:--:|
| **F_med** — mean of judges | 9 | **−0.380** | **[−0.752, −0.007]** | 3/0/6 | **FAIL** |
| F_med — judge 1 only | 9 | −0.370 | [−0.743, +0.002] | | FAIL |
| F_med — Batch-1 method (last-writer) | 9 | −0.389 | [−0.768, −0.010] | | FAIL |
| F_med — 09-07/08 only (C not reconstructed) | 6 | −0.347 | [−0.846, +0.152] | 2/0/4 | FAIL |
| **F_high** — mean of judges | 9 | **−0.287** | **[−0.791, +0.216]** | 4/0/5 | **FAIL** |
| F_high — judge 1 only | 9 | −0.296 | [−0.783, +0.191] | | FAIL |
| F_high — Batch-1 method (last-writer) | 9 | −0.278 | [−0.802, +0.247] | | FAIL |
| F_high — 09-07/08 only | 6 | −0.278 | [−1.086, +0.531] | 3/0/3 | FAIL |
| *F_low (Batch 1, own session) — mean of judges* | 9 | *−0.491* | *[−1.017, +0.036]* | 2/0/7 | FAIL |
| F_high vs F_med | 9 | +0.093 | [−0.154, +0.340] | 5/2/2 | — |

Every reading of both arms fails the bar, and the point estimate is negative on
all of them. **F_med's interval excludes zero on the losing side** on the
mean-of-judges and last-writer readings (judge-1-only touches +0.002): at
`medium` the flash model is measurably worse than the champion — the same
strength of result Batch 1 got for F_low only on its judge-1 reading
([−0.996, −0.004]). F_high is the
best flash arm — its point estimate is ~0.2 above F_low's — but its lower bound
(−0.79) sits far below −0.10, it loses 5 of 9 cases, and F_high vs F_med is not
separated (CI spans zero). **More reasoning narrows the gap without closing it.**

## The planner table — C / F_low / F_med / F_high

Rubric dims and plan shape are means over all judge readings; queries and
languages are deterministic from the plans. F_low is Batch 1's session
(cross-session absolutes are reference only — read the paired Δ above).

| arm | rubric mean | D1 gap cov. | D2 distinct | D3 specific | D4 priorit. | D5 no-invent | D6 lang bal. | queries/plan | angle groups | **queries / angle group** | named absences | languages/plan | mean rank | firsts |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **C** | **3.667** | 3.200 | **3.733** | 3.400 | **3.533** | 4.600 | **3.533** | 13.9 | 11.7 | **1.18** | 2.87 | 9.7 | **1.73** | **9/15** |
| F_low | 3.298 | 3.357 | 2.786 | 3.357 | 2.929 | 4.071 | 3.286 | 17.7 | 13.6 | 1.30 | 3.21 | 12.3 | 1.71 | 4/14 (2-way) |
| F_med | 3.256 | 3.200 | 3.067 | 3.200 | **2.467** | 4.600 | 3.000 | 17.9 | 13.7 | 1.30 | 2.67 | 13.3 | 2.40 | 1/15 |
| F_high | 3.356 | 3.133 | 2.867 | **3.733** | 2.867 | 4.600 | 2.933 | 19.7 | 14.7 | 1.34 | 2.80 | 13.4 | 1.87 | 5/15 |

Per-case matrix (all four arms plus Batch-1's reading of C): `aggregate.json` → `matrix`.

## Mechanism — why the loss happens, and what the extra reasoning buys

Batch 1's diagnosis carries over intact and grows with the level: **more
reasoning → more queries and more languages, not more angles.**

- **Volume up, angles flat.** Queries/plan 13.9 (C) → 17.7 / 17.9 / **19.7**
  (low/med/high). Queries per angle group 1.18 → 1.30 / 1.30 / **1.34**: each step
  up spends *more* of the budget re-rendering an angle already covered.
  Languages/plan 9.7 → 12.3 / 13.3 / 13.4: the translation-matrix pattern the
  planner prompt forbids, larger at higher levels.
- **Gap coverage is not the problem and never was.** Named absences (dossier
  gaps a plan leaves untargeted): C 2.87, F_med 2.67, F_high 2.80. The flash
  arms leave the same number of gaps as C or slightly fewer. D1 is flat across
  all four arms (3.13–3.36).
- **Prioritisation is the loss.** D4: C 3.53, F_med **2.47**, F_high 2.87. The
  judges' rationales name the same pattern case after case: the central story
  gets one query each while peripheral third-country and spill-over angles get
  whole language fans (`judge_rationales.md`, e.g. 09-06 t0: *"inverts priorities
  toward peripheral mediation and economic-spillover angles in checklist
  languages"*). `medium` is worst on exactly this dimension.
- **What `high` does buy:** D3 specificity rises above C (3.73 vs 3.40): more
  institution-level, concretely targeted queries. F_high's wins (4/9) are the
  cases where that specificity outweighs its breadth (09-08 t1: 4.08 vs 3.50).
  It does not transfer to D2/D4/D6.

## Fabrication (Honest-Detector, 2-of-2 confirmed)

| arm | raised (j1) | raised (j2) | **confirmed 2-of-2** |
|---|--:|--:|--:|
| C | 3 | 3 | **3** |
| F_med | 3 | 3 | **3** |
| F_high | 3 | 3 | **2** |

All 6 charged cases were fully double-judged (`needs_second_judge: []`).
Batch 1 had F_low at 6 confirmed vs C's 3; at `medium`/`high` the flash arms are
level with the champion. The class is unchanged: unsupported presupposition in
non-English queries, e.g. F_high 09-06 t0 q16 `북한군 우크라이나 파병` (North Korean
deployment the dossier never mentions); F_med 09-08 t2 q11 (a Pakistani UN
contingent in Lebanon). C's three are the same kind (e.g. an Arab League
condemnation the dossier explicitly says did not happen). No arm invented an
institution. Detail: `charges.json` → `confirmed_detail`.

## Judge-drift control — C re-judged

Same 9 champion plans, fresh sessions (now alongside two other plans instead of one):

| | Batch-1 C | re-judged C | Δ | CI95 | mean abs Δ | within 0.5 |
|---|--:|--:|--:|---|--:|:--:|
| mean of judges | 3.787 | 3.657 | **−0.130** | [−0.350, +0.090] | 0.204 | 8/9 |
| judge 1 only | | | −0.148 | | | |

**No material drift**: the interval spans zero and 8 of 9 cases move ≤ 0.5.
Two qualifications, as numbers not reassurance: (1) the drift is **negative**,
so this session scored the champion slightly *harder* — the paired deltas
above are computed within session, so this does not flatter C; if anything it
flatters the candidates; (2) per dimension D1 moved most (−0.229), in line with
the known D1 drift (INDEX 2026-09-02); D5 +0.171, D3 −0.171, others ≤ 0.11
(`aggregate.json` → `drift_C_per_dim`). The one large case is 09-06 t2
(3.75 → 3.08, a reconstructed-C day). Inter-judge agreement this batch: mean
|j1−j2| **0.139** over 18 double-scored outputs, 18/18 within 0.5.

## Cost and latency (measured, per call)

| arm | mean cost | median completion tok | median reasoning tok | mean latency |
|---|--:|--:|--:|--:|
| C (Batch 1, channel C) | $0.0152 | — | — | 56.4 s |
| F_low | $0.0028 | 1 937 (derived) | not logged | 12.4 s |
| F_med | $0.0032 | 2 420 | 1 862 | 13.9 s |
| F_high | $0.0038 | 3 394 | 2 758 | 19.2 s |

F_high is still **−75% vs C** at ~3× the speed. The planner is ~0.4% of a
$3.58 run; the absolute saving at 3 topics/run is ≈ $0.034/run.

## Hygiene

- 18 calls, 0 errors; all `model_used: deepseek/deepseek-v4.1-flash`,
  `provider_used: DeepSeek`, 1 API call each; levels as sent. **$0.0625** of the
  $10 cap, plus $0.0037 level probe. Judging $0.00.
- Production state byte-identical (351 files, `logs/prod_state_manifest.PRE.txt`
  == `.POST.txt`); frozen inputs re-verified vs production
  (`logs/frozen_vs_prod.txt`). `--reuse` never run.
- Batch-1 artifacts untouched. `git status` clean, on `main`, before and after.

## Limits

1. **Plan-level rubric, no harvest test** — Batch 1 / T5a's standing caveat.
   F_high's extra specificity might retrieve better than its D2/D4 suggest;
   nothing here measures it.
2. n=9; single judge on the 3 uncharged cases.
3. Judging context changed from 2 to 3 plans per session. The drift control
   absorbs this for C (−0.13, not material); it is why F_low is kept as
   reference rather than differenced against this session's C.
4. The 09-06 champion is Batch 1's reconstruction (`Cstar`); the n=6 subset
   points the same way on both arms.

## Found along the way

**Batch 1's headline statistic was mislabelled.** Its "all cases, both judges"
(−0.481) is judge 2 overwriting judge 1 on double-judged cases, not a mean
(`../../aggregate.py`, per-case assignment inside the verdict loop). The true
mean-of-judges value is −0.4907, CI [−1.017, +0.036]. The verdict does not
change; the Batch-1 report should carry a correction when the evidence is
mirrored (METHOD §4).

## For the owner

Nothing in this addendum reopens the swap. `medium` is significantly worse
than the champion. `high` is the best flash operating point measured, but it is
not non-inferior (lower bound −0.79 against −0.10), it wins 4 of 9, and its
remaining deficit is prioritisation, which reasoning budget does not fix.
The only open lever is the one Batch 1 already named: a harvest test (execute
both plans, compare what comes back). A higher level alone does not change the
answer.
