# RUBRIC-researcher-plan — T5A Round 1

Fixed before any judging. Scored against the topic inputs and these anchors
ONLY: the anchors are absolute standards, not a curve, and no judge ever sees
another output.

The `researcher_hydrated_plan` agent reads a topic assignment plus a
`coverage_summary` describing what the hydration pass already collected
(`total_sources`, `languages_covered`, `countries_covered`,
`stakeholder_types_present`, `coverage_gaps[]`) and emits a list of web-search
queries, each with a language code, designed to fill what the existing coverage
misses. The plan IS the product; nothing else is emitted.

---

## THE KNOWN LIMIT OF THIS RUBRIC — READ FIRST

**This rubric scores the PLAN, not the downstream harvest.**

No search is executed anywhere in this evaluation. Every score below is a
judgment about a plan as an artifact, read against the dossier it is meant to
extend. That is an upstream proxy, and its correlation with what the queries
would actually retrieve is **unmeasured**:

* A plan can be excellent by every anchor here and still return nothing — the
  local outlet may not have covered the story, the phrasing may be a dead
  string in that language's search index, the institution may publish nowhere
  a crawler reaches.
* A plan can look mechanical and retrieve well, because a blunt query in the
  right language sometimes beats a sophisticated one.

The planner has never been judged before, so there is no prior calibration to
inherit and no measured plan-to-harvest correlation to lean on. A model that
wins on this rubric has been shown to write better plans, not yet to produce
better dossiers. Anyone reading a verdict built on it should carry that gap
forward explicitly.

Two consequences for judges: score the plan you were given, not the plan you
would have written; and where an anchor asks whether a query *would* surface
something, judge plausibility from the dossier and say so in the note rather
than pretending to knowledge of a search index.

---

## THE FIRST STEP IS NOT SCORING

You return three fields **before** any score. They are computed, not
impressionistic, and the dimensions are defined on them.

### 1. `dossier_open_questions` — your own reference list, formed FIRST

Read the topic assignment and the `coverage_summary`, and write your own list
of what this dossier leaves open: which sides of the contested matter are
unsourced, which directly-involved countries or language communities are
absent, which stakeholder types named in `coverage_gaps` have no voice, which
factual questions the existing coverage raises and does not answer.

Form this list **before you read the plan**. Without it, "gap coverage"
degenerates into "did the plan look thorough", because the only spectrum in
your window would be the plan's own. Naming the reference list first is what
makes an untargeted gap visible.

### 2. `angle_groups` — partition the queries by information angle

Two queries belong to the SAME angle group when they chase the same
information, even when:

* they are in different languages;
* they name the same event from different national vantage points *without* a
  different stakeholder, question, or aspect behind them;
* one is broader and the other narrower on the same axis, with no new
  substantive question in between.

They are DIFFERENT angle groups when they would surface materially different
material — a different stakeholder speaking, a different aspect of the story, a
different kind of source (official filing vs affected community vs trade
press), or a different contested question.

This partition is the rubric's teeth. PLAN-INSTRUCTIONS.md forbids the
"translation-matrix anti-pattern" by name: one headline angle re-emitted in six
languages "counts as one query, not six". A judge told that in prose will nod
and then score query count anyway, because count is the salient number on the
page. So the partition is a required field, and D2 is defined on it.

Assign every query index to exactly one group. Each group carries a one-line
statement of the shared angle. **For every non-English query, put your own
short English gloss of what it actually says in the group line** — the plan
must be judged on what the query means, not on the fact that it is in Farsi.
If you cannot read a query's language well enough to gloss it, say so in the
note and score the affected dimensions `null` rather than guessing.

Return `n_queries` and `n_angle_groups`. **Raw query count is never a measure
of anything.**

### 3. `named_absences` — what the plan does not target

The entries from your own `dossier_open_questions` that no query in the plan
goes after. Count them.

---

## Dimensions (score each 1–5, whole numbers, or `null` if unassessable)

### D1 — Gap coverage
*How much of what the dossier leaves open the plan actually targets, counted in
angle groups against your own `dossier_open_questions`.*

- **5** — Every open question your reference list carries has at least one
  query going after it, in a language and register plausibly able to reach it.
  Stakeholder types named in `coverage_gaps` are targeted specifically, not
  incidentally.
- **4** — One open question from your list is untargeted, or is targeted only
  by a query so general it would return the coverage the dossier already has.
- **3** — Two or three are untargeted; the plan still covers the story's
  central contested matter and its main absent voices.
- **2** — A major side of the contested matter, or the single largest named
  coverage gap, has no query aimed at it.
- **1** — The plan is aimed at what the dossier already covers: it would
  return more of the same sources.

A plan that targets fewer gaps well beats one that gestures at all of them with
queries that could not reach any. Score reach, not enumeration.

### D2 — Angle distinctness
*Whether the plan's query count is earned.*

Computed against your own `angle_groups`: how many queries exceed the number of
groups, and how much of the plan's budget they consume.

- **5** — Every query is its own angle group, or the few that share a group are
  genuinely different stakeholders or aspects inside it.
- **4** — One redundant pair; defensible as a fine distinction even if you
  would not have drawn it.
- **3** — Two or three queries restate an angle already present, or one angle
  is split across queries differing only in wording or year.
- **2** — A substantial share of the plan is the translation-matrix
  anti-pattern: one headline angle rendered across several languages with no
  change of stakeholder, question, or aspect.
- **1** — The plan is mostly one or two angles inflated into many queries.

Every duplicate here costs a real search from a fixed budget. Score it as the
waste it is, not as harmless redundancy.

### D3 — Specificity and actionability
*Whether these are strings a working journalist would actually type.*

- **5** — Queries use local institution names, local abbreviations, and the
  terminology the story is discussed in inside each language community; native
  script where the language requires it; temporal markers where natural. Each
  is narrow enough to return the specific thing it is after.
- **4** — Mostly specific; one or two queries are generic enough that they
  would return an undifferentiated news wall.
- **3** — A mix: the plan names some institutions and terms correctly but
  several queries are keyword soup, or an English institution name is carried
  untranslated into a language that has its own.
- **2** — Most queries are generic topic strings — the story's title plus a
  country plus a year — that would return the same results as each other.
- **1** — The queries could not be executed usefully: empty, malformed,
  transliterated where native script is required, or so broad as to be
  meaningless.

Length is not specificity. A long string of stacked keywords can be worse than
a short precise one; judge what the string would plausibly retrieve.

### D4 — Prioritisation soundness
*Whether the plan spends its query budget where the story's weight is.*

- **5** — The largest share of queries goes to the story's central contested
  matter and its most consequential unsourced voices. Peripheral angles get
  proportionate, not equal, attention. The ordering and volume reflect a
  defensible read of what matters in this story.
- **4** — Broadly well-allocated; one peripheral angle takes budget a more
  central gap needed.
- **3** — Flat allocation: the plan treats every gap as equally important, so
  the central matter gets no more attention than a minor one.
- **2** — Inverted: substantial budget goes to peripheral or already-covered
  ground while a central gap gets one query.
- **1** — No discernible prioritisation; the plan reads as a checklist of
  languages rather than a research strategy.

Proportionality is to the story's weight as the dossier shows it, not to equal
coverage across languages. A language community central to the story warrants
more queries than one included for balance.

### D5 — No-invention
*Whether the plan asserts anything the inputs do not support.*

This is the fabrication dimension and it is the reason judges are given the
full dossier. Charge an instance when a query:

* names a person, body, document, or event that does not exist, or that has no
  plausible connection to this story;
* embeds a factual claim the dossier does not support and that a search would
  therefore be seeking confirmation of rather than testing (a query presupposing
  a death toll, an attribution of blame, or a signed agreement the dossier does
  not carry);
* attributes a position or statement to a named actor that the dossier does not
  show them taking.

- **5** — Nothing invented. Where a query names a body absent from the dossier,
  it is a real body plausibly connected to the story — targeting a missing
  voice, which is the plan's job.
- **4** — One query embeds a mild unsupported presupposition; no invented
  entity.
- **3** — One invented or misattributed entity, or two unsupported
  presuppositions.
- **2** — Several invented entities or attributions; a reader would be misled
  about what the dossier establishes.
- **1** — The plan is substantially built on things the inputs do not support.

**Naming something absent from the dossier is NOT by itself invention.** The
planner's whole purpose is to reach voices the coverage lacks; "IMO",
"Lloyd's", "ICRC" appearing where the dossier has no maritime or humanitarian
voice is the plan working. Charge only what is unreal or unsupported, and cite
the query index and the exact span in `charges`.

This dimension carries invention inside native-script queries, which no
mechanical screen at this stage can detect. Read those queries as carefully as
the English ones.

### D6 — Region and language balance awareness
*Whether the language selection follows this story's actual geography.*

- **5** — The languages chosen are those spoken where the story is happening
  and by the actors in it, weighted toward communities absent from
  `languages_covered`. Native script throughout. English is present for
  baseline anchoring but does not dominate.
- **4** — Sound selection with one language included by regional default rather
  than by this story's actual involvement.
- **3** — Several languages look picked off a region-to-language table rather
  than from the story: present but not where the reporting would be.
- **2** — The selection misses a language community central to the story, or is
  English-dominated.
- **1** — The language plan is unrelated to the story's geography.

Judge involvement, not variety. Fourteen languages picked mechanically is worse
than eight picked because the actors speak them. Where a language is already
well represented in `languages_covered`, adding more of it is a cost, not a
credit.

---

## Output contract

Return one JSON object:

```json
{
  "dossier_open_questions": ["...", "..."],
  "angle_groups": [
    {"query_indices": [0, 4, 9], "angle": "one line; gloss non-English queries"}
  ],
  "n_queries": 24,
  "n_angle_groups": 17,
  "named_absences": ["open question the plan does not target", "..."],
  "scores": {"D1": 4, "D2": 3, "D3": 4, "D4": 4, "D5": 5, "D6": 4},
  "mean": 4.0,
  "notes": {"D1": "...", "D2": "...", "D3": "...", "D4": "...",
            "D5": "...", "D6": "..."},
  "charges": [
    {"query_index": 7, "text": "the exact offending span",
     "why": "what the dossier does not support"}
  ]
}
```

Every query index must appear in exactly one `angle_groups` entry.
`charges` is `[]` when there are none. A dimension you cannot assess is `null`
with the reason in its note — never a guessed number.

`scores` carries exactly six entries, `D1`–`D6`, whole numbers 1–5 or `null`.
`mean` is the **unweighted** mean of the non-null dimensions, two decimals.

`n_queries`, `n_angle_groups` and `mean` are **advisory**: the analysis
recomputes all three from `angle_groups` and `scores` and uses the computed
values, counting any disagreement in the judge-reliability statistics. You are
not scored on them — they are a self-consistency check, so compute them as you
see them rather than to match anything.

A judge that cannot produce this object returns `{"error": "<reason>"}`; the
pair is re-dispatched once to a fresh judge before being recorded as a judging
failure.
