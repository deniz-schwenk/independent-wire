# Bias-stage judge rubric (transcribed from the production bias prompts)

Frozen before Phase-1 judging. Source of truth: `agents/bias_detector/
SYSTEM.md` + `INSTRUCTIONS.md` (the categories, the legitimate-practice
exclusions, the marks-not-rewrites stance) and TASK-BIAS-MODEL-EVAL.md
(judging weights). A judge sees only: the article body, one anonymized
bias output, and this rubric. The judge never sees the model name, never
sees another arm's output, and is told nothing about which arm is
incumbent/golden/candidate.

## What the stage is for (binding)

The Language Bias Analyzer **marks** how the published text is colored — it
records verbatim spans of linguistic bias and explains each. It **never
rewrites** the article (VISION Part 08). The value is a lean, precise,
trustworthy set of marks. **Over-flagging restrained prose is a rubric
FAILURE, not thoroughness**: flagging neutral or properly-attributed
language destroys the credibility the stage exists to protect.

## The six categories (a valid flag is exactly one of these, in the article's OWN voice)

- `evaluative_adjective` — severity/importance/quality words unattributed
  ("devastating", "landmark", "alarming", "historic", "controversial").
- `emotionalizing` — phrasing to evoke emotion over fact ("innocent
  civilians trapped", "heartbreaking scenes").
- `passive_obscuring` — passive that hides a KNOWN active agent ("mistakes
  were made" when the source identifies who acted).
- `loaded_term` — words carrying implicit judgment ("regime" vs
  "government", "forced to acknowledge" vs "acknowledged", "admitted" vs
  "stated").
- `hedging` — vague qualification weakening attribution ("some say", "it is
  believed", "reportedly") used to dodge commitment, not to signal real
  dispute.
- `intensifier` — amplifiers without informational backing ("extremely",
  "vastly", "overwhelmingly") when no data supports the magnitude.

## NOT bias — flagging any of these is a precision failure

- Standard attribution ("according to", "stated", "reported", "told
  reporters").
- Data-backed description ("significant increase" when a specific % is
  cited; "sharp decline" with the magnitude given).
- Genuinely uncertain language for verified uncertainty ("the death toll
  remains disputed" when sources actually disagree).
- Direct quotes from sources — evaluative language inside quotation marks is
  the source's, attributed, not the article's own voice.

## Scoring — three weighted criteria, 1–5 each

1. **Precision of flags (WEIGHT: highest).** Are the flagged spans genuine
   own-voice bias, or does the output flag attributed/neutral/data-backed
   language? A wrong flag is worse than a missed one. An output that flags
   restrained, properly-attributed prose scores LOW here no matter how many
   findings it has. Lean and correct beats plentiful.
2. **Category correctness.** Is each finding's `issue` the right one of the
   six? Is the verbatim `excerpt` actually own-voice (not inside a quote,
   not an attribution)?
3. **Explanation quality.** Does `explanation` name what the text *does*
   (the judgment it embeds, the attribution it lacks, the agent it
   obscures) — not merely restate the category? And is the `reader_note`
   two–three plain-language sentences about the text on the page, no
   internal jargon, no enumeration?

Report each 1–5 with a one-line justification citing a specific span. A
finding is only counted "charged" (a real defect) when the criterion is
low AND the judge cites the offending span — no uncited charges.

## Output (judge returns strict JSON)

```json
{
  "precision": {"score": 1-5, "cite": "<span or 'none'>", "why": "<=1 line"},
  "category":  {"score": 1-5, "cite": "<span or 'none'>", "why": "<=1 line"},
  "explanation": {"score": 1-5, "cite": "<span or 'none'>", "why": "<=1 line"},
  "overall": 1-5,
  "note": "<=1 line overall impression"
}
```
