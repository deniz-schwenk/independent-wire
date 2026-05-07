# TASK

You receive `final_actors[]` — every actor quoted across the dossier, each with an `id` (`actor-NNN`), a `name`, a `role`, a `type`, a `source_ids[]` array, and a `quotes[]` array. The list is deduped only on exact name strings, so the same real-world entity can appear under multilingual or paraphrased variants. Identify which entries refer to the same entity. Flag entries whose `name` is a generic source-class label.

## Same entity — merge

Merge entries that refer to the same real-world person, institution, or body, regardless of how the name is rendered:

- **Same person across name variants** — "Donald Trump" / "President Trump" / "Дональд Трамп" refer to one individual.
- **Same institution across translations** — "Russian Defense Ministry" / "Министерство обороны России" / "Russisches Verteidigungsministerium" refer to one body.
- **Same body across phrasings** — "IAEA" / "International Atomic Energy Agency" / "the Agency" (when context unambiguously identifies the IAEA) refer to one organisation.

Match across scripts by translation; use `role` and `type` to disambiguate when names overlap.

## Distinct entities — never merge

- **Different institutions across countries** — even when the names share words or describe similar functions, two institutions in different countries are two entities.
- **Person versus institution** — a person and an institution are distinct entities, regardless of how the person relates to the institution. Whether they head it, lead it, command a unit within it, speak for it, are employed by it, or belong to it, they remain two entities.
- **Different individuals with similar names** — two people are two people, even when their names overlap.
- **Generic versus specific institutions** — a generic descriptor (a category, a field, a domain reference) and a specific named institution are not the same entity, even when used interchangeably in coverage.

When in doubt, do not merge. False positives corrupt the audit trail and cannot be undone by a reader. False negatives produce visible duplication a reader can mentally group. Conservatism is the bias.

## Anonymous source-class labels

Flag the `actor-NNN` ID of any entry whose `name` is a generic source-class label rather than a named individual or specific institution.

Anonymous (flag): "Iranian military-linked sources", "Senior US officials", "Two people familiar with the matter", "Western intelligence sources".

Not anonymous (do not flag): named individuals ("Donald Trump"), specific institutions ("Iranian Revolutionary Guard Corps", "Reuters"), specific firms even when their operators are anonymous in real life ("TankerTrackers.com").


# OUTPUT FORMAT

A single JSON object with two top-level fields. Example:

```json
{
  "aliases": [
    {"alias_id": "actor-014", "canonical_id": "actor-007"},
    {"alias_id": "actor-019", "canonical_id": "actor-007"},
    {"alias_id": "actor-022", "canonical_id": "actor-007"}
  ],
  "anonymous_flags": [
    "actor-031",
    "actor-045"
  ]
}
```

Field notes:

- `aliases[].alias_id` and `aliases[].canonical_id` — both are `actor-NNN` IDs from the input. Either side of the pair works; the pipeline normalises. The pipeline also aggregates merge groups transitively, so a single pair per alias is enough.
- `anonymous_flags[]` — the `actor-NNN` IDs of entries whose `name` is a generic source-class label.
- Both arrays may be empty.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Merge only when you are confident two entries refer to the same real-world entity. When in doubt, leave them separate.
2. Different institutions across countries are never the same entity. A person and an institution are never the same entity. Different individuals are never the same entity.
3. Every `alias_id`, `canonical_id`, and `anonymous_flags[]` entry must reference an `actor-NNN` ID present in `final_actors[]`.
4. Flag only generic source-class labels. Named individuals and specific institutions are never flagged.
5. Each `alias_id` appears at most once in `aliases[]`.
