# TASK

You receive a JSON object with two fields: `topics` — an array of scored topic candidates assembled today, each carrying a title, a relevance score, a short summary, geographic coverage, languages present in coverage, identified missing perspectives, and a source count — and `previous_coverage`, a possibly-empty array of Topic Packages published in the last seven days, each with a `tp_id`, date, headline, slug, and summary. Read every topic and decide which qualify for today's multi-perspective production. Assign a priority from 1 to 10 to accepted topics, ordered by editorial urgency, and priority 0 to rejected topics. Mark a topic as a follow-up to a prior package only when there are material new developments — a new military action, a policy reversal, verified casualty figures that differ from prior reporting, a ceasefire announcement, an official response that did not previously exist. Additional outlets covering the same facts, longer pieces, or minor editorial variation do not count; same story without new substance is a reject or deprioritize. Write a substantive `selection_reason` for every decision, accepts and rejects alike.

# STEPS

1. For each topic, scan `previous_coverage` for the same story. If a match exists, judge whether material new developments have occurred since that prior package; if not, the topic is a reject or low-priority unless other factors clearly elevate it.
2. For each topic, evaluate multi-perspective viability — whether it has the regional, linguistic, and stakeholder breadth to support a dossier built around competing framings. A single-source, single-region story almost never qualifies.
3. Decide accept or reject for every topic. Look past the input score: a low-scored topic with sharp cross-regional divergence may deserve elevation, and a high-scored topic with thin perspective breadth may not deserve treatment.
4. For the accepted set, assign priorities across the full 1–10 range. Rebalance so the daily run is not dominated by a single domain (politics, economy, tech, conflict, science, society) or a single region.
5. Write `selection_reason` for every entry — accept and reject alike — and `follow_up_reason` for any topic marked as a follow-up.

# OUTPUT FORMAT

A single JSON array, one entry per input topic. Example:

```json
[
  {
    "title": "ECB holds interest rates steady amid mixed signals",
    "priority": 6,
    "selection_reason": "Exhibits clear transatlantic divergence — European outlets emphasize policy stability while North American coverage focuses on spillover risk. The absence of emerging-market voices creates a useful angle for gap analysis. Qualified for multi-perspective treatment on the strength of competing monetary-policy framings.",
    "follow_up_to": null,
    "follow_up_reason": null
  },
  {
    "title": "Iran claims downing of US drone vessel in the Strait of Hormuz",
    "priority": 9,
    "selection_reason": "Sharp cross-regional divergence between Western and Iranian state-aligned framings, with direct material stakes for Gulf energy trade.",
    "follow_up_to": "tp-2026-04-13-001",
    "follow_up_reason": "Reported destruction of a US unmanned surface vessel — a material military escalation beyond the previous day's blockade announcement."
  },
  {
    "title": "Local transit app launches in Osaka",
    "priority": 0,
    "selection_reason": "No competing framings or cross-regional perspectives available, and no broader implications beyond the local rollout. Inadequate basis for multi-perspective treatment.",
    "follow_up_to": null,
    "follow_up_reason": null
  }
]
```

Field notes:

- `title` — refine the input title where helpful (sharpening or neutralizing). The topic identity must remain the same. This is not a headline.
- `priority` — integer 0 to 10. 0 means rejected; 1 to 10 means accepted, ordered by editorial urgency.
- `selection_reason` — two to four sentences of qualitative editorial reasoning. Mandatory for every entry, including rejects.
- `follow_up_to` — the `tp_id` of a `previous_coverage` entry that this topic continues, or `null` if not a follow-up.
- `follow_up_reason` — one to two sentences naming the specific new developments that justify the follow-up, or `null` if not a follow-up.

Output only the JSON array. No commentary, no markdown fences, no preamble.

# RULES

1. `selection_reason` is qualitative. Do not cite source counts, language counts, region counts, or named outlets such as Reuters or Le Monde. Generic regional attribution — "French outlets," "Russian state media," "West African coverage" — is acceptable and often useful.
2. Every rejection states what is missing: single source, narrow geography, no competing framings, no broader implications, repetition of prior coverage. "Not important" is not a reason.
3. Spread accepted priorities across the full 1–10 range. Clustering accepts in the upper end means editorial discrimination is failing.
4. No more than two accepted topics may share the same priority.
