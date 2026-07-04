# TASK

You receive `article_body` (the full text of a finished article) and `candidates` (a numbered list of passages from that article, each with a `candidate_id`, a verbatim `excerpt`, and an `issue_hint`). Your job is judging the given passages, nothing else: for each candidate, read the excerpt in its surrounding article context and reach one of three verdicts — `confirmed`, `borderline`, or `cleared`. Close with a short reader note summarizing what you confirmed.

The article prose you are judging is deliberately restrained by design. Expect most candidates to be defensible word choices. A wrong confirmation damages the publication's credibility more than a missed one — confirm a finding only when the pattern clearly holds in context.

## The six patterns

- `evaluative_adjective` — words characterizing severity, importance, or quality in the article's own voice, unattributed ("devastating", "landmark", "alarming").
- `emotionalizing` — phrasing that evokes an emotional response rather than reporting a fact ("heartbreaking scenes", "a community in shock").
- `passive_obscuring` — passive constructions that hide an agent the article's sources identify ("mistakes were made" when the source names who made them).
- `loaded_term` — words carrying implicit judgment about a subject ("regime" for a government, "admitted" for "stated").
- `hedging` — vague qualification used to avoid committing to a claim ("some say", "it is believed" without a named source).
- `intensifier` — amplifiers without informational backing ("extremely", "vastly" when no data supports the magnitude).

## The three verdicts

- `confirmed` — the pattern clearly holds in context: the article speaks in its own voice, no attribution, no figure, no quote covers the phrasing.
- `borderline` — a genuinely defensible reading exists on both sides: the same passage can honestly be read as the article's own judgment and as covered by its context. Reserve this verdict for cases where the own-voice question is honestly contestable — a passage that merely required a moment's thought before clearing is `cleared`, not `borderline`.
- `cleared` — context shows legitimate practice (see below), or the word choice is simply defensible.

## What clears a candidate

A candidate is `cleared` when context shows legitimate practice: the phrase sits inside a direct quote or is attributed to a named source (the language is the source's, not the article's); a descriptor is backed by a specific figure in the text ("sharp decline" next to the percentage that makes it sharp); uncertain language marks genuinely disputed facts the article documents as disputed; or the word choice is simply defensible.

# OUTPUT FORMAT

A single JSON object. The `explanation` comes before the verdict fields — write the reasoning first; the verdict states what the reasoning established. Example, judging three candidates from an article about a municipal fee change:

{"judgments": [{"candidate_id": 1, "explanation": "The article says in its own voice that the decision 'dealt a devastating blow' to bakeries; no source is quoted using this characterization and no figure in the text establishes the severity. The judgment is the article's own.", "issue": "evaluative_adjective", "verdict": "confirmed"}, {"candidate_id": 2, "explanation": "'A sharp decline' directly precedes the figure — applications fell 40 percent in one quarter — so the descriptor summarizes a number the text provides rather than asserting an unsupported judgment.", "issue": null, "verdict": "cleared"}, {"candidate_id": 3, "explanation": "'Quietly doubled' rests on a documented fact — the article notes the fee change appeared in the register without an announcement — so 'quietly' can be read as compressed factual description. It can equally be read as an insinuation of concealment the sources do not make. Both readings are defensible; neither confirming nor clearing would be honest.", "issue": "loaded_term", "verdict": "borderline"}], "reader_note": "The article characterizes the fee decision's impact in its own voice — 'devastating' — where its quoted sources are more measured. Its factual descriptions are otherwise backed by the figures it cites."}

Field notes:

- `judgments[]` — exactly one entry per candidate in the input list, each carrying:
  - `candidate_id` — the id from the input list. Only ids from the list appear; the list is the complete scope of your judgment.
  - `explanation` — one or two sentences of reasoning from the article context, written before the verdict. For a `borderline` verdict, the reasoning names both defensible readings.
  - `issue` — the pattern name for `confirmed` and `borderline` verdicts; `null` for `cleared`.
  - `verdict` — exactly one of `confirmed`, `borderline`, `cleared`.
- `reader_note` — two or three plain-language sentences characterizing the confirmed findings for a reader of the article; an empty string when nothing is confirmed. No internal terminology — the reader does not know how the article was made.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Judge every candidate in the input list exactly once, referenced by its `candidate_id` — no additions, no omissions.
2. Write the `explanation` first and derive the verdict from it: reasoning that establishes legitimate practice yields `cleared`; reasoning that establishes the article's own unsupported voice yields `confirmed`; reasoning that honestly sustains both readings yields `borderline`.
3. Confirm a finding only when the article speaks in its own voice — attributed claims, quoted sources, and descriptors backed by figures in the text are legitimate practice.
4. `borderline` is reserved for genuinely contestable calls, not for hesitation: a defensible word choice is `cleared`, and the restrained house prose makes false confirmations costlier than misses.
5. The reader note describes confirmed findings only, in plain language, and stays empty when there are none.
