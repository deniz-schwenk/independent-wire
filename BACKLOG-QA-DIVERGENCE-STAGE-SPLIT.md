# BACKLOG — QA divergence handling: observe, then decide on stage split

Status: OBSERVE (no fix). Opened 2026-05-30.

## Trigger
tp-2026-05-30-003 (UN sexual-violence blacklist). A hard counter-fact — the
Guardian's report that Ukrainian forces themselves were cited for 31 verified
incidents, i.e. Ukraine is also on the list — never reached the article body.
Russia appears as sole perpetrator, Ukraine only as victim, though the system
held the fact.

## What was verified (diagnosis, no longer open)
- The counter-fact is QA-originated and POST-Writer. At Writer time it existed in
  no divergence slot. `qa_divergences` is empty when the Writer runs; the fact was
  first inferred by the QA agent afterwards.
- The Writer's only pre-Writer divergence slot, `merged_preliminary_divergences`,
  carried 10 entries for this topic — all of them framing/coverage/emphasis
  observations (which outlet foregrounds what), bare strings without type/
  resolution. NONE was a hard cross-source fact disagreement. This slot is
  Researcher feed (query-sharpening), not Writer material.
- Therefore wiring divergences into the Writer is REJECTED: it would feed coverage
  framing that correctly belongs in the layer (and that Lever 2 deliberately keeps
  out of the body), and would not have surfaced this fact anyway.
- QA DID flag the fact correctly as `missing_divergence`, then retracted it
  (correction_needed: false) with a factually wrong justification — it claimed the
  detail was "already noted in the Guardian paragraph later," which the body does
  not contain (that paragraph carries only the male-detainee point + Ben-Gvir).

## Why no fix now
The retraction error is a single QA-agent reasoning miss — LLM noise, not
deterministically fixable by a prompt rule. The compressed QA can and does enforce
missing_divergence elsewhere (Romania 70-vs-217 in the smoke). The fact remains
visible in the TP's divergence layer; it is absent only from the body.

## Observation criterion
Over the coming production runs, watch whether QA-originated hard counter-facts
that flip framing balance (a party shown only as victim/only as perpetrator while
a source proves the inverse) are a RECURRING wrongly-retracted pattern, or a
one-off.

## Future lever (decide only if it becomes a pattern)
The QA agent currently does two jobs in ONE LLM run: (a) factual corrections to the
article text, and (b) cross-source divergence analysis. These may compete — the
correction-minded pass ("is the Russia paragraph accurate as written? yes") can
swallow the divergence-minded duty ("but a source flips the framing"). Candidate
fix: split into TWO separate stages / two separate LLM runs — one for text
corrections, one for divergence analysis — so neither dilutes the other. This is a
framework change with its own smoke; not justified by a single incident.

## Activation
Pattern confirmed across runs → Architect writes the stage-split design (bus slots,
stage order, two prompts) as a proper task. Until then: observe only.
