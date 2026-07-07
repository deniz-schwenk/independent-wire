# WP-OLLAMA-2 — translate_de reasoning probe (think:false vs think:"max")

**Date:** 2026-07-05 · Read-only on production; writes only under
`scratch/translate-max-probe/`; no git operations; outside the 06:00 window; no
heavy local job running.

## Recommendation: **KEEP `think:false`.**
At the top reasoning tier, deepseek-v4-pro:cloud translation is **slightly worse**
on every quality axis, draws **more error flags** (embellishment/additions), and
costs **~4–5× wall-clock**. The mechanical guarantees survive, but there is no
quality upside to pay the latency for. Textbook null result — mildly negative.

---

## 1. Step-0 — accepted `think` tier for deepseek-v4-pro:cloud (primary evidence)
Proven on the **native** `/api/chat` validator (its own rejection message is the
evidence; the `/v1` shim silently swallows invalid values and was NOT used to
validate):
```
think:"xhigh" → 400 "invalid think value: \"xhigh\" (must be \"high\",\"medium\",\"low\",\"max\",true,or false)"
think:"max"   → 200, 463-char reasoning trace, content "die Katze", eval 135
```
**Accepted set: `{low, medium, high, max, true, false}`; `xhigh` rejected.** `max`
is accepted and engages heavy reasoning → used as the candidate tier (no
substitution needed).

### num_predict × thinking on `/api/generate` (measured, not assumed)
Production uses the native `/api/generate` with `think:False, num_predict=32000`.
On a real 8-item block at `think:"max"`:

| num_predict | num_ctx | done_reason | eval_count | thinking chars |
|---|---|---|---|---|
| 32000 | 39187 | **stop** | 15635 | 48128 |
| 64000 | 71187 | **stop** | 14580 | 41134 |

`num_predict` caps **total** generated tokens (thinking + answer). Even the
largest core blocks (up to ~249K thinking chars) returned `done=stop` — no
truncation. **Candidate budget: `num_predict=64000`** (2× production, measured
headroom), `num_ctx = input + num_predict + 4096`.

## 2. Mechanical gate — all candidate TPs (the production guard, reused verbatim)

| TP | items | clean | empty | degenerate | src-token preserved | truncated blocks | identical-to-source | verdict |
|---|---|---|---|---|---|---|---|---|
| tp-2026-07-04-001 | 151 | 151 | 0 | 0 | **100.0%** | 0 | 0 | PASS |
| tp-2026-07-04-002 | 139 | 139 | 0 | 0 | **100.0%** | 0 | 0 | PASS |
| tp-2026-07-04-003 | 124 | 124 | 0 | 0 | **100.0%** | 0 | 0 | PASS |
| tp-2026-07-05-001 | 152 | 152 | 0 | 0 | **100.0%** | 0 | 0 | PASS |
| tp-2026-07-05-002 | 178 | 178 | 0 | 0 | **100.0%** | 0 | 0 | PASS |
| tp-2026-07-05-003 | 154 | 154 | 0 | 0 | **100.0%** | 0 | 1 | PASS |

All 6 pass. src-token preservation 100%, zero empty, zero degenerate, zero
truncation. (07-05-003 has 1 item rendered identical to its English source — a
proper-noun-only segment; baseline had 0. Not a gate failure.) The
mechanical guarantees are **not** broken by reasoning.

## 3. Quality (blind, 2 Opus-4.8 subagent judges/TP, 30 seeded segments/TP)

Per-TP means (baseline → candidate), fidelity / terminology / naturalness, and
segment-level W/T/L (candidate vs baseline):

| TP | baseline | candidate | seg W/T/L |
|---|---|---|---|
| tp-2026-07-04-001 | 4.95 / 4.93 / 4.97 | 4.92 / 4.88 / 4.83 | 3 / 19 / 8 |
| tp-2026-07-04-002 | 4.92 / 4.98 / 4.85 | 5.00 / 4.97 / 4.92 | 6 / 21 / 3 |
| tp-2026-07-04-003 | 4.98 / 5.00 / 4.98 | 5.00 / 4.95 / 4.93 | 2 / 25 / 3 |
| tp-2026-07-05-001 | 4.98 / 4.92 / 4.92 | 4.97 / 4.95 / 4.88 | 4 / 21 / 5 |
| tp-2026-07-05-002 | 4.92 / 4.97 / 4.82 | 4.83 / 4.90 / 4.47 | 3 / 21 / 6 |
| tp-2026-07-05-003 | 5.00 / 5.00 / 4.82 | 4.92 / 4.93 / 4.95 | 5 / 21 / 4 |
| **overall** | **4.958 / 4.967 / 4.892** | **4.939 / 4.930 / 4.830** | **23 / 128 / 29** |

Candidate is **lower on all three axes** and takes **more segment losses than
wins** (29 vs 23; 71% ties). Error-flag matrix (counts over 180 segments × 2 judges):

| flag | baseline | candidate |
|---|---|---|
| mistranslation | 3 | 3 |
| omission | 4 | **0** |
| addition | 2 | **6** |
| wrong_language | 3 | **11** |

The candidate's extra flags are dominated by **additions** and **wrong_language**.
The additions are `think:max` **embellishing** — e.g. rendering the source's
"Kremlin aide Ushakov" as *"der außenpolitische Berater des Kremls"* (adding a
"foreign-policy" specificity the source never states). Reasoning invites the model
to *improve* rather than faithfully render — the precise mechanism by which
thinking hurts a fidelity-bound task. (It does clear more omissions — 0 vs 4 — but
trades them for more additions and language slips; net error count 20 vs 12.)

## 4. Latency projection for daily operation
Wall-clock, both arms measured under the SAME 3-TP-concurrent pattern production uses:

| | per-TP range | daily wall (3 TPs concurrent ≈ slowest) |
|---|---|---|
| baseline (think:false) | 318–484 s | **~8 min** (≈490 s, matches current chain) |
| candidate (think:max) | 1268–2277 s | **~28–38 min** (07-05 wave 1687 s / 07-04 wave 2277 s) |

**~4–5× slower — daily German translation would rise from ~8 min to ~30 min.**
Reasoning was genuinely engaged (thinking traces 62K–249K chars/block).

## 5. Recommendation — **KEEP `think:false`**
One-line rationale: `think:max` buys a ~4–5× latency increase for a *mild quality
regression* (lower on all three axes, 29 losses vs 23 wins, ~1.7× the error flags —
mostly reasoning-driven embellishment), while the mechanical guarantees are
unchanged. There is no case to adopt it. (Matches the backlog's honest prior:
translation rarely benefits from reasoning.)

---

## Assertions & acceptance
- **6 TPs, 30 seeded segments each (seed = date#tp_id), 12 subagent verdicts.** No
  silent shrinkage; all 6 candidate TPs mechanically gated (§2).
- **Zero API judge calls** — 12 blind Opus-4.8 subagents; blindness verified (no
  verdict references `anon_keys/`, grep-clean).
- **Total paid API spend $0.0000** (in-code cap $2.00, untouched; ollama flat-rate,
  no billed fallback provider used).
- **Baseline provenance quoted**: every baseline TP `provider="ollama-cloud"`,
  `fallbacks=[]` (from the de.json + `de/logs/*.log.json`); e.g. `tp-2026-07-05-002:
  {"provider":"ollama-cloud","fallbacks":[]}`.

### Artifacts (for re-verification) under `scratch/translate-max-probe/`
`harness_translate.py` (candidate generator + measure mode) · `candidate/*.de.json`
(6 candidate TPs + reasoning evidence) · `packets/*.json` (blind 30-seg bundles) ·
`anon_keys/*.json` (post-hoc keys) · `verdicts/*__j{0,1}.json` (12) ·
`mechanical_census.json` · `aggregate_translate.json` · `JUDGE-TRANSLATE.md`.
