# BACKLOG-F2-CANONICAL-NAME-CHOICE

**Status:** sketch / Architect-level diagnosis. No PE or CC brief yet.

**Owner:** Architect

**Created:** 2026-05-08, post WP-WRITER-CANONICAL-PROPAGATION

## Problem

`resolve_actor_aliases` (Phase 2 strict-merge) collapses alias actors into a chosen canonical actor — but its **canonical-name-choice heuristic** is fragile in two distinct edge cases the live runs have surfaced:

### Case 1 — typo wins canonical (TP 002, run 2026-05-07)

- `actor-001`: `Tedros Adhanom Ghebreyeu**s**` (typo — should be Ghebreye**su**s)
- `actor-005`: `Tedros Adhanom Ghebreye**su**s` (correct spelling)

The merge picked the typo as canonical and resolved the correct spelling as alias. Empirically the choice appears to be "first-seen wins" — the resolver does not check whether one name is a typo or whether one is more frequent across sources.

The Writer then writes the typo-form at the citation point because it is the canonical string, even though the source dossier overwhelmingly carries the correct spelling.

### Case 2 — quoted callsign in canonical (TP 003, run 2026-05-07, post WP-WRITER-CANONICAL-PROPAGATION)

- `actor-008`: `Robert 'Madyar' Brovdi` (canonical, with apostrophe-quoted callsign inline)
- `actor-010`: `Brovdi` (alias)

The Writer treats the apostrophe-quoted callsign as a parenthetical / nickname token and silently drops it at the citation point — writing "Robert Brovdi" instead of "Robert 'Madyar' Brovdi". This happens despite the verified Variant C prompt instruction (the same prompt produces correct full-name attributions for "Donald Trump" and "Volodymyr Zelensky" in the same run).

The model's stylistic default — "names with parenthetical inline tokens get the parenthetical dropped in formal prose" — overrides the prompt for this canonical shape.

## Common pattern

Both cases are **canonical-name-choice failures**, not Writer-side failures. The Writer faithfully renders whatever string `actors[].name` carries. The defect is upstream: `resolve_actor_aliases` chose a canonical string that downstream consumers cannot reliably reproduce — either because it contains an error (Tedros) or because it contains a stylistically unusual token the LLM Writer treats as droppable (Brovdi).

The Writer cannot solve this. No prompt iteration on the Writer will fix Case 2 without explicit edge-case enumeration ("if the canonical contains apostrophe-quoted tokens, reproduce them verbatim") — which is exactly the kind of regulation Variant C was designed to avoid.

## Possible directions (not chosen — sketch only)

1. **Frequency-weighted canonical choice.** When multiple alias candidates exist, pick the variant that appears most often across the dossier (counted from `actors_quoted[]` strings before merge). Solves Tedros cleanly. Solves Brovdi only if the bare "Brovdi" appears more often in sources than the full callsign form — likely true, which would mean canonical becomes "Brovdi" alone, losing the callsign entirely. Probably wrong.

2. **Length-weighted canonical choice with sanity bound.** Pick the longest variant that is a prefix or near-prefix of the others. Solves Brovdi (full form wins). Solves Tedros only if the typo and correct form are both present — but if the typo dominates, length-weighted picks the typo too.

3. **LLM-based canonical-choice tiebreaker.** When alias candidates conflict, ask a separate cheap LLM call: "given these N name variants for the same entity, which is the most appropriate canonical form?" Cost-aware, decoupled from the strict-merge logic. Adds one model call per merge in the run.

4. **Frequency × authoritative-source weighting.** Like (1) but weight by source authority (institutional / state / wire vs. unknown). Heavier infrastructure.

5. **Manual canonical override list** for known recurring entities. Brittle, breaks the openness principle, but solves the long-tail of recurring high-impact actors (heads of state, named military commanders).

## Why this is BACKLOG, not TASK

- No clean preferred direction yet — each option has a failure mode on at least one of the two cases
- Frequency of occurrence: 2 cases in 9 dossiers shipped to date — real but not blocking
- The canonical Writer-attribution audit trail is the actor's `id`, not the printed string. The strings being slightly wrong does not break audit traceability — it breaks reader trust in spelling, which is a quality concern, not a correctness concern.

## Decision-criteria when this becomes TASK

The right answer probably needs evaluation: pick 2–3 options above, run them on a small fixture set of merge cases (manually constructed plus harvested from previous runs), measure which produces canonical strings the Writer reproduces verbatim. Then ship.

Until then: ship as known-edge-case, carry on.
