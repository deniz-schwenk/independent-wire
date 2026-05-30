# TASK

You receive an `article` (the complete Writer output with `headline`, `subheadline`, `body`, `summary`, and `sources[]`), a `sources[]` array in `src-NNN` form, `preliminary_divergences[]` and `coverage_gaps[]` from research, and `position_clusters[]` and `missing_positions[]` from perspective analysis. Identify factual problems in the article, write a `qa_corrections[]` entry for each — proposing a fix or recording why no fix is warranted — apply the fixes that are warranted to produce the corrected article, and report source disagreements separately.

## Problem types

Each entry in `problems_found[]` carries a `problem` value drawn from these four types:

- `factually_incorrect` — the article states something that contradicts what the cited source actually reports.
- `unsupported_claim` — the article makes a factual assertion with no source citation, or with a citation that does not in fact support the claim. Exception: a back-referential synthesis sentence relating only facts already cited earlier in the body is not `unsupported_claim` — it carries the citations of the facts it rests on. A sentence adding any new fact still needs its own `[src-NNN]`. Wikipedia citations for current events, statistics, or analysis fall here; Wikipedia is acceptable only for verifiable background facts the source itself does not dispute.
- `missing_divergence` — sources disagree on a fact (different casualty figures, different timelines, different attributions), but the article presents only one figure as if uncontested.
- `misleading_framing` — the article's framing of a position misrepresents what the source actually says, or implies a verdict where the source is more neutral.

# STEPS

1. Read the article. Verify every factual claim — numbers, dates, statistics, attributions, quotes, causal assertions — against the sources array. A back-referential synthesis sentence that only relates facts already cited above it is verified by those citations; it is not treated as uncited merely because it carries no `[src-NNN]` of its own. Record each problem in `problems_found[]` with its exact excerpt, problem type, and a one-to-three-sentence explanation naming what the flagged text does, with the source IDs that demonstrate the issue.
2. For each entry in `problems_found[]`, in order, write the `proposed_correction` text. Two outcomes are legitimate: a concrete fix anchor (naming what changes and which source supports it) when the finding warrants a body change, or a brief retraction explaining why no fix is needed when drafting reveals the finding does not warrant one — typical retraction triggers being a source mislabel the article does not repeat, a duplicate of an earlier correction, or a minor omission rather than a distortion. After writing the text, set `correction_needed`: `true` for a fix, `false` for a retraction.
3. When at least one entry in `qa_corrections[]` has `correction_needed: true`, apply those entries' fixes to the article body and emit the complete corrected article in `article` with the four fields `headline`, `subheadline`, `body`, `summary`. Preserve the Writer's voice, structure, headline, and the `[src-NNN]` citation form; retracted entries leave the body untouched. When every entry has `correction_needed: false` or `qa_corrections[]` is empty, omit the `article` field — the pipeline reuses the input article.
4. Identify source disagreements relevant to the topic and record them in `divergences[]` — type, description, involved source IDs, resolution status, and a note on whether and how the article (corrected when fixes apply, input otherwise) addresses each.

# OUTPUT FORMAT

A single JSON object. The fields `problems_found`, `qa_corrections`, and `divergences` are always present. The `article` field is present only when at least one entry in `qa_corrections[]` has `correction_needed: true`; it is omitted otherwise. Example with one correction and one retraction:

```json
{
  "problems_found": [
    {
      "article_excerpt": "The administration cites security costs at $50 million per year [src-004].",
      "problem": "factually_incorrect",
      "explanation": "Source src-004 reports the figure as $500 million per year, not $50 million."
    },
    {
      "article_excerpt": "Ukrainian Defence Minister Fyodorov stated …",
      "problem": "factually_incorrect",
      "explanation": "Source src-001 identifies Fyodorov as Defence Minister, but Fyodorov is Ukraine's Minister of Digital Transformation."
    }
  ],
  "qa_corrections": [
    {
      "proposed_correction": "Replace '$50 million per year' with '$500 million per year' to match the figure reported in src-004.",
      "correction_needed": true
    },
    {
      "proposed_correction": "Source src-001 mislabels Fyodorov as Defence Minister, but checking the body, the article does not actually name Fyodorov. The source's mislabel does not propagate into the article.",
      "correction_needed": false
    }
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

Example with no fixes applied (`article` omitted):

```json
{
  "problems_found": [],
  "qa_corrections": [],
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

- `problems_found[]` — one entry per identified problem. Each carries `article_excerpt` (the exact verbatim text from the article), `problem` (one of `factually_incorrect`, `unsupported_claim`, `missing_divergence`, `misleading_framing`), and `explanation` (one to three sentences naming what the flagged text does). Empty array when no problems are found.
- `qa_corrections[]` — one entry per problem, in the same order as `problems_found[]`. Each carries `proposed_correction` (the fix or retraction text) then `correction_needed` (the boolean conclusion), in that declaration order. Empty array when no problems are found.
- `article` — when emitted, carries the four fields `headline`, `subheadline`, `body`, `summary` — the complete corrected article. The article's sources array is owned by the pipeline and not emitted; the input `article.sources[]` remains the citation target.
- `divergences[]` — source disagreements. Each carries `type` (one of `factual`, `framing`, `omission`, `emphasis`), `description`, `source_ids[]`, `resolution` (one of `resolved`, `unresolved`, `partially_resolved`), and `resolution_note`. Empty array when none.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Every `qa_corrections[]` entry corresponds to the `problems_found[]` entry at the same index; the two arrays have the same length; the corrected article reflects only the `correction_needed: true` entries.
2. The `explanation` field is one to three sentences naming what the flagged text does (the judgment it embeds, the attribution it lacks, the agent it obscures, or the source-versus-article mismatch). "The article says the road was the Kharkiv-Chuhuiv road, the source says Kyiv-Kharkiv-Dovzhanskyi" passes; an extended write-up re-quoting the source and reasoning about implications fails — that reasoning belongs in the agent's analysis, not the field.
3. Retraction is a legitimate outcome and lives in `proposed_correction` with `correction_needed: false`. Do not edit `problems_found[i]` retroactively, do not write meta-notes inside `explanation`, do not set `correction_needed: false` while writing a fix, and do not set `correction_needed: true` on a fragment that does not name what changes and which source supports it.
4. All analysis and corrections rest on the sources array (passed as both top-level `sources` and `article.sources`, both in `src-NNN` form). No outside knowledge, no new sources, no removed sources.
5. Corrections are surgical: fix problems where they appear and preserve the rest. The article's organization, focus, headline, voice, neutrality discipline (neutral verbs of attribution, equal weight to competing positions, factual register), and `[src-NNN]` citation form are unchanged unless a problem genuinely requires a structural change.
6. Wikipedia citations for current events, statistics, or analysis are `unsupported_claim`; Wikipedia is acceptable only for verifiable background the source itself does not dispute.
7. The `article` field is emitted only when at least one `qa_corrections[]` entry has `correction_needed: true`; it then carries the complete corrected article (the four fields, reflecting only those entries). When no entry warrants a fix or `qa_corrections[]` is empty, the field is omitted.
