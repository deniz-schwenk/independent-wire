# EVAL-GLM53-FM-CONFIRM — method and premise-check evidence

Cold-read confirmation of the Flash_M finding on data that did not exist when
the addendum ran: production runs of **2026-09-09 / 10 / 11**, executed
2026-09-12 after all three days had completed and published.

## 1. Premise check (run FIRST, before any call)

Requirement: both stages must have run `z-ai/glm-5.2` as primary with no
fallback on each day. Evidence read from each day's
`output/{day}/_state/run-*/run_stage_log.jsonl`:

| day | HydrationPhase2Stage | QaAnalyzeStage |
|---|---|---|
| 2026-09-09 | t0/t1/t2 `z-ai/glm-5.2` Baidu, `hydration_phase2_fallback_used: false` | t0/t1/t2 `z-ai/glm-5.2` Baidu, `qa_fallback_used: false` |
| 2026-09-10 | t0/t1/t2 `z-ai/glm-5.2` Baidu, fallback false | **t0 ABSENT** · t1/t2 `z-ai/glm-5.2` Baidu, fallback false |
| 2026-09-11 | t0/t1/t2 `z-ai/glm-5.2` Baidu, fallback false | t0/t1/t2 `z-ai/glm-5.2` Baidu, fallback false |

**Every champion instance that exists is a clean glm-5.2 primary serve. No day
is excluded for a wrong model.** But one instance does not exist:

### 2026-09-10 topic 0 — the topic FAILED mid-pipeline

`run_bus.json`'s `run_topic_manifest` records `tp-2026-09-10-001` as
`status: "failed"`, with `stages_completed` ending at `consolidate_actors`. The
run log carries one non-success row for the whole day:

```
topic-0  failed  Agent 'resolve_actor_aliases_fallback': API error 404:
  'No endpoints found for deepseek/deepseek-v4-flash-0731.'
  routing_funnel: Initial Endpoints 28 -> Filter by Parameters ...
```

The topic died at `ResolveActorAliasesStage` and never reached `WriterStage`,
so there is no `topic_buses.WriterStage.0.json` to feed QA and no champion QA
output. `HydrationPhase2Stage` had already run and succeeded before the
failure, so phase2 keeps that instance.

**Consequence, per the brief's instruction not to reconstruct champions:**

| stage | n | note |
|---|--:|---|
| `hydration_phase2` | **9** | complete |
| `qa_analyze` | **8** | 2026-09-10 t0 has no champion |

The exclusion is encoded once, as data, in `harness.py::MISSING` and
`build_judging.py::MISSING`, so no stage of the pipeline can silently
re-introduce it.

This failure is a **live production incident, not an eval artefact**: it cost
that day one of three published Topic Packages. It occurs on 1 of the 7 days
2026-09-06…12 (all other days: 0 failures). Diagnosing or fixing it is outside
this task's scope; it is reported because the Architect should see it.

## 2. The arm

Identical to the addendum's F_M arm, knob for knob:

| | F_M |
|---|---|
| model | `z-ai/glm-5.3-flash` |
| provider | openrouter, pin `{"order": ["z-ai"], "allow_fallbacks": false}` |
| reasoning | `max` |
| temperature / top_p | 1.0 / 0.95 (published vendor pair) |
| max_tokens | 120000 |
| structured output | `json_object` + local validation |

`confirm/harness.py` imports the addendum's stage table and bus loaders and
rebinds only the frozen-state path, so the two batches cannot drift apart in
plumbing. A **bare `Agent`** is used, never a `*WithFallback` wrapper.

## 3. Judging

- Fresh sessions per stage, each case carrying that day's production champion
  and F_M; paired within session; same rubrics (read-only from the prior
  batch), same verdict shape, same statistics.
- Blind: opaque `OUT-xxxxxx` ids from a new seed
  (`glm53-fm-confirm-2026-09-12`); keymap written pre-dispatch, stored above the
  case dirs.
- Ground truth is the exact user message each stage handed its agent, captured
  free by `prepare.py` (Agent.run stubbed, no API call).
- **Honest-Detector**: all 11 cases carrying a fabrication charge were fully
  double-judged; a charge counts only when two independent judges cite an
  overlapping quote against the same output, decided deterministically in
  `confirm_charges.py`.
- Judges are spawned Opus-5 subagents. **Judging cost $0.00.**

## 4. Confirmation criterion — fixed before the data

Stated in the brief and evaluated mechanically in `aggregate.py`:

> CONFIRMED for a stage iff F_M's paired Δ vs C is **positive** AND its
> **CI95 excludes zero** on the fresh data. Anything else = NOT confirmed.

The code prints the verdict from that test directly; there is no path in which
a stage is talked across the line.

## 5. Read-only production

State of 09-09/10/11 copied to `confirm/frozen/` before any call; `--reuse`
never invoked. sha256 manifest of all 330 files under those three days taken
before and after. Prior-batch artifacts read, never written.
