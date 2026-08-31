# TASK

You receive `article_body`, the full text of a finished article. Read it sentence by sentence and list every passage in the article's own editorial voice that is potentially evaluative, framing, emotionalizing, responsibility-obscuring, or loaded. Cast a wide net: a separate judge evaluates every candidate afterwards, so your job is coverage — when in doubt whether an own-voice passage qualifies, include it. You list candidates only; the judgment, the explanation, and the verdict belong to the judge.

## Whose voice

The article's own editorial voice is your extraction target: its narration, its descriptions, its word choices, its framing — everything the text says as itself. A quoted or attributed statement (direct quotation marks, or indirect speech introduced by "said", "argued", "called it") speaks in the speaker's voice; its words belong to the speaker and stay with the speaker, however loaded they are. What belongs to the article at such a passage is its handling of the speech, and the handling is fully in your target: the verb that introduces the statement ("admitted", "boasted", "claimed" where "said" would report the same act), the characterization the article wraps around the quote, and arrangements in which one side speaks in its own words while the other is paraphrased. Harvest the handling with the same wide net you apply to narration.

## The six patterns

- `evaluative_adjective` — words characterizing severity, importance, or quality in the article's own voice ("devastating", "landmark", "alarming").
- `emotionalizing` — phrasing that evokes an emotional response rather than reporting a fact ("heartbreaking scenes", "a community in shock").
- `passive_obscuring` — passive constructions that hide a known active agent ("mistakes were made", "the fees were raised").
- `loaded_term` — words carrying implicit judgment about a subject ("regime" for a government, "admitted" for "stated").
- `hedging` — vague qualification without a named source ("some say", "it is believed", "reportedly").
- `intensifier` — amplifiers without informational backing ("extremely", "vastly", "overwhelmingly").

# OUTPUT FORMAT

A single JSON object. Example, for an article containing the passage *"The council's decision dealt a devastating blow to neighborhood bakeries. The mayor admitted the new fees 'will keep our streets clean and our budget honest', while bakers were left to absorb the cost."*:

{"candidates": [{"excerpt": "a devastating blow", "issue_hint": "evaluative_adjective"}, {"excerpt": "admitted", "issue_hint": "loaded_term"}, {"excerpt": "were left to absorb the cost", "issue_hint": "emotionalizing"}]}

The mayor's quoted words stay with the mayor; the article's contribution at that sentence — the verb "admitted", which frames a confident statement as a concession — is the candidate.

Field notes:

- `excerpt` — an exact substring of `article_body`, copied character for character: same spelling, same capitalization, same punctuation. In the example above, the excerpt "a devastating blow" is copied directly out of the sentence — not reworded to "devastating blow to bakeries", not normalized. An excerpt that cannot be found by string lookup in `article_body` is discarded.
- `issue_hint` — exactly one of the six pattern names above; your best guess.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Every `excerpt` is a verbatim substring of `article_body` — copy the characters, never paraphrase, never adjust quotes or punctuation.
2. Extract from the article's own voice. At quoted or attributed speech, the candidate material is the article's handling — the attribution verb, the framing around the quote, the arrangement — never the speech itself, however loaded.
3. Prefer the shortest span that carries the pattern: a phrase, not a full sentence or paragraph.
4. When in doubt whether an own-voice passage qualifies, include it — the judge filters.
5. List up to roughly 25 candidates; when an article offers more, keep the 25 most clearly loaded ones. An empty list is valid for a clean article.
