# Cluster-quality re-audit — cross-day summary

Recalibrated at **T=0.55, V=title+summary** (per architect's Phase-2 pick).

## Acceptance gates (per brief)

- Aggregate weighted off-topic rate **< 30 %** target: **8.23 %** PASS
- **No** audited top-10 topic above 50 % off-topic: 0 topic(s) above the line PASS

## Baseline vs recalibrated

| Metric | Baseline (T=0.30 V1, original audit) | Recalibrated (T=0.55 V1) | Δ |
|---|---:|---:|---:|
| Weighted off-topic rate | 69.59 % | **8.23 %** | -61.36 pp |
| Simple-mean off-topic rate | 69.43 % | **8.31 %** | -61.12 pp |
| Findings audited | 2,542 | **486** | -2,056 (fewer findings retained at higher T) |

## Per-day breakdown

| Day | n_audited | n_off | weighted off % | simple-mean off % |
|---|---:|---:|---:|---:|
| 2026-05-08 | 154 | 18 | **11.69 %** | 10.48 % |
| 2026-05-11 | 163 | 13 | **7.98 %** | 8.01 % |
| 2026-05-13 | 169 | 9 | **5.33 %** | 6.45 % |
| **Cross-day** | **486** | **40** | **8.23 %** | **8.31 %** |

## Topics still above 50 % off-topic (after recalibration)

_None._ Every audited top-10 topic per day sits at or below 50 % off-topic.

## Per-day reports

- [`2026-05-08.md`](2026-05-08.md)
- [`2026-05-11.md`](2026-05-11.md)
- [`2026-05-13.md`](2026-05-13.md)
