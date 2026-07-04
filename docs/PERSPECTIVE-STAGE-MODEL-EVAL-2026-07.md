# Perspective-stage model eval (2026-07) — 5-arm blind eval on 21 production topics

Blind, rubric-anchored, 5-arm eval of three candidate perspective-stage models
against the production incumbent (+ an Opus-4.8 golden ceiling) on **21 real
production `perspective` topics** reconstructed byte-faithfully from on-disk
TopicBus state. Same playbook as the writer/editor evals
(`docs/WRITER-STAGE-MODEL-EVAL-2026-07.md`, `docs/EDITOR-STAGE-MODEL-EVAL-2026-07.md`
— protocol discipline binding), with the provider pins from
`docs/GLM-PROVIDER-VERIFICATION-2026-07.md` and `docs/DEEPSEEK-FP8-PIN-2026-07.md`.
Reconstruction, paid shadow, golden generation, deterministic scoring, and the
3-judge blind panels all ran 2026-07-04. The harness + raw corpus live untracked
under `scratch/perspective-eval/`; this document is the committed summary.

> **This is a decision input, not a cutover decision.** N=21 over 7 consecutive
> days; LLM-judge panels are fallible; correctness/charges are adjudicated
> against dossier *summaries*, not full source bodies (see caveats). The
> perspective spectrum IS the product (VISION Part 07) — invented positions or
> attributions are the product-critical failure mode, so the deterministic
> actor-existence gate and the judges' claim-cited charge rule both target it.

## Arms & operating points

| arm | model | reasoning | temp | max_tokens | routing |
|---|---|---|---|--:|---|
| **incumbent** | `anthropic/claude-opus-4.6` | none | 0.1 | (prod) | default |
| **GLM-5.2** | `z-ai/glm-5.2` | effort **xhigh** | 0.1 | 120000 | fp8 pin `[baidu, ambient, venice]`, `allow_fallbacks:false` |
| **DeepSeek V4 Pro** | `deepseek/deepseek-v4-pro` | effort **xhigh** | 0.1 | 120000 | fp8 pin `[baidu, wandb, parasail]`, `allow_fallbacks:false` |
| **Sonnet-5** | `anthropic/claude-sonnet-5` | `{enabled:true, effort:high}` | — (omitted) | 64000 | default (Azure) |
| **golden** | Opus-4.8 subagent, max care | — | — | — | ceiling reference, cost-neutral |

Prompts held **identical** to production `perspective` for every arm
(`agents/perspective/SYSTEM.md` + `INSTRUCTIONS.md`, the strict `PERSPECTIVE_SCHEMA`,
and the reconstructed 8-key context), assembled through the production `Agent`
message path — not re-implemented. Only the eval variables differ (model /
reasoning / routing / max_tokens). GLM & DeepSeek temperatures are held at
production's **0.1**; Sonnet-5 sends no temperature (the 5-family rejects
non-default temperature). Perspective prompts last changed **2026-05-11**
(`bdcadff`) — before the eval window — so the current files reconstruct every
sampled topic byte-faithfully. DeepSeek carried the brief's **early gate**: after
the first 6 topics, drop the arm if first-attempt schema-validity < 50%.

## Phase 1 — reconstruction (coverage)

The perspective agent runs once per topic; its whole input is the read-slots
`editor_selected_topic`, `final_sources`, the three `canonical_actors_*` pools,
`merged_preliminary_divergences`, and `merged_coverage_gaps`, all frozen in each
topic's `topic_buses.PerspectiveStage.{n}.json` snapshot exactly as the agent read
them (PerspectiveStage only *writes* `perspective_clusters` +
`perspective_missing_positions`). The reconstructed `agent.run(message,
context=...)` call is byte-identical to `PerspectiveStage.__call__`: the verbatim
message ("Identify the position clusters in this dossier. Map missing voices the
dossier could not source.") and the 8-key context in production key order.

**Coverage: 21 / 21 topics reconstructed** across the 7 most-recent days
(**2026-06-28 … 2026-07-04**, 3 topics/day), floor 15 → MET, **0 field-leaks** (a
per-topic allow-list self-check confirms only the 8 production keys reach the
agent), **6 follow-up topics**. Context wire size min 21 KB / median 48 KB / max
105 KB — 2–4× the writer/editor inputs (26 sources median; up to 34 sources / 62
canonical actors on the largest topic). The incumbent output + per-topic
cost/tokens come from the same snapshot + `run_stage_log.jsonl`.

## Phase 2 + provider verification — probe & paid shadow

Before spend, each pinned provider was probed once under the real
`PERSPECTIVE_SCHEMA` on a representative topic (2026-06-29/topic-0). **All six fp8
pins + Sonnet-5 returned schema-valid JSON:**

| arm | provider(s) | strict schema | probe $ | probe latency |
|---|---|---|--:|--:|
| GLM-5.2 | **Baidu** ✓ / Ambient ✓ / Venice ✓ | clean JSON | 0.068 / 0.031 / 0.045 | 167 / 239 / 85 s |
| DeepSeek V4 Pro | **Baidu** ✓ / WandB ✓ / Parasail ✓ | clean JSON | 0.034 / 0.077 / 0.083 | 324 / 423 / 668 s |
| Sonnet-5 | Azure ✓ | clean JSON | 0.084 | 70 s |

Notably, DeepSeek/WandB — which returned empty output under the *editor* schema —
returned clean JSON here; DeepSeek latency is high (324–668 s even on the smallest
topic). **Printed cost projection before the paid phase:** point estimate **$7.05**
/ input-scaled **$15.84** (the input-scaled figure exceeded the $10 cap, driven
almost entirely by DeepSeek's 2.5× retry multiplier and input-scaling — a
worst-case that the early gate and DeepSeek's actual reliability made moot).
**Actual paid spend: probe $0.42 + shadow $5.97 = $6.39 / $10 cap.**

## Reliability — the headline reversal from the editor eval

The editor eval found GLM (55 %) and DeepSeek (23 %) intermittently emit
`structured=None` under a strict schema at xhigh. **That fragility does not appear
on the perspective schema.** The perspective output is large and richly structured
(clusters + actor sub-lists + missing positions), and every arm was essentially
100 % reliable:

| arm | first-attempt valid / 21 | final valid / 21 | provider | mean latency |
|---|---|---|---|---|
| Incumbent (Opus-4.6) | 21 / 21 | 21 / 21 | prod | (not logged) |
| Golden (Opus-4.8) | 21 / 21 | 21 / 21 | subagent | — |
| **Sonnet-5** | **21 / 21** | 21 / 21 | Azure | **103 s** |
| **GLM-5.2** (xhigh) | **20 / 21** | 21 / 21 | Baidu | 217 s |
| **DeepSeek V4 Pro** (xhigh) | **21 / 21** | 21 / 21 | Baidu | 226 s |

**DeepSeek passed the early gate 6 / 6 (100 %)** and ran the full 21; it was *not*
dropped. GLM's single first-attempt miss recovered on attempt 2. **Reliability is
therefore not a differentiator on this stage** — unlike the editor stage, where it
was decisive. The differentiator is entirely *quality of the perspective spectrum*.

## Phase 3 — deterministic layer

Computed in Python (never delegated to an LLM): schema validity, `src-NNN`
resolution against the topic's `final_sources`, the **actor-existence gate** (every
`actor-NNN` in a cluster's stated/reported/mentioned resolves to a canonical actor,
and its name is normalized/fuzzy-matchable in the source texts), cluster-structure
integrity, and coverage stats.

| arm | schema | invented src | invented actor | name-unmatched | **fabrication** | disjoint viol. | src cov. | actor cov. | clusters | missing pos. |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| incumbent | 21/21 | 0 | 0 | 0 | **0** | **34** | 0.897 | 0.901 | 8.33 | 5.00 |
| glm | 21/21 | 0 | 0 | 0 | **0** | 2 | 0.960 | 0.900 | 7.43 | 4.62 |
| deepseek | 21/21 | 0 | 0 | 0 | **0** | 0 | 0.901 | **0.825** | **5.90** | 4.67 |
| sonnet5 | 21/21 | 0 | 0 | 0 | **0** | 15 | 0.963 | 0.915 | **11.0** | 4.90 |
| golden | 21/21 | 0 | 0 | 0 | **0** | 6 | 0.928 | 0.942 | 9.76 | 4.67 |

**The product-critical fabrication gate is clean for every arm — 0 invented
source ids, 0 fabricated/unresolvable actor references, 0 actor names unmatched in
the sources, including GLM.** GLM-5's historic actor-fabrication does not
materialize under this ID-referenced schema. The valid outputs separate on
**shape**, not integrity:

- **Cluster granularity** is the sharpest split: DeepSeek is the most parsimonious
  (5.9 clusters/topic), Sonnet-5 the most granular (11.0), incumbent 8.3, golden
  9.8. On the largest dossiers golden/Sonnet-5 went to 14–19 clusters.
- **Actor coverage**: DeepSeek assigns the fewest actors (0.825) — it leaves more
  of the dossier's actor population unplaced. All others 0.90–0.94.
- **Pool discipline (disjoint sub-lists per cluster)**: the **incumbent is the
  worst offender (34 violations)** — it routinely lists the same actor in
  stated+reported (or all three) sub-lists of one cluster, against the schema's
  "at most one sub-list per cluster" rule; Sonnet-5 15, golden 6, GLM 2, DeepSeek
  0. A minor structural-discipline metric (the downstream union collapses it), not
  fabrication.

## Phase 4 — blind 3-judge panels (Opus 4.8)

Each topic's five arm outputs were canonicalized to the bare `PERSPECTIVE_SCHEMA`
shape (all metadata stripped — structure is not a tell), assigned per-topic random
labels A–E via a seeded permutation, with the label→arm key sealed **outside** the
judge tree (`_judge_key.json`). Each of 3 fresh judges per topic saw the topic +
full sources + the three actor pools + the fixed R1–R9 rubric (transcribed from the
perspective prompts before judging) + the five anonymized, order-randomized
outputs, and returned per-output correctness (1–5), R1–R9 verdicts, claim-cited
invented-position/attribution charges, and a strict A–E ranking. **Judges ran on
Opus 4.8** (the strongest available subagent — the editor eval's Sonnet-4.6 panel
is the documented weaker counter-example; blindness is the family-bias mitigation).
**21 × 3 = 63 verdicts, 0 missing.** Blindness verified: the only banned-word
matches in the packets were topic content ("golden passport scheme"), never arm
labels; the label map is well-shuffled.

### Headline result (21 topics, 63 verdicts, all 5-way)

| metric | incumbent (Opus 4.6) | **Sonnet-5** | GLM-5.2 @ xhigh | DeepSeek V4 Pro | golden (Opus 4.8) |
|---|--:|--:|--:|--:|--:|
| Mean absolute correctness (1–5) | 3.75 | **4.29** | 3.62 | 2.83 | 4.51 |
| Rubric pass-rate (R1–R9) | 0.899 | **0.938** | 0.874 | 0.756 | 0.965 |
| Mean rank (↓, of 5) | 3.10 | **1.98** | 3.43 | 4.81 | 1.68 |
| Confirmed charges (≥2/3, cited) | 5 | **2** | 3 | 7 | 1 |
| Deterministic fabrication | 0 | 0 | 0 | 0 | 0 |
| $/topic | 0.136 | 0.157 | **0.049**¹ | **0.034** | — |

Overall order: **golden › Sonnet-5 › incumbent › GLM-5.2 › DeepSeek**.
¹ GLM realized $0.093/topic here (larger perspective input than the writer stage).

**Per-topic wins (highest mean correctness):** golden 9, **Sonnet-5 8**, incumbent
2, GLM 1, DeepSeek 0. Sonnet-5 never scored below 3.0; DeepSeek never above 4.0.

### Head-to-head majority pairwise (of 21 topics)

| pair | winner tally |
|---|---|
| Sonnet-5 vs incumbent | **Sonnet-5 19 – 2** |
| Sonnet-5 vs GLM | **Sonnet-5 16 – 5** |
| Sonnet-5 vs golden | golden 12 – 9 |
| incumbent vs GLM | **incumbent 14 – 7** |
| GLM vs DeepSeek | GLM 18 – 3 |
| golden vs everyone | 21–0 (DS), 19–2 (GLM), 18–3 (inc), 12–9 (Son) |

**Sonnet-5 beats the incumbent decisively (19–2) and GLM (16–5), and takes 9 of 21
even against the Opus-4.8 golden ceiling** — the strongest a deployable challenger
has looked in this eval family. **GLM sits *below* the incumbent (loses 14–7)** —
the reverse of the writer and QA evals, where GLM won.

### Rubric pass-rate by criterion (why the ordering holds)

| arm | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| incumbent | 0.85 | 1.00 | 1.00 | 0.92 | 0.68 | 0.88 | 0.95 | 0.98 | 0.82 |
| **Sonnet-5** | **0.98** | 1.00 | 1.00 | 0.91 | 0.84 | 0.76 | 0.99 | 1.00 | **0.95** |
| GLM-5.2 | 0.75 | 0.99 | 1.00 | 0.94 | 0.73 | 0.77 | 1.00 | 0.99 | 0.69 |
| DeepSeek | **0.52** | 1.00 | 0.98 | 0.90 | **0.45** | **0.51** | 0.96 | 1.00 | **0.49** |
| golden | 0.98 | 1.00 | 1.00 | 0.98 | 0.91 | 0.91 | 0.99 | 1.00 | 0.91 |

(R1 cluster-by-substance, R2 grounding, R3 citation discipline, R4 equal weight,
R5 actor-assignment correctness, R6 granularity, R7 missing-perspective
specificity, R8 own-words discipline, R9 spectrum fidelity.)

The three criteria that ARE the product — **R1 (substance clustering), R5 (actor
assignment), R9 (spectrum fidelity)** — drive everything:

- **DeepSeek collapses the spectrum.** R1 0.52 / R5 0.45 / R6 0.51 / R9 0.49: it
  merges opposing positions into single clusters and drops real positions
  (parsimony of 5.9 clusters is a defect here, not restraint). For a stage whose
  whole product is the perspective spectrum, this is disqualifying on quality.
- **GLM trails the incumbent exactly where it matters.** R9 0.69 (vs incumbent
  0.82) and R1 0.75 (vs 0.85): it drops or under-separates positions the dossier
  supports. GLM's grounding (R2 0.99) and citation discipline (R3 1.00) are clean —
  its weakness is spectrum completeness, the opposite of the writer stage where its
  consistency won.
- **Sonnet-5 leads on the product core** (R1 0.98, R9 0.95), essentially matching
  golden; its only relative soft spot is R6 (0.76 — its 11-cluster granularity is
  occasionally over-split).

### Per-topic (un-anonymised; correctness = mean of 3 judges)

| case | FU | inc | GLM | DS | Son | gold |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| 2026-06-28/topic-0 | Y | 4.3 | 3.0 | 4.0 | 4.3 | 4.0 |
| 2026-06-28/topic-1 |  | 3.7 | 4.0 | 3.0 | 4.3 | 5.0 |
| 2026-06-28/topic-2 |  | 4.0 | 4.3 | 2.7 | 4.7 | 5.0 |
| 2026-06-29/topic-0 |  | 3.3 | 3.3 | 2.7 | 4.3 | 4.0 |
| 2026-06-29/topic-1 | Y | 3.7 | 3.3 | 2.7 | 4.0 | 5.0 |
| 2026-06-29/topic-2 |  | 4.0 | 3.7 | 3.0 | 3.7 | 5.0 |
| 2026-06-30/topic-0 |  | 3.3 | 4.0 | 2.7 | 3.3 | 4.7 |
| 2026-06-30/topic-1 |  | 4.0 | 3.7 | 3.0 | 4.7 | 4.3 |
| 2026-06-30/topic-2 |  | 2.7 | 3.7 | 2.0 | 4.0 | 3.3 |
| 2026-07-01/topic-0 |  | 5.0 | 4.0 | 2.7 | 3.0 | 4.7 |
| 2026-07-01/topic-1 |  | 3.7 | 3.3 | 2.0 | 4.3 | 4.0 |
| 2026-07-01/topic-2 | Y | 4.0 | 4.0 | 3.0 | 4.0 | 4.7 |
| 2026-07-02/topic-0 |  | 3.7 | 3.3 | 2.3 | 5.0 | 4.7 |
| 2026-07-02/topic-1 |  | 4.7 | 4.0 | 2.7 | 4.7 | 4.3 |
| 2026-07-02/topic-2 | Y | 4.0 | 3.7 | 2.7 | 5.0 | 4.7 |
| 2026-07-03/topic-0 | Y | 3.3 | 4.7 | 3.0 | 4.7 | 4.0 |
| 2026-07-03/topic-1 |  | 4.0 | 2.7 | 3.3 | 5.0 | 4.7 |
| 2026-07-03/topic-2 |  | 4.0 | 3.3 | 3.3 | 4.0 | 5.0 |
| 2026-07-04/topic-0 | Y | 2.3 | 3.0 | 3.0 | 4.0 | 4.3 |
| 2026-07-04/topic-1 |  | 3.0 | 3.0 | 2.7 | 4.3 | 4.3 |
| 2026-07-04/topic-2 |  | 4.0 | 4.0 | 3.0 | 4.7 | 5.0 |
| **mean** |  | **3.75** | **3.62** | **2.83** | **4.29** | **4.51** |

GLM wins exactly one topic (2026-07-03/topic-0, its only 4.7); DeepSeek wins none
and tops out at 4.0. Sonnet-5's floor is 3.0, its worst two topics being the two
where the incumbent peaked (2026-06-30/topic-0, 2026-07-01/topic-0).

### Adjudicated charges

Confirmed only when ≥2 of 3 judges independently cite the same instance
(claim-overlap clustering), each with its citations in `aggregate_summary.json`:
DeepSeek 7 · incumbent 5 · GLM 3 · Sonnet-5 2 · golden 1. **Sonnet-5 has the fewest
charges among deployable arms**, near the golden floor. The charges are minor
misattributions / dropped-position claims (e.g. a Mitsotakis "seek-exemption"
misattribution confirmed against DeepSeek's and GLM's 2026-07-04/topic-1 outputs),
not invented actors — consistent with the deterministic layer's 0 fabrications.

## Cost & latency (measured, 21 topics)

| arm | total spend | mean $/topic | mean latency | max latency | served |
|---|--:|--:|--:|--:|---|
| incumbent (Opus 4.6) | $2.86 | $0.136 | (not logged) | — | Anthropic |
| **Sonnet-5** | $3.29 | $0.157 | **103 s** | 231 s | Azure (21/21) |
| GLM-5.2 @ xhigh | $1.96 | $0.093 | 217 s | 388 s | Baidu (21/21) |
| DeepSeek V4 Pro | $0.72 | **$0.034** | 226 s | 326 s | Baidu (21/21) |
| golden | cost-neutral | — | ~55–200 s | — | — |

DeepSeek is the cheapest (~4× under the incumbent) and Sonnet-5 the most expensive
and the fastest challenger. Cost is inversely correlated with quality here: the
cheapest arm (DeepSeek) is the worst, and the best deployable arm (Sonnet-5) is the
priciest but still only ~1.15× the incumbent.

## Decision reading (input, not a cutover)

1. **Sonnet-5 — the standout challenger.** The only arm that clearly *beats* the
   incumbent (correctness 4.29 vs 3.75, rubric 0.938 vs 0.899, pairwise 19–2), it
   also beats GLM 16–5, approaches the Opus-4.8 golden ceiling (9/21), is fully
   reliable (21/21 first-attempt), is the fastest challenger (~103 s), and carries
   the fewest charges of any deployable arm. Cost is its only downside (~1.15× the
   incumbent). It leads precisely on the product-defining criteria (R1 substance
   clustering 0.98, R9 spectrum fidelity 0.95).

2. **GLM-5.2 — a regression on this stage.** GLM loses to the incumbent (14–7,
   correctness 3.62 vs 3.75, rubric 0.874 vs 0.899) because it under-separates and
   drops positions (R1 0.75, R9 0.69). This is the **opposite** of the writer and
   QA evals, where GLM won — a clean demonstration that model fit is stage-specific
   (it echoes the bias-language finding that GLM is weaker on
   perspective/balance-type judgment). Cheapest deployable-quality challenger, but
   not a quality win here.

3. **DeepSeek V4 Pro — out on quality.** Fully reliable this time (gate 6/6, 21/21)
   and the cheapest arm, but it collapses the perspective spectrum (last on
   correctness 2.83, rubric 0.756, mean rank 4.81, loses ~20–1 to every other arm;
   R1/R5/R9 all ≈0.5) and carries the most charges. Reliability and price cannot
   offset a product that drops the positions it exists to surface.

4. **Incumbent Opus-4.6 — reliable and mid-pack.** Beats GLM and DeepSeek but is
   clearly bettered by Sonnet-5. Its one deterministic wart is pool-discipline (34
   disjoint violations). Staying put is the zero-risk status quo; Sonnet-5 is the
   defensible improvement.

**Recommendation (decision input): the perspective stage's strongest candidate is
Sonnet-5**, not GLM — the reverse of the writer/QA swaps. A swap would be a
separate task (mirroring the writer/QA/editor swap pattern) and would additionally
weigh the transparency-chain interaction (perspective feeds the writer[GLM-5.2] →
QA[GLM-5.2] chain) and a longer confirmation window. **GLM is not an upgrade here;
DeepSeek is out.**

## Caveats & limitations

- **N=21, 7 consecutive days.** No seasonal/topic-mix diversity beyond the window;
  6 follow-ups included (the perspective stage has no follow-up-specific path, so
  they are structurally ordinary topics).
- **Claude-family judges over a Claude-heavy field.** The Opus-4.8 judges share a
  lineage with three of the five arms (Opus-4.6 incumbent, Sonnet-5, Opus-4.8
  golden); a residual stylistic self-preference toward those three cannot be
  excluded and would bias *against* the off-family GLM and DeepSeek. Two facts blunt
  (not eliminate) this: (a) the incumbent — also Claude-family — still lost 19–2 to
  Sonnet-5, and GLM lost to the incumbent, so it is not a pure off-family penalty;
  and (b) the **deterministic layer corroborates the direction independently** —
  DeepSeek's 5.9-cluster parsimony + 0.825 actor coverage and GLM's lower spectrum
  fidelity are measured, not judged. Still, Sonnet-5's margin over GLM should be
  read with the family caveat in mind. The task deliberately chose the strongest
  judge model and relied on blindness; this is the accepted trade-off.
- **Correctness/charges judged against dossier source *summaries*, not full article
  bodies** — the same limitation as the writer eval; only cross-arm ordering is
  load-bearing, and it is consistent across correctness, rubric, pairwise, and the
  deterministic shape metrics.
- **Granularity is rubric-scored, not free.** Sonnet-5's R6 (0.76) shows over-
  splitting is penalized; a production swap would want to confirm its 11-cluster
  average renders acceptably downstream (enrichment, writer input, card).
- **Not a cutover decision by itself.** LLM-judge fallibility (3-judge majority
  mitigates, not eliminates); DeepSeek's WandB provider returned valid here but was
  empty under the editor schema (provider behavior is schema-dependent).

## Reproduction

All under `scratch/perspective-eval/` (untracked):

```bash
.venv/bin/python scratch/perspective-eval/reconstruct.py        # phase 1: 21 topics, coverage + field-leak check
.venv/bin/python scratch/perspective-eval/provider_probe.py     # 6 fp8 pins + Sonnet-5 under PERSPECTIVE_SCHEMA
.venv/bin/python scratch/perspective-eval/report.py             # coverage + cost projection (pre-spend)
.venv/bin/python scratch/perspective-eval/shadow.py             # GLM + DeepSeek(gated) + Sonnet-5, first-attempt/retry tracking, $10 cap
.venv/bin/python scratch/perspective-eval/golden_setup.py       # faithful Opus-4.8 golden packets
# spawn 1 Opus-4.8 golden subagent per topic -> golden_output.json
.venv/bin/python scratch/perspective-eval/score.py              # deterministic layer, 5 arms
.venv/bin/python scratch/perspective-eval/prep_judge.py         # 5-way anonymized packets + sealed key
# spawn 3 Opus-4.8 judge subagents per topic (JUDGE-TASK.md + RUBRIC.md) -> verdict-{1,2,3}.json
.venv/bin/python scratch/perspective-eval/aggregate.py          # means, rubric, pairwise, adjudicated charges, per-topic table
```

Artifacts: per-topic `input.json` / `incumbent_output.json` / `{glm,deepseek,
sonnet5}_output.json` + `_meta.json` / `golden_output.json` / `golden_packet.txt`;
`reconstruction_manifest.json`, `provider-probe/`, `_gate_deepseek.json`,
`shadow_run_summary.json`, `deterministic_scores.json`; `RUBRIC.md`,
`JUDGE-TASK.md`, `judge/{topic}/packet.json` + `verdict-{1,2,3}.json`,
`_judge_key.json` (label→arm, outside the judge tree), `aggregate_summary.json`
(per-arm aggregate + per-topic correctness + every confirmed charge with its judge
citations).
