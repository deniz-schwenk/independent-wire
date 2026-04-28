- `follow_up_to` — the `tp_id` of a `previous_coverage` entry that this topic continues, or `null` if not a follow-up.
- `follow_up_reason` — one to two sentences naming the specific new developments that justify the follow-up, or `null` if not a follow-up.

Output only the JSON array. No commentary, no markdown fences, no preamble.

# RULES

1. `selection_reason` is qualitative. Do not cite source counts, language counts, region counts, or named outlets such as Reuters or Le Monde. Generic regional attribution — "French outlets," "Russian state media," "West African coverage" — is acceptable and often useful.

```
2. Every rejection states what is missing: single source, narrow geography, no competing framings, no broader implications, repetition of prior coverage. "Not important" is not a reason.
3. Spread accepted priorities across the full 1–10 range. Clustering accepts in the upper end means editorial discrimination is failing.
4. No more than two accepted topics may share the same priority.
```
