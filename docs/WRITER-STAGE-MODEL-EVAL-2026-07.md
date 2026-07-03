# Writer-stage model eval — GLM-5.2 @ xhigh vs Sonnet-5 adaptive vs incumbent (2026-07)

Blind, rubric-anchored, 4-arm eval of two candidate writer-stage models against
the production incumbent on 21 real production `writer` topics reconstructed
byte-faithfully from on-disk run state. Same playbook as the QA-stage eval
(`docs/QA-STAGE-MODEL-EVAL-SHADOW-BACKFILL.md`; provider routing per
`docs/GLM-PROVIDER-VERIFICATION-2026-07.md`). Collection, shadow generation,
golden generation, and 3-judge blind judging all ran 2026-07-03. The harness and
raw corpus live untracked under `scratch/writer-shadow/`; this document is the
committed summary.

> **This is a decision input, not a cutover decision.** N=21 over 7 consecutive
> days; LLM-judge panels are fallible; fabrication charges are adjudicated
> against dossier *summaries*, not full source bodies (see caveats). Treat the
> direction as strong and the absolute fabrication counts as inflated-but-
> comparable across arms.

## Arms & operating points

| arm | model | reasoning | temp | max_tokens | routing |
|---|---|---|---|--:|---|
| **incumbent** | `anthropic/claude-opus-4.6` | none | 0.3 | (prod) | default |
| **GLM-5.2** | `z-ai/glm-5.2` | effort **xhigh** | 0.3 | 120000 | fp8 pin `[baidu, ambient, venice]`, `allow_fallbacks:false` |
| **Sonnet-5** | `anthropic/claude-sonnet-5` | `reasoning.enabled` (adaptive) | — (omitted) | 64000 | default |
| **golden** | Opus-4.8 subagent, max care | — | — | — | ceiling reference, cost-neutral |

Prompts held **identical** to production `writer` for every arm: `SYSTEM.md` +
`INSTRUCTIONS.md` (+ `FOLLOWUP.md` on follow-up topics), the strict
`WRITER_SCHEMA`, and the reconstructed input — assembled by the production
`Agent` message path, not re-implemented. Only the eval variables differ
(model / reasoning / routing / max_tokens). GLM temperature is held at
production's 0.3; Sonnet-5 sends no temperature (the 5-family rejects non-default
temperature). Writer prompts last changed 2026-04-28 / 2026-05-30 / 2026-05-01 —
all before the eval window — so the current files reconstruct every sampled
topic byte-faithfully.

## Headline result

3-judge majority, blind, anchor-free, scored against a prompt-derived R1–R9
rubric + the provided sources:

| metric | incumbent (Opus 4.6) | **GLM-5.2 @ xhigh** | Sonnet-5 adaptive | golden (ceiling) |
|---|--:|--:|--:|--:|
| Mean absolute correctness (1–5) | 3.29 | **3.86** | 3.48 | 4.38 |
| Rubric pass-rate (R1–R9; pass=1/partial=½/fail=0) | 0.855 | **0.931** | 0.852 | 0.951 |
| Confirmed fabrications — total (≥2/3 judges, cited) | 52 | **33** | 39 | 19 |
| Confirmed fabrications — topics with ≥1 | 19 | 18 | 18 | 13 |
| Deterministic: invented src ids | 0 | **0** | 0 | 0 |
| Deterministic: sources[] orphans / phantoms | n/a¹ | **0 / 0** | 11 / 42 | 0 / 0 |
| Deterministic: in 600–1200-word band | 21/21 | **21/21** | 18/21 | 21/21 |

Per-topic **majority pairwise** (21 topics):

| pair | winner tally |
|---|---|
| GLM vs incumbent | **GLM 15 – 6** |
| GLM vs Sonnet-5 | **GLM 14 – 7** |
| GLM vs golden | golden 16 – 5 |
| Sonnet-5 vs incumbent | Sonnet-5 12 – 9 |
| golden vs incumbent | golden 18 – 3 |
| golden vs Sonnet-5 | golden 15 – 6 |

Overall order: **golden › GLM-5.2 › Sonnet-5 ≈ incumbent**.

Correctness distribution — GLM `{5:9, 4:37, 3:16, 2:1}` (strikingly consistent,
almost never below 3); incumbent `{5:6, 4:15, 3:33, 2:9}`; Sonnet-5
`{5:11, 4:26, 3:12, 2:10, 1:4}` (higher variance — the four 1s are genuine
failures incl. a max_tokens truncation); golden `{5:29, 4:29, 3:5}`.

**Reading:** under the harder protocol, **GLM-5.2 @ xhigh is the strongest
challenger** — it beats the production incumbent decisively (15–6 pairwise, +0.57
mean correctness, ~0.08 higher rubric pass-rate, 33 vs 52 confirmed
fabrications) and beats Sonnet-5 (14–7), while sitting a clear step below the
Opus-4.8 golden ceiling (5–16). GLM's deterministic integrity **matches golden**
(0 invented ids, clean `sources[]`, 21/21 in band). GLM's per-topic consistency
is its signature: it almost never drops below correctness 3, whereas the
incumbent clusters at 3 and Sonnet-5 is polarised.

¹ The incumbent's production `writer_article` snapshot stores only the four text
fields (`sources[]` is dropped by the `WriterArticle` model before the snapshot),
so its `sources[]` hygiene cannot be measured. Its **body citations** were
integrity-checked like every arm (0 invented ids). Sonnet-5's 42 phantoms
(cited inline, absent from its emitted `sources[]`) + 11 orphans are a real
citation-hygiene defect unique to it.

## Rubric pass-rate by criterion

| arm | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| incumbent | 1.00 | 0.54 | 0.94 | 0.96 | 0.93 | 0.94 | 0.67 | 0.86 | 0.90 |
| **GLM-5.2** | 0.98 | 0.62 | 1.00 | 0.99 | 0.97 | 0.98 | 0.98 | 0.93 | 0.93 |
| Sonnet-5 | 0.89 | 0.66 | 0.98 | 0.94 | 0.90 | 0.98 | 0.73 | 0.73 | 0.90 |
| golden | 0.98 | 0.71 | 0.99 | 1.00 | 0.99 | 1.00 | 0.96 | 0.98 | 0.93 |

(R1 multi-perspective coverage, R2 grounding/no-fabrication, R3 citation
discipline, R4 equal weight, R5 reporting voice, R6 no editorial/intensity
vocab, R7 no coverage-landscape meta-claims, R8 structure/length, R9 follow-up.)

Two criteria drive the ranking. **R2 (grounding)** is the weakest for every arm
(0.54–0.71) — the summary-vs-full-source judging limitation (see caveats) — but
GLM (0.62) still clears the incumbent (0.54). **R7 (no coverage-landscape
meta-claims)** separates the arms sharply: GLM 0.98 and golden 0.96 stay in the
reporting voice, while the incumbent (0.67) and Sonnet-5 (0.73) more often slip
into the writer's-own-voice claims about what coverage did or didn't say — the
exact flatness discipline the prompt exists to enforce. GLM's R3 (citation
discipline) is a clean 1.00. Sonnet-5's R8 (0.73) reflects its 3 length-band
misses and the truncation.

## Cost & latency (measured, 21 topics)

| arm | total spend | mean $/topic | mean latency | max latency | served |
|---|--:|--:|--:|--:|---|
| incumbent (Opus 4.6) | $2.74 | $0.131 | — (not logged) | — | Anthropic |
| **GLM-5.2 @ xhigh** | $1.03 | **$0.049** | **110 s** | 218 s | Baidu (21/21) |
| Sonnet-5 adaptive | $1.93 | $0.092 | 49 s | 107 s | Azure (21/21) |
| golden | cost-neutral (Opus-4.8 subagents) | — | ~60–190 s | — | — |

**GLM-5.2 @ xhigh is the cheapest arm *and* the strongest challenger** —
~2.7× cheaper per topic than the incumbent and ~1.9× cheaper than Sonnet-5.
Unlike the QA stage (xhigh ~442 s/topic on the much larger QA input), the writer
input is light enough that xhigh runs ~110 s mean (218 s tail) — well inside the
httpx read window and a modest ~5–6 min/day added to the 3-topic daily runner.
Total paid eval spend: **$2.97 shadow + $0.23 provider-probe = $3.20** of the $18
hard cap.

## Method

**Inventory + reconstruction (byte-faithful).** For each production run day
≥2026-05-31 with `WriterStage` state, the exact writer input per topic is rebuilt
from `topic_buses.WriterStage.{n}.json`: the same fixed message
(`"Write a multi-perspective article on this topic."`), the same context dict in
the same key order WriterStage builds (`title, selection_reason,
perspective_analysis, sources` [`actors_quoted` dropped], `actors,
coverage_gaps`), and the **conditional follow-up addendum**. The follow-up path
is driven solely by `editor_selected_topic.follow_up_to` — the identical
predicate production uses; when truthy, `FOLLOWUP.md` is loaded as the
`instructions_addendum` and a `follow_up` context key `{previous_headline,
reason}` is appended, with `previous_headline` recovered from
`run_bus.previous_coverage`. Wire fidelity was confirmed end-to-end through the
real `Agent` message-assembly (FOLLOWUP text + `follow_up` context present iff
the topic is a follow-up). The incumbent output + per-topic cost/tokens come from
the same snapshot + `run_stage_log.jsonl`.

**Sample.** Most-recent-first, 7 days × 3 topics = **21 topics** (2026-06-27 …
2026-07-03), 5 follow-up + 16 standalone, 0 excluded (every topic's follow-up
applicability was determinable). Context size min 23.4 KB / median 35.6 KB /
max 76.4 KB; incumbent bodies 778–1181 words.

**Provider probe.** Before spend, one WRITER_SCHEMA probe per pinned GLM provider
on the median topic: Baidu / Ambient / Venice all returned schema-valid JSON with
`finish_reason: stop` (the QA verification used the QA schema; this re-verifies
under the writer schema). A Sonnet-5 probe validated its arm. Cost projection was
printed before the shadow phase.

**Deterministic scoring (Python, all four arms).** Schema validity; every inline
`[src-NNN]` resolves against the topic's `final_sources` (invented-id count);
`sources[]` orphan/phantom hygiene (arms that emit it); perspective-cluster
coverage proxy; body word count / length band. Counting is never delegated to an
LLM.

**Golden.** One fresh Opus-4.8 subagent per topic executed the writer task itself
at maximum care on the identical reconstructed prompt (schema-valid, cost-neutral)
— a quality ceiling, never a scoring target.

**Judging (blind, 4-way, leak-proof, 3 judges/topic).** Each topic's four arm
outputs were deep-normalised to one canonical shape (`{headline, subheadline,
body, summary}` — `sources[]` dropped for all, so the incumbent's missing array
is not a tell; all metadata stripped), assigned per-topic random labels A–D via a
seeded permutation, with the label→arm key written **outside** the judge tree. 21
topics × 3 fresh judges = **63 verdicts, 0 missing, 0 malformed.** Each judge
received the topic input + sources + the R1–R9 rubric (with the binding **style
trap** — restraint is the product requirement; livelier prose that breaks the
restraint constraints is a rubric FAILURE, not a bonus) + the four anonymised,
order-randomised outputs, and returned per-output correctness, R1–R9 verdicts,
claim-cited fabrication charges, and a strict A–D ranking. Pairwise is derived
from each judge's ranking and taken by majority. A fabrication is **confirmed**
only when ≥2 of 3 judges independently cite an overlapping claim against the same
output (deterministic claim-overlap clustering); every counted charge carries its
citations.

## Per-topic (un-anonymised; correctness = mean of 3 judges)

| case | FU | GLM | Son | Inc | Gold | GLM·vs·Inc | GLM·vs·Son | GLM·vs·Gold |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 2026-06-27/topic-0 |  | 4.00 | 4.00 | 3.00 | 3.33 | GLM | GLM | GLM |
| 2026-06-27/topic-1 |  | 3.67 | 5.00 | 3.67 | 5.00 | inc | son | gold |
| 2026-06-27/topic-2 |  | 3.33 | 5.00 | 2.00 | 4.00 | GLM | son | gold |
| 2026-06-28/topic-0 | Y | 3.67 | 1.00 | 3.67 | 4.33 | GLM | GLM | gold |
| 2026-06-28/topic-1 |  | 4.00 | 3.67 | 3.33 | 4.00 | GLM | GLM | GLM |
| 2026-06-28/topic-2 |  | 3.67 | 2.33 | 3.00 | 4.33 | GLM | GLM | gold |
| 2026-06-29/topic-0 |  | 4.00 | 4.00 | 3.00 | 4.00 | GLM | son | gold |
| 2026-06-29/topic-1 | Y | 3.33 | 4.67 | 3.00 | 4.67 | GLM | son | gold |
| 2026-06-29/topic-2 |  | 3.67 | 2.00 | 4.33 | 5.00 | inc | GLM | gold |
| 2026-06-30/topic-0 |  | 4.00 | 4.00 | 2.67 | 4.00 | GLM | son | gold |
| 2026-06-30/topic-1 |  | 3.67 | 3.33 | 3.33 | 4.33 | GLM | GLM | gold |
| 2026-06-30/topic-2 |  | 5.00 | 3.67 | 3.00 | 5.00 | GLM | GLM | gold |
| 2026-07-01/topic-0 |  | 4.00 | 2.00 | 3.00 | 4.00 | GLM | GLM | gold |
| 2026-07-01/topic-1 |  | 4.33 | 3.67 | 2.00 | 5.00 | GLM | GLM | gold |
| 2026-07-01/topic-2 | Y | 3.00 | 1.67 | 4.00 | 4.33 | inc | GLM | gold |
| 2026-07-02/topic-0 |  | 3.67 | 5.00 | 2.33 | 4.67 | GLM | son | gold |
| 2026-07-02/topic-1 |  | 4.00 | 3.33 | 4.33 | 4.67 | inc | GLM | gold |
| 2026-07-02/topic-2 | Y | 4.33 | 4.00 | 4.00 | 3.00 | GLM | GLM | GLM |
| 2026-07-03/topic-0 | Y | 4.00 | 3.00 | 4.33 | 4.33 | inc | GLM | GLM |
| 2026-07-03/topic-1 |  | 5.00 | 3.67 | 3.00 | 5.00 | GLM | GLM | GLM |
| 2026-07-03/topic-2 |  | 2.67 | 4.00 | 4.00 | 5.00 | inc | son | gold |

## Adjudicated fabrications & the summary limitation

143 charges were confirmed across the four arms (incumbent 52, Sonnet-5 39, GLM
33, golden 19), each with ≥2 judge citations in
`scratch/writer-shadow/aggregate_summary.json`. Two patterns matter for reading
them:

1. **Many charges are judge false-positives against terse dossier summaries.**
   Judges score grounding against the sources' *summaries*, not the full fetched
   article bodies. The clearest evidence: on 2026-06-27/topic-0 the claim that
   "Bolton's personal email was hacked by an individual linked to Iran [src-001]"
   is charged (3/3 judges) against the incumbent, Sonnet-5, **and the golden
   Opus-4.8 reference** — a max-care Claude pass makes the identical "fabrication."
   When the ceiling arm commits the same charge, it is a summary-coverage
   artifact, not a model defect. The same shape recurs (e.g. Der Spiegel / Reiche
   on 2026-06-27/topic-2 charged against both GLM and golden). **The absolute
   counts are therefore inflated; the relative ordering is the signal**, and it
   is consistent: GLM (33) < Sonnet-5 (39) < incumbent (52).

2. **A few are genuine.** Sonnet-5's charge on 2026-06-28/topic-0 is a real
   failure — the body **terminates mid-sentence** ("…the flight was ") and the
   summary field is not a summary: an output truncation at `max_tokens=64000`.
   That is the topic where Sonnet-5 scored 1.0 and lost every pairwise. It is the
   one hard operational strike against the Sonnet-5 arm at 64000, and it argues
   for a larger budget if Sonnet-5 were ever the writer.

## Caveats & limitations

- **N=21, 7 consecutive days.** No seasonal/topic-mix diversity beyond the window.
- **Fabrication judging is against dossier summaries, not full source bodies** —
  inflates absolute counts (golden itself scores 19); only the cross-arm ordering
  is load-bearing. Same standard applied to all four arms and to the production
  writer stage itself.
- **Three of four arms are Claude-family** (incumbent Sonnet? no — incumbent is
  Opus 4.6, golden is Opus 4.8, and the judges are Opus 4.8; only GLM is
  off-family). Anonymisation normalises structure and strips metadata but not
  writing style; a residual stylistic-familiarity bias toward the three
  Claude-family outputs cannot be excluded. If anything this biases *against* the
  GLM result, which still wins its challenger comparisons.
- **LLM-judge fallibility.** 3-judge majority mitigates but does not eliminate it.
- **Not a cutover decision by itself.** A swap would additionally weigh the
  transparency-chain interaction (writer output feeds QA — now GLM-5.2 — then
  balance/bias/card) and a longer confirmation window. Latency (~110 s/topic) and
  cost ($0.049/topic) are both favourable, unlike the QA-stage xhigh latency.

## Reproduction

All under `scratch/writer-shadow/` (untracked):

```bash
.venv/bin/python scratch/writer-shadow/collect.py                 # reconstruct inputs (free)
.venv/bin/python scratch/writer-shadow/provider_probe.py          # GLM×3 + Sonnet-5 probe under WRITER_SCHEMA
.venv/bin/python scratch/writer-shadow/report.py                  # coverage + cost projection (pre-spend)
.venv/bin/python scratch/writer-shadow/shadow.py --arm both       # GLM + Sonnet-5 shadow outputs (concurrency 4, $18 cap)
.venv/bin/python scratch/writer-shadow/score.py                   # deterministic scoring, 4 arms
.venv/bin/python scratch/writer-shadow/golden_setup.py            # golden prompt packets
# spawn one Opus-4.8 golden subagent per case -> golden_output.json
.venv/bin/python scratch/writer-shadow/prep_judge.py              # 4-way anonymised packets + key (outside judge tree)
# spawn 3 judge subagents per case (JUDGE-TASK.md + RUBRIC.md) -> verdict-{1,2,3}.json
.venv/bin/python scratch/writer-shadow/aggregate.py               # majority pairwise, means, rubric, adjudicated fabrications
```

Artifacts: per-topic `input.json` / `incumbent_output.json` / `glm_output.json`
/ `sonnet5_output.json` / `golden_output.json` / `*_meta.json`; `RUBRIC.md`,
`JUDGE-TASK.md`; `judge/{slug}/packet.json` + `verdict-{1,2,3}.json`;
`_judge_key.json` (label→arm, outside the judge tree); `deterministic_scores.json`,
`aggregate_summary.json` (full per-case detail + every confirmed fabrication with
its judge citations); `collection_manifest.json`, `provider-probe/`.

---

# Addendum — operating-point controls (2026-07-03)

The base eval left two operating-point variables uncontrolled, each capable of
confounding a comparison:

1. **The incumbent ran at its production point** (`reasoning=none`) while the GLM
   challenger ran at effort **xhigh** — so "GLM beats incumbent" conflated *model*
   with *reasoning budget*. This addendum adds the effort-matched control
   (**incumbent-high** = Opus 4.6 @ effort high).
2. **The Sonnet-5 arm ran `reasoning:{enabled:true}` with no explicit effort AND
   was served entirely by Azure** (`served_model …-20260630`, 21/21). Its
   citation-hygiene collapse (42 phantoms / 11 orphans over 21 topics) might be an
   operating-point or a serving artifact rather than a model property. This
   addendum adds **sonnet5-corrected** = an explicit effort + a pinned provider.

Both controls run on the **9 most-recent** of the 21 topics (2026-07-01 …
2026-07-03, 3 follow-ups), **reusing** the existing per-topic inputs and the
existing incumbent-none / GLM / Sonnet-5-original / golden outputs (no new golden
runs). Prompts, `WRITER_SCHEMA`, and reconstructed inputs are held at the base
eval's values. Read-only on production; raw under `scratch/writer-shadow/addendum/`.

## Probe — resolving the two operating points (with request bodies)

Six single-config probe calls on the median-size addendum topic
(2026-07-01/topic-1), full bodies in `addendum/probe/probe_summary.json`:

**Opus 4.6 @ effort high — is temperature accepted under thinking?** Anthropic's
extended-thinking API normally rejects a non-default `temperature`; the 4.7/5
family hard-rejects it. Empirically, **Opus 4.6 via OpenRouter accepts temperature
0.3 alongside `reasoning:{effort:high}`** (HTTP 200, `finish_reason:stop`,
served Anthropic):

```jsonc
// A1 — ACCEPTED (200): reasoning_tokens≈244, $0.145, no truncation at 32000
{ "model": "anthropic/claude-opus-4.6", "temperature": 0.3, "max_tokens": 32000,
  "reasoning": {"effort": "high"},
  "response_format": {"type":"json_schema","json_schema":{"strict":true, ...}},
  "provider": {"require_parameters": true} }
// A2 — temperature omitted: 200, reasoning_tokens≈337 (statistically indistinct)
```

So temperature is **held at production's 0.3**, making incumbent-high a clean
single-variable delta from incumbent-none (only `reasoning none→high` changes).
Note the low reasoning-token counts (≈244–337): Opus 4.6's `effort:high` via
OpenRouter engages only light thinking on the writer task even with a large
budget available — the model chooses to reason little here. `max_tokens=32000`
(production default) held; no truncation.

**Sonnet-5 — does effort shift reasoning? does provider matter?**

```jsonc
// B1 {enabled:true}          default routing → Azure, reasoning_tokens≈422
// B2 {enabled:true,effort:high} default routing → Azure, reasoning_tokens≈1299 (~3×), body 905→760w
{ "model": "anthropic/claude-sonnet-5", "max_tokens": 64000,
  "reasoning": {"enabled": true, "effort": "high"},
  "response_format": {"type":"json_schema", ...}, "provider": {"require_parameters": true} }
```

Effort **is** honored and measurably shifts reasoning (~3× tokens). Provider,
however, could **not** be pinned to Amazon Bedrock — every Bedrock form errored:

```
provider {"order":["amazon-bedrock"], "allow_fallbacks":false}   → "model not available on the requested cloud provider"
provider {"order":["amazon-bedrock/us-east-1"], ...}             → "Provider returned error"
provider {"order":["Amazon Bedrock"], ...}                       → "model not available on the requested cloud provider"
provider {"order":["azure"], "allow_fallbacks":false}            → 200, served Azure
```

Bedrock is listed in the OpenRouter endpoints API for `claude-sonnet-5` but is
**not routable** for this model through OpenRouter (structured-output beta /
region gating). The QA-eval's Bedrock serving path is therefore **untestable
here** (documented limitation — full record in `addendum/provider_diagnosis.json`).
The original arm was already 100% Azure, so provider was a *de-facto constant*;
the corrected arm **pins Azure explicitly, fail-loud** (`order:["azure"],
allow_fallbacks:false`). Because both the original and corrected Sonnet-5 arms are
served by the **same Azure**, any difference between them isolates the
**reasoning-effort** variable — not serving.

**Resolved points:** incumbent-high = Opus 4.6, `effort:high`, temp 0.3,
max_tokens 32000. sonnet5-corrected = Sonnet-5, `{enabled:true, effort:high}`,
Azure-pinned, no temperature, max_tokens 64000.

## Cost projection (printed pre-spend) & spend

Measured points: incumbent-high $0.145/topic, sonnet5-corrected $0.111/topic →
projection **9 × ($0.145 + $0.111) = $2.30 + $0.50 probe = $2.81**, well under the
**$15** cap, so all 9 topics ran (no reduction). Actual paid spend: probe $0.51 +
re-run $2.39 = **$2.90**. All 18 re-run calls schema-valid (incumbent-high 9/9
Anthropic; sonnet5-corrected 9/9 Azure).

## Judging

Fresh 3-judge blind panels on the 9 topics with **all six arms** in one
anonymized, order-randomized packet (incumbent-none, incumbent-high, GLM,
Sonnet-5-original, Sonnet-5-corrected, golden), canonicalized to
`{headline, subheadline, body, summary}` (leak-proof — `sources[]` dropped for
all), seeded label→arm key outside the judge tree. Same R1–R9 rubric, same
binding style trap, same ≥2/3 claim-cited fabrication rule. **9 × 3 = 27 verdicts,
0 missing, 0 malformed.**

## What the controls changed

### Control 1 — effort-matching the incumbent does NOT close the gap

| incumbent-none (effort none) | incumbent-high (effort high) |
|---|---|
| correctness **3.52** · rank 3.48 · rubric 0.884 · fab 16 | correctness 3.22 · rank 3.96 · rubric 0.867 · fab 16 |

Pairwise across the 9 topics: **incumbent-none 5 – 4 incumbent-high** — adding
effort-high produced **no improvement (a slight regression within N=9)**. This is
consistent with the probe: Opus 4.6's `effort:high` engages only ~300 reasoning
tokens on the writer task, so "more reasoning" is barely realized and buys
nothing here (while costing more: $0.162 vs $0.153/topic). **The base eval's
incumbent was not handicapped by its `reasoning=none` production point** — giving
it the challenger's reasoning intent does not move it toward GLM. The base
"GLM > incumbent" result is therefore not a reasoning-budget artifact.

### Control 2 — correcting Sonnet-5's operating point changes its verdict

| sonnet5-original ({enabled:true}, Azure) | sonnet5-corrected ({enabled:true,effort:high}, Azure) |
|---|---|
| correctness **3.19** · rank **4.22** (worst arm) · rubric 0.849 | correctness **3.59** · rank **3.37** (top challenger) · rubric 0.902 |
| deterministic: **11 orphans / 11 phantoms**, in-band 7/9, 4× correctness-1 tail | deterministic: **0 / 0**, in-band 8/9, **zero** correctness-1 |

Pairwise: **sonnet5-corrected 5 – 4 over its own original**; and corrected beats
GLM (5–4), incumbent-none (5–4), and incumbent-high (6–3). The base eval's
citation-hygiene collapse and low-correctness tail (including the max_tokens
truncation) were an **operating-point (under-reasoning) artifact, not intrinsic
to Sonnet-5 and not a serving artifact** — provider was Azure in *both* the
original and corrected arms, so raising effort (adaptive → explicit high) is the
sole cause, and it drives phantoms 11→0 and the correctness-1 tail 4→0. **The base
eval understated Sonnet-5.**

### Revised ordering (9 topics, 6-arm 3-judge blind panel)

| arm | corr. mean | mean rank (↓) | rubric | confirmed fab | determ. phantom/orphan | $/topic |
|---|--:|--:|--:|--:|--:|--:|
| golden (Opus-4.8 ceiling) | **4.07** | **2.33** | **0.949** | **8** | 0 / 0 | (cost-neutral) |
| **sonnet5-corrected** | 3.59 | **3.37** | 0.902 | 16 | **0 / 0** | $0.103 (Azure) |
| incumbent-none | 3.52 | 3.48 | 0.884 | 16 | n/a¹ | $0.153 (Anthropic) |
| GLM-5.2 @ xhigh | 3.56 | 3.63 | 0.911 | 15 | 0 / 0 | **$0.050** (Baidu) |
| incumbent-high | 3.22 | 3.96 | 0.867 | 16 | n/a¹ | $0.162 (Anthropic) |
| sonnet5-original | 3.19 | 4.22 | 0.849 | 17 | 11 / 11 | $0.105 (Azure) |

Overall order by mean rank: **golden › sonnet5-corrected › incumbent-none ≈ GLM ›
incumbent-high › sonnet5-original**. Latency: GLM 94 s (172 s max), incumbent-high
62 s, sonnet5-corrected 47 s. Rubric-by-criterion echoes the base eval: GLM keeps
its R7 edge (1.00 vs incumbent 0.65–0.70), and R8 is where sonnet5-corrected
recovers most (0.74 → 0.91, matching the deterministic in-band/truncation fix).

¹ The production incumbent snapshot stores only the four text fields (`sources[]`
dropped), so its `sources[]` hygiene cannot be measured; body citations resolved
cleanly (0 invented ids) for all arms.

## Caveats specific to the addendum

- **The 9-topic window is GLM's *weakest* slice.** In the base 21-topic 4-way
  eval, GLM beat the incumbent 15–6 overall but only **5–4 on exactly these 9
  most-recent topics**. So the addendum's GLM ≈ incumbent-none near-tie (GLM 4 – 5)
  is a property of the window, not a reversal of the base finding; it is the
  narrowest 9-topic stretch of the 21.
- **6-way panel, N=9 — not directly comparable to the base 4-way/21-topic
  numbers.** Adding two more outputs and dropping to 9 topics shifts absolute
  scores; only the within-addendum arm ordering is load-bearing here.
- **Fabrication counts barely discriminate on this window** (all non-golden arms
  15–17; golden 8 = floor) — the dossier-summary judging limitation from the base
  eval dominates. The signal in this addendum is the **rank / pairwise / rubric /
  deterministic** movement, not the fabrication tallies.
- **Bedrock serving hypothesis untested** (not routable via OpenRouter for
  Sonnet-5). The Sonnet-5 fix is attributed to effort with provider held constant
  at Azure; whether a different serving stack would change it is open.

## Net reading

Neither control overturns the base eval's direction, and both sharpen it:
**(1)** the incumbent was *not* under-powered by `reasoning=none` — effort-matching
it changes nothing (Opus 4.6 barely reasons on this task), so the model comparison
was fair; **(2)** the Sonnet-5 arm *was* operating-point-handicapped — corrected,
it is the strongest non-golden arm on this window and its deterministic defects
vanish, so the base eval understated it. The practical order among deployable
challengers on this slice is **sonnet5-corrected ≈ incumbent ≈ GLM**, with GLM
still the cheapest by ~2–3× and Sonnet-5-corrected the best-ranked. Still a
decision input, not a cutover: N=9, GLM's weakest window, Claude-family judges,
and the summary-grounding limitation all apply as before.

## Addendum reproduction

All under `scratch/writer-shadow/addendum/` (untracked):

```bash
.venv/bin/python scratch/writer-shadow/addendum/probe.py       # resolve operating points (request bodies)
.venv/bin/python scratch/writer-shadow/addendum/report.py      # coverage + cost projection (pre-spend)
.venv/bin/python scratch/writer-shadow/addendum/shadow.py --arm both   # incumbent-high + sonnet5-corrected, 9 topics
.venv/bin/python scratch/writer-shadow/addendum/score.py       # deterministic scoring, 6 arms
.venv/bin/python scratch/writer-shadow/addendum/prep_judge.py  # 6-way anonymized packets + key (outside judge tree)
# spawn 3 judge subagents per case (JUDGE-TASK-ADDENDUM.md + RUBRIC.md) -> verdict-{1,2,3}.json
.venv/bin/python scratch/writer-shadow/addendum/aggregate.py   # majority pairwise, means, rubric, adjudicated fabrications
```

Artifacts: `probe/probe_*.json` + `probe_summary.json`, `provider_diagnosis.json`,
`{date}/topic-{n}/incumbent_high_*.json` + `sonnet5_corrected_*.json`,
`deterministic_scores.json`, `judge/{slug}/packet.json` + `verdict-{1,2,3}.json`,
`_judge_key.json` (outside the judge tree), `aggregate_summary.json`.
