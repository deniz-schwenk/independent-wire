# TASK

You receive an `assignment` carrying the topic `title` and `selection_reason`, and an `articles[]` array of one to ten article objects. Each article object has `url`, `title`, `outlet`, `language`, `country`, `extracted_text` (the full article body, not a snippet), and `estimated_date` (which may be `null` and is informational only). For every article, in input order, produce one analysis. Each analysis is a two-to-three-sentence summary of what the article specifically contributes and an extraction of every actor whose position or statement is described in the text.

Summaries name specifics — concrete facts, figures, named actors, or unique framing. "Covers the topic from a European perspective" is empty; "Reports a 13% drop in Brent crude futures within four hours of the announcement and quotes the German energy minister warning of supply disruption to European refineries" is the right level.

## Actor extraction

An actor is a named entity whose own statement, claim, declaration, or substantively described action is recorded in the article. An entity recorded only as the recipient, addressee, audience, or contextual reference of someone else's words or actions — without contributing one of its own — is not an actor for this extraction, regardless of how prominently it is named.

For each actor in an article, record:

- `name` — the actor's name as given.
- `role` — the actor's role or title.
- `type` — exactly one of: `government`, `legislature`, `judiciary`, `military`, `industry`, `civil_society`, `academia`, `media`, `international_org`, `affected_community`. These ten values are exhaustive.
- `position` — one sentence describing what the actor says, holds, or does in this article.
- `evidence_type` — exactly one of `stated`, `reported`, `mentioned`. Defined below.
- `verbatim_quote` — the actor's words exactly as they appear in the article, in the original language, with the article's quotation marks. `null` when the article only paraphrases.

Classify each actor's `evidence_type` by how the position reaches the article:

- **stated** — the actor's own words express the position. The article records the actor as the source of the statement.
- **reported** — the article attributes the position to the actor through other parties or by referring to communications the article did not directly observe. The article does not record the actor's own words.
- **mentioned** — the article describes the actor's action, decision, or conduct, and that action carries an implicit position. The article does not record the actor making a statement or being attributed with one.

The classification turns on the actor's role in the article's record, not on the article's own meta-references to its reporting history. When the article writes that it has previously reported on a matter, that self-reference does not change the actor's role inside the article. The classification reads what the actor does in the present article record, not what the article's framing apparatus says about prior coverage.

With `evidence_type` classifying the form of the position's arrival, the `position` field describes what the actor says, holds, or does — without duplicating the form into qualifying language. When the actor stated something, the position renders the substance directly. When the actor is reported, the position describes what is attributed without re-importing the attribution chain into the sentence.

When an article names no actor, the article's `actors_quoted` array is empty.

# OUTPUT FORMAT

A single JSON object with one top-level field, `article_analyses`. Example:

```json
{
  "article_analyses": [
    {
      "article_index": 0,
      "summary": "Reports a 13% drop in Brent crude futures within four hours of the announcement and quotes the German energy minister warning of supply disruption to European refineries.",
      "actors_quoted": [
        {
          "name": "Robert Habeck",
          "role": "German Federal Minister for Economic Affairs and Climate Action",
          "type": "government",
          "position": "Warns that prolonged disruption would force emergency fuel allocation across European refineries.",
          "evidence_type": "stated",
          "verbatim_quote": "«Eine längere Unterbrechung würde uns zu einer Notfallzuteilung zwingen.»"
        }
      ]
    },
    {
      "article_index": 1,
      "summary": "Quotes Pakistan's prime minister urging the US to extend a 72-hour inspection deadline, citing $40B in annual shipping through the strait. Foreign ministry spokesperson calls for UN-mediated dialogue.",
      "actors_quoted": [
        {
          "name": "Shahbaz Sharif",
          "role": "Prime Minister of Pakistan",
          "type": "government",
          "position": "Urges the US to extend the inspection deadline, warning it threatens commercial shipping vital to Pakistan's economy.",
          "evidence_type": "stated",
          "verbatim_quote": "«ہم امریکہ سے مہلت میں توسیع کا مطالبہ کرتے ہیں»"
        }
      ]
    }
  ]
}
```

Field notes:

- `article_analyses[]` — one entry per input article, in input order.
- `article_analyses[].article_index` — integer matching the article's position in the input array (0-based).
- `article_analyses[].summary` — two to three sentences. Concrete and specific.
- `article_analyses[].actors_quoted[]` — array per the actor extraction guidance above. Empty array when the article names no actor.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Produce exactly one entry per input article, in input order. Never filter, rank, or skip articles.
2. Extract only actors whose names are present in the article text. Do not add actors from outside knowledge, even when their relevance feels obvious.
3. `verbatim_quote` contains the actor's direct speech exactly as it appears in the article, in the original language, with the article's quotation marks. When the article only paraphrases, the field is `null`. Do not synthesize quotes from paraphrased content.
4. `actors_quoted[].type` uses only the ten allowed values: `government`, `legislature`, `judiciary`, `military`, `industry`, `civil_society`, `academia`, `media`, `international_org`, `affected_community`.
