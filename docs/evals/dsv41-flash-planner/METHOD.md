# TASK-EVAL-DSV41-FLASH-PLANNER — method and identity evidence

## 1. Model identity (done before any batch call)

**Resolved id: `deepseek/deepseek-v4.1-flash`. Serving path: OpenRouter with the
native-provider pin `{"order": ["deepseek"], "allow_fallbacks": false}`.**

### T2d-a4 provider-identity check — PASS

`GET /api/v1/models/deepseek/deepseek-v4.1-flash/endpoints` returns 12
endpoints, and the FIRST carries the vendor's own provider:

```
provider=DeepSeek     tag=deepseek     ctx=1048576  max_completion=384000
```

The other 11 (DeepInfra, Fireworks, Morph, SiliconFlow, Modal, Wafer, Parasail,
GMICloud, Io Net, Novita, Venice) are third-party hosts and are excluded by the
pin. For contrast, `deepseek/deepseek-v4-flash-0731` has **28 endpoints and no
`deepseek` tag among them** — the same asymmetry T3a used to establish that the
vendor serves only its current build.

Every one of the 9 arm-F calls came back `provider_used: DeepSeek`, so identity
is established at call time, not only in the catalogue.

### Channel C (api.deepseek.com) — checked, and NOT used. Why.

`GET https://api.deepseek.com/models` returns exactly two ids:

```
deepseek-flash      (owned_by: deepseek)
deepseek-v4-pro     (owned_by: deepseek)
```

`deepseek-v4.1-flash` is **rejected by name**: *"The supported API model names
are deepseek-flash, deepseek-v4-pro, but you passed deepseek-v4.1-flash."*
The old `deepseek-v4-flash` id is accepted but the server echoes back
`deepseek-flash`, and `deepseek-v4-flash-0731` is rejected — i.e. the vendor has
renamed its single flash slot since T2d, which is *consistent with* a generation
roll but is not proof of one.

Three attempts to establish what build `deepseek-flash` actually is, all
negative:
- **Server echo** is the undated alias itself (`model: deepseek-flash`), so it
  carries no version.
- **Ceiling fingerprint fails to discriminate**: channel C accepts
  `max_tokens` 393216, 384001 and 384000 alike, so the 384000 figure on the
  vendor's OpenRouter endpoint cannot be used to tell the two builds apart.
- **Price fingerprint is not observable per call**: api.deepseek.com returns no
  `usage.cost`, and the repo's `DEEPSEEK_DIRECT_PRICES` table has no
  `deepseek-flash` key at all — a channel-C flash call would trip the
  "served model id absent from the table" path and report **no cost**, which
  would also have broken this task's per-call cost ledger.

The brief's rule is "If yes, prefer channel C; if not, OpenRouter with the
native-provider pin." Channel C does not expose the model under an id that names
v4.1, and the build behind its undated alias cannot be established from the API
surface. **The pinned OpenRouter route is the only path on which the served
build is both named `v4.1` and demonstrably the vendor's own endpoint**, so that
is the candidate's serving path, and this is a documented deviation from a
channel-C preference that could not be exercised.

Vendor pricing read from that endpoint on 2026-09-12, USD/M tokens:
offpeak 0.15 in / 0.60 out / 0.003 cache-read; peak (UTC Mon-Fri 01:00-04:00 and
06:00-10:00) exactly 2x. The peak windows match the ones the repo already
encodes for the other DeepSeek models.

## 2. Arms

| arm | model | route | reasoning | temperature | max_tokens | structured output |
|---|---|---|---|---|---|---|
| **C** | `deepseek-v4-pro` | channel C (`deepseek_direct`) | `low` | omitted | 24000 | `json_object` |
| **F** | `deepseek/deepseek-v4.1-flash` | OpenRouter + `deepseek` pin | `low` | omitted | 24000 | `json_object` |

The candidate mirrors the champion on every knob the brief names. Nothing in the
v4.1 vendor docs asked for a different operating point, so nothing was deviated.
`json_object` (not strict schema) on both arms: api.deepseek.com ignores the
schema block, and the OpenRouter strict path injects `require_parameters: true`,
which filters the vendor's own endpoint off its own route — this is why the
production planner already runs `json_object` on both of its DeepSeek rungs.

A **bare `Agent`** is used, never `PlannerWithFallbackLadder`: a rung firing
would silently substitute a different model and invalidate the arm.

## 3. A premise in the brief that did not hold — 2026-09-06

The brief says arm C is "existing deepseek-v4-pro production outputs, runs
2026-09-06 / 07 / 08". It is not, for one of the three days.
`output/2026-09-06/_state/run-*/run_stage_log.jsonl` records all three planner
calls that day as:

```
anthropic/claude-opus-4.6   Claude Platform on AWS   $0.101 / $0.089 / $0.057
```

That day's production run predates the planner swap taking effect; 09-07 and
09-08 both show `deepseek-v4-pro  deepseek_direct`. Only **6 of the 9** champion
instances the brief assumes actually exist.

Handling, stated rather than papered over:
- The three Opus-4.6 plans are preserved as arm **`I`** (pre-swap incumbent) in
  `candidates/`, as evidence. They are **not** a judged arm.
- The champion for 09-06 was **reconstructed** by re-running
  `deepseek-v4-pro` at the exact production operating point on that day's frozen
  input (arm `Cstar`, 3 calls, $0.0455). This is a deviation from the brief's
  "NOT re-generated / zero cost" and is flagged everywhere it affects a number.
  Its costs ($0.0138-0.0165) sit inside the real production range for the other
  two days ($0.0121-0.0176), which is the like-for-like check.
- **Both** readings are reported: the n=9 headline and the n=6 subset over the
  two days whose champion is untouched production output.

## 4. Stage isolation and read-only production

Each arm consumes the frozen production input of `researcher_hydrated_plan` for
that day/topic — the `topic_buses.assemble_hydration_dossier.{n}.json` snapshot
written immediately before the stage ran. No candidate output feeds any other
stage. The three `_state/` directories were copied to `frozen/` and every run
reads only from there; `--reuse` was never invoked. A sha256 manifest of all 351
files under `output/2026-09-0{6,7,8}` was taken before any call and re-taken at
the end (`logs/prod_state_manifest.PRE.txt` / `.POST.txt`).

## 5. Judging

- **Rubric**: `scratch/eval/t5a-researcher-plan/RUBRIC-researcher-plan.md`
  **verbatim**, copied to `rubrics/planner.md`. Reusing T5a's frozen rubric is
  deliberate — it is the standard the planner swap itself was decided on, so
  this verdict is comparable to that one. Its D1-D6 anchors, its mandatory
  `angle_groups` partition (the teeth against the translation-matrix
  anti-pattern) and its "score the plan, not the harvest" limitation all carry
  over unchanged.
- **Documented deviation from the rubric's own protocol**: T5a says "no judge
  ever sees another output". This task's brief requires "one judging session
  across both arms". Within-case judging is what removes the cross-run D1 drift
  T5a measured at ~0.667, so the brief's instruction is followed, and the
  rubric's intent is protected by making the judge form its
  `dossier_open_questions` reference list ONCE, **before opening any plan**, and
  produce a full independent per-output object for each arm against the absolute
  anchors. Judges are told explicitly that "better than the other one" is not a
  score.
- **Blind**: opaque `OUT-xxxxxx` ids from a seeded shuffle
  (`SEED = dsv41-planner-2026-09-12`); keymap written pre-dispatch and stored one
  level ABOVE the case dirs.
- **Ground truth** is the exact user message the planner received, captured free
  by `capture_inputs.py` (Agent.run stubbed, no API call).
- **Honest-Detector**: every case carrying a D5 invention charge was fully
  double-judged by a second judge that never saw the first verdict. A charge is
  COUNTED only when both judges cite an overlapping span against the SAME
  output; overlap is decided deterministically in `confirm_charges.py`
  (containment, or Jaccard >= 0.5, or same query_index plus a shared token),
  never by a model. The tokenizer is Unicode-aware because charges routinely
  quote Arabic, Hebrew and CJK spans.
- Judges are spawned Opus-5 subagents. **Judging cost $0.00.**
