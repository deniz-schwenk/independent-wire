# QA-stage model eval — GLM-5.2 shadow backfill (2026-07)

Anchor-free blind eval of a candidate QA-stage model (**GLM-5.2 @ reasoning
effort xhigh, fp8 via Baidu**) against the production incumbent
(**Sonnet 4.6, reasoning=none**) on 21 real production `qa_analyze` topics
backfilled from on-disk run state. Collection + shadow generation + judging were
all run 2026-07-02/03. The harness and raw corpus live untracked under
`scratch/qa-shadow/`; this document is the committed summary.

## Headline result

On a blind, per-topic panel (one fresh judge subagent per topic, anchored only
to the article + its sources, blind to which model produced which output):

| Metric | GLM-5.2 @ xhigh | Incumbent Sonnet 4.6 |
|---|--:|--:|
| Mean absolute correctness (1–5) | **4.57** | 3.57 |
| Fabrications — total | **2** | 15 |
| Fabrications — topics with ≥1 | **2 / 21** | 10 / 21 |
| Pairwise wins | **13** | 7 |
| Pairwise ties | 1 | 1 |
| **Pairwise win-or-tie** | **14 / 21** | 8 / 21 |

The candidate scored higher on absolute correctness and produced far fewer
fabrications across the panel. The recurring judge rationale (verbatim in
`scratch/qa-shadow/aggregate_summary.json`) is that the weaker output in a pair
tended to **pad `problems_found` with self-retracting non-findings** and
occasionally assert unsupported source content, while the stronger output was
"lean and precise." This document reports the panel's aggregated verdicts; it
does not add an independent quality judgment.

> **Caveat — this is not a cutover recommendation.** N=21 over 7 consecutive
> days, a single judge per topic (no multi-vote adversarial verification), and a
> LLM judge panel that is itself fallible. Latency is a hard operational
> concern (see below). Treat this as a decision input, not a decision.

## What was collected

The collector reconstructs the exact `qa_analyze` input per topic from
`output/{date}/_state/run-*/topic_buses.QaAnalyzeStage.{n}.json` — the article
under QA, its `final_sources`, `merged_preliminary_divergences`,
`perspective_clusters_synced`, and `perspective_missing_positions` — and pairs
it with the incumbent's production QA output from the same snapshot plus the
per-topic cost/tokens from `run_stage_log.jsonl`.

- **All 37 reconstructable run days (112 topics) reconstructed, 0 skipped** —
  every day's on-disk state was sufficient for byte-faithful input recovery.
- **Shadow outputs generated for the most recent 7 days (2026-06-26 … 2026-07-02,
  21 topics)** — the judged set. 21/21 shadow calls succeeded, all served by
  Baidu, all schema-valid, 0 transient retries.

## Shadow configuration

Held **identical** to production `qa_analyze`: the two prompts
(`agents/qa_analyze/SYSTEM.md` + `INSTRUCTIONS.md`, read as-is), the strict
`QA_ANALYZE_SCHEMA`, `temperature=0.1`, and the reconstructed input. The shadow
Agent reuses the production message-assembly path, so the wire prompt is built
by the same code, not re-implemented. Three eval variables differ:

| | Incumbent | Candidate |
|---|---|---|
| model | `anthropic/claude-sonnet-4.6` | `z-ai/glm-5.2` |
| reasoning | `none` | `effort: xhigh` |
| provider routing | default | Baidu **fp8**, `allow_fallbacks:false` (fail-loud, reuses the `provider_routing` from commit `b1edb22`) |

### One documented deviation: `max_tokens` 64000 → 131072

Production `qa_analyze` uses `max_tokens=64000`, a budget sized for a
*non-reasoning* incumbent whose answer is a few thousand tokens. At
`effort: xhigh` the reasoning trace alone can exceed 64000 completion tokens on
large topics — the first probe (2026-07-02, topic with 19 sources / 82 KB input)
consumed the entire 64000 cap and truncated to **zero parseable output**. A
diagnostic at the Baidu endpoint's `max_completion_tokens` (131072) produced a
clean `finish_reason: stop` with valid JSON (reasoning ≈ 10.9k tokens on a small
topic). `max_tokens` is neither the input, the schema, nor one of the three eval
variables, so it was raised to 131072 to give xhigh the headroom it structurally
requires. This does not bias the comparison: 64000 was never binding for the
incumbent. All 21 judged topics completed cleanly at 131072 (largest: ~20 min,
$0.43).

### Cost & latency (measured, 21 topics)

| | GLM-5.2 @ xhigh | Incumbent Sonnet 4.6 |
|---|--:|--:|
| Total spend (21 topics) | $3.38 | $2.93 |
| Mean cost / topic | $0.161 | $0.140 |
| Mean latency / topic | **442 s** (~7.4 min; range ~3.5–20.7 min) | seconds (no reasoning) |

Cost is comparable; **latency is the operational cost of the candidate** — a
daily 3-topic shadow is ~20–40 min, and full-history backfill at xhigh is
impractical (112 topics ≈ many hours). This is inherent to xhigh reasoning on
the large QA inputs and was the dominant practical finding of the run.

## Judging protocol (blind, anchor-free, leak-proof)

The parent process orchestrated only — it prepared material, spawned **one fresh
subagent per topic**, and mechanically aggregated the returned verdicts. It did
not judge or summarize output quality itself.

1. **Deterministic anonymization (by script).** Per topic, the two outputs were
   randomly assigned to labels **A/B** (seeded RNG; GLM landed as A in 8 cases,
   B in 13). The label→model mapping was written to `scratch/qa-shadow/_judge_key.json`,
   **outside** the judge tree, and no subagent was ever pointed at it.
2. **Leak-proofing.** Both outputs were **deeply key-normalized to one canonical
   shape** — erasing structural tells (the incumbent snapshot uses
   `qa_problems_found` / `qa_corrected_article`; the shadow uses `problems_found`
   / `article`) — and **all** eval metadata (latency, tokens, cost, provider,
   reasoning traces, model names, filenames) was stripped. A judge received
   exactly: the topic input + sources + `output_A` + `output_B`.
3. **Neutral prompts.** Judge prompts contained no parent observations (nothing
   about truncation, `max_tokens`, providers, or which model was under test).
   Each judge scored anchor-free against the article + sources: absolute
   correctness (1–5) per output, fabrication count per output, and a pairwise
   verdict (A / B / tie).

Verdicts were un-anonymized via the key and aggregated arithmetically
(`aggregate.py`): 21/21 verdicts returned, 0 missing, 0 malformed.

## Per-topic results (un-anonymized)

Correctness = (GLM / incumbent); fabrications = (GLM / incumbent); winner =
pairwise verdict.

| case | date | topic | correctness G/I | fabrications G/I | winner |
|---|---|---|:-:|:-:|:-:|
| 01 | 2026-06-26 | topic-0 | 4 / 4 | 0 / 0 | GLM |
| 02 | 2026-06-26 | topic-1 | 4 / 4 | 0 / 1 | incumbent |
| 03 | 2026-06-26 | topic-2 | 5 / 3 | 0 / 0 | GLM |
| 04 | 2026-06-27 | topic-0 | 5 / 2 | 0 / 1 | GLM |
| 05 | 2026-06-27 | topic-1 | 4 / 4 | 0 / 2 | incumbent |
| 06 | 2026-06-27 | topic-2 | 5 / 4 | 0 / 0 | GLM |
| 07 | 2026-06-28 | topic-0 | 5 / 4 | 0 / 0 | GLM |
| 08 | 2026-06-28 | topic-1 | 5 / 3 | 0 / 2 | GLM |
| 09 | 2026-06-28 | topic-2 | 3 / 4 | 1 / 1 | incumbent |
| 10 | 2026-06-29 | topic-0 | 5 / 3 | 0 / 2 | GLM |
| 11 | 2026-06-29 | topic-1 | 5 / 3 | 0 / 2 | GLM |
| 12 | 2026-06-29 | topic-2 | 5 / 4 | 0 / 0 | GLM |
| 13 | 2026-06-30 | topic-0 | 5 / 3 | 0 / 0 | GLM |
| 14 | 2026-06-30 | topic-1 | 4 / 4 | 0 / 0 | incumbent |
| 15 | 2026-06-30 | topic-2 | 4 / 4 | 0 / 0 | incumbent |
| 16 | 2026-07-01 | topic-0 | 3 / 5 | 1 / 0 | incumbent |
| 17 | 2026-07-01 | topic-1 | 5 / 3 | 0 / 2 | GLM |
| 18 | 2026-07-01 | topic-2 | 5 / 4 | 0 / 1 | incumbent |
| 19 | 2026-07-02 | topic-0 | 5 / 2 | 0 / 1 | GLM |
| 20 | 2026-07-02 | topic-1 | 5 / 4 | 0 / 0 | tie |
| 21 | 2026-07-02 | topic-2 | 5 / 4 | 0 / 0 | GLM |

Correctness distribution — GLM: {5:14, 4:5, 3:2}; incumbent: {5:1, 4:12, 3:6, 2:2}.
The incumbent's two `incumbent_win` cases with a fabrication charge against GLM
(case-09, case-16) are the only topics where GLM scored below 4.

## Caveats & limitations

- **N=21, 7 consecutive days.** No seasonal/topic-mix diversity beyond that
  window; the earlier 30 reconstructable days were collected but not shadow-run
  (xhigh latency makes full backfill impractical).
- **Single judge per topic.** No multi-vote / adversarial-refutation pass; a
  more robust protocol would run ≥3 independent judges per topic and require a
  majority. The fabrication counts in particular are one judge's tally.
- **LLM-judge fallibility.** The panel judges against the provided sources'
  *summaries*, not the full fetched article bodies; a judge cannot detect a
  fabrication that is plausible against the summary but false against the full
  source.
- **Latency.** xhigh at ~7 min/topic average (20 min tail) is a real operational
  constraint, unaddressed here.
- **Style is not stripped.** Anonymization removes metadata and structural tells,
  not writing style; a judge cannot be blind to stylistic differences that
  correlate with model identity.

## Reproduction

All under `scratch/qa-shadow/` (untracked):

```bash
.venv/bin/python scratch/qa-shadow/collect.py --all          # reconstruct inputs (free)
.venv/bin/python scratch/qa-shadow/shadow.py  --recent 7 --concurrency 4   # GLM shadow outputs
.venv/bin/python scratch/qa-shadow/report.py                 # backfill report
.venv/bin/python scratch/qa-shadow/prep_judge.py             # anonymized judge packets + key
# spawn one judge subagent per case-NN (neutral anchor-free prompt) -> verdict.json
.venv/bin/python scratch/qa-shadow/aggregate.py              # un-anonymize + aggregate
```

Raw artifacts: per-topic `input.json` / `incumbent_output.json` /
`shadow_output.json` / `shadow_meta.json`, judge `case-NN/packet.json` +
`verdict.json`, `_judge_key.json`, `aggregate_summary.json`. The daily
going-forward command is documented in `scratch/qa-shadow/README.md`.
