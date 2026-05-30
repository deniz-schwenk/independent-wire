# TASK

You receive a JSON object with two fields: `topics` — an array of topic candidates, each carrying a `title`, a `summary`, `geographic_coverage`, `languages` present in coverage, lists of `missing_regions` and `missing_languages`, and a `missing_perspectives` description — and `previous_coverage`, a possibly-empty array of Topic Packages published in the last seven days, each with a `tp_id`, date, headline, slug, and summary. Read every topic and decide which qualify for today's multi-perspective production. Write a substantive `selection_reason` for every decision, accepts and rejects alike, then assign each topic a priority — 1 to 10 for accepts (ordered by editorial urgency), 0 for rejects. Mark a topic as a follow-up to a prior package only when there are material new developments — a new military action, a policy reversal, verified casualty figures that differ from prior reporting, a ceasefire announcement, an official response that did not previously exist. Additional outlets covering the same facts, longer pieces, or minor editorial variation do not count; same story without new substance is a reject or deprioritize.

# STEPS

1. For each topic, scan `previous_coverage` for the same story. If a match exists, judge whether material new developments have occurred since that prior package; if not, the topic is a reject or low-priority unless other factors clearly elevate it.
2. For each topic, evaluate multi-perspective viability — whether it has the regional, linguistic, and stakeholder breadth to support a dossier built around competing framings. Weigh viability on the qualitative breadth signals: the spread of `geographic_coverage` and `languages`, and what `missing_perspectives`, `missing_regions`, and `missing_languages` flag as absent. A topic with narrow coverage but sharp framing divergence between the regions and languages present may still deserve elevation; one with broad coverage but thin substantive divergence and significant missing perspectives may not. A single-source, single-region story almost never qualifies.
3. For each topic in turn, write its `selection_reason` — for accepts and rejects alike — and its `follow_up_reason` where it is a follow-up, then derive its `priority` immediately after: 0 if the reason articulates rejection, an initial 1–10 score for accepts ordered by editorial urgency. The score follows the articulated judgment.
4. Rebalance the accepted set's priorities across the full 1–10 range. The daily run is not dominated by a single domain (politics, economy, tech, conflict, science, society) or a single region, and no more than two accepts share a priority.

# OUTPUT FORMAT

A single JSON array, one entry per input topic. Example:

```json
[
  {
    "title": "ECB holds interest rates steady amid mixed signals",
    "selection_reason": "Exhibits clear transatlantic divergence — European outlets emphasize policy stability while North American coverage focuses on spillover risk. The absence of emerging-market voices creates a useful angle for gap analysis. Qualified for multi-perspective treatment on the strength of competing monetary-policy framings.",
    "follow_up_to": null,
    "follow_up_reason": null,
    "priority": 6
  },
  {
    "title": "Iran claims downing of US drone vessel in the Strait of Hormuz",
    "selection_reason": "Sharp cross-regional divergence between Western and Iranian state-aligned framings, with direct material stakes for Gulf energy trade.",
    "follow_up_to": "tp-2026-04-13-001",
    "follow_up_reason": "Reported destruction of a US unmanned surface vessel — a material military escalation beyond the previous day's blockade announcement.",
    "priority": 9
  },
  {
    "title": "Local transit app launches in Osaka",
    "selection_reason": "No competing framings or cross-regional perspectives available, and no broader implications beyond the local rollout. Inadequate basis for multi-perspective treatment.",
    "follow_up_to": null,
    "follow_up_reason": null,
    "priority": 0
  }
]
```

Field notes:

- `title` — refine the input title where helpful (sharpening or neutralizing). The topic identity must remain the same. This is not a headline.
- `selection_reason` — two to four sentences of qualitative editorial reasoning. Mandatory for every entry, including rejects.
- `follow_up_to` — the `tp_id` of a `previous_coverage` entry that this topic continues, or `null` if not a follow-up.
- `follow_up_reason` — one to two sentences naming the specific new developments that justify the follow-up, or `null` if not a follow-up.
- `priority` — integer 0 to 10. 0 means rejected; 1 to 10 means accepted, ordered by editorial urgency.

Output only the JSON array. No commentary, no markdown fences, no preamble.

# RULES

1. `selection_reason` is qualitative. Do not cite source counts, language counts, region counts, or named outlets such as Reuters or Le Monde. Generic regional attribution — "French outlets," "Russian state media," "West African coverage" — is acceptable and often useful.
2. Every rejection states what is missing: single source, narrow geography, no competing framings, no broader implications, repetition of prior coverage. "Not important" is not a reason.
3. Spread accepted priorities across the full 1–10 range. Clustering accepts in the upper end means editorial discrimination is failing.
4. No more than two accepted topics may share the same priority.
