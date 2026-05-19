# BACKLOG-CLUSTER-FORMATION-SINGLE-ACTOR

**Status:** activation criterion met on 2026-05-19 — see "Activation signal" section below. PE brief not yet drafted.

**Owner:** Architect

**Created:** 2026-05-11

**Related commit:** evidence-type classification at Hydration layer
(this commit)

**Related BACKLOGs:**
`BACKLOG-PERSPECTIVE-CLUSTER-FORMATION-ITERATION.md` (prior 5-variant
prompt-iteration, rejected for false-positive collateral)

## The pattern

When an actor carries a substantively distinct position that no other
actor in the dossier shares, Perspective does not form a single-actor
cluster around it. The position drops out of the cluster output
entirely.

Both Flash and DeepSeek exhibit this. The new evidence-type pool
architecture does not address it — the agent still aggregates positions
into clusters in groups of two or more, and a unique single-source
single-actor position has no second voice to join.

## Production evidence

TP-08-002 (Russia/Victory Day), DeepSeek production run 2026-05-11:

- **The dropped position.** Putin offered Russia would declare a
  ceasefire on May 9 during a phone call with Trump (src-024 /
  Ukrinform). One source, one actor (Putin); no other actor in the
  dossier voices a position about a ceasefire offer from the Russian
  side.
- **DeepSeek result.** Putin is in 0 clusters. The ceasefire-offer
  position is absent from `perspectives.position_clusters[]`. Putin's
  remaining quotes (parade-related context) did not trigger inclusion
  in any tangential cluster either.
- **Flash result on the same dossier.** Putin is in 2 clusters at the
  `reported` tier — pc-005 ("scaled-back parade reflects vulnerability")
  and pc-006 ("Kremlin frames scaling back as strategic choice"). Both
  cover Putin's parade-context positions; neither addresses the
  ceasefire offer. Result: Flash assigns Putin to *some* clusters, but
  not the substantively unique ceasefire-offer cluster, which doesn't
  exist in either model's output.

Net: under both models, a structurally central actor (head of state
making a peace overture) with a substantively unique position has that
position elided from the published cluster output.

## Prior investigation

`BACKLOG-PERSPECTIVE-CLUSTER-FORMATION-ITERATION.md` captures a
five-variant prompt iteration in 2026-05-09 that targeted this exact
cluster-formation threshold (single-actor membership floor). Five
mechanically distinct prompt variants were smoke-tested across three
2026-05-08 dossiers. The iteration was rejected for false-positive
collateral: when the floor was lowered to admit single-actor clusters,
the agent generated **more** operational-label clusters (transportation
arrangements, security postures, scheduling) being clustered as
positions when they were really logistical descriptions.

## Why this is plausibly viable now

Two structural changes since that iteration reduce the
false-positive risk:

1. **Recipient-exclusion rule.** Hydration-Phase-1 (DeepSeek) now
   correctly excludes recipients of phone calls and addressees of
   speech-acts from `actors_quoted`. Border-line "actors" that mostly
   surfaced operational-label clusters under the old extraction
   (mediators, logistical points of contact, addressees of joint
   statements) are now excluded earlier in the pipeline. Less raw
   material for false positives.
2. **Evidence-type pool partition.** Perspective sees the three pools
   pre-classified by Hydration. A logistical description landing in
   `canonical_actors_mentioned[]` (because the article describes the
   action without quoting the actor) is structurally separated from a
   substantive position landing in `canonical_actors_stated[]`. Even
   if Perspective lowers its membership floor, lowering it on the
   `stated[]` pool specifically (where the false-positive risk is
   lowest) is more targeted than the prior all-tier intervention.

A focused single-variant iteration on the cluster-formation threshold,
scoped to `stated[]` membership, is plausibly viable post-launch where
it wasn't pre-migration.

## Decision criterion for activation

This becomes a TASK if production users surface the Putin-shaped
pattern — **a structurally central actor with a single-source position
disappearing from cluster output** — in multiple post-launch dossiers.
A single instance per dossier is acceptable: the substance-based
classifier and the evidence-type partition can absorb one or two edge
cases per topic without misleading the published output. What would
activate this work is a structural pattern across topics where
single-actor positions of consequence (peace offers, treaty
declarations, resignations, novel policy announcements) repeatedly
fail to surface in `position_clusters[]` and have to be reconstructed
from the article body manually.

## Activation signal — 2026-05-19

The first post-flash-swap daily run (3 hydrated TPs published) surfaced
the Putin-shaped pattern across multiple dossiers. The relevant
production observation is **tp-2026-05-19-003** (Ebola outbreak in DR
Congo / Uganda).

### Orphan rate per dossier (actors in `actors[]` not assigned to any `position_clusters[].actor_ids[]`):

| Dossier | Actors | Clusters | Orphans | Orphan % |
|---|---:|---:|---:|---:|
| tp-2026-05-19-001 (Iran ultimatum) | 33 | 9 | 5 | 15% |
| tp-2026-05-19-002 (Gaza flotilla) | 38 | 10 | 3 | 8% |
| tp-2026-05-19-003 (Ebola PHEIC) | 41 | 9 | 6 | 15% |

### Why this is the activation signal

In tp-19-001 and tp-19-002 the orphans are defensibly tangential —
actors who appear in source articles but whose contribution is
event-presence, biographical, or non-positional. The renderer label
"Mentioned in sources, no clustered position" is journalistically
honest for these.

In tp-19-003 the orphans include the dossier's structural
protagonists:

| Actor | Type | Sources | Quotes |
|---|---|---:|---:|
| Samuel Roger Kamba (DR Congo Health Minister) | government | 6 | 6 |
| German Ministry of Health | government | 4 | 4 |
| Centers for Disease Control and Prevention (CDC) | government | 2 | 2 |
| Satish Pillai (CDC Ebola response coordinator) | government | 1 | 1 |
| Félix Tshisekedi (DR Congo President) | government | 1 | 1 |
| Doctors Without Borders | civil_society | 1 | 1 |

A health-emergency dossier where the affected country's Health Minister
(6 quotes from 6 sources), the affected country's President, the CDC
response coordinator, and the German health authority are all absent
from `position_clusters` fails the multi-perspective promise of the
Topic Package. The reader's natural question — "what is the DRC
government saying about this outbreak?" — has an answer in the source
material that the perspective output does not surface.

This is exactly the "structurally central actor with a single-source
position disappearing from cluster output" criterion in the section
above. The 2026-05-08 Putin/Trump/Lavrov outlier has now repeated.

### Path considered and rejected: tactical renderer filter

A renderer-side filter that hides orphan actors from the Actors-section
would visually clean up the Iran / Gaza dossiers (where orphans are
tangential) at the cost of hiding the DR Congo Health Minister and the
DR Congo President from the Ebola dossier's Actors-section. That trades
one symptom for a worse one — the protagonists the reader most needs
to hear from get suppressed because the clustering missed them. The
renderer filter is rejected; the fix must happen at the cluster-
formation layer.

### Disposition

Activate the workstream shape described in `## Suggested workstream
shape (when activated)` below as a PE brief when scheduling permits.
Substrate of choice: tp-2026-05-19-003 (Ebola PHEIC) and
tp-2026-05-19-001 (Iran ultimatum), plus the existing TP-08-002
reference case for continuity with the prior 5-variant iteration.

## Suggested workstream shape (when activated)

Single-variant prompt iteration on the `## Assigning actors to
clusters` section of `agents/perspective/INSTRUCTIONS.md`. Candidate
intervention: add a paragraph stating that the cluster set must cover
substantively distinct positions in the dossier, including positions
voiced by a single actor when no second actor expresses the same
position, with the constraint scoped to `stated[]` pool members
(i.e., the actor's own words are in the dossier).

Smoke methodology: re-run TP-08-002 + two follow-up production
dossiers under the variant prompt. Track:

- Number of single-actor `stated`-tier clusters created.
- Number of operational-label clusters created (false-positive
  metric carried from the prior iteration).
- TP-08-002 Putin ceasefire-offer cluster: created or not.

Activation gate: cluster count stays in corridor (10-15), operational-
label count does not increase, Putin ceasefire-offer cluster surfaces.

## Out of scope here

- Cross-tier cluster membership invariants (already enforced by the
  validator's pool-source consistency check)
- Recipient-exclusion behaviour (working correctly under DeepSeek per
  the new commit)
- Attributional fidelity in position strings (working correctly under
  DeepSeek per the new commit)
- Production model decision for Hydration-Phase-1 (settled —
  DeepSeek-V4-Pro)
