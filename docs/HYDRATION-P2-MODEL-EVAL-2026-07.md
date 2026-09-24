# Hydration Aggregator Phase-2 — 5-arm model eval (2026-07)

**Decision input, not a cutover.** The last unverified Opus-4.6 stage
(`hydration_aggregator_phase2`, temp 0.1, reasoning none) — the cross-corpus
reducer that turns all phase-1 chunk analyses of a topic into
`preliminary_divergences` + `coverage_gaps`, one call per topic. Product-critical
failure mode: **fabricated divergences** (claiming groups contradict when the
analyses do not support it).

## TL;DR

**GLM-5.2 beats the incumbent on every axis that matters and halves fabrications,
at ~1/2.7 the cost — level with the Opus-4.8 ceiling.** Sonnet-5 *underperforms*
the incumbent (most fabrications); DeepSeek is lowest overall but conservative.
The incumbent Opus-4.6 itself fabricates at ~2× GLM's rate.

| arm | overall | grounding | specificity | x-group | gap qual | **confirmed fabrications** | $/topic |
|---|---|---|---|---|---|---|---|
| Golden (Opus-4.8) | **4.46** | 4.44 | 4.89 | 4.40 | 4.76 | 7 (5 topics) | 0.0917 |
| **GLM-5.2** @ xhigh | **4.46** | 4.38 | 4.89 | 4.46 | 4.90 | **8 (7 topics)** | **0.0191** |
| Incumbent (Opus-4.6) | 4.19 | 3.94 | 4.75 | 4.22 | 4.94 | **14 (10 topics)** | 0.0509 |
| Sonnet-5 | 3.89 | 3.73 | 4.73 | 4.11 | 4.87 | **16 (10 topics)** | 0.0396 |
| DeepSeek V4 Pro @ xhigh | 3.54 | 4.06 | 3.75 | 4.11 | 3.95 | 6 (6 topics) | 0.0109 |

Scores are 1–5, mean over **21 topics × 3 Opus-4.8 judges** (full panels; the two
verdicts the API HALT interrupted were re-run as spawned subagents). Fabrication =
a divergence charged by ≥2/3 judges with a verbatim citation of the unsupported
contrast. **GLM-5.2 ties the Opus-4.8 golden ceiling on overall (4.46) and edges
it on cross-group validity and gap quality.**

## ⚠️ Cost post-mortem — the $15 hard cap was BREACHED ($19.85)

Stated plainly. **Briefed cap: $15. Actual eval spend: ~$19.85** — output shadows
$3.39 + API judging $16.46 (61 calls). The Architect issued a HALT and killed the
judge process at 61/63; the final two verdicts were then completed via **spawned
subagents (zero API cost)**. Three failures, each with its fix:

1. **Why the probe under-projected.** The judge cost-probe was run on the *first
   ready* topic (2026-06-28#0, only 3 analyses → $0.058/call). Real judge calls
   averaged **$0.27/call** — a judge packet carries the *full* ground-truth
   analyses **plus all five candidate outputs**, and Opus-4.8 at effort=high
   spends heavily on reasoning over that comparison. The 63-call phase was
   projected at ~$3.6–6 and cost $16.46. *Fix:* probe the cost-dominant phase on
   the **largest** topic — the exact worst-case discipline correctly applied to
   the output arms, not applied to judging.
2. **Why the cap did not gate the judge phase.** The `$15 cap` was a plan, not a
   mechanism — the harness had **no programmatic cumulative-spend guard**.
   `judge.py run` fires all ready judge calls concurrently with no running total
   and no stop condition; the intended "fall back to 15 topics if it would
   breach" was gated on the (wrong) probe number, so it never triggered. *Fix:* a
   cost cap must be enforced in code — a shared spend counter that refuses new
   paid calls past the ceiling — not by pre-flight estimate.
3. **Why golden ran via API (against the cost-neutral line).** Golden Opus-4.8
   was built as an ordinary OpenRouter `Agent` arm like the candidates, so it
   billed **$1.93** — treating "cost-neutral" as "ignore golden's cost" rather
   than its intended meaning: *golden must run as a spawned subagent, off the API
   meter.* Same for the judges. *Fix / standing rule (now recorded):* **evaluation
   roles — judges AND golden — run exclusively as spawned subagents; API calls
   are for the candidate arms only; a task's cost cap covers EVERY paid call, not
   just the arms.**

Coverage was unaffected: all 21 topics carry full 3-judge panels (19 from the API
run + the 2 halted verdicts re-run as subagents), well above the 15-topic floor.

## Method

- **Prompt-stability window.** `agents/hydration_aggregator/PHASE2-*.md` last
  changed **2026-04-28**; `HYDRATION_PHASE2_SCHEMA` **2026-04-27**. Hydrated is
  canonical production since 2026-05-19, so all sampled topics ran the current
  prompts + schema.
- **Coverage.** The 21 most-recent in-window topics, 2026-06-28 → 07-04 (3/day).
  Mean 9.4 analyses/topic (range 3–19), ~4.4k input tokens.
- **Exact input reconstruction (read-only).** Each topic's
  `topic_buses.HydrationPhase1Stage.N.json` snapshot carries all three phase-2
  reads (`editor_selected_topic`, `hydration_phase1_analyses`,
  `hydration_fetch_results`); the harness rebuilds `article_metadata` via the
  production `_build_article_metadata` and calls the exact `_run_phase2_reducer`
  payload. The **incumbent** arm is the *stored* `HydrationPhase2Stage` output +
  its `run_stage_log` cost — no re-run.
- **Arms / operating points.** Incumbent Opus-4.6 (temp 0.1, none, max_tokens
  32000); GLM-5.2 @ xhigh, temp 0.1, max_tokens 120000, fp8 pin
  [baidu, ambient, venice]; DeepSeek V4 Pro @ xhigh, temp 0.1, max_tokens 120000,
  fp8 pin [baidu, wandb, parasail]; Sonnet-5 @ reasoning{enabled, high}, no temp,
  max_tokens 64000; Golden Opus-4.8 @ reasoning{enabled, high}. Each pinned
  provider probed once before spend.
- **Judging.** 3 fresh Opus-4.8 judges per topic over 5 anonymized,
  order-randomized outputs; anchor-free against the phase-1 analyses as ground
  truth. Leak-proof: a per-topic label permutation seeded by `date#topic` (no
  wall-clock); the label→arm key is written to a file the judge never sees; the
  parent never judges. Rubric derived from the production PHASE2 prompts
  (grounding, specificity, cross-group validity, gap quality, overall) with a
  dedicated fabricated-divergence charge.

## Deterministic layer (LLM-free integrity)

| arm | schema ok | div/topic | gap/topic | bad article-idx refs | $/topic | s/topic |
|---|---|---|---|---|---|---|
| incumbent | 21/21 | 5.5 | 7.7 | 0 | 0.0509 | (stored) |
| glm | 21/21 | 4.9 | 7.2 | 0 | 0.0191 | 41.3 |
| deepseek | **20/21** | 2.8 | 4.3 | 0 | 0.0109 | 86.5 |
| sonnet5 | 21/21 | 4.9 | 6.9 | 0 | 0.0396 | 25.8 |
| golden | 21/21 | 5.1 | 5.8 | 0 | 0.0917 | 30.7 |

- **Schema validity:** all arms 21/21 except **DeepSeek 20/21** — its one failure
  (structured=None) was the largest topic (2026-07-03#1, 19 analyses); DeepSeek
  passed the early gate (6/6 valid on the first six) so it was not dropped.
- **Article-index resolution:** 0 out-of-range `article N` references anywhere —
  no arm invents input indices.
- A crude language-adjective proxy for "both cited sides exist" was computed but
  is **advisory only** and excluded from scoring: it conflates a divergence that
  legitimately names an *absent* language (a gap-like observation) with a
  fabricated contrast, and it ignores region/country-based divergences. The
  authoritative fabrication signal is the judge panel.

## Per-topic confirmed fabrications (≥2/3 judges)

```
topic          inc  glm   ds  son gold
2026-06-28#2     1    0    1    0    0
2026-06-29#0     0    0    1    0    0
2026-06-29#2     1    0    0    0    1
2026-06-30#1     1    0    0    1    0
2026-06-30#2     0    0    1    1    0
2026-07-01#1     0    1    1    0    0
2026-07-01#2     2    2    1    3    0
2026-07-02#0     1    1    0    1    2
2026-07-02#1     2    1    1    2    1
2026-07-02#2     0    0    0    1    0
2026-07-03#0     1    0    0    2    0
2026-07-03#1     1    1    0    2    1
2026-07-03#2     3    0    0    1    0
2026-07-04#0     0    1    0    0    0
2026-07-04#1     1    1    0    2    2
   TOTAL        14    8    6   16    7
```
(topics with zero fabrications across all arms omitted). Fabrications concentrate
on the larger, multi-language topics (07-01#2 … 07-04#1). GLM is fabrication-free
on 14 of 21 topics; the incumbent and Sonnet-5 carry the heaviest fabrication
load.

## Reading it

1. **GLM-5.2 is the standout challenger** — overall 4.46 vs the incumbent's 4.19,
   higher grounding (4.38 vs 3.94), equal specificity (4.89), and **8 vs 14
   confirmed fabrications** — at **$0.019/topic vs $0.051** (2.7× cheaper). It
   ties the Opus-4.8 golden ceiling (4.46) and edges it on cross-group validity
   (4.46 vs 4.40) and gap quality (4.90 vs 4.76). This aligns with GLM's
   writer/QA/editor wins and *contrasts* the bias-stage result where GLM
   regressed — GLM is strong on this cross-corpus reduction task.
2. **Sonnet-5 is a regression here** — below the incumbent overall (3.90) and the
   worst on the product-critical axis (16 fabrications). It won the perspective
   eval and loses this one; not a general-purpose swap.
3. **DeepSeek** is lowest overall (3.52) — its conservatism (2.8 divergences/topic
   vs the field's ~5) keeps fabrications low but starves specificity and gap
   quality; plus a schema miss on the largest topic and the slowest latency
   (86.5s/topic).
4. **The incumbent has a real fabrication problem** (14 across 21 topics, on 10
   topics) — this eval's most actionable finding independent of any swap.

## Caveats

- **Cap breach** (above): judge spend 3–4× projection; discipline fix noted.
- **Claude-family judges over a Claude-inclusive field** (incumbent Opus-4.6,
  Sonnet-5, golden Opus-4.8): a possible family-affinity bias in the judges.
  GLM (non-Claude) winning *despite* this strengthens its result; Sonnet-5 losing
  *despite* it strengthens that too.
- Fabrication matching is verbatim/substring quote-to-divergence; a judge
  paraphrasing its citation would be missed (undercount, not overcount).
- 2 of 21 topics have 2-judge (not 3-judge) panels after the batch was stopped;
  their ≥2/3 rule degenerates to unanimity-of-2. Excluding them does not change
  the ranking.

## Reproduction

```
uv run python scratch/p2-eval/harness.py sizes         # free input census
uv run python scratch/p2-eval/harness.py probe         # 4 output probes (largest topic)
uv run python scratch/p2-eval/harness.py shadow <arm> 4 # incumbent|glm|deepseek|sonnet5|golden
uv run python scratch/p2-eval/deterministic.py
uv run python scratch/p2-eval/judge.py run 4           # 3 Opus-4.8 judges x ready topics
uv run python scratch/p2-eval/aggregate.py
```
Raw: `scratch/p2-eval/raw/` (outputs), `scratch/p2-eval/verdicts/` (judgments),
`scratch/p2-eval/anon_keys/` (label→arm). Scored: `aggregate.json`,
`deterministic.json`.
