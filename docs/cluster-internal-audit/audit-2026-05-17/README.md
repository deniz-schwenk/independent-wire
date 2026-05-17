# Cluster-internal-coherence audit — cross-day summary

Audit of the top-10 largest micro-clusters produced by Brief 1's
`pre_cluster_findings` (`distance_threshold=0.7`, `linkage='average'`,
`metric='cosine'`) on three eval datasets. For each cluster the auditor
read every finding title, formed a one-sentence hypothesis of the cluster's
apparent story (or wrote a "no apparent single story" sentinel when the
titles did not converge), then labelled every finding on-topic / off-topic
against that hypothesis. Conservative borderline rule: same-actor-different-story,
tangential mention, multi-topic news roundup → off-topic.

Brief: [`TASK-CLUSTER-INTERNAL-AUDIT.md`](../../../TASK-CLUSTER-INTERNAL-AUDIT.md)
(architect-local; gitignored). Architectural context:
[`docs/ADR-CURATOR-TRIPLE-STAGE.md`](../../ADR-CURATOR-TRIPLE-STAGE.md);
chronology: [`docs/AUDIT-TIMELINE.md`](../../AUDIT-TIMELINE.md).

## Cross-day aggregate

| Metric | Value |
|---|---:|
| Findings audited | **1,233** |
| Off-topic | **118** |
| Weighted off-topic rate (per-finding) | **9.57 %** |
| Simple-mean off-topic rate (per-cluster average) | **9.83 %** |
| Clusters audited | **30** of 30 |
| Clusters with non-singular hypothesis | **16** of 30 |

## Per-day breakdown

| Day | n_findings_audited | n_off | weighted off % | simple-mean off % | non-singular hypothesis |
|---|---:|---:|---:|---:|---:|
| 2026-05-08 | 438 | 49 | **11.19 %** | 12.00 % | 7 of 10 |
| 2026-05-11 | 359 | 34 | **9.47 %** | 9.10 % | 4 of 10 |
| 2026-05-13 | 436 | 35 | **8.03 %** | 8.37 % | 5 of 10 |
| **Cross-day** | **1,233** | **118** | **9.57 %** | **9.83 %** | **16 of 30** |

## Per-cluster raw

| Day | cluster | size | off | off % | hypothesis singular? |
|---|---|---:|---:|---:|:---:|
| 2026-05-08 | mc-000 | 100 | 17 | 17.0 % | yes |
| 2026-05-08 | mc-001 | 70 | 5 | 7.1 % | yes |
| 2026-05-08 | mc-002 | 49 | 4 | 8.2 % | yes |
| 2026-05-08 | mc-003 | 47 | 3 | 6.4 % | no |
| 2026-05-08 | mc-004 | 41 | 1 | 2.4 % | no |
| 2026-05-08 | mc-005 | 34 | 1 | 2.9 % | no |
| 2026-05-08 | mc-006 | 25 | 3 | 12.0 % | no |
| 2026-05-08 | mc-007 | 25 | 1 | 4.0 % | no |
| 2026-05-08 | mc-008 | 24 | 5 | 20.8 % | no |
| 2026-05-08 | mc-009 | 23 | 9 | 39.1 % | no |
| 2026-05-11 | mc-000 | 66 | 14 | 21.2 % | yes |
| 2026-05-11 | mc-001 | 61 | 3 | 4.9 % | yes |
| 2026-05-11 | mc-002 | 55 | 0 | 0.0 % | yes |
| 2026-05-11 | mc-003 | 29 | 1 | 3.4 % | yes |
| 2026-05-11 | mc-004 | 29 | 0 | 0.0 % | no |
| 2026-05-11 | mc-005 | 29 | 9 | 31.0 % | no |
| 2026-05-11 | mc-006 | 27 | 2 | 7.4 % | no |
| 2026-05-11 | mc-007 | 23 | 3 | 13.0 % | yes |
| 2026-05-11 | mc-008 | 21 | 1 | 4.8 % | no |
| 2026-05-11 | mc-009 | 19 | 1 | 5.3 % | yes |
| 2026-05-13 | mc-000 | 77 | 4 | 5.2 % | yes |
| 2026-05-13 | mc-001 | 72 | 6 | 8.3 % | yes |
| 2026-05-13 | mc-002 | 58 | 4 | 6.9 % | yes |
| 2026-05-13 | mc-003 | 53 | 7 | 13.2 % | no |
| 2026-05-13 | mc-004 | 44 | 2 | 4.5 % | no |
| 2026-05-13 | mc-005 | 29 | 1 | 3.4 % | no |
| 2026-05-13 | mc-006 | 27 | 4 | 14.8 % | yes |
| 2026-05-13 | mc-007 | 26 | 4 | 15.4 % | no |
| 2026-05-13 | mc-008 | 25 | 3 | 12.0 % | no |
| 2026-05-13 | mc-009 | 25 | 0 | 0.0 % | yes |

## Per-day reports

- [`2026-05-08.md`](2026-05-08.md)
- [`2026-05-11.md`](2026-05-11.md)
- [`2026-05-13.md`](2026-05-13.md)

## Sidecar data

- Per-cluster finding bundles (title + summary + description per finding):
  [`_data/<day>/cluster-NN.json`](_data/)
- Per-cluster auditor hypothesis (one-sentence anchor):
  `_data/<day>/cluster-NN.hypothesis.txt`
- Per-cluster per-finding labels and reasoning notes:
  `_data/<day>/cluster-NN.audit.csv`
- Per-day replay provenance: `_data/<day>/_meta.json`
- Aggregate machine-readable: [`summary.json`](summary.json)

## Interpretation

Per the brief, this audit surfaces the numbers and the architect applies
the interpretation bands (< 15 %, 15–30 %, ≥ 30 % aggregate; ≤ 3, 4–9,
≥ 10 non-singular clusters). No recommendation paragraph is drafted here.
