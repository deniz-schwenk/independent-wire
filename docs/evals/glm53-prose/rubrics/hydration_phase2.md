# Hydration Aggregator Phase-2 rubric (R1-R6)

Transcribed from the production Phase-2 prompts
(`agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md`).
Frozen before judging. It is the ONLY standard a judge applies.

The output is a corpus-level reducer result over one topic:
`{"preliminary_divergences": [str], "coverage_gaps": [str]}`. Judge each output
against the `article_analyses[]` + `article_metadata[]` it was given - nothing
else. No outside knowledge about the events.

Score each **applicable** item: **pass = 1 / partial = 1/2 / fail = 0**. Also
give one absolute 1-5 quality score for the output as a whole.

- **R1 - Cross-group unit of analysis.** Every divergence is a pattern ACROSS
  language groups or regional clusters, and names the specific groups involved.
  A difference between two articles inside the same language group is not a
  divergence and is a failure of this item, as is a divergence stated without
  naming its groups.

- **R2 - Grounding / no fabrication.** Every divergence and gap rests on what
  `article_analyses[]` actually says and on the languages/countries/outlets
  actually present in `article_metadata[]`. Asserting that a group frames
  something a way the analyses do not describe, inventing an actor or a fact, or
  attributing coverage to a language/region absent from the metadata is a
  fabrication. (A fabrication charge must cite the specific sentence and the
  input it misrepresents.)

- **R3 - Specificity.** Each divergence names what differs, concretely. Each gap
  names a specific missing region, stakeholder type, or story dimension AND why
  its absence matters for this topic. Generic phrasing ("articles differ in
  emphasis", "more sources needed", "coverage is uneven") is a failure.

- **R4 - Gap validity.** A named gap is genuinely absent from the corpus. Naming
  as missing a region, stakeholder type, or dimension that the analyses DO cover
  is a false gap and fails this item. Conversely, a corpus-obvious absence (a
  central region or stakeholder type with no coverage anywhere) that the output
  misses counts against it.

- **R5 - Coverage / recall.** The substantive cross-group differences and the
  substantive absences actually present in the corpus are found. Judge both
  directions: material misses and padding with non-substantive entries both
  fail. Volume is not merit - a long list of thin observations scores below a
  short list of real ones.

- **R6 - Form discipline.** Each entry is ONE clear sentence. No commentary,
  preamble, markdown, or meta-talk about the task. No reference to an
  `article_index` not present in the input. Arrays may legitimately be empty
  when the corpus genuinely offers nothing - an honest empty array is a pass,
  not a failure.

---

## THE VOLUME TRAP (binding - read before scoring)

This stage feeds a downstream dossier. A longer list is NOT a better list. An
arm that emits ten thin, partly-unsupported divergences scores BELOW an arm that
emits four real, well-grounded ones. Reward grounded specificity; penalize
padding, restated near-duplicates, and observations that dress up the corpus's
composition ("most articles are in English") as a framing divergence.
