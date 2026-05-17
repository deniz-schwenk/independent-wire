# Coherence-stage calibration — V1 baseline

> **Historical / superseded.** This document records the passive coherence-stage measurements taken on the V1 Curator's output (single-pass `CuratorStage` that was removed in the Brief 5 cutover, commit `0135c8f`). The numbers were the substrate for Brief 2's provisional `T=0.30` gravitational threshold calibration. The current V2 calibration is `T=0.55, V=title+summary` per Brief 5b; see [`docs/AUDIT-TIMELINE.md`](../AUDIT-TIMELINE.md) for the full chronology and [`docs/cluster-quality-audit/audit-2026-05-16-recalibrated/`](../cluster-quality-audit/audit-2026-05-16-recalibrated/) for the validation evidence. This file is retained as audit-trail.

- Source state: `output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json`
- Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- fastembed version (pinned): `0.8.0`
- Wall: 32.19 s
- RSS Δ: 948 MB
- Clusters scored: 14
- Findings scored: 1116

## Per-cluster aggregates

| Cluster | n | mean | median | p10 | p90 | min | max | <0.20 | <0.25 | <0.30 | <0.35 | <0.40 | <0.45 | <0.50 | <0.55 | <0.60 | <0.70 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Stalled US-Iran peace negotiations and escalating regional tensions | 1004 | 0.120 | 0.080 | -0.048 | 0.317 | -0.179 | 0.788 | 775 | 838 | 890 | 922 | 944 | 952 | 954 | 958 | 966 | 985 |
| Global hantavirus outbreak linked to MV Hondius cruise ship | 8 | 0.321 | 0.293 | 0.135 | 0.540 | 0.131 | 0.597 | 3 | 4 | 4 | 4 | 5 | 6 | 6 | 7 | 8 | 8 |
| Impeachment of Philippine Vice President Sara Duterte | 3 | 0.299 | 0.045 | -0.035 | 0.735 | -0.055 | 0.908 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| Russia-Ukraine Victory Day ceasefire violations and peace talk proposals | 31 | 0.381 | 0.381 | 0.221 | 0.535 | 0.094 | 0.803 | 3 | 6 | 11 | 13 | 17 | 22 | 26 | 28 | 29 | 29 |
| Macron's 'Africa Forward' summit in Kenya and French-African relations | 12 | 0.369 | 0.376 | 0.182 | 0.550 | 0.171 | 0.748 | 2 | 3 | 5 | 5 | 9 | 10 | 10 | 10 | 11 | 11 |
| Indian Prime Minister Modi's austerity measures amid energy crisis | 17 | 0.143 | 0.064 | -0.056 | 0.478 | -0.104 | 0.682 | 12 | 14 | 14 | 14 | 14 | 15 | 15 | 15 | 16 | 17 |
| Release of former Thai Prime Minister Thaksin Shinawatra | 2 | 0.875 | 0.875 | 0.848 | 0.901 | 0.841 | 0.908 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Keir Starmer's leadership crisis following UK local election losses | 3 | 0.357 | 0.167 | 0.109 | 0.680 | 0.095 | 0.809 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| Trump's upcoming state visit to China and trade negotiations | 6 | 0.243 | 0.206 | -0.067 | 0.589 | -0.077 | 0.751 | 3 | 3 | 3 | 4 | 4 | 5 | 5 | 5 | 5 | 5 |
| Gaza documentary 'Doctors Under Attack' wins BAFTA after BBC rejection | 3 | 0.499 | 0.678 | 0.135 | 0.791 | -0.001 | 0.819 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2 |
| Israeli settler violence and human rights abuses in the West Bank | 12 | 0.249 | 0.176 | 0.047 | 0.536 | -0.013 | 0.561 | 7 | 7 | 8 | 8 | 9 | 9 | 10 | 11 | 12 | 12 |
| Latvian Defense Minister resigns over Ukrainian drone incursions | 3 | 0.277 | 0.312 | 0.131 | 0.408 | 0.086 | 0.432 | 1 | 1 | 1 | 2 | 2 | 3 | 3 | 3 | 3 | 3 |
| Barcelona clinches La Liga title with El Clasico victory | 4 | 0.422 | 0.453 | 0.121 | 0.699 | 0.004 | 0.779 | 1 | 1 | 1 | 1 | 2 | 2 | 2 | 3 | 3 | 3 |
| AI advancements and safety regulations in global tech | 8 | 0.136 | 0.132 | 0.052 | 0.224 | -0.030 | 0.300 | 7 | 7 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 |

## Aggregate score histogram (all clusters, all findings)

```
[-0.10, -0.05)  █████████████████████ 101
[-0.05, +0.00)  ███████████████████████████ 134
[+0.00, +0.05)  ████████████████████████████████████████ 197
[+0.05, +0.10)  ███████████████████████████████ 154
[+0.10, +0.15)  █████████████████████████ 125
[+0.15, +0.20)  ██████████████████████ 108
[+0.20, +0.25)  ██████████████ 70
[+0.25, +0.30)  ████████████ 61
[+0.30, +0.35)  ███████ 36
[+0.35, +0.40)  ███████ 33
[+0.40, +0.45)  ████ 18
[+0.45, +0.50)  █ 7
[+0.50, +0.55)  ██ 9
[+0.55, +0.60)  ███ 13
[+0.60, +0.65)  ██ 10
[+0.65, +0.70)  ██ 11
[+0.70, +0.75)  ██ 9
[+0.75, +0.80)  ███ 14
[+0.80, +0.85)  █ 4
[+0.85, +0.90)   0
[+0.90, +0.95)   2
[+0.95, +1.00)   0
```

## Target-cluster ROC

- Target cluster (index 0): `Stalled US-Iran peace negotiations and escalating regional tensions`
- n_findings: 1004
- score distribution: mean=0.120, median=0.080, p10=-0.048, p90=0.317

### ROC against the dynamic on-topic regex (`src/curator_metrics.py`)

| threshold | TP | FP | FN | TN | precision | recall | F1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.20 | 130 | 99 | 81 | 694 | 0.568 | 0.616 | 0.591 ← |
| 0.25 | 111 | 55 | 100 | 738 | 0.669 | 0.526 | 0.589 |
| 0.30 | 89 | 25 | 122 | 768 | 0.781 | 0.422 | 0.548 |
| 0.35 | 74 | 8 | 137 | 785 | 0.902 | 0.351 | 0.505 |
| 0.40 | 56 | 4 | 155 | 789 | 0.933 | 0.265 | 0.413 |
| 0.45 | 49 | 3 | 162 | 790 | 0.942 | 0.232 | 0.373 |
| 0.50 | 48 | 2 | 163 | 791 | 0.960 | 0.227 | 0.368 |
| 0.55 | 44 | 2 | 167 | 791 | 0.957 | 0.209 | 0.342 |
| 0.60 | 36 | 2 | 175 | 791 | 0.947 | 0.171 | 0.289 |
| 0.70 | 17 | 2 | 194 | 791 | 0.895 | 0.081 | 0.148 |

Best F1 at threshold 0.20: precision=0.568, recall=0.616, F1=0.591

Regex is the heuristic baseline per the brief: ~5–10% FP/FN, directional not absolute. The regex is derived from the target cluster's own title + summary, then matched against each finding's title + summary + description.

### ROC against manual labels (`docs/coherence-filter/_manual-labels-2026-05-11.csv`)

| threshold | TP | FP | FN | TN | precision | recall | F1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.20 | 3 | 8 | 1 | 38 | 0.273 | 0.750 | 0.400 |
| 0.25 | 2 | 5 | 2 | 41 | 0.286 | 0.500 | 0.364 |
| 0.30 | 1 | 2 | 3 | 44 | 0.333 | 0.250 | 0.286 |
| 0.35 | 1 | 0 | 3 | 46 | 1.000 | 0.250 | 0.400 ← |
| 0.40 | 1 | 0 | 3 | 46 | 1.000 | 0.250 | 0.400 |
| 0.45 | 1 | 0 | 3 | 46 | 1.000 | 0.250 | 0.400 |
| 0.50 | 1 | 0 | 3 | 46 | 1.000 | 0.250 | 0.400 |
| 0.55 | 1 | 0 | 3 | 46 | 1.000 | 0.250 | 0.400 |
| 0.60 | 0 | 0 | 4 | 46 | 0.000 | 0.000 | 0.000 |
| 0.70 | 0 | 0 | 4 | 46 | 0.000 | 0.000 | 0.000 |

Best F1 at threshold 0.35: precision=1.000, recall=0.250, F1=0.400

Manual labels are the ground-truth reference. When regex and manual ROCs agree on the best-F1 threshold, the regex heuristic is validated for this dataset.

#### Confusion matrix at F1-optimal manual threshold (0.35)

|  | predicted-keep | predicted-drop |
|---|---:|---:|
| manual on  | 1 (TP) | 3 (FN) |
| manual off | 0 (FP) | 46 (TN) |

## Agreement matrix: regex vs manual labels

On the 50-finding manual-label subset, regex and manual judgement **agree on 43/50 findings (86.0%)**.

|  | manual on | manual off |
|---|---:|---:|
| regex on  | 4 (both on) | 7 (regex over-counts) |
| regex off | 0 (regex under-counts) | 39 (both off) |

**Regex says on-topic, manual says off-topic:**
- `finding-291` — Plot to coerce girl into carrying out terrorist attack in Islamabad thwarted, CM Bugti says
- `finding-478` — India news: Cut fuel use, gold buys and foreign trips, says Modi, as no end in sight to Iran war
- `finding-77` — Israeli soldier killed in Hezbollah drone attack near Lebanon border
- `finding-75` — Hezbollah using fibre optic drones to evade Israeli jamming
- `finding-272` — A Year After Op Sindoor, Pak Army Chief's Unprovoked Threat To India
- `finding-422` — Modi urges Indians to work from home and limit foreign travel as Iran war continues
- `finding-271` — Stock Market Highlights, Sensex Today: Sensex Falls 1,312 Points, Nifty Down 360 As Oil Prices Rally

Reading: regex agrees with manual labels in the majority. Disagreements are the heuristic's failure modes — regex over-counts when peripheral lexical matches creep into the vocabulary; regex under-counts when on-topic findings phrase the topic in vocabulary that didn't make the regex tokens. The agreement rate tells the architect how much trust to place in the daily regex-only comparator on the coherence report.

## Reading guide

- TP = on-topic finding that would be kept (score ≥ threshold)
- FP = off-topic finding that would be kept (= leakage; want low)
- FN = on-topic finding that would be dropped (= regression; want low)
- TN = off-topic finding that would be dropped (= win)
- Best F1 marks the threshold balancing leakage vs regression.
- Single-cluster ROC: directional indicator, not final calibration. Cross-cluster sweep + multi-day production data make the final case.
