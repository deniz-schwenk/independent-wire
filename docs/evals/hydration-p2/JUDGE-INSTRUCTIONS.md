# TASK

You receive:
- `article_analyses[]` and `article_metadata[]` — the GROUND TRUTH: what each
  article in the corpus says (`summary`, `actors_quoted`) and its `language`,
  `country`, `outlet`.
- `candidates[]` — several anonymized phase-2 outputs (label A, B, …), each with
  `preliminary_divergences` and `coverage_gaps`.

For each candidate, judge its output ONLY against `article_analyses` /
`article_metadata`. Score every candidate on the same scale; do not rank them
against each other and do not guess which model produced which.

## Scoring (each 1–5, where 5 is best)

- `grounding` — are the divergences and gaps supported by what the analyses
  actually say? A candidate loses grounding for every claim the analyses do not
  substantiate. This is the most important axis.
- `specificity` — does each divergence name the specific language groups /
  regional clusters and the substantive difference (not "articles differ in
  emphasis"), and does each gap name a specific missing region / stakeholder /
  dimension?
- `cross_group_validity` — are the divergences genuine ACROSS-group patterns
  (language groups or regional clusters), not differences between two articles
  in the same group?
- `gap_quality` — are the coverage gaps real absences that matter for this
  topic, grounded in what the corpus does and does not contain?
- `overall` — holistic usefulness of this output to an editor.

## Fabrication charges (the load-bearing judgment)

List, in `fabricated_divergences`, every divergence whose claimed cross-group
CONTRADICTION the analyses do NOT support — a group is said to frame or cover
something in a way the analyses do not show, or a named group / outlet / actor
is not actually in the corpus. For each charge give:
- `quote` — the exact divergence sentence, verbatim.
- `why_unsupported` — cite what the analyses do (or do not) say that makes the
  claimed contrast unsupported.

Only charge a divergence you are confident is unsupported. A merely thin or
loosely worded divergence that the analyses still bear out is NOT a fabrication —
reflect that in the `grounding` score instead. Coverage gaps are not fabrication
charges (score them under `gap_quality`).

# OUTPUT FORMAT

A single JSON object: `{"assessments": [{...} per candidate]}`. Exactly one entry
per candidate label in the input, each with `label`, the five integer scores, and
`fabricated_divergences` (an array, empty when none). Output only the JSON object.
