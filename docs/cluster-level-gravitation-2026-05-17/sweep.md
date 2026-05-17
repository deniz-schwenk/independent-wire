# Cluster-level gravitational sweep

Phase 1 of `TASK-CLUSTER-LEVEL-GRAVITATION.md`.

Sweeps cluster-level gravitational assignment over Threshold × Assignment-Mode × Fallback-Behaviour against the 2,542 audit labels from `TASK-CLUSTER-QUALITY-AUDIT` (audit at `docs/cluster-quality-audit/audit-2026-05-16/`, HEAD `6d8ffc4`). The Brief 5b pinned baseline (finding-level T=0.55 V1, the current production configuration) appears as an explicit comparison row.

## Method

- **Cluster centroids** are computed inline as the L2-normalised mean of the L2-normalised finding embeddings within each Brief 1 micro-cluster (`distance_threshold=0.7, linkage='average', metric='cosine'`).
- **Topic centres** use the V1 production text (`title + summary`), unchanged from Brief 5b.
- **Thresholds T:** `0.55, 0.60, 0.65, 0.70, 0.75`.
- **Modes:** `single, multi`. 
- **Fallbacks:** `orphan, finding_level` (`finding_level` falls back to Brief 5b's T=0.55 V1 for findings whose cluster has no topic above T).
- **PER_FINDING_CAP:** 3 (matches production; applied after cluster→finding propagation).
- **Audit-set metrics** (off-topic %, precision, recall) are computed only on (finding, topic) pairs that have a label in the 2,542-label audit set. Full-population metrics (orphan %, multi/single counts, total assignments) are computed across all 4,007 findings of the three eval days.
- **Day populations:** 2026-05-08 = 1401 findings, 15 topics, 246 clusters / 2026-05-11 = 1201 findings, 15 topics, 241 clusters / 2026-05-13 = 1405 findings, 18 topics, 279 clusters.

## Top-level table

21 rows (20 cluster-level configurations + Brief 5b baseline). Ranked by weighted off-topic %. Off % low is good, recall high is good — they compete; read both. Orphan % is the share of the 4,007 findings with zero topic assignments after propagation + fallback.

| Rank | Config | Off % | Mean prec | Mean recall | Orphan | Orphan % | Single | Multi | Total assn | Topics 0-retained |
|---:|:--|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | baseline T=0.55 V1 finding-level | 8.23% | 0.9169 | 0.6552 | 3,404 | 84.95% | 598 | 5 | 608 | 0 |
| 2 | cluster T=0.75 single+finding_level | 28.86% | 0.7950 | 0.7557 | 3,019 | 75.34% | 986 | 2 | 990 | 1 |
| 3 | cluster T=0.70 single+finding_level | 29.66% | 0.7564 | 0.7931 | 2,925 | 73.00% | 1,082 | 0 | 1,082 | 1 |
| 4 | cluster T=0.70 single+orphan | 30.32% | 0.7262 | 0.7043 | 2,970 | 74.12% | 1,037 | 0 | 1,037 | 6 |
| 5 | cluster T=0.75 single+orphan | 30.76% | 0.7327 | 0.5907 | 3,105 | 77.49% | 902 | 0 | 902 | 10 |
| 6 | cluster T=0.65 single+finding_level | 31.65% | 0.7113 | 0.8129 | 2,865 | 71.50% | 1,142 | 0 | 1,142 | 1 |
| 7 | cluster T=0.65 single+orphan | 31.87% | 0.7063 | 0.7627 | 2,891 | 72.15% | 1,116 | 0 | 1,116 | 3 |
| 8 | cluster T=0.75 multi+finding_level | 32.17% | 0.7756 | 0.7891 | 3,019 | 75.34% | 920 | 68 | 1,056 | 0 |
| 9 | cluster T=0.60 single+finding_level | 32.52% | 0.6893 | 0.8424 | 2,821 | 70.40% | 1,186 | 0 | 1,186 | 1 |
| 10 | cluster T=0.60 single+orphan | 32.65% | 0.6867 | 0.8283 | 2,835 | 70.75% | 1,172 | 0 | 1,172 | 1 |
| 11 | cluster T=0.70 multi+finding_level | 32.69% | 0.7382 | 0.8264 | 2,925 | 73.00% | 1,016 | 66 | 1,148 | 0 |
| 12 | cluster T=0.70 multi+orphan | 33.45% | 0.7055 | 0.7377 | 2,970 | 74.12% | 971 | 66 | 1,103 | 5 |
| 13 | cluster T=0.55 single+finding_level | 33.92% | 0.6655 | 0.8470 | 2,786 | 69.53% | 1,221 | 0 | 1,221 | 0 |
| 14 | cluster T=0.55 single+orphan | 34.10% | 0.6635 | 0.8341 | 2,797 | 69.80% | 1,210 | 0 | 1,210 | 0 |
| 15 | cluster T=0.75 multi+orphan | 34.27% | 0.7079 | 0.6240 | 3,105 | 77.49% | 836 | 66 | 968 | 9 |
| 16 | cluster T=0.65 multi+finding_level | 34.43% | 0.6946 | 0.8462 | 2,865 | 71.50% | 1,076 | 66 | 1,208 | 0 |
| 17 | cluster T=0.65 multi+orphan | 34.71% | 0.6886 | 0.7960 | 2,891 | 72.15% | 1,050 | 66 | 1,182 | 2 |
| 18 | cluster T=0.60 multi+finding_level | 35.16% | 0.6733 | 0.8757 | 2,821 | 70.40% | 1,120 | 66 | 1,252 | 0 |
| 19 | cluster T=0.60 multi+orphan | 35.32% | 0.6709 | 0.8616 | 2,835 | 70.75% | 1,106 | 66 | 1,238 | 0 |
| 20 | cluster T=0.55 multi+finding_level | 36.41% | 0.6709 | 0.8803 | 2,786 | 69.53% | 1,130 | 91 | 1,312 | 0 |
| 21 | cluster T=0.55 multi+orphan | 36.60% | 0.6689 | 0.8674 | 2,797 | 69.80% | 1,119 | 91 | 1,301 | 0 |

## Cluster-behaviour summary

Per-(T, mode) — how many of the ~766 clusters (across three days) land in 0 / 1 / ≥2 topics at threshold T, plus mean cluster size in each bucket. Under the orphan-fallback variant these counts directly drive finding-level orphan rate; under finding-level fallback, orphan clusters are split apart and individual findings get re-assigned via Brief 5b's T=0.55 V1 rule (so cluster-level orphan ≠ finding-level orphan there).

| T | mode | clusters | orphan | single-topic | multi-topic | mean orphan size | mean assigned size |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.55 | multi | 766 | 713 | 51 | 2 | 3.9 | 22.8 |
| 0.55 | single | 766 | 713 | 53 | 0 | 3.9 | 22.8 |
| 0.60 | multi | 766 | 718 | 47 | 1 | 3.9 | 24.4 |
| 0.60 | single | 766 | 718 | 48 | 0 | 3.9 | 24.4 |
| 0.65 | multi | 766 | 721 | 44 | 1 | 4.0 | 24.8 |
| 0.65 | single | 766 | 721 | 45 | 0 | 4.0 | 24.8 |
| 0.70 | multi | 766 | 726 | 39 | 1 | 4.1 | 25.9 |
| 0.70 | single | 766 | 726 | 40 | 0 | 4.1 | 25.9 |
| 0.75 | multi | 766 | 731 | 34 | 1 | 4.2 | 25.8 |
| 0.75 | single | 766 | 731 | 35 | 0 | 4.2 | 25.8 |

### Top-10 audited clusters per day — assignment behaviour at each T

Cross-references the cluster-internal audit (`audit-2026-05-17`, 1,233 labels) singular/non-singular hypothesis per cluster with the assignment behaviour under each cluster-level T. Same behaviour under both fallbacks (fallback only changes what happens to findings inside orphaned clusters, not the cluster-level assignment itself).

| Day | cluster_id | size | singular? | T=0.55 (s/m) | T=0.60 | T=0.65 | T=0.70 | T=0.75 |
|---|---|---:|:--:|:--:|:--:|:--:|:--:|:--:|
| 2026-05-08 | mc-000 | 100 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-08 | mc-001 | 70 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-08 | mc-002 | 49 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-08 | mc-003 | 47 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-08 | mc-004 | 41 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-08 | mc-005 | 34 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-08 | mc-006 | 25 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-08 | mc-007 | 25 | no | 1/1 | 1/1 | 0/0 | 0/0 | 0/0 |
| 2026-05-08 | mc-008 | 24 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-08 | mc-009 | 23 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-11 | mc-000 | 66 | yes | 1/2 | 1/2 | 1/2 | 1/2 | 1/2 |
| 2026-05-11 | mc-001 | 61 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-11 | mc-002 | 55 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-11 | mc-003 | 29 | yes | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-11 | mc-004 | 29 | no | 1/1 | 1/1 | 1/1 | 1/1 | 0/0 |
| 2026-05-11 | mc-005 | 29 | no | 1/1 | 1/1 | 1/1 | 0/0 | 0/0 |
| 2026-05-11 | mc-006 | 27 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-11 | mc-007 | 23 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-11 | mc-008 | 21 | no | 1/1 | 1/1 | 1/1 | 1/1 | 0/0 |
| 2026-05-11 | mc-009 | 19 | yes | 1/1 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-13 | mc-000 | 77 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-13 | mc-001 | 72 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-13 | mc-002 | 58 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 0/0 |
| 2026-05-13 | mc-003 | 53 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-13 | mc-004 | 44 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-13 | mc-005 | 29 | no | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-13 | mc-006 | 27 | yes | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| 2026-05-13 | mc-007 | 26 | no | 1/1 | 1/1 | 1/1 | 0/0 | 0/0 |
| 2026-05-13 | mc-008 | 25 | no | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| 2026-05-13 | mc-009 | 25 | yes | 1/2 | 1/1 | 1/1 | 1/1 | 1/1 |

Cell format: `single/multi` count of topic-assignments at that T. `single` is always 0 or 1 (single-mode picks at most one topic per cluster). `multi` can be 0 / 1 / 2+ — see `multi` column for whether the cluster lands in multiple topics.

## Per-topic detail — all 30 audited topics across all 21 configurations

For each audited topic, off-topic % and retained-count at each configuration. Use this to identify which topics benefit most from cluster-level assignment vs. which lose recall.

### 2026-05-08 · topic-00 · US and Iran maintain diplomatic dialogue despite exchange of fire in Strait of Hormuz

_source_count=195, audit on=88 / 195_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 41 | 38 | 3 | 7.3% | 0.9268 | 0.4318 |
| cluster T=0.55 multi+finding_level | 68 | 61 | 7 | 10.3% | 0.8971 | 0.6932 |
| cluster T=0.55 multi+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.55 single+finding_level | 68 | 61 | 7 | 10.3% | 0.8971 | 0.6932 |
| cluster T=0.55 single+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.60 multi+finding_level | 68 | 61 | 7 | 10.3% | 0.8971 | 0.6932 |
| cluster T=0.60 multi+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.60 single+finding_level | 68 | 61 | 7 | 10.3% | 0.8971 | 0.6932 |
| cluster T=0.60 single+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.65 multi+finding_level | 68 | 61 | 7 | 10.3% | 0.8971 | 0.6932 |
| cluster T=0.65 multi+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.65 single+finding_level | 68 | 61 | 7 | 10.3% | 0.8971 | 0.6932 |
| cluster T=0.65 single+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.70 multi+finding_level | 68 | 61 | 7 | 10.3% | 0.8971 | 0.6932 |
| cluster T=0.70 multi+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.70 single+finding_level | 68 | 61 | 7 | 10.3% | 0.8971 | 0.6932 |
| cluster T=0.70 single+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.75 multi+finding_level | 69 | 61 | 8 | 11.6% | 0.8841 | 0.6932 |
| cluster T=0.75 multi+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |
| cluster T=0.75 single+finding_level | 69 | 61 | 8 | 11.6% | 0.8841 | 0.6932 |
| cluster T=0.75 single+orphan | 65 | 60 | 5 | 7.7% | 0.9231 | 0.6818 |

### 2026-05-08 · topic-01 · Russia and Ukraine trade accusations over Victory Day ceasefire violations

_source_count=163, audit on=37 / 163_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 32 | 20 | 12 | 37.5% | 0.6250 | 0.5405 |
| cluster T=0.55 multi+finding_level | 99 | 37 | 62 | 62.6% | 0.3737 | 1.0000 |
| cluster T=0.55 multi+orphan | 99 | 37 | 62 | 62.6% | 0.3737 | 1.0000 |
| cluster T=0.55 single+finding_level | 99 | 37 | 62 | 62.6% | 0.3737 | 1.0000 |
| cluster T=0.55 single+orphan | 99 | 37 | 62 | 62.6% | 0.3737 | 1.0000 |
| cluster T=0.60 multi+finding_level | 95 | 35 | 60 | 63.2% | 0.3684 | 0.9459 |
| cluster T=0.60 multi+orphan | 94 | 35 | 59 | 62.8% | 0.3723 | 0.9459 |
| cluster T=0.60 single+finding_level | 95 | 35 | 60 | 63.2% | 0.3684 | 0.9459 |
| cluster T=0.60 single+orphan | 94 | 35 | 59 | 62.8% | 0.3723 | 0.9459 |
| cluster T=0.65 multi+finding_level | 95 | 35 | 60 | 63.2% | 0.3684 | 0.9459 |
| cluster T=0.65 multi+orphan | 94 | 35 | 59 | 62.8% | 0.3723 | 0.9459 |
| cluster T=0.65 single+finding_level | 95 | 35 | 60 | 63.2% | 0.3684 | 0.9459 |
| cluster T=0.65 single+orphan | 94 | 35 | 59 | 62.8% | 0.3723 | 0.9459 |
| cluster T=0.70 multi+finding_level | 95 | 35 | 60 | 63.2% | 0.3684 | 0.9459 |
| cluster T=0.70 multi+orphan | 94 | 35 | 59 | 62.8% | 0.3723 | 0.9459 |
| cluster T=0.70 single+finding_level | 95 | 35 | 60 | 63.2% | 0.3684 | 0.9459 |
| cluster T=0.70 single+orphan | 94 | 35 | 59 | 62.8% | 0.3723 | 0.9459 |
| cluster T=0.75 multi+finding_level | 95 | 35 | 60 | 63.2% | 0.3684 | 0.9459 |
| cluster T=0.75 multi+orphan | 94 | 35 | 59 | 62.8% | 0.3723 | 0.9459 |
| cluster T=0.75 single+finding_level | 95 | 35 | 60 | 63.2% | 0.3684 | 0.9459 |
| cluster T=0.75 single+orphan | 94 | 35 | 59 | 62.8% | 0.3723 | 0.9459 |

### 2026-05-08 · topic-02 · Donald Trump and Lula da Silva meet at White House to relink US-Brazil relations

_source_count=77, audit on=12 / 77_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 12 | 12 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.55 multi+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.55 multi+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.55 single+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.55 single+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.60 multi+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.60 multi+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.60 single+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.60 single+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.65 multi+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.65 multi+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.65 single+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.65 single+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.70 multi+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.70 multi+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.70 single+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.70 single+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.75 multi+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.75 multi+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |
| cluster T=0.75 single+finding_level | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| cluster T=0.75 single+orphan | 13 | 11 | 2 | 15.4% | 0.8462 | 0.9167 |

### 2026-05-08 · topic-03 · South African Constitutional Court orders Parliament to revisit Cyril Ramaphosa impeachmen

_source_count=75, audit on=5 / 75_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 4 | 4 | 0 | 0.0% | 1.0000 | 0.8000 |
| cluster T=0.55 multi+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.55 multi+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.55 single+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.55 single+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.60 multi+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.60 multi+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.60 single+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.60 single+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.65 multi+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.65 multi+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.65 single+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.65 single+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.70 multi+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.70 multi+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.70 single+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.70 single+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.75 multi+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.75 multi+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.75 single+finding_level | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |
| cluster T=0.75 single+orphan | 6 | 5 | 1 | 16.7% | 0.8333 | 1.0000 |

### 2026-05-08 · topic-04 · Hantavirus outbreak on cruise ship MV Hondius triggers international health response

_source_count=56, audit on=47 / 56_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 25 | 25 | 0 | 0.0% | 1.0000 | 0.5319 |
| cluster T=0.55 multi+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.55 multi+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.55 single+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.55 single+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.60 multi+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.60 multi+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.60 single+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.60 single+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.65 multi+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.65 multi+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.65 single+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.65 single+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.70 multi+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.70 multi+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.70 single+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.70 single+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.75 multi+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.75 multi+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.75 single+finding_level | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |
| cluster T=0.75 single+orphan | 48 | 45 | 3 | 6.2% | 0.9375 | 0.9574 |

### 2026-05-08 · topic-05 · Internal crisis hits Real Madrid following training ground altercation

_source_count=49, audit on=8 / 49_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| cluster T=0.55 multi+finding_level | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| cluster T=0.55 multi+orphan | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| cluster T=0.55 single+finding_level | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| cluster T=0.55 single+orphan | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| cluster T=0.60 multi+finding_level | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| cluster T=0.60 multi+orphan | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| cluster T=0.60 single+finding_level | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| cluster T=0.60 single+orphan | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| cluster T=0.65 multi+finding_level | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| cluster T=0.65 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.65 single+finding_level | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| cluster T=0.65 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 multi+finding_level | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| cluster T=0.70 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 single+finding_level | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| cluster T=0.70 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 multi+finding_level | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-08 · topic-06 · Tamil Nadu government formation proceeds with support for Vijay's TVK party

_source_count=47, audit on=12 / 47_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 3 | 3 | 0 | 0.0% | 1.0000 | 0.2500 |
| cluster T=0.55 multi+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.55 multi+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.55 single+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.55 single+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.60 multi+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.60 multi+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.60 single+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.60 single+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.65 multi+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.65 multi+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.65 single+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.65 single+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.70 multi+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.70 multi+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.70 single+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.70 single+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.75 multi+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.75 multi+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.75 single+finding_level | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.75 single+orphan | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |

### 2026-05-08 · topic-07 · US trade court strikes down Donald Trump's 10 percent universal tariffs

_source_count=47, audit on=21 / 47_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 19 | 19 | 0 | 0.0% | 1.0000 | 0.9048 |
| cluster T=0.55 multi+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.55 multi+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.55 single+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.55 single+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.60 multi+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.60 multi+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.60 single+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.60 single+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.65 multi+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.65 multi+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.65 single+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.65 single+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.70 multi+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.70 multi+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.70 single+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.70 single+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.75 multi+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.75 multi+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.75 single+finding_level | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |
| cluster T=0.75 single+orphan | 22 | 21 | 1 | 4.5% | 0.9545 | 1.0000 |

### 2026-05-08 · topic-08 · China sentences former defense ministers to death with reprieve for corruption

_source_count=43, audit on=4 / 43_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 5 | 3 | 2 | 40.0% | 0.6000 | 0.7500 |
| cluster T=0.55 multi+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.55 multi+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.55 single+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.55 single+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.60 multi+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.60 multi+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.60 single+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.60 single+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.65 multi+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.65 multi+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.65 single+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.65 single+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.70 multi+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.70 multi+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.70 single+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.70 single+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.75 multi+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.75 multi+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.75 single+finding_level | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |
| cluster T=0.75 single+orphan | 11 | 3 | 8 | 72.7% | 0.2727 | 0.7500 |

### 2026-05-08 · topic-09 · Pope Leo XIV marks first anniversary amid tensions with US administration

_source_count=33, audit on=12 / 33_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 8 | 8 | 0 | 0.0% | 1.0000 | 0.6667 |
| cluster T=0.55 multi+finding_level | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.55 multi+orphan | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.55 single+finding_level | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.55 single+orphan | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.60 multi+finding_level | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.60 multi+orphan | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.60 single+finding_level | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.60 single+orphan | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.65 multi+finding_level | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.65 multi+orphan | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.65 single+finding_level | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.65 single+orphan | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.70 multi+finding_level | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.70 multi+orphan | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.70 single+finding_level | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.70 single+orphan | 15 | 12 | 3 | 20.0% | 0.8000 | 1.0000 |
| cluster T=0.75 multi+finding_level | 8 | 8 | 0 | 0.0% | 1.0000 | 0.6667 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 8 | 8 | 0 | 0.0% | 1.0000 | 0.6667 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-11 · topic-00 · Russia and Ukraine accuse each other of violating US-brokered ceasefire

_source_count=155, audit on=22 / 155_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 17 | 11 | 6 | 35.3% | 0.6471 | 0.5000 |
| cluster T=0.55 multi+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.55 multi+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.55 single+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.55 single+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.60 multi+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.60 multi+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.60 single+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.60 single+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.65 multi+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.65 multi+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.65 single+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.65 single+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.70 multi+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.70 multi+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.70 single+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.70 single+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.75 multi+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.75 multi+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.75 single+finding_level | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |
| cluster T=0.75 single+orphan | 62 | 20 | 42 | 67.7% | 0.3226 | 0.9091 |

### 2026-05-11 · topic-01 · Donald Trump rejects Iran's response to US peace proposal as unacceptable

_source_count=144, audit on=71 / 144_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 45 | 42 | 3 | 6.7% | 0.9333 | 0.5915 |
| cluster T=0.55 multi+finding_level | 71 | 58 | 13 | 18.3% | 0.8169 | 0.8169 |
| cluster T=0.55 multi+orphan | 70 | 57 | 13 | 18.6% | 0.8143 | 0.8028 |
| cluster T=0.55 single+finding_level | 71 | 58 | 13 | 18.3% | 0.8169 | 0.8169 |
| cluster T=0.55 single+orphan | 70 | 57 | 13 | 18.6% | 0.8143 | 0.8028 |
| cluster T=0.60 multi+finding_level | 71 | 58 | 13 | 18.3% | 0.8169 | 0.8169 |
| cluster T=0.60 multi+orphan | 70 | 57 | 13 | 18.6% | 0.8143 | 0.8028 |
| cluster T=0.60 single+finding_level | 71 | 58 | 13 | 18.3% | 0.8169 | 0.8169 |
| cluster T=0.60 single+orphan | 70 | 57 | 13 | 18.6% | 0.8143 | 0.8028 |
| cluster T=0.65 multi+finding_level | 63 | 51 | 12 | 19.1% | 0.8095 | 0.7183 |
| cluster T=0.65 multi+orphan | 61 | 49 | 12 | 19.7% | 0.8033 | 0.6901 |
| cluster T=0.65 single+finding_level | 63 | 51 | 12 | 19.1% | 0.8095 | 0.7183 |
| cluster T=0.65 single+orphan | 61 | 49 | 12 | 19.7% | 0.8033 | 0.6901 |
| cluster T=0.70 multi+finding_level | 63 | 51 | 12 | 19.1% | 0.8095 | 0.7183 |
| cluster T=0.70 multi+orphan | 61 | 49 | 12 | 19.7% | 0.8033 | 0.6901 |
| cluster T=0.70 single+finding_level | 63 | 51 | 12 | 19.1% | 0.8095 | 0.7183 |
| cluster T=0.70 single+orphan | 61 | 49 | 12 | 19.7% | 0.8033 | 0.6901 |
| cluster T=0.75 multi+finding_level | 63 | 51 | 12 | 19.1% | 0.8095 | 0.7183 |
| cluster T=0.75 multi+orphan | 61 | 49 | 12 | 19.7% | 0.8033 | 0.6901 |
| cluster T=0.75 single+finding_level | 63 | 51 | 12 | 19.1% | 0.8095 | 0.7183 |
| cluster T=0.75 single+orphan | 61 | 49 | 12 | 19.7% | 0.8033 | 0.6901 |

### 2026-05-11 · topic-02 · Vladimir Putin proposes Gerhard Schröder as mediator for Ukraine negotiations

_source_count=134, audit on=12 / 134_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| cluster T=0.55 multi+finding_level | 74 | 12 | 62 | 83.8% | 0.1622 | 1.0000 |
| cluster T=0.55 multi+orphan | 74 | 12 | 62 | 83.8% | 0.1622 | 1.0000 |
| cluster T=0.55 single+finding_level | 17 | 0 | 17 | 100.0% | 0.0000 | 0.0000 |
| cluster T=0.55 single+orphan | 17 | 0 | 17 | 100.0% | 0.0000 | 0.0000 |
| cluster T=0.60 multi+finding_level | 57 | 12 | 45 | 79.0% | 0.2105 | 1.0000 |
| cluster T=0.60 multi+orphan | 57 | 12 | 45 | 79.0% | 0.2105 | 1.0000 |
| cluster T=0.60 single+finding_level | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.60 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.65 multi+finding_level | 57 | 12 | 45 | 79.0% | 0.2105 | 1.0000 |
| cluster T=0.65 multi+orphan | 57 | 12 | 45 | 79.0% | 0.2105 | 1.0000 |
| cluster T=0.65 single+finding_level | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.65 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 multi+finding_level | 57 | 12 | 45 | 79.0% | 0.2105 | 1.0000 |
| cluster T=0.70 multi+orphan | 57 | 12 | 45 | 79.0% | 0.2105 | 1.0000 |
| cluster T=0.70 single+finding_level | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 multi+finding_level | 57 | 12 | 45 | 79.0% | 0.2105 | 1.0000 |
| cluster T=0.75 multi+orphan | 57 | 12 | 45 | 79.0% | 0.2105 | 1.0000 |
| cluster T=0.75 single+finding_level | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-11 · topic-03 · South Korean vessel damaged by explosion in the Strait of Hormuz

_source_count=70, audit on=28 / 70_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 8 | 8 | 0 | 0.0% | 1.0000 | 0.2857 |
| cluster T=0.55 multi+finding_level | 29 | 15 | 14 | 48.3% | 0.5172 | 0.5357 |
| cluster T=0.55 multi+orphan | 29 | 15 | 14 | 48.3% | 0.5172 | 0.5357 |
| cluster T=0.55 single+finding_level | 29 | 15 | 14 | 48.3% | 0.5172 | 0.5357 |
| cluster T=0.55 single+orphan | 29 | 15 | 14 | 48.3% | 0.5172 | 0.5357 |
| cluster T=0.60 multi+finding_level | 28 | 14 | 14 | 50.0% | 0.5000 | 0.5000 |
| cluster T=0.60 multi+orphan | 27 | 13 | 14 | 51.9% | 0.4815 | 0.4643 |
| cluster T=0.60 single+finding_level | 28 | 14 | 14 | 50.0% | 0.5000 | 0.5000 |
| cluster T=0.60 single+orphan | 27 | 13 | 14 | 51.9% | 0.4815 | 0.4643 |
| cluster T=0.65 multi+finding_level | 28 | 14 | 14 | 50.0% | 0.5000 | 0.5000 |
| cluster T=0.65 multi+orphan | 27 | 13 | 14 | 51.9% | 0.4815 | 0.4643 |
| cluster T=0.65 single+finding_level | 28 | 14 | 14 | 50.0% | 0.5000 | 0.5000 |
| cluster T=0.65 single+orphan | 27 | 13 | 14 | 51.9% | 0.4815 | 0.4643 |
| cluster T=0.70 multi+finding_level | 8 | 8 | 0 | 0.0% | 1.0000 | 0.2857 |
| cluster T=0.70 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 single+finding_level | 8 | 8 | 0 | 0.0% | 1.0000 | 0.2857 |
| cluster T=0.70 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 multi+finding_level | 8 | 8 | 0 | 0.0% | 1.0000 | 0.2857 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 8 | 8 | 0 | 0.0% | 1.0000 | 0.2857 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-11 · topic-04 · Hantavirus outbreak on MV Hondius cruise ship triggers international health alerts

_source_count=65, audit on=56 / 65_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 33 | 33 | 0 | 0.0% | 1.0000 | 0.5893 |
| cluster T=0.55 multi+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.55 multi+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.55 single+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.55 single+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.60 multi+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.60 multi+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.60 single+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.60 single+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.65 multi+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.65 multi+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.65 single+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.65 single+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.70 multi+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.70 multi+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.70 single+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.70 single+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.75 multi+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.75 multi+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.75 single+finding_level | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |
| cluster T=0.75 single+orphan | 53 | 53 | 0 | 0.0% | 1.0000 | 0.9464 |

### 2026-05-11 · topic-05 · Emmanuel Macron visits Kenya for Africa Forward economic summit

_source_count=48, audit on=10 / 48_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 9 | 9 | 0 | 0.0% | 1.0000 | 0.9000 |
| cluster T=0.55 multi+finding_level | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.55 multi+orphan | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.55 single+finding_level | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.55 single+orphan | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.60 multi+finding_level | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.60 multi+orphan | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.60 single+finding_level | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.60 single+orphan | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.65 multi+finding_level | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.65 multi+orphan | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.65 single+finding_level | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.65 single+orphan | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.70 multi+finding_level | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.70 multi+orphan | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.70 single+finding_level | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.70 single+orphan | 14 | 9 | 5 | 35.7% | 0.6429 | 0.9000 |
| cluster T=0.75 multi+finding_level | 9 | 9 | 0 | 0.0% | 1.0000 | 0.9000 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 9 | 9 | 0 | 0.0% | 1.0000 | 0.9000 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-11 · topic-06 · Donald Trump prepares for state visit to China amid trade tensions

_source_count=46, audit on=22 / 46_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 15 | 15 | 0 | 0.0% | 1.0000 | 0.6818 |
| cluster T=0.55 multi+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.55 multi+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.55 single+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.55 single+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.60 multi+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.60 multi+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.60 single+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.60 single+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.65 multi+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.65 multi+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.65 single+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.65 single+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.70 multi+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.70 multi+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.70 single+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.70 single+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.75 multi+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.75 multi+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.75 single+finding_level | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |
| cluster T=0.75 single+orphan | 23 | 19 | 4 | 17.4% | 0.8261 | 0.8636 |

### 2026-05-11 · topic-07 · Narges Mohammadi released from Iranian prison for medical treatment

_source_count=45, audit on=8 / 45_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 8 | 8 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.55 multi+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.55 multi+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.55 single+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.55 single+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.60 multi+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.60 multi+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.60 single+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.60 single+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.65 multi+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.65 multi+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.65 single+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.65 single+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.70 multi+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.70 multi+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.70 single+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.70 single+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.75 multi+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.75 multi+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.75 single+finding_level | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| cluster T=0.75 single+orphan | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |

### 2026-05-11 · topic-08 · Latvian Defense Minister resigns following Ukrainian drone incursions

_source_count=43, audit on=8 / 43_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 6 | 5 | 1 | 16.7% | 0.8333 | 0.6250 |
| cluster T=0.55 multi+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.55 multi+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.55 single+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.55 single+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.60 multi+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.60 multi+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.60 single+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.60 single+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.65 multi+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.65 multi+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.65 single+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.65 single+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.70 multi+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.70 multi+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.70 single+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.70 single+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.75 multi+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.75 multi+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.75 single+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |
| cluster T=0.75 single+orphan | 7 | 5 | 2 | 28.6% | 0.7143 | 0.6250 |

### 2026-05-11 · topic-09 · Barcelona wins La Liga title after victory over Real Madrid

_source_count=42, audit on=15 / 42_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 8 | 8 | 0 | 0.0% | 1.0000 | 0.5333 |
| cluster T=0.55 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.55 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.55 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.55 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.60 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.60 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.60 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.60 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.65 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.65 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.65 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.65 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.70 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.70 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.70 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.70 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.75 multi+finding_level | 8 | 8 | 0 | 0.0% | 1.0000 | 0.5333 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 8 | 8 | 0 | 0.0% | 1.0000 | 0.5333 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-13 · topic-00 · Escalating costs and military risks threaten Middle East truce between US and Iran

_source_count=162, audit on=62 / 162_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 12 | 11 | 1 | 8.3% | 0.9167 | 0.1774 |
| cluster T=0.55 multi+finding_level | 60 | 47 | 13 | 21.7% | 0.7833 | 0.7581 |
| cluster T=0.55 multi+orphan | 60 | 47 | 13 | 21.7% | 0.7833 | 0.7581 |
| cluster T=0.55 single+finding_level | 60 | 47 | 13 | 21.7% | 0.7833 | 0.7581 |
| cluster T=0.55 single+orphan | 60 | 47 | 13 | 21.7% | 0.7833 | 0.7581 |
| cluster T=0.60 multi+finding_level | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.60 multi+orphan | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.60 single+finding_level | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.60 single+orphan | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.65 multi+finding_level | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.65 multi+orphan | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.65 single+finding_level | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.65 single+orphan | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.70 multi+finding_level | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.70 multi+orphan | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.70 single+finding_level | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.70 single+orphan | 53 | 44 | 9 | 17.0% | 0.8302 | 0.7097 |
| cluster T=0.75 multi+finding_level | 12 | 11 | 1 | 8.3% | 0.9167 | 0.1774 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 12 | 11 | 1 | 8.3% | 0.9167 | 0.1774 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-13 · topic-01 · Ukraine and Russia exchange long-range drone strikes on energy and military infrastructure

_source_count=137, audit on=34 / 137_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 33 | 30 | 3 | 9.1% | 0.9091 | 0.8824 |
| cluster T=0.55 multi+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.55 multi+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.55 single+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.55 single+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.60 multi+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.60 multi+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.60 single+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.60 single+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.65 multi+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.65 multi+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.65 single+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.65 single+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.70 multi+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.70 multi+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.70 single+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.70 single+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.75 multi+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.75 multi+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.75 single+finding_level | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |
| cluster T=0.75 single+orphan | 77 | 33 | 44 | 57.1% | 0.4286 | 0.9706 |

### 2026-05-13 · topic-02 · Donald Trump arrives in China for high-stakes summit with Xi Jinping

_source_count=125, audit on=77 / 125_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 55 | 54 | 1 | 1.8% | 0.9818 | 0.7013 |
| cluster T=0.55 multi+finding_level | 74 | 64 | 10 | 13.5% | 0.8649 | 0.8312 |
| cluster T=0.55 multi+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.55 single+finding_level | 74 | 64 | 10 | 13.5% | 0.8649 | 0.8312 |
| cluster T=0.55 single+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.60 multi+finding_level | 74 | 64 | 10 | 13.5% | 0.8649 | 0.8312 |
| cluster T=0.60 multi+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.60 single+finding_level | 74 | 64 | 10 | 13.5% | 0.8649 | 0.8312 |
| cluster T=0.60 single+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.65 multi+finding_level | 74 | 64 | 10 | 13.5% | 0.8649 | 0.8312 |
| cluster T=0.65 multi+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.65 single+finding_level | 74 | 64 | 10 | 13.5% | 0.8649 | 0.8312 |
| cluster T=0.65 single+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.70 multi+finding_level | 74 | 64 | 10 | 13.5% | 0.8649 | 0.8312 |
| cluster T=0.70 multi+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.70 single+finding_level | 74 | 64 | 10 | 13.5% | 0.8649 | 0.8312 |
| cluster T=0.70 single+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.75 multi+finding_level | 76 | 65 | 11 | 14.5% | 0.8553 | 0.8442 |
| cluster T=0.75 multi+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |
| cluster T=0.75 single+finding_level | 76 | 65 | 11 | 14.5% | 0.8553 | 0.8442 |
| cluster T=0.75 single+orphan | 71 | 61 | 10 | 14.1% | 0.8592 | 0.7922 |

### 2026-05-13 · topic-03 · Anti-corruption probe in Ukraine targets former presidential aide Andriy Yermak

_source_count=107, audit on=7 / 107_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 6 | 6 | 0 | 0.0% | 1.0000 | 0.8571 |
| cluster T=0.55 multi+finding_level | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.55 multi+orphan | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.55 single+finding_level | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.55 single+orphan | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.60 multi+finding_level | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.60 multi+orphan | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.60 single+finding_level | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.60 single+orphan | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.65 multi+finding_level | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.65 multi+orphan | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.65 single+finding_level | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.65 single+orphan | 23 | 7 | 16 | 69.6% | 0.3043 | 1.0000 |
| cluster T=0.70 multi+finding_level | 6 | 6 | 0 | 0.0% | 1.0000 | 0.8571 |
| cluster T=0.70 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 single+finding_level | 6 | 6 | 0 | 0.0% | 1.0000 | 0.8571 |
| cluster T=0.70 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 multi+finding_level | 6 | 6 | 0 | 0.0% | 1.0000 | 0.8571 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 6 | 6 | 0 | 0.0% | 1.0000 | 0.8571 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-13 · topic-04 · Emmanuel Macron seeks renewed partnerships during Africa Forward summit in Kenya

_source_count=89, audit on=22 / 89_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 19 | 19 | 0 | 0.0% | 1.0000 | 0.8636 |
| cluster T=0.55 multi+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.55 multi+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.55 single+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.55 single+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.60 multi+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.60 multi+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.60 single+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.60 single+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.65 multi+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.65 multi+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.65 single+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.65 single+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.70 multi+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.70 multi+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.70 single+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.70 single+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.75 multi+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.75 multi+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.75 single+finding_level | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |
| cluster T=0.75 single+orphan | 29 | 21 | 8 | 27.6% | 0.7241 | 0.9545 |

### 2026-05-13 · topic-05 · Massive protests in Argentina against university funding cuts by Javier Milei

_source_count=84, audit on=7 / 84_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.55 multi+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.55 multi+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.55 single+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.55 single+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.60 multi+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.60 multi+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.60 single+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.60 single+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.65 multi+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.65 multi+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.65 single+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.65 single+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.70 multi+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.70 multi+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.70 single+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.70 single+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.75 multi+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.75 multi+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.75 single+finding_level | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| cluster T=0.75 single+orphan | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |

### 2026-05-13 · topic-06 · Nunes Marques takes office as President of Brazil's Superior Electoral Court

_source_count=81, audit on=7 / 81_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 7 | 5 | 2 | 28.6% | 0.7143 | 0.7143 |
| cluster T=0.55 multi+finding_level | 19 | 7 | 12 | 63.2% | 0.3684 | 1.0000 |
| cluster T=0.55 multi+orphan | 18 | 6 | 12 | 66.7% | 0.3333 | 0.8571 |
| cluster T=0.55 single+finding_level | 19 | 7 | 12 | 63.2% | 0.3684 | 1.0000 |
| cluster T=0.55 single+orphan | 18 | 6 | 12 | 66.7% | 0.3333 | 0.8571 |
| cluster T=0.60 multi+finding_level | 19 | 7 | 12 | 63.2% | 0.3684 | 1.0000 |
| cluster T=0.60 multi+orphan | 18 | 6 | 12 | 66.7% | 0.3333 | 0.8571 |
| cluster T=0.60 single+finding_level | 19 | 7 | 12 | 63.2% | 0.3684 | 1.0000 |
| cluster T=0.60 single+orphan | 18 | 6 | 12 | 66.7% | 0.3333 | 0.8571 |
| cluster T=0.65 multi+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.7143 |
| cluster T=0.65 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.65 single+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.7143 |
| cluster T=0.65 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 multi+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.7143 |
| cluster T=0.70 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 single+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.7143 |
| cluster T=0.70 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 multi+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.7143 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 7 | 5 | 2 | 28.6% | 0.7143 | 0.7143 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

### 2026-05-13 · topic-07 · Keir Starmer faces internal pressure and calls for resignation in the UK

_source_count=70, audit on=23 / 70_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 15 | 15 | 0 | 0.0% | 1.0000 | 0.6522 |
| cluster T=0.55 multi+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.55 multi+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.55 single+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.55 single+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.60 multi+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.60 multi+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.60 single+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.60 single+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.65 multi+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.65 multi+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.65 single+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.65 single+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.70 multi+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.70 multi+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.70 single+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.70 single+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.75 multi+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.75 multi+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.75 single+finding_level | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |
| cluster T=0.75 single+orphan | 26 | 23 | 3 | 11.5% | 0.8846 | 1.0000 |

### 2026-05-13 · topic-08 · Israel and Lebanon exchange fire as ceasefire efforts remain strained

_source_count=56, audit on=15 / 56_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 12 | 10 | 2 | 16.7% | 0.8333 | 0.6667 |
| cluster T=0.55 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.55 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.55 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.55 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.60 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.60 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.60 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.60 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.65 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.65 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.65 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.65 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.70 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.70 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.70 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.70 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.75 multi+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.75 multi+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.75 single+finding_level | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |
| cluster T=0.75 single+orphan | 24 | 12 | 12 | 50.0% | 0.5000 | 0.8000 |

### 2026-05-13 · topic-09 · South Korea and Australia consider joining naval missions in the Strait of Hormuz

_source_count=54, audit on=21 / 54_

| Config | Retained | On | Off | Off % | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| **baseline** | 3 | 3 | 0 | 0.0% | 1.0000 | 0.1429 |
| cluster T=0.55 multi+finding_level | 9 | 8 | 1 | 11.1% | 0.8889 | 0.3810 |
| cluster T=0.55 multi+orphan | 7 | 6 | 1 | 14.3% | 0.8571 | 0.2857 |
| cluster T=0.55 single+finding_level | 9 | 8 | 1 | 11.1% | 0.8889 | 0.3810 |
| cluster T=0.55 single+orphan | 7 | 6 | 1 | 14.3% | 0.8571 | 0.2857 |
| cluster T=0.60 multi+finding_level | 9 | 8 | 1 | 11.1% | 0.8889 | 0.3810 |
| cluster T=0.60 multi+orphan | 7 | 6 | 1 | 14.3% | 0.8571 | 0.2857 |
| cluster T=0.60 single+finding_level | 9 | 8 | 1 | 11.1% | 0.8889 | 0.3810 |
| cluster T=0.60 single+orphan | 7 | 6 | 1 | 14.3% | 0.8571 | 0.2857 |
| cluster T=0.65 multi+finding_level | 9 | 8 | 1 | 11.1% | 0.8889 | 0.3810 |
| cluster T=0.65 multi+orphan | 7 | 6 | 1 | 14.3% | 0.8571 | 0.2857 |
| cluster T=0.65 single+finding_level | 9 | 8 | 1 | 11.1% | 0.8889 | 0.3810 |
| cluster T=0.65 single+orphan | 7 | 6 | 1 | 14.3% | 0.8571 | 0.2857 |
| cluster T=0.70 multi+finding_level | 3 | 3 | 0 | 0.0% | 1.0000 | 0.1429 |
| cluster T=0.70 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.70 single+finding_level | 3 | 3 | 0 | 0.0% | 1.0000 | 0.1429 |
| cluster T=0.70 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 multi+finding_level | 3 | 3 | 0 | 0.0% | 1.0000 | 0.1429 |
| cluster T=0.75 multi+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |
| cluster T=0.75 single+finding_level | 3 | 3 | 0 | 0.0% | 1.0000 | 0.1429 |
| cluster T=0.75 single+orphan | 0 | 0 | 0 | 0.0% | — | 0.0000 |

## CC recommendation

**Top three cluster-level configurations** by aggregate weighted off-topic % against the 2,542-label audit set, with the one-line trade-off each (recall vs. drift vs. orphan rate):

1. **T=0.75, single+finding_level** — weighted off **28.86%**, recall **0.756**, orphan **75.34%** (3,019/4,007); clusters orphan/single/multi-topic = 731/35/0.
   - **Trade-off:** high recall (+10 pp vs baseline) and the highest precision of any cluster-level row, but only 35 of 766 clusters are non-orphan — the cluster-level work is essentially doing nothing here; 731/766 clusters fall back to Brief 5b's finding-level T=0.55 V1.

2. **T=0.70, single+finding_level** — weighted off **29.66%**, recall **0.793**, orphan **73.00%** (2,925/4,007); clusters orphan/single/multi-topic = 726/40/0.
   - **Trade-off:** small step further into cluster-level territory (40 non-orphan clusters), best recall in the top-3 (+14 pp vs baseline), but the off % climbs as more non-orphan clusters bring in their internal drift.

3. **T=0.70, single+orphan** — weighted off **30.32%**, recall **0.704**, orphan **74.12%** (2,970/4,007); clusters orphan/single/multi-topic = 726/40/0.
   - **Trade-off:** first row without the finding-level safety net — orphan % rises sharply (74% vs 73% with fallback, but recall drops -9 pp because findings inside the 726 orphan clusters get no second-chance individual assignment).


**Brief 5b baseline** (T=0.55 V1 finding-level, current production):
- weighted off **8.23%**, recall **0.655**, orphan **84.95%** (3,404/4,007), single-assigned **598**, multi-assigned **5**.

### Trade-off read

- **Lowest off %** of any cluster-level row: cluster T=0.75 single+finding_level at 28.86% (recall 0.756).
- **Highest recall:** cluster T=0.55 multi+finding_level at recall 0.880 (off 36.41%) — extra recall is bought with substantial drift.
- **Lowest orphan %:** cluster T=0.55 single+finding_level at 69.53% (off 33.92%, recall 0.847).

### Key empirical observations

- **Brief 5b baseline beats every cluster-level row on aggregate off %** by a wide margin (8.23% vs the best cluster-level 28.86%). The cluster-level configurations buy recall (and reduce orphans) at the cost of substantial drift.
- **The top-3 cluster-level configurations are essentially baseline + a thin overlay.** At T=0.70 and T=0.75 in single mode, 726–731 of the 766 clusters orphan; under the `finding_level` fallback their findings are then re-assigned via the production T=0.55 V1 rule, so most of the assignment behaviour at the top of the leaderboard is finding-level.
- **Multi mode does not split thematic-field clusters across topics on the audit days.** The audited-cluster table above shows that for the 30 audited clusters across three days, multi-mode assigns the same number of topics as single-mode (usually 1; never more than 2). The 2026-05-11 Sport-Wochenende cluster (mc-04) lands on **only** topic-09 (Barcelona LaLiga) at every T ≤ 0.70 in both modes; no other sports topic exists in the day's discovered set above its centroid-similarity threshold. Phase 2 will show what that wholesale Barcelona assignment looks like at the finding level.
- **Gravity-trap drift is visible at the audit level.** At T=0.55 single+orphan, topic-02 (Putin/Schröder mediator, 2026-05-11) jumps from baseline 14 retained (11 on / 3 off, 21.4 % off) to 17 retained with 0 on / 17 off (100 % off). The cluster that lands there in single mode (mc-009, the Pistorius Kyiv visit / EU funding cluster) is internally singular per `audit-2026-05-17`, so the drift is between-topic, not within-cluster. Multi-mode adds three more drift clusters, pushing the topic to 74 retained / 62 off-topic (83.8 % off). The same pattern appears on 2026-05-13 topic-03 (Yermak, 100 → 23 retained / 16 off) and topic-01 (Russia-Ukraine drone strikes, 33 → 77 retained / 44 off).
- **Audit-set metrics are conservative for cluster-level.** The 2,542 labels cover only the (finding, topic) pairs the original T=0.30 V1 audit assigned. Cluster-level can promote findings into topics that weren't in the original audit set; those new assignments don't get counted in the off-topic %. So the drift numbers reported here are a lower bound. Phase 2 samples show every finding the configuration assigns, with the audit label visible — that's where the architect sees the full picture.

### CC recommendation for Phase-2 sampling

The brief's instruction is to surface the top three configurations by aggregate weighted off-topic % — that's the ranking above. CC would render samples for all three because they span the design space: **T=0.75 single+finding_level** (the conservative high-T finding-level fallback that wins on the audit numbers but does little cluster-level work), **T=0.70 single+finding_level** (slightly more cluster-level activity at the cost of ~1 pp drift), and **T=0.70 single+orphan** (first row that removes the finding-level safety net — shows the cost of pure cluster-level).

If the architect wants to actually stress-test the cluster-level hypothesis, consider substituting one of the top-3 with a **low-T row** (e.g. T=0.55 multi+finding_level — highest recall row at 36.41 % off, or T=0.55 single+finding_level — lowest orphan at 33.92 % off). Those are the configurations where cluster-level actually does the assignment work; the top-3 are mostly finding-level under the hood. Phase 2 samples on a low-T row would make the editorial trade-off concrete for the Sport-Wochenende and Putin/Schröder cases.

_This is the data CC sees on the audit labels alone. The architect picks the top three for Phase-2 qualitative sampling, then makes the production-pin decision in Phase 3._