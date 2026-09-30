# EVAL-DSV41-PLANNER-MEDHIGH — method

Addendum to Batch 1 (`../../reports/METHOD.md`). Everything not listed here is
Batch 1's method, unchanged.

## 1. Level acceptance (done before any batch call)

Evidence: `level_probe.py` → `level_probe.json` (2026-09-24 ~10:00 UTC), plus the
per-call `api_calls[].sent_reasoning` / `reasoning_tokens` in every candidate file.

- **Enum validation exists on this route.** `reasoning.effort: "bogus_level"` →
  **HTTP 400** *"reasoning.effort: Invalid option: expected one of
  "max"|"xhigh"|"high"|"medium"|"low"|"minimal""*. So acceptance of a name is
  meaningful, not a pass-through.
- **`medium` → 200 ×3, `high` → 200 ×3**, every call served `provider: DeepSeek`.
  The endpoint catalogue lists `reasoning` and `reasoning_effort` in the vendor
  endpoint's `supported_parameters`.
- **What was actually sent** (instrumented client wrapper, `harness.py::instrument`):
  `{"effort": "medium"}` / `{"effort": "high"}`, provider block
  `{"order": ["deepseek"], "allow_fallbacks": false}`, temperature OMITTED,
  max_tokens 24000 — on all 18 calls (`logs/calls.jsonl`).
- **Distinctness, measured on the real planner inputs** (the toy probe did not
  separate the levels — 380–883 reasoning tokens across all three):
  F_high spent more reasoning tokens than F_med on **7 of 9** identical inputs;
  medians **1 862 (medium) vs 2 758 (high)**. Median completion tokens:
  low 1 937 (derived, see `aggregate.json` `_note`), medium 2 420, high 3 394.
  `medium` is therefore **not** behaving as an alias of `high` on this route —
  unlike channel C, where LEVEL-AUDIT measured `medium ≡ high`
  (docs/evals/INDEX.md, 2026-09-05). What OpenRouter forwards to DeepSeek for
  `medium` is not observable from here; the measured behaviour is the evidence.
- Standing convention "documented level names only": the vendor documents
  low/high/max. `medium` here is an OpenRouter-enum value with a recorded
  characterization (above) — permissible for an eval arm, and any production use
  would need the same record.

## 2. Arms

| arm | model | route | reasoning | temp | max_tokens | structured | source |
|---|---|---|---|---|---|---|---|
| C | deepseek-v4-pro | channel C | low | omitted | 24000 | json_object | Batch-1 files, NOT regenerated (09-06 = Batch-1's reconstructed `Cstar`) |
| F_low | deepseek/deepseek-v4.1-flash | OpenRouter + pin | low | omitted | 24000 | json_object | Batch 1 (reference; its own session) |
| **F_med** | deepseek/deepseek-v4.1-flash | OpenRouter + pin | **medium** | omitted | 24000 | json_object | this batch |
| **F_high** | deepseek/deepseek-v4.1-flash | OpenRouter + pin | **high** | omitted | 24000 | json_object | this batch |

Bare `Agent`, never the fallback ladder. Inputs: Batch-1's `frozen/` (read-only),
re-verified byte-identical to production before any call
(`logs/frozen_vs_prod.txt`: 3 × 101 files, 0 diffs). All 18 calls ran
2026-09-24 10:01–10:05 UTC — inside the vendor's weekday off-peak window
(`level_probe.json` → `endpoint_catalog[0].pricing.overrides`).

## 3. Judging

- Rubric: Batch 1's `rubrics/planner.md` (= T5a's), verbatim.
- One fresh session per case containing **C, F_med, F_high** (three outputs);
  protocol = Batch 1's text with exactly two edits forced by three outputs
  ("every plan" for "both plans"; a 3-way ranking). `build_judging.py` imports
  Batch 1's PROTOCOL and asserts the edit.
- Blind: `OUT-xxxxxx` = sha256(seed|case|arm), seed
  `dsv41-planner-medhigh-2026-09-24`; per-case seeded shuffle; keymap one level
  above the case dirs. Judges were instructed to read only their case dir and
  (judge 2) never the other verdict.
- Judges: spawned subagents on the harness's `opus` model — never API calls.
  **Judging cost $0.00.** 9 judge-1 verdicts; judge 2 on every case where judge 1
  raised any charge (6 cases) — `confirm_charges.py` reports
  `needs_second_judge: []`.
- Honest-Detector: Batch 1's deterministic `overlap()` imported unchanged.

## 4. Aggregation — and a correction to Batch 1's labelling

`aggregate.py` first **reproduces Batch 1 from Batch 1's own verdicts**
(`self_check`) before computing anything new. It found that Batch 1's headline
"all cases, both judges" (−0.481, CI [−1.042, +0.079]) is not a mean over judges:
`../../aggregate.py` assigns `per[arm][case] = m` inside the verdict-file loop,
so on double-judged cases **judge 2 silently overwrote judge 1**. The published
number reproduces exactly under that "last-writer" rule (−0.4815,
[−1.0415, +0.0786]); the true mean over both judges is **−0.4907,
[−1.0174, +0.0360]**. Batch 1's verdict is unaffected (both fail the −0.10 bar;
both CIs include zero). This addendum reports the TRUE mean as primary, and
last-writer + judge-1-only alongside for exact comparability.

Gating = paired Δ (arm − C) where both were scored in the SAME session; bar =
CI95 lower bound > −0.10 (Batch 1 / T5b). F_low enters the table from its own
session with its own paired Δ; absolute scores across sessions are reference
only (INDEX convention, 2026-09-02).

## 5. Hygiene

- 18 calls, 0 errors, 0 non-DeepSeek serves, 0 wrong-model serves, 1 API call
  each (no retries). $0.0625 of the $10 cap (+ $0.0037 level probe).
- Production state: `logs/prod_state_manifest.PRE.txt` == `.POST.txt` (351
  files), and PRE == Batch 1's POST (unchanged since 2026-09-12).
- Batch-1 artifacts: no file outside `medhigh/` newer than this batch's PRE
  manifest. Batch-1 modules were imported only with `PYTHONDONTWRITEBYTECODE=1`.
- `git status` clean on `main` before and after; no commits.
