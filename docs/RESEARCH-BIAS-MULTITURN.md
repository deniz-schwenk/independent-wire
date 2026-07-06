# Research: Bias multiturn spike (transport + plumbing + latency)

**Date:** 2026-06-22 · **Task:** `TASK-BIAS-MULTITURN-SPIKE.md` (research only)
**Scope:** establish the technical facts to design a candidate-side
find → audit → note multiturn for the `bias_language` stage (agent dir
`bias_detector`) plus a deterministic `<3 findings → Opus 4.6` fallback guard.
**Out of scope (untouched):** the loop itself, judge subagents, prompt tuning,
the guard implementation, any master-prompt / production change. No tracked
files edited beyond this doc; throwaway measurement code lives under
`~/iw-stage-bench/shadow/`.

---

## TL;DR

| Q | Answer | Primary evidence |
|---|---|---|
| Q1 | **json_object + deterministic Python guard** for the candidate turns. Strict `json_schema` decoding is **proven to choke on verbatim spans** (the bias `excerpt`). The one exception that works is DeepSeek **direct API strict *tools*** (already the proven bias transport). | `HANDOFF-2026-06-22.md:62-67`; `src/translate/transport.py`; `driver_v3.py:13-18` |
| Q2 | **No bus or schema change.** The stage makes exactly one `agent.run()` call and writes exactly two slots from the final parsed output. N internal turns are invisible to the bus. | `src/agent_stages.py:1666-1690`; `src/bus.py:777-778`; `ARCH-V2-BUS-SCHEMA.md:305-306` |
| Q3 | **single-turn 15.5–18.7 s; 3-turn 43.6–65.1 s; delta +28–46 s (2.8–3.5×).** | measured `shadow/latency-2026-06-21-t{0,1}.json` |
| Q4 | Guard plugs in at the stage-finalization `model_copy` (`src/agent_stages.py:1685-1690`). **Cost per fire ≈ $0.046** (one Opus 4.6 bias call). | `src/agent_stages.py:1685-1690`; prod `run_stage_log.jsonl` (15 runs) |

**One-line recommendation:** use **`json_object` + the existing deterministic
excerpt/schema guard** for the candidate turns on every transport, except the
DeepSeek-direct primary which uses **strict tools** (GA, already proven for the
bias stage) — do **not** use `response_format: json_schema` strict decoding for
deepseek, because the verbatim `excerpt` field triggers the same constrained-
decoding failure that retired strict mode in translation.

---

## Q1 — Structured output per transport

**Question.** For `deepseek-v4-pro` across Ollama-Cloud, DeepSeek direct API, and
OpenRouter, does strict `json_schema` decoding work, or must we use `json_object`
+ deterministic Python guard? The bias schema carries a verbatim `excerpt` (exact
article substring, `src/schemas.py:395` — `"excerpt": {"type": "string"}`) — does
strict decoding choke on it the way Policy-A quotes did in translation?

**Answer: it chokes — and the translation feature already paid for this lesson
and abandoned strict json_schema for exactly this reason.**

### The proven precedent (verbatim-quote ≈ verbatim-excerpt)

The German translation feature has the identical problem (a translated block must
reproduce verbatim source quotes — "Policy-A") and solved it across the same three
transports. Its transport chain is the authority here:

> **Transport + fallback chain (per-TP):** Ollama-Cloud `deepseek-v4-pro:cloud`
> (flat-rate, primary) → DeepSeek direct API (strict tools) → OpenRouter(deepseek)
> → OpenRouter(atlas-cloud). json_object + deterministic Python guard (schema,
> every `[src-NNN]` preserved, no degenerate final) — **NOT strict json_schema
> (strict decoding chokes on Policy-A verbatim quotes; proven).**
> — `docs/handoffs/HANDOFF-2026-06-22.md:62-67`

The mechanism, from the driver that made the switch:

> The strict-json_schema OpenRouter transport is abandoned — it sends the model
> into a loop when a Policy-A verbatim quote must be reproduced inside constrained
> decoding (v2 finding; a subagent translated the same paragraphs cleanly without
> the constraint).
> — `~/iw-stage-bench/translation/driver_v3.py:13-18`

The bias `excerpt` (an exact article substring the model must reproduce inside the
constrained grammar) is the precise structural analog of a Policy-A verbatim
quote. Same failure surface.

### Per-transport verdict (from `src/translate/transport.py:273-288`, `build_chain`)

| transport | model id | mode used in production | strict json_schema? |
|---|---|---|---|
| **Ollama-Cloud** | `deepseek-v4-pro:cloud` | `json_object` (`format:"json"`, `think:false`) + Python guard — `transport.py:80-99` | not used (Ollama path here offers only `format:"json"`) |
| **DeepSeek direct API** | `deepseek-v4-pro` | **strict TOOLS** (`tool_mode=True, strict=True, disable_thinking=True`, main base URL) + Python guard — `transport.py:138-144, 278-280` | **strict *tools* works** (GA on the main URL; the `/beta` path does not enforce). This is "the transport proven for the bias stage" (`transport.py:9`). |
| **OpenRouter** (provider `deepseek` or `atlas-cloud`) | `deepseek/deepseek-v4-pro` | `json_object` + Python guard — `transport.py:149-150, 281-286` | **not used — proven to choke** on verbatim spans (above). DeepSeek's own OpenRouter endpoint additionally *failed* the json_schema const probe (`~/iw-stage-bench/results/FALLBACK-PROVIDER-REPORT.md:30`); AtlasCloud probes as json_schema-capable but is not trusted with the verbatim field. |

### Why strict *tools* (direct API) is the exception that works

Both `response_format: json_schema` and strict tools constrain decoding to the
schema, but for a `{"type":"string"}` field the schema only requires *a valid JSON
string* — the content is free. The empirical failure is in specific providers'
`response_format` implementations for deepseek (loop/degrade on long verbatim
reproduction), **not** in the strict-tools path on `api.deepseek.com`, which is GA
and already carried the bias shadow at 15/15 step1-clean excerpt integrity (shadow
ran deepseek-direct strict-tools primary, 0 fallbacks; `SHADOW-REPORT.md`).
Excerpt correctness there is enforced by a *deterministic* string-match guard +
one repair turn, not by constrained decoding of the excerpt content
(`~/iw-stage-bench/candidate/code/runner.py::heal_excerpts / failed_excerpts`).

### Anthropic-side note

`docs/RESEARCH-OPENROUTER-STRUCTURED-OUTPUTS.md` establishes that strict
`json_schema` *does* work for Anthropic models (Opus 4.6 — the master reference
and the fallback-guard model). That doc is about Anthropic models; it does not
cover deepseek, and the verbatim-quote failure mode is provider-specific to the
deepseek `response_format` path. So: strict json_schema for the **Opus guard**
call is fine; `json_object` + guard for the **deepseek candidate** turns.

**Q1 recommendation (one line):** **json_object + deterministic guard** for every
candidate (deepseek) turn, with the DeepSeek-direct primary using **strict
tools**; never `response_format: json_schema` strict on deepseek for a turn that
must emit the verbatim `excerpt`.

---

## Q2 — Bus impact of a multiturn candidate

**Question.** If the candidate runs as N internal turns, does only the FINAL stage
output reach the bus, with intermediates discarded and no schema/slot change?

**Answer: yes — confirmed; zero bus or schema change required.**

The entire stage I/O is this single method:

```python
# src/agent_stages.py:1658-1690  (BiasLanguageStage.__call__)
result = await self.agent.run(                      # :1666 — ONE call boundary
    message,
    context={"article_body": ..., "bias_card": ...},
)
parsed = _parse_agent_output(result) or {}          # :1673 — reads result.structured
...
return topic_bus.model_copy(                          # :1685 — the ONLY write
    update={
        "bias_language_findings": findings,           # :1687  (parsed.language_bias.findings)
        "bias_reader_note": parsed.get("reader_note", "") or "",  # :1688
    }
)
```

Load-bearing facts:

1. **The stage consumes a single `AgentResult`.** `agent.run()` returns one
   `AgentResult` whose `structured: dict | None` is the schema-validated final
   parse (`src/agent.py:26-30`, `:795-797`). `_parse_agent_output` reads
   `result.structured` (`src/agent_stages.py:208-210`). The stage is
   **agent-implementation-agnostic**: whether the agent made 1 call or N internal
   turns is entirely opaque to it. A multiturn candidate is built by giving
   `BiasLanguageStage` an `agent` object whose `.run()` internally does
   find→audit→note and returns one `AgentResult` with the final
   `{language_bias:{findings}, reader_note}` in `.structured`.

2. **Exactly two bus slots are written, both single-writer.**
   `bias_language_findings` and `bias_reader_note` are the only slots in the
   `model_copy` update (`:1687-1688`). Bus schema confirms each has **one writer
   = `bias_language`** and no mirror pattern
   (`docs/ARCH-V2-BUS-SCHEMA.md:305-306`; `src/bus.py:777-778`). Intermediate
   turn payloads (a FIND draft, an AUDIT `analysis`/`self_validation`/`passed`,
   etc.) are never assigned to any slot — they have nowhere to go.

3. **The output contract is unchanged.** `BIAS_DETECTOR_SCHEMA`
   (`src/schemas.py:384-422`) stays exactly as is; the candidate's *final* turn
   must match it (`{language_bias:{findings:[{excerpt,issue,explanation,
   finding_valid}]}, reader_note}`). Render is pure selection over those two slots
   (`src/render.py:325,347`), so nothing downstream sees the turns either.

**Conclusion:** a multiturn candidate is a drop-in at the `agent` boundary. No bus
slot, schema, mirror, or render change. (Throwaway turn-prompts are free; only the
final turn's output is contract-bound — consistent with the task's framing.)

---

## Q3 — Real latency delta (single-turn vs 3-turn)

**Method.** One real reuse-date topic, same input, same transport
(`deepseek-direct` strict tools, thinking disabled — `config.json` candidate
block), back-to-back, on the production Mac Mini. Throwaway driver
`~/iw-stage-bench/shadow/measure_latency.py` builds the stage input from the
persisted `topic_buses.BiasLanguageStage.{N}.json` snapshot (read-only) exactly as
production builds it, then runs the bench `single_call` and `find_audit_note`
architectures. Two topics measured (2-sample, to guard against provider weather).

| reuse topic | body len | single-turn | 3-turn (find→audit→note) | delta | ratio |
|---|---|---|---|---|---|
| 2026-06-21 t0 (Ukraine/Russia oil) | 6 991 | **15.51 s** (1 call) | **43.60 s** (3 calls) | +28.09 s | 2.81× |
| 2026-06-21 t1 (Europe heatwave) | 5 916 | **18.72 s** (1 call) | **65.11 s** (3 calls) | +46.39 s | 3.48× |
| **range** | — | **15.5–18.7 s** | **43.6–65.1 s** | **+28–46 s** | **2.8–3.5×** |

Artifacts: `~/iw-stage-bench/shadow/latency-2026-06-21-t0.json`, `…-t1.json`.

**Corroboration (independent prior measurements, same transport):**
- 3-turn `find_audit_note` over 15 real shadow topics (2026-06-11→15): mean
  **57.9 s/topic** — `~/iw-stage-bench/shadow/SHADOW-REPORT.md`. The fresh 43.6 /
  65.1 s bracket that mean.
- single-call deepseek configs ran **~17–19 s mean** at the bench —
  `~/iw-stage-bench/results/FINAL-REPORT.md`. Matches the fresh 15.5 / 18.7 s.

**Takeaway for the loop design.** The 3-turn split costs **~+30–45 s/topic**
(≈3×). At 3 topics/day that is ~+1.5–2.5 min/day of wall-clock — the same
operational delta the shadow already accepted (its 57.9 s mean cleared the
55–80 s band). Latency is not a blocker for a 3-turn candidate; it is a known,
in-band cost. Spike spend: **$0.023** (well under the EUR 0.50 cap).

---

## Q4 — Fallback guard hook (location + per-fire cost)

**Question.** Where does a deterministic `if validated_findings < 3 → re-run stage
on Opus 4.6` guard plug in post-stage, and what does it cost per fire?

**Location — `src/agent_stages.py:1685-1690` (the stage-finalization `model_copy`).**
`findings` is fully computed by `:1683`; the two slots are written at `:1685-1690`.
The guard is a deterministic check inserted between those points (or, equivalently,
a thin Python stage placed between `BiasLanguageStage` and `compose_transparency_card`
— they are adjacent in both production and hydrated stage lists,
`src/runner/stage_lists.py:170-171, 242-243`):

```python
# conceptual placement (NOT implemented here — out of scope)
validated = [f for f in findings if f.get("finding_valid")]      # after :1683
if len(validated) < 3:
    # re-run the SAME stage input on an Opus-4.6-configured agent,
    # write its findings + reader_note to the two slots instead
    ...
return topic_bus.model_copy(update={...})                         # :1685
```

This is clean because:
- The two slots are **single-writer** (`src/bus.py:777-778`); re-running on Opus
  and writing the same two slots violates no bus invariant.
- **No downstream validator is keyed on findings content.** The citation harvest
  intentionally does **not** scan `bias_language_findings`
  (`src/stages/topic_stages.py:1331-1337`); render is pure selection
  (`src/render.py:325,347`). So an Opus re-run is transparent downstream.
- The repo already has the **precedent pattern**: `_call_with_empty_retry` /
  `_call_agent_with_empty_retry` (`src/agent_stages.py:106-189`) is a
  deterministic re-roll mitigation for DeepSeek's empty-emission mode. The
  `<3 findings → Opus` guard is its sibling (re-run target = Opus instead of a
  re-roll). It also directly addresses the shadow's one hard miss (2026-06-13 t2:
  candidate emitted **0** findings vs Opus 8 — `SHADOW-REPORT.md`), which a
  `<3` guard would have caught and repaired.

**Cost per fire — ≈ $0.046 (one Opus 4.6 bias_language call).**
From 15 recent production `run_stage_log.jsonl` BiasLanguageStage entries
(2026-06-11, -15, -19, -20, -21):

| metric | value |
|---|---|
| per-call cost range | **$0.0392 – $0.0529** |
| mean | **≈ $0.046 / fire** |
| tokens / call | 5 700 – 6 900 |

So each guard activation costs one full Opus call (~$0.046) — the very cost the
migration is trying to avoid, but paid only on the rare low-finding topics rather
than every topic. Fire rate on shadow evidence was ~1/15 topics (the 0/8 day);
both Q3 measurement topics had 5 and 10 validated findings, i.e. would **not**
fire.

---

## Recommendation summary (for the loop-design task that follows)

1. **Transport:** `json_object` + deterministic excerpt/schema guard for all
   deepseek candidate turns; DeepSeek-direct primary uses **strict tools**. No
   `response_format: json_schema` strict on deepseek. (Q1)
2. **Plumbing:** build the multiturn at the `agent` boundary of
   `BiasLanguageStage`; the final turn matches `BIAS_DETECTOR_SCHEMA`. **Zero**
   bus/schema/render change. (Q2)
3. **Latency budget:** plan for **~3× / +30–45 s per topic** for a 3-turn split —
   in-band, not a blocker. (Q3)
4. **Fallback guard:** deterministic `<3 validated findings → Opus 4.6` at
   `agent_stages.py:1685-1690`, ~$0.046/fire, mirroring the existing
   `_call_with_empty_retry` precedent. (Q4)

**No production or master-prompt changes were made. `agents/bias_detector/*`
untouched. Throwaway measurement code is under `~/iw-stage-bench/shadow/`.**
