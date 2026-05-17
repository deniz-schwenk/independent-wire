# Cluster-LLM-assignment smoke — cross-day summary

Three runs per day × three eval datasets = **nine `AssignClustersStage` LLM calls**, all at temperature 1.0.

## Methodology — fixed-topic input

The topic-set input to `AssignClustersStage` is the fixed `_topics.json` from `docs/cluster-quality-audit/audit-2026-05-16/` (the same topics Brief 5b's pinned configuration was audited against). No `CuratorTopicDiscoveryStage` call is made — the topics come from disk. This guarantees that the Phase-2 audit cross-references against the 2,542 labels are directly comparable to Brief 5b's 8.23 % aggregate weighted off-topic baseline: same topics, same findings, only the assignment algorithm differs.

Pre-cluster output is deterministic and reused from `docs/cluster-internal-audit/audit-2026-05-17/_cache/` when present.

## Cost

- **Total LLM cost: $0.2735**

## Per-run table (9 rows = 3 dates × 3 runs)

| Date | Run | Wall (s) | Cost (USD) | Tokens | Clusters in | Assigned | Orphan | Multi-asg | Findings assigned | Orphan findings |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05-08 | 1 | 81.4 | $0.0399 | 75,031 | 246 | 27 | 219 | 1 | 519 | 882 |
| 2026-05-08 | 2 | 79.6 | $0.0062 | 74,831 | 246 | 24 | 222 | 1 | 468 | 933 |
| 2026-05-08 | 3 | 78.8 | $0.0398 | 74,996 | 246 | 26 | 220 | 1 | 516 | 885 |
| 2026-05-11 | 1 | 68.0 | $0.0384 | 74,059 | 241 | 15 | 226 | 1 | 356 | 845 |
| 2026-05-11 | 2 | 67.6 | $0.0388 | 74,195 | 241 | 19 | 222 | 1 | 381 | 820 |
| 2026-05-11 | 3 | 67.2 | $0.0075 | 74,210 | 241 | 22 | 219 | 1 | 392 | 809 |
| 2026-05-13 | 1 | 75.8 | $0.0473 | 91,924 | 279 | 23 | 256 | 0 | 501 | 904 |
| 2026-05-13 | 2 | 75.9 | $0.0073 | 92,107 | 279 | 31 | 248 | 1 | 514 | 891 |
| 2026-05-13 | 3 | 73.2 | $0.0484 | 92,305 | 279 | 26 | 253 | 0 | 516 | 889 |

## Per-day spread (mean ± min ± max across 3 runs)

Spread is the load-bearing signal for production viability at temperature 1.0 — large spread = the LLM makes materially different judgements run-to-run.

| Date | Pre-clusters | n_topics | Clusters assigned (mean / min / max) | Orphan clusters (mean / min / max) | Findings assigned (mean / min / max) | Topic-Jaccard mean / min |
|---|---:|---:|---|---|---|---|
| 2026-05-08 | 246 | 15 | 25.667 / 24 / 27 | 220.333 / 219 / 222 | 501 / 468 / 519 | 0.952 / 0.929 |
| 2026-05-11 | 241 | 15 | 18.667 / 15 / 22 | 222.333 / 219 / 226 | 376.333 / 356 / 392 | 0.789 / 0.689 |
| 2026-05-13 | 279 | 18 | 26.667 / 23 / 31 | 252.333 / 248 / 256 | 510.333 / 501 / 516 | 0.401 / 0.265 |

## Cross-date aggregate (9-run pool)

| Metric | Mean | Min | Max |
|---|---:|---:|---:|
| Wall (s) | 74.156 | 67.22 | 81.354 |
| Cost per call (USD) | 0.03 | 0.0061534 | 0.048425 |
| Clusters assigned | 23.667 | 15 | 31 |
| Clusters orphan | 231.667 | 219 | 256 |
| Multi-assignments per run | 0.778 | 0 | 1 |
| Findings assigned | 462.556 | 356 | 519 |
| Orphan findings | 873.111 | 809 | 933 |

## Schema-failure log

No schema-validation failures across the 9 LLM calls — every response parsed cleanly under strict mode.

## Per-day reports

- [`2026-05-08/summary.md`](2026-05-08/summary.md)
- [`2026-05-11/summary.md`](2026-05-11/summary.md)
- [`2026-05-13/summary.md`](2026-05-13/summary.md)
