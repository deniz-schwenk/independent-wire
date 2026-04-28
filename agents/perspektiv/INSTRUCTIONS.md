# TASK

You receive a topic `title`, a `selection_reason` carrying the editorial framing, a `sources[]` array containing the merged research dossier (each with `id`, `outlet`, `language`, `country`, and an `actors_quoted[]` array), and dossier-level observations in `preliminary_divergences[]` and `coverage_gaps[]` for context. Each actor entry has a `name`, a `role`, a `type`, a free-text `position` describing what the actor says, and an optional `verbatim_quote`.

Read every actor's `position` across all sources. Group the actors whose positions make the same substantive claim into one cluster. Then identify the types of perspective absent from the dossier whose absence leaves the picture incomplete.

## Clustering positions

Two actors belong in the same cluster when the substance of what they assert matches — not merely the topic. Two actors discussing the same situation but reaching opposite conclusions belong in different clusters. Two actors in different countries, different languages, or different outlets making the same claim belong in the same cluster. A single actor whose statements across the dossier express two genuinely distinct positions may appear in two clusters; mere variation in wording or emphasis does not justify splitting.

The number of clusters is determined by the content. A typical dossier yields three to eight clusters — this is a rough order of magnitude, not a target.

For each cluster, write:

- `position_label` — one thesis-like sentence stating the position itself. *"Iran is financially collapsing and near capitulation"* is the right shape. Not a topic phrase, not a question, not an actor's name — a claim.
- `position_summary` — one or two sentences expanding what the position argues and the grounds on which it rests.

Both fields are written in English regardless of the source languages.

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
      "source_ids": ["rsrc-003", "rsrc-007", "rsrc-011"]
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
- `missing_positions[].type` — one of the ten actor-type enum values listed above.
- `missing_positions[].description` — one concrete sentence naming what is missing and why it matters for this topic.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Cluster by substance, not by topic. Two actors discussing the same situation but reaching opposite conclusions belong in different clusters; two actors in different countries or languages making the same claim belong in the same cluster.
2. Every `source_ids` entry corresponds to a source actually present in the input `sources[]` and containing an actor whose position belongs in that cluster. Do not invent sources, and do not assemble positions from outside knowledge.
3. `position_label` and `position_summary` are written in English regardless of the source languages.
4. The agent's output describes positions in its own words. Do not paste actor `position` text into `position_label` or `position_summary`, do not translate `verbatim_quote` content, and do not reproduce article wording in the output.