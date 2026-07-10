# Evaluation evidence archive

Tracked, citable copies of the empirical evidence behind Independent Wire's
open-weight-model core claim: blind model-eval waves, search backtests, and
quantization / translation / fetch probes. Rescued from untracked `scratch/`
(TASK-EVIDENCE-RESCUE, 2026-07-07).

These are the **raw scoring outputs, rubrics, judge tasks, and result reports**
that back the narrative digests already tracked at `docs/*-MODEL-EVAL-*.md` and
`docs/*-EVAL-*.md`. Copy-only: the originals remain in `scratch/` (each file's
original path is listed below). Nothing here was rewritten or summarized.

**Content policy applied on copy:** no API keys / auth headers (scanned clean).
No full source-article texts — only scores, rubrics, judge prompts, and result
prose (longest embedded string across all copied JSON is 583 chars, i.e. a judge
rationale, not an article). Files that embed source-derived fulltext or raw
per-topic model I/O were **excluded** — see "Excluded" at the bottom.

Each group lead line: *what it evaluated → decision it supported (date)*.
Each artifact line: *filename — role · original path*.

---

## registry-search-backtest — registry vs Sonar (2-arm) then + Ollama (3-arm) web-search backends: host breadth, language coverage, datedness, overlap, cost → **flip default search provider Sonar → Ollama** (QUALIFIED GO, cost-driven interim; registry = $0 endgame) (2026-07-04 → 07-06)
- `BACKTEST-3ARM-REPORT.md` — 3-arm registry/Sonar/Ollama final report + GO decision · orig `scratch/registry-shadow/BACKTEST-3ARM-REPORT.md`
- `BACKTEST-REPORT.md` — 2-arm registry-vs-Sonar (A3a) backtest report · orig `scratch/registry-shadow/BACKTEST-REPORT.md`
- `LEDGER.md` — per-run cost / query ledger · orig `scratch/registry-shadow/LEDGER.md`

## editor-model-eval — 5-arm blind editor eval (GLM-5.2, DeepSeek-V4, Sonnet-5 vs Opus-4.6 incumbent, +Opus-4.8 golden), 21 days → **editor → GLM-5.2 @ xhigh (+ Sonnet-5 fallback)** (2026-07-04)
- `ARCHITECT-DIGEST.md` — architect blind digest · orig `scratch/editor-eval/ARCHITECT-DIGEST.md`
- `ARCHITECT-VERDICTS.md` — architect per-day verdicts · orig `scratch/editor-eval/ARCHITECT-VERDICTS.md`
- `JUDGE-TASK.md` — blind judge task/prompt · orig `scratch/editor-eval/JUDGE-TASK.md`
- `RUBRIC.md` — scoring rubric · orig `scratch/editor-eval/RUBRIC.md`
- `panel_results.json` — panel win / agreement tallies · orig `scratch/editor-eval/panel_results.json`
- `deterministic_scores.json` — deterministic per-day scores (overlap / jaccard) · orig `scratch/editor-eval/deterministic_scores.json`
- `shadow_run_summary.json` — shadow-run summary + spend · orig `scratch/editor-eval/shadow_run_summary.json`

## writer-model-eval — 4-arm blind writer eval (21 topics; GLM-5.2 vs Opus-4.6 vs Sonnet-5 vs Opus-4.8 golden) → **writer → GLM-5.2 @ xhigh (+ Opus-4.6 fallback)** (2026-07-03)
- `JUDGE-TASK.md` — blind judge task/prompt · orig `scratch/writer-shadow/JUDGE-TASK.md`
- `RUBRIC.md` — scoring rubric · orig `scratch/writer-shadow/RUBRIC.md`
- `deterministic_scores.json` — per-topic deterministic scores · orig `scratch/writer-shadow/deterministic_scores.json`
- `aggregate_summary.json` — aggregate verdicts / pairwise + judge rationales · orig `scratch/writer-shadow/aggregate_summary.json`

## perspective-model-eval — 5-arm perspective eval (21 topics) → **perspective → Sonnet-5 (+ Opus-4.6 fallback)** (2026-07-04)
- `JUDGE-TASK.md` — blind judge task/prompt · orig `scratch/perspective-eval/JUDGE-TASK.md`
- `RUBRIC.md` — scoring rubric · orig `scratch/perspective-eval/RUBRIC.md`
- `deterministic_scores.json` — per-topic deterministic scores · orig `scratch/perspective-eval/deterministic_scores.json`
- `aggregate_summary.json` — aggregate + pairwise + per-topic correctness · orig `scratch/perspective-eval/aggregate_summary.json`

## qa-model-eval — QA GLM-5.2 shadow + v2 golden re-judge (63 topics) → **qa_analyze → GLM-5.2 @ xhigh (+ Sonnet-5 fallback)** (2026-07-03)
- `BACKFILL-REPORT.md` — GLM shadow backfill + v2 golden re-judge report · orig `scratch/qa-shadow/BACKFILL-REPORT.md`
- `README.md` — eval method readme · orig `scratch/qa-shadow/README.md`
- `report_summary.json` — collection / shadow status summary · orig `scratch/qa-shadow/report_summary.json`
- `aggregate_summary.json` — correctness means + verdict tallies · orig `scratch/qa-shadow/aggregate_summary.json`

## bias-model-eval — bias_language re-eval (GLM-5.2 / DeepSeek-V4-Pro / Sonnet-5 vs Opus-4.6 incumbent, +Opus-4.8) + stability gates for the split/dedup/tier/dual-judge/third-extractor progression → **KEEP Opus judge; land extract → union → judge composite** (all swap candidates failed the stability gate) (2026-07-04 → 07-05)
- `RUBRIC.md` — scoring rubric · orig `scratch/bias-eval/RUBRIC.md`
- `GATE-CRITERION.md` — stability (flip-distance) gate criterion · orig `scratch/bias-eval/GATE-CRITERION.md`
- `COMPOSITE-STABILITY-RESULT.md` — composite-split stability result · orig `scratch/bias-eval/COMPOSITE-STABILITY-RESULT.md`
- `DEDUP-FIX-STABILITY-RESULT.md` — dedup-fix stability result · orig `scratch/bias-eval/DEDUP-FIX-STABILITY-RESULT.md`
- `THIRD-EXTRACTOR-GATE-RESULT.md` — third-extractor gate result · orig `scratch/bias-eval/THIRD-EXTRACTOR-GATE-RESULT.md`
- `TIER-DUAL-JUDGE-GATE-V3-RESULT.md` — dual-judge tier gate (v3) result · orig `scratch/bias-eval/TIER-DUAL-JUDGE-GATE-V3-RESULT.md`
- `TIER-MAPPING-GATE-V2-RESULT.md` — tier-mapping gate (v2) result · orig `scratch/bias-eval/TIER-MAPPING-GATE-V2-RESULT.md`
- `gate.json` — per-arm gate scores (incumbent/glm/deepseek/sonnet5/opus48) · orig `scratch/bias-eval/gate.json`

## ds-xhigh-probe — DeepSeek-V4-Pro at reasoning xhigh vs production none on phase1 / bias / consolidator → **KEEP reasoning=none on all three** (2026-07-05)
- `REPORT.md` — xhigh-vs-none probe report + verdict · orig `scratch/ds-xhigh-probe/REPORT.md`
- `JUDGE-PHASE1.md` — phase-1 judge task · orig `scratch/ds-xhigh-probe/JUDGE-PHASE1.md`
- `JUDGE-BIAS.md` — bias judge task · orig `scratch/ds-xhigh-probe/JUDGE-BIAS.md`
- `JUDGE-CONSOLIDATOR.md` — consolidator judge task · orig `scratch/ds-xhigh-probe/JUDGE-CONSOLIDATOR.md`
- `aggregate_phase1.json` — phase-1 aggregate scores · orig `scratch/ds-xhigh-probe/aggregate_phase1.json`
- `aggregate_bias.json` — bias aggregate scores · orig `scratch/ds-xhigh-probe/aggregate_bias.json`
- `aggregate_consolidator.json` — consolidator aggregate scores · orig `scratch/ds-xhigh-probe/aggregate_consolidator.json`

## ollama-quant-probe — ollama-cloud vs OpenRouter Baidu-fp8 (GLM-5.2 & DeepSeek-V4-Pro) quant/quality parity, + `think:max` re-run → **parity → gate PROCEED (production xhigh → ollama think:max)** (2026-07-05)
- `REPORT.md` — run-1 quant/quality parity report · orig `scratch/ollama-probe/REPORT.md`
- `REPORT-MAX.md` — run-1b GLM `think:max` re-run report · orig `scratch/ollama-probe/REPORT-MAX.md`
- `JUDGE-PHASE2.md` — phase-2 judge task · orig `scratch/ollama-probe/JUDGE-PHASE2.md`
- `JUDGE-CONSOLIDATOR.md` — consolidator judge task · orig `scratch/ollama-probe/JUDGE-CONSOLIDATOR.md`
- `aggregate.json` — run-1 aggregate scores (glm / deepseek) · orig `scratch/ollama-probe/aggregate.json`
- `aggregate_max.json` — run-1b aggregate scores + latency · orig `scratch/ollama-probe/aggregate_max.json`
- `deterministic_glm.json` — per-candidate deterministic scores (GLM) · orig `scratch/ollama-probe/deterministic_glm.json`
- `deterministic_deepseek.json` — per-candidate deterministic scores (DeepSeek) · orig `scratch/ollama-probe/deterministic_deepseek.json`
- `deterministic_glmmax.json` — per-candidate deterministic scores (GLM think:max) · orig `scratch/ollama-probe/deterministic_glmmax.json`

## translation-max-probe — German `translate_de` at `think:max` vs `think:false` → **KEEP think:false** (worse on all axes + embellishes + slower) (2026-07-05)
- `REPORT.md` — think:max vs think:false report + verdict · orig `scratch/translate-max-probe/REPORT.md`
- `JUDGE-TRANSLATE.md` — translation judge task · orig `scratch/translate-max-probe/JUDGE-TRANSLATE.md`
- `aggregate_translate.json` — per-TP + overall scores · orig `scratch/translate-max-probe/aggregate_translate.json`

## fetch-quality-diag — ollama `web_fetch` vs direct HTTP + trafilatura for hydration fulltext (30 URLs) → **KEEP trafilatura** (pubdate 93% vs 57%, 1.8× faster) (2026-07-06)
- `REPORT.md` — head-to-head diagnostic report · orig `scratch/fetch-diag/REPORT.md` (`raw.json` excluded — embeds fetched article fulltext)

## madlad-clustering-shadow — MADLAD-400 CT2-int8 clustering-backend shadow + finalize (non-Latin embedding bridge) → **lift validated live; 5 enablement blockers still gate the flag (stays OFF)** (2026-07-05)
- `MADLAD-FINALIZE-REPORT.md` — backend finalize report (rebuild + backfill lift) · orig `scratch/MADLAD-FINALIZE-REPORT.md`
- `MADLAD-SHADOW-STABILITY.md` — multi-day shadow stability report · orig `scratch/MADLAD-SHADOW-STABILITY.md`

## madlad-floor-gate — do the clustering floors (0.55 assign / 0.30 pre-cluster) stay safe under MADLAD translation for the non-Latin languages never in the May calibration (ar/zh/ja/th/bn/ne)? + Latin native baseline → **GO ×6 (zh/ja GO\* single-day); measurement only, no flag flipped** (2026-07-10)
> Authored gate (not a scratch copy): the harness is git-tracked at `tools/madlad_floor_eval/`; raw distributions / translation maps / per-batch labels stay in gitignored `scratch/floor-eval/`.
- `REPORT.md` — full report: P0 calibration reproduction (13/13 PASS), P1 blind labelset, P2 per-language GO/NO-GO with raw distributions, P3 Latin native baseline
- `labels/{ar,zh,ja,th,bn,ne}.json` — 780 blind on/off-topic labels (130/lang), Opus-4.8 spawned-subagent judges, native-text-only (circularity guard)
- `labels/architect_review_sample.json` + `labels/architect_blind_review.json` — 79-pair 10 % stratified blind re-review by the Architect subagent → 79/79 agreement, κ=1.0, PASS
- `labels/_meta.json` — per-language counts, seed 20260707, method

---

## Excluded (with reason)
- **Per-topic raw model I/O** across every eval dir (`scratch/*/YYYY-MM-DD/**` — `input.json`, `incumbent.json`, `golden.json`, `glm_output.json`, `PROMPT.md`, judge `packet.json`): raw eval inputs/outputs, not reports or scores; embed source-derived content (curator topics, dossiers, generated articles). Out of scope + copyright-adjacent.
- **`scratch/fetch-diag/raw.json`**: embeds full fetched article text (trafilatura + ollama extractions of live news) — copyright. The aggregated `REPORT.md` (metrics only) was copied instead.
- **`scratch/p2-eval/raw/*.json`** (hydration Phase-2 eval): raw per-run candidate outputs, embed source summaries. No standalone report/aggregate exists in scratch; the Phase-2 eval digest lives on the unpushed branch `eval/hydration-p2-model-eval` (`d1f265d`) and is referenced by `scripts/run.py` as `docs/HYDRATION-P2-MODEL-EVAL-2026-07.md` — track that separately when the branch lands.
- **`scratch/registry-seed/`** (`_mined.json` 520 KB, `candidates.json`, `long_tail.json`, `REPORT.md`): feed-mining data acquisition, not a model evaluation; large files embed scraped feed content + URLs.
- **`scratch/MADLAD-INTEGRATION-REQUIREMENTS.md`**: a requirements spec, not evaluation evidence.
- **Eval tooling scripts** (`score.py`, `report.py`, `backtest.py`, `backtest_3arm.py`, `score_phase0.py`, …): the generators, not the evidence; they remain in `scratch/`.
- **Smoke / verification dirs** (`scratch/search-flip`, `loud-log-smoke`, `p2-swap-smoke`, `batch2-verify`, `branch-landing`): not evaluations.
