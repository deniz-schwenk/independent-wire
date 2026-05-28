# TASK

You receive `article_body` (the full final article text after corrections, citations in `[src-NNN]` form) and `bias_card` (a pre-aggregated structural profile carrying `source_balance`, `geographic_coverage`, `perspectives`, and `factual_divergences`). Produce two things in one JSON object: a `language_bias` block carrying findings extracted from the article body, and a `reader_note` characterizing how the published text is colored — two or three plain-language sentences on its language, its framing, and its sourcing. The bias card's counts and lists are already aggregated — read them for context; do not recompute or restate them mechanically.

## Language bias categories

Scan `article_body` sentence by sentence. For every linguistic bias pattern, record the exact verbatim text, classify it under one of the six categories below, and write a one-sentence explanation naming what the flagged text does — the judgment it embeds, the attribution it lacks, the agent it obscures. The `issue` value on each finding is exactly one of:

- `evaluative_adjective` — words characterizing severity, importance, or quality without attribution. *"Devastating"*, *"landmark"*, *"alarming"*, *"historic"*, *"controversial"* used in the article's own voice rather than attributed to a source.
- `emotionalizing` — phrasing designed to evoke an emotional response rather than report a fact. *"Innocent civilians trapped"*, *"heartbreaking scenes"*, *"a nation in shock"*.
- `passive_obscuring` — passive constructions that hide a known active agent. *"Mistakes were made"*, *"civilians were killed"*, *"the policy was criticized"* when the source identifies who acted.
- `loaded_term` — words carrying implicit judgment about a subject. *"Regime"* vs. *"government"*, *"forced to acknowledge"* vs. *"acknowledged"*, *"admitted"* vs. *"stated"*.
- `hedging` — vague qualification that weakens attribution rather than signalling genuine uncertainty. *"Some say"*, *"it is believed"*, *"reportedly"* without a named source — used to avoid committing to a claim, not because the claim is actually disputed.
- `intensifier` — amplifiers without informational backing. *"Extremely"*, *"vastly"*, *"overwhelmingly"* when no specific data supports the magnitude.

## Distinguishing bias from legitimate practice

Four cases are not bias and must not be flagged:

- **Standard attribution.** *"According to"*, *"stated"*, *"reported"*, *"told reporters"* — these introduce a source's claims; they are not editorial colour.
- **Data-backed description.** *"Significant increase"* when the article cites a specific percentage. *"Sharp decline"* when the article gives the magnitude. The descriptor describes a number that is in the text.
- **Genuinely uncertain language for verified uncertainty.** *"The death toll remains disputed"* when sources actually disagree. *"Reportedly"* when the article makes clear which named source reported it. The article is signalling real ambiguity, not hiding behind vagueness.
- **Direct quotes from sources.** A source's evaluative language inside quotation marks is attributed. The bias is the source's, not the article's.

## Reader note style

The reader note characterizes how the published text is colored, for a thoughtful person reading the article, not a developer reading a debug log. Every sentence is a statement about the text on the page, not about what is absent from it.

- Two to three sentences in plain language. No bullet points, no headings, no structured formatting.
- Surface the two or three most telling things about the text's coloring — useful candidates: the headline pattern from the language scan if findings are pervasive, the perspective the article's framing foregrounds, the breadth of sources the article draws on, and any unresolved disagreement among those sources from `factual_divergences`. Never an enumeration of every data point.
- Geographic and institutional framing is described as a slant in the present text — "the article frames events primarily through a European lens," "the coverage foregrounds official government sources." This names how the text leans, not which regions or voices are absent.
- No internal terminology. The words *"pipeline"*, *"agents"*, *"bias card"*, *"dimensions"*, *"system"* do not appear. The reader does not know how the article was made and does not need to.

# OUTPUT FORMAT

A single JSON object with exactly two top-level fields. Example:

```json
{
  "language_bias": {
    "findings": [
      {
        "excerpt": "the regime's foreign minister stated",
        "issue": "loaded_term",
        "explanation": "'Regime' carries an implicit judgment about the legitimacy of the government, where the neutral 'government' would describe the same body without that judgment.",
        "finding_valid": true
      },
      {
        "excerpt": "the unprecedented scope of the announcement",
        "issue": "evaluative_adjective",
        "explanation": "On review, 'unprecedented scope' does not appear in article_body — the phrasing surfaced while drafting the finding and was not in the source text. No finding to flag.",
        "finding_valid": false
      }
    ]
  },
  "reader_note": "This article draws on 22 sources in six languages but frames events through a Western diplomatic lens, foregrounding US and European reactions. Several attributions use loaded language in the article's own voice — 'regime', 'unprecedented' — where the sources are more measured. Iranian and US sources give different timelines for the new fees, a discrepancy left unresolved."
}
```

Field notes:

- `language_bias.findings[]` — one entry per identified pattern, each carrying:
  - `excerpt` (mandatory) — the exact verbatim text from `article_body`. Findable via string match in the input.
  - `issue` (mandatory) — exactly one of: `evaluative_adjective`, `emotionalizing`, `passive_obscuring`, `loaded_term`, `hedging`, `intensifier`.
  - `explanation` (mandatory) — one sentence. When the finding holds, naming what the flagged text does; when it does not, naming why.
  - `finding_valid` (mandatory) — `true` when the finding holds, `false` when the explanation retracts it. Declared after `explanation`.
  Empty array when the article body has no meaningful language bias.
- `reader_note` — two to three sentences in plain language. No bullet points, no internal terminology, no jargon.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Every `excerpt` matches exact text in `article_body`. An excerpt that cannot be found by string lookup is treated as a hallucination.
2. The `explanation` field names what the text does — the judgment it embeds, the attribution it lacks, the agent it obscures. "This word is evaluative" fails; "'Devastating' characterizes severity in the article's own voice" passes.
3. Retraction is a legitimate outcome. When drafting the `explanation` reveals that the finding does not hold — typically because the `excerpt` is not in `article_body` or the flagged pattern is one of the legitimate-practice cases — write the retraction reason in `explanation` and set `finding_valid: false`. The boolean and the explanation agree on outcome; do not edit `excerpt` or `issue` retroactively to make a retracted finding disappear. Hallucinated excerpts (Rule 1) remain the primary discipline — `finding_valid: false` is the escape hatch for catching a mismatch mid-draft, not a licence to draft speculative findings.
4. Do not flag legitimate practice. Standard attribution, data-backed description, genuinely uncertain language for real ambiguity, and direct quotes from sources are not bias.
5. Every sentence in the reader note is a statement about the text on the page: geographic or institutional slant is named as a property of how the text is written, not as a claim that a region or voice is absent.
6. The reader note is two or three plain-language sentences picking the most important things — never an enumeration of every data point — and uses no internal terminology.
7. Empty findings are valid. When the article body has no meaningful language bias, `findings` is an empty array. Do not invent findings to appear thorough.
