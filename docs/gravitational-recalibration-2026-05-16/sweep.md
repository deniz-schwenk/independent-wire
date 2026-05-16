# Gravitational recalibration — parameter sweep

Phase 1 of `TASK-GRAVITATIONAL-RECALIBRATION.md`.

Sweeps the gravitational threshold and topic-centre embedding text against the 2,542 audit labels from `TASK-CLUSTER-QUALITY-AUDIT` (audit at `docs/cluster-quality-audit/audit-2026-05-16/`, HEAD 6d8ffc4).

## Method

- **Thresholds T:** `{0.30, 0.35, 0.40, 0.45, 0.50, 0.55}`.
- **Variants V:** `V1 = title + summary` (production), `V2 = title only`.
- **Per-(T, V) recomputation:** the audited findings' similarities are recomputed against re-embedded topic centres; on/off-topic counts use the audit labels.
- **Full-population diagnostics** (orphan rate, assignments-per-finding distribution): all topics × all findings per day, pre-cap counts plus post-cap multi/single/orphan.
- **PER_FINDING_CAP:** 3 (current production constant; unchanged across the sweep).
- **Day populations:** 2026-05-08 = 1401 / 2026-05-11 = 1201 / 2026-05-13 = 1405; total 4007 findings, 48 topics, 30 audited topics, 2542 audited findings.

## Top-level table

Ranked by weighted off-topic %. Reach (lower is better) and recall (higher is better) compete — read both.

| Rank | T | V | Weighted off % | Mean prec | Mean recall | Multi | Single | Orphan | Orphan % | Topics w/ 0 retained |
|---:|---:|:--|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.55 | V2 | 3.31% | 0.9713 | 0.4703 | 3 | 413 | 3,591 | 89.62% | 0 |
| 2 | 0.55 | V1 | 8.23% | 0.9169 | 0.6552 | 5 | 598 | 3,404 | 84.95% | 0 |
| 3 | 0.50 | V2 | 9.62% | 0.8974 | 0.5892 | 10 | 558 | 3,439 | 85.82% | 0 |
| 4 | 0.50 | V1 | 15.91% | 0.8544 | 0.7702 | 20 | 733 | 3,254 | 81.21% | 0 |
| 5 | 0.45 | V2 | 18.69% | 0.8347 | 0.7222 | 34 | 702 | 3,271 | 81.63% | 0 |
| 6 | 0.45 | V1 | 25.93% | 0.7320 | 0.8523 | 57 | 871 | 3,079 | 76.84% | 0 |
| 7 | 0.40 | V2 | 30.42% | 0.7100 | 0.8168 | 92 | 837 | 3,078 | 76.82% | 0 |
| 8 | 0.40 | V1 | 40.47% | 0.5814 | 0.9190 | 167 | 1,006 | 2,834 | 70.73% | 0 |
| 9 | 0.35 | V2 | 44.12% | 0.5778 | 0.9059 | 238 | 939 | 2,830 | 70.63% | 0 |
| 10 | 0.35 | V1 | 55.60% | 0.4392 | 0.9743 | 394 | 1,093 | 2,520 | 62.89% | 0 |
| 11 | 0.30 | V2 | 56.87% | 0.4401 | 0.9576 | 490 | 1,046 | 2,471 | 61.67% | 0 |
| 12 | 0.30 | V1 | 69.59% | 0.3057 | 1.0000 | 787 | 1,191 | 2,029 | 50.64% | 0 |

## Assignments-per-finding distribution (pre-cap, all topics × all findings)

`PER_FINDING_CAP = 3` would truncate the `4+` bucket to 3. Findings in `0` are orphans at this (T, V).

| T | V | 0 | 1 | 2 | 3 | 4+ | mean assignments/finding (post-cap) |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 2,029 | 1,191 | 521 | 180 | 86 | 0.756 |
| 0.35 | V1 | 2,520 | 1,093 | 315 | 66 | 13 | 0.489 |
| 0.40 | V1 | 2,834 | 1,006 | 152 | 15 | 0 | 0.338 |
| 0.45 | V1 | 3,079 | 871 | 55 | 2 | 0 | 0.246 |
| 0.50 | V1 | 3,254 | 733 | 20 | 0 | 0 | 0.193 |
| 0.55 | V1 | 3,404 | 598 | 5 | 0 | 0 | 0.152 |
| 0.30 | V2 | 2,471 | 1,046 | 363 | 103 | 24 | 0.537 |
| 0.35 | V2 | 2,830 | 939 | 207 | 29 | 2 | 0.361 |
| 0.40 | V2 | 3,078 | 837 | 84 | 8 | 0 | 0.257 |
| 0.45 | V2 | 3,271 | 702 | 34 | 0 | 0 | 0.192 |
| 0.50 | V2 | 3,439 | 558 | 10 | 0 | 0 | 0.144 |
| 0.55 | V2 | 3,591 | 413 | 3 | 0 | 0 | 0.105 |

## Gravity-trap topic movement (per brief watch-item 2)

Gravity-trap = baseline T=0.30 V1 off-topic rate ≥ 80%. This catches Putin/Schröder, Yermak, Ramaphosa, China defense ministers, Latvian defense minister, and Nunes Marques on the three eval days. A configuration that drops aggregate to <30% but leaves these >50% is failing the editorial job. Per-topic off-topic % across all 12 configurations:

### 2026-05-08 · topic-02 · Donald Trump and Lula da Silva meet at White House to relink US-Brazil relations

_source_count=77, audit on-topic=12 / 77_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 77 | 12 | 65 | 84.4% | 0.1558 | 1.0000 |
| 0.35 | V1 | 45 | 12 | 33 | 73.3% | 0.2667 | 1.0000 |
| 0.40 | V1 | 25 | 12 | 13 | 52.0% | 0.4800 | 1.0000 |
| 0.45 | V1 | 17 | 12 | 5 | 29.4% | 0.7059 | 1.0000 |
| 0.50 | V1 | 12 | 12 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.55 | V1 | 12 | 12 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.30 | V2 | 47 | 12 | 35 | 74.5% | 0.2553 | 1.0000 |
| 0.35 | V2 | 22 | 12 | 10 | 45.5% | 0.5455 | 1.0000 |
| 0.40 | V2 | 14 | 12 | 2 | 14.3% | 0.8571 | 1.0000 |
| 0.45 | V2 | 12 | 12 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.50 | V2 | 11 | 11 | 0 | 0.0% | 1.0000 | 0.9167 |
| 0.55 | V2 | 9 | 9 | 0 | 0.0% | 1.0000 | 0.7500 |

### 2026-05-08 · topic-03 · South African Constitutional Court orders Parliament to revisit Cyril Ramaphosa impeachmen

_source_count=75, audit on-topic=5 / 75_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 75 | 5 | 70 | 93.3% | 0.0667 | 1.0000 |
| 0.35 | V1 | 36 | 5 | 31 | 86.1% | 0.1389 | 1.0000 |
| 0.40 | V1 | 20 | 5 | 15 | 75.0% | 0.2500 | 1.0000 |
| 0.45 | V1 | 11 | 5 | 6 | 54.5% | 0.4545 | 1.0000 |
| 0.50 | V1 | 5 | 5 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.55 | V1 | 4 | 4 | 0 | 0.0% | 1.0000 | 0.8000 |
| 0.30 | V2 | 21 | 5 | 16 | 76.2% | 0.2381 | 1.0000 |
| 0.35 | V2 | 10 | 5 | 5 | 50.0% | 0.5000 | 1.0000 |
| 0.40 | V2 | 5 | 5 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.45 | V2 | 5 | 5 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.50 | V2 | 4 | 4 | 0 | 0.0% | 1.0000 | 0.8000 |
| 0.55 | V2 | 4 | 4 | 0 | 0.0% | 1.0000 | 0.8000 |

### 2026-05-08 · topic-05 · Internal crisis hits Real Madrid following training ground altercation

_source_count=49, audit on-topic=8 / 49_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 49 | 8 | 41 | 83.7% | 0.1633 | 1.0000 |
| 0.35 | V1 | 26 | 8 | 18 | 69.2% | 0.3077 | 1.0000 |
| 0.40 | V1 | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| 0.45 | V1 | 9 | 7 | 2 | 22.2% | 0.7778 | 0.8750 |
| 0.50 | V1 | 8 | 7 | 1 | 12.5% | 0.8750 | 0.8750 |
| 0.55 | V1 | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| 0.30 | V2 | 24 | 8 | 16 | 66.7% | 0.3333 | 1.0000 |
| 0.35 | V2 | 14 | 8 | 6 | 42.9% | 0.5714 | 1.0000 |
| 0.40 | V2 | 8 | 6 | 2 | 25.0% | 0.7500 | 0.7500 |
| 0.45 | V2 | 6 | 5 | 1 | 16.7% | 0.8333 | 0.6250 |
| 0.50 | V2 | 5 | 4 | 1 | 20.0% | 0.8000 | 0.5000 |
| 0.55 | V2 | 3 | 3 | 0 | 0.0% | 1.0000 | 0.3750 |

### 2026-05-08 · topic-08 · China sentences former defense ministers to death with reprieve for corruption

_source_count=43, audit on-topic=4 / 43_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 43 | 4 | 39 | 90.7% | 0.0930 | 1.0000 |
| 0.35 | V1 | 20 | 4 | 16 | 80.0% | 0.2000 | 1.0000 |
| 0.40 | V1 | 12 | 4 | 8 | 66.7% | 0.3333 | 1.0000 |
| 0.45 | V1 | 10 | 4 | 6 | 60.0% | 0.4000 | 1.0000 |
| 0.50 | V1 | 7 | 4 | 3 | 42.9% | 0.5714 | 1.0000 |
| 0.55 | V1 | 5 | 3 | 2 | 40.0% | 0.6000 | 0.7500 |
| 0.30 | V2 | 19 | 4 | 15 | 79.0% | 0.2105 | 1.0000 |
| 0.35 | V2 | 14 | 4 | 10 | 71.4% | 0.2857 | 1.0000 |
| 0.40 | V2 | 11 | 4 | 7 | 63.6% | 0.3636 | 1.0000 |
| 0.45 | V2 | 8 | 4 | 4 | 50.0% | 0.5000 | 1.0000 |
| 0.50 | V2 | 5 | 3 | 2 | 40.0% | 0.6000 | 0.7500 |
| 0.55 | V2 | 4 | 3 | 1 | 25.0% | 0.7500 | 0.7500 |

### 2026-05-11 · topic-00 · Russia and Ukraine accuse each other of violating US-brokered ceasefire

_source_count=155, audit on-topic=22 / 155_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 155 | 22 | 133 | 85.8% | 0.1419 | 1.0000 |
| 0.35 | V1 | 106 | 22 | 84 | 79.2% | 0.2075 | 1.0000 |
| 0.40 | V1 | 67 | 20 | 47 | 70.2% | 0.2985 | 0.9091 |
| 0.45 | V1 | 39 | 17 | 22 | 56.4% | 0.4359 | 0.7727 |
| 0.50 | V1 | 25 | 13 | 12 | 48.0% | 0.5200 | 0.5909 |
| 0.55 | V1 | 17 | 11 | 6 | 35.3% | 0.6471 | 0.5000 |
| 0.30 | V2 | 108 | 21 | 87 | 80.6% | 0.1944 | 0.9545 |
| 0.35 | V2 | 79 | 20 | 59 | 74.7% | 0.2532 | 0.9091 |
| 0.40 | V2 | 44 | 17 | 27 | 61.4% | 0.3864 | 0.7727 |
| 0.45 | V2 | 28 | 15 | 13 | 46.4% | 0.5357 | 0.6818 |
| 0.50 | V2 | 16 | 10 | 6 | 37.5% | 0.6250 | 0.4545 |
| 0.55 | V2 | 9 | 9 | 0 | 0.0% | 1.0000 | 0.4091 |

### 2026-05-11 · topic-02 · Vladimir Putin proposes Gerhard Schröder as mediator for Ukraine negotiations

_source_count=134, audit on-topic=12 / 134_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 134 | 12 | 122 | 91.0% | 0.0896 | 1.0000 |
| 0.35 | V1 | 86 | 12 | 74 | 86.0% | 0.1395 | 1.0000 |
| 0.40 | V1 | 56 | 12 | 44 | 78.6% | 0.2143 | 1.0000 |
| 0.45 | V1 | 41 | 12 | 29 | 70.7% | 0.2927 | 1.0000 |
| 0.50 | V1 | 23 | 11 | 12 | 52.2% | 0.4783 | 0.9167 |
| 0.55 | V1 | 14 | 11 | 3 | 21.4% | 0.7857 | 0.9167 |
| 0.30 | V2 | 84 | 12 | 72 | 85.7% | 0.1429 | 1.0000 |
| 0.35 | V2 | 65 | 12 | 53 | 81.5% | 0.1846 | 1.0000 |
| 0.40 | V2 | 41 | 11 | 30 | 73.2% | 0.2683 | 0.9167 |
| 0.45 | V2 | 26 | 11 | 15 | 57.7% | 0.4231 | 0.9167 |
| 0.50 | V2 | 15 | 11 | 4 | 26.7% | 0.7333 | 0.9167 |
| 0.55 | V2 | 11 | 11 | 0 | 0.0% | 1.0000 | 0.9167 |

### 2026-05-11 · topic-07 · Narges Mohammadi released from Iranian prison for medical treatment

_source_count=45, audit on-topic=8 / 45_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 45 | 8 | 37 | 82.2% | 0.1778 | 1.0000 |
| 0.35 | V1 | 19 | 8 | 11 | 57.9% | 0.4211 | 1.0000 |
| 0.40 | V1 | 14 | 8 | 6 | 42.9% | 0.5714 | 1.0000 |
| 0.45 | V1 | 12 | 8 | 4 | 33.3% | 0.6667 | 1.0000 |
| 0.50 | V1 | 9 | 8 | 1 | 11.1% | 0.8889 | 1.0000 |
| 0.55 | V1 | 8 | 8 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.30 | V2 | 18 | 8 | 10 | 55.6% | 0.4444 | 1.0000 |
| 0.35 | V2 | 14 | 8 | 6 | 42.9% | 0.5714 | 1.0000 |
| 0.40 | V2 | 14 | 8 | 6 | 42.9% | 0.5714 | 1.0000 |
| 0.45 | V2 | 10 | 7 | 3 | 30.0% | 0.7000 | 0.8750 |
| 0.50 | V2 | 10 | 7 | 3 | 30.0% | 0.7000 | 0.8750 |
| 0.55 | V2 | 7 | 6 | 1 | 14.3% | 0.8571 | 0.7500 |

### 2026-05-11 · topic-08 · Latvian Defense Minister resigns following Ukrainian drone incursions

_source_count=43, audit on-topic=8 / 43_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 43 | 8 | 35 | 81.4% | 0.1860 | 1.0000 |
| 0.35 | V1 | 28 | 8 | 20 | 71.4% | 0.2857 | 1.0000 |
| 0.40 | V1 | 16 | 8 | 8 | 50.0% | 0.5000 | 1.0000 |
| 0.45 | V1 | 9 | 6 | 3 | 33.3% | 0.6667 | 0.7500 |
| 0.50 | V1 | 6 | 5 | 1 | 16.7% | 0.8333 | 0.6250 |
| 0.55 | V1 | 6 | 5 | 1 | 16.7% | 0.8333 | 0.6250 |
| 0.30 | V2 | 33 | 8 | 25 | 75.8% | 0.2424 | 1.0000 |
| 0.35 | V2 | 22 | 8 | 14 | 63.6% | 0.3636 | 1.0000 |
| 0.40 | V2 | 15 | 8 | 7 | 46.7% | 0.5333 | 1.0000 |
| 0.45 | V2 | 8 | 6 | 2 | 25.0% | 0.7500 | 0.7500 |
| 0.50 | V2 | 5 | 5 | 0 | 0.0% | 1.0000 | 0.6250 |
| 0.55 | V2 | 5 | 5 | 0 | 0.0% | 1.0000 | 0.6250 |

### 2026-05-13 · topic-03 · Anti-corruption probe in Ukraine targets former presidential aide Andriy Yermak

_source_count=107, audit on-topic=7 / 107_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 107 | 7 | 100 | 93.5% | 0.0654 | 1.0000 |
| 0.35 | V1 | 51 | 7 | 44 | 86.3% | 0.1373 | 1.0000 |
| 0.40 | V1 | 21 | 7 | 14 | 66.7% | 0.3333 | 1.0000 |
| 0.45 | V1 | 11 | 7 | 4 | 36.4% | 0.6364 | 1.0000 |
| 0.50 | V1 | 8 | 6 | 2 | 25.0% | 0.7500 | 0.8571 |
| 0.55 | V1 | 6 | 6 | 0 | 0.0% | 1.0000 | 0.8571 |
| 0.30 | V2 | 58 | 7 | 51 | 87.9% | 0.1207 | 1.0000 |
| 0.35 | V2 | 34 | 7 | 27 | 79.4% | 0.2059 | 1.0000 |
| 0.40 | V2 | 14 | 7 | 7 | 50.0% | 0.5000 | 1.0000 |
| 0.45 | V2 | 8 | 6 | 2 | 25.0% | 0.7500 | 0.8571 |
| 0.50 | V2 | 6 | 6 | 0 | 0.0% | 1.0000 | 0.8571 |
| 0.55 | V2 | 1 | 1 | 0 | 0.0% | 1.0000 | 0.1429 |

### 2026-05-13 · topic-05 · Massive protests in Argentina against university funding cuts by Javier Milei

_source_count=84, audit on-topic=7 / 84_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 84 | 7 | 77 | 91.7% | 0.0833 | 1.0000 |
| 0.35 | V1 | 44 | 7 | 37 | 84.1% | 0.1591 | 1.0000 |
| 0.40 | V1 | 20 | 7 | 13 | 65.0% | 0.3500 | 1.0000 |
| 0.45 | V1 | 10 | 7 | 3 | 30.0% | 0.7000 | 1.0000 |
| 0.50 | V1 | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.55 | V1 | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.30 | V2 | 58 | 7 | 51 | 87.9% | 0.1207 | 1.0000 |
| 0.35 | V2 | 28 | 7 | 21 | 75.0% | 0.2500 | 1.0000 |
| 0.40 | V2 | 14 | 7 | 7 | 50.0% | 0.5000 | 1.0000 |
| 0.45 | V2 | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.50 | V2 | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |
| 0.55 | V2 | 7 | 7 | 0 | 0.0% | 1.0000 | 1.0000 |

### 2026-05-13 · topic-06 · Nunes Marques takes office as President of Brazil's Superior Electoral Court

_source_count=81, audit on-topic=7 / 81_ 

| T | V | Retained | On | Off | Off % | Precision | Recall |
|---:|:--|---:|---:|---:|---:|---:|---:|
| 0.30 | V1 | 81 | 7 | 74 | 91.4% | 0.0864 | 1.0000 |
| 0.35 | V1 | 38 | 7 | 31 | 81.6% | 0.1842 | 1.0000 |
| 0.40 | V1 | 21 | 6 | 15 | 71.4% | 0.2857 | 0.8571 |
| 0.45 | V1 | 11 | 5 | 6 | 54.5% | 0.4545 | 0.7143 |
| 0.50 | V1 | 9 | 5 | 4 | 44.4% | 0.5556 | 0.7143 |
| 0.55 | V1 | 7 | 5 | 2 | 28.6% | 0.7143 | 0.7143 |
| 0.30 | V2 | 34 | 6 | 28 | 82.3% | 0.1765 | 0.8571 |
| 0.35 | V2 | 16 | 4 | 12 | 75.0% | 0.2500 | 0.5714 |
| 0.40 | V2 | 8 | 3 | 5 | 62.5% | 0.3750 | 0.4286 |
| 0.45 | V2 | 4 | 3 | 1 | 25.0% | 0.7500 | 0.4286 |
| 0.50 | V2 | 2 | 1 | 1 | 50.0% | 0.5000 | 0.1429 |
| 0.55 | V2 | 1 | 1 | 0 | 0.0% | 1.0000 | 0.1429 |

## Per-topic detail — all 30 audited topics across 12 configurations

For each topic, off-topic % at each (T, V). The lower row of each topic also shows the retained count, so you can see when a configuration empties the bucket.

### 2026-05-08 · topic-00 · US and Iran maintain diplomatic dialogue despite exchange of fire in Strait of Hormuz

_source_count=195, audit on=88 / 195_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 54.9% | 43.4% | 28.0% | 11.9% | 7.8% | 7.3% | 36.8% | 24.2% | 16.2% | 7.5% | 5.6% | 0.0% |
| retained | 195 | 143 | 100 | 67 | 51 | 41 | 125 | 91 | 68 | 53 | 36 | 20 |
| precision | 0.4513 | 0.5664 | 0.7200 | 0.8806 | 0.9216 | 0.9268 | 0.6320 | 0.7582 | 0.8382 | 0.9245 | 0.9444 | 1.0000 |

### 2026-05-08 · topic-01 · Russia and Ukraine trade accusations over Victory Day ceasefire violations

_source_count=163, audit on=37 / 163_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 77.3% | 72.1% | 61.7% | 48.5% | 43.4% | 37.5% | 73.9% | 67.0% | 58.0% | 54.7% | 36.4% | 12.5% |
| retained | 163 | 129 | 94 | 68 | 53 | 32 | 142 | 109 | 81 | 53 | 33 | 16 |
| precision | 0.2270 | 0.2791 | 0.3830 | 0.5147 | 0.5660 | 0.6250 | 0.2606 | 0.3303 | 0.4198 | 0.4528 | 0.6364 | 0.8750 |

### 2026-05-08 · topic-02 · Donald Trump and Lula da Silva meet at White House to relink US-Brazil relations

_source_count=77, audit on=12 / 77_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 84.4% | 73.3% | 52.0% | 29.4% | 0.0% | 0.0% | 74.5% | 45.5% | 14.3% | 0.0% | 0.0% | 0.0% |
| retained | 77 | 45 | 25 | 17 | 12 | 12 | 47 | 22 | 14 | 12 | 11 | 9 |
| precision | 0.1558 | 0.2667 | 0.4800 | 0.7059 | 1.0000 | 1.0000 | 0.2553 | 0.5455 | 0.8571 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-08 · topic-03 · South African Constitutional Court orders Parliament to revisit Cyril Ramaphosa impeachmen

_source_count=75, audit on=5 / 75_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 93.3% | 86.1% | 75.0% | 54.5% | 0.0% | 0.0% | 76.2% | 50.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| retained | 75 | 36 | 20 | 11 | 5 | 4 | 21 | 10 | 5 | 5 | 4 | 4 |
| precision | 0.0667 | 0.1389 | 0.2500 | 0.4545 | 1.0000 | 1.0000 | 0.2381 | 0.5000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-08 · topic-04 · Hantavirus outbreak on cruise ship MV Hondius triggers international health response

_source_count=56, audit on=47 / 56_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 16.1% | 8.2% | 4.5% | 4.9% | 6.1% | 0.0% | 11.3% | 6.2% | 6.8% | 4.8% | 3.1% | 0.0% |
| retained | 56 | 49 | 44 | 41 | 33 | 25 | 53 | 48 | 44 | 42 | 32 | 24 |
| precision | 0.8393 | 0.9184 | 0.9545 | 0.9512 | 0.9394 | 1.0000 | 0.8868 | 0.9375 | 0.9318 | 0.9524 | 0.9688 | 1.0000 |

### 2026-05-08 · topic-05 · Internal crisis hits Real Madrid following training ground altercation

_source_count=49, audit on=8 / 49_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 83.7% | 69.2% | 50.0% | 22.2% | 12.5% | 20.0% | 66.7% | 42.9% | 25.0% | 16.7% | 20.0% | 0.0% |
| retained | 49 | 26 | 16 | 9 | 8 | 5 | 24 | 14 | 8 | 6 | 5 | 3 |
| precision | 0.1633 | 0.3077 | 0.5000 | 0.7778 | 0.8750 | 0.8000 | 0.3333 | 0.5714 | 0.7500 | 0.8333 | 0.8000 | 1.0000 |

### 2026-05-08 · topic-06 · Tamil Nadu government formation proceeds with support for Vijay's TVK party

_source_count=47, audit on=12 / 47_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 74.5% | 64.5% | 16.7% | 18.2% | 0.0% | 0.0% | 52.4% | 33.3% | 14.3% | 0.0% | 0.0% | 0.0% |
| retained | 47 | 31 | 12 | 11 | 7 | 3 | 21 | 12 | 7 | 5 | 3 | 3 |
| precision | 0.2553 | 0.3548 | 0.8333 | 0.8182 | 1.0000 | 1.0000 | 0.4762 | 0.6667 | 0.8571 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-08 · topic-07 · US trade court strikes down Donald Trump's 10 percent universal tariffs

_source_count=47, audit on=21 / 47_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 55.3% | 38.2% | 22.2% | 8.7% | 4.5% | 0.0% | 41.7% | 22.2% | 4.5% | 4.5% | 0.0% | 0.0% |
| retained | 47 | 34 | 27 | 23 | 22 | 19 | 36 | 27 | 22 | 22 | 20 | 15 |
| precision | 0.4468 | 0.6176 | 0.7778 | 0.9130 | 0.9545 | 1.0000 | 0.5833 | 0.7778 | 0.9545 | 0.9545 | 1.0000 | 1.0000 |

### 2026-05-08 · topic-08 · China sentences former defense ministers to death with reprieve for corruption

_source_count=43, audit on=4 / 43_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 90.7% | 80.0% | 66.7% | 60.0% | 42.9% | 40.0% | 79.0% | 71.4% | 63.6% | 50.0% | 40.0% | 25.0% |
| retained | 43 | 20 | 12 | 10 | 7 | 5 | 19 | 14 | 11 | 8 | 5 | 4 |
| precision | 0.0930 | 0.2000 | 0.3333 | 0.4000 | 0.5714 | 0.6000 | 0.2105 | 0.2857 | 0.3636 | 0.5000 | 0.6000 | 0.7500 |

### 2026-05-08 · topic-09 · Pope Leo XIV marks first anniversary amid tensions with US administration

_source_count=33, audit on=12 / 33_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 63.6% | 45.5% | 20.0% | 8.3% | 0.0% | 0.0% | 42.9% | 25.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| retained | 33 | 22 | 15 | 12 | 9 | 8 | 21 | 16 | 7 | 7 | 4 | 2 |
| precision | 0.3636 | 0.5455 | 0.8000 | 0.9167 | 1.0000 | 1.0000 | 0.5714 | 0.7500 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-11 · topic-00 · Russia and Ukraine accuse each other of violating US-brokered ceasefire

_source_count=155, audit on=22 / 155_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 85.8% | 79.2% | 70.2% | 56.4% | 48.0% | 35.3% | 80.6% | 74.7% | 61.4% | 46.4% | 37.5% | 0.0% |
| retained | 155 | 106 | 67 | 39 | 25 | 17 | 108 | 79 | 44 | 28 | 16 | 9 |
| precision | 0.1419 | 0.2075 | 0.2985 | 0.4359 | 0.5200 | 0.6471 | 0.1944 | 0.2532 | 0.3864 | 0.5357 | 0.6250 | 1.0000 |

### 2026-05-11 · topic-01 · Donald Trump rejects Iran's response to US peace proposal as unacceptable

_source_count=144, audit on=71 / 144_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 50.7% | 36.5% | 25.9% | 14.3% | 10.6% | 6.7% | 38.2% | 23.0% | 12.7% | 6.5% | 7.0% | 5.6% |
| retained | 144 | 107 | 85 | 63 | 47 | 45 | 102 | 74 | 55 | 46 | 43 | 36 |
| precision | 0.4931 | 0.6355 | 0.7412 | 0.8571 | 0.8936 | 0.9333 | 0.6176 | 0.7703 | 0.8727 | 0.9348 | 0.9302 | 0.9444 |

### 2026-05-11 · topic-02 · Vladimir Putin proposes Gerhard Schröder as mediator for Ukraine negotiations

_source_count=134, audit on=12 / 134_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 91.0% | 86.0% | 78.6% | 70.7% | 52.2% | 21.4% | 85.7% | 81.5% | 73.2% | 57.7% | 26.7% | 0.0% |
| retained | 134 | 86 | 56 | 41 | 23 | 14 | 84 | 65 | 41 | 26 | 15 | 11 |
| precision | 0.0896 | 0.1395 | 0.2143 | 0.2927 | 0.4783 | 0.7857 | 0.1429 | 0.1846 | 0.2683 | 0.4231 | 0.7333 | 1.0000 |

### 2026-05-11 · topic-03 · South Korean vessel damaged by explosion in the Strait of Hormuz

_source_count=70, audit on=28 / 70_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 60.0% | 43.2% | 24.0% | 15.8% | 6.7% | 0.0% | 41.9% | 22.2% | 23.1% | 0.0% | 0.0% | 0.0% |
| retained | 70 | 44 | 25 | 19 | 15 | 8 | 31 | 18 | 13 | 5 | 3 | 3 |
| precision | 0.4000 | 0.5682 | 0.7600 | 0.8421 | 0.9333 | 1.0000 | 0.5806 | 0.7778 | 0.7692 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-11 · topic-04 · Hantavirus outbreak on MV Hondius cruise ship triggers international health alerts

_source_count=65, audit on=56 / 65_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 13.8% | 1.8% | 0.0% | 0.0% | 0.0% | 0.0% | 10.0% | 1.9% | 0.0% | 0.0% | 0.0% | 0.0% |
| retained | 65 | 55 | 50 | 46 | 39 | 33 | 60 | 53 | 50 | 39 | 33 | 24 |
| precision | 0.8615 | 0.9818 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9000 | 0.9811 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-11 · topic-05 · Emmanuel Macron visits Kenya for Africa Forward economic summit

_source_count=48, audit on=10 / 48_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 79.2% | 58.3% | 44.4% | 23.1% | 0.0% | 0.0% | 65.5% | 33.3% | 23.1% | 9.1% | 0.0% | 0.0% |
| retained | 48 | 24 | 18 | 13 | 10 | 9 | 29 | 15 | 13 | 11 | 8 | 8 |
| precision | 0.2083 | 0.4167 | 0.5556 | 0.7692 | 1.0000 | 1.0000 | 0.3448 | 0.6667 | 0.7692 | 0.9091 | 1.0000 | 1.0000 |

### 2026-05-11 · topic-06 · Donald Trump prepares for state visit to China amid trade tensions

_source_count=46, audit on=22 / 46_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 52.2% | 31.2% | 24.0% | 15.0% | 5.6% | 0.0% | 46.3% | 28.6% | 20.8% | 19.1% | 6.2% | 6.7% |
| retained | 46 | 32 | 25 | 20 | 18 | 15 | 41 | 28 | 24 | 21 | 16 | 15 |
| precision | 0.4783 | 0.6875 | 0.7600 | 0.8500 | 0.9444 | 1.0000 | 0.5366 | 0.7143 | 0.7917 | 0.8095 | 0.9375 | 0.9333 |

### 2026-05-11 · topic-07 · Narges Mohammadi released from Iranian prison for medical treatment

_source_count=45, audit on=8 / 45_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 82.2% | 57.9% | 42.9% | 33.3% | 11.1% | 0.0% | 55.6% | 42.9% | 42.9% | 30.0% | 30.0% | 14.3% |
| retained | 45 | 19 | 14 | 12 | 9 | 8 | 18 | 14 | 14 | 10 | 10 | 7 |
| precision | 0.1778 | 0.4211 | 0.5714 | 0.6667 | 0.8889 | 1.0000 | 0.4444 | 0.5714 | 0.5714 | 0.7000 | 0.7000 | 0.8571 |

### 2026-05-11 · topic-08 · Latvian Defense Minister resigns following Ukrainian drone incursions

_source_count=43, audit on=8 / 43_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 81.4% | 71.4% | 50.0% | 33.3% | 16.7% | 16.7% | 75.8% | 63.6% | 46.7% | 25.0% | 0.0% | 0.0% |
| retained | 43 | 28 | 16 | 9 | 6 | 6 | 33 | 22 | 15 | 8 | 5 | 5 |
| precision | 0.1860 | 0.2857 | 0.5000 | 0.6667 | 0.8333 | 0.8333 | 0.2424 | 0.3636 | 0.5333 | 0.7500 | 1.0000 | 1.0000 |

### 2026-05-11 · topic-09 · Barcelona wins La Liga title after victory over Real Madrid

_source_count=42, audit on=15 / 42_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 64.3% | 41.7% | 40.0% | 21.4% | 20.0% | 0.0% | 45.8% | 29.4% | 21.4% | 9.1% | 0.0% | 0.0% |
| retained | 42 | 24 | 20 | 14 | 10 | 8 | 24 | 17 | 14 | 11 | 7 | 5 |
| precision | 0.3571 | 0.5833 | 0.6000 | 0.7857 | 0.8000 | 1.0000 | 0.5417 | 0.7059 | 0.7857 | 0.9091 | 1.0000 | 1.0000 |

### 2026-05-13 · topic-00 · Escalating costs and military risks threaten Middle East truce between US and Iran

_source_count=162, audit on=62 / 162_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 61.7% | 50.9% | 37.0% | 25.0% | 16.0% | 8.3% | 58.5% | 54.1% | 40.3% | 28.0% | 19.4% | 22.2% |
| retained | 162 | 108 | 73 | 44 | 25 | 12 | 147 | 122 | 77 | 50 | 31 | 18 |
| precision | 0.3827 | 0.4907 | 0.6301 | 0.7500 | 0.8400 | 0.9167 | 0.4150 | 0.4590 | 0.5974 | 0.7200 | 0.8065 | 0.7778 |

### 2026-05-13 · topic-01 · Ukraine and Russia exchange long-range drone strikes on energy and military infrastructure

_source_count=137, audit on=34 / 137_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 75.2% | 67.3% | 57.5% | 46.8% | 34.0% | 9.1% | 70.4% | 62.5% | 45.9% | 31.1% | 3.9% | 0.0% |
| retained | 137 | 104 | 80 | 62 | 47 | 33 | 115 | 88 | 61 | 45 | 26 | 18 |
| precision | 0.2482 | 0.3269 | 0.4250 | 0.5323 | 0.6596 | 0.9091 | 0.2957 | 0.3750 | 0.5410 | 0.6889 | 0.9615 | 1.0000 |

### 2026-05-13 · topic-02 · Donald Trump arrives in China for high-stakes summit with Xi Jinping

_source_count=125, audit on=77 / 125_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 38.4% | 27.4% | 11.9% | 5.7% | 1.6% | 1.8% | 22.7% | 6.5% | 3.0% | 0.0% | 0.0% | 0.0% |
| retained | 125 | 106 | 84 | 70 | 64 | 55 | 97 | 77 | 66 | 58 | 51 | 42 |
| precision | 0.6160 | 0.7264 | 0.8810 | 0.9429 | 0.9844 | 0.9818 | 0.7732 | 0.9351 | 0.9697 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-13 · topic-03 · Anti-corruption probe in Ukraine targets former presidential aide Andriy Yermak

_source_count=107, audit on=7 / 107_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 93.5% | 86.3% | 66.7% | 36.4% | 25.0% | 0.0% | 87.9% | 79.4% | 50.0% | 25.0% | 0.0% | 0.0% |
| retained | 107 | 51 | 21 | 11 | 8 | 6 | 58 | 34 | 14 | 8 | 6 | 1 |
| precision | 0.0654 | 0.1373 | 0.3333 | 0.6364 | 0.7500 | 1.0000 | 0.1207 | 0.2059 | 0.5000 | 0.7500 | 1.0000 | 1.0000 |

### 2026-05-13 · topic-04 · Emmanuel Macron seeks renewed partnerships during Africa Forward summit in Kenya

_source_count=89, audit on=22 / 89_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 75.3% | 58.8% | 41.7% | 19.2% | 0.0% | 0.0% | 47.6% | 23.1% | 13.0% | 0.0% | 0.0% | 0.0% |
| retained | 89 | 51 | 36 | 26 | 20 | 19 | 42 | 26 | 23 | 15 | 11 | 5 |
| precision | 0.2472 | 0.4118 | 0.5833 | 0.8077 | 1.0000 | 1.0000 | 0.5238 | 0.7692 | 0.8696 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-13 · topic-05 · Massive protests in Argentina against university funding cuts by Javier Milei

_source_count=84, audit on=7 / 84_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 91.7% | 84.1% | 65.0% | 30.0% | 0.0% | 0.0% | 87.9% | 75.0% | 50.0% | 0.0% | 0.0% | 0.0% |
| retained | 84 | 44 | 20 | 10 | 7 | 7 | 58 | 28 | 14 | 7 | 7 | 7 |
| precision | 0.0833 | 0.1591 | 0.3500 | 0.7000 | 1.0000 | 1.0000 | 0.1207 | 0.2500 | 0.5000 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-13 · topic-06 · Nunes Marques takes office as President of Brazil's Superior Electoral Court

_source_count=81, audit on=7 / 81_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 91.4% | 81.6% | 71.4% | 54.5% | 44.4% | 28.6% | 82.3% | 75.0% | 62.5% | 25.0% | 50.0% | 0.0% |
| retained | 81 | 38 | 21 | 11 | 9 | 7 | 34 | 16 | 8 | 4 | 2 | 1 |
| precision | 0.0864 | 0.1842 | 0.2857 | 0.4545 | 0.5556 | 0.7143 | 0.1765 | 0.2500 | 0.3750 | 0.7500 | 0.5000 | 1.0000 |

### 2026-05-13 · topic-07 · Keir Starmer faces internal pressure and calls for resignation in the UK

_source_count=70, audit on=23 / 70_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 67.1% | 36.1% | 11.5% | 0.0% | 0.0% | 0.0% | 4.5% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| retained | 70 | 36 | 26 | 21 | 20 | 15 | 22 | 21 | 15 | 14 | 12 | 9 |
| precision | 0.3286 | 0.6389 | 0.8846 | 1.0000 | 1.0000 | 1.0000 | 0.9545 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

### 2026-05-13 · topic-08 · Israel and Lebanon exchange fire as ceasefire efforts remain strained

_source_count=56, audit on=15 / 56_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 73.2% | 61.5% | 56.2% | 36.4% | 27.8% | 16.7% | 65.9% | 58.8% | 45.8% | 31.2% | 22.2% | 0.0% |
| retained | 56 | 39 | 32 | 22 | 18 | 12 | 44 | 34 | 24 | 16 | 9 | 6 |
| precision | 0.2679 | 0.3846 | 0.4375 | 0.6364 | 0.7222 | 0.8333 | 0.3409 | 0.4118 | 0.5417 | 0.6875 | 0.7778 | 1.0000 |

### 2026-05-13 · topic-09 · South Korea and Australia consider joining naval missions in the Strait of Hormuz

_source_count=54, audit on=21 / 54_

| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| off % | 61.1% | 40.6% | 40.0% | 0.0% | 0.0% | 0.0% | 51.2% | 43.3% | 31.6% | 14.3% | 0.0% | 0.0% |
| retained | 54 | 32 | 20 | 11 | 8 | 3 | 41 | 30 | 19 | 7 | 4 | 2 |
| precision | 0.3889 | 0.5938 | 0.6000 | 1.0000 | 1.0000 | 1.0000 | 0.4878 | 0.5667 | 0.6842 | 0.8571 | 1.0000 | 1.0000 |

## CC recommendation

**Top three configurations by aggregate weighted off-topic %** (the ranking the brief asks for):

1. **T=0.55, V2** — weighted off=3.31%, mean recall=0.470, orphan%=89.6%, max gravity-trap off=25.0%, min gravity-trap retained=1.
   - Per-trap movement: 2026-05-08/topic-02=0% (n_r=9), 2026-05-08/topic-03=0% (n_r=4), 2026-05-08/topic-05=0% (n_r=3), 2026-05-08/topic-08=25% (n_r=4), 2026-05-11/topic-00=0% (n_r=9), 2026-05-11/topic-02=0% (n_r=11), 2026-05-11/topic-07=14% (n_r=7), 2026-05-11/topic-08=0% (n_r=5), 2026-05-13/topic-03=0% (n_r=1), 2026-05-13/topic-05=0% (n_r=7), 2026-05-13/topic-06=0% (n_r=1)

2. **T=0.55, V1** — weighted off=8.23%, mean recall=0.655, orphan%=85.0%, max gravity-trap off=40.0%, min gravity-trap retained=4.
   - Per-trap movement: 2026-05-08/topic-02=0% (n_r=12), 2026-05-08/topic-03=0% (n_r=4), 2026-05-08/topic-05=20% (n_r=5), 2026-05-08/topic-08=40% (n_r=5), 2026-05-11/topic-00=35% (n_r=17), 2026-05-11/topic-02=21% (n_r=14), 2026-05-11/topic-07=0% (n_r=8), 2026-05-11/topic-08=17% (n_r=6), 2026-05-13/topic-03=0% (n_r=6), 2026-05-13/topic-05=0% (n_r=7), 2026-05-13/topic-06=29% (n_r=7)

3. **T=0.50, V2** — weighted off=9.62%, mean recall=0.589, orphan%=85.8%, max gravity-trap off=50.0%, min gravity-trap retained=2.
   - Per-trap movement: 2026-05-08/topic-02=0% (n_r=11), 2026-05-08/topic-03=0% (n_r=4), 2026-05-08/topic-05=20% (n_r=5), 2026-05-08/topic-08=40% (n_r=5), 2026-05-11/topic-00=38% (n_r=16), 2026-05-11/topic-02=27% (n_r=15), 2026-05-11/topic-07=30% (n_r=10), 2026-05-11/topic-08=0% (n_r=5), 2026-05-13/topic-03=0% (n_r=6), 2026-05-13/topic-05=0% (n_r=7), 2026-05-13/topic-06=50% (n_r=2)

Baseline T=0.30 V1 (current production) — weighted off **69.59%**, recall 1.000, orphan 50.6%, max gravity-trap off=93.5%.

### Dual-constraint read

The brief sets two thresholds: aggregate weighted off-topic **< 30 %** and **no gravity-trap topic above 50 % off-topic**. Configurations that satisfy both, ranked by ascending weighted off:

| Rank | T | V | Weighted off % | Max trap off % | Mean recall | Orphan % | Min trap retained |
|---:|---:|:--|---:|---:|---:|---:|---:|
| 1 | 0.55 | V2 | 3.31% | 25.0% | 0.470 | 89.6% | 1 |
| 2 | 0.55 | V1 | 8.23% | 40.0% | 0.655 | 85.0% | 4 |
| 3 | 0.50 | V2 | 9.62% | 50.0% | 0.589 | 85.8% | 2 |

**Reading the trade-off.** Raising T tightens precision at the cost of recall. V2 (title-only) collapses faster than V1 because the title has less semantic surface area — at high T the gravity-trap small-core topics (Yermak, Nunes Marques) drop to retained=1, which is below the editorial-viability floor. T=0.55 V2 minimises the aggregate (3.31%) but at recall 0.47 it loses more than half the on-topic content; min trap retained = 1. T=0.55 V1 holds recall at 0.66 with max-trap off 40.0% and min trap retained 4. T=0.50 V2 sits between them at recall 0.59 with max-trap off 50.0% (Nunes Marques exactly on the 50% line, retained=2).

**CC's recommendation.** Surface T=0.55 V2, T=0.55 V1, and T=0.50 V2 for qualitative Phase-2 sampling — they are the three configurations that satisfy the brief's dual-constraint test and the top three by weighted off-topic %. If CC had to pick one without seeing the samples, **T=0.55 V1** is the best balance on the numbers: aggregate 8.23%, gravity-trap max 40.0%, recall 0.66, every gravity-trap small-core topic retains ≥4 findings. T=0.50 V2 is the runner-up — same dual-constraint pass, lower recall, but the title-only centre narrows the embedding anchor in a way the architect may prefer editorially. T=0.55 V2 is the aggressive choice: strongest aggregate, but Yermak and Nunes Marques fall to one finding each — a small-core erosion the architect should see in the Phase-2 samples before choosing.

This is the data CC sees. The architect picks the configuration after reading the qualitative samples in Phase 2.