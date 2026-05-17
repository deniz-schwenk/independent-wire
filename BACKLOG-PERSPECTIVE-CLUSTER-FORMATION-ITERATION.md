# BACKLOG-PERSPECTIVE-CLUSTER-FORMATION-ITERATION

**Status:** iteration smoke complete, no winner selected.

**Owner:** Architect

**Created:** 2026-05-09

## Context

Five-variant prompt iteration on the cluster-formation section of `agents/perspective/INSTRUCTIONS.md`. The previous migration introduced three-level (stated / reported / mentioned) classification per cluster, which works as designed for tier assignment — but the implicit plural floor in the cluster-membership rule ("two actors belong in the same cluster") leaves single-actor positions outside any cluster. This iteration samples five mechanically distinct interventions to that floor, evaluated against the same three 2026-05-08 dossiers.

Each variant lives at `agents/perspective/INSTRUCTIONS_v{1..5}.md`. The original `agents/perspective/INSTRUCTIONS.md` was swapped in/out per variant and restored after each smoke; final md5 matches the snapshot taken before the iteration began.

## Comparison table — full (3 TPs × 6 variants including baseline)

| Variant  | TP  | Clusters | Stated | Reported | Mentioned | Unassigned | Operational-label |
|----------|-----|---------:|-------:|---------:|----------:|-----------:|------------------:|
| baseline | 001 |        9 |     14 |        8 |         1 |         10 |                 1 |
| baseline | 002 |       11 |     24 |        6 |         4 |         38 |                 3 |
| baseline | 003 |        8 |      5 |        8 |         0 |          1 |                 0 |
| v1       | 001 |       11 |     17 |        9 |         3 |          4 |                 1 |
| v1       | 002 |       10 |     20 |       15 |         4 |         32 |                 2 |
| v1       | 003 |        7 |      3 |        8 |         1 |          0 |                 1 |
| v2       | 001 |       15 |     19 |        8 |         2 |          6 |                 0 |
| v2       | 002 |       21 |     28 |       15 |         9 |         21 |                 4 |
| v2       | 003 |        9 |      4 |       10 |         0 |          0 |                 1 |
| v3       | 001 |       14 |     18 |        8 |         2 |          6 |                 0 |
| v3       | 002 |       16 |     26 |       12 |         7 |         27 |                 4 |
| v3       | 003 |        9 |      5 |        9 |         0 |          0 |                 1 |
| v4       | 001 |       12 |     15 |        9 |         1 |          7 |                 0 |
| v4       | 002 |       13 |     22 |       11 |         4 |         32 |                 3 |
| v4       | 003 |        9 |      5 |        9 |         0 |          0 |                 1 |
| v5       | 001 |       11 |     17 |        7 |         1 |         10 |                 1 |
| v5       | 002 |       13 |     26 |       12 |         3 |         31 |                 3 |
| v5       | 003 |        9 |      5 |        9 |         0 |          0 |                 1 |

### TP-08-002 detail (the architect's primary test case — 63 canonical actors, the prior-art outlier)

| Variant  | Clusters | Stated | Reported | Mentioned | Unassigned (of 63) | Operational-label |
|----------|---------:|-------:|---------:|----------:|-------------------:|------------------:|
| baseline |       11 |     24 |        6 |         4 |                 38 |                 3 |
| v1       |       10 |     20 |       15 |         4 |                 32 |                 2 |
| v2       |       21 |     28 |       15 |         9 |                 21 |                 4 |
| v3       |       16 |     26 |       12 |         7 |                 27 |                 4 |
| v4       |       13 |     22 |       11 |         4 |                 32 |                 3 |
| v5       |       13 |     26 |       12 |         3 |                 31 |                 3 |

## Per-variant levers (mechanical idea, no wording samples)

**v1 — Singularize the membership rule (Lever A wording).** The plural subject in "Two actors belong in the same cluster…" is rewritten in singular form, so the rule operates on one actor at a time matching cluster substance. The implicit floor of two is removed at the rule's grammar layer. Lever B's example sentences are recast in matching singular form for consistency. Lever C is unchanged.

**v2 — Frame inversion: positions over actor-groupings.** The section is renamed "Identifying positions". The unit of analysis changes from "what actors agree on" to "what positions are present in the dossier"; clusters are produced one-per-position rather than aggregated bottom-up from actor pairs. Lever B's "two actors X" pattern dissolves because the section no longer reasons in terms of actor pairs. Lever C is replaced with a count-of-positions framing ("typically several, occasionally many").

**v3 — Widen Lever C alone.** Lever A and Lever B are kept verbatim. The cluster-count heuristic is widened from "three to eight" to "between three and fifteen" with a tail explaining that high-positional-diversity dossiers sit toward the upper end. The hypothesis is that loosening the count corridor lets the agent admit more clusters even under the original plural-framed membership rule.

**v4 — Explicit override clause appended to Lever A.** Lever A and Lever B are kept verbatim. A new paragraph is added immediately below stating that a cluster's membership floor is one and that the plural framing above describes the typical case rather than an exclusion of singletons. The rule's wording is unchanged; the override is additive.

**v5 — Completeness requirement appended after Lever C.** Lever A, B, and C are kept verbatim. A new paragraph is added stating that the cluster set must cover every materially distinct position in the dossier — voiced by any number of actors, including one, including none directly — with explicit "left out / split" failure modes. The constraint is top-down enumerative rather than a change to the per-cluster rule.

## Operational-label cluster spotlights

The operational-label classifier is heuristic (regex over labels for transportation / logistics / aviation / scheduling / coordination / security-arrangement language). Some matches catch genuinely operational clusters (TP-003 ship-quarantine arrangements); others catch positional claims that *contain* operational words ("Ukrainian strikes on aviation infrastructure are legitimate self-defense" — a stance, not a logistics description). The architect should read the labels themselves rather than rely on the count.

```
baseline TP-001: The war is causing severe global economic damage through energy price shocks and supply chain disruption
baseline TP-002: The parade reduction is a prudent security measure against Ukrainian terrorism, not a sign of weakness
baseline TP-002: Ukrainian long-range drone strikes on Russian energy and aviation infrastructure are legitimate acts of self-defense …
baseline TP-002: The drone war is creating dangerous spillover risks for NATO member states and regional aviation

v1       TP-001: The war is causing severe global economic damage through oil price surges and supply chain disruption
v1       TP-002: Russia's domestic security measures including internet shutdowns and airspace closures reveal the extent to which the war …
v1       TP-002: Ukrainian drone operations transiting NATO member airspace create dangerous escalation risks that threaten regional security
v1       TP-003: Spain's central government should manage the ship's arrival at Tenerife for quarantine and evacuation

v2       TP-002: The parade reduction was a proactive security measure against Ukrainian terrorism rather than a sign of military weakness
v2       TP-002: Ukrainian drone strikes on air traffic control infrastructure have paralyzed civilian aviation across southern Russia
v2       TP-002: Russia's widespread mobile internet shutdowns represent an extraordinary domestic security measure reflecting vulnerability
v2       TP-002: Ukrainian drones transiting NATO member airspace create dangerous regional security spillover risks
v2       TP-003: The ship will dock at Granadilla port in Tenerife for evacuation and quarantine

v3       TP-002: The parade reduction was a proactive security measure against Ukrainian terrorism rather than a sign of weakness
v3       TP-002: Ukrainian drone strikes on air traffic control infrastructure have paralyzed civilian aviation across southern Russia
v3       TP-002: Russia is using Latvian airspace allegations to deflect from its own vulnerabilities and create NATO tensions
v3       TP-002: Russia's widespread mobile internet shutdowns represent an unprecedented domestic security measure with significant civi…
v3       TP-003: The MV Hondius should dock at Tenerife for evacuation and quarantine

v4       TP-002: Ukrainian long-range drone strikes on Russian energy and aviation infrastructure constitute effective economic warfare
v4       TP-002: Ukrainian drone operations through NATO member airspace create dangerous regional security spillover risks
v4       TP-002: Russia implemented unprecedented domestic security measures including mobile internet shutdowns across 21 regions to coun…
v4       TP-003: Spain's central government should dock the MV Hondius at Tenerife for evacuation and quarantine

v5       TP-001: The conflict is causing severe global economic damage through oil price surges and supply chain disruption
v5       TP-002: The Kremlin frames the parade reduction as a proactive security measure against Ukrainian terrorism rather than a sign of …
v5       TP-002: Ukrainian drone operations through NATO member airspace create dangerous regional security spillover risks
v5       TP-002: Diplomatic channels remain active with potential for renewed U.S.-Ukraine coordination and Slovak mediation with Moscow
v5       TP-003: Spain's central government will receive the ship at Tenerife for evacuation and quarantine
```

## Artefacts

Per-variant outputs preserved at:

```
output/2026-05-08/_iteration/baseline/   tp-2026-05-08-{001,002,003}.json   (post-pipeline TP JSON)
output/2026-05-08/_iteration/v1/state/   topic_buses.{PerspectiveStage,enrich_perspective_clusters}.{0,1,2}.json
output/2026-05-08/_iteration/v2/state/   (same shape)
output/2026-05-08/_iteration/v3/state/   (same shape)
output/2026-05-08/_iteration/v4/state/   (same shape)
output/2026-05-08/_iteration/v5/state/   topic_buses.{PerspectiveStage,enrich_perspective_clusters,mirror_perspective_synced}.{0,1,2}.json
```

Each `enrich_perspective_clusters.{N}.json` is a full TopicBus dump containing the variant's `perspective_clusters[]` slot post-validation (pc-NNN IDs, partition repair, count fields). To re-inspect a variant: `python -c "import json; print(json.dumps(json.load(open('PATH'))['perspective_clusters'], indent=2))"`.

## Cost

Total perspective calls across the iteration (failed first smoke + recovery rerun): 27 calls. Per `run_stage_log.jsonl`, average $0.15 per call → total ~$4 / ~€3.7. Well under the brief's ~€7.50 estimate.

## Anomalies

**One process anomaly during the smoke**, recovered cleanly:

The first smoke pass used `--from PerspectiveStage --to mirror_perspective_synced` and copied `output/2026-05-08/tp-2026-05-08-*.json` per variant. Because the V2 runner skips post-run stages (RenderStage included) when `--to` cuts inside the topic-stage list — see `src/runner/runner.py:480–487` ("Runner: --to %s cuts before post-run stages; skipping render+finalize") — those TP JSONs were never regenerated with variant data. The five copies were byte-identical to baseline. Spotted by direct file diff after metric extraction returned suspiciously identical numbers across all variants.

Recovered by:
1. Saving v5's state files directly from `_state/run-{run_id}/` (v5 was the most recent run, so its state was the surviving copy in that directory).
2. Re-running v1–v4 with `--to enrich_perspective_clusters` and copying the per-stage state files to the iteration directory before the next variant overwrote `_state/`.

No agent failures, no schema-validator rejections. All 5 variants emit valid `position_clusters` arrays carrying the new `stated` / `reported` / `mentioned` sub-lists. The final INSTRUCTIONS.md md5 matches the pre-iteration snapshot bit-for-bit.

## Decision criteria reference (from brief, for transparency)

The architect's success criteria from the brief, restated here only so the reader can scan the table against them — the iteration does NOT optimize for these:

- TP-08-002 cluster count in the corridor 10–15 (current 11): met by v1 (10), v4 (13), v5 (13). Exceeded by v2 (21), v3 (16).
- Operational-label clusters per TP at zero or one (current TP-08-002 baseline: 3): no variant cleanly meets this on TP-08-002 (range 2–4). v1 reduces to 2. The classifier is over-inclusive (see the spotlight list).
- Reduction in unassigned-count metric in TP-08-002 (current 38): met by all five variants. v2 most aggressive (38 → 21). v1, v4, v5 all land near 31–32.
