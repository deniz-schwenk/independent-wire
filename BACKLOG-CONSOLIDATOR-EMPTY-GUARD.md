# BACKLOG — Consolidator empty-emission guard (latent, gates any T3 swap)

Diagnosed 2026-08-26 during T3b: vision-exp @ reasoning=medium returned
finish_reason="stop" with 4,423/4,423 tokens reasoning and an empty body.
Parses to `{}` → `WhatIsMissing([],[])`, and the `what_is_missing` slot's
legitimate-empty semantics (`src/bus.py` ~line 872) make the failure
indistinguishable from a real empty result. Dossier ships without the
missing-voices analysis; nothing logs a failure.

Verified at code: the family pathology is named and mitigated in
`src/agent_stages.py` (cache-cold empty-emission, 3-attempt retry) — but
only for HydrationPhase1. `ConsolidatorStage` has no guard.

Verified at production data: retro-scan of all 75 August consolidator
topic buses — zero occurrences of empty output despite non-empty inputs.
The incumbent pro build has never exhibited the mode in 25 days. Risk is
**latent today, acute at model swap**: the mode is documented on
flash-family @ medium (historical) and vision-exp @ medium (T3b).

## Fix direction (CC task, small — deterministic-before-LLM)
Post-call check in `ConsolidatorStage`: if either input array is non-empty
and both output arrays are empty → retry (Phase-1 pattern, max 2-3), then
loud stage failure instead of silent `{}`. Genuine empty (both inputs
empty) stays legitimate and unretried. Log attempts like Phase 1.

## Sequencing
MUST land before any T3-motivated model change on the consolidator.
Independent of which candidate wins. Merge queue: after
fix/registry-bias-gate.
