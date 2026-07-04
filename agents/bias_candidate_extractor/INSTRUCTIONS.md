# TASK

You receive `article_body`, the full text of a finished article. Read it sentence by sentence and list every passage that is potentially evaluative, framing, emotionalizing, responsibility-obscuring, or loaded. Cast a wide net: a separate judge evaluates every candidate afterwards, so your job is coverage — when in doubt whether a passage qualifies, include it. You list candidates only; the judgment, the explanation, and the verdict belong to the judge.

For each candidate, give your best guess which of the six patterns it matches:

- `evaluative_adjective` — words characterizing severity, importance, or quality in the article's own voice ("devastating", "landmark", "alarming").
- `emotionalizing` — phrasing that evokes an emotional response rather than reporting a fact ("heartbreaking scenes", "a community in shock").
- `passive_obscuring` — passive constructions that hide a known active agent ("mistakes were made", "the fees were raised").
- `loaded_term` — words carrying implicit judgment about a subject ("regime" for a government, "admitted" for "stated").
- `hedging` — vague qualification without a named source ("some say", "it is believed", "reportedly").
- `intensifier` — amplifiers without informational backing ("extremely", "vastly", "overwhelmingly").

# OUTPUT FORMAT

A single JSON object. Example, for an article containing the sentence *"The council's decision dealt a devastating blow to neighborhood bakeries, and inspection fees were quietly doubled."*:

{"candidates": [{"excerpt": "a devastating blow", "issue_hint": "evaluative_adjective"}, {"excerpt": "were quietly doubled", "issue_hint": "passive_obscuring"}]}

Field notes:

- `excerpt` — an exact substring of `article_body`, copied character for character: same spelling, same capitalization, same punctuation. In the example above, the excerpt "a devastating blow" is copied directly out of the sentence — not reworded to "devastating blow to bakeries", not normalized. An excerpt that cannot be found by string lookup in `article_body` is discarded.
- `issue_hint` — exactly one of the six pattern names above; your best guess.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Every `excerpt` is a verbatim substring of `article_body` — copy the characters, never paraphrase, never adjust quotes or punctuation.
2. Prefer the shortest span that carries the pattern: a phrase, not a full sentence or paragraph.
3. When in doubt, include the passage — the judge filters.
4. List up to roughly 25 candidates; when an article offers more, keep the 25 most clearly loaded ones. An empty list is valid for a clean article.
