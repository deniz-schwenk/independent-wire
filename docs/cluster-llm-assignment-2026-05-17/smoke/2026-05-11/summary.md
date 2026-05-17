# Cluster-LLM-assignment smoke — 2026-05-11

Three runs of `AssignClustersStage` at temperature 1.0 against the fixed `audit-2026-05-16` topic-set (15 topics) and the cached `curator_pre_clusters` (241 clusters).

## Per-run table

| Run | Wall (s) | Cost (USD) | Tokens | Clusters in | Assigned | Orphan | Multi-asg | Findings assigned | Orphan findings |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 68.0 | $0.0384 | 74,059 | 241 | 15 | 226 | 1 | 356 | 845 |
| 2 | 67.6 | $0.0388 | 74,195 | 241 | 19 | 222 | 1 | 381 | 820 |
| 3 | 67.2 | $0.0075 | 74,210 | 241 | 22 | 219 | 1 | 392 | 809 |

## Per-day spread across 3 runs

| Metric | Mean | Min | Max | Spread (max - min) |
|---|---:|---:|---:|---:|
| Wall (s) | 67.591 | 67.22 | 67.964 | 0.7439999999999998 |
| Cost (USD) | 0.028 | 0.00753545 | 0.038765 | 0.031229550000000002 |
| Clusters assigned | 18.667 | 15 | 22 | 7 |
| Clusters orphan | 222.333 | 219 | 226 | 7 |
| Multi-assignments | 1 | 1 | 1 | 0 |
| Findings assigned | 376.333 | 356 | 392 | 36 |
| Orphan findings | 824.667 | 809 | 845 | 36 |

## Topic-level cluster-set stability (Jaccard across runs)

For each topic, the assigned cluster set per run is compared pairwise; mean and min Jaccard across the 3 pairs are reported. 1.0 = identical cluster set across all 3 runs.

| # | Topic title (truncated) | Per-run cluster counts | Jaccard mean | Jaccard min |
|---:|---|---|---:|---:|
| 0 | Russia and Ukraine accuse each other of violating US-brokere | 1/2/2 | 0.667 | 0.500 |
| 1 | Donald Trump rejects Iran's response to US peace proposal as | 1/3/2 | 0.500 | 0.333 |
| 2 | Vladimir Putin proposes Gerhard Schröder as mediator for Ukr | 1/1/1 | 1.000 | 1.000 |
| 3 | South Korean vessel damaged by explosion in the Strait of Ho | 2/3/3 | 0.778 | 0.667 |
| 4 | Hantavirus outbreak on MV Hondius cruise ship triggers inter | 1/1/1 | 1.000 | 1.000 |
| 5 | Emmanuel Macron visits Kenya for Africa Forward economic sum | 1/1/2 | 0.667 | 0.500 |
| 6 | Donald Trump prepares for state visit to China amid trade te | 1/1/2 | 0.667 | 0.500 |
| 7 | Narges Mohammadi released from Iranian prison for medical tr | 1/1/1 | 1.000 | 1.000 |
| 8 | Latvian Defense Minister resigns following Ukrainian drone i | 1/2/1 | 0.667 | 0.500 |
| 9 | Barcelona wins La Liga title after victory over Real Madrid | 1/0/1 | 0.333 | 0.000 |
| 10 | Keir Starmer faces leadership challenge following UK local e | 1/1/1 | 1.000 | 1.000 |
| 11 | Chad military airstrikes against jihadists reportedly cause  | 1/1/1 | 1.000 | 1.000 |
| 12 | Narendra Modi urges Indians to reduce fuel and gold consumpt | 1/1/3 | 0.556 | 0.333 |
| 13 | Sara Duterte impeached by Philippine lawmakers for a second  | 1/1/1 | 1.000 | 1.000 |
| 14 | Gaza documentary wins BAFTA award after being rejected by th | 1/1/1 | 1.000 | 1.000 |

**Day aggregates:** mean-across-topics of `jaccard_mean` = **0.789**; mean-across-topics of `jaccard_min` = **0.689**.
