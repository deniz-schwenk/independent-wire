# TASK-EVAL-GLM53-PROSE-STAGES (Batch 1) — REPORT

Three-arm judged comparison on the four glm-5.2 prose stages over the frozen
production state of 2026-09-06 / 07 / 08.

- **C** = champion, live glm-5.2 production output, NOT re-generated ($0.00)
- **H** = `z-ai/glm-5.3` @ reasoning `high`
- **M** = `z-ai/glm-5.3` @ reasoning `max`

Method, blinding and rubric provenance: `reports/METHOD.md`.
Machine-readable results: `reports/aggregate.json`, `reports/charges.json`.

## Headline

| stage | n | verdict | margin (paired abs 1-5, vs C) |
|---|--:|---|---|
| `hydration_phase2` | 9 | **M** (H also beats C) | M **+1.333** CI [+1.001, +1.666]; H +0.778 CI [+0.499, +1.057] |
| `qa_analyze` | 9 | **M** (H also beats C) | M **+1.111** CI [+0.510, +1.712]; H +0.722 CI [+0.383, +1.061] |
| `writer` | 9 | **M** (H does NOT beat C) | M **+0.833** CI [+0.449, +1.218]; H −0.111 CI [−0.531, +0.309] |
| `editor` | **3** | **no discrimination — n=3** | M +0.167 CI [−0.551, +0.884]; H −0.167 CI [−2.064, +1.731] |

Every CI is a t-based 95% interval on the per-case paired delta. A verdict is
called only where the interval excludes zero.

**M wins three of four stages outright. H beats the champion on the two
analytical stages and is a wash on the writer. The editor is undecided at n=3
and cannot be decided by this batch.**

## Per-stage detail

### hydration_phase2 (n=9, 18 verdict files, all 9 cases double-judged)

| arm | absolute 1-5 | rubric pass-rate | mean rank | firsts | paired W/T/L vs C | confirmed fabrications |
|---|--:|--:|--:|--:|:--:|--:|
| C | 3.056 | 0.766 | 2.94 | 0/18 | — | **15** |
| H | 3.833 | 0.852 | 1.94 | 2/18 | 8/1/0 | 8 |
| M | **4.389** | **0.931** | **1.11** | 16/18 | **9/0/0** | **2** |

The cleanest result in the batch: M wins every single case and carries an order
of magnitude fewer confirmed fabrications than the incumbent. The champion's
weakness is the one the rubric was written around — divergences that name no
groups, and gaps that name as missing something the corpus does cover.

### qa_analyze (n=9, 11 verdict files, 2 charged cases double-judged)

| arm | absolute 1-5 | rubric pass-rate | mean rank | firsts | paired W/T/L vs C | confirmed fabrications |
|---|--:|--:|--:|--:|:--:|--:|
| C | 3.222 | 0.786 | 3.00 | 0/11 | — | 1 |
| H | 3.944 | 0.911 | 1.64 | 4/11 | 7/2/0 | **0** |
| M | **4.333** | 0.917 | **1.36** | 7/11 | 7/2/0 | 1 |

Both candidates beat the champion decisively and never lose a case. H and M are
close: M leads on absolute score, their pass-rates are within 0.006, and M's CI
is the wider of the two. Deterministically, glm-5.3 finds about **twice** as
many problems as the champion (H 5.1, M 6.7 vs C 2.8 per topic) and the judges
scored that as recall, not padding — the rubric's R1 penalises invented problems
explicitly, and the fabrication count did not rise with the problem count.

Correspondence invariants hold on **all 27 outputs, every arm**: R4
(`len(corrections) == len(problems)`) 27/27, R5 (corrected article present iff
some correction is needed) 27/27.

### writer (n=9, 16 verdict files, 7 charged cases double-judged)

| arm | absolute 1-5 | rubric pass-rate | mean rank | firsts | paired W/T/L vs C | confirmed fabrications |
|---|--:|--:|--:|--:|:--:|--:|
| C | 3.667 | 0.857 | 2.19 | 1/16 | — | 5 |
| H | 3.556 | 0.801 | 2.75 | 0/16 | 2/5/2 | 7 |
| M | **4.500** | **0.956** | **1.06** | 15/16 | 7/2/0 | **0** |

M is the strongest arm anywhere in the batch — 15 of 16 firsts, zero confirmed
fabrications across nine articles. **H is not an improvement here**: its CI
straddles zero, it takes zero firsts, and it is the only arm-stage pair in the
batch whose confirmed-fabrication count is *worse* than the champion's (7 vs 5).

Deterministic checks over all 27 articles:
- **Zero invented source ids** on every arm — every `[src-NNN]` resolves to a
  real id in that topic's `final_sources`.
- Length discipline (R8, 600-1200 words) is where glm-5.3 is worse, not better:
  over-length articles C **3/9**, H **4/9**, M **6/9**. Mean words C 1087,
  H 1180, M 1211. M buys its rubric win while breaking the length rule most
  often — the judges caught this (it is inside their R8 score) but a swap should
  expect longer articles.

### editor (n=3 — LOW STATISTICAL POWER, flagged per the brief)

| arm | absolute 1-5 | rubric pass-rate | mean rank | firsts | paired W/T/L vs C | confirmed fabrications |
|---|--:|--:|--:|--:|:--:|--:|
| C | 3.833 | 0.813 | 2.60 | 1/5 | — | 1 |
| H | 3.667 | 0.817 | 2.20 | 0/5 | 1/1/1 | 2 |
| M | 4.000 | 0.897 | 1.20 | 4/5 | 1/2/0 | 1 |

**No verdict.** The editor runs once per day, so three days give three
instances; both CIs span zero and H's is ±1.9 wide. M ranks first on 4 of 5
verdicts and leads pass-rate by 8 points, which is suggestive and nothing more.
All three arms were schema-valid on all three days, all produced 10 assignments
with a well-spread priority range.

## Cost and latency (measured, per stage instance)

| stage | C cost | H cost | M cost | C tok | H tok | M tok | H latency | M latency |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| `editor` | $0.0276 | $0.0261 | $0.0718 | 15086 | 10961 | 21338 | 80 s | 285 s |
| `hydration_phase2` | $0.0186 | $0.0362 | $0.1237 | 20138 | 20668 | 39124 | 59 s | 471 s |
| `writer` | $0.0427 | $0.0616 | $0.3256 | 41569 | 35477 | 95472 | 69 s | 992 s |
| `qa_analyze` | $0.1161 | $0.1422 | $0.2977 | 82421 | 75893 | 106323 | 233 s | 850 s |

**Per 3-topic production run, these four stages together:**
C $0.5678 → H $0.7458 (**+31%**) → M **$2.2949 (+304%)**.

The operational number the owner should weigh first is **latency**, not cost.
On the writer, M averages **16.5 minutes per topic** against the champion's
sub-minute-class call — 3 topics serially is roughly 50 minutes of added
wall-clock on that stage alone, and phase2 + qa add more. `max` is not a
drop-in operating point for a nightly runner without a schedule change.

## Verification and hygiene

- **60 candidate calls, 0 errors, 0 non-z-ai serves.** Every row in
  `logs/calls.jsonl` carries `model_used: z-ai/glm-5.3` and
  `provider_used: Z.AI`. No fallback wrapper was in the path.
- **API total $9.1776** against the $15 cap. Judging cost $0.00 (subagents).
- **Production state byte-identical**: 351 files under `output/2026-09-0{6,7,8}`
  hashed before and after; `prod_state_manifest.PRE.txt` and `.POST.txt` are
  identical. `--reuse` was never run.
- `git status` clean, on `main`, both before and after. No commits, no
  production file touched.
- **Inter-judge agreement** on double-judged cases (mean |j1−j2| on the absolute
  1-5): phase2 0.185 (exact 22/27), qa 0.167 (5/6), editor 0.167 (5/6), writer
  0.524 (exact 10/21, within-1 21/21). The writer is the noisiest surface and
  its verdict rests on a margin (+0.833) well outside that noise.
- **Honest-Detector**: every case carrying a fabrication charge was fully
  double-judged; 74 charges were raised across the batch and **41 confirmed**
  by two independent judges citing an overlapping claim. Confirmation is
  deterministic (`confirm_charges.py`), never model-adjudicated.

## Known limits of this batch

1. **Stage isolation cuts both ways.** Every QA arm analysed the CHAMPION's
   article, so a writer improvement cannot show up in the QA score, and a QA arm
   is never tested on the article a glm-5.3 writer would actually hand it.
2. **n=3 on the editor** is not fixable by re-judging; it needs more days.
3. **One judge per case except where a charge triggered the second.** Scores on
   singly-judged cases carry the drift of one draw; the fabrication counts do
   not, by construction.
4. Candidate arms run `json_object` + local validation because the Z.AI endpoint
   serves no strict `json_schema`. The champion ran strict schema. This is a
   channel difference that cannot be equalised, not an eval choice.
5. **One QA H call was paid for and lost** to a harness serialization bug before
   its metrics were written (nested pydantic models in `qa_corrections`). It was
   re-run after the fix. The $9.1776 tally therefore understates true spend by
   roughly one QA H call (~$0.11); the tally is what the ledger recorded.

## What a Batch 2 would have to settle (owner's call — NOT part of this task)

- **M vs H is only genuinely open on `qa_analyze`** (Δ 0.389, overlapping CIs,
  pass-rates 0.911 vs 0.917). On writer and phase2 the M-over-H gap is large and
  consistent; on the editor nothing is decided.
- If cost or latency rules `max` out, the honest reading is: **H is a real
  improvement on `qa_analyze` and `hydration_phase2` at +31% run cost, and is
  NOT an improvement on the writer.** Those two stages could move without the
  writer.
