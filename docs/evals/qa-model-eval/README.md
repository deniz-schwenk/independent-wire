# QA-stage GLM-5.2 shadow run

Collection harness for the QA-stage model eval (`TASK-QA-GLM-SHADOW`).
**Collection only** — judging is a separate, later, anchor-free task.

For each production run day, we reconstruct the *exact* `qa_analyze` input per
topic from on-disk run state, pair it with the incumbent's production QA output
(Sonnet 4.6, reasoning=none), and produce a GLM-5.2 shadow output on the
identical input and schema. Everything here is untracked scratch — nothing is
committed, and production is never touched.

## What differs from production `qa_analyze`

Held identical: prompts (`agents/qa_analyze/SYSTEM.md` + `INSTRUCTIONS.md`, read
as-is), the strict `QA_ANALYZE_SCHEMA`, `temperature=0.1`, `max_tokens=64000`,
and the reconstructed input (article + sources + preliminary divergences +
position clusters + missing positions). Only three knobs are the eval variables:

| Knob | Incumbent | Shadow candidate |
|---|---|---|
| model | `anthropic/claude-sonnet-4.6` | `z-ai/glm-5.2` |
| reasoning | `none` | `effort: xhigh` |
| provider routing | (default) | Baidu **fp8**, `allow_fallbacks: false` |
| max_tokens | `64000` | `131072` (see note) |

**max_tokens deviation (documented, necessary).** Production `qa_analyze` uses
`max_tokens=64000` — a budget sized for the *non-reasoning* incumbent. At
`effort: xhigh` the reasoning trace alone can exceed 64000 completion tokens on
large topics: the 2026-07-02 probe on topic-0 (82 KB input, 19 sources) hit the
64000 cap and truncated to **zero parseable output**. `max_tokens` is not one of
the three eval variables, nor the input, nor the schema, so we raise it to the
Baidu fp8 endpoint's `max_completion_tokens` (**131072**). The diagnostic
(`diag.py`) confirmed a clean `finish_reason: stop` with valid JSON at that
budget. This does not bias a later comparison — 64000 was never binding for the
incumbent (its answers are a few thousand tokens).

GLM-5.2 fp8 + strict structured outputs is verified only at Baidu (per the task
brief and the `docs/DEEPSEEK-FP8-PIN-2026-07.md` verification method); the pin is
fail-loud, so if Baidu can't serve a topic the shadow call for that topic fails
and is logged — no silent fp4/quant fallback. Routing reuses the `Agent`
`provider_routing` shipped in commit `b1edb22`.

## Layout

```
scratch/qa-shadow/
  qa_shadow.py                 # shared lib (reconstruction + GLM agent builder)
  collect.py                   # reconstruct inputs from run state (free, disk-only)
  shadow.py                    # GLM-5.2 shadow caller (costs money)
  collection_manifest.json     # what was reconstructed
  BACKFILL-REPORT.md           # backfill scope + counts + findings
  {date}/topic-{n}/
    input.json                 # {"message", "context"} — the exact agent.run input
    incumbent_output.json      # production QA output (problems/corrections/article/divergences)
    incumbent_meta.json        # incumbent model + cost_usd + tokens (from run_stage_log.jsonl)
    reconstruction.json        # provenance: run_id, source snapshot, input shape counts
    shadow_output.json         # GLM-5.2 structured output (same schema shape)
    shadow_meta.json           # served provider, cost, tokens, latency, schema_valid, status
```

## Daily manual command (run after each production daily run)

From the repo root, after the daily pipeline has written `output/{date}/_state/`:

```bash
# 1. Reconstruct that day's qa_analyze inputs + incumbent outputs (free):
.venv/bin/python scratch/qa-shadow/collect.py --date "$(date +%F)"

# 2. Produce the GLM-5.2 shadow outputs for that day (costs ~$0.10-0.20/topic):
.venv/bin/python scratch/qa-shadow/shadow.py --date "$(date +%F)"
```

`shadow.py` is idempotent — a topic that already has `shadow_output.json` is
skipped (use `--force` to re-run). `OPENROUTER_API_KEY` is auto-loaded from
`.env`. Add `--limit 1` to probe a single topic first.

> **Latency/cost note (measured 2026-07-02, Baidu fp8):** GLM-5.2 at
> `effort: xhigh` is slow and cost scales with the reasoning trace. A small/
> medium topic completes in ~3 min for ~$0.065 (~11 k reasoning tokens); a
> large complex topic (topic-0) runs ~13 min. Budget several minutes to ~15 min
> per topic. The `httpx` read timeout is 300 s but OpenRouter SSE heartbeats
> keep long generations alive, so calls stream rather than time out. A topic
> whose reasoning still exceeds 131072 completion tokens fails-and-logs.

## Backfill (past days)

```bash
.venv/bin/python scratch/qa-shadow/collect.py --all      # reconstruct every reconstructable day (free)
.venv/bin/python scratch/qa-shadow/shadow.py  --date 2026-06-30   # then shadow specific days
.venv/bin/python scratch/qa-shadow/shadow.py  --all      # or every collected topic missing a shadow output
```

`collect.py --list` enumerates reconstructable dates without writing anything.
See `BACKFILL-REPORT.md` for the scope actually run and why.

## Budget guard

`shadow.py` accounts cost per call and aborts the batch if any single call
exceeds `MAX_COST_PER_CALL_USD` ($1.00) — loop safety. `max_tokens=64000`
bounds the output structurally. Expected real cost is ~$0.10–0.20/topic.
