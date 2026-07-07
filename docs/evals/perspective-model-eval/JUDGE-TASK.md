# Judge task — perspective-stage blind panel

You are one of three independent expert judges evaluating **five anonymized
perspective analyses** of the SAME news dossier. Each analysis groups the
positions expressed across the dossier's sources into clusters, assigns the
dossier's actors to those clusters, and names perspective types missing from the
corpus. You do not know which model produced which output; judge only what is in
front of you.

You are given, in your packet:
- `topic` — the dossier title + editorial framing (`selection_reason`).
- `sources[]` — the multilingual research dossier every analysis worked from
  (each with `id`, `outlet`, `language`, `country`, `title`, `summary`, and an
  `actors_quoted[]` array).
- `canonical_actors_stated[] / _reported[] / _mentioned[]` — the three
  pre-classified actor pools the analyses assign from (each actor has an `id`,
  `name`, `role`, `type`, and `quotes[]`).
- `RUBRIC` — the fixed R1–R9 rubric + the correctness scale + the
  invented-position/attribution charge rule. **Read it fully before scoring.**
- `outputs` — five analyses labeled `A`–`E`, in randomized order.

**The perspective spectrum is the product. Invented positions or attributions —
a cluster no source supports, a position attributed to an actor the dossier does
not back, a referenced source/actor absent from the input — are the
product-critical failure and must be caught and charged.** Verify attributions
against the sources and the actor pools; do not reward fluent prose that drifts
from what the dossier actually supports. Restraint and fidelity beat richness:
an analysis that invents a plausible-but-unsourced cluster is WORSE than one that
reports a thinner but faithful spectrum.

For **each** output A–E, return:
- `correctness` — integer 1–5 (RUBRIC scale).
- `rubric` — a verdict for each of `R1`…`R9`, one of `"pass"`, `"partial"`,
  `"fail"`.
- `charges` — a list (possibly empty) of invented-position/attribution charges.
  Each charge MUST cite the exact offending claim — the cluster
  `position_label`/`position_summary` text, or the `actor-NNN`/`src-NNN` id — in
  `claim`, and explain in `why` precisely why the provided sources/actor pools do
  not support it. Only raise a charge you can tie to a specific claim; do not
  raise vague or stylistic complaints here.

Then return `ranking` — a strict best-to-worst ordering of all five labels
`A`–`E` (no ties; break them with your own judgment).

Output ONLY a single JSON object of this exact shape, no prose, no markdown
fence:

```json
{
  "outputs": {
    "A": {"correctness": 4, "rubric": {"R1":"pass","R2":"pass","R3":"pass","R4":"pass","R5":"partial","R6":"pass","R7":"pass","R8":"pass","R9":"partial"}, "charges": []},
    "B": {"correctness": 2, "rubric": {"R1":"pass","R2":"partial","R3":"pass","R4":"fail","R5":"fail","R6":"pass","R7":"partial","R8":"pass","R9":"fail"}, "charges": [{"claim":"cluster 'Tehran secretly agreed to disarm' / actor-014", "why":"No source in the dossier states or reports Tehran agreeing to disarm; actor-014's only quote (src-006) concerns fuel imports, not disarmament."}]},
    "C": { ... },
    "D": { ... },
    "E": { ... }
  },
  "ranking": ["A","C","E","B","D"]
}
```

Your `outputs` object must contain exactly the five keys A, B, C, D, E, and
`ranking` must be a permutation of those five labels.
