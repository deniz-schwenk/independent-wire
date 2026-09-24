# QA_analyze evaluation rubric (v2)

Derived verbatim from the production QA prompts — `agents/qa_analyze/SYSTEM.md`
and `agents/qa_analyze/INSTRUCTIONS.md`. These are the prompt's own stated task
requirements, transcribed into a fixed checklist. The rubric was frozen before
any judging began; it is the single evaluation guideline every judge applies.

An output is a QA analysis of one article: `problems_found[]`, `qa_corrections[]`,
`divergences[]`, and an optional corrected `article`. Judge each output against
the article and its `sources[]` only — the same material the QA task was given.

## Criteria

**R1 — Problem detection.** Does the output identify the article's genuine
factual problems (and only those)? A problem is a real mismatch between the
article and its cited sources: a wrong number/date/attribution/quote/causal
claim (`factually_incorrect`), an assertion with no or non-supporting citation
(`unsupported_claim`), a one-sided figure where sources disagree
(`missing_divergence`), or a framing that misrepresents a source
(`misleading_framing`). Both **missed** real problems and **invented** problems
count against R1.

**R2 — Problem records well-formed.** Each `problems_found[]` entry uses one of
the four valid `problem` types, quotes an **exact verbatim** `article_excerpt`
from the article, and gives a 1–3 sentence `explanation` that names what the
flagged text does and points to the source ID(s) demonstrating the issue (not an
extended re-argument).

**R3 — Grounding / no fabrication.** Every claim the output *itself* makes —
inside an `explanation`, a `proposed_correction`, a `divergence`, or the
corrected article body — rests only on the provided sources. No outside
knowledge, no invented figures, no asserting a source says something it does
not. **A fabrication is an assertion by the output that the provided sources do
not support** (e.g. "src-004 reports $500m" when src-004 says no such thing, or
a correction grounded in a source statement that isn't there). Flagging a
problem that is truly in the article is *not* a fabrication; misdescribing what a
source says *is*.

**R4 — Corrections correspondence.** `qa_corrections[]` has exactly one entry per
`problems_found[]` entry, in the same order (equal length). Each
`proposed_correction` is either a concrete fix that names what changes and which
source supports it (`correction_needed: true`), or a legitimate retraction that
explains why no fix is warranted (`correction_needed: false`). No fix written
while `correction_needed: false`; no `true` on a fragment that fails to name the
change and its source.

**R5 — Corrected-article discipline.** The `article` field is present **iff** at
least one correction has `correction_needed: true`. When present it carries
`headline`/`subheadline`/`body`/`summary`, applies only the warranted fixes
surgically, and preserves the Writer's voice, structure, headline, neutrality,
and `[src-NNN]` citation form; retracted entries leave the body untouched. When
no fix is warranted, the field is correctly omitted.

**R6 — Divergence reporting.** `divergences[]` captures the real source
disagreements relevant to the topic, each with a valid `type`
(`factual`/`framing`/`omission`/`emphasis`), the involved `source_ids[]`, a
`resolution` (`resolved`/`unresolved`/`partially_resolved`), and a
`resolution_note` stating whether and how the article addresses it. Real
disagreements are neither missed nor invented.

**R7 — Precision, no padding.** `problems_found[]` is not padded with spurious,
trivial, or self-cancelling entries (a "problem" immediately retracted for no
substantive reason, a duplicate, a non-issue). High yield of real problems with
low noise scores well; a long list dominated by retracted non-findings scores
poorly.

**R8 — Back-reference & Wikipedia rules.** A back-referential synthesis sentence
that only relates facts already cited earlier is **not** flagged as
`unsupported_claim`. A Wikipedia citation used for a current event, statistic, or
analysis **is** an `unsupported_claim` (Wikipedia is acceptable only for
uncontested background). Output is penalized for getting either rule backwards.

## Scoring each output (what a judge returns)

- **Per criterion R1–R8:** `pass` / `partial` / `fail` with a one-line note.
- **Absolute correctness (1–5):** how well the output performs the QA task
  against the article + sources, judged on its own merits — 5 = precise,
  fully-grounded, complete; 1 = misses real problems and/or asserts unsupported
  content. This is an absolute score, **not** a comparison to the other outputs.
- **Fabrication charges:** zero or more, each citing the **specific claim**
  (verbatim from the output) plus why the provided sources do not support it.
  Only R3-type assertions count — not the mere act of flagging an article
  problem.
- **Ranking:** a strict best→worst ordering of the three outputs.

Golden-reference similarity is **never** a criterion. The three outputs are
anonymous and symmetric; judge each only against the article, its sources, and
this rubric.
