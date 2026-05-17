# Cluster-LLM-assignment smoke — 2026-05-08

Three runs of `AssignClustersStage` at temperature 1.0 against the fixed `audit-2026-05-16` topic-set (15 topics) and the cached `curator_pre_clusters` (246 clusters).

## Per-run table

| Run | Wall (s) | Cost (USD) | Tokens | Clusters in | Assigned | Orphan | Multi-asg | Findings assigned | Orphan findings |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 81.4 | $0.0399 | 75,031 | 246 | 27 | 219 | 1 | 519 | 882 |
| 2 | 79.6 | $0.0062 | 74,831 | 246 | 24 | 222 | 1 | 468 | 933 |
| 3 | 78.8 | $0.0398 | 74,996 | 246 | 26 | 220 | 1 | 516 | 885 |

## Per-day spread across 3 runs

| Metric | Mean | Min | Max | Spread (max - min) |
|---|---:|---:|---:|---:|
| Wall (s) | 79.909 | 78.812 | 81.354 | 2.5420000000000016 |
| Cost (USD) | 0.029 | 0.0061534 | 0.039868 | 0.0337146 |
| Clusters assigned | 25.667 | 24 | 27 | 3 |
| Clusters orphan | 220.333 | 219 | 222 | 3 |
| Multi-assignments | 1 | 1 | 1 | 0 |
| Findings assigned | 501 | 468 | 519 | 51 |
| Orphan findings | 900 | 882 | 933 | 51 |

## Topic-level cluster-set stability (Jaccard across runs)

For each topic, the assigned cluster set per run is compared pairwise; mean and min Jaccard across the 3 pairs are reported. 1.0 = identical cluster set across all 3 runs.

| # | Topic title (truncated) | Per-run cluster counts | Jaccard mean | Jaccard min |
|---:|---|---|---:|---:|
| 0 | US and Iran maintain diplomatic dialogue despite exchange of | 5/4/6 | 0.767 | 0.667 |
| 1 | Russia and Ukraine trade accusations over Victory Day ceasef | 2/2/2 | 1.000 | 1.000 |
| 2 | Donald Trump and Lula da Silva meet at White House to relink | 2/2/2 | 1.000 | 1.000 |
| 3 | South African Constitutional Court orders Parliament to revi | 1/1/1 | 1.000 | 1.000 |
| 4 | Hantavirus outbreak on cruise ship MV Hondius triggers inter | 1/1/1 | 1.000 | 1.000 |
| 5 | Internal crisis hits Real Madrid following training ground a | 2/2/2 | 1.000 | 1.000 |
| 6 | Tamil Nadu government formation proceeds with support for Vi | 1/1/1 | 1.000 | 1.000 |
| 7 | US trade court strikes down Donald Trump's 10 percent univer | 5/4/4 | 0.733 | 0.600 |
| 8 | China sentences former defense ministers to death with repri | 1/1/1 | 1.000 | 1.000 |
| 9 | Pope Leo XIV marks first anniversary amid tensions with US a | 1/1/1 | 1.000 | 1.000 |
| 10 | Labour Party suffers significant losses in UK local election | 1/1/1 | 1.000 | 1.000 |
| 11 | Bank of Mexico concludes interest rate cut cycle at 6.5 perc | 1/1/1 | 1.000 | 1.000 |
| 12 | K-pop group BTS begins successful concert residency in Mexic | 3/2/2 | 0.778 | 0.667 |
| 13 | Mount Dukono eruption in Indonesia kills three hikers | 1/1/1 | 1.000 | 1.000 |
| 14 | Naturalist David Attenborough celebrates 100th birthday | 1/1/1 | 1.000 | 1.000 |

**Day aggregates:** mean-across-topics of `jaccard_mean` = **0.952**; mean-across-topics of `jaccard_min` = **0.929**.
