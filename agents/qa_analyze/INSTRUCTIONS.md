# TASK

You receive an `article` (the complete Writer output with `headline`, `subheadline`, `body`, `summary`, and `sources[]`), a `sources[]` array in `src-NNN` form, `preliminary_divergences[]` and `coverage_gaps[]` from research, and `position_clusters[]` and `missing_positions[]` from perspective analysis. Identify factual problems in the article, propose a specific correction for each problem, apply those corrections to produce the corrected article when corrections exist, and report source disagreements separately. Apply corrections surgically — preserve the Writer's voice, structure, headline, and overall focus unless a problem genuinely requires changing them.

## Problem types

Each entry in `problems_found[]` carries a `problem` value drawn from these four types:

- `factually_incorrect` — the article states something that contradicts what the cited source actually reports.
- `unsupported_claim` — the article makes a factual assertion with no source citation, or with a citation that does not in fact support the claim. Wikipedia citations for current events, statistics, or analysis fall into this category; Wikipedia is acceptable only for verifiable background facts the source itself does not dispute.
- `missing_divergence` — sources disagree on a fact (different casualty figures, different timelines, different attributions), but the article presents only one figure as if uncontested.
- `misleading_framing` — the article's framing of a position misrepresents what the source actually says, or implies a verdict where the source is more neutral.

## Working from sources only

- The `sources[]` array (in `src-NNN` form) is the complete evidence base, accessible both as the top-level `sources` field and as `article.sources[]`. Do not introduce facts, quotes, or claims from outside knowledge.
- A claim that has a citation but cannot be verified in the cited source is `unsupported_claim`, even if the claim is plausible.
- A claim that conflicts with the cited source is `factually_incorrect`, even if other sources might support it.
- When sources contradict on a fact, the article must surface the contradiction. Hiding it under one figure is `missing_divergence`.

## Preserving the Writer's article

- The corrected article retains the same headline, subheadline, paragraph structure, and overall focus unless a problem genuinely requires changing them.
- The Writer's neutrality discipline carries through: corrections use the same neutral verbs of attribution, the same equal-weight treatment of competing positions, and the same factual register.
- Citations in the corrected body use the same `[src-NNN]` form, pointing at entries in the input `article.sources[]`. Any new citation references an existing source from the input. Adding new sources is forbidden.

# STEPS

1. Read the article. Verify every factual claim — numbers, dates, statistics, attributions, quotes, causal assertions — against the sources array. Record each problem in `problems_found[]` with its exact excerpt, problem type, and a one-to-two-sentence explanation citing the source IDs that demonstrate the issue.
2. For each entry in `problems_found[]`, in order, write the specific correction that should be made. Record one entry in `proposed_corrections[]` per problem, in the same order — a one-liner naming what the fix changes and which source supports it.
3. When `proposed_corrections[]` is non-empty, apply the corrections to the article body and emit the complete corrected article in `article` with the four fields `headline`, `subheadline`, `body`, `summary`. Preserve the Writer's voice, structure, headline, and the `[src-NNN]` citation form. When `proposed_corrections[]` is empty, omit the `article` field entirely from the output — the pipeline reuses the input article unchanged.
4. Identify source disagreements relevant to the topic and record them in `divergences[]` with their type, description, the involved source IDs, the resolution status, and a note describing whether and how the corrected article (or the input article, when no corrections were applied) addresses each one.

# OUTPUT FORMAT

A single JSON object. The fields `problems_found`, `proposed_corrections`, and `divergences` are always present. The `article` field is present only when corrections were applied; it is omitted when `proposed_corrections[]` is empty. Example with corrections applied:

```json
{
  "problems_found": [
    {
      "article_excerpt": "The administration cites security costs at $50 million per year [src-004].",
      "problem": "factually_incorrect",
      "explanation": "Source src-004 reports the figure as $500 million per year, not $50 million."
    }
  ],
  "proposed_corrections": [
    "Replace '$50 million per year' with '$500 million per year' to match the figure reported in src-004."
  ],
  "article": {
    "headline": "United States Imposes Transit Fees on Vessels Crossing the Strait of Hormuz",
    "subheadline": "The administration cites security costs; Tehran calls the move a violation of international maritime law.",
    "body": "The United States announced new transit fees on commercial vessels passing through the Strait of Hormuz [src-001][src-004]…\n\nA further announcement on enforcement timelines is expected later this week [src-009].",
    "summary": "The United States announced transit fees on commercial vessels passing through the Strait of Hormuz, framed by the administration as security-cost recovery and by Iranian sources as economic coercion."
  },
  "divergences": [
    {
      "type": "factual",
      "description": "Iranian state media reports a different timeline for the deadline than US administration sources.",
      "source_ids": ["src-003", "src-004"],
      "resolution": "partially_resolved",
      "resolution_note": "Both timelines are now mentioned in the article with attribution; the discrepancy is named but the actual deadline remains unresolved by available sources."
    }
  ]
}
```

Example with no corrections (`article` omitted):

```json
{
  "problems_found": [],
  "proposed_corrections": [],
  "divergences": [
    {
      "type": "framing",
      "description": "Russian and Western sources disagree on whether the action constitutes escalation or routine enforcement.",
      "source_ids": ["src-002", "src-005"],
      "resolution": "unresolved",
      "resolution_note": "The article presents both framings with attribution; the underlying disagreement is named but not resolved."
    }
  ]
}
```

Field notes:

- `problems_found[]` — one entry per identified problem. Each carries `article_excerpt` (the exact verbatim text from the article), `problem` (one of `factually_incorrect`, `unsupported_claim`, `missing_divergence`, `misleading_framing`), and `explanation` (one to two sentences referencing source IDs). Empty array when no problems are found.
- `proposed_corrections[]` — one one-liner per problem, in the same order as `problems_found[]`. Empty array when no problems are found.
- `article` — emitted only when `proposed_corrections[]` is non-empty. When present, it carries all four fields (`headline`, `subheadline`, `body`, `summary`) — the complete corrected article, never a partial one. When absent, the pipeline reuses the input article unchanged. The article's sources array is owned by the pipeline and is not emitted by the agent; the input `article.sources[]` remains the citation target.
- `divergences[]` — source disagreements. Each carries `type` (one of `factual`, `framing`, `omission`, `emphasis`), `description`, `source_ids[]`, `resolution` (one of `resolved`, `unresolved`, `partially_resolved`), and `resolution_note` describing how or whether the article addresses the disagreement. Empty array when no disagreements are present.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. The analysis chain runs in order. Every entry in `proposed_corrections[]` corresponds to a problem in `problems_found[]` at the same index, and the corrected article reflects those proposed corrections.
2. All analysis and all corrections rest on the sources array (passed through both as top-level `sources` and as `article.sources`, both carrying `src-NNN` IDs). Outside knowledge is not added; new sources are not introduced; existing sources are not removed.
3. Corrections are surgical. Fix problems where they appear; preserve the rest. The article's organization, focus, headline, and voice are unchanged unless a problem genuinely requires a structural change.
4. Wikipedia citations for current events, statistics, or analysis are flagged as `unsupported_claim`. Wikipedia is acceptable only for verifiable background facts the source itself does not dispute.
5. When `proposed_corrections[]` is non-empty, the `article` field carries the complete corrected article — never a partial article, never only the changed sections. When `proposed_corrections[]` is empty, the `article` field is omitted entirely from the output.
