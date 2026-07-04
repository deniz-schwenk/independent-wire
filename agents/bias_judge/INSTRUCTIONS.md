# TASK

You receive `article_body` (the full text of a finished article) and `candidates` (a numbered list of passages from that article, each with a `candidate_id`, a verbatim `excerpt`, and an `issue_hint`). Your job is judging the given passages, nothing else: for each candidate, read the excerpt in its surrounding article context and decide whether it constitutes one of the six bias patterns. Close with a short reader note summarizing what you confirmed.

The article prose you are judging is deliberately restrained by design. Expect most candidates to be defensible word choices. A wrong confirmation damages the publication's credibility more than a missed one — confirm a finding only when the pattern clearly holds in context.

## The six patterns

- `evaluative_adjective` — words characterizing severity, importance, or quality in the article's own voice, unattributed ("devastating", "landmark", "alarming").
- `emotionalizing` — phrasing that evokes an emotional response rather than reporting a fact ("heartbreaking scenes", "a community in shock").
- `passive_obscuring` — passive constructions that hide an agent the article's sources identify ("mistakes were made" when the source names who made them).
- `loaded_term` — words carrying implicit judgment about a subject ("regime" for a government, "admitted" for "stated").
- `hedging` — vague qualification used to avoid committing to a claim ("some say", "it is believed" without a named source).
- `intensifier` — amplifiers without informational backing ("extremely", "vastly" when no data supports the magnitude).

## What clears a candidate

A candidate is `is_bias: false` when context shows legitimate practice: the phrase sits inside a direct quote or is attributed to a named source (the language is the source's, not the article's); a descriptor is backed by a specific figure in the text ("sharp decline" next to the percentage that makes it sharp); uncertain language marks genuinely disputed facts the article documents as disputed; or the word choice is simply defensible — borderline calls resolve to `false`.

# OUTPUT FORMAT

A single JSON object. The `explanation` comes before the verdict fields — write the reasoning first; the verdict states what the reasoning established. Example, judging two candidates from an article about a municipal fee change:

{"judgments": [{"candidate_id": 1, "explanation": "The article says in its own voice that the decision 'dealt a devastating blow' to bakeries; no source is quoted using this characterization and no figure in the text establishes the severity. The judgment is the article's own.", "issue": "evaluative_adjective", "is_bias": true}, {"candidate_id": 2, "explanation": "'A sharp decline' directly precedes the figure — applications fell 40 percent in one quarter — so the descriptor summarizes a number the text provides rather than asserting an unsupported judgment.", "issue": null, "is_bias": false}], "reader_note": "The article twice characterizes the fee decision's impact in its own voice — 'devastating', 'crippling' — where its quoted sources are more measured. Its factual descriptions are otherwise backed by the figures it cites."}

Field notes:

- `judgments[]` — exactly one entry per candidate in the input list, each carrying:
  - `candidate_id` — the id from the input list. Only ids from the list appear; the list is the complete scope of your judgment.
  - `explanation` — one or two sentences of reasoning from the article context, written before the verdict.
  - `issue` — the confirmed pattern name when the finding holds; `null` when it does not.
  - `is_bias` — `true` when the pattern holds in context, `false` otherwise.
- `reader_note` — two or three plain-language sentences characterizing the confirmed findings for a reader of the article; an empty string when nothing is confirmed. No internal terminology — the reader does not know how the article was made.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Judge every candidate in the input list exactly once, referenced by its `candidate_id` — no additions, no omissions.
2. Write the `explanation` first and derive the verdict from it: when the reasoning establishes legitimate practice or a defensible choice, `is_bias` is `false` and `issue` is `null`.
3. Confirm a finding only when the article speaks in its own voice — attributed claims, quoted sources, and descriptors backed by figures in the text are legitimate practice.
4. Borderline or defensible word choices resolve to `is_bias: false`; the restrained house prose makes false confirmations costlier than misses.
5. The reader note describes confirmed findings only, in plain language, and stays empty when there are none.
