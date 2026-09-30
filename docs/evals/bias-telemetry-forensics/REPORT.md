# BIAS-TELEMETRY-FORENSICS — A1–A4

Read-only forensics. Produced 2026-09-13. No production file touched for Part A.
Every claim below names the path it came from.

Evidence roots:
- production stage logs: `output/{date}/_state/run-*/run_stage_log.jsonl`
- runner logs: `~/iw-logs/run-{date}.log`
- code: `src/runner/runner.py`, `src/bias_composite.py`, `src/agent.py`, `scripts/run.py`

---

## A1 — `model_used` on BiasLanguageStage

### Correction to the premise
The field is **not** logged as `None`. It is **absent from the row entirely**.
`src/runner/runner.py:597` builds each row as `{stage, kind, status, ts, **extra}`
and `src/runner/state.py:207-213` appends it verbatim — keys that were never set
are never written. A consumer reading `row.get("model_used")` sees `None`, which
is how the observation arose. The distinction matters for the fix: nothing is
writing a null, a writer is missing.

### Root cause — one line
`src/runner/runner.py:96`:

```python
if hasattr(agent, "last_model_used"):
    out["model_used"] = ...
    out["provider_used"] = ...
```

`model_used` / `provider_used` are emitted **only** for agents that expose
`last_model_used`. `BiasComposite` (`src/bias_composite.py:670`) does not define
that attribute — it sets `last_cost_usd`, `last_tokens`, `extra_log_fields`
(`src/bias_composite.py:695-704`) and nothing else. The omission is deliberate
and documented at `src/runner/runner.py:93-95`:

> "The BiasComposite deliberately reports per-sub-agent `extractor_model` /
> `judge_model` via `extra_log_fields` and exposes no `last_model_used`, so it
> is left untouched here."

So the stage was exempted from the generic loud-logging seam
(`7b8cb4d`, 2026-07-05, *feat(observability): loud model_used/provider_used for
all plain LLM stages*) on the reasoning that its per-sub-agent fields are
richer. That reasoning is half right — see "what IS logged" below — but it
leaves the stage the single row in the log whose canonical model field is
missing, so every cross-stage query that keys on `model_used` silently skips it.

### Sub-agent call sites
The sub-agents never reach the runner because they are one level below it.
`BiasLanguageStage` (`src/agent_stages.py:1679-1743`) calls `self.agent.run(...)`
once. That `agent` is a `BiasComposite` (`scripts/run.py:834`), whose `run()`
(`src/bias_composite.py:775-956`) issues **5–6 LLM calls**:
- 3 concurrent `bias_candidate_extractor` passes (`:780-790`), plus an adaptive
  4th on a thin outlier pass (`:802-825`)
- 2 concurrent `bias_judge` votes (`:855-858`), skipped on an empty candidate set

The composite returns a single `AgentResult` with `model=self.model`
(`src/bias_composite.py:954`) — the *static* label
`"bias-composite(deepseek-v4-flash x3 -> z-ai/glm-5.3 x2)"`, built from the
configured ids at construction (`:687`), never from what served. The runner does
not read `AgentResult.model`; it reads attributes off the agent object.

### What IS logged (and is genuinely good)
`extra_log_fields` (`src/bias_composite.py:889-918`) is merged verbatim by
`src/runner/runner.py:128-131`. A real row (09-12 t0) carries:
`extractor_model`, `extractor_model_served`, `extractor_provider`,
`extractor_fallback_used`, `extractor_fallback_passes`, `judge_model`,
`judge_model_served` (a list, one per vote), `judge1_provider`,
`judge2_provider`, `bias_judge_fallback_used`, `bias_judge_fallback_votes`.

The composite even solves the hard part correctly: because the passes run
concurrently against one wrapper instance, the wrapper's own
`last_fallback_used` is last-writer-wins and cannot answer "did any pass fall
back?" — so `_channel_report` (`:751-770`) and `_judge_fallback_votes`
(`:736-749`) derive it per result instead.

**The gap is therefore narrow and specific**: the canonical, cross-stage
`model_used` / `provider_used` keys, and a `{agent}_fallback_used` key under
each sub-agent's own name.

### Since when — never
Sweep of every `run_stage_log.jsonl` on disk, 2026-05-27 → 2026-09-13
(110 run-days, 330 `BiasLanguageStage` rows): **`model_used` present in 0 rows.**
This predates the composite: it is also absent on the pre-split single-agent
days (2026-05-27 → 2026-07-04, split landed `f1bbaa8` 2026-07-04), because the
generic seam itself only landed 2026-07-05 (`7b8cb4d`) — by which time the stage
had already been carved out of it. The field has **never** been populated for
this stage.

---

## A2 — the 2026-09-12 `fallback_used=True`

**Row**: `output/2026-09-12/_state/run-2026-09-12-4e9b3a29/run_stage_log.jsonl`,
`BiasLanguageStage` topic_index 1.

```
bias_judge_fallback_used : true
bias_judge_fallback_votes: [1, 2]        <- BOTH votes
judge_model              : z-ai/glm-5.3  (requested)
judge_model_served       : ["anthropic/claude-opus-4.6", "anthropic/claude-opus-4.6"]
judge1_provider          : "Claude Platform on AWS"
cost_usd                 : 0.18864
```

**Sub-agent**: `bias_judge` — *not* the extractor. The extractor passes for that
topic succeeded on channel C (`extractor_fallback_used: false`).

**What failed**: `~/iw-logs/run-2026-09-12.log:480` and `:484`, both at 07:02:07:

> `bias_judge FALLBACK: primary z-ai/glm-5.3 (channel openrouter) failed — final
> output not schema-valid (truncation or malformed). Making exactly one fallback
> attempt on anthropic/claude-opus-4.6 (channel openrouter).`

Both concurrent votes failed local schema validation on the same input. Two
lines earlier (`:478`, `:482`) the primary also reports
`provider did not report cost for model z-ai/glm-5.3; cost_usd=0.0` — the failed
primary attempts are billed by Z.AI but booked at zero here (a second, smaller
unmeasured-cost class; see A3 note).

**What served instead**: `anthropic/claude-opus-4.6` via *Claude Platform on
AWS*, both votes schema-valid (`:487-490`).

**Cost**: `$0.093070` + `$0.095570` = **`$0.188640`**, which reconciles to the
penny with the row's `cost_usd: 0.18864`. Against the same day's other two bias
rows (`$0.04646`, `$0.057565`) the fallback cost this topic **~3.6×** the normal
bias-stage price. The judge legs are the entire measured cost of the row: the
three extractor passes were booked at $0.00 (A3).

This one is working as designed — loud in the log, loud in the row. It is the
one sub-agent fallback the current telemetry does surface.

---

## A3 — the alias-roll tripwire

### The warning and its trigger
`src/agent.py` computes channel-C cost from `DEEPSEEK_DIRECT_PRICES`
(`src/agent.py:126-136`, keys `deepseek-v4-flash` and `deepseek-v4-pro`, dated
`api-docs.deepseek.com @ 2026-08-23`). `deepseek_direct_cost_usd`
(`:147-168`) returns `None` for an unknown key, and the caller emits:

> `deepseek_direct served model 'deepseek-flash' is absent from the price table
> ... If the vendor rolled its alias, this is the tripwire`

### Since when — first fired 2026-09-10 06:15:09
`grep -c "absent from the price table" ~/iw-logs/run-*.log`:

| day | tripwire lines | channel-C flash completions | served id |
|---|---|---|---|
| 2026-09-09 and earlier | 0 | 29 | `deepseek-v4-flash` |
| 2026-09-10 | 26 | 26 | `deepseek-flash` |
| 2026-09-11 | 29 | 29 | `deepseek-flash` |
| 2026-09-12 | 31 | 31 | `deepseek-flash` |
| 2026-09-13 | 30 | 30 | `deepseek-flash` |

The roll landed between the 09-09 and 09-10 production runs. Every channel-C
flash call since has been unpriced — the counts are identical because the
tripwire fires on **every** such call. First line:
`~/iw-logs/run-2026-09-10.log:193`.

### Ledger understatement — 116 calls, ~$1.70 (ESTIMATE)
116 production calls across 4 runs, 4 035 237 tokens, all booked `cost_usd=0.0`.

Estimation basis: the per-agent **effective $/M-token measured on 2026-09-09**,
the last priced day — same six agents, same channel, same operating points,
same input shapes — applied to each agent's unmeasured token count. This folds
in that day's real input/output and cache-hit mix, which a rate card cannot: the
logs record only a *total* token count per call, and solving for the split from
09-09 is underdetermined (it yields a negative output count for
`curator_topic_discovery` under both price windows, i.e. cache hits dominate).
**All figures below are estimates, not measurements.**

| agent | calls | tokens | est. $ | share |
|---|--:|--:|--:|--:|
| `hydration_aggregator_phase1` | 44 | 1 465 636 | 0.8033 | 47.4% |
| `researcher_assemble` | 12 | 1 314 395 | 0.4265 | 25.2% |
| `bias_candidate_extractor` | 33 | 496 359 | 0.2807 | 16.6% |
| `resolve_actor_aliases` | 12 | 320 738 | 0.1035 | 6.1% |
| `curator_topic_discovery` | 4 | 399 323 | 0.0623 | 3.7% |
| `consolidator` | 11 | 38 786 | 0.0187 | 1.1% |
| **total** | **116** | **4 035 237** | **1.6950** | |

Per day: 09-10 $0.4227 · 09-11 $0.3909 · 09-12 $0.4581 · 09-13 $0.4232.
**≈ $0.42 per production run understated, ≈ $1.70 to date.** Against a real
hydrated run of ~$3.58 that is on the order of 12% of run cost booked as free.

Rate-card cross-checks on the same 4 035 237 tokens, bracketed
[all-prompt … all-completion] because the split is not observable:

| basis | bracket |
|---|---|
| OpenRouter `deepseek/deepseek-v4-flash` ($0.04928 / $0.09856 per M, read 2026-09-13) | $0.20 … $0.40 |
| vendor v4.1-flash offpeak ($0.15 / $0.60 per M) | $0.61 … $2.42 |
| old table `deepseek-v4-flash` offpeak ($0.22 / $0.66 per M) | $0.89 … $2.66 |

The brief's requested OpenRouter-v4-flash basis is the **lowest** of these by a
wide margin — those are third-party host prices, not what api.deepseek.com
bills. The $1.70 figure sits inside the two vendor brackets and is the one I'd
carry forward.

*Secondary unmeasured class, out of the brief's scope but same shape*:
`provider did not report cost for model z-ai/glm-5.3` also books $0.00 — seen on
the two failed judge primaries of 09-12 (A2). Not quantified here.

### What api.deepseek.com serves on `deepseek-flash` — probably v4.1-flash, not proven
`GET https://api.deepseek.com/models` returns exactly two ids: `deepseek-flash`
and `deepseek-v4-pro`. The old `deepseek-v4-flash` id is still accepted but the
server echoes `deepseek-flash`; `deepseek-v4-flash-0731` is rejected by name.

The planner eval already worked this problem and came up empty on three
discriminators (`scratch/eval/dsv41-flash-planner/reports/METHOD.md:26-57`):
server echo carries no version; the `max_tokens` ceiling does **not** separate
the builds (393216 / 384001 / 384000 all accepted); price is not observable
per call because the vendor returns no `usage.cost`.

**New evidence found here, from the OpenRouter catalogue** (a listing read, no
inference from probes):

- `deepseek/deepseek-v4.1-flash` — 13 endpoints, **one tagged `deepseek`** (the
  vendor's own first-party endpoint).
- `deepseek/deepseek-v4-flash-0731` — 28 endpoints, **none tagged `deepseek`**.
- `deepseek/deepseek-v4-flash` (undated) — 16 endpoints, **none tagged
  `deepseek`**.

OpenRouter's `deepseek`-tagged endpoint *is* api.deepseek.com. The vendor
exposes exactly one flash id there (`deepseek-flash`). The only flash model for
which OpenRouter still lists a first-party DeepSeek endpoint is v4.1-flash.
Those two facts only reconcile if **`deepseek-flash` == v4.1-flash**.

That is strong circumstantial evidence, not proof: it is an inference from one
vendor's routing catalogue about another vendor's alias, and I found no vendor
changelog or dated doc stating the rename. Marking it **PROBABLE, NOT
ESTABLISHED** — the same standard the planner eval applied. Per B2 this is not
sufficient to write a price into the table.

**Operational consequence either way**: production has been running six stages
on an undated alias whose build changed under it on 2026-09-10, with no eval
behind the new build. Reporting only, per B3.

---

## A4 — the alias roll is not bias-only, and the fallback rung is broken

### Inventory — every stage on deepseek flash

Six stages use the `_flash_0731_primary` / `_flash_0731_fallback` pair
(`scripts/run.py:227-319`), all wrapped in `FlashStageWithFallback`:

| stage | primary (rung 1) | fallback (rung 2) | exposure |
|---|---|---|---|
| `curator_topic_discovery` | `scripts/run.py:381` | `:389` | 1 call/run — **kills the run** |
| `researcher_assemble` | `:509` | `:517` | 3 calls/run, per topic |
| `resolve_actor_aliases` | `:549` | `:557` | 3 calls/run, per topic |
| `bias_candidate_extractor` | `:836` | `:847` | 3–4 calls/topic (inside `BiasComposite`) |
| `consolidator` | `:980` | `:989` | 3 calls/run, per topic |
| `hydration_aggregator_phase1` | `:1132` | `:1141` | 10–12 calls/run, chunked |

Rung 1 for all six: `model="deepseek-v4-flash"`, `provider="deepseek_direct"` —
the rolled alias. Rung 2 for all six: `model="deepseek/deepseek-v4-flash-0731"`,
`provider="openrouter"`, `provider_routing=DEEPSEEK_NATIVE_ROUTING`
(`scripts/run.py:90-93` = `{"order": ["deepseek"], "allow_fallbacks": false}`).

**Both rungs are compromised, in different ways.** Rung 1 serves an unevaluated
build; rung 2 is described below. There is no third rung on any of the six —
a rung-2 failure fails the stage.

For contrast, `researcher_hydrated_plan` (`scripts/run.py:1042-1100`) runs a
three-rung ladder on the **pro** line: `deepseek-v4-pro` (channel C) →
`deepseek/deepseek-v4-pro-0813` (same pin) → `anthropic/claude-opus-4.6`. The
pro alias did **not** roll (still priced, `cost_usd` reported every day), and
`deepseek/deepseek-v4-pro-0813` still carries a `deepseek`-tagged endpoint
(21 endpoints, DeepSeek present). That ladder is healthy.

### Reconciling "28 endpoints" with the 404 — they are both true
The planner eval's claim (`scratch/eval/dsv41-flash-planner/reports/METHOD.md:19`)
was *"28 endpoints and **no `deepseek` tag among them**"*, and it used that
asymmetry as evidence. Re-verified 2026-09-13: still 28 endpoints, still zero
`deepseek` tag (provider names: Alibaba, AtlasCloud, Baidu, BaseTen, Cloudflare,
CoreWeave, DeepInfra, DigitalOcean, Fireworks, GMICloud, Inceptron, Makora,
Mancer 2, Morph, NextBit, Novita, OpenInference, Parasail, Phala, Reka, Relace,
Sail Research, SiliconFlow, StreamLake, Together, Venice, Wafer).

So: the **model** is alive and has 28 healthy endpoints. The **route production
asks for** — `order: ["deepseek"]`, `allow_fallbacks: false` — resolves to the
empty set, and that is the 404. No contradiction. The pin is doing exactly what
`scripts/run.py:88-89` says it should ("this is the vendor's own endpoint or
nothing"); what changed is that the vendor retired its own 0731 endpoint.

Dating the retirement from the logs — rung 2 was **alive on 2026-09-06**:
`~/iw-logs/run-2026-09-06.log`, two `*_fallback` calls completed with
`channel=DeepSeek served_model=deepseek/deepseek-v4-flash-0731` (and one more on
09-01). By 2026-09-10 06:25:08 the same request 404s. The window is 09-06 → 09-10,
i.e. the endpoint went away at roughly the same time as the alias roll.

### The rung is now WORSE than 404 — it silently substitutes a different model
Live probes, 2026-09-13 (three calls, ≤5 max_tokens, ~$0 total):

| request | served `model` | `provider` |
|---|---|---|
| `deepseek-v4-flash-0731`, **no pin** | `deepseek/deepseek-v4-flash-0731` | OpenInference |
| `deepseek-v4-flash-0731`, **production pin** | **`deepseek/deepseek-v4.1-flash`** | **DeepSeek** |
| `deepseek-v9-flash-0101` (control), production pin | — | 400 *not a valid model ID* |

**With the production pin, OpenRouter now serves `deepseek-v4.1-flash` for a
`deepseek-v4-flash-0731` request.** The control call confirms OpenRouter does
reject genuinely unknown ids, so this is a deliberate redirect of a retired id
onto the vendor's current endpoint, not a lookup accident.

This is a three-state degradation of rung 2:
`09-06 genuine 0731` → `09-10 404 (loud, fails)` → `09-13 v4.1-flash (silent
substitution)`. The current state is the dangerous one: it violates
*"keine stillen Fallbacks"* at the vendor's routing layer, below anything the
repo controls. The repo's one defence holds — `src/agent.py:954` logs the
server-echoed id, and `FlashStageWithFallback` sets `last_model_used` from it,
so `model_used` in the row **would** name `deepseek-v4.1-flash` if this fires.
That defence does **not** exist on `bias_candidate_extractor`, because its
wrapper sits inside `BiasComposite` — the A1 gap and the A4 risk are the same
hole. (`extractor_model_served` would still catch it; the canonical key would not.)

Not yet observed in production: no rung-2 call has fired since 09-10.

### Is 09-10 an outlier or a rate? — a rate, and an unchanged one
Schema-invalid **primary** completions from channel-C flash
(`grep "FALLBACK: primary .* channel deepseek_direct" ~/iw-logs/run-*.log`) —
four ever, all since the 08-24 swap:

| date | agent | rung-2 outcome |
|---|---|---|
| 2026-09-01 | `hydration_aggregator_phase1` | recovered — served genuine 0731 |
| 2026-09-06 | `hydration_aggregator_phase1` | recovered — served genuine 0731 |
| 2026-09-06 | `bias_candidate_extractor` | recovered — served genuine 0731 |
| 2026-09-10 | `resolve_actor_aliases` | **404 — topic 0 lost** |

| window | channel-C flash calls | primary schema-invalid | rate |
|---|--:|--:|--:|
| pre-roll 09-01…09-09 | 263 | 3 | 1.14% |
| post-roll 09-10…09-13 | 116 | 1 | **0.86%** |

**09-10 is not an outlier and the roll did not make the model worse** — the
failure rate is flat (if anything slightly lower, n far too small to call a
difference). What changed is the consequence: the same ~1% failure used to be
absorbed by rung 2 three times in ten days, and on 09-10 it cost a published
Topic Package instead.

Full chain, `~/iw-logs/run-2026-09-10.log:296-301`:
```
06:25:08 resolve_actor_aliases completed ... served_model=deepseek-flash cost_usd=unreported
06:25:08 resolve_actor_aliases FALLBACK: primary ... not schema-valid ...
06:25:08 POST https://openrouter.ai/api/v1/chat/completions "HTTP/1.1 404 Not Found"
06:25:08 Runner: topic 0 failed at stage; continuing with next topic
```
Independently corroborated by the FM-CONFIRM eval, which lost the same instance
(`scratch/eval/glm53-prose/confirm/reports/REPORT.md`, qa n=8 not 9).

**Expected loss at the current rate**: ~1% of ~29 channel-C flash calls per run
≈ 0.3 unprotected failures per run. Whether that lands on a per-topic stage
(loses one Topic Package) or on `curator_topic_discovery` (one call, no rung 2,
loses the whole run) is luck.

---

## Summary for the owner

1. `model_used`/`provider_used` have **never** been logged for `BiasLanguageStage`
   — one `hasattr` guard, deliberate, documented, and now wrong. **Fixed in Part B.**
2. The 09-12 fallback was `bias_judge`: both glm-5.3 votes schema-invalid →
   both served by Opus-4.6, $0.18864, ~3.6× a normal bias row. Telemetry handled
   this one correctly.
3. Six stages have run on a silently rolled vendor alias since 2026-09-10;
   116 calls, ~**$1.70** (estimate) booked as free, ~$0.42/run.
4. The alias is **probably** v4.1-flash — strong catalogue evidence, no vendor
   doc. Not established, so **no price written** (B2 deferred).
5. **The most serious finding is not the ledger.** The shared rung-2 fallback for
   all six flash stages died between 09-06 and 09-10, and as of 09-13 it no
   longer 404s — it silently serves a different model. Six stages currently run
   an unevaluated build with a broken net behind it. Rung repair and any
   pin/swap are owner decisions; this task changes telemetry only.
