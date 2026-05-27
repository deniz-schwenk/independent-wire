# TASK

You receive two arrays describing what is missing from a multi-perspective news dossier. `perspective_missing_positions[]` carries structured entries, each with a `type` (one of `government`, `legislature`, `judiciary`, `military`, `industry`, `civil_society`, `academia`, `media`, `international_org`, `affected_community`) and a `description` — one English sentence naming the missing voice. `merged_coverage_gaps[]` carries free-text English strings, each describing one thing the dossier lacks — sometimes a missing voice, sometimes a missing topic, sometimes both.

For each entry across both inputs, decide whether it primarily describes a missing voice or a missing topic. Deduplicate semantic overlaps across the two inputs. Produce two lists of compact English strings: `voices_missing[]` and `topics_missing[]`.

## Voice or topic

A **missing voice** is a person, institution, stakeholder type, region, language, or media sphere whose perspective is absent from the dossier. The lack is *who or where the dossier doesn't reach*.

A **missing topic** is an aspect, dimension, angle, or theme that no source in the dossier addresses. The lack is *what content the dossier doesn't cover*.

When an entry covers both — it names a missing perspective and a missing topic dimension — classify it as voice. Reserve topic for entries with no obvious stakeholder, region, language, or media-sphere component, entries that are genuinely about a missing thematic angle.

## Deduplication

Two entries from different inputs may name the same gap in different wording — for example, a structured entry on missing international organizations and a free-text entry naming specific humanitarian groups. When their substance overlaps, merge them into a single line. When each entry carries unique substance, write one consolidated line that captures both. The output should not contain two entries describing essentially the same thing.

## Writing the entries

Each entry is a compact English string — one sentence or a comma-fragment phrase, not a paragraph. The line stands on its own. Where relevant context appears in the source — a number, a region, a specific event — preserve it briefly.

Do not start entries with "No", "Missing", or "Lack of". The list itself is the what-is-missing list; the descriptive phrasing carries the meaning. Write *"Iraqi government and media voices, despite Iraq being identified as the origin of the drone attacks"*, not *"No Iraqi government and media voices are present in the dossier"*.

# OUTPUT FORMAT

A single JSON object with exactly two top-level fields. Either list may be empty. Example:

```json
{
  "voices_missing": [
    "Iraqi government and media voices, despite Iraq being identified as the origin of the drone attacks",
    "International humanitarian organizations (ICRC, MSF, UNHCR, WHO)",
    "Cuban dissident and independent media operating inside Cuba"
  ],
  "topics_missing": [
    "Humanitarian dimension of the ongoing US oil blockade — food security, medical supply shortages, energy crises",
    "Legal viability and historical precedent of indicting a former foreign head of state"
  ]
}
```

Field notes:

- `voices_missing[]` — compact English strings, each naming a missing voice (person, institution, stakeholder type, region, language, or media sphere). Empty array when no input maps to this bucket.
- `topics_missing[]` — compact English strings, each naming a missing topic (aspect, dimension, angle, or theme). Empty array when no input maps to this bucket.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Every output entry derives from at least one input entry. Do not invent gaps the inputs do not describe.
2. Entries that name both a missing voice and a missing topic dimension are classified as voice. Topic is reserved for entries with no stakeholder, region, language, or media-sphere component.
3. Entries do not begin with "No", "Missing", or "Lack of". Write the missing thing directly, with brief context preserved from the source where relevant.
4. Overlapping entries across the two inputs are merged. The output does not contain two entries describing essentially the same gap.
