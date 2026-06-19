# BACKLOG — Topic conflation at the clustering stage  ⚠️ IMPORTANT

Status: OPEN — **IMPORTANT / HIGH PRIORITY**
Raised: 2026-06-18
Origin: diagnosis of tp-2026-06-18-002 ("Ghana Reparations as DRC
Ebola…"), run run-2026-06-18-5771ad7e. Full finding:
~/iw-stage-bench/diagnostics/TOPIC-CONFLATION-2026-06-18.md.

## Why IMPORTANT

This is not a cosmetic defect. A wrongly drawn topic boundary poisons
EVERY structured layer downstream — positions, source distribution,
bias card — because all of them are computed per topic. A conflated
topic produces a structurally invalid Topic Package: the core product
(multi-perspective transparency over ONE story) silently breaks. It
recurs whenever unrelated stories share a coarse semantic neighborhood,
so it is a standing quality risk, not a one-off.

## The defect (verified at primary artifacts)

tp-2026-06-18-002 fused four editorially separate stories — Ghana
reparations summit, DRC Ebola, M23/Human Rights Watch, Liberia-DRC-UNSC
agreement — into one package.

The boundary tears at the deterministic clustering stage
`pre_cluster_findings`, NOT at the Curator or Editor:

1. **Clustering is too coarse.** `src/stages/pre_cluster.py`:
   paraphrase-multilingual-MiniLM-L12-v2, agglomerative `linkage=
   'average'`, `metric='cosine'`, `distance_threshold=0.7`
   (≈ similarity ≥0.3) — verified in source. Loose enough that
   11-language "African + World Cup football" content collapses into
   one region. No explicit geo anchor is injected; the continent is the
   emergent centroid, with football match-reports acting as semantic
   glue between otherwise unrelated stories.
2. **Micro-cluster mc-002 (size 61)** already fuses all four strands +
   football + Haiti/Somalia/Cameroon items. They were never separated.
3. **Curator** named the already-fused blob (topic index 2);
   `gravitational_assign` (cosine-threshold-topk, T=0.55) then swept 33
   findings into it, 31 of 33 tracing to mc-002. The curator cannot
   separate what arrives as one cluster.
4. **Editor caught it but could not fix it** — it explicitly flagged
   the Ebola component as repetitive / extensively covered across prior
   packages (verbatim in EditorStage bus), yet assigned priority and
   published. Structural reasons: an EditorAssignment is 1:1
   (rename/reject only, no split lever), and the editor agent is fed
   the title, not the findings.

Verification caveat: the exact curator proposal string for index 2 was
not isolated at the artifact during architect re-verification (bus
structure nesting); CC's quoted blob is consistent with the rest but
should be re-confirmed at primary data if it becomes load-bearing for
the fix decision.

## Where intervention is most effective (input for a later decision, NOT a fix)

- **Earliest and cheapest: clustering granularity at
  `pre_cluster_findings`.** No downstream stage re-segments findings,
  so every error here propagates unchecked. Tightening the threshold or
  the linkage is the smallest lever with the largest reach.
- **If an explicit split capability is wanted:** it must live at or
  before `CuratorTopicDiscoveryStage`, where boundaries are still
  mutable.
- **The Editor is the worst place to fix it:** it sees the conflation
  but has neither the findings nor a split lever.

## Cross-cutting note — sport as semantic glue

Football match-reports act as the connective tissue pulling unrelated
stories together at clustering. The Editor sport-threshold rule
(rule 5) filters sport OUT at the editorial stage — far too late to
prevent this clustering effect. This is an argument for handling sport
earlier in the pipeline; relevant to scope when this item is taken up.

## Relation to other work

Independent of the translation and bias workstreams. Touches the
deterministic clustering core of the English pipeline — a production
pipeline change, to be scoped properly (Architect diagnosis done; no
work package written yet).
