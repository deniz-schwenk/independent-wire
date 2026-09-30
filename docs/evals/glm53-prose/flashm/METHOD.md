# EVAL-GLM53-PROSE-STAGES addendum: arm F_M — method

## The arm

| | F_M |
|---|---|
| model | `z-ai/glm-5.3-flash` |
| provider | openrouter, pin `{"order": ["z-ai"], "allow_fallbacks": false}` |
| reasoning | `max` |
| temperature | **1.0** |
| top_p | **0.95** |
| max_tokens | 120000 (parity with the H / M arms) |
| structured output | `json_object` + local validation |

**`max` was verified on flash before the batch, and verified as a DISTINCT
level, not merely an accepted string.** A probe on one arithmetic prompt at the
same operating point:

| level | reasoning_tokens | completion | cost |
|---|--:|--:|--:|
| low | 132 | 401 | $0.000210 |
| high | 286 | 691 | $0.000355 |
| **max** | **1316** | **1690** | $0.000855 |

No 400, served by Z.AI, and the reasoning budget scales 10x from low to max — so
`max` is real on this model and the brief's stop-condition did not trigger. (This
check exists because LEVEL-AUDIT found `minimal` ≡ `low` on another family: an
accepted level name is not evidence of a distinct level.)

### top_p — an interpretation, stated

The brief specifies `temperature 1.0` and grounds it in two sources: docs.z.ai
"Recommended Settings" **and** "the production perspective_verify leg". Both of
those carry the PAIR temperature 1.0 / top_p 0.95 — `scripts/run.py`'s
`perspective_verify` sets both, with top_p going through
`extra_body_override` because `Agent` has no top_p parameter. Running
temperature alone would mirror neither cited source, so **F_M runs the pair**.
This is the one place where the arm's config was resolved by interpretation
rather than read literally off the brief, and it is flagged here because it is a
real configuration decision, not a formatting detail.

## What is held identical to Batch 1

Same four stages, same nine frozen production inputs (2026-09-06/07/08), same
prompts, schemas, tool config, same `max_tokens`, same `json_object` channel.
`flashm/harness.py` imports Batch 1's stage table and bus loaders rather than
re-deriving them, so a drift between the two batches' plumbing is impossible.

The frozen input copy was **re-verified byte-identical to production before use**
— 303 state files, 0 mismatches — so F_M and the Batch-1 arms demonstrably
consumed the same bytes.

A **bare `Agent`** is used, never a `*WithFallback` wrapper: a fallback serve
would silently substitute another model and invalidate the arm.

## Judging, and the drift control

- **Fresh sessions per stage containing C and F_M.** C is re-judged alongside
  F_M rather than having its Batch-1 scores reused. This is what makes the F_M
  delta comparable to the Batch-1 deltas: every delta in the combined table is
  paired against a C judged in its own session, so judge drift cancels inside
  each delta.
- **Raw absolute scores are never differenced across batches.** Only deltas are.
- **Drift is measured and reported**, per the brief: C's re-scores vs its
  Batch-1 scores, per stage, with CI.
- Blind: opaque `OUT-xxxxxx` ids from a NEW seed (`glm53-flashm-2026-09-12`) so
  nothing collides with Batch 1's keymap; keymap written pre-dispatch, stored one
  level above the case dirs. Verdict shape identical to Batch 1's.
- Ground truth is Batch 1's captured exact stage inputs (`inputs/*.txt`),
  read-only.
- Rubrics are Batch 1's, read-only, unchanged.
- **Honest-Detector**: all 19 cases carrying a fabrication charge were fully
  double-judged; a charge counts only when two independent judges cite an
  overlapping quote against the same output, decided deterministically in
  `confirm_charges.py`.
- Judges are spawned Opus-5 subagents. **Judging cost $0.00.**

## Read-only production

Batch-1 artifacts were read, never written; all F_M output lives under
`flashm/`. Production state hashed before and after (351 files);
`--reuse` never invoked.
