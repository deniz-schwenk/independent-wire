# BACKLOG-F2-PERSPECTIVE-CLUSTER-ASSIGNMENT

**Status:** investigation findings. No PE or CC follow-up brief yet.

**Owner:** Architect

**Created:** 2026-05-08, post pre-launch fix

## Context

The pre-launch fix in commit `cf6ef4a` reworded the actor-no-cluster label from "Quoted in Sources but not assigned to any cluster" to "Mentioned in sources, no clustered position." That ships the surface symptom. This investigation looks at the deeper cause: across the 6 TPs from 2026-05-07 / 2026-05-08, 33% of canonical actors (57 of 172) sit outside every cluster's `actor_ids[]`, including the dossier's structural protagonists (Putin, Trump, Lavrov in TP-08-002).

## Provenance

The cluster→actor mapping is produced in three files, in order:

1. **PerspectiveStage** (`src/agent_stages.py:946–1010`) — agent wrapper. Reads `final_sources`, `canonical_actors`, divergences, gaps. Calls the Perspective agent with prompt `agents/perspective/{SYSTEM,INSTRUCTIONS}.md`. Writes `perspective_clusters` raw — `[{position_label, position_summary, source_ids, actor_ids}]` — straight from the LLM's JSON without transformation.
2. **enrich_perspective_clusters** (`src/stages/topic_stages.py:640–674`) — deterministic post-processor. Validates each `actor_ids[]` entry against `canonical_actors[].id` (`topic_stages.py:603–625`). Drops unknown / aliased-out IDs with a warning, dedups, attaches `pc-NNN` plus `n_actors / n_sources / n_regions / n_languages`. **Does not add actors; only validates and drops.**
3. **mirror_perspective_synced** (`topic_stages.py:686–704`) — per-element mirror that copies into `perspective_clusters_synced`. In hydrated, the upstream perspective_sync stage may emit `position_cluster_updates`, but `_merge_perspective_deltas` (`agent_stages.py:821–874`) only merges `position_label` and `position_summary` — `actor_ids[]` is explicitly *not* in `mergeable_fields`. So the actor-id set the renderer reads is exactly what the Perspective agent emitted, minus invalid IDs.

The `actors[]` list the renderer reads (`scripts/render.py:_actors_section_render`) comes from `canonical_actors`, populated upstream by `resolve_actor_aliases` (strict-merge). That list is independent of cluster assignment — every named or institutional speaker quoted anywhere in the dossier appears in `actors[]` regardless of whether the Perspective agent included their `actor-NNN` in any cluster.

## Data

### Per-TP table

| Dossier | Actors | Clusters | Unassigned | Unas % | Med Q (assigned) | Med Q (unassigned) |
|---|---:|---:|---:|---:|---:|---:|
| tp-2026-05-07-001 | 33 | 11 |  4 | 12% | 1 | 1 |
| tp-2026-05-07-002 | 10 |  5 |  0 |  0% | 1 | 0 |
| tp-2026-05-07-003 | 22 |  8 |  1 |  5% | 1 | 1 |
| tp-2026-05-08-001 | 32 | 10 | 12 | 38% | 1 | 1 |
| tp-2026-05-08-002 | 63 | 10 | 39 | 62% | 1 | 1 |
| tp-2026-05-08-003 | 12 |  8 |  1 |  8% | 1 | 1 |

### 2×2 distribution (all 6 TPs combined)

|                        | 1 quote | 2+ quotes |
|------------------------|--------:|----------:|
| Assigned to cluster    |      84 |        31 |
| Not assigned           |      55 |         2 |

Among 1-quote actors, 84 / 139 = 60.4% are assigned. Among 2+ quote actors, 31 / 33 = 93.9% are assigned. Quote count is *correlated* with assignment but is not a hard threshold — the agent assigns most 1q actors and excludes only 2 actors with 2+ quotes across all 6 TPs (Russian transport ministry / 3q operational announcement; General Staff of Ukraine / 3q — both report logistics rather than positions).

### TP-2026-05-08-002 — structurally central unassigned (14 of 39)

All carry exactly 1 quote. Roles in `()`; quote-position field truncated for readability.

| Actor | Role | Quote (paraphrase from `quotes[0].position`) |
|---|---|---|
| Vladimir Putin | President of Russia | "Reportedly told Donald Trump during a phone call that Russia was ready to declare a ceasefire on May 9." |
| Donald Trump | President of the US | "Participated in a phone call where Putin allegedly discussed a potential ceasefire." |
| Sergey Lavrov | Russian Foreign Minister | "Allegedly communicated regarding ceasefire rewards through intermediaries to the U.S." |
| Steve Witkoff | Trump envoy | "Identified as a potential envoy to arrive in the Ukrainian capital after the Easter holidays." |
| Jared Kushner | Trump envoy | "Identified as a potential envoy to arrive in the Ukrainian capital after the Easter holidays." |
| Ilham Aliyev | President of Azerbaijan | "Discussed the issue of temporarily occupied Crimea during a meeting with President Zelensky in April 2026." |
| Andrey Nikitin | Russia's Transportation Minister | "Requested that airlines coordinate with state railways and bus services to transport stranded passengers." |
| Peter Magyar | Prime Minister of Hungary | "Returned seized assets to a Ukrainian bank but maintains a veto on Ukraine's EU accession pending a referendum." |
| Marek Eštok | State Secretary | "Reported to be accompanying the Slovak Prime Minister on his visit to Moscow." |
| Milorad Dodik | Former Republika Srpska president | "Expected to attend the commemorations in Moscow." |
| Denys Uliutin | Ukrainian Minister of Social Policy | "Stressed that Russian aggression caused the largest displacement in modern European history…" |
| Ugochi Daniels | IOM Deputy DG | "Discussed cooperation in migration policy…" |
| Pierre Vandier | NATO SACT | "Briefed the NATO-Ukraine Council on JATEC progress." |
| Yevhen Moisiuk | Ukrainian Deputy Defence Minister | "Briefed permanent representatives on interoperability lessons…" |

The quote forms cluster into three classes: (a) **reported attribution** ("Reportedly told", "Allegedly communicated", "Participated in a phone call where") — Putin / Trump / Lavrov. (b) **event-presence reports** ("Expected to attend", "Identified as a potential envoy", "Discussed the issue of … during a meeting with") — Witkoff / Kushner / Dodik / Aliyev / Eštok. (c) **operational/logistical announcements** without a directional position — Nikitin / Uliutin / Daniels / Vandier / Moisiuk / Magyar.

## Hypothesis

The Perspective prompt's assignment rule (`agents/perspective/INSTRUCTIONS.md:22`):

> *"For each cluster, list the `actor-NNN` IDs from `canonical_actors[]` whose statements actually express the cluster's position. Inclusion is decided from the actor's own words — what they say in any of their `quotes[].position` or `quotes[].verbatim` entries — not from the sources that quote them."*

reinforced at `INSTRUCTIONS.md:62`:

> *"an actor MAY NOT appear here merely because their source is cited in `source_ids`. Empty when the cluster's position is grounded only in source-level material."*

There is **no quote-count threshold in the prompt**. The rule is purely substance-based: an actor is assigned iff their own quote(s) express the cluster's position. The 2×2 confirms the agent honours this — 60% of 1-quote actors *are* assigned.

The agent's behaviour is therefore a **faithful execution of the prompt**, not a divergence. Rules out **(C)**.

But the rule has a systematic blind spot. The three quote classes in TP-08-002's central-unassigned list — reported attribution, event-presence reports, operational announcements — are all defensibly read as "not voicing a position." Putin's only quote in the dossier ("Reportedly told Trump that Russia was ready to declare a ceasefire") is the source's reported attribution, not a first-person stance; the position field paraphrases an act, not a claim. Under a strict reading of "the actor's own words," this is correctly excluded. Under a reader's intuition, the President of Russia missing from the perspective map of a Russia-Ukraine dossier looks like a pipeline failure. The label fix (`cf6ef4a`) papers over the wording but not the substance.

A softer rule would distinguish: when an actor's only quote is a reported attribution to a clear stance (e.g., "ready to declare a ceasefire on May 9" → has a stance, just reported indirectly), attach the actor to the closest-matching cluster. When the only quote is a non-positional event-presence or operational announcement, leave them unassigned. That distinction is rule-shaped, not count-shaped.

**Verdict: (B) Prompt is too strict** in one specific dimension — it treats reported-attribution quotes ("X reportedly said Y") as non-positional even when Y itself is a clear stance. The rule is internally consistent and faithfully executed, but produces a UX failure mode for event-driven dossiers where the main actors are covered via reported speech rather than direct statements.

## Decision criteria for follow-up

This becomes a TASK if either:

- The Russia-Ukraine pattern (Putin/Trump/Lavrov absent from the cluster map) repeats on the next 2–3 daily runs in dossiers about diplomatic episodes — i.e., a structural dossier class where reported attribution dominates.
- A reader / external reviewer flags the absence as confusing (the label fix's hypothesis was that it resolves the perception issue; if it does, this stays a BACKLOG).

If commissioned, the PE brief would target a single clause in `INSTRUCTIONS.md:22–24` with a softening rule: a 1-quote actor whose quote reports a clear stance (modal verbs of speech: "told", "said", "communicated", "announced", combined with a directional object) attaches to the closest-matching cluster. Estimated cost of a Perspective-only iteration with eval: ~€1.50 for re-running 3 archived dossiers (TP-08-001, TP-08-002, TP-08-003) Perspective-only via `--from PerspectiveStage --to PerspectiveStage --reuse 2026-05-08 --hydrated` × 1 prompt iteration. Eval is a re-count of the 2×2 above plus a manual spot-check that Russian transport ministry / Magyar / Dodik (true non-positions) stay unassigned.
