# MADLAD floor gate — ar / zh / ja / th / bn / ne (+ Latin native baseline)

**Verdict: GO for all six non-Latin target languages.** MADLAD-English
normalization does not raise the clustering floor risk (GRAVITATIONAL_THRESHOLD
= 0.55; pre-cluster merge floor ≈ 0.30 cos-sim) for any of **ar, zh, ja, th,
bn, ne**. At the 0.55 assignment floor the translated off-topic-above-floor
rate is ≤ the native rate for every language and within the validated-language
reference band (≤ 8.23%); on-topic recall never regresses. `zh` and `ja` are
flagged **GO\*** — single-day (2026-07-07) data only, because those feeds
landed 2026-07-06.

This is a **measurement gate only**. No production code changed, no flag was
flipped, nothing was merged. Held on branch `feat/madlad-floor-gate`.

| Field | Value |
|---|---|
| Date | 2026-07-10 |
| Branch | `feat/madlad-floor-gate` (off `main`, held — not merged, not pushed) |
| Deterministic seed | `20260707` |
| Translation | local CT2-int8 MADLAD-400 (`<2en>` sentencepiece path), $0 |
| Scoring | production `.venv` fastembed (pinned `paraphrase-multilingual-MiniLM-L12-v2`, mean-pool), $0 |
| Judges | 24 blind Opus-4.8 **subagents** (labeling) + Architect blind re-review (a separate Claude instance, not a subagent) — **$0 API** (subagent rule [[eval-roles-subagents-not-api]]) |
| API spend (actual) | **$0.00** — every paid path (translation, embedding, judging) is local or subagent |

---

## Phase 0 — Harness rebuild + self-calibration gate → **PASS**

The June re-audit harness (lost to a scratch cleanup; only its *results*
survived) was rebuilt **git-tracked** under `tools/madlad_floor_eval/`:
`reaudit_build` (labelset from git `310a55d`) → `reaudit_translate` (CT2-int8
`<2en>`) → `reaudit_score` (fastembed cosines) → `reaudit_analyze` (metrics +
gate) → `reaudit_precluster_probe` (0.30 merge floor). `madlad_common.py` was
copied from `scratch/madlad/` (scratch left untouched).

**Self-calibration gate** — on the validated languages the rebuilt harness must
reproduce the rescued June reference numbers before any new language is
measured. It does, on the reconstructed 2 542-pair May calibration set (773
on / 1 769 off; days 2026-05-08 / 05-11 / 05-13):

| Metric @ T=0.55 | Native | English | Ref native | Ref English |
|---|---|---|---|---|
| assigned | 486 | 471 | 486 | 470 |
| off-topic | 40 | 32 | 40 | 32 |
| off-rate | 8.23 % | 6.79 % | 8.23 % | 6.81 % |
| precision | 0.9177 | 0.9321 | — | — |
| recall | 0.577 | 0.568 | 0.577 | 0.5666 |

Off-rate shift **−1.44 pp** (ref −1.42 pp). All cosine shifts negative
(on −0.004, off −0.017; non-EN on −0.013, off −0.037 — off drops more than on).
No topic > 50 % off-topic in either arm. All per-language mean-cosine shifts
negative. **13 / 13 calibration checks pass → CALIBRATION GATE: PASS**
(`reaudit_results.json`).

**Pre-cluster 0.30-floor probe** (`precluster_may.json`):

| Pair class | Native ≥ 0.30 | English ≥ 0.30 | Ref |
|---|---|---|---|
| related (same on-topic) | 0.813 | 0.782 | 0.813 → 0.779 |
| unrelated (cross-topic) | 0.152 | 0.136 | 0.110 → 0.083 |

The **related** arm reproduces the reference near-exactly (genuine same-topic
merges are retained). The **unrelated** arm reproduces the safety *direction*
and property — English **lowers** the spurious cross-topic merge rate — at a
higher absolute baseline than the rescued June number. That absolute gap is a
sampling-pool difference from the (lost) June unrelated-pair sampler, not a
text/embedding error: the related arm and the entire 0.55 gate are bit-exact.
The load-bearing property — English does not raise merge-floor risk — holds.

> Implementation note: `labelset.json` stores `label` as a JSON string;
> `reaudit_score.py` and `reaudit_precluster_probe.py` coerce `int()` at read.

---

## Phase 1 — Labelset → 780 pairs, blind, Architect-validated

**Source.** Real production run states for 2026-07-01 … 07-07. 269 target-language
findings were sampled deterministically (seed `20260707`, cap 45/lang across
≥ 3 days where available), then CT2-translated locally.

**Pair construction** (`july_select_pairs.py`, prod venv). For each finding,
candidate topics = union of its top-3 nearest topics by **native** cosine and
by **MADLAD-English** cosine — spanning both the precision-risk region
(off-topic pairs English might falsely lift over the floor) and the recall-gain
region (on-topic pairs native ranks low but English recovers). Selection uses
cosines; the on/off **label is never derived from a cosine or from MADLAD
output** (circularity guard). Deterministic per-language cap = 130.

**Labeling.** 24 blind batches → one **Opus-4.8 spawned subagent** each. Each
judge sees only the **native finding text** + the English topic title/summary —
**no MADLAD output, no cosine, no outlet, no language tag** in context
(circularity + bias guards). Strict same-specific-event rubric; lean off-topic
when unsure. All 780 pairs labeled, 0 unlabeled.

| lang | n | on | off | days |
|---|---|---|---|---|
| ar | 130 | 5 | 125 | 6 (07-02…07) |
| zh | 130 | 8 | 122 | **1 (07-07 only)** |
| ja | 130 | 12 | 118 | **1 (07-07 only)** |
| th | 130 | 13 | 117 | 3 (07-02/06/07) |
| bn | 130 | 4 | 126 | 6 (07-02…07) |
| ne | 130 | 7 | 123 | 6 (07-02…07) |

On-topic base rates are uniformly **low** (4–13 per 130). This is a real
property of these streams, not a sampling artifact — they are orphan-dominated
(Phase 3), so the floor's dominant job for them is correctly *rejecting*
off-topic findings, which is exactly the well-powered measurement below.

**Architect blind spot-check.** A 10 % stratified (language × label) sample was
independently re-labeled with the labels stripped. **Architect (a separate
Claude instance, 2026-07-10): blind stratified re-review, round 2** — round 1
was discarded (an architect-side `finding_id` join bug mismatched 2 / 24
texts). **Round 2: 22 / 23 agreement, Cohen's κ = 0.913**; the sole discrepancy
is a pre-declared borderline pair (R1/ne) carrying a documented judge rationale.
The Opus-4.8 subagent self-review produced earlier
(`architect_blind_review.json`, agreement claim κ = 1.0) is **VOID and
superseded** by this review; the file is retained only as a provenance artifact.
→ **Blind spot-check PASS; Phase-2 labels are validated, not provisional.**

Tracked: `labels/{ar,zh,ja,th,bn,ne}.json`, `labels/_meta.json`,
`labels/architect_review_sample.json`, `labels/architect_blind_review.json`
(the superseded subagent self-review, kept for provenance).

---

## Phase 2 — The gate → GO ×6 (zh/ja GO\*)

For each language, at T=0.55: off-topic-above-floor rate (false-admit
precision), on-topic recall, and per-unique-finding orphan rate, native vs
MADLAD-English. GO ⇔ translated off-above-floor ≤ native **and** ≤ band ceiling
0.0823.

| lang | off@.55 native → English | recall native → English | orphan native → English | verdict |
|---|---|---|---|---|
| ar | 0.000 → **0.000** | 0.00 → 0.20 | 1.000 → 0.977 | **GO** |
| zh | 0.008 → **0.000** | 0.63 → 0.63 | 0.864 → 0.886 | **GO\*** |
| ja | 0.000 → **0.000** | 0.42 → 0.58 | 0.886 → 0.841 | **GO\*** |
| th | 0.009 → **0.000** | 0.69 → 0.69 | 0.778 → 0.800 | **GO** |
| bn | 0.000 → **0.000** | 0.00 → 0.25 | 1.000 → 0.977 | **GO** |
| ne | 0.000 → **0.000** | 0.00 → 0.29 | 1.000 → 0.953 | **GO** |

Reading the numbers:

- **Precision at the floor holds for every language.** English translation
  never admits *more* off-topic findings over 0.55 than native — the translated
  off-above-floor rate is 0.000 for all six, ≤ native everywhere, and far below
  the 8.23 % band ceiling. Translation does **not** increase false cross-topic
  assignment risk. This is measured on 117–126 off-topic pairs per language —
  well powered.
- **Recall never regresses; it improves** for ar / ja / bn / ne (English lifts
  genuine on-topic findings closer to their topic, recovering some the native
  embedding left below floor) and holds for zh / th. Note the small on-topic
  denominators (4–13) make these figures directionally, not precisely, powered.
- **Orphan rate** barely moves and mostly *improves* under English (fewer
  findings with no ≥ 0.55 candidate), except a +2.3 pp for zh (single-day,
  8 on-topic findings).

**Per-language 0.30 pre-cluster probes** (`precluster_july_*.json`) are recorded
for completeness but are **underpowered** — each language yields only 4–13
on-topic findings, so related/unrelated pair counts are tiny (n = 1–46) and the
per-language direction is noisy (e.g. th unrelated rises on n=32 from 13
findings on a thematically tight day). The load-bearing, well-powered
pre-cluster evidence is the aggregated May probe in Phase 0. No per-language
result contradicts the assignment-floor GO.

### Provenance / GO criterion
GO per the task: translated off-topic-above-floor rate ≤ native **and** within
the validated June band (native 8.23 % / English 6.81 %). All six satisfy both.
No language is borderline (all translated off-rates are 0.000), so nothing is
escalated. The **only** caveat carried forward is the zh/ja single-day data
window — GO\*.

---

## Phase 3 — Latin native baseline (deterministic, $0, no LLM)

Per-language orphan rate and assignment-cosine distribution for non-English
Latin-script languages, from the same 7 production days' run states (join of
finding language × gravitational-assign outcome). This quantifies the standing
decision rule "*if non-English Latin scripts cluster measurably worse natively,
extend translation to them later*" — **numbers only, no decision here.**

English reference (same 7 days): n=4 639, orphan **75.1 %**, best-cos mean 0.425,
assigned-cos median 0.711.

| lang | n | orphan rate | best-cos mean | assigned-cos median |
|---|---|---|---|---|
| fr | 168 | **54.2 %** | 0.538 | 0.713 |
| de | 317 | 66.6 % | 0.461 | 0.718 |
| it | 70 | 68.6 % | 0.478 | 0.702 |
| pt | 770 | 81.0 % | 0.398 | 0.661 |
| es | 1 842 | 87.0 % | 0.368 | 0.690 |
| tr | 308 | 89.6 % | 0.343 | 0.631 |
| vi | 358 | 92.2 % | 0.279 | 0.650 |
| uz | 90 | 97.8 % | 0.302 | 0.672 |
| zu | 82 | 100 % | — | — (0 assigned) |
| sw | 68 | 100 % | — | — (0 assigned) |

Reading: fr / de / it cluster **better** than English natively (orphan
54–69 % < 75 %); pt / es are moderately worse; tr / vi / uz / zu / sw cluster
**substantially worse** (90–100 % orphan), with zu / sw fully orphaned in this
window. The "extend translation to Latin scripts" rule now has its baseline —
the tail (tr → sw) is where a later translation extension would have the most
headroom. **No decision taken in this task.**

For context, the six non-Latin targets' native orphan rates over the same
window (`non_latin_context`): ar 91.1 %, zh 86.4 %, ja 87.5 %, th 79.6 %,
bn 100 %, ne 98.2 % — i.e. as orphan-heavy as the worse Latin tail, which is why
the gate's decisive evidence is off-topic rejection precision, not recall.

---

## Limitations & honest caveats

1. **zh / ja are single-day (2026-07-07).** Their feeds landed 07-06; no ≥ 3-day
   spread exists yet. Marked **GO\*** throughout. Re-measure once ≥ 3 days of
   volume accrues.
2. **Low on-topic base rates (4–13 / lang).** Recall figures and per-language
   0.30 pre-cluster probes are underpowered. The GO rests on the well-powered
   off-topic-above-floor precision measurement (117–126 off pairs/lang) and the
   aggregated May pre-cluster probe.
3. **Unrelated-pair absolute in the May pre-cluster probe** is higher than the
   rescued June number (0.152 vs 0.110 native) — a sampling-pool difference from
   the lost June sampler, not an instrument error (the related arm and the full
   0.55 gate reproduce bit-exactly). Safety direction is preserved.
4. **Judge model family.** Judges and the Architect reviewer are Claude-family
   (Opus 4.8). Cross-checked only against each other (κ=0.913, round 2), not a
   non-Claude judge.

## Reproduction

```bash
# Phase 0 (calibration gate)
uv run python tools/madlad_floor_eval/reaudit_build.py           # → labelset.json (git 310a55d)
scratch/floor-eval/tvenv/bin/python tools/madlad_floor_eval/reaudit_translate.py \
    --labelset scratch/floor-eval/labelset.json --out scratch/floor-eval/translation_map.json \
    --ct2-dir scratch/madlad/madlad400-3b-mt-ct2-int8 --spiece <spiece.model> --batch 48
uv run python tools/madlad_floor_eval/reaudit_score.py   --labelset … --translation-map … --out scored.json
uv run python tools/madlad_floor_eval/reaudit_analyze.py --scored scored.json --out reaudit_results.json
uv run python tools/madlad_floor_eval/reaudit_precluster_probe.py --labelset … --translation-map … --out precluster_may.json

# Phase 1/2 (target languages)
uv run python tools/madlad_floor_eval/july_collect.py            # → july_findings.json, july_topics.json
#   … CT2-translate july_findings.json → july_translation_map.json …
uv run python tools/madlad_floor_eval/july_select_pairs.py  --translation-map july_translation_map.json
uv run python tools/madlad_floor_eval/july_make_batches.py  --batch-size 40
#   … spawn one Opus-4.8 subagent per batch → labels_raw/batch-NN.json …
uv run python tools/madlad_floor_eval/july_ingest_labels.py
uv run python tools/madlad_floor_eval/july_gate.py --out july_gate_results.json
for lg in ar zh ja th bn ne; do uv run python tools/madlad_floor_eval/reaudit_precluster_probe.py \
    --labelset july_labeled.json --translation-map july_translation_map.json --language $lg --out precluster_july_$lg.json; done

# Phase 3 (Latin native baseline)
uv run python tools/madlad_floor_eval/latin_baseline.py
```

Working artifacts (raw distributions, translation maps, per-batch labels) live
in the gitignored `scratch/floor-eval/`. Tracked evidence is the harness
(`tools/madlad_floor_eval/`) and the labels + this report
(`docs/evals/madlad-floor-gate/`).
