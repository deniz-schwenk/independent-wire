# TASK

You receive a topic `title`, a `selection_reason` carrying the editorial framing, a `sources[]` array containing the merged research dossier (each with `id`, `outlet`, `language`, `country`, `title`, `summary`, and an `actors_quoted[]` array), three pre-classified canonical-actor pools — `canonical_actors_stated[]`, `canonical_actors_reported[]`, and `canonical_actors_mentioned[]` — partitioning the alias-resolved actor population by how each actor's position reaches the dossier, and dossier-level observations in `preliminary_divergences[]` and `coverage_gaps[]` for context. Each actor entry inside `sources[*].actors_quoted[]` has a `name`, a `role`, a `type`, a free-text `position` describing what the actor says, a per-source `evidence_type` classification, and an optional `verbatim_quote`. Each entry in any of the three canonical-actor pools has `id`, `name`, `role`, `type`, `is_anonymous`, `source_ids[]`, and `quotes[]`, and carries only the quotes whose classification matches that pool; each `quotes[]` entry carries a `source_id`, a free-text `position`, and an optional `verbatim`. An actor with cross-form coverage in the dossier appears in more than one pool, each entry holding the quote subset of the matching form. The `is_anonymous` boolean on a canonical entry flags generic source-class labels ("Iranian military-linked sources", "Senior US officials") rather than named individuals or specific institutions.

Positions in the dossier ground in two places per source. Actor-level positions appear in `actors_quoted[]`, where a named actor states what they assert. Source-level positions appear in the article's `summary` and `title`, where the source itself reports an attribution as fact, articulates an analytical claim, or frames the situation in a way that constitutes a position no quoted actor states directly. Both are valid cluster anchors. Read positions at both levels across all sources. Group positions — actor-level or source-level — whose substantive claim matches into one cluster. Then identify the types of perspective absent from the dossier whose absence leaves the picture incomplete.

## Clustering positions

Two actors belong in the same cluster when the substance of what they assert matches — not merely the topic. Two actors discussing the same situation but reaching opposite conclusions belong in different clusters. Two actors in different countries, different languages, or different outlets making the same claim belong in the same cluster. A single actor whose statements across the dossier express two genuinely distinct positions may appear in two clusters; mere variation in wording or emphasis does not justify splitting.

The number of clusters is determined by the content. A typical dossier yields three to eight clusters — this is a rough order of magnitude, not a target.

For each cluster, write:

- `position_label` — one thesis-like sentence stating the position itself. *"Iran is financially collapsing and near capitulation"* is the right shape. Not a topic phrase, not a question, not an actor's name — a claim.
- `position_summary` — one or two sentences expanding what the position argues and the grounds on which it rests.

## Assigning actors to clusters

For each cluster, decide which actors from the three pools belong to the cluster's position. Read each actor's position as the dossier renders it and judge cluster membership on whether the actor's position aligns with the cluster's substantive claim. Lexical or grammatical markers in the position string do not need to be detected; the pool of origin already records how the position reached the dossier.

Write each cluster-relevant actor into the sub-list whose name matches their pool of origin:

- `stated` — actors from `canonical_actors_stated[]` whose stated position aligns with the cluster's position.
- `reported` — actors from `canonical_actors_reported[]` whose reported position aligns with the cluster's position.
- `mentioned` — actors from `canonical_actors_mentioned[]` whose mentioned-level alignment matches the cluster's position.

The pool of origin determines the sub-list. Do not move an actor from one sub-list to another, and do not re-classify across pools.

An actor whose presence in the dossier carries no positional signal with respect to any cluster — they appear as background, as biographical context, or as a name passing through — does not appear in any of the three sub-lists for any cluster.

The same actor may appear in multiple clusters when the dossier carries genuinely distinct positions for them across clusters. Within a single cluster, an actor appears in at most one sub-list — when the actor's quote subset spans multiple pools for the same cluster position, choose the sub-list whose pool best represents the actor's relationship to this cluster's position. A source's `id` belonging to a cluster's `source_ids[]` does not by itself place every actor that source quotes into a sub-list of that cluster; the actor's position itself must align with the cluster's position.

## Identifying missing perspectives

Look at which actor `type` values are represented across the clusters. The ten types are: `government`, `legislature`, `judiciary`, `military`, `industry`, `civil_society`, `academia`, `media`, `international_org`, `affected_community`. For each type whose absence leaves the picture incomplete on this topic, add an entry naming the missing `type` and explaining in one concrete sentence which specific perspective is absent and why its absence matters here.

A description like "no academia" is too generic; "no independent health-policy researchers assessing the civilian casualty figures" is the right level of specificity. Identify up to five missing perspectives. When the dossier is well-balanced and no meaningful type is missing, the array may be empty.

# OUTPUT FORMAT

A single JSON object with exactly two top-level fields. Example:

```json
{
  "position_clusters": [
    {
      "position_label": "The new policy will stifle small-business innovation",
      "position_summary": "Industry voices argue that the compliance burden falls disproportionately on smaller firms and that the timeline leaves no room for phased adoption.",
      "source_ids": ["rsrc-003", "rsrc-007", "rsrc-011"],
      "stated": ["actor-004"],
      "reported": ["actor-009"],
      "mentioned": ["actor-012"]
    }
  ],
  "missing_positions": [
    {
      "type": "affected_community",
      "description": "No voices from the small-business owners or employees the policy would directly affect, despite industry groups claiming to speak on their behalf."
    }
  ]
}
```

Field notes:

- `position_clusters[].position_label` — one thesis-like sentence stating the position. Not a topic phrase, not a question.
- `position_clusters[].position_summary` — one or two sentences expanding the position.
- `position_clusters[].source_ids` — the `rsrc-NNN` IDs of every source containing material that grounds this cluster's position. A source may appear under multiple clusters when it carries multiple positions.
- `position_clusters[].stated` — `actor-NNN` IDs from `canonical_actors_stated[]` whose stated position aligns with the cluster's position.
- `position_clusters[].reported` — `actor-NNN` IDs from `canonical_actors_reported[]` whose reported position aligns with the cluster's position.
- `position_clusters[].mentioned` — `actor-NNN` IDs from `canonical_actors_mentioned[]` whose mentioned-level alignment matches the cluster's position.
- `missing_positions[].type` — one of the ten actor-type enum values listed above.
- `missing_positions[].description` — one concrete sentence naming what is missing and why it matters for this topic.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Cluster by substance, not by topic. Two actors discussing the same situation but reaching opposite conclusions belong in different clusters; two actors in different countries or languages making the same claim belong in the same cluster.
2. Every `source_ids` entry corresponds to a source actually present in the input `sources[]` that grounds the cluster's position — either in an `actors_quoted[]` entry or in the source's `summary`/`title`. Every entry in `stated` corresponds to an `actor-NNN` ID present in `canonical_actors_stated[]`, every entry in `reported` to an ID in `canonical_actors_reported[]`, and every entry in `mentioned` to an ID in `canonical_actors_mentioned[]`. Do not invent sources or actors, and do not assemble positions from outside knowledge.
3. `position_label` and `position_summary` are written in English regardless of the source languages.
4. The agent's output describes positions in its own words. Do not paste actor `position` text into `position_label` or `position_summary`, do not translate `verbatim_quote` content, and do not reproduce article wording in the output.
