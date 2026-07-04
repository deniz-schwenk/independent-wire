# Bias-Stage Model Eval — GLM-5.2 & DeepSeek-V4-Pro (fp8-pinned) & Sonnet-5 vs Opus 4.6 (+ Opus-4.8 stability ceiling)

Two-phase re-eval of the `bias_language` stage (the project's one documented
commercial-core dependency). Phase 0 is a cheap cache-cold **stability gate**;
Phase 1 (quality) runs only for gate survivors. Binding methodology:
`docs/BIAS-LANGUAGE-MODEL-EVAL-2026-06-28.md`. This eval supersedes that one on
two axes it explicitly left open: (1) the two open-weight candidates are now
**pinned to fp8** (the 2026-06-28 DeepSeek run was at UNKNOWN quantization — a
possible fp4 confound); (2) **Sonnet-5** is added. **Opus-4.8** (adaptive
thinking, effort high) is additionally run through the same stability grid as a
ceiling reference (not a swap candidate). Frozen gate criterion + article
manifest: `scratch/bias-eval/GATE-CRITERION.md`. Raw (75 calls):
`scratch/bias-eval/raw/`. Read-only on production throughout; `main` untouched.

## 1. Verdict

**Keep Opus 4.6 on `bias_language`. No candidate cleared Phase 0 — none was
quality-tested.** All three challengers churn their confirmed-span verdict
across identical cache-cold repeats **more than the incumbent does** — the
2026-06-28 disqualifier, reproduced against three new models under the
incumbent's own measured bar. The result is robust to the span-overlap metric
(exact-string *and* substring-tolerant Jaccard agree on the ranking). Two
findings sharpen the earlier record:

- **The fp4 confound is resolved and does not rescue DeepSeek.** Pinned to
  fp8 (Baidu, all 15 calls, loud-fail routing), DeepSeek V4 Pro no longer
  reproduces the 2026-06-28 *over*-flagging (1.9–2.4×). Instead it **severely
  under-flags** (0.87 valid findings/article vs the incumbent's 4.13) and is
  the **least stable arm** (Jbar 0.80). Quantization materially changes its
  behaviour; fp8 flips the failure mode from unstable-over-flag to
  unstable-under-flag, but does not produce a usable, stable detector.
- **Sonnet-5 is the closest challenger and still fails.** It flags at nearly
  the incumbent's level (3.53 valid/article) but its confirmed-span set churns
  ~1.6× more (Jbar 0.685 vs 0.510; soft 0.551 vs 0.337). Closest ≠ no-worse.
- **Opus-4.8 (ceiling reference) is the ONLY arm to pass the gate — but only by
  under-flagging, and it does not beat the incumbent as a detector.** Added at
  the user's request (adaptive thinking enabled, effort high). It ties the
  incumbent on stability (Jbar 0.496 vs 0.510; soft 0.264 vs 0.337 — a ~0.01
  exact-Jbar gap on n=5, i.e. noise) while flagging **40% as much** (1.67 valid
  vs 4.13). Its aggregate "pass" is carried by two articles where it flags 0–1
  (Bolsonaro 0/0/0, Pope 1/1/1 → J=0); on the richer articles it churns as much
  as anyone (US-Iran 3/3/3 but Jexact 0.93). Takeaway: **even the strongest
  current model only ties the incumbent's stability and loses coverage — the
  incumbent is already at the stability ceiling for this task.** Opus-4.8 is not
  a swap candidate (it is the golden/ceiling reference) and was not
  quality-tested; whether its leaner flagging is higher-precision or
  missing-bias is a Phase-1 question, not entered.

This reaffirms the deliberate, documented acceptance of one commercial
dependency on this stage — an unstable bias detector destroys the credibility
it exists to protect (Vision Paper standard).

## 2. Setup

### 2a. Prompt-stability window
Last `agents/bias_detector/` prompt change: **2026-05-28** (`0d66d56`). Last
`BIAS_DETECTOR_SCHEMA` change: 2026-05-19 (`6f59fb4`, `finding_valid`). Window
start = 2026-05-28. All production topics on disk (06-05→07-04) are in-window.

### 2b. Arms & operating points
Prompts (`agents/bias_detector/{SYSTEM,INSTRUCTIONS}.md`) and
`BIAS_DETECTOR_SCHEMA` are **identical across all arms**; only model / provider
/ reasoning / temperature differ. Temperature is held at the incumbent's
production 0.1 across every arm that accepts it, to isolate the model's
*intrinsic* verdict determinism rather than a sampling-temperature difference.

| arm | model | temp | reasoning | max_tokens | provider pin | served |
|---|---|---|---|---|---|---|
| **incumbent** | anthropic/claude-opus-4.6 | 0.1 | none | 32000 (prod default) | — | Anthropic |
| **glm** | z-ai/glm-5.2 | 0.1 | effort:xhigh | 120000 | baidu/ambient/venice fp8 | Baidu (15/15) |
| **deepseek** | deepseek/deepseek-v4-pro | 0.1 | effort:xhigh | 120000 | baidu/wandb/parasail fp8 | Baidu (15/15) |
| **sonnet5** | anthropic/claude-sonnet-5 | none | enabled, effort:high | 64000 | — (Anthropic-served) | Azure |
| **opus48** (ceiling) | anthropic/claude-opus-4.8 | none | enabled, effort:high | 64000 | — (Anthropic-served) | Anthropic |

DeepSeek V4 Pro **accepted** `temperature=0.1` under xhigh reasoning (probed;
no 400), so it runs at the incumbent's temperature like the other open arms.
Sonnet-5 omits temperature (5-family 400s on any non-default value — the one
documented deviation, same as the perspective swap).

### 2c. Input fidelity (read-only)
Each arm receives the **exact production stage input** — reconstructed from the
stored `topic_buses.BiasLanguageStage.N.json` snapshots: `article_body =
qa_corrected_article.body` and the deterministic `bias_card` rebuilt via the
production `_build_bias_card_for_agent_input`, with the verbatim stage message.
Production is never run; snapshots are read, never written.

## 3. Phase 0 — stability gate

### 3a. Frozen criterion (transcribed from the 2026-06-28 method)
The 2026-06-28 disqualifier was **run-to-run instability of the calibration
verdict** on identical input ("the count is steady; *which spans confirm* is
not"), with the incumbent — not an abstract number — setting the bar. Formal
metrics per article (3 cache-cold repeats, `Vi` = set of confirmed/valid
`excerpt` strings in repeat i):

- **valid-span instability** `J = 1 − mean pairwise Jaccard(Vi,Vj)` — the
  verdict-set churn (the root-cause axis).
- **valid-count spread** `C = max|Vi| − min|Vi|` — the worst-case swing axis
  (the doc's "4→16", "Δ5").

> **GATE: PASS ⇔ Jbar(m) ≤ Jbar(inc) AND Cmax(m) ≤ Cmax(inc)**, plus a hard
> precondition that no call is errored / schema-invalid / empty-emission /
> truncated. `Jbar` = mean-over-5-articles of J; `Cmax` = max-over-5 of C.
> Ties pass ("no worse than"). (Schema note: the brief's "severity
> distribution" maps to the `issue`-category distribution — `severity` was
> removed from the schema 2026-06-02 `2a41570`; category-dist churn `D` and
> total-count spread `Ctot` are reported for context, not gated.)

### 3b. Results (5 articles × 5 arms × 3 cache-cold repeats = 75 calls, all OK)

| arm | **Jbar** (exact) | Jbar (soft) | **Cmax** | Dbar | mean valid | mean total | mean tok | max tok | $ / 15 | mean s |
|---|---|---|---|---|---|---|---|---|---|---|
| **incumbent (bar)** | **0.510** | **0.337** | **3** | 0.191 | **4.13** | 7.27 | 6,072 | 7,150 | 0.665 | 18 |
| opus48 (ceiling) | 0.496 | 0.264 | 2 | 0.178 | 1.67 | 2.93 | 9,786 | 11,629 | 1.420 | 33 |
| sonnet5 | 0.685 | 0.551 | 3 | 0.367 | 3.53 | 3.80 | 13,818 | 17,523 | 1.173 | 65 |
| glm | 0.798 | 0.678 | 2 | 0.600 | 1.33 | 1.53 | 11,454 | 17,878 | 0.438 | 83 |
| deepseek | 0.800 | 0.800 | 3 | 0.400 | 0.87 | 0.87 | 10,907 | 14,354 | 0.162 | 98 |

`mean tok` / `max tok` = `usage.total_tokens` per call (reasoning + output).
No call truncated (all maxima well under each arm's max_tokens). The incumbent
(reasoning=none) is the leanest at 6,072; Opus-4.8 at effort:high spends ~1.6×
that (9,786) for its adaptive thinking; the three explicit-effort arms spend
10,900–13,800.

`soft` Jaccard treats one normalized excerpt as matching another if either
contains the other (tolerates near-duplicate spans like "unprecedented" vs
"unprecedented scope"). It only *lowers* churn — and the ranking is identical
under both, so no candidate's failure is a spans-differ-cosmetically artifact.

### 3c. Gate verdict

| arm | Jbar ≤ 0.510? | Cmax ≤ 3? | precondition | **GATE** |
|---|---|---|---|---|
| sonnet5 | 0.685 ✗ | 3 ✓ | clean | **FAIL** |
| glm | 0.798 ✗ | 2 ✓ | clean | **FAIL** |
| deepseek | 0.800 ✗ | 3 ✓ | clean | **FAIL** |
| opus48 *(ceiling, not a swap candidate)* | 0.496 ✓ | 2 ✓ | clean | PASS\* |

All three **swap candidates** exceed the incumbent's own valid-span
instability. The count-spread axis (Cmax) is not where they fail — and for the
open-weight arms the low Cmax is **degenerate, not stable**: it is small because
they barely flag anything (GLM 1.33, DeepSeek 0.87 valid/article), so a single
flipped span already saturates their tiny verdict set (that is exactly why their
*Jbar* is high). This is the two-phase design working as intended: a
stably-nothing detector would clear a count-spread test but is caught by the
churn axis and, had any survived, by Phase-1 quality.

\* **Opus-4.8 passes the stability gate but is the ceiling reference, not a swap
candidate**, and its pass does not make it a better detector. It ties the
incumbent on stability (0.496 vs 0.510 — noise on n=5) *by under-flagging*: it
confirms 1.67 valid/article vs the incumbent's 4.13, and its aggregate Jbar is
pulled down by two articles where it flags 0–1 (Bolsonaro 0/0/0, Pope 1/1/1 →
J=0). Where it flags comparably it churns as much as the failing arms (US-Iran
3/3/3 but Jexact 0.93; Anthropic-IPO 1/2/2, Jexact 0.89). So the strongest
current model does not *beat* the incumbent's stability — it matches it while
losing coverage. That the ceiling only ties Opus-4.6 is the strongest
statement in this eval that **the incumbent is already at the stability ceiling
for this task**; there is no stability headroom for an upgrade to capture. (per
§4, quality was not judged — the gate is stability-only.)

### 3d. fp4-confound resolution (DeepSeek)
The pin held on every call: **15/15 DeepSeek calls served by Baidu at fp8**,
`allow_fallbacks:false` + `quantizations:["fp8"]` guaranteeing fp8 by
construction (a non-fp8 route would have failed loud, not silently degraded).
So any behaviour here is intrinsic to **DeepSeek-V4-Pro-at-fp8**, not an fp4
artifact. At fp8 it **under-flags** (mean total = mean valid = 0.87 — it never
even exercises the `finding_valid=false` retraction path, it simply emits ~0–1
findings) and is the **least stable** arm (Jbar 0.80 exact = soft; its span
sets are so sparse and disjoint — 0↔2↔3 across identical input — that there is
nothing to soft-match). The 2026-06-28 rejection therefore **stands and is not
attributable to fp4**: DeepSeek is unfit on this stage at verified fp8 too, now
via under-flagging + maximal instability rather than the earlier
over-flagging + instability.

## 4. Phase 1 — NOT ENTERED

Zero candidates survived Phase 0. The binding brief: *"Failures exit here —
report, spend nothing further on them."* No Phase-1 candidate runs, no golden
generation, no judging — **$0 Phase-1 spend**, per protocol. The Phase-1
machinery (candidate-on-21-topics runner, Opus-4.8 golden arm, blind
Opus-4.8 judge rubric transcribed from the production prompts) was built and is
staged in `scratch/bias-eval/` for the next candidate that clears the gate, but
was deliberately not run.

## 5. Per-arm notes

- **Sonnet-5** — the only challenger flagging near the incumbent's level (3.53
  valid). Its instability is genuine, not sparsity-driven: on the Bolsonaro
  article it swings 0→1→1 confirmed (finds nothing on one cold run); on the
  Pope article 2→4→5. Closest of the three, but still churns more than Opus,
  and ~1.8× the cost / ~3.6× the latency.
- **GLM-5.2 @ xhigh** — a **regression on this stage**, consistent with
  2026-06-28 and opposite to its wins on writer/QA/editor. It under-flags
  (1.33 valid) and its category assignment churns most of any arm (Dbar 0.60).
  Reasoning at xhigh did not buy stability, mirroring the earlier
  "reasoning does not smooth it" finding.
- **DeepSeek V4 Pro @ xhigh fp8** — see §3d. Cheapest and slowest; a near-empty
  detector that still can't decide *which* near-nothing to flag.
- **Incumbent Opus 4.6** — sets the bar with Jbar 0.510 / soft 0.337 and a lean
  4.13 valid/article. Its own churn is real but the smallest, and much of it is
  cosmetic near-duplicate spans (soft J drops it to 0.337, a bigger relative
  fall than any challenger's).
- **Opus-4.8 @ effort:high (ceiling)** — only arm to clear the gate, but by
  under-flagging (1.67 valid) not by out-stabilizing: it ties Opus-4.6 (0.496 vs
  0.510) and its own soft-J of 0.264 sits just below the incumbent's 0.337 —
  again driven by the 0/0/0 (Bolsonaro) and 1/1/1 (Pope) articles. On US-Iran it
  holds 3/3/3 but reshuffles which 3 (Jexact 0.93), the same verdict-churn
  signature the failing arms show. Costs the most per call ($0.095) and spends
  9,786 tok/call (adaptive thinking) vs the incumbent's 6,072. Not a swap
  candidate; characterized here only as the stability ceiling.

## 6. Caveats

- **Gate is stability-only and necessary-not-sufficient.** It cannot reward a
  model for *better* marks, only reject one that is *less stable*. A hypothetical
  model that stably under-flags would clear it and be caught in Phase 1; here
  the point is moot (all three fail stability outright).
- **Exact-string Jaccard is conservative** (near-duplicate spans read as
  non-overlapping). Mitigated by reporting the substring-tolerant `soft`
  variant; the ranking is invariant.
- **n = 5 articles × 3 repeats.** Matches the 2026-06-28 gate's fixture scale;
  the gaps here (0.51 vs 0.69–0.80) are wide relative to that n, but this is a
  gate, not a fine-grained quality measurement.
- **Served-provider variability.** Sonnet-5 via Azure, incumbent via Anthropic
  direct — served endpoints are recorded per call in the raw logs but not
  controlled beyond the fp8 pins on the open-weight arms.
- **Cache-cold** = three independent HTTP calls, no cache-control markers; at
  temp 0.1 the incumbent is near-deterministic by design (that is the bar).

## 7. Reproduction

```bash
source .env
# Phase 0 grid (crash-safe; skips completed cells):
uv run python scratch/bias-eval/harness.py phase0par 6
uv run python scratch/bias-eval/score_phase0.py        # gate table + gate.json
```
- Frozen criterion + article manifest: `scratch/bias-eval/GATE-CRITERION.md`
- Deterministic checks (schema/verbatim/category/empty): `scratch/bias-eval/deterministic.py`
- Judge rubric (staged for Phase 1): `scratch/bias-eval/RUBRIC.md`
- Raw per-call records (75): `scratch/bias-eval/raw/*.json`
  (structured output, cost, tokens, latency, served provider, response id).
  Opus-4.8 ceiling grid: `uv run python scratch/bias-eval/harness.py phase0par 6 opus48`
- Consolidated detail: `scratch/bias-eval/phase0/GATE-DETAIL.txt`, `gate.json`

## 8. Cost ledger

| arm | calls | cost | total tokens |
|---|---|---|---|
| incumbent | 15 | $0.665 | 91,080 |
| opus48 (ceiling) | 15 | $1.420 | 146,800 |
| sonnet5 | 15 | $1.173 | 207,280 |
| glm | 15 | $0.438 | 171,810 |
| deepseek | 15 | $0.162 | 163,607 |
| **Phase 0 total** | **75** | **$3.86** | 780,577 |
| Phase 1 | 0 | $0.00 | — |
| **Eval total** | | **$3.86** | |

Well under the $10 cap. Judging free (would have been blind CC subagents).
Decision input, not a cutover. Production `bias_language` stays
`anthropic/claude-opus-4.6` (temp 0.1, reasoning none); no code changed.

## 9. Addendum — emission / self-retraction analysis (what the gate really measures)

The `finding_valid` boolean makes the stage's internal examine-then-judge step
*visible in the schema*: the model emits a candidate span, drafts its
`explanation`, and sets `finding_valid:false` to retract it in place (kept as an
audit trail, filtered by the renderer). Counting **emitted vs kept vs retracted**
across the 75 grid calls (15/arm) splits the field into two process families:

| arm | emitted | kept | self-retracted | retract % | process |
|---|---|---|---|---|---|
| incumbent Opus-4.6 (reasoning none) | 109 | 62 | 47 | 43% | **externalizes** retraction into the schema |
| opus48 Opus-4.8 (effort high) | 44 | 25 | 19 | 43% | **externalizes** retraction into the schema |
| sonnet5 (high) | 57 | 53 | 4 | 7% | pre-filters internally |
| glm (xhigh) | 23 | 20 | 3 | 13% | pre-filters internally |
| deepseek (xhigh) | 13 | 13 | 0 | 0% | pre-filters internally |

Two readings follow.

**1. The gate measures prompt-design fit as much as model-intrinsic stability.**
The bias prompt is a two-stage *emit-then-retract* design. The Opus family plays
it as written — propose a generous candidate set, then retract ~43% via
`finding_valid` — so their calibration *decision* is externalized where the gate
can watch it flip. The reasoning arms do the equivalent work *inside the
reasoning trace* and emit only near-survivors (retract 0–13%), so their
finding set is already post-filtered. Their high Jbar is therefore not "they
cannot decide" so much as "the little they surface churns," and it is not a
clean apples-to-apples read against the incumbent's externalized churn. The
valid-span instability metric is thus partly a signal of *whether a model uses
the schema's retraction mechanism the way the prompt intends* — a prompt-design
fit measure — layered on top of intrinsic determinism. (This does not rescue the
swap candidates: they still under-flag and, where they flag, churn. It reframes
*what* the gate proves.) Note Opus-4.8 keeps the same 43% retract rate as
Opus-4.6 but emits far fewer candidates (44 vs 109) — its "under-flagging" is
really under-*extraction* at stage one, then the same fractional retract.

**2. The real, robust finding is the incumbent's own 0.51 exact
repeat-consistency.** Independent of every challenger, the incumbent reconfirms a
~49%-different span set on identical cold input (Jbar_exact 0.510; soft 0.337).
On richer articles it is stark — Anthropic-IPO 4/6/6 kept (Jexact 0.81), US-Iran
5/5/4 kept-but-reshuffled (0.65); Opus-4.8 shows the same signature at lower
volume (US-Iran 3/3/3, Jexact 0.93). So the stage's confirmed-span verdict is
only ~half-stable run-to-run **even for the model we keep** — a property of the
single-call emit-then-retract design, not of any one model. That is the
actionable signal from this eval, and it is what a redesign must beat. Decided
direction + acceptance criterion: **`docs/BACKLOG-BIAS-STABILITY.md`**.
