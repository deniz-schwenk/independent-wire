# Writer-stage judging rubric (R1–R9)

Transcribed from the production Writer prompts (`agents/writer/SYSTEM.md` +
`INSTRUCTIONS.md`, and `FOLLOWUP.md` for follow-up topics). Score each
**applicable** item per output: **pass = 1 / partial = ½ / fail = 0**. An item
that does not apply to a topic (e.g. R9 on a non-follow-up) is scored `n/a` and
excluded from that output's pass-rate denominator.

Judge every output against these requirements **and the sources provided** —
nothing else.

- **R1 — Multi-perspective coverage.** Every position cluster in the dossier's
  perspective analysis is substantively addressed: at least one factual sentence
  with attribution conveying its position. A one-source cluster can be the only
  voice on a critical aspect — presence is required regardless of weight;
  per-cluster counts inform how much *space* a cluster gets, not whether it
  appears. Fault lines are built around framing differences, not marched through
  one stakeholder at a time.

- **R2 — Grounding / no fabrication.** Every new factual claim carries an inline
  `[src-NNN]`, and the cited source actually supports the claim as stated. No
  invented sources, quotes, facts, or attributions; no claim attributed to a
  source that does not contain it. (A fabrication charge under R2 must cite the
  specific claim and the source it misrepresents or that is missing.)

- **R3 — Citation discipline.** Inline citations use `[src-NNN]` matching dossier
  ids. No floating facts ("experts say" with no citation). A back-referential
  synthesis sentence that introduces no new fact carries the citations of the
  facts it rests on; any sentence adding a new fact needs its own `[src-NNN]`.

- **R4 — Equal weight & symmetry.** Competing clusters get the same factual
  register, the same density of attribution, and the same kind of phrasing.
  Contrasts across languages/regions are written in symmetric registers — no
  asymmetric editorial loading on one side.

- **R5 — Reporting voice.** Neutral attribution verbs (said, stated, reported,
  told, wrote, announced, published, described); `claimed` only for
  source-framed-as-disputed. Third-person reporting voice. No verdict on which
  side is right, no causal claim without a source, no "this suggests / indicates
  / reveals", no evaluative or narrative turn.

- **R6 — No editorial or intensity vocabulary.** No evaluative words in the
  writer's own voice (controversial, alarming, landmark, stunning, historic,
  …). No trajectory/intensity vocabulary in the writer's own voice (sharply,
  widening, sharpening, deepening, escalating, intensifying, mounting,
  spiraling, self-reinforcing, measured, …). Concrete attribution replaces
  characterization.

- **R7 — No coverage-landscape meta-claims.** The writer does not make its own
  observations about which outlets/languages/regions did or did not cover
  something, what is "absent from Western coverage", what "received little
  attention", or that an actor "has not responded". A plainly sourced fact ("RT
  reported Moscow has not commented [src-014]") is fine; the writer's own
  meta-claim about the distribution of coverage is a failure.

- **R8 — Structure, length, format.** Lead states what/where/when and per which
  sources. Paragraphs are one idea, ~4–5 sentences, and begin with their central
  fact. Closing describes the current state or named next developments,
  attributed to sources. Body is 600–1200 words. The body contains **no numeric
  claims about source/language/region counts** anywhere. The article does not
  begin with the word "In". Non-English quotes appear in the original followed by
  a parenthetical English translation.

- **R9 — Follow-up discipline (follow-up topics ONLY).** Leads with the new
  development (the `follow_up.reason`), attributed to dossier sources. The
  article is self-contained — no "as previously reported" / "building on
  yesterday's coverage" / pointer to a separate document. Two–three sentences of
  background, not a recap paragraph. Leading with the new development does not
  license sympathetic framing: the new fact carries a citation and competing
  positions on it get equal-weight treatment.

---

## THE STYLE TRAP (binding — read before scoring)

IW writes deliberately flat prose — restraint is a product decision (VISION Part
08). Judges evaluate ONLY against the prompt's own requirements: a livelier,
"better-written" article that deviates from the prompt's restraint constraints
is a rubric FAILURE, not a bonus. No general writing-quality taste.

Concretely: if one article is more vivid, more narratively engaging, or "reads
better" **because** it uses intensity vocabulary, editorial characterization, a
narrative turn, or the writer's own synthesis beyond what the sources state, that
article scores **lower** on R5/R6/R7, not higher. Do not reward liveliness. Do
not penalize an article for being flat, dry, or list-like if it faithfully meets
the requirements. Correctness and faithful restraint are the product; prose flair
against the constraints is a defect.
