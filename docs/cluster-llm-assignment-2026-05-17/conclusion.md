# LLM cluster→topic assignment — Branch B conclusion

**Decision:** Brief 5b's pinned finding-level `T=0.55, V=title+summary`
configuration stays in production. No code or schema change. The
architect ruled Branch B after Phase 2 per
`TASK-CLUSTER-LLM-ASSIGNMENT.md`; the LLM stage and its deterministic
translation stay in the codebase as available alternatives but are not
wired into the default production / hydrated stage lists.

## Why LLM-cluster-assignment was tested

The cluster-level gravitation brief
([`docs/cluster-level-gravitation-2026-05-17/conclusion.md`](../cluster-level-gravitation-2026-05-17/conclusion.md))
ruled out pure-similarity cluster-level approaches as exceedings of
Brief 5b's 8.23 % aggregate weighted off-topic baseline. Two
architectural alternatives remained:

1. Continue with finding-level deterministic assignment (Brief 5b's
   pinned configuration).
2. Replace the cluster-level similarity rule with a semantically-aware
   LLM that reads the cluster's primary subject from its sample titles
   and decides topic membership cluster-by-cluster.

This brief is the empirical test of Hypothesis 2. The architecture-
pivot decision rode on the data.

## Test design

Two new stages, both new, both opt-in:

- `AssignClustersStage` (`src/agent_stages.py`) — LLM call at
  `google/gemini-3-flash-preview`, **temperature 1.0**, reasoning
  none, max_tokens 8000. Reuses the shared top-K-by-centroid
  sample-title compression (K = 8) from `CuratorTopicDiscoveryStage`.
- `cluster_to_finding_assignments`
  (`src/stages/cluster_to_finding_assignments.py`) — deterministic
  translation of LLM `{cluster_id, topic_indices}` records into the
  finding-level `curator_topic_assignments` slot consumed unchanged by
  the downstream `assemble_curator_topics` stage.

**Smoke methodology** (surfaced prominently in
[`smoke/summary.md`](smoke/summary.md)): the smoke runs
`AssignClustersStage` three times per day across the three eval
datasets (2026-05-08, 2026-05-11-v1-baseline, 2026-05-13) against the
**fixed `_topics.json` from `audit-2026-05-16`** as the topic-set
input — not against a freshly-discovered topic list. Reason: the
Phase-2 audit cross-references the 9 runs against the 2,542 audit
labels, which are keyed on those exact audit topics. Using the audit
topics guarantees direct 1:1 comparability against Brief 5b's pinned
configuration — same topics, same findings, only the assignment
algorithm differs.

Cost: $0.27 for 9 LLM calls (under the brief's $1 budget). Wall:
~11 min. **Zero schema failures** across the 9 calls at temperature 1.0
under strict-mode `response_format` validation.

## What was found

Headline against Brief 5b's pinned configuration:

| Metric | Brief 5b (T=0.55 V1) | LLM 9-run mean | LLM min | LLM max | Spread (pp) | Δ vs baseline |
|---|---:|---:|---:|---:|---:|---:|
| **Weighted off-topic %** | **8.23 %** | **36.04 %** | 32.07 % | 40.94 % | 8.87 | **+27.81 pp** |
| Simple-mean off-topic % | 8.31 % | 38.77 % | 30.92 % | 60.67 % | 29.75 | +30.46 pp |

Per-day:

| Day | Baseline | LLM mean | LLM min | LLM max | Δ |
|---|---:|---:|---:|---:|---:|
| 2026-05-08 | 11.69 % | 32.52 % | 32.07 % | 32.94 % | +20.83 pp |
| 2026-05-11 | 7.98 %  | 40.22 % | 39.82 % | 40.94 % | +32.24 pp |
| 2026-05-13 | 5.33 %  | 35.30 % | 34.56 % | 36.40 % | +29.97 pp |

The best of 9 LLM runs (32.07 %) is ~4× the baseline. **There is no
"win" to spread-check — even the best run is far worse than baseline.**
No audited topic improves; 28 of 30 strictly regress; the other 2 tie
at 0 % off.

Two of three named gravity-trap topics regress catastrophically:

- **Putin / Schröder** (2026-05-11 topic-02): 78.95 % off across all 3
  runs vs Brief 5b's 21.4 % → +57.55 pp regression.
- **Yermak** (2026-05-13 topic-03): 69.57 % off across all 3 runs vs
  Brief 5b's 0.0 % → +69.57 pp regression.

Three observations the brief flagged for preservation:

### 1. Reproducibility is high — the stochastic concern was overestimated

Zero schema failures across the 9 LLM calls at temperature 1.0 under
strict-mode `response_format` validation. Per-topic spread across the
3 runs of each day is mostly 0.00 pp — the LLM converges on the same
(wrong) assignments run-to-run rather than flailing. Topic-level
Jaccard agreement of cluster-sets across runs: 0.95 / 0.79 / 0.92 mean
per day. Per-day weighted off-topic spread: 0.87 / 1.12 / 1.84 pp.

This is valuable foreknowledge for future LLM-based stages. The
temperature-1.0 design choice did not produce the kind of run-to-run
instability that would have made the result inconclusive; the result
is conclusive, just in the opposite direction the hypothesis
predicted.

### 2. mc-004 / Sport-Wochenende is a worked example of the granularity mismatch

mc-004 is a worked example of the granularity mismatch named in
observation 3. The cluster's primary subject (Barcelona LaLiga) is
locally defensible as a Barcelona-topic match — the prompt's
discipline allows it. But the cluster also carries Liga MX, Brazilian
volleyball, and Tennis Rome findings that get dragged off-topic onto
a Barcelona-specific topic when the assignment fires. The
50 % / 0 % / 50 % topic-09 off-rate across runs is the cluster-
granularity failure mode made visible — and adds a run-to-run
instability the deterministic Brief 7 path did not have.

mc-004 was not the architectural success the prior hand-back's
audit-doc bug suggested. The audit's case-study section originally
reported mc-04 as orphaned in all 3 runs because the harness
hard-coded `mc-04` rather than the zero-padded `mc-004` Brief 1
actually emits. The case-study section is patched in
[`audit/README.md`](audit/README.md) (corrigendum at the bottom of the
Sport-Wochenende fate section).

### 3. Cluster granularity > topic granularity is the structural ceiling

Brief 1's micro-clusters are coarser than Brief 4's discovered topics.
Many clusters carry multiple sub-stories within a coherent semantic
theme (the "thematic-field" pattern the
[`docs/cluster-internal-audit/audit-2026-05-17/`](../cluster-internal-audit/audit-2026-05-17/)
labels surfaced: 16 of 30 audited top-10 clusters were thematic
fields, not single-story clusters). Any cluster-level
assignment method — deterministic or LLM-based — is structurally
limited when cluster granularity is broader than topic granularity:
the *only* defensible cluster-level decisions on thematic-field
clusters are "assign all sub-stories to one topic and accept the
drift" or "orphan the cluster entirely and lose recall". Both are
worse than the finding-level alternative, which operates at the same
granularity as the topics and can split findings across topics
per-finding.

Brief 5b succeeds because its decision unit (the finding) matches the
topic granularity. Brief 7 fails because its decision unit (the
cluster) does not. This brief fails the same way — for the same
structural reason — even though the deciding function is a
semantically-aware LLM rather than a cosine-threshold rule.

## Architectural implication

The granularity-mismatch insight constrains the space of future
architectural alternatives:

- **Cluster-level approaches cannot exceed finding-level approaches
  on the current Brief 1 / Brief 4 granularity stack.** This rules
  out the entire cluster-level family, whether deterministic
  (Brief 7), LLM-judged (this brief), or any hybrid.
- A meaningful future cluster-level test would require **tightening
  Brief 1's clustering** so cluster granularity matches topic
  granularity — for example, raising the agglomerative
  `distance_threshold` below the current 0.7 to split thematic-field
  clusters into per-sub-story clusters. That is a Brief 1
  recalibration, not a Brief 7 or Brief 8 redesign.
- Until / unless Brief 1's clustering is tightened, the production
  path stays finding-level: Brief 5b's pinned
  `T=0.55, V=title+summary` is the correct architectural choice for
  the current pipeline.

## Why the finding-level configuration was retained

Brief 5b's acceptance gates (aggregate weighted off-topic < 30 %,
no topic > 50 % off-topic) are met by the production configuration at
8.23 % aggregate and zero topics above 50 % off-topic
([`audit-2026-05-16-recalibrated/`](../cluster-quality-audit/audit-2026-05-16-recalibrated/)).
Neither acceptance gate is met by any of the 9 LLM runs: every run
sits above 30 % aggregate (32–41 %), and per-topic off-rates exceed
50 % in 8 of 30 audited topics in the LLM mean (Putin/Schröder, China
defense, Russia-Ukraine drones, Yermak, Nunes Marques, Israel-Lebanon,
2026-05-08 t01 Victory Day, 2026-05-08 t08 China defense).

## Artefacts

- [`smoke/summary.md`](smoke/summary.md) + [`smoke/summary.json`](smoke/summary.json)
  — 9-run smoke results with per-run / per-day spread and topic-level
  Jaccard stability tables.
- [`smoke/{date}/`](smoke/) — per-run state files
  (`assignments_llm.json`, `topic_assignments.json`, `run_meta.json`)
  plus the fixed `_topics.json` and `_pre_clusters.json` per day.
- [`audit/README.md`](audit/README.md) + [`audit/audit.json`](audit/audit.json)
  — 9-run audit against the 2,542-label set, per-topic detail,
  gravity-trap case studies, and the patched Sport-Wochenende /
  mc-004 case-study section with corrigendum.
- [`audit/{date}.md`](audit/) — per-day per-run audit detail.
- `scripts/smoke_cluster_llm_assignment.py` — smoke harness (reusable
  if the architectural conditions change; the harness itself is
  correct).
- `scripts/audit_cluster_llm_assignment.py` — audit harness. The
  `SPORT_CLUSTER_ID = "mc-04"` constant is left as the documented
  bug it was; a future reuse of the harness should replace it with
  `"mc-004"` to match Brief 1's three-digit zero-padded cluster IDs.

## Hypothesis-2 status

This brief was Hypothesis 2 of the two architectural alternatives
raised by the cluster-internal-audit findings. Both hypotheses have
been tested and ruled out:

- Hypothesis 1 (Brief 7 — deterministic cluster-level): ruled out at
  ≥ 20 pp aggregate deficit, see
  [`docs/cluster-level-gravitation-2026-05-17/conclusion.md`](../cluster-level-gravitation-2026-05-17/conclusion.md).
- Hypothesis 2 (this brief — LLM cluster-level): ruled out at
  +27.81 pp aggregate deficit.

The structural reason both fail is the same: cluster granularity
exceeds topic granularity on the current Brief 1 / Brief 4 stack.
Future cluster-level work is gated on a Brief 1 recalibration that
tightens clustering, not on a new cluster→topic decision function.
