# Backlog — bias_language stability redesign (split extract / judge)

**Status: OPEN — decided direction, not yet scheduled.** Evidence:
`docs/BIAS-STAGE-MODEL-EVAL-2026-07.md` (esp. §3 and §9 addendum) and
`docs/BIAS-LANGUAGE-MODEL-EVAL-2026-06-28.md`. This records *why* and *what*, so
the next person picking up the thread does not re-derive it.

## The problem (evidence)

The single-call *emit-then-retract* bias prompt produces a confirmed-span
verdict that is only **~half-stable across identical cache-cold runs — even for
the incumbent** Opus-4.6 (exact valid-span repeat-consistency **Jbar 0.510**;
soft 0.337; measured on 3 cold repeats × 5 varied in-window articles).

No model beats it on the same grid:

| arm | Jbar exact | mean valid | emitted / kept / retracted (15 calls) |
|---|---|---|---|
| **incumbent Opus-4.6** | **0.510** | 4.13 | 109 / 62 / 47 (43% retract) |
| Opus-4.8 (effort high) | 0.496 | 1.67 | 44 / 25 / 19 (43%) — ties only by under-extracting |
| Sonnet-5 (high) | 0.685 | 3.53 | 57 / 53 / 4 |
| GLM-5.2 (xhigh, fp8) | 0.798 | 1.33 | 23 / 20 / 3 |
| DeepSeek-V4-Pro (xhigh, fp8) | 0.800 | 0.87 | 13 / 13 / 0 |

The emission split shows **the churn lives in the retraction decision**: the
Opus family emits a generous candidate set and re-draws which ~43% survive on
each cold pass (externalized in `finding_valid`); the reasoning arms pre-filter
inside the reasoning trace (0–13% retract) and under-emit. So the instability is
a property of doing **candidate generation AND judgment in one stochastic pass**,
not of any particular model — and the metric partly measures prompt-design fit
rather than intrinsic determinism (see the eval §9 addendum).

## Decided direction — split the stage

Separate the two jobs into individually-more-deterministic pieces, per the
project's *deterministic-before-LLM* principle:

1. **Candidate extraction — recall, cheap, redundant.**
   Two cheap open-weight models each extract candidate bias spans (verbatim
   `excerpt` + proposed `issue`) from `article_body`. **Python takes the union**
   (dedup on normalized span) — a deterministic merge, no LLM counting, no LLM
   deciding what survives. Redundancy buys recall stability: a span *either*
   extractor surfaces becomes a candidate. The open-weight under-flagging failure
   mode is mitigated by union + by not asking either model to also judge; the
   extractor prompt must be tuned to **flag generously** (the opposite of
   today's lean single-call prompt).

2. **Per-candidate judgment — precision, Opus-4.6, closed questions.**
   Opus-4.6 judges each candidate span with **closed (yes/no) questions** — "is
   this the article's own voice (not attributed)?", "is the proposed category
   correct?", "is it data-backed / a direct quote / genuine uncertainty?" —
   instead of open-ended emit-then-retract. Closed, bounded decisions over a
   *fixed* candidate list are far more repeatable cold-to-cold than free-form
   generation, and they isolate the calibration decision from the extraction
   decision. Emits keep/drop + a **confidence** per span.

3. **Schema.** The **outer Topic Package schema is unchanged**; add a
   per-finding **`confidence`** field so borderline own-voice-verb spans carry a
   judged confidence instead of a brittle binary that flips cold-to-cold. Whether
   `confidence` surfaces in the TP or stays internal is a schema decision to be
   **surfaced for review, not drift** (contract discipline).

## Acceptance criterion

Accept the redesign only if it **beats the incumbent's 0.510 exact valid-span
repeat-consistency on the same 5-article × 3-cache-cold grid**
(`scratch/bias-eval/`, `harness.py` + `score_phase0.py`), at no worse Phase-1
blind quality and within a sane cost/latency envelope. The gate that matters is
**stability (Jbar), not median quality** — same discipline as the 2026-06-28
doc. Beating 0.51 is the whole point; a redesign that merely matches it is not
worth the added architecture.

## Open questions before scheduling

- **Judge cost.** Union of two generous extractors raises the candidate volume
  the judge processes → cost. Measure judge cost/latency on the 5-article grid
  before scaling to a full run.
- **Extractor pair.** GLM-5.2 + DeepSeek-V4-Pro (both fp8-pinned) are the obvious
  cheap pair, but they *under*-extract under today's prompt (13–23 spans / 15
  calls). Re-prompt for recall and re-measure extraction stability (recall union
  should be much steadier than the current single-pass verdict).
- **Does closed-question judgment actually stabilize?** Validate the core
  hypothesis (bounded yes/no over a fixed list < free-form emit-then-retract in
  cold-to-cold churn) on a small probe before committing to the full split.
- **`confidence` semantics** — threshold for render inclusion, visibility tier.

## Deprioritized / superseded (from the 2026-06-28 backlog)

- *Deterministic prune-turn* to cap over-flagging — moot; the current failure is
  under-flagging + verdict churn, not over-flagging.
- *passive_obscuring actor carry-over* — an independent prompt improvement, still
  worth a look, unrelated to this split.
