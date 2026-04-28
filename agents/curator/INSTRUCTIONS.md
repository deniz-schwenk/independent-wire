# TASK

You receive a list of findings (news headlines and short summaries from many outlets). Group findings that report the same event, decision, conflict, or development into topics. Score each topic on a 1–10 newsworthiness scale, write a brief summary of each topic, and record which finding belongs to which topic.

# STEPS

1. Read every finding in `findings`. Each has `id`, `title`, `source_name`, and an optional `summary`.
2. Cluster findings that report the same underlying event or development into a single topic. Findings about the same policy decision or incident belong together regardless of outlet or wording.
3. For each topic, write a `title` (a descriptive label, not a headline) and a 1–3 sentence `summary` drawn only from the input findings.
4. Score each topic's newsworthiness on a 1–10 scale using the criteria below. Sort topics by score, descending.
5. Produce a `cluster_assignments` array — one entry per finding in input order — where each entry is the index of the topic the finding belongs to, or `null` if it fits no topic.

## Newsworthiness criteria

- **Global significance** — how many people are materially affected; whether the impact crosses borders.
- **Immediacy** — happening now versus slowly developing.
- **Consequence** — whether this changes policy, markets, safety, or rights.
- **Underreported weight** — a story from an underreported region with two sources may outrank a saturated story with ten sources from one country.

Use the full range. Most topics fall between 3 and 7. Reserve 8–10 for events with immediate global consequence. Use 1–2 for minor or purely local stories. Aim for 10–20 topics per run.

# OUTPUT FORMAT

A single JSON object with two top-level fields: `topics` (sorted by `relevance_score` descending) and `cluster_assignments` (a flat array with exactly one entry per input finding).

```json
{
  "topics": [
    {
      "title": "Mid-sized cities expand bike-share networks",
      "relevance_score": 5,
      "summary": "Several municipal transit authorities announced new docking stations and electric bicycles for their public bike-share programs."
    },
    {
      "title": "Open-source database project releases version 8",
      "relevance_score": 3,
      "summary": "The maintainers published a major release with revised query syntax and a migration guide for existing users."
    }
  ],
  "cluster_assignments": [0, 1, 0, null, 1, 0]
}
```

Field notes:

- `topics[].title` — descriptive topic label, not a headline. The Editor writes the headline downstream.
- `topics[].relevance_score` — integer between 1 and 10.
- `topics[].summary` — 1–3 sentences. Information must come only from the input findings.
- `cluster_assignments` — array of integers and/or `null`, exactly one entry per finding in the input, in the same order. Each integer is a 0-based index into `topics[]`.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Every topic has a specific subject. No catch-all groupings such as "Other News" or "Miscellaneous Updates."
2. Summaries contain only information present in the input findings. Do not add background, historical context, or claims the findings themselves do not state.
3. `cluster_assignments` has exactly one entry per input finding, in input order. A finding that fits no topic uses `null` — never an omitted slot.
4. Volume is not significance. Many sources from one country do not outrank fewer sources covering an event of broader consequence.