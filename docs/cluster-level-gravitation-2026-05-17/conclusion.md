# Cluster-level gravitation — Branch B conclusion

**Decision:** Brief 5b's pinned finding-level `T=0.55, V=title+summary`
configuration stays in production. No code or schema change. The architect
ruled Branch B at the Phase 1 STOP per `TASK-CLUSTER-LEVEL-GRAVITATION.md`;
Phase 2 qualitative samples were not rendered because the Phase 1 sweep already
made the empirical case.

## Why cluster-level was tested

The cluster-internal-coherence audit
([`docs/cluster-internal-audit/audit-2026-05-17/`](../cluster-internal-audit/audit-2026-05-17/),
1,233 labels) surfaced two findings:

1. Brief 1's micro-clusters are internally coherent at **9.57 %** aggregate
   off-topic.
2. **16 of 30** top-10 audited clusters carry titles spanning multiple
   sub-stories within a coherent semantic theme — "thematic-field" clusters,
   not single-story clusters.

The architect's hypothesis was that thematic-field clusters may be a valid
form of topic — the Curator's headline + summary frames the breadth, the
Writer produces one primary thread + surrounding coverage, and cluster-level
gravitational assignment becomes the right architectural mechanism. Phase 1
tested this empirically by recomputing assignments under 20 cluster-level
configurations (`T ∈ {0.55, 0.60, 0.65, 0.70, 0.75} × {single, multi} ×
{orphan, finding_level}`) against the 2,542 topic-quality audit labels
from [`audit-2026-05-16`](../cluster-quality-audit/audit-2026-05-16/), with
Brief 5b's pinned configuration as an explicit comparison row.

## What was found

| Configuration | Off % | Recall | Orphan % | Cluster orphan / single / multi |
|---|---:|---:|---:|---|
| **Brief 5b baseline** (finding-level T=0.55 V1) | **8.23 %** | 0.655 | 84.95 % | n/a |
| Lowest off % cluster-level (T=0.75 single+finding_level) | 28.86 % | 0.756 | 75.34 % | 731 / 35 / 0 |
| Highest recall cluster-level (T=0.55 multi+finding_level) | 36.41 % | 0.880 | 69.53 % | 713 / 51 / 2 |
| Lowest orphan cluster-level (T=0.55 single+finding_level) | 33.92 % | 0.847 | 69.53 % | 713 / 53 / 0 |

Brief 5b's baseline beat every cluster-level row by **≥ 20 pp** on aggregate
weighted off-topic. Four observations made the call against cluster-level:

1. **The top-3 cluster-level rows are baseline + a thin overlay.** At
   `T ≥ 0.70` in `single` mode, 726–731 of 766 clusters orphan; under
   `finding_level` fallback their findings re-assign via Brief 5b's
   `T=0.55 V1` rule. So the wins at the top of the leaderboard come from
   finding-level work, not cluster-level decisions.

2. **`multi` mode does not split thematic-field clusters.** For every audited
   cluster across the three eval days, `multi` assigned the same number of
   topics as `single` (usually 1; never more than 2). The brief's named
   architectural pivot — the Sport-Wochenende cluster `mc-04` on 2026-05-11 —
   lands on **only** topic-09 (Barcelona LaLiga) at every `T ≤ 0.70` in both
   modes; no other sports topic exists in the day's discovered set above its
   centroid-similarity threshold. Topic-09 jumps from baseline
   `8 on / 0 off` to `12 on / 12 off` (**50 % off**) at every cluster-level
   `T ≤ 0.70` because the rest of the Sport cluster (Liga MX, Brazilian
   medals, tennis Rome) is dragged into the Barcelona topic.

3. **Gravity-trap drift is structurally cluster-level.** At `T=0.55 single`,
   topic-02 (Putin/Schröder, 2026-05-11) jumps from baseline
   `11 on / 3 off` to `0 on / 17 off` (**100 % off**) because cluster
   `mc-009` — the Pistorius Kyiv visit / EU funding cluster, internally
   **singular** per `audit-2026-05-17` — lands wholesale on the Schröder
   topic. `multi` mode pulls three more drift clusters in → 83.8 % off. Same
   pattern on 2026-05-13 topic-03 (Yermak: 6 retained → 23, 16 off) and
   topic-01 (Russia-Ukraine drone strikes: 33 → 77, 44 off). The drift is
   between-topic — coherent clusters crossing the centroid threshold of an
   unrelated topic that happens to share embedding vocabulary.

4. **Audit-set metrics are a lower bound on cluster-level drift.** The 2,542
   labels cover only `(finding, topic)` pairs the original `T=0.30 V1` audit
   assigned. Cluster-level can promote findings into topics that weren't in
   the original audit set; those unlabeled new assignments are uncounted. The
   true drift is higher than what `sweep.md` reports.

## Why the finding-level configuration was retained

The architectural hypothesis behind cluster-level gravitation was that
internally-coherent thematic-field clusters, assigned as wholes, would lift
recall without substantial drift. The data did not support this:

- Where thematic-field clusters had a discovered topic above threshold, they
  landed on **one** specific sub-story topic and dragged the rest along
  (Sport-Wochenende → Barcelona LaLiga).
- Where coherent single-story clusters had a discovered topic above threshold
  that they did not belong to, they drifted wholesale onto that topic
  (mc-009 Pistorius → Schröder).
- The cluster-level "wins" were mostly finding-level under the hood.

Brief 5b's acceptance gates (aggregate weighted off < 30 % AND no topic
> 50 % off) are not within reach of any cluster-level configuration tested.
The current production configuration — `T=0.55 V1` finding-level — sits at
8.23 % weighted off, recall 0.655, with zero topics above 50 % off-topic
([`audit-2026-05-16-recalibrated/`](../cluster-quality-audit/audit-2026-05-16-recalibrated/)).

## Architectural implication

This brief was Hypothesis 1 of two architectural alternatives raised by the
cluster-internal-audit findings. Hypothesis 2 — LLM-based cluster→topic
assignment — remains the next architectural option if a future audit reveals
a problem with the finding-level configuration that this brief did not
surface. Hypothesis 2 is out of scope; if the architect wants to scope it, it
lives as a future `TASK-*` brief.

## Artefacts

- [`sweep.md`](sweep.md) — full sweep results (21 configurations × 30
  topics × full-population diagnostics + recommendation paragraph).
- [`sweep.json`](sweep.json) — machine-readable per-config + per-topic data.
- [`scripts/sweep_cluster_level_gravitation.py`](../../scripts/sweep_cluster_level_gravitation.py)
  — sweep harness (deterministic, sub-second per configuration, zero LLM
  spend).
- [`tests/test_sweep_cluster_level_gravitation.py`](../../tests/test_sweep_cluster_level_gravitation.py)
  — 18 helper tests (centroid math, assignment modes, fallback branches, four
  mode × fallback combinations).
- `_cache/{date}/cluster_topic_sim.npy` + `finding_topic_sim.npy` —
  similarity-matrix cache (gitignored).

Phase 2 samples were not rendered (architect ruled Branch B at Phase 1 STOP).
The sweep harness has a `render_all_samples`-style entry-point available if
a future calibration needs the per-finding view at specific configurations.
