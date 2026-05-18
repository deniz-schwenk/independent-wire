# Cluster-LLM-assignment audit — cross-day summary

TASK-CLUSTER-LLM-ASSIGNMENT Phase 2 — audit of the 9 smoke runs against the 2,542-label ground truth from `docs/cluster-quality-audit/audit-2026-05-16/`. Each row reports the new pipeline's `curator_topic_assignments` intersected with the audit's labels per topic; pairs not in the audit label set (i.e. new assignments outside the V1 top-10 audit space) are excluded from the aggregate per the brief's documented constraint.

## Headline — LLM 9-run pool vs Brief 5b baseline

| Metric | Brief 5b (T=0.55 V1) | LLM 9-run mean | LLM min | LLM max | Spread (pp) | Δ mean vs baseline |
|---|---:|---:|---:|---:|---:|---:|
| **Weighted off-topic %** | **8.23 %** | **36.04 %** | 32.07 % | 40.94 % | 8.87 | +27.81 pp |
| Simple-mean off-topic % | 8.31 % | 38.77 % | 30.92 % | 60.67 % | 29.75 | +30.46 pp |

**Verdict (mechanical):** the LLM mean (36.04 %) does NOT beat Brief 5b's baseline (8.23 %); deficit +27.81 pp.

## Per-run audit (9 rows)

| Date | Run | n_audited | n_off | Weighted off % | Simple-mean off % | Mean precision | Mean recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-05-08 | 1 | 343 | 113 | **32.94 %** | 31.87 % | 0.681 | 0.949 |
| 2026-05-08 | 2 | 341 | 111 | **32.55 %** | 31.68 % | 0.683 | 0.949 |
| 2026-05-08 | 3 | 343 | 110 | **32.07 %** | 30.92 % | 0.691 | 0.952 |
| 2026-05-11 | 1 | 342 | 140 | **40.94 %** | 37.96 % | 0.620 | 0.827 |
| 2026-05-11 | 2 | 339 | 135 | **39.82 %** | 38.11 % | 0.619 | 0.807 |
| 2026-05-11 | 3 | 356 | 142 | **39.89 %** | 37.25 % | 0.627 | 0.860 |
| 2026-05-13 | 1 | 298 | 103 | **34.56 %** | 45.45 % | 0.545 | 0.628 |
| 2026-05-13 | 2 | 261 | 95 | **36.40 %** | 60.67 % | 0.393 | 0.443 |
| 2026-05-13 | 3 | 329 | 115 | **34.95 %** | 35.06 % | 0.649 | 0.808 |

## Per-day spread

Spread is the load-bearing signal — large spread between runs indicates the LLM is making materially different judgements run-to-run, which has implications for production stability.

| Date | Baseline (Brief 5b) | LLM mean | LLM min | LLM max | Spread (pp) |
|---|---:|---:|---:|---:|---:|
| 2026-05-08 | 11.69 % | **32.52 %** | 32.07 % | 32.94 % | 0.87 |
| 2026-05-11 | 7.98 % | **40.22 %** | 39.82 % | 40.94 % | 1.12 |
| 2026-05-13 | 5.33 % | **35.30 %** | 34.56 % | 36.40 % | 1.84 |

## Per-topic detail (30 audited topics × 3 LLM runs + baseline)

For each of the 30 audited topics (10 per day): per-run off-topic %, baseline off-topic % at Brief 5b, mean precision + recall.

### 2026-05-08

| Bundle | Topic title (truncated) | Baseline off % | Run 1 off % | Run 2 off % | Run 3 off % | LLM mean off % | LLM spread (pp) |
|---:|---|---:|---:|---:|---:|---:|---:|
| topic-00 | US and Iran maintain diplomatic dialogue despite exchange of | 7.32 % | 14.61 % | 12.64 % | 14.13 % | **13.79 %** | 1.97 |
| topic-01 | Russia and Ukraine trade accusations over Victory Day ceasef | 37.50 % | 62.63 % | 62.63 % | 62.63 % | **62.63 %** | 0.00 |
| topic-02 | Donald Trump and Lula da Silva meet at White House to relink | 0.00 % | 29.41 % | 29.41 % | 29.41 % | **29.41 %** | 0.00 |
| topic-03 | South African Constitutional Court orders Parliament to revi | 0.00 % | 16.67 % | 16.67 % | 16.67 % | **16.67 %** | 0.00 |
| topic-04 | Hantavirus outbreak on cruise ship MV Hondius triggers inter | 0.00 % | 6.25 % | 6.25 % | 6.25 % | **6.25 %** | 0.00 |
| topic-05 | Internal crisis hits Real Madrid following training ground a | 20.00 % | 50.00 % | 50.00 % | 50.00 % | **50.00 %** | 0.00 |
| topic-06 | Tamil Nadu government formation proceeds with support for Vi | 0.00 % | 21.43 % | 21.43 % | 21.43 % | **21.43 %** | 0.00 |
| topic-07 | US trade court strikes down Donald Trump's 10 percent univer | 0.00 % | 25.00 % | 25.00 % | 16.00 % | **22.00 %** | 9.00 |
| topic-08 | China sentences former defense ministers to death with repri | 40.00 % | 72.73 % | 72.73 % | 72.73 % | **72.73 %** | 0.00 |
| topic-09 | Pope Leo XIV marks first anniversary amid tensions with US a | 0.00 % | 20.00 % | 20.00 % | 20.00 % | **20.00 %** | 0.00 |

### 2026-05-11

| Bundle | Topic title (truncated) | Baseline off % | Run 1 off % | Run 2 off % | Run 3 off % | LLM mean off % | LLM spread (pp) |
|---:|---|---:|---:|---:|---:|---:|---:|
| topic-00 | Russia and Ukraine accuse each other of violating US-brokere | 35.29 % | 67.74 % | 67.19 % | 67.19 % | **67.37 %** | 0.55 |
| topic-01 | Donald Trump rejects Iran's response to US peace proposal as | 6.67 % | 19.67 % | 18.57 % | 18.57 % | **18.94 %** | 1.10 |
| topic-02 | Vladimir Putin proposes Gerhard Schröder as mediator for Ukr | 21.43 % | 78.95 % | 78.95 % | 78.95 % | **78.95 %** | 0.00 |
| topic-03 | South Korean vessel damaged by explosion in the Strait of Ho | 0.00 % | 48.28 % | 45.16 % | 45.16 % | **46.20 %** | 3.12 |
| topic-04 | Hantavirus outbreak on MV Hondius cruise ship triggers inter | 0.00 % | 0.00 % | 0.00 % | 0.00 % | **0.00 %** | 0.00 |
| topic-05 | Emmanuel Macron visits Kenya for Africa Forward economic sum | 0.00 % | 35.71 % | 35.71 % | 33.33 % | **34.92 %** | 2.38 |
| topic-06 | Donald Trump prepares for state visit to China amid trade te | 0.00 % | 17.39 % | 17.39 % | 17.39 % | **17.39 %** | 0.00 |
| topic-07 | Narges Mohammadi released from Iranian prison for medical tr | 0.00 % | 33.33 % | 33.33 % | 33.33 % | **33.33 %** | 0.00 |
| topic-08 | Latvian Defense Minister resigns following Ukrainian drone i | 16.67 % | 28.57 % | 46.67 % | 28.57 % | **34.60 %** | 18.10 |
| topic-09 | Barcelona wins La Liga title after victory over Real Madrid | 0.00 % | 50.00 % | 0.00 % | 50.00 % | **33.33 %** | 50.00 |

### 2026-05-13

| Bundle | Topic title (truncated) | Baseline off % | Run 1 off % | Run 2 off % | Run 3 off % | LLM mean off % | LLM spread (pp) |
|---:|---|---:|---:|---:|---:|---:|---:|
| topic-00 | Escalating costs and military risks threaten Middle East tru | 8.33 % | 16.98 % | 16.98 % | 16.98 % | **16.98 %** | 0.00 |
| topic-01 | Ukraine and Russia exchange long-range drone strikes on ener | 9.09 % | 57.14 % | 57.14 % | 57.14 % | **57.14 %** | 0.00 |
| topic-02 | Donald Trump arrives in China for high-stakes summit with Xi | 1.82 % | 14.08 % | 14.08 % | 14.08 % | **14.08 %** | 0.00 |
| topic-03 | Anti-corruption probe in Ukraine targets former presidential | 0.00 % | 69.57 % | 69.57 % | 69.57 % | **69.57 %** | 0.00 |
| topic-04 | Emmanuel Macron seeks renewed partnerships during Africa For | 0.00 % | 27.59 % | 27.59 % | 27.59 % | **27.59 %** | 0.00 |
| topic-05 | Massive protests in Argentina against university funding cut | 0.00 % | 0.00 % | 100.00 % | 0.00 % | **33.33 %** | 100.00 |
| topic-06 | Nunes Marques takes office as President of Brazil's Superior | 28.57 % | 66.67 % | 100.00 % | 66.67 % | **77.78 %** | 33.33 |
| topic-07 | Keir Starmer faces internal pressure and calls for resignati | 0.00 % | 11.54 % | 0.00 % | 11.54 % | **7.69 %** | 11.54 |
| topic-08 | Israel and Lebanon exchange fire as ceasefire efforts remain | 16.67 % | 100.00 % | 100.00 % | 52.00 % | **84.00 %** | 48.00 |
| topic-09 | South Korea and Australia consider joining naval missions in | 0.00 % | 0.00 % | 0.00 % | 0.00 % | **0.00 %** | 0.00 |

## Gravity-trap case studies

Three known gravity-trap topics where deterministic T=0.55 V1 either succeeds or hovers near the acceptance boundary. The LLM's per-run behaviour is reported below.

### 2026-05-11 topic-02 — Putin/Schröder

_Brief 5b's pinned configuration drops topic-02 from 27.5 % off (baseline T=0.30) to 21.4 % off at T=0.55 — a hard case where gravitational drift pulls Pistorius / EU funding into the Schröder Victory-Day topic._

| Run | n_new_assigned | n_labeled | n_unlabeled_new | on | off | off % | n_clusters_assigned |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 66 | 57 | 9 | 12 | 45 | **78.95 %** | 1 |
| 2 | 66 | 57 | 9 | 12 | 45 | **78.95 %** | 1 |
| 3 | 66 | 57 | 9 | 12 | 45 | **78.95 %** | 1 |

### 2026-05-13 topic-03 — Yermak/Russia-Ukraine

_Topic-03 carries cross-topic drift between Yermak's resignation and the broader Russia-Ukraine war coverage._

| Run | n_new_assigned | n_labeled | n_unlabeled_new | on | off | off % | n_clusters_assigned |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 26 | 23 | 3 | 7 | 16 | **69.57 %** | 1 |
| 2 | 26 | 23 | 3 | 7 | 16 | **69.57 %** | 1 |
| 3 | 26 | 23 | 3 | 7 | 16 | **69.57 %** | 1 |

### 2026-05-11 topic-04 — Hantavirus (NOT Sport-Wochenende — see corrigendum)

_This subsection was originally labelled "Sport-Wochenende" but its data
is actually for 2026-05-11 topic-04 (Hantavirus outbreak on the MV
Hondius cruise ship), not for the Sport-Wochenende cluster. The
harness's `GRAVITY_TRAPS` constant pointed `bundle_idx=4`, which on
2026-05-11 is the Hantavirus topic, not a sports topic. The figures
below are correct for Hantavirus topic-04; the architectural
Sport-Wochenende canary case is the corrected section below._

| Run | n_new_assigned | n_labeled | n_unlabeled_new | on | off | off % | n_clusters_assigned |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 55 | 53 | 2 | 53 | 0 | **0.00 %** | 1 |
| 2 | 55 | 53 | 2 | 53 | 0 | **0.00 %** | 1 |
| 3 | 55 | 53 | 2 | 53 | 0 | **0.00 %** | 1 |

## Sport-Wochenende cluster mc-004 fate (architectural canary)

The Sport-Wochenende cluster (`mc-004`, 2026-05-11) is the
architectural pivot from the cluster-level gravitation brief — under
deterministic cluster-level T=0.55 it landed wholesale on topic-09
(Barcelona LaLiga), causing 50 % drift on a previously-clean topic.
This section tracks the LLM's per-run decision on the same cluster.

`mc-004` carries 29 findings spanning Barcelona LaLiga, Liga MX,
Brazilian volleyball, Tennis Rome, and other Sport-Wochenende coverage
— the thematic-field pattern surfaced by
[`docs/cluster-internal-audit/audit-2026-05-17/`](../../cluster-internal-audit/audit-2026-05-17/).

| Run | Fate | Assigned topics | topic-09 off-% (consequence) |
|---:|---|---|---:|
| 1 | **assigned** | topic-09 (Barcelona LaLiga) | 50.00 % |
| 2 | **orphan** (intentional — in `orphan_cluster_ids`) | — | 0.00 % |
| 3 | **assigned** | topic-09 (Barcelona LaLiga) | 50.00 % |

The 50 % / 0 % / 50 % off-rate on topic-09 across the three runs is
the direct consequence of `mc-004`'s assignment: when assigned (runs
1 & 3), the Liga MX / volleyball / tennis findings get dragged onto
the Barcelona-specific topic; when orphaned (run 2), topic-09 stays
clean. This is the **same wholesale-onto-Barcelona drift Brief 7's
deterministic cluster-level gravitation produced**, with the
additional run-to-run instability of the LLM path.

### Corrigendum (2026-05-18)

The first iteration of this audit document, committed in `48a137d`,
reported `mc-04` as orphaned in all 3 runs. That was wrong. The
harness's `SPORT_CLUSTER_ID = "mc-04"` constant never matched a real
cluster — Brief 1 emits zero-padded three-digit IDs (`mc-000`,
`mc-001`, …, `mc-004`). The lookup returned `None` for every run, and
the rendering code defaulted to `fate: "orphan"`. The corrected mc-004
fate above was reconstructed directly from
`smoke/2026-05-11/run-{N}/assignments_llm.json`.

The `gravity-trap case studies` subsection labelled "2026-05-11
topic-04 — Sport-Wochenende" above is also relabelled to "Hantavirus"
because the original label was the same naming confusion — `bundle_idx
= 4` on 2026-05-11 is the Hantavirus topic, not a sports topic. The
audit script's `GRAVITY_TRAPS` constant carries the same bug; a future
re-use of the harness should replace `bundle_idx: 4` with the actual
audited topic that hosts the Sport / Barcelona discussion (topic-09 on
2026-05-11). The script itself is left unchanged in this brief because
the data and the conclusion are now correctly framed in this document
and in [`../conclusion.md`](../conclusion.md).

The `audit.json` machine-readable file also carries the pre-correction
`sport_cluster_case` field with the wrong "orphan in all 3 runs"
data — it has not been mutated; readers consuming `audit.json` should
treat the `sport_cluster_case` field as superseded and consult the
table above instead.

## Honest framing

The LLM audit numbers are themselves stochastic across runs. Architect-decision rule (per brief watch-item 4): the LLM mean must beat 8.23 % **by enough that the win survives the spread** — a mean of 6 % with spread 3–9 % is a different proposition from a mean of 6 % with spread 5.5–6.5 %. The spread column above is the load-bearing one for that judgement.