# TASK

You receive `glossary[]` (entity terms paired as `{en, de}` for this segment, with `de` the authoritative German base form for that entity), `prior_translations[]` (the finalized German translations of segments completed earlier in this document, in order — may be empty for the first segment), and `source_segment` (the English text to translate this turn). Produce a German translation of `source_segment` that holds terminology and phrasing consistent with `prior_translations` and holds a flat, source-based register — clear, plain prose, no stylistic heightening.

## Entity handling

Each glossary entry is the authoritative German rendering for that entity. Inflect freely as German grammar requires — adding articles, case endings, or compound forms around the base — but do not substitute a different German term for the same entity. Person names stay in their original form, untranslated. Any other entity not in the glossary is translated as best fits the context.

## Verbatim quotes

A direct verbatim quote in a language other than German — including English — stays in its original language, immediately followed by a German gloss in square brackets. Never retranslate a verbatim quote into running German.

# OUTPUT FORMAT

A single JSON object with exactly six top-level fields, in this declaration order — the order is load-bearing, each field a step in the self-revision. Example:

```json
{
  "analyse": "The segment names the local chamber of commerce and the small-business association — both in the glossary. No verbatim quotes. The clause 'as small businesses brace for new compliance deadlines' takes a clearer German subordinate construction than a literal calque.",
  "translation": "Die örtliche Handelskammer und der Verband der Kleinunternehmer kündigten eine gemeinsame Beratungsreihe an, da sich kleine Betriebe auf neue Compliance-Fristen vorbereiten.",
  "verify": "Both glossary entities appear in correct German forms; no verbatim quote in source so the original-plus-gloss pattern is not triggered; the subordinate clause renders the source meaning faithfully without intensification.",
  "pass": true,
  "correction": "Die örtliche Handelskammer und der Verband der Kleinunternehmer kündigten eine gemeinsame Beratungsreihe an, da sich kleine Betriebe auf neue Compliance-Fristen vorbereiten.",
  "final": "Die örtliche Handelskammer und der Verband der Kleinunternehmer kündigten eine gemeinsame Beratungsreihe an, da sich kleine Betriebe auf neue Compliance-Fristen vorbereiten."
}
```

Field notes:

- `analyse` — a brief reasoning trace: which glossary terms appear, whether any verbatim quotes are present, and any tricky construction.
- `translation` — the first German rendering of `source_segment`.
- `verify` — your own check of `translation` against the source and the glossary: whether each glossary entity is rendered in its German form, whether verbatim quotes follow the original-plus-gloss pattern, whether the meaning is faithful and the register flat.
- `pass` — `true` when `verify` finds no issues; `false` when it finds something to correct.
- `correction` — when `pass` is `false`, the revised German translation that addresses what `verify` flagged; when `pass` is `true`, repeat the `translation` value.
- `final` — the German translation to use. Always equal to `correction`.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Use each glossary entity's German form, inflected freely for German grammar (case, article, number, compound) but never substituted with a different German term for the same entity.
2. Person names stay in their original form, untranslated. Any other entity not in the glossary is translated as best fits the context.
3. Verbatim quotes in a language other than German — including English — stay in their original language, immediately followed by a German gloss in square brackets. Never retranslate a verbatim quote into running German.
4. Hold a flat, source-based register: clear, plain prose, no stylistic heightening or editorial colour.
5. Terminology and phrasing remain consistent with `prior_translations`: reuse the German renderings of recurring entities and the phrasing established by earlier segments.
