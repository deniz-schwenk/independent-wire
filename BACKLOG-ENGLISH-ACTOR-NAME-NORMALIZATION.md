# BACKLOG — Deterministic English actor-name normalization

Status: OPEN
Raised: 2026-06-15
Origin: surfaced while building the German translation stage
(de_exonyms lookup); see
docs/handoffs + ~/iw-translation-eval/results/SCOPE-TURNORDER-ANALYSIS.md.

## Problem

Actor names in finished Topic Packages are not canonicalized. The same
entity appears in multiple surface forms within a single TP — verified
example in tp-2026-06-14-001: `actors[].name` contains both
"US state department" and "US State Department". The names are
LLM-generated output extracted from raw articles by upstream agents
(hydration, perspective), and each tends to mirror the casing/spelling
of its source article. There is no deterministic normalization pass
that collapses surface variants to one canonical English form.

`resolve_actor_aliases` maps alias_id -> canonical_id, but evidently
does not normalize trivial casing/spacing variants across all
name-bearing fields, or these variants would not reach the final TP.

## Why it matters

- The English TP itself is internally inconsistent (a credibility /
  polish defect, visible to readers).
- It is the ROOT of the German terminology-drift defect: the
  translation stage currently has to absorb the inconsistency
  downstream (mitigated for now by case-insensitive lookup in
  config/de_exonyms.json, which fixes the German symptom only).
- Fixing it in English makes every downstream rendering — German and
  any future language — inherit consistency for free. This is the
  "fix the input, don't forbid the output" principle.

## Proposed direction (not yet scoped)

A deterministic normalization step in the English pipeline that
canonicalizes actor surface forms (case, whitespace, common
abbreviation variants) to one form before the TP is finalized.
Candidate: extend or follow `resolve_actor_aliases`, or a Python
post-pass keyed on a canonical-form map. Deterministic-before-LLM:
casing/whitespace canonicalization is pure code, no LLM needed.

## Relation to translation workstream

Decoupled. The translation stage proceeds now with case-insensitive
lookup as the interim mitigation. This backlog item is the proper
root fix and touches production pipeline code — it must NOT be folded
into the translation work.
