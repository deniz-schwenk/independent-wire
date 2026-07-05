# BACKLOG — Evidence-anchoring for `hydration_aggregator_phase2` (structural fabrication guard)

Status: DIAGNOSED, not activated. Written 2026-07-05 (Architect), same day the GLM-5.2 swap
landed (`41b8e76`). Activation gate below.

## Problem
The Phase-2 reducer fabricates divergences: contrasts between sources that the Phase-1
analyses do not support. Measured in the 2026-07 model eval (21 topics, 3 Opus-4.8 judges,
verbatim-citation standard): incumbent Opus-4.6 fabricated on 10/21 topics (14 findings);
the new primary GLM-5.2 halves this (8 findings on 7 topics) but does not eliminate it.
For this product an invented divergence is the worst error class — it lands directly in the
transparency story. Ref: `docs/HYDRATION-P2-MODEL-EVAL-2026-07.md` (on branch
`eval/hydration-p2-model-eval`, pushed).

## Design (deterministic-before-LLM; declaration order is load-bearing)
Restructure the divergence output so evidence is declared BEFORE the verdict, then verify it
in Python. Per divergence, per side:
- the Phase-1 chunk/article IDs the side rests on, and
- one short verbatim quote per side, copied from the Phase-1 text.

Python then validates deterministically (zero LLM cost):
1. Cited IDs exist in `hydration_phase1_analyses` and the two sides belong to different
   sources/groups.
2. Each quote fuzzy-matches its cited Phase-1 text (normalized token-overlap or
   partial-ratio; threshold to be gated empirically, start ~85 and tune on real misses).
3. Divergences failing verification are dropped or marked `unverified` (never silently
   rewritten) — the counts go to the stage log (`anchored_ok`, `anchored_dropped`,
   `anchored_unverified`).

Why this kills the failure mode: a fabricated divergence cannot produce a real quote — the
string match fails and Python catches it pre-publication. This moves the eval judges'
citation test into the pipeline itself.

## Escalation ladder (only if residual fabrications remain after anchoring)
1. Bias-detector-style composite: 2x extraction, Python union over position IDs,
   2/2 = confirmed, singles = borderline. Proven pattern (bias_language), ~$0.02 extra,
   but adds a seam — do not pull early.
2. Candidate pre-computation: Python derives candidate contrasts from Phase-1 data
   (alias-resolved actor overlap across chunks); the model verifies instead of freely
   associating. Cleanest conceptually, biggest rebuild. Last resort.

## Activation gate
- At least 3 clean production days on GLM-5.2 primary first (baseline for before/after
  comparison; swap active from the 2026-07-06 06:00 run).
- Then: PE brief (schema-shaped INSTRUCTIONS change: evidence fields BEFORE the verdict
  field in the divergence object — mirrors the judge-schema lesson) + CC task (schema in
  the output_schema, Python verifier, stage-log counters, unit tests on synthetic
  fabrications, stage-isolated smoke with `--reuse`).
- Success criterion for the smoke/gate: known-good divergences pass ≥95%; a synthetic
  fabricated divergence is caught 100%; report how many real divergences per topic land
  in `unverified` (if >~20%, the threshold is too tight — tune before landing).

## Cost
Verification itself: $0 (pure Python). Slight token increase from the evidence fields
(quotes are short); expected well under +20% of the stage's ~$0.02/topic.
