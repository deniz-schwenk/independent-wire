# Bias stage split — stability re-measurement (DECISIVE GATE)

**Verdict: STOP + REPORT for Architect decision.** `Jbar_exact = 0.406` falls in
the `(0.35, 0.51]` band defined by TASK-BIAS-STAGE-SPLIT: the composite **beats
the incumbent** single-call Opus-4.6 (0.510) but does **not** clear the ≤ 0.35
acceptance target. Per the task, work stops here; the prompts are authoritative
(commit-never-edit) so this is an Architect prompt/architecture decision, not a
tuning loop.

## The same 5-article × 3-cache-cold grid, against the new composite

| article | confirmed (r0,r1,r2) | Jexact | Jsoft |
|---|---|---|---|
| 2026-06-13#0 (Pope/Spain) | 2, 0, 1 | 0.83 | 0.83 |
| 2026-06-17#1 (Bolsonaro) | 0, 0, 0 | 0.00 | 0.00 |
| 2026-06-02#2 (Anthropic IPO) | 0, 0, 0 | 0.00 | 0.00 |
| 2026-06-22#2 (DRC Ebola) | 2, 3, 3 | 0.53 | 0.22 |
| 2026-06-20#0 (US-Iran/Hezb) | 1, 0, 0 | 0.67 | 0.67 |

- **Jbar_exact = 0.406** (incumbent 0.510) · **Jbar_soft = 0.344** (incumbent 0.337)
- **mean confirmed / article = 0.80** (incumbent 4.13)
- **mean $ / composite run = $0.0705** (target ≤ $0.06)
- extractor served Baidu fp8 (both passes), judge served Anthropic; deterministic
  layer clean (verbatim-substring validation dropping 1–3 invalid spans/run;
  union 20–33 candidates/article).

## Reading it (for the Architect)

1. **The split works directionally** — cross-run churn drops 0.510 → 0.406, and
   the extract+union layer is deterministic by construction (the instability is
   no longer in candidate generation). But the residual churn now lives in the
   **judge's confirm/clear decision**: on the three articles where the judge
   confirms anything (06-13, 06-22, 06-20) it still churns 0.53–0.83 cold-to-cold
   — the closed-question judgment did not fully stabilize the borderline
   own-voice calls.
2. **Coverage collapsed** — mean confirmed 0.80/article vs the incumbent's 4.13,
   with 2 of 5 articles stable-**zero** (0/0/0). Those zeros are what pull Jbar
   under 0.51; they are *stable* but represent a near-empty bias card. The judge
   prompt ("the prose is deliberately restrained… confirm only when the pattern
   clearly holds… borderline → false") is confirming almost nothing. Whether
   that lean rate is desirable (high precision) or a coverage regression is a
   product call — and would need Phase-1 quality judging to settle, not the
   stability gate.
3. **Cost** is slightly over target ($0.0705 vs $0.06), driven by the judge
   processing 20–33 candidates/article; a lower extractor candidate cap would
   trade recall for cost.

## Options for the Architect (no code/prompt changed beyond the committed split)

- **Accept 0.406** as a real improvement over the incumbent despite missing 0.35,
  and treat the coverage drop as acceptable precision — then run Phase-1 quality.
- **Revisit the judge prompt** (authoritative, so an Architect edit): the
  confirm-rate is the lever for both the residual churn and the coverage
  collapse; a less-restrained confirm threshold may raise coverage but could
  re-introduce churn.
- **Extractor cap / union tuning** for the cost target.

Reproduce: `uv run python scratch/bias-eval/composite_grid.py run 5` then
`… score`. Raw: `scratch/bias-eval/composite_raw.jsonl`; scored:
`scratch/bias-eval/composite_gate.json`.
