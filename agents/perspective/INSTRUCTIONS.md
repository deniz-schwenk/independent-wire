# TASK

You receive a topic `title`, a `selection_reason` carrying the editorial framing, a `sources[]` array containing the merged research dossier (each with `id`, `outlet`, `language`, `country`, `title`, `summary`, and an `actors_quoted[]` array), a `canonical_actors[]` array carrying the alias-resolved deduplicated list of every actor quoted across the dossier (each with `id`, `name`, `role`, `type`, `is_anonymous`, `source_ids[]`, and `quotes[]`), and dossier-level observations in `preliminary_divergences[]` and `coverage_gaps[]` for context. Each actor entry inside `sources[*].actors_quoted[]` has a `name`, a `role`, a `type`, a free-text `position` describing what the actor says, and an optional `verbatim_quote`. Each entry inside `canonical_actors[].quotes[]` carries a `source_id`, a free-text `position`, and an optional `verbatim` (the same speaker re-emitted across every source they appear in). The `is_anonymous` boolean on a canonical entry flags generic source-class labels ("Iranian military-linked sources", "Senior US officials") rather than named individuals or specific institutions.

Positions in the dossier ground in two places per source. Actor-level positions appear in `actors_quoted[]`, where a named actor states what they assert. Source-level positions appear in the article's `summary` and `title`, where the source itself reports an attribution as fact, articulates an analytical claim, or frames the situation in a way that constitutes a position no quoted actor states directly. Both are valid cluster anchors. Read positions at both levels across all sources. Group positions — actor-level or source-level — whose substantive claim matches into one cluster. Then identify the types of perspective absent from the dossier whose absence leaves the picture incomplete.

## Clustering positions

Two actors belong in the same cluster when the substance of what they assert matches — not merely the topic. Two actors discussing the same situation but reaching opposite conclusions belong in different clusters. Two actors in different countries, different languages, or different outlets making the same claim belong in the same cluster. A single actor whose statements across the dossier express two genuinely distinct positions may appear in two clusters; mere variation in wording or emphasis does not justify splitting.

The number of clusters is determined by the content. A typical dossier yields three to eight clusters — this is a rough order of magnitude, not a target.

For each cluster, write:

- `position_label` — one thesis-like sentence stating the position itself. *"Iran is financially collapsing and near capitulation"* is the right shape. Not a topic phrase, not a question, not an actor's name — a claim.
- `position_summary` — one or two sentences expanding what the position argues and the grounds on which it rests.

Both fields are written in English regardless of the source languages.

## Assigning actors to clusters

For each cluster, list the `actor-NNN` IDs from `canonical_actors[]` whose statements actually express the cluster's position. Inclusion is decided from the actor's own words — what they say in any of their `quotes[].position` or `quotes[].verbatim` entries — not from the sources that quote them. An actor whose source is cited in the cluster but whose own statements voice a different position is not an actor of this cluster.

A single actor may appear in two clusters when they have voiced two genuinely distinct positions; this is correct and expected. Conversely, an actor's quoted source can feed a cluster (its source-id is in `source_ids`) without the actor themselves belonging to that cluster (their actor-id is not in `actor_ids`) — for example when the source's `summary` or another speaker in the same source carries the cluster's position.

An example of correct assignment: a source quotes both a foreign minister calling for restraint and an opposition deputy demanding escalation. The foreign minister's `actor-NNN` belongs only in the restraint cluster; the deputy's `actor-NNN` belongs only in the escalation cluster; the source's `id` may legitimately appear under both because both positions ground in it. An example of incorrect assignment: placing every actor quoted in a multi-position source into every cluster the source feeds. That is the leak this list is designed to prevent.

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
      "actor_ids": ["actor-004", "actor-009"]
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

- `position_clusters[].position_label` — one thesis-like sentence stating the position. Not a topic phrase, not a question. English regardless of source language.
- `position_clusters[].position_summary` — one or two sentences expanding the position. English regardless of source language.
- `position_clusters[].source_ids` — the `rsrc-NNN` IDs of every source containing an actor expressing this cluster's position. A source may appear under multiple clusters when it quotes actors with different positions.
- `position_clusters[].actor_ids` — the `actor-NNN` IDs from `canonical_actors[]` whose own statements voice this cluster's position. An actor may appear under multiple clusters when their statements across the dossier express genuinely distinct positions; an actor MAY NOT appear here merely because their source is cited in `source_ids`. Empty when the cluster's position is grounded only in source-level material (a `summary` or `title` claim no quoted actor states).
- `missing_positions[].type` — one of the ten actor-type enum values listed above.
- `missing_positions[].description` — one concrete sentence naming what is missing and why it matters for this topic.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Cluster by substance, not by topic. Two actors discussing the same situation but reaching opposite conclusions belong in different clusters; two actors in different countries or languages making the same claim belong in the same cluster.
2. Every `source_ids` entry corresponds to a source actually present in the input `sources[]` that grounds the cluster's position — either in an `actors_quoted[]` entry or in the source's `summary`/`title`. Every `actor_ids` entry corresponds to an `actor-NNN` ID present in the input `canonical_actors[]`. Do not invent sources or actors, and do not assemble positions from outside knowledge.
3. `position_label` and `position_summary` are written in English regardless of the source languages.
4. The agent's output describes positions in its own words. Do not paste actor `position` text into `position_label` or `position_summary`, do not translate `verbatim_quote` content, and do not reproduce article wording in the output.