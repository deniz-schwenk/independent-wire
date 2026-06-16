# TASK

You receive `glossary[]` (entity terms paired as `{en, de}`, with `de` the authoritative German base form for that entity), `prior_translations[]` (the finalized German of blocks completed earlier in this document, in order — may be empty for the first block), and `items[]` (the English prose pieces of this block, each `{key, text}`). Produce a German translation of every item's `text` in a flat, source-based register — clear, plain prose, no stylistic heightening.

Translate the items as a set: a recurring entity, term, or phrasing reads the same way in every item where it occurs and matches the German already established in `prior_translations`. This cross-item consistency is the point of translating items as a block.

## Entity handling

Each glossary entry is the authoritative German rendering for that entity — use it, inflecting freely for German grammar (case, article, compound). Do not substitute a different German term for the same entity. Person names stay in their original form, untranslated. Any other entity not in the glossary is translated as best fits the context.

## Citation tokens and verbatim quotes

- Inline citation tokens like `[src-001]` are opaque sentinels: copy them through unchanged, in their original positions relative to the surrounding text. Every `[src-NNN]` in an item's `text` appears in that item's `final`.
- A direct verbatim quote in a language other than German — including English — stays in its original language, immediately followed by a German gloss in square brackets. Example: `the DOJ was attempting to "manufacture" a crime` → `… versuchte, ein Verbrechen zu "manufacture" [zu konstruieren] …`.
- An item whose `key` ends in `.title` is an original-language source headline: keep the original verbatim and append a bracketed German gloss — `<original> [<gloss>]`.

# OUTPUT FORMAT

A single JSON object `{"items": [ ... ]}`, one object per input item, in the same order and with the same keys. Each item carries the six-field self-revision in this declaration order — the order is load-bearing, each field a step in the revision. Example:

```json
{
  "items": [
    {
      "key": "headline.title",
      "analyse": "Original-language source headline; .title key triggers verbatim-plus-gloss handling. No glossary entities, no citations, no embedded quotes.",
      "translation": "«Aviso de tormenta» [Sturmwarnung]",
      "verify": "Original Spanish kept verbatim, German gloss appended in brackets per the .title rule.",
      "pass": true,
      "correction": "«Aviso de tormenta» [Sturmwarnung]",
      "final": "«Aviso de tormenta» [Sturmwarnung]"
    },
    {
      "key": "body.paragraph_1",
      "analyse": "Glossary entity 'National Weather Service' present, German base form 'Wetterdienst'. Two citation tokens [src-001] and [src-002] to preserve in position. No verbatim quotes.",
      "translation": "Der Wetterdienst gab am Dienstag eine Sturmwarnung für die Küstenregionen aus [src-001] und forderte kleine Betriebe auf, Außenanlagen zu sichern [src-002].",
      "verify": "Entity rendered in given German form, inflected with article and case. Both citation tokens preserved in their original positions. Register flat, meaning faithful.",
      "pass": true,
      "correction": "Der Wetterdienst gab am Dienstag eine Sturmwarnung für die Küstenregionen aus [src-001] und forderte kleine Betriebe auf, Außenanlagen zu sichern [src-002].",
      "final": "Der Wetterdienst gab am Dienstag eine Sturmwarnung für die Küstenregionen aus [src-001] und forderte kleine Betriebe auf, Außenanlagen zu sichern [src-002]."
    },
    {
      "key": "body.paragraph_2",
      "analyse": "Embedded Spanish verbatim quote — Policy A applies: original preserved, German gloss in brackets immediately after. One citation token [src-003].",
      "translation": "Ein Sprecher der Handelskammer beschrieb die Reaktion der Geschäfte als «rápida y coordinada» [schnell und koordiniert] [src-003].",
      "verify": "Quote left in Spanish with bracketed gloss, not retranslated into running German. Citation token preserved.",
      "pass": true,
      "correction": "Ein Sprecher der Handelskammer beschrieb die Reaktion der Geschäfte als «rápida y coordinada» [schnell und koordiniert] [src-003].",
      "final": "Ein Sprecher der Handelskammer beschrieb die Reaktion der Geschäfte als «rápida y coordinada» [schnell und koordiniert] [src-003]."
    }
  ]
}
```

Field notes:

- `key` — copied verbatim from the input item's `key`. Same string, same position in the output array as in `items[]`.
- `analyse` — a brief reasoning trace per item: which glossary entities appear, any verbatim quotes, any `[src-NNN]` tokens, any tricky construction.
- `translation` — the first German rendering of the item's `text`.
- `verify` — your own check of `translation` against the source, the glossary, and `prior_translations`: glossary entities in German form, verbatim quotes preserved with gloss, every citation token present, meaning faithful, register flat, and grammatical agreement correct — in particular, collective and mass nouns take the number and verb form German grammar requires (e.g. "das Gesundheitspersonal wurde", "mehrere Mitarbeiter des Gesundheitspersonals wurden").
- `pass` — `true` when `verify` finds no issues; `false` when it finds something to correct.
- `correction` — when `pass` is `false`, the revised German that addresses what `verify` flagged; when `pass` is `true`, repeats the `translation` value.
- `final` — the German translation to use, always equal to `correction`, and always a complete faithful German translation of the item's `text` — never a placeholder, meta-comment, empty string, or English passthrough of running prose.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Translate every item; return items in the same order with the same keys.
2. Use each glossary entity's German form, inflected for grammar but never substituted; render it identically across items and consistently with `prior_translations`.
3. Person names stay original, untranslated. Any other entity not in the glossary is translated as best fits the context.
4. Three constructs are preserved verbatim from the source: citation tokens `[src-NNN]` stay in place with every one present in `final`; verbatim non-German quotes (including English) stay in their original language with a bracketed German gloss appended; an item whose `key` ends in `.title` keeps its original-language headline with a bracketed German gloss appended.
5. Hold a flat, source-based register: clear, plain prose, no stylistic heightening or editorial colour.
