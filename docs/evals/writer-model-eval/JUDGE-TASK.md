# Judge task — Writer-stage blind evaluation (one of three independent judges)

You are one of **three independent judges** scoring anonymized outputs of a
news-article writing task. You judge **blind**: you do not know which system
produced which output, and you must not speculate about it. Judge only against
the rubric and the provided sources — nothing else.

## What you receive (in `packet.json`)

- `input` — the writing assignment: `title`, `selection_reason`, the perspective
  analysis (`position_clusters` with `position_label` / `position_summary` /
  `source_ids`, and `missing_positions`). If `follow_up` is present, the task was
  a follow-up: `follow_up.reason` is the new development the article must lead
  with, and rubric item **R9 applies**. If `follow_up` is absent, **R9 is n/a**.
- `sources` — the dossier the article had to be grounded in (each with `id`,
  outlet, language, country, and a `summary`). Check every citation against
  these.
- Four anonymized outputs: `outputs.A`, `outputs.B`, `outputs.C`, `outputs.D`,
  each `{headline, subheadline, body, summary}`. Order is randomized per topic.

Also read `RUBRIC.md` (R1–R9 + the binding STYLE TRAP) in the same directory.

## The style trap (binding — repeated from RUBRIC.md)

IW writes deliberately flat prose — restraint is a product decision. Evaluate
ONLY against the prompt's own requirements: a livelier, "better-written" article
that deviates from the restraint constraints is a rubric FAILURE, not a bonus.
No general writing-quality taste. Do not reward vividness, narrative energy, or
the writer's own synthesis beyond the sources; those are defects under R5/R6/R7.
Do not penalize flat, dry, or list-like prose that faithfully meets the
requirements.

## How to score each output

1. **Absolute correctness (1–5)** — how well the article satisfies the rubric
   and stays grounded in the sources. 5 = fully faithful and complete; 1 = badly
   flawed (fabrications, missing dominant clusters, editorializing). This is
   absolute, not relative — two outputs may both deserve 5, or both 2.
2. **Rubric R1–R9** — for each item a verdict `"pass"` / `"partial"` / `"fail"`,
   or `"na"` when the item does not apply (R9 on non-follow-ups). Judge R8's
   length loosely (you cannot count words exactly — flag only clearly-too-short
   or clearly-too-long).
3. **Fabrication charges** — list every claim in the body that is **not
   supported by the cited source** (or cites a source id absent from the
   dossier, or invents a quote/fact/attribution). Each charge MUST carry: the
   `claim` (quote the sentence or its factual core), `cited_src` (the `[src-NNN]`
   it leans on, or `"none"`), and `why_unsupported`. If you make no charge, use
   an empty list. A charge without a specific claim citation does not count.

## Then rank

Provide `ranking`: the four labels best-to-worst as a **strict permutation** of
`["A","B","C","D"]` (no ties — if two are close, use correctness + rubric to
break it). This is used for majority-pairwise aggregation across the three
judges.

## Output (write EXACTLY this JSON, nothing else, to the path you are given)

```json
{
  "outputs": {
    "A": {"correctness": 4,
          "rubric": {"R1":{"verdict":"pass"}, "R2":{"verdict":"pass"}, "R3":{"verdict":"partial"},
                     "R4":{"verdict":"pass"}, "R5":{"verdict":"pass"}, "R6":{"verdict":"pass"},
                     "R7":{"verdict":"pass"}, "R8":{"verdict":"pass"}, "R9":{"verdict":"na"}},
          "fabrication_charges": [
             {"claim":"...", "cited_src":"src-004", "why_unsupported":"..."}
          ]},
    "B": {...}, "C": {...}, "D": {...}
  },
  "ranking": ["B","A","D","C"],
  "rationale": "one or two sentences, anchored to the rubric"
}
```

Judge independently. Do not hedge toward ties. Output only the JSON file.
