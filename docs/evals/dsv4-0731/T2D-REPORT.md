# T2d — the direct DeepSeek API as channel C

**Task:** `TASK-EVAL-T2D-DEEPSEEK-DIRECT.md` · **Date:** 2026-08-23 · **Spend:** $1.17 / **EUR 1.09 of the 2.00 cap (54 %)**, 86 logged calls
**Reads:** T2 (`T2-REPORT.md`), T2b (`T2B-REPORT.md` incl. its §6 T2c addendum)
**Channels:** A = OpenRouter pinned to the DeepSeek provider · B = Ollama Cloud · **C = api.deepseek.com direct**

---

## 0. Verdict up front

**No dealbreaker on any of the three flash stages. Channel C is the strongest of the three on capability, and it is the same weights as channel A.** Two findings qualify that:

1. **You cannot pin a build on channel C.** The vendor exposes exactly one flash id — `deepseek-v4-flash` — and `deepseek-v4-flash-0731` is a hard HTTP 400. Channel C serves 0731 today because the vendor rolled its alias forward, not because you asked for it. Channel A's dated id is the only pin that exists, and it points at this same upstream.
2. **`reasoning_effort: "medium"` on C is not the same operating point as `reasoning: {"effort":"medium"}` on A.** Paired on 9 inputs at an identical cap, C spends **2.64× the reasoning** (9/9 samples). **A · medium ≈ C · low** (ratio 1.10). Swapping A→C at nominally the same setting silently buys a harder, slower, dearer configuration.

Everything else favours C: a **393 216** output ceiling (6× Ollama Cloud's), **100 % raw-JSON validity on 60 calls, zero repairs, zero truncations, zero empty bodies**, working prompt caching, and structural parity with channel A on all Python-checkable measures — so no judges were run, per the task.

---

## 1. Part A — characterization

### 1.1 Model id, and what the response actually proves

| question | answer | how established |
|---|---|---|
| ids on `/models` | `deepseek-v4-flash`, `deepseek-v4-pro`, `deepseek-v4-flash-vision-exp` | `GET /models` |
| a dated id? | **no** — `deepseek-v4-flash-0731`, `-20260731` and `:0731` all return **HTTP 400** naming the three supported ids | 3 probes |
| legacy aliases | `deepseek-chat` and `deepseek-reasoner` both resolve to `deepseek-v4-flash`, same `system_fingerprint` `a26a7955944dc5c60445bff77fac9c8e` | 3 probes |
| …but they differ | `deepseek-chat` returned **no** reasoning tokens; `deepseek-v4-flash` and `deepseek-reasoner` did. The aliases carry different reasoning defaults | same probes |
| **revision echo** | **no.** `response.model` echoes `deepseek-v4-flash`. No dated build string appears anywhere in the response | every call |

So T2b §5.2's caveat is **not** closed by a revision echo — the direct API is no more forthcoming than OpenRouter. It is closed by three converging pieces of evidence instead:

- **OpenRouter's endpoint listing puts the `DeepSeek` provider on `deepseek-v4-flash-0731` (1 of 30 providers) and *not* on `deepseek-v4-flash` (17 providers, no DeepSeek).** The vendor does not serve the incumbent id at all.
- **The metadata matches.** OpenRouter publishes for that endpoint: context 1 048 576, max completion 384 000, prompt $0.22/M, completion $0.66/M, cache read $0.007/M, `supported_parameters` including `reasoning_effort` and `response_format` but **not** `structured_outputs`. Every one of those matches what the direct API documents and what §1.2–§1.4 probe.
- **Tokenizer fingerprint.** On 21 byte-identical message pairs, `prompt_tokens` differs by **exactly +79, on all 21**, across inputs spanning 8 105 to 248 210 tokens. A constant offset over a 30× size range is the signature of the same tokenizer behind a fixed chat-template difference; a different tokenizer would scale with length.

**Conclusion: channel C is the 0731 build, addressed by an undated alias.** The cost of that is pinning: if the vendor rolls the alias again, channel C follows silently and there is no request-level way to notice.

### 1.2 Output ceiling — the potential dealbreaker, refuted

| `max_tokens` | result |
|---:|---|
| 8 192 · 65 536 · 131 072 · 200 000 · 384 000 · 384 001 | accepted |
| 400 000 · 1 048 576 | **HTTP 400** — `"the valid range of max_tokens is [1, 393216]"` |

**Ceiling: 393 216**, stated by the API itself, refused loudly. That is above channel A's 384 000 (OpenRouter 404s past it) and **6× channel B's 65 536**. Curator at `medium` needs ~61 k; the largest completion measured anywhere in T2d was 61 573. No stage comes close to binding.

**The trap is the default.** With `max_tokens` omitted the API caps at **8 192** and returns `finish_reason: "length"` — enough to truncate curator and assemble at `medium` on every run. An integration that forgets the parameter fails quietly in the payload and loudly only in a field nobody reads.

### 1.3 Reasoning control — accepted everywhere, portable nowhere

`reasoning_effort` is accepted at `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`. `none` returns no reasoning tokens at all. On a trivial prompt every level from `minimal` up spends ~14 reasoning tokens, so the levels can only be separated on real inputs.

**The OpenRouter-shaped form is a silent trap:** `reasoning: {"effort": "medium"}` is **accepted without error** and ignored. No 400 tells you the setting did not apply.

Measured on real inputs, the two channels' "medium" are different settings:

| stage | A · medium reasoning p50 | C · medium reasoning p50 | ratio |
|---|---:|---:|---:|
| `curator_topic_discovery` | 25 388 | 23 110 | **0.91** |
| `researcher_assemble` | 15 494 | 23 391 | **1.51** |
| `resolve_actor_aliases` | 3 423 | 7 640 | **2.23** |

Paired per-input on `resolve` at an identical 65 536 cap, the gap is **2.64× (median), 1.10–3.72, 9 of 9 samples**, with latency at **2.73×**.

**This is not an artifact of my `max_tokens` choice.** Part B ran C at 131 072 against T2b's 65 536, so A.6 re-ran `resolve` on C at 65 536: reasoning p50 moved 9 171 → 7 564 (ratio 1.21) and **5 of 9 samples went the other way**. The cap is not what drives it.

**A · medium ≈ C · low.** Same 9 inputs, same cap, `reasoning_effort: "low"`:

| | median | range | validity |
|---|---:|---|---|
| C · low ÷ A · medium reasoning | **1.10** | 0.80 – 1.73 | 9/9 raw-valid, 9/9 schema-valid |

The mismatch is stage-dependent — `curator` is already equivalent at medium — so a swap needs a **per-stage** effort mapping, not one global translation.

### 1.4 JSON mode and validity

| | result |
|---|---|
| `response_format: {"type":"json_object"}` | accepted, works |
| strict `json_schema` | not offered — `structured_outputs` absent from `supported_parameters`, same as channel A |
| **raw-JSON validity, 60 real-input calls** | **100 %** — 0 repairs needed, on all three stages |
| without `json_object`, same messages | also raw-valid — the production prompts carry the JSON contract themselves |

So `json_object` on channel C is belt-and-braces rather than load-bearing. Contrast channel B, where §6 of the T2b report showed `format` is a no-op and the repair layer is the only defence.

### 1.5 Pricing, caching, and a vendor-authoritative cost check

USD per 1M tokens (`api-docs.deepseek.com/quick_start/pricing`, fetched 2026-08-23):

| | input, cache hit | input, cache miss | output |
|---|---:|---:|---:|
| off-peak | $0.007 | $0.22 | $0.66 |
| **peak** | $0.014 | $0.44 | $1.32 |

**Peak = 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday.** Everything else, weekends included, is off-peak. OpenRouter's published rate for the same endpoint equals the **off-peak** figure, so during peak hours the direct API is twice what the OpenRouter listing implies.

**Production sits on the boundary.** `daily_run.sh` fires at **06:00 local**, which is 04:00 UTC under CEST and 05:00 UTC under CET — off-peak in both, but summer starts it at the exact minute the 01:00–04:00 block closes, and a long hydrated run reaches into the 06:00–10:00 block. An hour's schedule drift, or a DST edge, doubles the flash-stage bill without any code change.

**Caching works and is worth having.** 45.1 % of input tokens across the 42 Part-B calls were cache hits; a repeat of an identical prompt hits at ~100 % and costs **~2.6× less**. Production sends each prompt once a day, so the cold figure is the one to plan with — but a retry is nearly free.

**Cost cross-check.** The API returns no cost field, so T2d computes from the table above. `/user/balance` is the vendor's own accounting:

| | |
|---|---:|
| vendor-measured spend between snapshots | **$1.12** |
| harness-computed spend over the same window | **$1.1664** |
| deviation | **+4.1 %** |

The harness slightly over-estimates (balance resolution is one cent, and reasoning-token billing may differ marginally), but 4 % agreement confirms both the price table and that off-peak rates applied — peak rates would have been off by 100 %.

### 1.6 Normalized cost — the number to decide on

Per-call costs as logged are not comparable across arms: channel A ran 4 reps and channel C 2, so they carry different cache-hit fractions. This model instead takes each arm's **measured median token profile** and prices it at the same off-peak list rates with **cold input**, which is what production actually does — one call per input per morning, 1 curator + 3 assemble + 3 resolve.

| arm | curator $/call | assemble $/call | resolve $/call | **per day** | per year |
|---|---:|---:|---:|---:|---:|
| **A · medium** | 0.0369 | 0.0446 | 0.00557 | **$0.1874** | $68.40 |
| **C · medium** | 0.0356 | 0.0504 | 0.00837 | **$0.2119** | $77.34 |
| C · low (resolve only) | — | — | 0.00595 | — | — |

C is **13 % dearer at nominal medium, and the entire gap is the reasoning-setting mismatch, not the channel** — same vendor, same rates. On `resolve` at the matched setting the two are within 7 % ($0.00595 vs $0.00557), and on `curator`, where the mediums already agree, C is marginally *cheaper*. **Channel B is $0 marginal** (flat-rate subscription).

---

## 2. Part B — parity check

21 captured production inputs, `reasoning_effort: "medium"`, 2 reps, `json_object`, local validation against the current `src/schemas.py`. The comparison arm is T2b's `dsn-med` — same inputs, same nominal operating point on channel A — reused rather than re-measured.

Both arms are **re-validated against today's schema** rather than trusting their stored verdicts: T2b's records were scored before `fix/assemble-schema-coverage-gaps` landed on main (`2c4249f`), so comparing stored verdicts would report a schema-history artifact as a channel difference.

| | curator A | curator C | assemble A | assemble C | resolve A | resolve C |
|---|---:|---:|---:|---:|---:|---:|
| n | 12 | 6 | 36 | 18 | 36 | 18 |
| raw-JSON validity | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % |
| repairs needed | 0 | 0 | 0 | 0 | 0 | 0 |
| schema conformance | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % |
| production-usable | 100 % | 100 % | 100 % | 100 % | 88.9 % | 88.9 % |
| truncations | 0 | 0 | 0 | 0 | 0 | 0 |
| calls over 65 536 | 0 | 0 | 0 | 0 | 0 | 0 |
| mean payload count | 28.50 | 30.00 | 14.83 | 15.00 | 9.11 | 9.11 |
| Jaccard (reps) | 0.014 | 0.041 | 0.462 | 0.543 | 0.856 | 0.822 |
| count CV | 0.046 | 0.000 | 0.020 | 0.000 | 0.013 | 0.013 |
| reasoning p50 | 25 388 | 23 110 | 15 494 | 23 391 | 3 423 | 7 640 |
| completion p50 / max | 27 405 / 38 949 | 25 475 / 27 504 | 21 731 / 38 418 | 30 474 / **61 573** | 3 638 / 6 701 | 7 857 / 23 722 |
| latency p50 | 189.2 s | 204.4 s | 147.7 s | 200.0 s | 26.0 s | 58.1 s |

Stage compliance, Python-counted: `curator` **0 duplicate titles and 0 breaches of the 10–30 bound on both arms**; `assemble` **0 breaches of the 15-source cap on both arms**. `resolve`'s 88.9 % "usable" is identical on both and is not a failure — it counts inputs whose correct answer is an empty alias list.

**Verdict: no structural divergence, so no judges were run**, per the task's gate. The only material differences are reasoning volume, latency and cost — all traceable to §1.3's setting mismatch — plus slightly *better* rep-to-rep reproducibility on C (Jaccard up on two of three stages, count CV at or below A everywhere).

One number to keep: C's largest assemble completion was **61 573 tokens — 94 % of channel B's entire 65 536 ceiling.** Channel B has almost no margin on that stage; channel C uses 16 % of its own.

---

## 3. Channel decision matrix

| | **A — OpenRouter / DeepSeek** | **B — Ollama Cloud** | **C — api.deepseek.com** |
|---|---|---|---|
| weights | 0731, **dated id, pinnable** | 0731 (`deepseek-v4-flash:0731`) | 0731 — **undated alias, not pinnable** |
| output ceiling | 384 000 | **65 536** (loud 400) | **393 216** (loud 400) |
| default `max_tokens` | provider default | must be sent | **8 192 — truncates silently** |
| server-side JSON | `json_object`; no strict schema | **none — `format` is a no-op** (T2b §6) | `json_object`; no strict schema |
| raw-JSON validity measured | 100 % (108 calls) | curator 100 %, assemble 77.8 %, resolve 91.7 % | **100 % (60 calls)** |
| repair layer | optional | **required** | optional |
| reliability tail | 0 truncations, 0 empty bodies | **6.2 % empty bodies** at medium, input-driven (T2b §6.4) | 0 truncations, 0 empty bodies |
| reasoning control | `reasoning.effort` | `think` (native) / `reasoning_effort` (compat); `think:false` ignored on compat | `reasoning_effort`; **OR-shaped form silently ignored** |
| "medium" means | the reference | (its own) | **~2.6× A's on resolve; use `low` for parity** |
| cost | $0.187/day modelled | **$0 marginal** (subscription) | $0.212/day at medium; ≈ A at matched effort |
| peak/off-peak | flat | flat | **2× during 01–04 and 06–10 UTC, Mon–Fri** |
| caching | via provider | n/a | 45 % measured; ~2.6× cheaper on a repeat |
| second provider behind it | **yes — 29 other hosts on the same id** | **no** | **no** |
| integration delta | smallest — existing OpenRouter path | provider exists; reasoning mapping wrong | new transport, new cost path, effort remap |

---

## 4. Integration delta for channel C

Beyond the channel-agnostic items already in T2b §3 (local validation, repair as a first-class logged step):

1. **A new transport.** `src/agent.py` has `openrouter` and `ollama_cloud`; it has no `deepseek_direct`. Base URL `https://api.deepseek.com`, OpenAI-shaped `/chat/completions`, bearer key from a new environment variable.
2. **Never send `reasoning: {...}`.** It is accepted and ignored. Only `reasoning_effort: "<level>"` applies. A misconfigured stage would silently run at the default, not fail.
3. **A per-stage effort remap.** `A medium → C low` on `resolve` (ratio 1.10); `curator` is already equivalent at medium; `assemble` sits between (1.51×) and is uncalibrated. Do not port a single global level.
4. **Always send `max_tokens`.** The 8 192 default truncates two of the three stages at `medium`.
5. **A cost path with no cost field.** Responses carry `usage.prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` / `completion_tokens` but no price. `run_stage_log.jsonl`'s `cost_usd` must be computed from a **versioned, window-aware price table** — peak and off-peak differ by 2× — or it will be wrong by 100 % for part of the week.
6. **No provider routing and no second host.** The fp8-pin machinery is OpenRouter-only and irrelevant here. If api.deepseek.com is down, the stage is down; channel A reaches the same weights through 29 other hosts, which is an argument for A as the *fallback* even if C is the primary.
7. **`finish_reason: "length"` must be a loud stage error**, not a silent short answer — the same guard T2b §6.5 asked for on channel B.

---

## 5. Dealbreaker verdict per stage

| stage | verdict on channel C | note |
|---|---|---|
| `curator_topic_discovery` | **no dealbreaker** | ceiling used: 27 504 of 393 216 (7 %). The two channels' `medium` already agree here; C is marginally cheaper |
| `researcher_assemble` | **no dealbreaker** | ceiling used: 61 573 of 393 216 (16 %) — the same call is 94 % of channel B's entire ceiling. Effort remap uncalibrated (1.51×) |
| `resolve_actor_aliases` | **no dealbreaker** | run at `low`, not `medium`, to match channel A. At `medium` it costs 1.5× and takes 2.7× as long for reasoning nobody asked for |

**Suggested reading for the primary/fallback decision** — the owner's call, not this report's:

- **C is the capability winner** (ceiling, validity, caching, no repair dependency) and **A is the resilience winner** (a dated pinnable id and 29 alternative hosts behind the same weights). They are the same model; the choice is between pinning + redundancy and headroom + directness.
- **B is not a primary for a reasoning-heavy stage.** Its 65 536 ceiling has 6 % margin on the largest assemble call measured, `format` gives no enforcement, and 6.2 % of medium calls return nothing.
- **A → C or C → A is a cheap cross-channel fallback pair** — same weights, same prompts, same output contract, only the effort parameter needs translating.

---

## 6. Limitations

1. **2 reps, not 4.** Part B is half T2b's repetition count, so the variance figures are directional. `curator` in particular rests on 3 inputs × 2 reps.
2. **No judging.** The task gated judges on structural divergence and there was none. Quality parity is *inferred* from identical weights plus matching structural measures — it is not measured.
3. **The effort calibration is one stage.** `A medium ≈ C low` is established on `resolve` (9 paired inputs). `assemble`'s 1.51× is unmapped, and `curator` was not re-run at other levels.
4. **Costs are computed, not billed.** No cost field exists; the price table is cross-checked against `/user/balance` to ±4.1 %, at one-cent resolution.
5. **All calls were off-peak** (Sunday). Peak-hour behaviour is priced from the published table, not observed — only the rate should change, but that is an assumption.
6. **The alias could move.** Every "channel C is 0731" claim in §1.1 is true as measured on 2026-08-23 and has no request-level guarantee behind it.
7. **Nothing ran through the real `PipelineRunner`** — same limitation as T2 and T2b. A swap still needs a full `--hydrated` shadow day.
8. **Rate limits and concurrency were never stressed.** 60 calls at concurrency 4 saw no throttling; that is not a capacity finding.

---

## 7. Artifacts

| what | where |
|---|---|
| every call — channel, model tag, reasoning, tokens, computed cost, price window; **never the key** | `scratch/eval/t2d/logs/calls.jsonl` — 86 calls, $1.17 |
| model ids, balance | `scratch/eval/t2d/partA/a1_models.json`, `a2_model_ids.json` |
| price table + OpenRouter endpoint metadata for both flash ids | `scratch/eval/t2d/partA/a0_pricing.json` |
| ceiling, default `max_tokens`, reasoning surface | `scratch/eval/t2d/partA/a3_surface.json` |
| identity + `json_object` smoke | `scratch/eval/t2d/partA/a4_identity.json` |
| `/user/balance` snapshots (cost cross-check) | `scratch/eval/t2d/partA/a5_balance.jsonl` |
| `max_tokens` confound test (resolve @ 65 536) | `scratch/eval/t2d/partA/a6_maxtok_confound.py`, `a6_runs/` |
| effort calibration (resolve @ `low`) | `scratch/eval/t2d/partA/a7_effort_calibration.py`, `a7_runs_low/` |
| Part B replays (42) | `scratch/eval/t2d/runs/<stage>/<sample>.rN.json` |
| analysis — metric code imported from T2b's analyzer | `scratch/eval/t2d/analyze_d.py` → `analysis_d.json` |
| transport, key handling, window-aware pricing | `scratch/eval/t2d/t2d_lib.py` |

**Key handling.** The key was read from `~/Desktop/deepseek_api.txt` into the process at call time and used only as an `Authorization` header. It appears in no log line, no filename, no error string — HTTP error bodies are regex-scrubbed before logging. Verified: the key string appears in **no** file under `scratch/eval/t2d/`. Three early probe calls predate the price table and are uncosted (215 in / 57 out ≈ $0.000085).
