# GLM-5.2 provider verification — fp8 + strict structured outputs + xhigh headroom (2026-07)

Empirical verification of fallback providers for a potential `qa_analyze` swap
to **GLM-5.2 @ effort xhigh** (see `docs/QA-STAGE-MODEL-EVAL-SHADOW-BACKFILL.md`).
Only **Baidu** was previously verified. This task probes the additional fp8
providers OpenRouter lists for `z-ai/glm-5.2` and records which actually deliver
fp8 + strict structured outputs + enough completion headroom for xhigh.

**No production code was changed.** `scripts/run.py` and `src/` are untouched;
the verified routing constant below is for a later swap task to wire in. Probe
harness + raw artifacts are untracked under
`scratch/qa-shadow/provider-verify/`.

## Outcome — PASS (≥3 verified)

Three providers deliver fp8 + strict structured outputs + xhigh headroom and are
operationally sound: **Baidu, Ambient, Venice**. A fourth, **StreamLake**, is
*capability*-verified but **operationally disqualified** (its xhigh reasoning is
pathologically verbose — it would truncate real QA inputs). Two named candidates
failed outright.

| provider | tag | quant | strict schema (empirical) | max-token cap | xhigh reasoning tokens¹ | latency¹ | cost¹ | verdict |
|---|---|---|---|--:|--:|--:|--:|---|
| **Baidu** | `baidu/fp8` | fp8 | ✅ clean JSON | 131072 | 19,244 | 259 s | $0.081 | **VERIFIED** (primary) |
| **Ambient** | `ambient/fp8` | fp8 | ✅ clean JSON | 202752 | 6,762 | 168 s | $0.025 | **VERIFIED** |
| **Venice** | `venice/fp8` | fp8 | ✅ clean JSON | 131072 | 5,252 | 59 s | $0.024 | **VERIFIED** (transient 429s²) |
| StreamLake | `streamlake/fp8` | fp8 | ✅ clean JSON | 128000 | **88,834** | **1,253 s** | $0.308 | capability-verified, **operationally disqualified**³ |
| GMICloud | `gmicloud/fp8` | fp8 | ❌ **markdown-fenced** | (null / unstated) | 9,476 | 261 s | $0.032 | **FAILED**⁴ |
| Novita | `novita/fp8` | fp8 | ❌ **not supported** | 131072 | — | 0.2 s | $0 | **FAILED**⁵ |

¹ Measured on one small-but-realistic `qa_analyze` input (2 sources, 3-sentence
article) — identical across providers, so the reasoning-token column is a direct
per-provider comparison of xhigh verbosity.
² Venice returned transient upstream `429` (rate-limited without BYOK) on the
first two attempts; cleared on the third. The production `Agent`'s built-in 429
retry (`MAX_RETRIES=3`) absorbs this, but it is an availability wrinkle → ordered
last.
³ StreamLake honored strict schema and accepts 128000 (≥ the 120000 floor), but
spent **88,834 reasoning tokens on a trivial input** — ~4.6× Baidu and ~13× the
lean providers. On a real ~80 KB QA topic its reasoning alone would blow past
128000 and truncate; 21-minute latency and 4× cost compound this. Excluded from
the recommended pin. This is the same truncation failure mode that forced the
64000→131072 raise, but structural to the provider.
⁴ GMICloud returned the answer wrapped in a ```json markdown fence — it does
**not** enforce strict `json_schema` despite the endpoints API advertising
`structured_outputs: true`. The production decode path (`response_format` strict)
would fail to parse it. Headroom (131072) and fp8 were fine; strict schema is
not.
⁵ Novita's endpoint does not list `structured_outputs`. With
`require_parameters: true` (how the production `Agent` issues a schema call) the
router returns `404 No endpoints found` — i.e. it is filtered out for strict-
schema traffic. `response_format` is listed but structured/strict is not
honored.

## Method

Mirrors `TASK-DEEPSEEK-FP8-PIN` (`docs/DEEPSEEK-FP8-PIN-2026-07.md`). Per
candidate, a single forced-provider probe:

- **Forced single-provider routing** — `provider = {order: [tag],
  allow_fallbacks: false, quantizations: ["fp8"], require_parameters: true}`.
  `require_parameters: true` is what the production `Agent` sets for a schema
  call, so a provider that cannot satisfy strict structured output is filtered
  out (surfacing as `404 No endpoints found`) rather than silently downgraded.
- **Real schema, real prompts** — the production `qa_analyze` SYSTEM + INSTRUCTIONS
  prompts and the strict `QA_ANALYZE_SCHEMA` (`response_format: json_schema,
  strict: true`), assembled by the shadow `Agent`'s own prompt path.
- **effort `xhigh`**, `max_tokens = 131072`. A provider whose cap is below the
  request is rejected by the router (StreamLake at 131072 → `404`); it was then
  re-probed at its stated cap (128000).
- **Headroom floor = 120000** (operator decision, 2026-07-03): a provider need
  not reach the full 131072, but must clear 120000 — a 64k-capped endpoint is
  unusable for xhigh by construction (reasoning trace alone exceeds it).
- **Served provider, HTTP status, `finish_reason`, schema validity, latency, and
  cost** recorded per probe. A **cumulative $2 budget ledger**
  (`_ledger.json`) refuses any probe once spend reaches $1.80.

A **Baidu control** (already production-verified on the 21-topic shadow) ran
first and returned clean strict JSON — validating the harness and giving the
baseline row.

**Total probe spend: $0.47** of the $2 cap (11 calls; the four Venice/StreamLake
`404`/`429` attempts were free).

## Verified routing constant (for a later swap task)

Recommended pin — the three operationally-sound providers, Baidu primary
(most evidence: all 21 shadow topics served by Baidu, schema-valid), then the two
lean providers as fail-loud fallbacks:

```python
# All three accept ≥120000 completion tokens; set the qa_analyze max_tokens in
# [120000, 131072]. StreamLake is deliberately excluded (would truncate real
# xhigh inputs at its 128000 cap — see note ³).
GLM_QA_PROVIDER_ROUTING = {
    "order": ["baidu/fp8", "ambient/fp8", "venice/fp8"],
    "allow_fallbacks": False,   # never fp4 / unverified — fail loud
    "quantizations": ["fp8"],
}
```

`allow_fallbacks: False` with a multi-provider `order` tries the listed fp8
providers in sequence and fails loud if all three are unavailable — it never
routes to an fp4 or unverified endpoint. Ambient's economics (leanest reasoning,
$0.025, 168 s, cap 202752) make it a candidate to promote ahead of Baidu pending
its own multi-topic shadow; that is out of scope here.

## Caveats / no silent loosening

- Each provider was probed **once** on a small input (budget discipline). The
  reasoning-token counts are a strong signal but a single sample; a fuller shadow
  (as was run for Baidu) is warranted before promoting Ambient/Venice to primary.
- `strict schema` here means: HTTP 200 from the pinned provider **and** raw
  parseable JSON matching `QA_ANALYZE_SCHEMA` top keys with `finish_reason:
  stop` (not `length`). GMICloud's fenced output is the reason this is checked
  empirically rather than trusting `supported_parameters`.
- StreamLake is recorded as capability-verified but **must not** be pinned for
  xhigh — its verbosity is the disqualifier, and silently including it (as the
  raw `report.py` capability list does) would reintroduce the truncation failure.
- Venice's non-BYOK endpoint is intermittently rate-limited upstream; it is
  ordered last and relies on the Agent's 429 retry.

## Reproduction

All under `scratch/qa-shadow/provider-verify/` (untracked):

```bash
# endpoint scan (API-claimed capabilities)
.venv/bin/python - <<'PY'  # writes endpoints_raw.json  (see harness)
PY
# one probe per provider (forced single-provider, strict schema, xhigh)
.venv/bin/python scratch/qa-shadow/provider-verify/provider_probe.py baidu/fp8 131072
.venv/bin/python scratch/qa-shadow/provider-verify/provider_probe.py ambient/fp8 131072
.venv/bin/python scratch/qa-shadow/provider-verify/provider_probe.py venice/fp8 131072
.venv/bin/python scratch/qa-shadow/provider-verify/provider_probe.py streamlake/fp8 128000
.venv/bin/python scratch/qa-shadow/provider-verify/provider_probe.py gmicloud/fp8 131072
.venv/bin/python scratch/qa-shadow/provider-verify/provider_probe.py novita/fp8 131072
# assemble the matrix + verdicts
.venv/bin/python scratch/qa-shadow/provider-verify/report.py
```

Raw artifacts: `endpoints_raw.json`, `probe_<provider>_<maxtok>.json`,
`_ledger.json`.
