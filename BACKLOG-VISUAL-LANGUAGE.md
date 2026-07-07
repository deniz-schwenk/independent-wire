# BACKLOG — Visual language for transparency data

**Status:** Architect design sketches from concept session 2026-07-06/07.
NOT execution-ready; each concept needs a small design+render task when
activated.
**Premise:** IW's data types (divergences, gaps, bias flags, verification
verdicts, follow-up chains) have NO established visualization language.
The opportunity is not better charts but an own visual grammar for
transparency data. Bar and pie charts are excluded by direction (Deniz).

## House rule (applies to every visual, non-negotiable)

Every visualization is itself an editorial decision — position, order,
color depth all encode judgments. Therefore: (a) every visual is rendered
deterministically from TP JSON — no LLM in any renderer
(deterministic-before-LLM applies to the eye as well); (b) every visual
carries its own legend in the pattern of the bias-card legend: "how to
read this — and what it cannot tell you"; (c) one graphic, one claim —
overloading a figure with a second message is how honesty dies politely.
The most delicate encoding is any ordered axis over sources or framings:
a left-right arrangement suggests a political spectrum the system never
claimed. Order only by measurable quantities, never by ideology; where
distance matters, axes must carry no meaning (see Divergence Compass).

## Level: dossier / day

1. **Bias Seismogram** — the five bias dimensions as horizontal traces
   along article position; each flag a spike where it sits in the text.
   Shows WHERE the coloring concentrates (e.g. framing loaded into the
   opening). DEPENDENCY: evidence anchoring (flags anchored to text
   positions) — see BACKLOG-P2-EVIDENCE-ANCHORING; this visual is that
   backlog item's visible payoff.

2. **Consensus Orbit** — claims as points in concentric rings: verified
   core inside, unverifiable middle zone, explicitly contradicted at the
   periphery; angular position by source region; connecting lines mark
   documented contradictions. Answers at a glance: how firm is the ground
   under this topic? Replaces the fact-check list with a spatial judgment.
3. **Divergence Compass** — sources as points on a plane, distance derived
   from measured claim agreement; contradiction creates distance, omission
   shows as a point without neighbors. Design rule: axes carry NO meaning,
   only distance counts (avoids implying a political spectrum). LAST in
   priority — only concept requiring real method work (distance metric).

## Level: index / day

4. **The Day's Eye** (PRIMARY index/day concept) — ONE world ring for the
   whole day, all topics as nodes inside; lines connect regions to the
   topics they sourced, line width = source count; dashed arc = the day's
   collective blind sector (regions no topic heard from). Shows what no
   per-dossier view can: shared sourcing (one region fanning to several
   topics) and the union blind spot. Scales 3–9 topics. Follow-up topics
   get a small tail (chain depth) linking to the story-thread view.
   - REJECTED ALTERNATIVE (documented so it is not re-litigated): a
     glyph-per-dossier row ("topic glyphs" — identical anatomy per topic:
     ring, source rays, silent arcs, claim dots). Rejected because Deniz
     prefers one unified figure over a notation row; the union view also
     surfaces collective blind sectors, which the row cannot. Per-topic
     depth (verification ratio, perspectives) lives at dossier level.
5. **Selection Field** — published topics as filled cores, DISCARDED
   candidates from the transparency trail as hollow ghost shapes with
   their one-word discard reason (duplicate, thin sourcing, below
   threshold). The most radical rendering of the thesis: the editorial
   decision itself becomes visible. Data exists today per run. CHEAPEST
   build; recommended first.
6. **Day balance line** — one aggregate line under either view: union of
   unique sources, languages covered, regions reached — and, equal-ranked,
   the regions silent today. Weekly accumulation of exactly this line
   feeds the Silence Sediment.

## Level: longitudinal

7. **Story Threads** (PRIMARY longitudinal concept) — follow-up chains as
   horizontal threads across days: node = one installment, node color
   depth = share of verified claims (stories visibly harden or stay
   soft), forks = a story splitting into independent threads, a lone node
   = a topic that died without follow-up (also editorial information no
   newsroom shows). KEY ADVANTAGE: follow-up edges are EXPLICIT pipeline
   data (editor memory) — deterministic record, not a model judgment.
   - v1 scope: node-level aggregates (verified share, source count,
     regions per installment) — all in TP JSON today.
   - Named extension, NOT silently promised: claim-level hardening
     ("unverifiable on d3, verified on d7") requires deterministic claim
     identity ACROSS installments, which does not exist and is not
     trivial. Documented dependency, separate decision.
   - SUPERSEDES the earlier "braided river / Narrativ-Flechtwerk" idea,
     which would have INFERRED topic relatedness via similarity measures —
     a new judgment layer with its own bias. Explicit edges beat inferred
     ones. Do not re-litigate.
8. **Silence Sediment** — regions/topics × weeks; each uninterrupted
   silent week deposits a layer, color densifies with duration; coverage
   events break the sediment visibly. Chronic blind spots become dark
   strata. The natural cover image of the Blind Spot Report (see
   BACKLOG-TP-DATA-LEVERAGE.md — report and graphic are two renderings of
   the same Q4 aggregation layer).

## Priority & dependencies (order of activation)

1. Selection Field — data complete today, strongest statement, pure render
2. Day's Eye — data complete today (region bearings = fixed deterministic
   mapping; silent arc = set difference in Python)
3. Bias Seismogram — after evidence anchoring lands
4. Consensus Orbit — mid-term, dossier level
5. Story Threads (v1 node-level) — needs modest archive depth; pairs with
   Day's Eye tails
6. Silence Sediment — Q4, consumes the aggregation layer
7. Divergence Compass — last; requires distance-metric method work

All seven: no new LLM stage, no new judgment module — renderer work over
existing TP JSON + transparency trail + follow-up edges.
