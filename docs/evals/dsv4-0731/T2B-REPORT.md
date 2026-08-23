# T2b — `deepseek-v4-flash-0731` on the two full-precision channels

**Task:** `TASK-EVAL-T2B-CHANNELS.md` · **Date:** 2026-08-23 · **Status:** complete
**Stages:** `curator_topic_discovery`, `researcher_assemble`, `resolve_actor_aliases`
**Model (both channels):** `deepseek-v4-flash-0731`, full precision. No fp8 anywhere; Morph excluded per the owner directive.
**Channels:** **A — DeepSeek native** (OpenRouter, `provider.order = ["deepseek"]`) · **B — Ollama Cloud** (`deepseek-v4-flash:0731`)
**API spend:** **$1.70 (~EUR 1.58) of the 8 EUR cap — 20 %.** 382 calls, every one logged with channel, model tag, reasoning level, tokens and cost in `scratch/eval/t2b/logs/calls.jsonl`. The 80 % stop rule never came near firing.
**The old production model was not re-run.** T2's control rows are the fixed zero point; the published outputs remain the judge anchor.
**Production untouched.** Everything under `scratch/eval/t2b/` plus this report.

---

## 0. Verdict up front

**Both channels work, `medium` wins everywhere, and the blocker is neither channel — it is a schema bug in this repo.**

| stage | winner | fallback | confidence |
|---|---|---|---|
| `curator_topic_discovery` | **B — Ollama Cloud · `think: "medium"`** (+0.333/pair vs control, count CV **0.005**, zero duplicate titles, 116 s) | A · `medium` (+0.000/pair — level with control) | low-medium — 6 judged pairs, as in T2 |
| `researcher_assemble` | **A — DeepSeek native · `medium`** (+0.750/pair, 18/18 judged better, 100 % raw-JSON, no cap breaches) | B · `medium` (+0.639/pair) | **medium-high** — 18 judged pairs, 36 replays, both channels beat control |
| `resolve_actor_aliases` | **B — Ollama Cloud · `think: "medium"`** (+1.150/pair, Jaccard 0.84) | A · `medium` (+1.111/pair, Jaccard 0.856, no truncation) | medium — 18 pairs, but 1/36 B calls ran to the ceiling |

Three findings decide any production swap, and only one of them is about the models:

1. **Dropping strict `json_schema` breaks `researcher_assemble` schema validation outright — on every candidate, both channels, 100 % of the time.** `RESEARCHER_ASSEMBLE_SCHEMA` marks `coverage_gaps` *required*; `ASSEMBLE-INSTRUCTIONS.md` tells the model not to emit it and the stage drops it. Strict decoding used to force the key into existence. Without it the model obeys the prompt and the output fails the schema. 143 of the 144 assemble validations carry a `coverage_gaps` error, and 142 of them fail on that path **alone**. **This is a repo bug, not a channel property, and it must be fixed before either channel can ship.** Excluding it, strict-schema conformance is 94.4-100 % everywhere.
2. **`reasoning: none` is not shippable on the Curator on either channel.** Both `none` arms score *below* the control (-1.333 and -1.500 per pair) and the blind judges independently found why: wholesale repetition. One output re-emitted a 15-topic block past the 30-topic ceiling; another restated the same story a dozen times. Python counts agree — 29 and 24 duplicate titles across 12 calls, versus **0** at `medium`.
3. **Ollama Cloud's `format: "json"` is not grammar-enforcing.** At `think: false` its raw-JSON validity is **0 % on the Curator** and 19 % on `researcher_assemble` — markdown fences, despite the prompt saying "no markdown fences". The translate sidecar's existing repair (`parse_json_loose`) recovers all but 3 of the 62 affected calls, so this is a mandatory-dependency finding, not a disqualification: **channel B cannot ship without the repair layer**, channel A does not need it (raw-valid on **168 of 168** calls).

---

## 1. Part A — channel groundwork

### 1.1 Channel A — DeepSeek native via OpenRouter

| property | value | how established |
|---|---|---|
| endpoint tag | `deepseek` | endpoints API, 2026-08-23 |
| `structured_outputs` | **false** | endpoints API; `response_format` **true** |
| strict `json_schema` + `require_parameters` | **HTTP 404 "No endpoints found"** | forced probe — confirms T2 §1.1 |
| `json_object` mode | works | probe, returns `{"answer": 7}` |
| context / max output | 1 048 576 / **384 000** | API; `max_tokens = 384000` accepted, `400000` → 404 |
| pricing | $0.22 /Mtok in · $0.66 /Mtok out · **$0.007 /Mtok cache read** | API |
| reasoning | all 7 effort levels accepted; `none` → 0 reasoning tokens | probe |
| served revision | response `model` echoes `deepseek/deepseek-v4-flash-0731` | see caveat below |

**Served-revision caveat, stated rather than papered over.** The task asked for response-`model` evidence reading `20260731`. The DeepSeek native endpoint **echoes the requested alias**, not the dated build — every one of the 144 channel-A calls returned `deepseek/deepseek-v4-flash-0731`. T2 §1.3 obtained `deepseek-v4-flash-20260731` from *fp8* providers, which expand the alias; the native endpoint does not. The revision evidence available here is the alias plus `provider: "DeepSeek"` on every response. Treat "served revision = 20260731" as **unconfirmed at response level on this channel**.

**Prompt-driven JSON needs no prompt change.** All three stages' `INSTRUCTIONS.md` already carry a full example of the output object and the line *"Output only the JSON object. No commentary, no markdown fences, no preamble."* The captured production messages were therefore replayed **byte-identical**; nothing was appended to teach the model a shape. The strict schema was belt-and-braces over a contract the prompt already stated.

### 1.2 Channel B — Ollama Cloud

| property | value | how established |
|---|---|---|
| model tag | **`deepseek-v4-flash:0731`** (local daemon alias `deepseek-v4-flash:0731-cloud`) | `GET https://ollama.com/v1/models` — 19 cloud models, this among them |
| routes that work | local daemon `/api/chat` and `/api/generate`; `https://ollama.com/api/*`; `https://ollama.com/v1/*` | all four probed |
| **prompt truncation** | **none** | `prompt_eval_count` 86 233 / 248 190 / 18 736 vs OpenRouter's 86 253 / 248 210 / 18 756 on the same messages — a constant 20-token chat-template delta. **`num_ctx` changes nothing**; the cloud runtime sizes its own context |
| max output | **65 536, enforced LOUDLY** — `HTTP 400 "max_tokens (65537) exceeds model's maximum output tokens (65536)"` | probe |
| `format: "json"` | accepted, **not grammar-enforcing** — see §2.1 |
| `format: <JSON Schema>` | accepted; returns valid JSON | probe |
| reasoning | `think: false / true / "low" / "medium" / "high"` all accepted; `medium` produces 13 k-109 k characters of `thinking` on real inputs | probe + 144 replays |
| reasoning-token accounting | **not reported separately** — `eval_count` is the total; only `thinking` character length is observable | all replays |
| pricing | **flat-rate subscription; no per-token cost field in any response** | 144 calls, $0 marginal |

Two things a metadata-only reading would miss, both measured on real inputs:

- **The 65 536 ceiling is a hard channel constraint, and it binds.** It is *below* what T2 §5 recorded 0731 needing at `medium` on other providers (curator 55 496; resolve exceeded 131 072 on 2/18 DeepInfra calls). See §1.4.
- **The loud 400 is a feature.** OpenRouter silently clamps an over-ceiling `max_tokens` (the defect `TASK-FLASH-PIN-REPAIR` fixed); Ollama Cloud refuses the call and says the number. A misconfiguration cannot go unnoticed for six weeks here.

### 1.3 Two surfaces, two different defaults — this matters for the framework

`src/agent.py` already carries provider `ollama_cloud` (`base_url https://ollama.com/v1`, `OLLAMA_API_KEY`), i.e. the **OpenAI-compatible** surface, while the translate sidecar uses the **native** API. They do not behave the same. Measured on the same real Curator input (native references: `think:false` → 1 463 completion tokens and fenced JSON; `think:"medium"` → 32 358 tokens, raw-valid):

| compat-surface request | completion tokens | reasoning returned | raw-valid JSON |
|---|---:|---|---|
| no reasoning parameter at all | 33 579 | yes (`message.reasoning`) | yes |
| `think: "medium"` | 51 714 | yes | yes |
| `reasoning_effort: "medium"` | 46 342 | yes | yes |
| **`think: false`** | **38 760** | **yes — ignored** | yes |
| **`reasoning_effort: "none"`** | 65 536 (**hit the cap**) | no | **no** |

**On the compat surface, reasoning is ON by default and `think: false` does not turn it off — only `reasoning_effort: "none"` does.** That is the opposite default from the native route the sidecar uses, and `src/agent.py` maps `reasoning="none"` to `extra_body["reasoning"] = {"effort": "none"}` for OpenRouter but to `extra_body["think"]` for `ollama`/`ollama_cloud` — i.e. **the mapping the Agent layer has today is the one that does not work.** (Its `{"effort": ...}` form is untested on this surface; `reasoning_effort` is the form proven here.)

### 1.4 Derived `max_tokens` — and where the 2× rule cannot be met

Worst completion observed on the **largest real input** of each stage, per channel, plus T2 §5's larger-*n* figures for 0731 on other providers where those are higher:

| stage | effort | A: native | B: Ollama | T2 (other providers) | worst | **set to** | headroom |
|---|---|---:|---:|---:|---:|---:|---:|
| `curator_topic_discovery` | none | 1 952 | 1 463 | — | 1 952 | **8 000** | 4.10× |
| `curator_topic_discovery` | medium | 17 304 | 32 358 | 55 496 | 55 496 | **65 536** | **1.18×** |
| `researcher_assemble` | none | 5 361 | 5 599 | — | 5 599 | **16 000** | 2.86× |
| `researcher_assemble` | medium | 26 981 | 16 488 | 31 896 | 31 896 | **65 536** | 2.05× |
| `resolve_actor_aliases` | none | 175 | 222 | — | 222 | **4 000** | 18.02× |
| `resolve_actor_aliases` | medium | 3 046 | 3 189 | >131 072 (2/18) | >131 072 | **65 536** | **0.50×** |

**The ≥2× headroom rule cannot be satisfied for `medium` on Ollama Cloud.** 65 536 is the channel's hard maximum, and on two of three stages that is below 2× the worst figure on record. Both channels were given the same value so the comparison stays like-for-like; channel A could go to 384 000 if it were pinned alone.

The empirical answer to whether that matters is in Part B: **across 168 `medium` calls, exactly one truncated** — `oll-med` on `resolve_actor_aliases`, which ran the full 65 536 (§2.1). T2's unbounded-reasoning tail is real but rare; it is a monitored risk, not a blocker.

---

## 2. Part B — results

**Method.** The same 21 captured production inputs from `scratch/eval/t2/inputs/` (3 curator, 9 assemble, 9 resolve), byte-identical messages, no new snapshot work. 4 candidates × 21 samples × **4 repetitions = 336 calls**, all completed. Operating point `t = 0.5`, production prompts, `max_tokens` per §1.4. Channel A in `json_object` mode, channel B with `format: "json"` — the closest equivalent each channel offers, since neither can be given a strict schema on the terms the owner set. All counting, validity checking, Jaccard and CV are Python (`analyze.py`); no LLM counts anything, including as a self-check.

**Three metrics, deliberately.** *raw-JSON* = plain `json.loads`, nothing forgiven. *post-repair* = `parse_json_loose` from `src/translate/core.py`, the sidecar precedent (fence strip → outermost-brace extract → trailing-comma clean). *production-usable* = parses **and** carries a non-empty primary payload — what the stage code actually consumes.

### 2.1 Reliability, validity, variance

| candidate | stage | n | raw JSON % | post-repair % | strict % | strict *ex* `coverage_gaps` % | usable % | trunc | mean count | Jaccard | count CV | out p50 | out max | lat p50 s | $/call |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A `none` | curator | 12 | **100** | 100 | 100 | 100 | 100 | 0 | 28.33 | 0.117 | 0.120 | 2 121 | 2 705 | 18.6 | 0.0094 |
| A `none` | assemble | 36 | **100** | 100 | 0 | 100 | 100 | 0 | 15.42 | 0.625 | 0.042 | 5 015 | 6 615 | 32.8 | 0.0150 |
| A `none` | resolve | 36 | **100** | 100 | 100 | 100 | 97.2 | 0 | 9.47 | 0.471 | 0.170 | 196 | 703 | 2.3 | 0.0017 |
| A `med` | curator | 12 | **100** | 100 | 100 | 100 | 100 | 0 | 28.50 | 0.014 | 0.046 | 27 405 | 38 949 | 189.2 | 0.0183 |
| A `med` | assemble | 36 | **100** | 100 | 0 | 100 | 100 | 0 | 14.83 | 0.462 | 0.020 | 21 731 | 38 418 | 147.7 | 0.0155 |
| A `med` | resolve | 36 | **100** | 100 | 100 | 100 | 88.9 | 0 | 9.11 | **0.856** | 0.013 | 3 638 | 6 701 | 26.0 | 0.0026 |
| B `none` | curator | 12 | **0** | 91.7 | 91.7 | 91.7 | 91.7 | 0 | 27.64 | 0.068 | 0.296 | 2 157 | 4 042 | 13.9 | 0 |
| B `none` | assemble | 36 | **19.4** | 97.2 | 0 | 94.4 | 97.2 | 0 | 15.06 | 0.527 | 0.026 | 4 473 | 7 092 | 21.4 | 0 |
| B `none` | resolve | 36 | **63.9** | 100 | 100 | 100 | 94.4 | 0 | 9.67 | 0.561 | 0.204 | 205 | 708 | 1.6 | 0 |
| B `med` | curator | 12 | 100 | 100 | 100 | 100 | 100 | 0 | 30.08 | 0.036 | **0.005** | 33 691 | 48 679 | 116.0 | 0 |
| B `med` | assemble | 36 | 77.8 | 100 | 0 | 100 | 100 | 0 | 15.00 | 0.446 | **0.000** | 21 048 | 43 627 | 79.2 | 0 |
| B `med` | resolve | 36 | 91.7 | 97.2 | 97.2 | 97.2 | 86.1 | **1** | 8.74 | 0.840 | 0.066 | 3 645 | 65 536 | 16.2 | 0 |

**Reading these numbers:**

- **Channel A never emitted a byte of invalid JSON** — **168/168** raw-valid across both levels and all three stages, with `json_object` mode and no repair. That is the single cleanest result in the table.
- **Channel B's raw validity is a reasoning-level artefact.** At `think: false` it fences its output (0 % raw on the Curator); at `medium` it mostly does not (78-100 %). **62 of 168** B calls needed repair, and the sidecar's `parse_json_loose` recovered all but **three**. **Ship B only with that repair in the path.**
- **`strict %` is 0 on `researcher_assemble` for all four candidates** and 94.4-100 % once the single `$.coverage_gaps` path is excluded. The taxonomy over all 336 records: 143 × `$.coverage_gaps`, 3 × unparseable, and 4 × a truncated `$.sources[i]` field (`outlet` cut to `out` at indices 9 and 10 of two outputs). Nothing else.
- **`medium` is the only level that makes the Curator reproducible.** Count CV 0.005 (B) and 0.046 (A) at `medium`, against 0.120 (A) and 0.296 (B) at `none`. Curator title-Jaccard is near zero for every candidate — the stage rephrases titles on every draw, so it is not a usable variance metric here, exactly as T2 §4.1 found; count CV is.
- **`medium` also fixes rule compliance.** Python-counted, over 12 curator calls each: duplicate titles 29 (A `none`) and 24 (B `none`) → **0** at `medium` on both channels; outside the 10-30 bound 1 and 3 → 0 (A) and 1 (B). On `researcher_assemble`, over-the-15-source-cap outputs 6 (A `none`) and 5 (B `none`) → **0** on both at `medium`.
- **The one truncation** is `oll-med` on `resolve_actor_aliases`: 65 536 tokens, `done_reason: length`. That is T2's unbounded-reasoning tail on the smallest stage in the pipeline, reproduced on a new channel — 1 in 36.
- **`resolve` usable % is the weakest column everywhere** (86.1-97.2). It is not a parse problem: these are outputs whose `aliases[]` array is legitimately empty, which the "non-empty primary payload" definition scores as unusable. An empty alias list is a valid answer for the stage, so read this column as a floor, not a defect rate.

### 2.2 Blind judging

**Protocol, unchanged from T2 §2.** 12 context-free subagent judges, one per (stage × candidate); reps 0 and 1 judged; **165 verdicts returned, none missing**. Each judge saw only the stage's real `SYSTEM.md` + `INSTRUCTIONS.md`, a digest of the same input, one candidate output, the published output relabelled `reference.json`, and Python-verified counts. Opaque `j-`/`item-` ids, keymap held outside the packet tree, verified by grep for every identifying term (`deepseek`, `ollama`, `0731`, `openrouter`, channel and candidate labels — zero hits; the residual matches are news content such as "payroll" and "an effort to"). **No judge model was called through the API — subagents only.** `resolve_actor_aliases` candidates were put through the production post-processing (`_resolve_canonical_groups`, imported from `src/agent_stages.py`) and both sides reduced to the same merge-decision shape, so judges compare what the *stage* would produce.

**Verdicts are control-relative.** T2's control rows are the zero point and were not re-run. Because T2 judged a different number of pairs per stage, the delta is computed on the **per-pair rate**.

| stage | candidate | better/equal/worse | net | pairs | net/pair | control/pair | **Δ/pair** |
|---|---|---|---:|---:|---:|---:|---:|
| curator | A `none` | 0 / 1 / 5 | −5 | 6 | −0.833 | +0.500 | **−1.333** |
| | A `med` | 4 / 1 / 1 | +3 | 6 | +0.500 | +0.500 | +0.000 |
| | B `none` | 0 / 0 / 5 | −5 | 5 | −1.000 | +0.500 | **−1.500** |
| | **B `med`** | 5 / 1 / 0 | +5 | 6 | +0.833 | +0.500 | **+0.333** |
| assemble | A `none` | 11 / 5 / 2 | +9 | 18 | +0.500 | +0.250 | +0.250 |
| | **A `med`** | **18 / 0 / 0** | +18 | 18 | +1.000 | +0.250 | **+0.750** |
| | B `none` | 10 / 4 / 3 | +7 | 17 | +0.412 | +0.250 | +0.162 |
| | B `med` | 16 / 2 / 0 | +16 | 18 | +0.889 | +0.250 | +0.639 |
| resolve | A `none` | 6 / 4 / 8 | −2 | 18 | −0.111 | −0.444 | +0.333 |
| | A `med` | 13 / 4 / 1 | +12 | 18 | +0.667 | −0.444 | +1.111 |
| | B `none` | 7 / 5 / 6 | +1 | 18 | +0.056 | −0.444 | +0.500 |
| | **B `med`** | 12 / 5 / 0 | +12 | 17 | +0.706 | −0.444 | **+1.150** |

**Like-for-like on T2's own 6-sample assemble subset** (t0/t1 only — T2 limitation #5 left topic index 2 unrepresented), against its control net of +3 over 12 pairs: A `none` **+4**, A `med` **+9**, B `none` **+0**, B `med` **+8**. The full-9 and subset readings agree on the ordering.

**What the judges said, unprompted:**

- **Curator, `none`, both channels** — *"the candidate degenerates: about a dozen of its 30 entries restate the US $40 trillion debt story … leaving roughly 15 distinct stories"*; *"entries #20-#34 are a near-verbatim re-emission of #6-#19 … about 15 distinct stories in 34 slots"*. This is the same defect T2 §4.1 found at `none`, now reproduced on both full-precision channels.
- **Curator, `medium`** — *"candidates consistently discover more of the day's actually-large micro-clusters than the references do, and they keep topics as single concrete stories instead of roundups"*. The recurring candidate weakness is format, not fabrication: one output collapsed 18 of 30 summaries below the 2-4 sentence bound.
- **`researcher_assemble`, `medium`, channel A — 18/18 better, the largest margin in either eval.** *"Every candidate holds the explicit 5-to-15 source bound, draws only on journalistic outlets, and extracts markedly more actors — typically two to three times as many … the references repeatedly substitute institutional or advocacy primary sources (WHO/UNDP/Oxford Vaccine Group, mofa.gov.ae, mfa.gov.cn, Amnesty, HRW, MSF …), twice under-select at 10 sources from pools of 179 to 280 URLs, once emit 20 sources"*.
- **`researcher_assemble`, channel B** — same strength, one extra weakness: *"character-level URL corruption, present in seven of eighteen items"*, and one output that repeated a single URL five times. Channel A's judges recorded URL defects too but fewer.
- **`resolve`, `medium`** — *"the candidate … never merged a person into the institution they speak for, never merged two distinct named individuals, and never flagged a named person or a specific institution, whereas reference did all three"*. The candidates' recurring weakness is over-flagging borderline collective institutions ("North Korean authorities").

**Judge-pool caveat, carried over from T2 limitation #3.** The framing pull toward the candidate is real and is precisely why every number above is stated control-relative. On `resolve` the reference is the published Topic Package — one draw from a high-variance stage — which is why the control itself sits at −0.444/pair.

### 2.3 Cost and latency, per production day

One production day = 1 Curator call (run-level) + 3 topics × (`researcher_assemble` + `resolve_actor_aliases`).

| candidate | $/day | usable-adjusted $/day | wall-clock s/day |
|---|---:|---:|---:|
| A `none` | 0.0597 | 0.0614 | 124 |
| A `med` | 0.0725 | 0.0815 | 710 |
| B `none` | **0** | **0** | 83 |
| B `med` | **0** | **0** | 402 |

Channel B is free at the margin (flat-rate subscription; no cost field in any response) and **1.8× faster than A at `medium`**. Channel A at `medium` costs about **7 cents a day** — a rounding error against the pipeline, and cheaper than the list price suggests because DeepSeek's implicit prompt cache hit on the repeat draws (`cached_tokens` 86 144 of 86 253 on rep 1 of an identical curator prompt, billed at $0.007/Mtok instead of $0.22). **Latency, not cost, is what `medium` charges**: +10 min/day on channel A, +5 min/day on channel B.

---

## 3. The framework delta a production swap needs

No implementation here — this is the list of what `src/agent.py` and its callers must gain. It is **shorter than expected for channel B and longer than expected for the schema layer.**

**Blocking for either channel:**

1. **Fix the `coverage_gaps` schema/prompt mismatch.** `RESEARCHER_ASSEMBLE_SCHEMA` requires a key the prompt forbids and the stage discards. Under strict decoding this was invisible; without it, assemble output never validates. Remove `coverage_gaps` from `required` (or from the schema), a `src/schemas.py` change of one line — but a **contract change**, so it is the Architect's call, not drift. T2 §2 already flagged it as pre-existing and hitting the incumbent 1/24; T2b shows it becomes total.
2. **A no-strict-schema validation path.** Today `Agent` sets `response_format: json_schema, strict: true` whenever `output_schema` is present and relies on decode-time enforcement. Neither channel supports that. The stages need: `json_object` (A) / `format: "json"` (B) on the wire, then **local validation against the same `src/schemas.py` object**, then the repair policy. The defensive parser chain (`_extract_dict`, `_parse_json`, `_parse_or_retry_structured`) already exists; what is missing is an explicit *validate-and-report* step so a schema miss is a loud stage error rather than a silent pass-through.
3. **Adopt the repair policy as a first-class, measured step.** `parse_json_loose` (`src/translate/core.py`) is the precedent and it is sufficient — but on channel B it is load-bearing, not optional (52/144 calls). Raw-vs-repaired must be **logged separately per call** in `run_stage_log.jsonl`, or a channel silently degrading into fence-wrapping becomes invisible.

**Channel B (Ollama Cloud) specifically — smaller than expected, because the provider already exists:**

4. `src/agent.py` **already has** `provider: "ollama_cloud"` (`https://ollama.com/v1`, `OLLAMA_API_KEY`). The compat surface carries reasoning and accepts `response_format`. **No new transport is required.**
5. **The reasoning mapping is wrong for this surface.** `_call_with_retry` sends `extra_body["think"] = <str|bool>` for `ollama*` providers. Measured: **`think: false` is ignored on the compat surface** (38 760 completion tokens, reasoning still returned) and reasoning is **on by default**. `reasoning_effort: "none"` is the form that works. Any stage wanting `reasoning="none"` on this channel silently gets `medium`-ish behaviour and a 25× token bill under the current mapping.
6. **A $0 / flat-rate cost path.** Ollama responses carry no `usage.cost`. `run_stage_log.jsonl`'s `cost_usd` must accept "not billed per token" rather than recording 0 as if it were a measurement — otherwise cost dashboards silently under-report a subscription.
7. **Token accounting differs.** The native route reports `prompt_eval_count` / `eval_count` with reasoning folded into the total and no separate reasoning count; the compat route reports OpenAI-shaped `usage` plus a `message.reasoning` field. Anything reading `reasoning_tokens` gets `None` here.
8. **A 65 536 output ceiling and its loud 400.** `max_tokens` must be clamped per channel before the request, and the 400 must be treated as a configuration error (non-retryable), not a transient.
9. **No `provider_routing`.** The fp8-pin machinery (`order`, `allow_fallbacks`, `quantizations`, `require_parameters`) is OpenRouter-only and is already gated on `provider == "openrouter"`. Channel B has one endpoint and no pin — which also means **no fail-loud-to-a-second-provider behaviour**: if Ollama Cloud is down, the stage is down. A cross-channel fallback (B primary → A fallback) would be new wrapper code in the `FlashStageWithFallback` family.

**Channel A (DeepSeek native) specifically:**

10. **Pin `provider.order = ["deepseek"]` with `allow_fallbacks: false` and NO `quantizations` filter.** The native endpoint reports quantization `unknown`; an fp8 filter excludes it. This is the opposite of every existing pin in `scripts/run.py`, so it needs its own named constant and a comment saying why the filter is absent.
11. **Never send `require_parameters: true` with a schema on this route** — that is the 404. It is currently injected automatically whenever `output_schema` is set, so item 2 above and this are the same code path.

**Not required:** any prompt change. All three stages already specify their JSON shape and forbid fences.

---

## 4. Recommendation

- **Do not swap `curator_topic_discovery` yet.** Best measured arm is B · `medium` at +0.333/pair, but this is the run-level stage, the evidence is 6 judged pairs, and its `medium` ceiling has 1.18× headroom against T2's worst recorded figure. Same conclusion T2 reached, for the same reason.
- **`researcher_assemble` is the swap to make first, on channel A · `medium`.** 18/18 judged better, +0.750/pair against control, 100 % raw-JSON across 36 replays, no truncation, no cap breaches, ~4 cents a day. B · `medium` is a credible fallback at +0.639 but adds URL corruption and a repair dependency.
- **`resolve_actor_aliases`: both `medium` arms are strong** (+1.111 A, +1.150 B) and reproducibility roughly doubles (Jaccard 0.47-0.56 → 0.84-0.86). Prefer **A** despite B's marginally higher score: A had zero truncations where B ran one call to the ceiling, and this is the stage T2 identified as having an unbounded-reasoning tail that 65 536 cannot cover.
- **`reasoning: none` is not a shippable control arm on the Curator** on either channel. If a risk-averse configuration is wanted, it must be `medium` on a channel with headroom — which today means channel A.
- **Nothing ships until item 1 of the framework delta lands.** A stage whose output never validates is not a swap, it is an outage.

---

## 5. Limitations

1. **`curator_topic_discovery` rests on 3 inputs / 6 judged pairs per candidate** — the stage is run-level. Directional only, as in T2.
2. **Served revision is unconfirmed at response level on channel A** (§1.1). The alias is echoed; the dated build is not.
3. **The `max_tokens` derivation for `medium` is ceiling-limited, not data-limited** (§1.4). Two of three stages sit below the 2× bar because 65 536 is all Ollama Cloud allows. The observed truncation rate (1/168) is reassuring but is not a bound.
4. **`format: <JSON Schema>` on channel B was probed but not run as a main arm.** It works and it removed the fencing in a single real-input test; quantifying what it buys against `format: "json"` is a follow-up, and it may make channel B's repair dependency disappear.
5. **The judge pool is uncalibrated in absolute terms** and pulls toward the candidate; every number is stated control-relative for that reason.
6. **T2's control rows were measured on a different sample count per stage.** Deltas are computed per-pair, and the assemble comparison is additionally reported on T2's own 6-sample subset — but the controls themselves are second-hand, not re-measured.
7. **Nothing was run through the real `PipelineRunner`.** Inputs are byte-identical and `resolve` post-processing was replayed, but no downstream stage consumed a candidate output. A swap needs a full `--hydrated` shadow day.
8. **Three reference days, all mid-August 2026.** No seasonal or news-cycle variation.
9. **Ollama Cloud rate limits and availability were never stressed.** 168 calls at concurrency 4 saw no throttling; that is not a capacity finding, and the channel has no second provider behind it.

---

## 6. Artifacts

| what | where |
|---|---|
| every call (channel, model tag, reasoning, tokens, cost) | `scratch/eval/t2b/logs/calls.jsonl` — 382 calls, $1.70 |
| channel capability probes (A.1/A.2) | `scratch/eval/t2b/partA/a1_a2_results.json` |
| context-truncation probe | `scratch/eval/t2b/partA/a3_context.json` |
| max-output measurement + derivation | `scratch/eval/t2b/partA/a3_maxout.json`, `derived_max_tokens.json` |
| Agent-layer / compat-surface probes | `scratch/eval/t2b/partA/a4_agent_layer.json`, `a5_compat_vs_native.json`, `a6_compat_reasoning_off.json` |
| Part B replays (336) | `scratch/eval/t2b/partB/runs/<candidate>/<stage>/<sample>.rN.json` |
| analysis | `scratch/eval/t2b/analyze.py` → `analysis.json` |
| blind judge packets, keymap, verdicts | `scratch/eval/t2b/judge/packets/`, `keymap.json`, `verdicts/`, `verdicts_scored.json` |
| transport + repair policy used | `scratch/eval/t2b/t2b_lib.py` |
