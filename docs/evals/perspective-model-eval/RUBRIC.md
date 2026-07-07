# Perspective-stage rubric (R1–R9)

Transcribed verbatim-in-substance from the production perspective prompts
(`agents/perspective/SYSTEM.md` + `INSTRUCTIONS.md`) and **fixed before any
judging**. The perspective agent reads a multilingual dossier and (a) groups the
positions expressed across all sources into distinct clusters, (b) assigns the
dossier's actors to the clusters whose position they hold, and (c) names the
types of perspective absent from the corpus. The perspective spectrum IS the
product — **invented positions or attributions are the product-critical failure
mode**.

Each output is scored on nine criteria. For each: **pass (1)** / **partial (½)**
/ **fail (0)**.

- **R1 — Cluster by substance, not topic.** Two actors reaching opposite
  conclusions about the same situation are in *different* clusters; two actors in
  different countries/languages/outlets making the *same* claim are in the *same*
  cluster. Clusters are distinguished by the substantive claim, not the subject.
- **R2 — position_label is a thesis-like claim.** One sentence stating the
  position itself (*"Iran is financially collapsing and near capitulation"*), not
  a topic phrase, not a question, not an actor's name.
- **R3 — position_summary grounds the position.** One or two sentences expanding
  what the position argues and the grounds it rests on — not a restatement of the
  label, not a topic description.
- **R4 — Grounding / NO fabrication (product-critical).** Every cluster,
  position, source and actor traces to the dossier. Positions are not assembled
  from outside knowledge. No invented source ids, no invented/unsupported actor
  attributions, no positions that no source or actor in the dossier holds. This
  is the criterion the invented-position/attribution charges attach to.
- **R5 — Actor assignment correctness.** Each actor is placed only in clusters
  whose substantive position it actually holds; an actor is written into the
  sub-list (`stated`/`reported`/`mentioned`) matching its pool of origin, never
  re-classified across pools; background-only / passing-mention actors carrying
  no positional signal appear in no sub-list. A source in a cluster's
  `source_ids` does not force every actor it quotes into that cluster.
- **R6 — Cluster granularity fits the content.** The number of clusters is
  driven by the material (a typical dossier yields ~3–8, a rough order of
  magnitude not a target). Genuinely distinct positions are separated; mere
  variation in wording or emphasis is not split into extra clusters; a single
  actor's two genuinely distinct positions may span two clusters.
- **R7 — Missing perspectives are specific and warranted.** Each entry names a
  `type` from the ten-value enum (`government, legislature, judiciary, military,
  industry, civil_society, academia, media, international_org,
  affected_community`) and explains in one concrete sentence which specific
  perspective is absent and why its absence matters here. Generic ("no academia")
  fails; specific ("no independent health-policy researchers assessing the
  civilian-casualty figures") passes. Up to five; empty is correct when the
  dossier is well-balanced.
- **R8 — Own-words discipline.** The output describes positions in its own words:
  no pasted actor `position` text in labels/summaries, no translated
  `verbatim_quote` content, no reproduced article wording; labels and summaries
  are in English regardless of source language.
- **R9 — Spectrum fidelity / balance.** The set of clusters faithfully
  represents the range of positions the dossier actually supports — no position
  the sources carry is dropped, none is invented or inflated beyond its dossier
  footing, and opposing sides present in the corpus are both surfaced. The
  missing-positions list complements this by naming what the corpus itself lacks.

## Absolute correctness (1–5)

Holistic quality of the perspective analysis as a transparency artifact,
independent of the other outputs:

- **5** — Faithful, complete, well-separated spectrum; actor assignments sound;
  missing-perspective calls specific and warranted; zero fabrication.
- **4** — Strong; minor granularity or assignment imperfections; no fabrication.
- **3** — Usable but with real gaps (a merged/split cluster, a few loose actor
  assignments, or generic missing-perspective entries); no clear fabrication.
- **2** — Notable problems: a missing major position, several misassignments, or
  a weakly-supported attribution.
- **1** — Fabricated position/attribution, or a spectrum that misrepresents the
  dossier.

## Invented-position / attribution charges

Flag any **specific** instance where the output asserts a position no source or
actor in the dossier holds, attributes a position to an actor the dossier does
not support, references a source/actor absent from the input, or manufactures a
cluster from outside knowledge. **Each charge must cite the exact offending claim
(the cluster label/summary text or the actor/source id) and say why it is
unsupported by the provided sources.** A charge is only counted when ≥2 of the 3
judges independently cite the same instance.
