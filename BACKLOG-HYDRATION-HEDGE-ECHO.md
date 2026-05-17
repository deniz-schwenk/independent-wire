# BACKLOG-HYDRATION-HEDGE-ECHO

**Status:** documented; activation gated on production signal.

**Owner:** Architect

**Created:** 2026-05-09

**Related commit:** `93b9d69 fix(pipeline): faithful attribution + substance-based tier classification`

## The pattern

Hydration-Phase-1 (Gemini 3 Flash) imports outlet-self-reference
qualifiers — phrases the source uses to refer back to its own earlier
coverage — into the per-actor `position` field as if they were
source-internal hedges on the actor's statement. The most observed
shape: an article opens a recap paragraph with "as previously reported,
[Actor] said X", which is journalistically clear direct attribution,
but the model renders it as "Reportedly told... X" in the actor's
position field. The article's certainty about the statement has not
shifted; only the article's pointer to its own publication history.

This was the intended target of the Hydration-Phase-1 attributional
fidelity revision shipped in `93b9d69`. The new prompt is correctly
worded ("Render the actor's position using the article's own
attributional language. Do not introduce qualification...") and
eliminates many other failure modes, but does not reliably suppress
this specific outlet-self-reference echo.

## Production evidence

TP-08-002 (Russia/Victory Day, smoke run 2026-05-09):

- Source: `src-024` (Ukrinform, ukrinform.net/rubric-ato/4120973-...)
- Original article text: *"As previously reported, on April 29,
  Russian President Vladimir Putin said during a phone call with U.S.
  President Donald Trump that Russia was ready to declare a ceasefire
  on May 9."*
- Hydration-Phase-1 emitted position: *"Reportedly told U.S. President
  Donald Trump that Russia was ready to declare a ceasefire on May 9."*

The article uses direct attribution ("Putin said"). The hedge
"Reportedly" is introduced by the model, propagating from the
journalistic phrase "as previously reported" earlier in the sentence.

A second instance in the same TP, less load-bearing: src-039 (Sky
TG24) → "Reported to have preferred not holding the parade given the
vulnerability of Russian air defenses." Same shape; the source text
should be re-checked to see whether the original carries an explicit
hedge or whether this is also model-introduced.

## Downstream consequence

The hedged position string drives the substance-based classifier in
the Perspective agent toward `mentioned` (lowest tier, "actions align
with the position"), because the model reads the syntactic shape
"Reportedly told..." as third-party reportage rather than first-person
statement. In TP-08-002, Putin's only cluster membership is `pc-004
[mentioned]` — the Victory Day vulnerability cluster. There is no
cluster about the Putin-Trump phone call ceasefire offer at all,
because the only voice in the dossier expressing that position was
this same hedged Putin rendering.

## Two sub-options to test in a future workstream

**(i) PE-iteration with sharper distinction between outlet
meta-references and source-internal hedging.**

Rewrite the Hydration-Phase-1 attributional-fidelity rule to call out
this specific failure mode. Candidate framings:

- Distinguish lexically: "Phrases the article uses to refer to its
  own earlier coverage ('as previously reported', 'as reported earlier
  this week') are not hedges on the actor's statement. The actor's
  position is rendered with the verb the article applies to the actor
  ('said', 'told', 'announced'), not with the verb the article
  applies to its own publication history."
- Negative example pinned to the prompt: a one-line example of the
  Putin/Ukrinform shape with the correct rendering shown alongside the
  failure mode.

Cost: zero additional API spend; one PE pass + one A2/A3 smoke (~€2).

**(ii) Model upgrade for Hydration-Phase-1.**

Swap Gemini 3 Flash for a stronger reader: Sonnet 4.6 or Gemini 3 Pro.
Rationale: the failure mode is a subtle inferential step (recognising
that "as previously reported" modifies the publication's own
historical pointer rather than the statement's epistemic status),
which a stronger model is more likely to make reliably.

Cost implication: ~10× per Hydration-Phase-1 call. At current daily
volume that's roughly +€1-2 per daily run. Hydration is on the
hot-path; cost discipline matters here. Worth testing whether (i) is
sufficient before paying for (ii).

## Decision criterion for activation

This becomes a TASK if production users flag the Putin-shaped pattern
repeatedly in post-LinkedIn-launch dossiers. Otherwise stays as
BACKLOG. The production-signal threshold is deliberately stricter than
"once" — the substance-based classifier in the new Perspective prompt
is robust enough to recover from one or two hedged-rendering edge
cases per dossier; what would activate this work is a structural
pattern (heads-of-state quoted via reportage chains being
systematically routed to `mentioned` across multiple production
dossiers).

## Artefacts

- Smoke run: `output/2026-05-08/_state/run-2026-05-08-607bb556/`
  (TP-08-002 → topic_index 1; the `topic_buses.HydrationPhase1Stage.1.json`
  and `topic_buses.PerspectiveStage.1.json` snapshots are the
  evidentiary state files)
- TP JSON: `output/2026-05-08/tp-2026-05-08-002.json`
- Original Ukrinform source: src-024 in the same TP, url field

## Out of scope here

- The recipient-exclusion rule (Trump removed from src-024 actors) is
  shipping in the same commit and works correctly. Not a hedge-echo
  issue.
- The Perspective output-schema simplification (drop agent-emitted
  `actor_ids[]`, derive deterministically) is shipping in the same
  commit and works correctly. Not a hedge-echo issue.
- The two production-deferred items from earlier iterations
  (cluster-formation threshold, perspective-cluster-assignment) remain
  separate BACKLOG entries.
