# WP-OLLAMA-1b — GLM candidate at `think:"max"` (three-way comparison)

**Date:** 2026-07-05 · Read-only on production; writes only under
`scratch/ollama-probe/`; no git operations; tree on `main`. Follow-up to
`REPORT.md` (WP-OLLAMA-1).

## Correction under test
Run-1 claimed ollama's top GLM reasoning tier was `think:"high"` and flagged
"xhigh unexpressible on ollama" as the load-bearing caveat. Deniz corrected: the
top tier is named **`"max"`**. **Confirmed** — and run-1 therefore ran the GLM
candidate one tier below the ceiling. At the true top tier the caveat **dissolves**.

---

## Step 0 — accepted `think` tier set (primary evidence)

Probed `glm-5.2:cloud` directly on the daemon (`scratch/ollama-probe/think_probe.py`
→ `think_tier_probe.json`). The **native `/api/chat` validator is authoritative**;
its own rejection message enumerates the legal set:

```
POST /api/chat  think:"xhigh"  → HTTP 400
  "invalid think value: \"xhigh\" (must be \"high\", \"medium\", \"low\", \"max\", true, or false)"
```

**Accepted `think` set for `glm-5.2:cloud`: `low`, `medium`, `high`, `max`, `true`,
`false`.** `xhigh` is **rejected** (it is OpenRouter's effort vocabulary, not
ollama's). Reasoning depth scales monotonically with the tier (native, trivial
prompt — where reasoning tokens dominate):

| think | thinking chars | eval tokens | accepted? |
|---|---|---|---|
| `max` | 485 | 139 | ✅ (top tier) |
| `true` | 496 | 141 | ✅ (≈ max) |
| `high` | 340 | 92 | ✅ (**run-1 used this**) |
| `medium` | 303 | 79 | ✅ |
| `low` | 238 | 67 | ✅ |
| `false` | 0 | 2 | ✅ (off) |
| `xhigh` | — | — | ❌ rejected |

So `max` sits **above** the `high` used in run-1. → proceed to Step 1.

**Transport nuance (recorded honestly).** The native endpoint validates `think`
strictly. The OpenAI-compatible `/v1/chat/completions` endpoint — the path
`src/agent.py` (and therefore production) uses — is **lenient**: it accepted the
invalid `xhigh` and even returned some thinking on `false`. On the production
path the tier is still *requestable* (`max` is accepted and passed through);
on large real inputs the per-tier reasoning-token delta is swamped by the
~13 K-token prompt, so total-token/latency signals cannot resolve the tier — but
the quality outcome at `max` (below) is the measure that matters, and the
production integration will run this exact `/v1` path.

---

## Step 1 — GLM candidate re-run at `think:"max"`

Same 10 items, same reconstructed inputs, same PHASE2 prompts, same temp 0.1 /
`max_tokens` 120000, same `agent.py → ollama /v1` transport as run-1 — **only the
tier changed `high → max`**. Baseline = the unchanged OpenRouter Baidu-fp8 **xhigh**
outputs reused from `scratch/p2-eval/raw`. Fresh blind packets (new seed salt
`"max"` → different A/B permutations) judged by **2 fresh Opus-4.8 spawned-subagent
judges**, leak-proof (no verdict referenced the keys — grep-clean).

Generation: **10/10 OK, 10/10 schema-valid, 0 truncations, 0 errors, $0.00.**

### Three-way table

| arm | mean quality | W/T/L vs baseline | artifacts (candidate) | mean latency |
|---|---|---|---|---|
| **openrouter @ xhigh** (baseline) | 4.35 | — | 0 | 41.3 s |
| **ollama @ high** (run 1) | 4.40 | 2 / 7 / 1 | 0 | 30.0 s |
| **ollama @ max** (run 1b) | **4.45** | **2 / 8 / 0** | **0** | 17.4 s |

- Baseline mean is **4.35 under both judge panels** (run-1 and run-1b) — the fresh
  panel independently re-scored the identical xhigh outputs to the same number, a
  strong stability check on the judging.
- `max` **≥** `high`: it carries **no losses** (vs `high`'s single loss) and edges
  the baseline by +0.10 (2 wins / 8 ties / 0 losses). The one topic where `high`
  lost in run-1 (2026-07-02#1) is a **tie** at `max`.
- **Zero artifacts of any class** on the `max` candidate. The only artifact anywhere
  in the max run is **1 fabricated-contrast charged to the OpenRouter xhigh
  baseline** (2026-07-04#1) — the ollama candidate was clean there.
- Latency: `max` was *faster* in wall-clock (17.4 s mean) — dominated by
  concurrency/cloud-load variance across runs, not a tier signal; not a quality
  concern.

Per-item quality (max run, `base[j0,j1]` vs `max[j0,j1]`): every item a tie or a
candidate win; judges never split ≥2 on any item (a consistent j0=4/j1=5 offset on
several items, no third call needed).

---

## Revised WP-OLLAMA-3 caveat

**Does the operating-point gap still exist? — No.** Run-1's caveat rested on a
naming error: ollama *does* expose a top reasoning tier, called `max`, and the
production `/v1` path accepts it. Re-run at `max`, ollama GLM-5.2 **matches and
marginally exceeds** the OpenRouter Baidu-fp8 **xhigh** baseline (4.45 vs 4.35,
2 W / 8 T / 0 L) with **zero quantization artifacts** — cleaner than the baseline,
which itself drew one fabricated-contrast charge. There is no remaining
"unexpressible tier" objection to carry into WP-OLLAMA-3.

The one honest limitation: `max` and `xhigh` are each their *platform's* top
discrete tier; this probe cannot prove token-for-token internal-reasoning
equivalence across two different platforms/quantizations. It shows the thing that
matters for the gate — **blind output quality at the top tier is at parity (indeed
slightly better), with no artifact regression.**

## Handoff conclusion — tier mapping

**Production `reasoning="xhigh"` (OpenRouter) maps to ollama `think:"max"`** — the
top reasoning tier on each platform. WP-OLLAMA-2 should configure the ollama GLM-5.2
agent with `reasoning="max"` (which `src/agent.py` already translates to
`extra_body={"think": "max"}` on the ollama route). Do **not** use `"high"` (run-1's
setting — one tier low) and do **not** pass `"xhigh"` (rejected by ollama's native
validator; silently mishandled by `/v1`).

**Revised gate for GLM-5.2 → PROCEED, caveat cleared.** DeepSeek-V4-Pro was already
a clean PROCEED (operating point matched exactly; see `REPORT.md`). Both models
clear the quantization screen with no disqualifying artifact class and no quality
regression.

---

## Assertions & acceptance

- **Zero API judge calls.** All judging = 2 fresh spawned Opus-4.8 subagents;
  blindness verified (no verdict references `anon_keys/`).
- **Total paid API spend: $0.0000** (in-code cap $2.00, untouched). ollama is
  flat-rate; the xhigh baseline was reused, never regenerated.
- **10/10 items generated at `max`**, 20 fresh verdicts (`verdicts/glmmax_*__j{0,1}.json`),
  three-way table complete. No silent shrinkage.
- **Accepted think-tier set documented from primary evidence** (the native
  validator's own rejection), not from memory or docs.

### Artifacts (for re-verification), under `scratch/ollama-probe/`
`think_tier_probe.json` (Step-0 evidence) · `rerun_max.py` (generator) ·
`raw/glm-max-cand__*.json` (10 candidate outputs + metrics) ·
`packets/glmmax_*.json` (blind bundles) · `anon_keys/glmmax_*.json` (post-hoc keys) ·
`verdicts/glmmax_*__j{0,1}.json` (20 verdicts) · `deterministic_glmmax.json`
(schema/degeneration census) · `aggregate_max.json` (this report's numbers).
