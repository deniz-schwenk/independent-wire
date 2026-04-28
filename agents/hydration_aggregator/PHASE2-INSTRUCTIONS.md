# TASK

You receive an `assignment` (with `title` and `selection_reason`) and two parallel arrays — `article_analyses[]` and `article_metadata[]` — both keyed by `article_index`, one entry per article. Each `article_analyses` entry carries the article's `summary` and extracted `actors_quoted[]`. Each `article_metadata` entry carries the article's `language` (ISO 639-1), `country`, and `outlet`. The corpus typically spans 10 to 40 articles across multiple languages and regions. Group the articles by language and by region. Compare the framings across language groups and across regional clusters to identify cross-group divergences. Then assess what perspectives the corpus does not cover.

Divergences and gaps are observations about the corpus as a whole — patterns across language groups and regional clusters. Differences between two articles in the same language group are not divergences in this sense.

## Identifying divergences

For each pair of language groups or regional clusters, look at:

- which facts each group emphasizes
- which actors each group quotes
- how each group characterizes the events
- what consequences each group foregrounds
- what one group covers that another omits

Write each substantive cross-group difference as one clear sentence that names the specific language groups or regional clusters involved.

## Identifying gaps

Assess what the corpus does not cover. Look for:

- regions central to the story that have no coverage anywhere in the corpus
- stakeholder types that are not represented by any quoted actor
- dimensions of the story that no article addresses

Write each substantive absence as one clear sentence that names what is missing and why its absence matters for this topic.

# OUTPUT FORMAT

A single JSON object with two top-level fields. Example:

```json
{
  "preliminary_divergences": [
    "Arabic-language sources frame the naval blockade as an act of economic warfare targeting civilian shipping, while English-language sources frame it as a nonproliferation enforcement measure with humanitarian carve-outs.",
    "Russian-language sources foreground the impact on Caspian basin oil flows; no other language group covers this angle."
  ],
  "coverage_gaps": [
    "No perspectives from Gulf Arab energy exporters despite their direct exposure to Strait of Hormuz disruptions.",
    "No civil-society or affected-community voices anywhere in the corpus — every quoted actor is a government official, military spokesperson, or industry analyst."
  ]
}
```

Field notes:

- `preliminary_divergences[]` — array of single-sentence strings. Each names the specific language groups or regional clusters involved and the substantive difference between them. May be empty when no clear cross-group divergence exists.
- `coverage_gaps[]` — array of single-sentence strings. Each names a specific missing region, stakeholder type, or dimension. May be empty when the corpus is genuinely well-balanced.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Each divergence and each gap is a pattern across language groups or regional clusters. Differences between two articles within the same language group are not divergences in this sense.
2. Each divergence names what differs and which groups it differs between. Each gap names what is missing and why its absence matters for this topic. Generic phrasing such as "articles differ in emphasis" or "more sources needed" is insufficient.
3. Observations rest on what `article_analyses` actually says. Do not infer content beyond what the analyses describe, and do not reference `article_index` values that are not present in the input.