# Bias dedup fix — stability re-measurement (DECISIVE GATE, round 2)

**Verdict: STOP + REPORT.** `Jbar_exact = 0.411` is still in the `(0.35, 0.51]`
band — the composite beats the single-call incumbent (0.510) but does not clear
the ≤ 0.35 target. Per TASK-BIAS-DEDUP-FIX: *"If still in (0.35, 0.51]: STOP and
report — the three-tier judge change lands next either way."*

## What changed in this round (TASK-BIAS-DEDUP-FIX)

1. **Position-anchored variant merge** replaced string-containment dedup in the
   union step. Each validated excerpt is resolved to its character interval(s);
   two candidates merge into one family **only** when their intervals overlap at
   the same location (nesting or partial overlap). No string-similarity merging —
   a multi-occurrence excerpt is location-ambiguous and never merges, so an
   `ongoing defiance` inside `no ongoing defiance` cannot collapse an affirmed
   `ongoing defiance in some localities` elsewhere. The family presents its
   shortest variant to the judge (killing the long/short oscillation that the
   Architect identified as the artifact).
2. **Extractor cap 25 → 18** per pass (deterministic, prompt untouched).

## The same 5-article × 3-cache-cold grid, post-fix

| article | confirmed (r0,r1,r2) | Jexact | Jsoft |
|---|---|---|---|
| 2026-06-13#0 (Pope/Spain) | 1, 0, 0 | 0.67 | 0.67 |
| 2026-06-17#1 (Bolsonaro) | 0, 0, 0 | 0.00 | 0.00 |
| 2026-06-02#2 (Anthropic IPO) | 0, 1, 0 | 0.67 | 0.67 |
| 2026-06-22#2 (DRC Ebola) | 1, 2, 2 | 0.72 | 0.72 |
| 2026-06-20#0 (US-Iran/Hezb) | 0, 0, 0 | 0.00 | 0.00 |

- **Jbar_exact = 0.411** (soft 0.411) — vs pre-fix 0.406, vs incumbent 0.510
- **mean confirmed / article = 0.47** (pre-fix 0.80; incumbent 4.13)
- **mean $ / composite run = $0.0648** (pre-fix $0.0705; target ≤ $0.06)
- union size dropped to **16–24 candidates/article** (pre-fix 20–33); invalid-span
  drops 0–3/run; extractor served Baidu fp8 both passes, judge served Anthropic.

## Reading it (for the Architect)

1. **The dedup fix worked as designed but was not the load-bearing lever.** The
   union is smaller and cleaner (16–24 vs 20–33; span variants now collapse by
   location, so the long/short oscillation is gone), yet `Jbar` is flat
   (0.406 → 0.411). The residual churn simply moved: 06-13 and 06-20 got *more*
   stable (both now stable-zero), while 06-22 (Ebola) got *less* stable
   (0.53 → 0.72). Net wash.
2. **The instability is now unambiguously judge-side.** With candidate generation
   deterministic and variants merged, the only remaining source of cross-run
   churn is the judge's binary confirm/clear decision on borderline own-voice
   calls. On the three articles where it confirms anything it churns 0.67–0.72
   cold-to-cold. This is exactly the case the three-tier judge (confirmed /
   borderline / cleared) is meant to address — a binary judge is forced to flip
   a genuinely contestable call to one pole or the other, and it flips
   differently each cold run.
3. **Coverage fell further** (0.80 → 0.47 mean confirmed; 3/5 articles now
   stable-zero). The extractor cap + the restrained judge prompt together push
   the confirm rate down. Whether that is high precision or a coverage
   regression is a Phase-1 quality question, not a stability question.
4. **Cost is close but marginally over** ($0.0648 vs $0.06). The extractor cap
   bounds each pass to 18, but the judge still sees the *union* of two 18-lists
   (16–24 after merge). Capping the union (judge input) rather than each pass is
   the remaining cost lever, deferred with the three-tier judge work.

## Decision surface

The dedup fix is a real, low-risk improvement (cleaner union, negation-safe,
cheaper, variant oscillation removed) and is committed on `feat/bias-stage-split`.
It does not by itself clear the gate. The next lever is the three-tier judge
(staged, out of scope for this task) — the binary judge is the dominant residual
instability.

Reproduce: `rm -rf scratch/bias-eval/raw_composite && uv run python
scratch/bias-eval/composite_grid.py run 5 && … score`. Raw cells:
`scratch/bias-eval/raw_composite/`; scored: `scratch/bias-eval/composite_gate.json`.
Pre-fix baseline: `scratch/bias-eval/COMPOSITE-STABILITY-RESULT.md`.
