# QA-stage model eval — GLM-5.2 shadow backfill (2026-07)

Anchor-free blind eval of a candidate QA-stage model (**GLM-5.2 @ reasoning
effort xhigh, fp8 via Baidu**) against the production incumbent
(**Sonnet 4.6, reasoning=none**) on 21 real production `qa_analyze` topics
backfilled from on-disk run state. Collection + shadow generation + judging were
all run 2026-07-02/03. The harness and raw corpus live untracked under
`scratch/qa-shadow/`; this document is the committed summary.

> **⚠️ Superseded — read the v2 section first.** The v1 result below used a
> **single** judge per topic (its own stated weakness). It has been superseded
> by a harder **v2 re-judge** (2026-07-03): a rubric derived from the production
> prompt, **3 independent judges per topic (majority)**, a **golden reference**
> as an anonymous third output, and claim-cited fabrication adjudication. The v2
> section (**"v2 — golden re-judge"**, at the end of this document) is
> authoritative. v1 is retained below as a superseded record; its direction
> (GLM ≫ incumbent) held and strengthened.

## v1 headline result (SUPERSEDED — see "v2 — golden re-judge" below)

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

---

# v2 — golden re-judge (authoritative, 2026-07-03)

The v1 pass used a **single** judge per topic — its own stated weakness,
especially for the fabrication tallies. v2 re-judges the **same 21 topics and
the same GLM/incumbent outputs** with a harder, higher-signal protocol. No new
model API calls — everything ran cost-neutral via spawned judge subagents.

## What changed vs v1

1. **Prompt-derived rubric (fixed before judging).** An explicit R1–R8 checklist
   transcribed from the production `qa_analyze` prompts (`agents/qa_analyze/`
   SYSTEM + INSTRUCTIONS) — problem detection, well-formed records, grounding /
   no-fabrication, corrections correspondence, corrected-article discipline,
   divergence reporting, precision/no-padding, back-reference & Wikipedia rules.
   Frozen at `scratch/qa-shadow/judging-v2/RUBRIC.md`.
2. **Golden reference as an anonymous third output.** One fresh subagent per
   topic executed the production QA task itself on the full reconstructed input
   with maximum care, producing a schema-valid **golden** output — a quality
   *ceiling* reference. Golden similarity is **never** a scoring criterion; it
   participates only as an anonymous third output.
3. **3 independent judges per topic (majority).** Each of 21 topics × 3 fresh
   judges received the topic input + sources + rubric + **three** anonymized,
   deep-key-normalized outputs (GLM / incumbent / golden; per-topic random label
   **and** random order; key file outside the judge tree). 21 × 3 = **63
   verdicts, 0 missing, 0 malformed.**
4. **Claim-cited fabrication adjudication.** A fabrication counts **only** when
   **≥2 of 3 judges** independently cite an overlapping claim against the same
   output (deterministic claim-overlap match in `aggregate_v2.py`). Every counted
   charge carries its verbatim claim citation.

Parent orchestrated only (prepared, spawned, collected, aggregated
mechanically); it formed no quality judgment of its own.

## v2 headline result

| Metric (3-judge majority, anchor-free vs rubric+sources) | GLM-5.2 @ xhigh | Incumbent Sonnet 4.6 | Golden (ceiling) |
|---|--:|--:|--:|
| Mean absolute correctness (1–5) | **4.16** | 2.59 | 4.02 |
| Rubric pass-rate (R1–R8; pass=1/partial=½/fail=0) | **0.97** | 0.64 | 0.97 |
| Confirmed fabrications — total (≥2/3 judges, cited) | **1** | 11 | 0 |
| Confirmed fabrications — topics with ≥1 | **1 / 21** | 10 / 21 | 0 / 21 |

Per-topic **majority pairwise**: **GLM > incumbent in 19 / 21** (incumbent wins
only case-02 and case-16); GLM vs golden **11 / 10** (a statistical tie); golden
> incumbent in 17 / 21.

Correctness distribution — GLM `{5:13, 4:47, 3:3}` (strikingly consistent);
incumbent `{4:5, 3:27, 2:31}`; golden `{5:24, 4:18, 3:19, 2:2}` (higher ceiling
but more variable). GLM's edge over golden in the mean is consistency: it almost
never drops below 4, while golden is more polarized.

**Reading:** under the harder protocol, GLM-5.2 @ xhigh performs **at the
golden-reference ceiling** (a Claude-Opus max-care QA pass) and **decisively
beats the production incumbent** — 19-2 pairwise, +1.6 mean correctness, and 11×
fewer confirmed fabrications. The direction of v1 held and *strengthened*: the
incumbent's mean fell from v1's 3.57 to 2.59 because the rubric-anchored 3-judge
panel is harsher on its two recurring failure modes (padding `problems_found`
with self-retracting non-findings, and asserting unsupported source content).

## Per-topic (un-anonymized; correctness = mean of 3 judges)

| case | date | topic | corr G / I / Gold | GLM vs inc | GLM vs golden |
|---|---|---|:-:|:-:|:-:|
| 01 | 2026-06-26 | topic-0 | 4.33 / 3.00 / 4.00 | GLM | GLM |
| 02 | 2026-06-26 | topic-1 | 4.00 / 3.67 / 3.00 | **inc** | GLM |
| 03 | 2026-06-26 | topic-2 | 4.33 / 2.00 / 4.33 | GLM | GLM |
| 04 | 2026-06-27 | topic-0 | 4.67 / 2.00 / 5.00 | GLM | gold |
| 05 | 2026-06-27 | topic-1 | 4.00 / 3.00 / 4.33 | GLM | gold |
| 06 | 2026-06-27 | topic-2 | 4.00 / 2.00 / 4.33 | GLM | gold |
| 07 | 2026-06-28 | topic-0 | 4.00 / 2.33 / 5.00 | GLM | gold |
| 08 | 2026-06-28 | topic-1 | 4.00 / 2.00 / 4.00 | GLM | GLM |
| 09 | 2026-06-28 | topic-2 | 5.00 / 2.00 / 5.00 | GLM | GLM |
| 10 | 2026-06-29 | topic-0 | 4.00 / 2.00 / 5.00 | GLM | gold |
| 11 | 2026-06-29 | topic-1 | 4.00 / 2.33 / 4.33 | GLM | gold |
| 12 | 2026-06-29 | topic-2 | 3.67 / 3.00 / 4.67 | GLM | gold |
| 13 | 2026-06-30 | topic-0 | 4.00 / 2.00 / 3.33 | GLM | GLM |
| 14 | 2026-06-30 | topic-1 | 3.67 / 2.67 / 4.67 | GLM | gold |
| 15 | 2026-06-30 | topic-2 | 4.00 / 3.00 / 5.00 | GLM | gold |
| 16 | 2026-07-01 | topic-0 | 4.00 / 4.00 / 3.00 | **inc** | GLM |
| 17 | 2026-07-01 | topic-1 | 4.00 / 3.00 / 3.00 | GLM | GLM |
| 18 | 2026-07-01 | topic-2 | 4.33 / 3.00 / 3.00 | GLM | GLM |
| 19 | 2026-07-02 | topic-0 | 3.67 / 2.00 / 4.00 | GLM | gold |
| 20 | 2026-07-02 | topic-1 | 4.67 / 3.00 / 2.33 | GLM | GLM |
| 21 | 2026-07-02 | topic-2 | 5.00 / 2.33 / 3.00 | GLM | GLM |

## Adjudicated fabrications (each ≥2/3 judges, with claim citation)

**Incumbent: 11 confirmed across 10 topics.** Representative:

- **case-02 (3/3 judges):** the incumbent asserts *"src-006 and src-004 report
  three reactors shut down at Bugey, Nogent-sur-Seine, and Golfech."* src-004's
  dossier entry says EDF announced *"the shutdown of three reactors at the
  Nogent-sur-Seine nuclear power plant"* — three reactors at **one** plant, not
  three plants.
- **case-08 (2/3 judges):** the incumbent's retraction claims *"the article does
  not assign her a title at all."* The article text under QA reads *"President
  Claudia Sheinbaum …"*, and src-018 assigns her *"Head of Government of Mexico
  City"* — the retraction misdescribes the article to dismiss a real title error.

**GLM: 1 confirmed (case-19, 3/3 judges):** GLM asserts *"src-004 specifies
'Cabo San Lucas, Baja California Sur.'"* src-004's summary names only *"Cabo San
Lucas"* with no state — GLM attributed a state string the source does not
contain.

**Golden: 0 confirmed.**

## v2 caveats

- **Golden is Claude-family, and so are the judges.** Two of the three outputs
  (incumbent = Sonnet 4.6, golden = a Claude subagent) share lineage; only GLM
  is off-family. Anonymization normalizes structure and strips metadata but not
  writing style — a residual stylistic-familiarity bias toward the two
  Claude-family outputs cannot be excluded. If anything this biases *against* the
  GLM result, which still wins.
- **Sources are dossier summaries, not full article bodies** (as in v1) — a judge
  cannot catch a fabrication that is plausible against the summary but false
  against the full source. Same standard applied to all three outputs and to the
  production QA stage itself.
- **Still N=21, 7 consecutive days.** No seasonal/topic-mix diversity beyond that
  window.
- **Not a cutover decision by itself.** This is a strong, harder-protocol
  decision input; a swap remains gated on latency (xhigh ~7 min/topic; see
  above) and the provider work in `docs/GLM-PROVIDER-VERIFICATION-2026-07.md`.

## v2 reproduction

All under `scratch/qa-shadow/` (untracked); raw v2 verdicts under
`scratch/qa-shadow/judging-v2/`:

```bash
.venv/bin/python scratch/qa-shadow/jv2_setup.py          # isolated golden inputs + case index
# spawn one golden subagent per case (GOLDEN-TASK.md) -> golden/case-NN.json
.venv/bin/python scratch/qa-shadow/jv2_validate.py       # golden schema check
.venv/bin/python scratch/qa-shadow/prep_judge_v2.py      # 3-way anonymized packets + key (outside judge tree)
# spawn 3 judge subagents per case (JUDGE-TASK-V2.md + RUBRIC.md) -> verdict-{1,2,3}.json
.venv/bin/python scratch/qa-shadow/jv2_check_verdicts.py # 63/63 present + valid
.venv/bin/python scratch/qa-shadow/aggregate_v2.py       # majority pairwise, means, adjudicated fabrications
```

Artifacts: `judging-v2/RUBRIC.md`, `judging-v2/golden/case-NN.json`,
`judging-v2/judge/case-NN/packet.json` + `verdict-{1,2,3}.json`,
`judging-v2/_judge_key_v2.json` (label→model, outside the judge tree),
`judging-v2/aggregate_v2_summary.json` (full per-case detail + every confirmed
fabrication with its judge citations).
