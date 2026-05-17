# Cluster-LLM-assignment smoke — 2026-05-13

Three runs of `AssignClustersStage` at temperature 1.0 against the fixed `audit-2026-05-16` topic-set (18 topics) and the cached `curator_pre_clusters` (279 clusters).

## Per-run table

| Run | Wall (s) | Cost (USD) | Tokens | Clusters in | Assigned | Orphan | Multi-asg | Findings assigned | Orphan findings |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 75.8 | $0.0473 | 91,924 | 279 | 23 | 256 | 0 | 501 | 904 |
| 2 | 75.9 | $0.0073 | 92,107 | 279 | 31 | 248 | 1 | 514 | 891 |
| 3 | 73.2 | $0.0484 | 92,305 | 279 | 26 | 253 | 0 | 516 | 889 |

## Per-day spread across 3 runs

| Metric | Mean | Min | Max | Spread (max - min) |
|---|---:|---:|---:|---:|
| Wall (s) | 74.969 | 73.213 | 75.929 | 2.716000000000008 |
| Cost (USD) | 0.034 | 0.0073427 | 0.048425 | 0.0410823 |
| Clusters assigned | 26.667 | 23 | 31 | 8 |
| Clusters orphan | 252.333 | 248 | 256 | 8 |
| Multi-assignments | 0.333 | 0 | 1 | 1 |
| Findings assigned | 510.333 | 501 | 516 | 15 |
| Orphan findings | 894.667 | 889 | 904 | 15 |

## Topic-level cluster-set stability (Jaccard across runs)

For each topic, the assigned cluster set per run is compared pairwise; mean and min Jaccard across the 3 pairs are reported. 1.0 = identical cluster set across all 3 runs.

| # | Topic title (truncated) | Per-run cluster counts | Jaccard mean | Jaccard min |
|---:|---|---|---:|---:|
| 0 | Escalating costs and military risks threaten Middle East tru | 3/1/1 | 0.556 | 0.333 |
| 1 | Ukraine and Russia exchange long-range drone strikes on ener | 1/3/1 | 0.556 | 0.333 |
| 2 | Donald Trump arrives in China for high-stakes summit with Xi | 1/1/1 | 1.000 | 1.000 |
| 3 | Anti-corruption probe in Ukraine targets former presidential | 1/1/1 | 1.000 | 1.000 |
| 4 | Emmanuel Macron seeks renewed partnerships during Africa For | 1/2/1 | 0.667 | 0.500 |
| 5 | Massive protests in Argentina against university funding cut | 0/1/1 | 0.000 | 0.000 |
| 6 | Nunes Marques takes office as President of Brazil's Superior | 1/2/1 | 0.333 | 0.000 |
| 7 | Keir Starmer faces internal pressure and calls for resignati | 1/1/1 | 0.333 | 0.000 |
| 8 | Israel and Lebanon exchange fire as ceasefire efforts remain | 3/4/4 | 0.700 | 0.600 |
| 9 | South Korea and Australia consider joining naval missions in | 1/2/1 | 0.167 | 0.000 |
| 10 | Israel qualifies for Eurovision final amid protests and boyc | 1/4/5 | 0.167 | 0.000 |
| 11 | Trump administration officials resign amid policy shifts and | 3/3/1 | 0.000 | 0.000 |
| 12 | Nigeria reports airstrike casualties and interception of Sta | 2/1/3 | 0.000 | 0.000 |
| 13 | Sam Altman testifies in high-stakes trial regarding Elon Mus | 1/2/2 | 0.000 | 0.000 |
| 14 | Global health authorities monitor hantavirus outbreak on cru | 1/4/2 | 0.067 | 0.000 |
| 15 | US inflation rises to 3.8% driven by high energy costs | 1/0/0 | 0.333 | 0.000 |
| 16 | Cannes Film Festival 2026 opens with honors for Peter Jackso | 1/0/0 | 0.333 | 0.000 |
| 17 | NBA players Jason Collins and Brandon Clarke die on the same | 0/0/0 | 1.000 | 1.000 |

**Day aggregates:** mean-across-topics of `jaccard_mean` = **0.401**; mean-across-topics of `jaccard_min` = **0.265**.
