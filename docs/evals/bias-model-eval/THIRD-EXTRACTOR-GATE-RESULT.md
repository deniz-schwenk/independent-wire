# Third extractor — Gate re-run (TASK-BIAS-THIRD-EXTRACTOR)

**Verdict: HARD gate PASS — zero full flips.** Recall hardened to three
extraction passes; the dual-judge aggregate stability holds and presence
stability improves as expected.

## Grid (5-article × 3-cache-cold), three extractors + dual judge

| article | confirmed (r0,r1,r2) | borderline | flips | presence |
|---|---|---|---|---|
| 06-13#0 Pope | 0,1,0 | 2,3,5 | 0 | 1/1 |
| 06-17#1 Bolsonaro | 0,0,0 | 1,5,4 | 0 | 0/0 |
| 06-02#2 Anthropic | 0,0,0 | 4,3,3 | 0 | 0/0 |
| 06-22#2 Ebola | 0,3,1 | 4,3,3 | 0 | 1/3 |
| 06-20#0 US-Iran | 0,0,1 | 2,2,1 | 0 | 0/1 |

- **HARD — full flips (confirmed↔cleared, aggregate) = 0** → **PASS**
- **PRIMARY — presence stability = 2/5** (up from **0/3** at two extractors)
- confirmed-set Jbar 0.467 (informational; sparse)
- mean confirmed 0.40/article · mean borderline 3.00/article
- **mean $ 0.1432/run** (3 extractors + 2 judges) — within the ≤ $0.15 budget

## Reading it

The third pass is pure recall insurance: a p=0.8 candidate's miss probability
across passes drops ~4% (two) → ~1% (three), and `extraction_confidence` is now
`K/3` (3/3, 2/3, 1/3). The stability guarantee is unchanged — still zero
confirmed↔cleared full flips, because the tier is still assigned by Python from
the two judge votes, not by the extractor. Presence stability rose 0/3 → 2/5:
wider surfacing means a confirmed family is more often re-surfaced (as confirmed
or borderline) across cold runs rather than being absent. Borderline mass grew
(mean 3.00/article) — the honest gray zone absorbs the extra recall. Cost is at
$0.143, just inside the $0.15 ceiling.

Landed directly on main per the brief (recall hardening for the once-per-article
production path). Reproduce: `rm -rf scratch/bias-eval/raw_composite && uv run
python scratch/bias-eval/composite_grid.py run 5 && … scorev3`.
