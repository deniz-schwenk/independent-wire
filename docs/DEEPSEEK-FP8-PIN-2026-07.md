# DeepSeek fp8 provider pin — decision record (2026-07)

**Status:** applied (branch `fix/deepseek-fp8-pin`).
**Date of verification calls:** 2026-07-02, from the production Mac Mini with the production `OPENROUTER_API_KEY`.
**Task:** `TASK-DEEPSEEK-FP8-PIN.md`. **Motivation:** the QA-stage eval proved fp4 quantization causes fabrications in DeepSeek V4 (disqualifying fabrication at fp4; 0/9 at Baidu fp8). Five production stages ran on DeepSeek via OpenRouter with **no quantization pin**, so OpenRouter could route any call to an fp4 provider — a silent integrity risk, most acutely for `hydration_aggregator_phase1` (attributional fidelity).

## The 5 pinned stages

| Stage | Model | `create_agents*` |
|---|---|---|
| curator_topic_discovery | deepseek-v4-flash | `create_agents` |
| researcher_assemble | deepseek-v4-flash | `create_agents` |
| resolve_actor_aliases | deepseek-v4-flash | `create_agents` |
| consolidator | deepseek-v4-pro | `create_agents` |
| hydration_aggregator_phase1 | deepseek-v4-pro | `create_agents_hydrated` |

## Method

Per the eval's routing facts (treated as ground truth):

- The endpoints API's `supported_parameters` is **optimistic** — a provider may claim `structured_outputs` and still fail strict `response_format`. Capability is verified empirically per provider.
- `/generation` returns `quantization: null` — the served quant **cannot be read back** after the fact. fp8 must be guaranteed **by construction** (routing constraints), never audited post-hoc.

**Discovery** (candidate list only): `GET /api/v1/models/{model}/endpoints`, filtered to `quantization == "fp8"`.

**Verification** (per candidate, per model): one forced single-provider call —
`provider: {order: ["<tag>/fp8"], allow_fallbacks: false, quantizations: ["fp8"], require_parameters: true}` — carrying a minimal strict json-schema `response_format` (`{answer: integer}`). This mirrors the **faithful production config** (`require_parameters: true` is what `src/agent.py` already injects for schema calls). A provider **PASSES** iff HTTP 200, the returned content is schema-conformant JSON, and `response.provider` matches the forced endpoint. Transient `429`s were retried; the fp8 providers that `404`'d under `require_parameters` were re-probed **without** it, to distinguish a genuine capability gap from a `require_parameters` artifact.

## Verified provider matrix

Result legend: **VERIFIED** = fp8 endpoint + schema-conformant strict output (empirical). **INCAPABLE** = fp8 but OpenRouter refuses to route a `response_format` request there even without `require_parameters` (`404 No endpoints found`) → genuinely no strict-structured-output support for this model. fp4 / unknown-quant endpoints are disqualified up front (never fp8 by construction).

### deepseek-v4-pro — **3 verified** (meets ≥3)

| Provider | tag | endpoint status | quant | strict structured output | verdict |
|---|---|---|---|---|---|
| **Baidu** | `baidu/fp8` | 0 | fp8 | PASS (1st try) | **VERIFIED** |
| **WandB** | `wandb/fp8` | 0 | fp8 | PASS (after transient 429) | **VERIFIED** |
| **Parasail** | `parasail/fp8` | −2 | fp8 | PASS (after transient 429) | **VERIFIED** (endpoint deranked, see note) |
| StreamLake | `streamlake/fp8` | 0 | fp8 | 404 with & without require_parameters | INCAPABLE |
| GMICloud | `gmicloud/fp8` | 0 | fp8 | 404 with & without require_parameters | INCAPABLE |
| Novita | `novita/fp8` | 0 | fp8 | 404 with & without require_parameters | INCAPABLE |
| SiliconFlow | `siliconflow/fp8` | 0 | fp8 | 404 with & without require_parameters | INCAPABLE |
| DeepInfra | `deepinfra/fp4` | 0 | **fp4** | — | DISQUALIFIED (fp4 fabrication risk) |
| AtlasCloud | `atlas-cloud/fp4` | 0 | **fp4** | — | DISQUALIFIED (fp4) |
| DeepSeek, DigitalOcean, Alibaba, Venice, Together, Fireworks | — | — | **unknown** | — | EXCLUDED (fp8 not guaranteed by construction) |

Baidu + WandB + Parasail are the **complete** set of structured-output-capable fp8 pro endpoints; there is no headroom beyond 3.

### deepseek-v4-flash — **5 verified**

| Provider | tag | endpoint status | quant | strict structured output | verdict |
|---|---|---|---|---|---|
| **Baidu** | `baidu/fp8` | 0 | fp8 | PASS (1st try) | **VERIFIED** |
| **WandB** | `wandb/fp8` | 0 | fp8 | PASS (1st try) | **VERIFIED** |
| **StreamLake** | `streamlake/fp8` | 0 | fp8 | PASS (1st try) | **VERIFIED** |
| **Parasail** | `parasail/fp8` | 0 | fp8 | PASS (1st try) | **VERIFIED** |
| **AkashML** | `akashml/fp8` | 0 | fp8 | PASS (after transient 429) | **VERIFIED** |
| GMICloud | `gmicloud/fp8` | 0 | fp8 | 404 with & without require_parameters | INCAPABLE |
| SiliconFlow | `siliconflow/fp8` | 0 | fp8 | 404 with & without require_parameters | INCAPABLE |
| Novita | `novita/fp8` | 0 | fp8 | 404 with & without require_parameters | INCAPABLE |
| DeepInfra | `deepinfra/fp4` | 0 | **fp4** | — | DISQUALIFIED (fp4) |
| AtlasCloud | `atlas-cloud/fp4` | 0 | **fp4** | — | DISQUALIFIED (fp4) |
| DekaLLM, DigitalOcean, Alibaba, Venice, Morph, Fireworks, DeepSeek | — | — | **unknown** | — | EXCLUDED (fp8 not guaranteed) |

**Note on Parasail (v4-pro).** Its pro endpoint reports OpenRouter status `−2` (deranked / low recent uptime) yet served a conformant fp8 response on retry, so it meets the pass criteria. It is placed **last** in the pro order — used only if Baidu and WandB are both unavailable. Its flash endpoint is status `0`.

**Note on the "INCAPABLE" fp8 providers.** They serve fp8 but return `404 No endpoints found` for a `response_format` request **even with `require_parameters` removed** — OpenRouter itself will not route strict structured output to them for that model. Their endpoints-API `supported_parameters` correctly omits `structured_outputs` (the "optimistic" caveat is about over-claiming, which did not bite here). They are genuinely unusable for these schema-bearing stages.

## Chosen pin

`scripts/run.py` (`DEEPSEEK_V4_*_FP8_ROUTING`), passed to each stage via the new `Agent(provider_routing=...)`:

```python
DEEPSEEK_V4_PRO_FP8_ROUTING = {
    "order": ["baidu/fp8", "wandb/fp8", "parasail/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}
DEEPSEEK_V4_FLASH_FP8_ROUTING = {
    "order": ["baidu/fp8", "wandb/fp8", "streamlake/fp8", "parasail/fp8", "akashml/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}
```

Guarantees:

- **fp8 by construction** — both the `/fp8` endpoint tags in `order` and the `quantizations: ["fp8"]` filter. Neither depends on reading the served quant back.
- **Verified providers only** — `order` lists exactly the empirically verified endpoints, in priority order (Baidu first: the anchor from the eval's ground truth).
- **Fail loud, never fp4/unverified** — `allow_fallbacks: false` means if every listed provider is unavailable the request **errors** (surfaces as a stage error after `agent.py`'s retries) rather than silently dropping to an unknown or fp4 provider. The availability risk of a closed list is the accepted trade-off, mitigated by ≥3 providers per model.
- `require_parameters: true` is still added per-request by `Agent` for schema calls (unchanged); all verified providers honor it.

The request-body construction was also hardened: `src/agent.py` now deep-copies `extra_body_override` and `provider_routing` before the per-request `provider` merge / `require_parameters` injection, closing the `setdefault` aliasing trap documented in `docs/CODE-REVIEW-2026-07-02.md` (Core low findings, `agent.py:362`). Verified by unit test (`tests/test_agent_provider_routing.py`).

## Historical fp4 exposure — **not computable from artifacts**

**The served provider identity is not recorded anywhere in the run artifacts.** `AgentResult.provider` is captured in-memory from `response.provider` (`src/agent.py:744,803`) but is **never persisted**: `Agent` exposes `last_cost_usd` / `last_tokens` but no `last_provider`; `run_stage_log.jsonl` rows carry only `{kind, stage, status, ts, cost_usd, tokens, topic_index, topic_slug}`; and no `provider` key appears in any bus snapshot or Topic Package JSON. Checked across all 37 on-disk run days (`output/2026-*`).

Consequently the actual fp4 hit-rate of past runs **cannot be reconstructed** — we cannot say which provider (or quant) served any historical DeepSeek call. This is stated explicitly rather than estimated. It compounds the original risk: past fp4 exposure was not only silent at run time but is also unauditable after the fact (and `/generation`'s `quantization: null` means it could not have been audited even with the provider known). If retrospective auditing is wanted going forward, persisting `AgentResult.provider` into `run_stage_log.jsonl` would be the minimal change — out of scope for this task.

## Re-verification

Providers and their fp8/structured-output support drift. Before adding or reordering providers, re-run the discovery + forced-single-provider verification (the harness used here lives in the session scratchpad; it is ~15 tiny calls). Do **not** hand-edit the `order` lists toward unverified endpoints — that reintroduces exactly the silent fp4 risk this pin removes.

### 2026-07-14 re-verification — `deepseek-v4-flash`, streamlake dropped

Drift confirmed. On 2026-07-14 `researcher_assemble` (deepseek-v4-flash) hit a non-retryable **HTTP 400** from **StreamLake** — *"Model 'deepseek/deepseek-v4-flash' does not support 'json_schema' response format. Supported formats: json_object"* — after the higher-priority providers were transiently `429`-rate-limited and routing fell to it. StreamLake had **PASSED** on 2026-07-02 (§ deepseek-v4-flash table) but has since dropped strict-`json_schema` support. The 400 dropped `tp-2026-07-14-002` (the stage had no fallback at the time).

Re-ran the forced single-provider strict-schema probe (`{answer:int}`, `require_parameters:true`, retry `429`, re-probe `400/404` without `require_parameters`) across all five flash endpoints:

| Provider | 2026-07-02 | 2026-07-14 |
|---|---|---|
| `baidu/fp8` | VERIFIED | **PASS** |
| `wandb/fp8` | VERIFIED | **PASS** |
| `parasail/fp8` | VERIFIED | **PASS** |
| `akashml/fp8` | VERIFIED | **PASS** |
| `streamlake/fp8` | VERIFIED | **INCAPABLE** — 400 with *and* without `require_parameters` |

`DEEPSEEK_V4_FLASH_FP8_ROUTING.order` is now `["baidu/fp8", "wandb/fp8", "parasail/fp8", "akashml/fp8"]` (4 still-verified endpoints, ≥ the 3-provider bar).

Independently, **all three** deepseek-v4-flash schema-bearing stages — `researcher_assemble` (per-topic), `curator_topic_discovery` (**run-level**; its failure ends the whole day's run), and `resolve_actor_aliases` (per-topic) — were given a one-shot `google/gemini-3-flash-preview` fallback via the generic `FlashStageWithFallback` (`src/flash_stage_fallback.py`), for the residual case where *all* pinned providers are simultaneously rate-limited — a total flash outage, distinct from the schema-incapable-provider bug fixed by the pin edit. Gemini-3-flash-preview is the **pre-migration incumbent** for all three stages (they *were* Gemini-3-Flash until 2026-05-18/19, Wave-1/2 sweeps; deepseek-v4-flash won on cost, not quality), it lives in a different provider ecosystem (Google) so a broad DeepSeek rate-limit event does not take it down with the primary, and it was re-verified 2026-07-14 to honor strict json_schema against **all three** live schemas (`RESEARCHER_ASSEMBLE` / `CURATOR_TOPIC_DISCOVERY` / `RESOLVE_ACTOR_ALIASES`, empty AND populated, via the production checker) — served by Google, no fp8 pin (that pin is DeepSeek-specific). Each fallback runs at its stage's original Gemini operating point; each carries a distinct loud marker (`<stage>_fallback_used`). The `-pro` flash-family pin was untouched (streamlake was already absent from it — it was `INCAPABLE` for `-pro` even on 2026-07-02).
