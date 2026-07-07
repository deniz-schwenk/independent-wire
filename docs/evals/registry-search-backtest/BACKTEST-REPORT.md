# Registry backend — A3a backtest vs Sonar (2026-07-04/05/06)

_Generated 2026-07-06 07:39 UTC · $0, no LLM calls · registry code from worktree `/Users/denizschwenk/iw-registry-shadow-worktree` · production tree read-only._

## Direction verdict: **MIXED**

_Two clear wins (100%-dated vs Sonar's 32%; 90% language coverage) against two clear misses (breadth ratio 0.25 and 5% overlap, both well short of the ≥0.70 source-count gate). Strong where the registry is designed to win, weak on raw breadth vs whole-web search._

**Asymmetry caveat (why this is direction-grade, not gate-grade):** the registry fetches **now** against each feed's *rolling window* (~last 24–72h of items), while Sonar searched **then** against the *whole web* at run time. Older topics (07-04/05) are structurally disadvantaged for the registry — the then-fresh articles have already rolled out of the live feeds. The FRESH slice (07-06, age ≤ ~4h) is the least-unfair comparison; the time-fair read is the A3b prospective shadow.

## Aggregate gate-precursor numbers

| Metric | Value | Note |
|---|---|---|
| Source-count ratio (registry ÷ Sonar hosts), mean | **0.25** | fresh-slice 0.25; backlog gate ≥0.70 |
| Language coverage of Sonar's languages, mean | **90%** | backlog gate ≥90% primary region/language |
| Dated share — registry | **100%** | by construction (undated dropped) |
| Dated share — Sonar (dossier estimated_date), mean | **32%** | registry's structural advantage |
| Overlap (Sonar hosts also found by registry), mean | **5%** | fresh-slice 4% |

## Per-topic table

| Day | T | Topic | Age (h) | Sonar hosts | Reg hosts | Ratio | Overlap | Reg-only | Sonar dated | Reg undated dropped | Lang cov | Sonar langs | Reg wall |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|
| 07-04 | 0 | Russian strikes and Ukrainian countera | 50 | 96 | 23 | 0.24 | 6 | 17 | 53% | 130 | 100% | ar,en,fr,ru,uk | 130051ms |
| 07-04 | 1 | NATO summit convenes with divisions ov | 50 | 78 | 23 | 0.29 | 7 | 16 | 20% | 0 | 82% | de,el,en,es,fr,it,ko,ru,sv,tr,uk | 102952ms |
| 07-04 | 2 | Lebanon-Israel tensions escalate with  | 50 | 66 | 11 | 0.17 | 6 | 5 | 40% | 0 | 80% | ar,en,fa,fr,he | 110082ms |
| 07-05 | 0 | Russia-Ukraine war: Zelensky denies Ru | 26 | 79 | 20 | 0.25 | 1 | 19 | 33% | 0 | 89% | ar,en,fr,ko,pl,pt,ru,tr,uk | 118939ms |
| 07-05 | 1 | Iran holds funeral for slain Supreme L | 26 | 90 | 19 | 0.21 | 6 | 13 | 27% | 0 | 89% | ar,en,fa,hi,ko,pt,ru,tr,zh | 109714ms |
| 07-05 | 2 | Thousands protest in Germany against f | 26 | 62 | 19 | 0.31 | 3 | 16 | 33% | 0 | 100% | de,en,fr,it,ko,pl,ru,tr | 88798ms |
| 07-06 | 0 | Russia launches deadly missile and dro | 2 | 74 | 19 | 0.26 | 3 | 16 | 27% | 0 | 86% | en,fr,hi,pl,ru,tr,uk | 97833ms |
| 07-06 | 1 | NATO summit in Ankara: Trump to meet Z | 2 | 84 | 24 | 0.29 | 4 | 20 | 27% | 0 | 88% | ar,de,en,es,fa,ja,ko,tr | 114502ms |
| 07-06 | 2 | Venezuela earthquakes: death toll pass | 2 | 60 | 13 | 0.22 | 2 | 11 | 27% | 0 | 100% | ar,de,en,es,fr,pt,ru,sw,tr | 57470ms |

### Column notes
- **Sonar hosts** = unique domains parsed from the stored raw `results` strings (all queries); **Reg hosts** = unique domains of the registry's top-5-per-query delivered items (deduped). Both = 'what the search arm handed the assembler.'
- **Ratio** = Reg hosts ÷ Sonar hosts. Registry draws from a curated 83-feed pool, so <1.0 is expected; the question is whether it clears the ≥0.70 gate on the time-fair (fresh/shadow) comparison.
- **Overlap** = Sonar domains the registry also surfaced. **Reg-only** = domains registry found that Sonar did not.
- **Sonar dated** = share of dossier sources with a parseable `estimated_date`. **Reg undated dropped** = feed items excluded to keep the registry 100% dated. NOTE: the cross-topic feed cache attributes each feed's undated drops to the FIRST topic that fetched it (hence the count clusters on topic 0 = 130); read it as a per-backtest aggregate (~130 total), not per-topic. The 100%-dated guarantee on RETURNED items holds on every topic regardless.
- **Lang cov** = share of Sonar's dossier languages covered by the registry's selected outlets (catalog `languages` per domain). This is an outlet-capability measure, not per-article language — noted as a mild over-count.
- **Reg wall** = wall-clock for the topic's replay. Even with the feed cache warm, wall stays ~90–120s/topic → it is EMBEDDING-dominated, not fetch-dominated: each query re-embeds its full fetched pool (up to ~500 items). A per-item embedding cache (feeds are stable within a run) is the obvious optimization for production activation — out of scope here.

## Interpretation
- **Win:** registry is **100% dated** vs Sonar's 32% dossier dated share — decisive, on every topic.
- **Win:** language coverage averages **90%** — the curated pool's multilingual outlets cover ~the languages Sonar surfaced (meets the ≥90% gate).
- **Miss:** breadth (host ratio **0.25**) and overlap (**5%**) fall well short of the ≥0.70 source-count gate.
- **Structural, not temporal:** the breadth ratio is ~uniform across ages (fresh-slice 0.25 ≈ overall 0.25), so the gap is driven by the 83-feed curated-pool SIZE, not primarily by the fetch-now-vs-searched-then asymmetry. The A3b time-fair shadow will confirm, but do **not** expect the breadth gap to close with same-day timing.
- **Net:** strong where the registry is designed to win (dated, multilingual, $0, deterministic), weak on raw breadth vs a whole-web search — hence **MIXED**. The Phase-B decision hinges on whether the pipeline values 100%-dated curated retrieval over breadth.

_Wins: language_gate_met(>=90%), dated_decisive(reg100%_vs_sonar<50%) · Misses: breadth_miss(0.25<0.70), low_overlap(5%)._
