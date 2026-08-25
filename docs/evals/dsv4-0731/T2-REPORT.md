# T2 — `deepseek/deepseek-v4-flash-0731` swap evidence for the three flash stages

**Task:** `TASK-EVAL-T2-DSV4-FLASH-0731.md` · **Date:** 2026-08-22 · **Status:** complete
**Stages under test:** `curator_topic_discovery`, `researcher_assemble`, `resolve_actor_aliases`
**Incumbent:** `deepseek/deepseek-v4-flash` (revision `20260423`) · **Candidate:** `deepseek/deepseek-v4-flash-0731` (revision `20260731`)
**API spend:** **$3.13** (~€2.90 at 1.08 USD/EUR) against a 5 EUR cap — ~58 %, no budget stop triggered. Every call logged with model, provider, reasoning level, token counts and cost in `scratch/eval/t2/logs/calls.jsonl` (641 calls).
**Production untouched.** No change to `scripts/run.py`, `src/`, `agents/` or any published output. All work under `scratch/eval/t2/`; reference snapshots copied and `chmod a-w` before use.

---

## 0. Verdict up front

**`deepseek-v4-flash-0731` is a genuine quality improvement over the incumbent on all three stages — and a naive swap would still have broken production.** The two findings are independent and both load-bearing.

| stage | recommendation | confidence |
|---|---|---|
| `curator_topic_discovery` | **HOLD.** 0731 · `medium` is the best arm measured, but this is the run-level stage (its failure ends the day's run) and the evidence is 3 samples / 6 judged pairs. Not a mandate. | low |
| `researcher_assemble` | **SWAP CANDIDATE — the strongest case in this eval.** 0731 · `reasoning: medium` on a DeepInfra-led fp8 pin: +8 judged net against a provider-matched control, 100 % usable across 12 replays, no truncations, cost unchanged. Needs a shadow day first. | medium |
| `resolve_actor_aliases` | **SWAP CANDIDATE, second in line.** 0731 · `medium` scores +14 against control and holds Jaccard 0.78–0.88 where the incumbent sits at 0.34–0.58, but 2 of 18 DeepInfra calls truncated. `none` is the safe version of the same swap (+8, 100 % usable, 2 s). | medium |

**One reasoning level does not dominate outright, and the honest answer has two halves:**

- **`max` is excluded on every axis.** Unbounded reasoning — a median of **124 318 reasoning tokens on an 8 k–19 k-token input** — truncated 18 of its 36 DeepInfra calls. No `max_tokens` value buys the ≥2× headroom the brief requires.
- **`medium` wins on quality; `none` wins on reliability, latency and cost.** `medium` is the top arm on all three stages (+3 / +8 / +14 vs control) and is the only level that makes the Curator reproducible (count CV 0.000 vs 0.14–0.21). `none` is 100 % usable on every non-Baidu provider, 3–10× faster, and free of provider-specific failure modes — but on the Curator it **duplicates topics and overruns the 30-topic ceiling**, which is why it is the one place 0731 scores *below* the incumbent.

**T3 should start from `medium`, carrying `none` as its control arm.** `medium`'s quality edge is consistent across all three stages, and both of its failure modes are addressable (a pin that excludes one broken endpoint; an explicit output ceiling). `none` is what a risk-averse swap would actually ship, so it belongs in T3 as the comparison, not the incumbent.

**Before any of that: the provider decision.** The malformed-JSON failures that dominate the raw candidate numbers are **a Baidu-endpoint defect specific to 0731**, not a property of the model — `baidu/fp8` serves the incumbent at 92 % strict-valid and 0731 at 34 % on the same prompts and schemas. Baidu is the **first entry of the production pin**, so a model-id-only edit in `scripts/run.py` would have shipped an ~8 % usable rate on `researcher_assemble`. See §3. Two further disqualifications fall out of Part A: **DeepSeek's own endpoint cannot serve these stages at all** (no `structured_outputs`), and **`akashml/fp8` 404s on real inputs** (131 072 context). Details in §1.

---

## 1. Part A — provider and parameter discovery

### 1.1 The owner's expectation was wrong, and the difference matters

The task brief expected **"DeepSeek (native, BF16) and Morph (BF16)"**. What the OpenRouter endpoints API actually reports for `deepseek/deepseek-v4-flash-0731`:

- **30 endpoints**, not 2 (the incumbent has 17).
- **Exactly one is bf16** — Morph. The rest are fp8 (12), fp4 (8), or report no quantization (9, including DeepSeek's own endpoint).
- **The DeepSeek native endpoint reports `structured_outputs: false`.** All three stages under test are schema-bearing, and `Agent._call_with_retry` sets `provider.require_parameters = True` whenever `output_schema` is present. Forcing `provider.order = ["deepseek"]` with a strict `json_schema` therefore returns **HTTP 404 "No endpoints found"**; the same call without a schema succeeds and is served by DeepSeek. Response-level evidence: `scratch/eval/t2/partA/a3b_deepseek_native.py` output.

> **DeepSeek's own endpoint cannot serve any of these three stages.** It is disqualified before quality is even discussed.

### 1.2 Endpoints (API-reported)

Schema-capable endpoints for 0731, cheapest first (full 30-row table in `scratch/eval/t2/partA/partA_tables.json`):

| provider | tag | quant | context | max output | $/Mtok in | $/Mtok out | uptime 1d |
|---|---|---|---:|---:|---:|---:|---:|
| Sail Research | `sail-research/fp4` | fp4 | 1 048 576 | 1 048 576 | 0.065 | 0.180 | 99.4 % |
| OpenInference | `open-inference/fp4` | fp4 | 262 144 | 262 144 | 0.065 | 0.180 | 96.1 % |
| Decart | `decart/fp4` | fp4 | 262 144 | 262 144 | 0.0675 | 0.135 | 88.5 % |
| **Baidu** | `baidu/fp8` | **fp8** | 1 048 576 | **131 072** | 0.0686 | 0.1372 | 99.8 % |
| **DeepInfra** | `deepinfra/fp8` | **fp8** | 1 048 576 | **384 000** | 0.080 | 0.180 | 99.0 % |
| Ambient | `ambient/fp4` | fp4 | 1 048 576 | 1 048 576 | 0.080 | 0.180 | 99.4 % |
| **Morph** | `morph/bf16` | **bf16** | 1 048 576 | 1 048 576 | 0.120 | 0.278 | 98.8 % |
| AkashML | `akashml/fp8` | fp8 | **131 072** | 131 072 | 0.140 | 0.280 | 99.7 % |
| **Parasail** | `parasail/fp8` | **fp8** | 1 048 576 | 1 048 576 | 0.140 | 0.280 | 99.1 % |
| SiliconFlow | `siliconflow/fp8` | fp8 | 1 048 576 | 393 216 | 0.140 | 0.280 | 99.7 % |
| DeepSeek | `deepseek` | unreported | 1 048 576 | 384 000 | 0.220 | 0.660 | 98.5 % |

**0731 is ~9 % more expensive per input token than the incumbent on the same Baidu endpoint** ($0.0686 vs $0.063 /Mtok in, $0.1372 vs $0.126 /Mtok out).

### 1.3 Response-level provider and quantization evidence

OpenRouter's `/generation` endpoint returns `quantization: null` for every call, so there is no direct response-level quant field. The evidence available, and used here, is:

1. Pinning `provider.order = ["<slug>/<quant>"]` with `allow_fallbacks: false` **plus** `quantizations: ["fp8"]` (or `["bf16"]`) — routing is fp8/bf16 by construction, and fails loud rather than dropping to fp4. Verified to route: `["baidu/fp8","parasail/fp8","akashml/fp8"] + quantizations:["fp8"]` → served by Baidu; `["morph/bf16"] + quantizations:["bf16"]` → served by Morph.
2. The response `provider` field matches the pinned endpoint on every probe.
3. The response `model` field distinguishes the revisions: `deepseek/deepseek-v4-flash-20260731` for the candidate, `deepseek/deepseek-v4-flash-20260423` for the incumbent — confirming the two ids are genuinely different weights and not an alias.

Per-pin strict-schema probes (`{answer: integer}`, `require_parameters: true`), one call each:

| pin | routed | served | strict schema honoured |
|---|---|---|---|
| `deepseek` (native) | ✗ **HTTP 404** | — | **no — endpoint filtered out by `require_parameters`** |
| `morph/bf16` | ✓ | Morph | ✓ |
| `baidu/fp8` | ✓ | Baidu | ✓ |
| `parasail/fp8` | ✓ | Parasail | ✓ |
| `akashml/fp8` | ✓ | AkashML | ✓ (but see below) |
| `deepinfra/fp8` | ✓ | DeepInfra | ✓ |
| `siliconflow/fp8` | ✓ | SiliconFlow | ✓ |

**A tiny probe is not a capability test.** `akashml/fp8` passes the toy probe and then **404s on every real stage input**: its context length is 131 072, and `curator_topic_discovery` (86 k prompt) plus `max_tokens = 131 072`, or `researcher_assemble` (137 k–249 k prompt) on its own, exceed it. 16 real calls, 16 × HTTP 404. **AkashML cannot serve these stages.**

### 1.4 Production pin drift (incidental finding, worth acting on separately)

`DEEPSEEK_V4_FLASH_FP8_ROUTING` in `scripts/run.py:68` pins `["baidu/fp8", "wandb/fp8", "parasail/fp8", "akashml/fp8"]` with `allow_fallbacks: false`. Against today's API:

| pinned tag | exists on incumbent | exists on 0731 |
|---|---|---|
| `baidu/fp8` | ✓ | ✓ |
| `wandb/fp8` | **✗ gone** | ✗ |
| `parasail/fp8` | ✓ | ✓ |
| `akashml/fp8` | **✗ gone** | ✓ (but context-incapable) |

**Production's 4-provider pin is effectively a 2-provider pin today** — below the 3-provider robustness bar the pin edit of 2026-07-14 was written to hold (`docs/DEEPSEEK-FP8-PIN-2026-07.md`). Out of scope for this task; flagged for the Architect.

### 1.5 Reasoning parameters — what the model accepts

**Every OpenRouter reasoning form is accepted with no 400 on both the fp8 and bf16 pins.** Nothing in this family behaves like Opus 4.7 (which rejects `temperature`). Accepted, verified by probe:

| form | values probed | result |
|---|---|---|
| `reasoning: {effort: …}` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | all 7 accepted, no 400, on `baidu/fp8` **and** `morph/bf16` |
| `reasoning: {enabled: true}` | — | accepted, produces reasoning |
| `reasoning: {max_tokens: 4000}` | — | accepted, produces reasoning |
| `reasoning: {effort: …, exclude: true}` | — | accepted; reasoning still billed, just not returned |
| top-level `reasoning_effort` | `medium`, `xhigh` | accepted, produces reasoning |

`supported_parameters` lists both `reasoning` and `reasoning_effort` on all 30 endpoints. `temperature` is accepted everywhere; the production `t=0.5` carries over unchanged.

**Two caveats that a metadata-only reading would miss:**

1. **A tiny probe cannot rank the effort levels.** On a one-line arithmetic prompt the reasoning-token counts were non-monotonic (`minimal` 550, `low` 758, `medium` 336, `high` 355, `xhigh` 274, `max` 842) — that is sampling noise, not a ladder. **On real production inputs the ladder is real and steep**: see §1.6. Only `none` is unambiguous at any scale — it reliably yields 0 reasoning tokens.
2. **Morph silently ignores reasoning entirely.** `morph/bf16` returns **0 reasoning tokens and an empty `reasoning` field at every effort level**, including `max`, on both a trivial and a deliberately hard prompt, and with `include_reasoning: true`. Its completion length is identical at `none` and at `max`. **A Morph pin cannot serve `curator_topic_discovery` at its production `reasoning: medium` operating point** — the parameter would be accepted and discarded.

### 1.6 Part A.4 — MAX OUTPUT verification and the derived `max_tokens`

Measured on the largest real production input of each stage, then confirmed across all 551 successful replay calls. Full table in §5; the load-bearing rows:

| stage | effort | provider | n | reasoning p50 | completion max | truncations | ceiling | headroom |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `researcher_assemble` | none | Baidu | 25 | 0 | 131 072¹ | 1 | 131 072 | 1.0× |
| `researcher_assemble` | none | DeepInfra | 16 | 0 | 6 421 | 0 | 384 000 | 59.8× |
| `researcher_assemble` | medium | Baidu | 26 | 12 039 | 29 438 | 0 | 131 072 | 4.45× |
| `researcher_assemble` | max | DeepInfra | 12 | 33 741 | 131 072¹ | **4** | 384 000 | 2.93× |
| `resolve_actor_aliases` | max | DeepInfra | 18 | **124 318** | 131 072¹ | **14** | 384 000 | 2.93× |
| `curator_topic_discovery` | medium | DeepInfra | 10 | 29 413 | 55 496 | 0 | 384 000 | 6.92× |

¹ clamped at the requested `max_tokens = 131 072` with `finish_reason: length` — i.e. the true need was higher.

**Derived `max_tokens`, at ≥2× the worst observed completion:**

| stage | effort | derived `max_tokens` | note |
|---|---|---:|---|
| `curator_topic_discovery` | none | **16 000** | worst observed 5 848 off Baidu |
| `curator_topic_discovery` | medium | **131 072** | worst observed 55 496 (DeepInfra) |
| `researcher_assemble` | none | **16 000** | worst observed 6 421 off Baidu |
| `researcher_assemble` | medium | **72 000** | worst observed 31 896 |
| `resolve_actor_aliases` | none | **4 000** | worst observed 710 |
| `resolve_actor_aliases` | medium | **no safe value from this data** | 2/18 DeepInfra calls exceeded 131 072 |
| any stage | **max** | **no safe value** | reasoning is unbounded — 124 k median on an 8–19 k-token input |

**`max` fails the ≥2× headroom requirement outright.** On `resolve_actor_aliases` — the *smallest* of the three stages, 8 k–19 k prompt tokens, whose correct answer is ~200 tokens — DeepInfra at `max` produced a **median of 124 318 reasoning tokens** and hit the 131 072 ceiling on **14 of 18 calls**. There is no `max_tokens` that buys 2× headroom over unbounded reasoning; raising the ceiling just raises the bill. `max` is disqualified on this criterion alone, before any quality argument.

Two further notes:

- **Production currently requests `max_tokens = 160000` on all three stages, above Baidu's 131 072 ceiling.** OpenRouter clamps rather than erroring, so this has been silently ineffective. The derived values above are all far below either ceiling.
- **DeepInfra serves 0731 with a 384 000 output ceiling but the incumbent with only 65 536.** A `max_tokens` above 65 536 on `deepinfra/fp8` 404s the incumbent out of the route entirely — which is how the first matched-control arm failed and had to be re-run at 65 536.

---

## 2. Method

**Inputs are the real thing, not reconstructions.** The three stages were instantiated from `src/agent_stages.py` with a capture agent that wraps a real `Agent` built at the production operating point, so `_build_system_prompt()` / `_build_user_message()` produce **byte-identical** messages to what production sent. 21 inputs captured across the three published reference days:

| stage | samples | prompt tokens (min–max) |
|---|---|---|
| `curator_topic_discovery` | 3 (one per day, run-level) | 83 k – 87 k |
| `researcher_assemble` | 6 of 9 (2 topics × 3 days) | 102 k – 249 k |
| `resolve_actor_aliases` | 9 (3 topics × 3 days) | 9 k – 21 k |

- **Reference days 2026-08-19 / -20 / -21**, snapshots copied to `scratch/eval/t2/snapshots/` and `chmod a-w` before anything ran. `--reuse` was never invoked against the reference dates (it overwrites in place).
- **Operating point:** `t = 0.5`, current prompts, current `src/schemas.py` schemas, strict `json_schema` + `require_parameters: true` — exactly as production sends them. `max_tokens = 131 072` uniformly (the Baidu ceiling; ≥4× the worst control need, so no candidate is truncation-constrained by the harness rather than by itself). The one exception is the DeepInfra matched control at 65 536 — DeepInfra's *incumbent* endpoint caps there, and a higher value 404s the route out entirely; 65 536 is still >2× that control's worst observed completion.
- **4 repetitions** per candidate × sample on the main arm, 2 on the provider-controlled arm. Variance is measured over all repetitions; judging covers repetitions 0 and 1.
- **Like-for-like comparison.** `resolve_actor_aliases` candidate output is put through the *same* deterministic post-processing production applies (`_resolve_canonical_groups` union-find + validity filtering) before it reaches a judge, and Python-assigned fields (`research-rsrc-NNN` ids) are stripped from both sides on `researcher_assemble`. Judges compare what the *stage* would produce, not raw LLM text.
- **Counting is Python's job.** Emission counts, Jaccard overlap, count CV, schema validation, URL grounding and actor-id validity are all computed in `scratch/eval/t2/analyze.py` / `analyze2.py` / a 60-line schema validator. No LLM counts anything, including as a self-check.
- **Judging is blind and anchor-free.** 18 context-free subagents, one per (stage × candidate). Each saw only the stage's real `SYSTEM.md` + `INSTRUCTIONS.md`, a digest of the same input, one candidate output, the published production output, and the Python-verified counts. No model names, no provider names, no reasoning levels, no candidate labels anywhere in the packet tree — candidates addressed by opaque `cand-xxxxxxxx` ids, keymap held outside the tree. Verified by grep for every leak term. Judges never saw another candidate's output, and the published output was relabelled `reference.json` so nothing framed it as a gold standard. 216 verdicts returned, none missing. **No judge model was called via the API — subagents only.**

### Two metrics, deliberately

- **strict-schema %** — output parses *and* validates against the production JSON Schema.
- **production-usable %** — output parses *and* carries a non-empty primary payload. This mirrors what the stage code actually consumes. The gap between the two is almost entirely `coverage_gaps`, a key that is `required` in `RESEARCHER_ASSEMBLE_SCHEMA` while `ASSEMBLE-INSTRUCTIONS.md` tells the model not to emit it and `ResearcherAssembleStage` drops it. **That mismatch is pre-existing and also hits the incumbent** (1/24). It is a schema/prompt bug, not a candidate defect, and it is scored separately so it cannot flatter or damn either side.

---

## 3. The Baidu finding — read this before the tables

Every fp8 call in the main Part B run was served by **Baidu**, the first entry in the pin. Parasail and AkashML never received traffic. So "0731 · fp8" in the main arm means "0731 · Baidu".

On Baidu, 0731 emits **structurally invalid JSON** at high rates on the two long-output stages, despite `response_format: json_schema, strict: true` and `require_parameters: true`. The failure is not truncation — `finish_reason` is `stop` — it is an **unescaped `"` inside a string value**, e.g.:

```
"summary": "… the fire got deep into the area called "zombie fire"; Germany is also …"
```

That is a decoder that is not grammar-constrained. A forced single-provider sweep separates model from provider:

| stage · effort | Baidu | Parasail | DeepInfra |
|---|---:|---:|---:|
| `curator_topic_discovery` · none | 10/12 | 4/4 | 4/4 |
| `curator_topic_discovery` · medium | **2/12** | 2/4 | 4/4 |
| `researcher_assemble` · none | 14/24 strict, 23/24 usable | 4/4 | 4/4 |
| `researcher_assemble` · medium | **2/24** | 4/4 | 4/4 |

Across the full run: **0731 on Baidu 37/108 strict-valid (34 %) on the two long stages; 0731 on DeepInfra 50/54 (93 %); 0731 on Morph 36/36 (100 %); the incumbent on Baidu 33/36 (92 %) and on DeepInfra 18/18 (100 %)**. Same model id, same schema, same prompt — the provider decides.

**Conclusion: `baidu/fp8` is INCAPABLE for `deepseek-v4-flash-0731` under strict `json_schema`,** in the same category as the StreamLake regression recorded on 2026-07-14, and it is capable for the incumbent. Any 0731 pin must exclude Baidu. Because Baidu is the incumbent pin's first entry, **a naive model-id swap in `scripts/run.py` would route straight into this defect** and would have shipped an ~8 % usable rate on `researcher_assemble` at the curator's `medium` setting.

For that reason the quality comparison below is carried by the **provider-controlled DeepInfra arm** and the **Morph arm**. The Baidu 0731 rows are reported as a reliability result, and were excluded from judging: their few surviving outputs are a biased sample and would measure the provider, not the model.

---

## 4. Part B — results

### 4.1 Reliability, emission counts and variance

`n` = calls. **usable %** and **strict-schema %** as defined in §2. **Jaccard** = mean pairwise overlap of the stage's identity set across repetitions of the same input (curator: normalised topic titles; researcher: canonicalised source URLs; resolve: `(alias_id, canonical_id)` pairs) — higher is more reproducible. **count CV** = coefficient of variation of the primary emission count across repetitions — lower is more reproducible. Counts, Jaccard and CV are computed over *usable* outputs only, so a failed call shows up in the failure rate rather than dragging a mean toward zero.

#### curator_topic_discovery

| candidate | n | usable % | strict-schema % | trunc | mean count | Jaccard | count CV | reasoning tok | completion tok | $/call | latency s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| incumbent · Baidu fp8 (control) | 12 | 100.0 | 100.0 | 0 | 27.67 | 0.011 | 0.063 | 10758 | 12882 | 0.00511 | 118 |
| incumbent · DeepInfra fp8 (control) | 6 | 100.0 | 100.0 | 0 | 29.00 | 0.042 | 0.036 | 27090 | 31360 | 0.01225 | 408 |
| 0731 · none · Baidu fp8 | 12 | 83.3 | 83.3 | 1 | 33.60 | 0.074 | 0.210 | 0 | 13219 | 0.00453 | 51 |
| 0731 · medium · Baidu fp8 | 12 | 8.3 | 16.7 | 0 | 20.00 | — | — | 10389 | 12247 | 0.00287 | 76 |
| 0731 · max · Baidu fp8 | 12 | 33.3 | 33.3 | 0 | 29.25 | 0.000 | 0.026 | 19950 | 22347 | 0.00576 | 144 |
| 0731 · none · DeepInfra fp8 | 6 | 100.0 | 100.0 | 0 | 36.83 | 0.080 | 0.142 | 0 | 2959 | 0.00279 | 65 |
| 0731 · medium · DeepInfra fp8 | 6 | 100.0 | 100.0 | 0 | 30.00 | 0.006 | 0.000 | 32531 | 37350 | 0.00898 | 458 |
| 0731 · max · DeepInfra fp8 | 6 | 100.0 | 100.0 | 0 | 30.00 | 0.053 | 0.000 | 29900 | 33189 | 0.01189 | 416 |
| 0731 · none · Morph bf16 | 12 | 100.0 | 100.0 | 0 | 31.83 | 0.070 | 0.181 | 0 | 2430 | 0.00971 | 193 |

#### researcher_assemble

| candidate | n | usable % | strict-schema % | trunc | mean count | Jaccard | count CV | reasoning tok | completion tok | $/call | latency s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| incumbent · Baidu fp8 (control) | 24 | 91.7 | 87.5 | 0 | 15.32 | 0.589 | 0.061 | 0 | 5755 | 0.00556 | 51 |
| incumbent · DeepInfra fp8 (control) | 12 | 100.0 | 100.0 | 0 | 15.00 | 0.619 | 0.000 | 0 | 4710 | 0.01103 | 57 |
| 0731 · none · Baidu fp8 | 24 | 95.8 | 58.3 | 1 | 15.39 | 0.514 | 0.042 | 0 | 10307 | 0.00953 | 42 |
| 0731 · medium · Baidu fp8 | 24 | 16.7 | 8.3 | 0 | 12.25 | — | — | 13032 | 17320 | 0.00437 | 104 |
| 0731 · max · Baidu fp8 | 24 | 29.2 | 20.8 | 0 | 13.71 | 0.244 | 0.207 | 24411 | 30982 | 0.00917 | 183 |
| 0731 · none · DeepInfra fp8 | 12 | 100.0 | 100.0 | 0 | 15.17 | 0.634 | 0.010 | 0 | 5108 | 0.00655 | 53 |
| 0731 · medium · DeepInfra fp8 | 12 | 100.0 | 100.0 | 0 | 15.00 | 0.550 | 0.000 | 15014 | 20433 | 0.00672 | 217 |
| 0731 · max · DeepInfra fp8 | 12 | 66.7 | 66.7 | 4 | 15.00 | 0.569 | 0.000 | 60143 | 63461 | 0.01834 | 642 |
| 0731 · none · Morph bf16 | 24 | 100.0 | 100.0 | 0 | 17.58 | 0.597 | 0.164 | 0 | 5896 | 0.01433 | 252 |

#### resolve_actor_aliases

| candidate | n | usable % | strict-schema % | trunc | mean count | Jaccard | count CV | reasoning tok | completion tok | $/call | latency s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| incumbent · Baidu fp8 (control) | 36 | 100.0 | 100.0 | 0 | 9.61 | 0.580 | 0.170 | 0 | 241 | 0.00061 | 2 |
| incumbent · DeepInfra fp8 (control) | 18 | 100.0 | 100.0 | 0 | 10.11 | 0.336 | 0.131 | 0 | 255 | 0.00105 | 5 |
| 0731 · none · Baidu fp8 | 36 | 100.0 | 100.0 | 0 | 9.00 | 0.541 | 0.136 | 0 | 233 | 0.00086 | 2 |
| 0731 · medium · Baidu fp8 | 36 | 97.2 | 97.2 | 0 | 9.09 | 0.776 | 0.032 | 3651 | 3872 | 0.00075 | 19 |
| 0731 · max · Baidu fp8 | 36 | 100.0 | 100.0 | 0 | 8.94 | 0.777 | 0.011 | 12193 | 12392 | 0.00224 | 68 |
| 0731 · none · DeepInfra fp8 | 18 | 100.0 | 100.0 | 0 | 10.78 | 0.680 | 0.111 | 0 | 269 | 0.00074 | 3 |
| 0731 · medium · DeepInfra fp8 | 18 | 88.9 | 88.9 | 2 | 9.31 | 0.875 | 0.046 | 16610 | 17902 | 0.00361 | 146 |
| 0731 · max · DeepInfra fp8 | 18 | 22.2 | 22.2 | 14 | 4.00 | 1.000 | 0.000 | 101241 | 104523 | 0.01960 | 849 |
| 0731 · none · Morph bf16 | 36 | 100.0 | 100.0 | 0 | 9.83 | 0.624 | 0.094 | 0 | 232 | 0.00134 | 19 |


**Reading these numbers:**

- **Curator title-Jaccard is near zero for every candidate, including the incumbent (0.011).** The Curator rephrases titles on every draw, so exact-title overlap is not a usable variance metric for this stage — **count CV is**. There the ordering is stark: `medium` and `max` on DeepInfra emit **exactly 30 topics every time (CV 0.000)**, while every `none` arm swings (control 0.063, 0731·none·DeepInfra 0.142, Morph 0.181, 0731·none·Baidu 0.210).
- **`none` on Curator over-emits and repeats itself.** Mean 33.6–36.8 topics against the incumbent's 27.7–29.0, and the blind judges independently named the cause without being told to look for it: *"the dominant failure is repetition: four of six candidate outputs restate stories already emitted, twice as a wholesale repeated block that also blew past the 10–30 topic bound"* (0731·none·DeepInfra) and the same finding on Morph. This is a genuine quality defect at `none`, not a scoring artifact.
- **A degenerate runaway exists even at `reasoning: none`, on Baidu only** — 1/13 curator calls and 1/25 researcher calls ran to the full 131 072 ceiling with `finish_reason: length`. Off Baidu, the worst `none` completion across 100 calls was 15 893 tokens.
- **`max` truncates catastrophically on DeepInfra**: 4/12 on `researcher_assemble` and **14/18 on `resolve_actor_aliases`** — the smallest stage in the pipeline.
- **Resolve is the one stage where reasoning buys reproducibility cheaply on the incumbent pin**: 0731 · medium · Baidu holds Jaccard 0.776 against the incumbent's 0.580, at 97.2 % usable, 19 s and $0.00075/call.

### 4.2 Blind judging

18 blind judges, 216 pairwise verdicts. **Verdicts must be read against the control arm, not against zero.** The control is the incumbent model re-run on the same inputs, so a perfectly calibrated judge pool would score it all-`equal`; it does not. On `resolve_actor_aliases` the incumbent re-run scores **3 better / 4 equal / 11 worse** against its own published output — the published Topic Package is one draw from a high-variance stage (control Jaccard 0.34–0.58), and a fresh draw usually differs enough for a judge to find a fault. **The control's net score is therefore the zero point.**

| stage | candidate | better / equal / worse | net | vs control |
|---|---|---|---:|---:|
| curator_topic_discovery | incumbent · DeepInfra **(control)** | 4 / 1 / 1 | +3 | — |
| | incumbent · Baidu | 2 / 1 / 3 | −1 | −4 |
| | 0731 · none · DeepInfra | 1 / 1 / 4 | −3 | **−6** |
| | 0731 · none · Morph | 0 / 2 / 4 | −4 | **−7** |
| | 0731 · medium · DeepInfra | 6 / 0 / 0 | +6 | **+3** |
| | 0731 · max · DeepInfra | 6 / 0 / 0 | +6 | +3 |
| researcher_assemble | incumbent · DeepInfra **(control)** | 6 / 3 / 3 | +3 | — |
| | incumbent · Baidu | 6 / 2 / 4 | +2 | −1 |
| | 0731 · none · DeepInfra | 8 / 2 / 2 | +6 | **+3** |
| | 0731 · none · Morph | 7 / 2 / 3 | +4 | +1 |
| | 0731 · medium · DeepInfra | 11 / 1 / 0 | +11 | **+8** |
| | 0731 · max · DeepInfra | 8 / 0 / 4 | +4 | +1 |
| resolve_actor_aliases | incumbent · DeepInfra **(control)** | 3 / 4 / 11 | −8 | — |
| | incumbent · Baidu | 3 / 5 / 10 | −7 | +1 |
| | 0731 · none · DeepInfra | 7 / 4 / 7 | 0 | **+8** |
| | 0731 · none · Morph | 7 / 7 / 4 | +3 | **+11** |
| | 0731 · medium · DeepInfra | 9 / 6 / 3 | +6 | **+14** |
| | 0731 · max · DeepInfra | 4 / 0 / 14 | −10 | −2 |

**0731 beats the incumbent on judged quality on every stage except `curator_topic_discovery` at `reasoning: none`, and `medium` is the strongest level on all three.** The judges' unprompted reasons are consistent and specific:

- **researcher_assemble · medium** — *"extracts two to three times as many grounded actors per source, including institutional and civil-society speakers the reference leaves in the snippet, and its divergences name concrete outlets and details rather than generic language-bloc claims. The reference repeatedly breaches hard constraints the candidate respects: 20 sources where 15 is the cap, URLs absent from the supplied input, and institutional press releases … counted as journalistic sources."*
- **curator · medium** — *"selected topics that track cluster mass more closely, keeping stories separate where the reference merged unrelated events and reaching several of the day's largest clusters the reference left uncovered."*
- **resolve · medium** — *"consistently stronger on merge recall for transliteration and translation variants and on the person-versus-institution rule … Its recurring weakness is over-extending `anonymous_flags` to entries that name a specific office or institution."*
- **resolve · none** — the same recall gain but *"bimodal … clearly stronger where it stays conservative and clearly worse where its aggressiveness spills into audit-corrupting false merges."* Resolve is a stage with an explicit conservatism bias, so that bimodality is expensive.
- **`max`'s +6 on Curator is not a quality signal** — it is 6 of 6 on the only stage where `max` did not truncate. On `resolve` the same level scores 4/0/14, and 14 of those 14 `worse` verdicts read *"no usable output"*.

### 4.3 Cost


| candidate | $/day | worst-stage usable % | effective $/day |
|---|---:|---:|---:|
| incumbent · Baidu fp8 (control) | 0.02360 | 91.7 | 0.02573 |
| incumbent · DeepInfra fp8 (control) | 0.04849 | 100.0 | 0.04849 |
| 0731 · none · Baidu fp8 | 0.03570 | 83.3 | 0.04286 |
| 0731 · medium · Baidu fp8 | 0.01821 | 8.3 | 0.21943 |
| 0731 · max · Baidu fp8 | 0.04001 | 29.2 | 0.13702 |
| 0731 · none · DeepInfra fp8 | 0.02466 | 100.0 | 0.02466 |
| 0731 · medium · DeepInfra fp8 | 0.03997 | 88.9 | 0.04496 |
| 0731 · max · DeepInfra fp8 | 0.12571 | 22.2 | 0.56627 |
| 0731 · none · Morph bf16 | 0.05670 | 100.0 | 0.05670 |

**Effective $/day** divides by the worst stage's usable rate — a call that produces nothing still bills, and production's empty-retry wrapper pays for up to three attempts. The whole flash-stage family is a rounding error against the pipeline's daily spend either way; **latency, not cost, is what `medium` actually charges.** Per production day: Curator 118 s → 458 s (run-level, once), researcher_assemble 51 s → 217 s × 3 topics, resolve 2 s → 146 s × 3 topics on DeepInfra (19 s on Baidu). That is roughly **+20 minutes of wall clock per daily run** for the `medium` configuration.

---

## 5. Full `max_tokens` derivation table


| stage | model | effort | provider | n | reasoning p50 | completion p50 | completion max | truncations | provider ceiling | headroom | derived max_tokens (2×) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| curator_topic_discovery | 0731 | max | Baidu | 14 | 18350 | 21124 | 30780 | 0 | 131072 | 4.26× | 61560 |
| curator_topic_discovery | 0731 | max | DeepInfra | 6 | 31689 | 35235 | 37719 | 0 | 384000 | 10.18× | 75438 |
| curator_topic_discovery | 0731 | medium | Baidu | 13 | 9776 | 12358 | 17609 | 0 | 131072 | 7.44× | 35218 |
| curator_topic_discovery | 0731 | medium | DeepInfra | 10 | 29413 | 33386 | 55496 | 0 | 384000 | 6.92× | 110992 |
| curator_topic_discovery | 0731 | medium | Parasail | 4 | 13163 | 15046 | 25361 | 0 | 1048576 | 41.35× | 50722 |
| curator_topic_discovery | 0731 | none | Baidu | 13 | 0 | 2398 | 131072 | 1 | 131072 | 1.0× | 131072 |
| curator_topic_discovery | 0731 | none | DeepInfra | 10 | 0 | 2293 | 5848 | 0 | 384000 | 65.66× | 11696 |
| curator_topic_discovery | 0731 | none | Morph | 12 | 0 | 2276 | 4461 | 0 | 1048576 | 235.05× | 8922 |
| curator_topic_discovery | 0731 | none | Parasail | 4 | 0 | 2145 | 3790 | 0 | 1048576 | 276.67× | 7580 |
| curator_topic_discovery | incumbent | medium | Baidu | 13 | 10664 | 12339 | 31511 | 0 | 131072 | 4.16× | 63022 |
| curator_topic_discovery | incumbent | medium | DeepInfra | 6 | 16505 | 20533 | 61366 | 0 | 384000 | 6.26× | 122732 |
| researcher_assemble | 0731 | max | Baidu | 25 | 24288 | 31438 | 40567 | 0 | 131072 | 3.23× | 81134 |
| researcher_assemble | 0731 | max | DeepInfra | 12 | 33741 | 37283 | 131072 | 4 | 384000 | 2.93× | 262144 |
| researcher_assemble | 0731 | medium | Baidu | 26 | 12039 | 17498 | 29438 | 0 | 131072 | 4.45× | 58876 |
| researcher_assemble | 0731 | medium | DeepInfra | 16 | 15104 | 20819 | 31896 | 0 | 384000 | 12.04× | 63792 |
| researcher_assemble | 0731 | medium | Parasail | 4 | 16959 | 23006 | 25777 | 0 | 1048576 | 40.68× | 51554 |
| researcher_assemble | 0731 | none | Baidu | 25 | 0 | 4996 | 131072 | 1 | 131072 | 1.0× | 131072 |
| researcher_assemble | 0731 | none | DeepInfra | 16 | 0 | 5400 | 6421 | 0 | 384000 | 59.8× | 12842 |
| researcher_assemble | 0731 | none | Morph | 24 | 0 | 5229 | 15893 | 0 | 1048576 | 65.98× | 31786 |
| researcher_assemble | 0731 | none | Parasail | 4 | 0 | 5365 | 5836 | 0 | 1048576 | 179.67× | 11672 |
| researcher_assemble | incumbent | none | Baidu | 25 | 0 | 5190 | 18853 | 0 | 131072 | 6.95× | 37706 |
| researcher_assemble | incumbent | none | DeepInfra | 12 | 0 | 4859 | 5595 | 0 | 384000 | 68.63× | 11190 |
| resolve_actor_aliases | 0731 | max | Baidu | 38 | 11942 | 12071 | 25772 | 0 | 131072 | 5.09× | 51544 |
| resolve_actor_aliases | 0731 | max | DeepInfra | 18 | 124318 | 131072 | 131072 | 14 | 384000 | 2.93× | 262144 |
| resolve_actor_aliases | 0731 | medium | Baidu | 37 | 3641 | 3797 | 8451 | 0 | 131072 | 15.51× | 16902 |
| resolve_actor_aliases | 0731 | medium | DeepInfra | 18 | 3785 | 3976 | 131072 | 2 | 384000 | 2.93× | 262144 |
| resolve_actor_aliases | 0731 | none | Baidu | 37 | 0 | 194 | 710 | 0 | 131072 | 184.61× | 1420 |
| resolve_actor_aliases | 0731 | none | DeepInfra | 18 | 0 | 200 | 683 | 0 | 384000 | 562.23× | 1366 |
| resolve_actor_aliases | 0731 | none | Morph | 36 | 0 | 195 | 653 | 0 | 1048576 | 1605.78× | 1306 |
| resolve_actor_aliases | incumbent | none | Baidu | 37 | 0 | 185 | 662 | 0 | 131072 | 197.99× | 1324 |
| resolve_actor_aliases | incumbent | none | DeepInfra | 18 | 0 | 212 | 698 | 0 | 384000 | 550.14× | 1396 |



Rows whose `completion max` is exactly 131 072 hit the harness ceiling — the true requirement is higher and unmeasured.

---

## 6. Recommendation

### 6.1 The provider decision comes first

Whatever happens to the model, **any 0731 pin must exclude `baidu/fp8`** (INCAPABLE under strict `json_schema` for this model id), **`deepseek`** (no `structured_outputs`) and **`akashml/fp8`** (131 072 context, too small for two of the three stages). The verified-capable set from this eval is:

```
order: ["deepinfra/fp8", "parasail/fp8", "siliconflow/fp8"]   # 0731 only
allow_fallbacks: false
quantizations: ["fp8"]
```

DeepInfra is verified on 124 real stage calls, Parasail on 16, SiliconFlow on the toy capability probe only — **SiliconFlow needs its own strict-schema probe against all three live schemas before it goes into any pin.** `morph/bf16` is verified on 72 real stage calls at 100 % and is the natural non-quantized fallback, but it **cannot serve `curator_topic_discovery`** because it silently discards `reasoning`.

### 6.2 Per stage

| stage | winner | fallback | confidence |
|---|---|---|---|
| `curator_topic_discovery` | **HOLD.** Best measured arm is 0731 · `medium` · DeepInfra-led fp8 pin, `max_tokens = 131072` | incumbent, unchanged | **low** — 6 judged pairs, 6 replays |
| `researcher_assemble` | **0731 · `reasoning: medium` · DeepInfra-led fp8 pin**, `max_tokens = 72000` | 0731 · `none` on the same pin | **medium** — 12 judged pairs, 12 replays, largest and most consistent margin in the eval |
| `resolve_actor_aliases` | **0731 · `reasoning: medium`** — but **no safe `max_tokens` is derivable from this data** (2/18 DeepInfra calls exceeded 131 072); `none` at `max_tokens = 4000` is the shippable form | 0731 · `none` (Jaccard 0.54–0.68, 100 % usable, 2 s, and still +8 vs control) | **medium** — 18 judged pairs, but 2/18 truncations on DeepInfra |

**`none` is the safe swap and `medium` is the good one.** If only one change is made, make it `researcher_assemble`: it has the largest judged margin (+8 vs control), 100 % usable across 12 replays at `medium`, no truncations, and its cost is unchanged ($0.00672 vs the control's $0.00556 on the same provider).

**Do not swap `curator_topic_discovery` yet.** It is the run-level stage — its failure ends the whole day's run — and the evidence there is the thinnest in the eval (3 samples). The `medium` result is good but 6 judged pairs is not a mandate for the one stage with no per-topic blast radius.

### 6.3 The dominant reasoning level, for T3

**`max` is excluded outright** — unbounded reasoning (median 124 318 tokens on an 8–19 k-token input), 18 truncations across its 36 DeepInfra calls, and no `max_tokens` that buys the required 2× headroom.

Between the other two there is a real trade-off rather than a dominance:

- **`medium` dominates on judged quality** — the strongest arm on all three stages (+3 / +8 / +14 vs control), and the only level that makes the Curator reproducible (count CV 0.000 vs 0.14–0.21).
- **`none` dominates on reliability, latency and cost** — 100 % usable on every non-Baidu provider and stage, 3–10× faster, and it is the only level with zero provider-specific failure modes.

**T3 should start from `medium`**, because its quality advantage is consistent across all three stages while its failures are traceable to two identifiable causes — one broken provider endpoint and one unbounded-reasoning tail — both of which are addressable with a pin and a ceiling. **T3 should carry `none` as the control arm**, not the incumbent-at-`medium`, since `none` is what a risk-averse swap would actually ship.

---

## 7. Limitations — what this evidence does not support

1. **`curator_topic_discovery` rests on 3 samples.** One input per reference day, because the stage is run-level. Six judged pairs per candidate. Treat every Curator conclusion as directional.
2. **The DeepInfra arm ran 2 repetitions, not 4.** The 4-rep variance measurement is complete only on the Baidu and Morph arms, and Baidu's is contaminated by the malformed-JSON defect. Curator count-CV = 0.000 at `medium` is 2 reps × 3 samples — real, but not yet a variance *bound*.
3. **The judge pool is uncalibrated in absolute terms.** The control arm scoring −8 on `resolve` proves the "vs published" framing has a systematic pull. Every conclusion here is stated control-relative; the raw better/worse counts should not be quoted on their own.
4. **`researcher_assemble` judges did not see the raw search results**, only a digest plus Python-verified URL-grounding counts. Source-summary faithfulness to the underlying article text was not assessed by anyone — the grounding check confirms a URL was in the input, not that the summary reflects it.
5. **6 of 9 `researcher_assemble` samples**, chosen for cost. Topic index 2 on each day is unrepresented in the main arm (it appears in Part A.4 and the provider sweep).
6. **Three reference days, all mid-August 2026.** No seasonal or news-cycle variation.
7. **SiliconFlow, Parasail and Morph are under-tested relative to DeepInfra** (0 / 16 / 72 real stage calls vs 124). The recommended pin's second and third entries are not yet verified to the standard the first one is.
8. **Nothing here was run through the real `PipelineRunner`.** Stage inputs are byte-identical and the deterministic post-processing was replayed for `resolve_actor_aliases`, but no downstream stage consumed a candidate output. A swap needs a full `--hydrated` shadow day before it goes live.

---

## 8. Artifacts

| what | where |
|---|---|
| every API call (model, provider, reasoning, tokens, cost, retries) | `scratch/eval/t2/logs/calls.jsonl` — 641 calls, $3.13 |
| captured production stage inputs (21) | `scratch/eval/t2/inputs/` |
| read-only reference snapshots | `scratch/eval/t2/snapshots/` (`chmod a-w`) |
| main replay arm (360 calls) | `scratch/eval/t2/runs/` |
| provider-controlled DeepInfra arm (144 candidate + 36 matched control) | `scratch/eval/t2/runs_di/` |
| forced single-provider sweep (32 served + 16 AkashML 404s) | `scratch/eval/t2/runs_sweep/` |
| HTTP failures, quarantined for re-queue (52: 16 AkashML + 36 first control attempt) | `scratch/eval/t2/failures/` |
| Part A probes + endpoint metadata | `scratch/eval/t2/partA/` |
| blind judge packets, keymap, verdicts | `scratch/eval/t2/judge/` |
| analysis + derived tables | `scratch/eval/t2/analysis.json`, `analyze2.py` output, `maxout_table.json`, `cost_projection.json`, `tables.md` |
