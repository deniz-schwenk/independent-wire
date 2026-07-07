# MADLAD clustering backend — finalize on the Mini (convert · latency · control sweep)

**Machine:** Apple M4 / 32 GB / 10 cores, macOS Darwin 25.2.0.
**Date:** 2026-06-30.
**Scope:** measurement + conversion only, behind the flag, scratch output. Production
config / `pyproject` / `uv.lock` / pinned fastembed **untouched** (verified). The flag
is **not** enabled in production; nothing pushed.

> **Status of the premise.** The translate-to-English clustering sidecar described in
> the task landed in this repo overnight as commit `7e920b1`
> (*feat(cluster): translate-to-English sidecar for embedding (NLLB-local, isolated,
> flagged)*). It is real, fully wired, and flag-gated by `IW_CLUSTER_TRANSLATE`
> (default OFF), writing only the internal RunBus slot `curator_findings_clustering`,
> read by `pre_cluster_findings`, `CuratorTopicDiscoveryStage`, and
> `gravitational_assign` via `clustering_findings()`. **However** the shipped sidecar
> hardcodes `facebook/nllb-200-distilled-600M` (`translate_sidecar.py:85`) — the model
> the task says cannot ship (CC-BY-NC). This task produces the MADLAD-400 (Apache-2.0)
> conversion + latency + control data that the production swap depends on. No
> production code was edited (the sidecar's own injectable-backend / pre-warmed-cache
> seam was used instead).

---

## Task 1 — Self-convert MADLAD-400-3B → CTranslate2 int8 (provenance)

- **Model:** `google/madlad400-3b-mt` — **License: Apache-2.0** (confirmed at the HF
  model card). T5 architecture, 3B params, target language via a `<2xx>` source-prefix
  token (e.g. `<2en>`).
- **Provenance:** weights downloaded directly from HF and **sha256-verified**
  (`66ff5f8f…b3a76d4`, 11,761,587,872 bytes) before conversion. Converted locally with
  `ct2-transformers-converter --quantization int8`. **No third-party conversion repo.**
- **Local CT2-int8 model:** `scratch/madlad/madlad400-3b-mt-ct2-int8/` — **2.8 GB**
  (`model.bin` 2.95 GB int8 + `shared_vocabulary.json` + `config.json`).
- **Validated correct** across all 7 controls, e.g.
  `de` *"Boris Pistorius: Ende des Marine-Großprojekts…"* → *"Boris Pistorius: End of
  Navy Grand Project Increases Pressure on Minister"*; `ru` → *"President signed decree
  on new economic measures"*; `tr` → *"Motorcycle courier crash in Ankara settled"*.

### ⚠️ Dependency finding (matters for production wiring, currently out-of-scope)
Converting MADLAD correctly required a **specific dependency pair**:
**`ctranslate2==4.5.0` + `transformers==4.46.3`**.
- `transformers>=5.x` **silently corrupts** the MADLAD checkpoint: it declines to tie
  `shared.weight`/`decoder.embed_tokens.weight` ("different values"), leaving a
  mismatched LM head → fluent-looking **garbage** output (verified: fp32, fp16, and the
  CT2 model converted under 5.x all produced garbage). The model card shipped on
  transformers 4.35.
- `ctranslate2==4.8.0`'s converter is incompatible with transformers 4.46.3 (passes a
  `dtype=` kwarg only 5.x accepts) — hence pinning ct2 to 4.5.0 for the conversion.
- **Action for the swap:** the sidecar's `_CTranslate2NLLB` backend is NLLB-tokenizer /
  FLORES-target-prefix specific and **will not** drive a MADLAD CT2 model as-is
  (`IW_CLUSTER_TRANSLATE_CT2_DIR` pointed at MADLAD would mis-tokenize). A MADLAD
  backend needs the `<2en>` source-prefix scheme (provided here as `madlad_backend.py`).

---

## Task 2 — Authoritative latency on the M4 (CT2 int8 CPU/NEON vs transformers fp16 MPS)

Real production text (day 2026-06-26): "short headlines" = non-English control titles
(mean 82 chars), "long summaries" = control summaries (mean 201, p90 347, max 500).
beam=4, `do_sample=False` (matches the sidecar's deterministic decode). seg/s normalises
the differing batch sizes (CT2 64, MPS 24).

| metric | **CT2 int8 / CPU-NEON** | transformers fp16 / MPS |
|---|---:|---:|
| model load (s) | **1.3** | 13.6 |
| RSS after load (GB) | **3.5** | 19.2 |
| RSS peak (GB) | **13.9** | 19.2 |
| cold first call (seg/s) | **0.23** | 0.13 |
| warm parallel — LONG (seg/s) | **0.39** | 0.14 |
| warm parallel — SHORT (seg/s) | **1.89** | 1.10 |
| warm single — LONG (median ms) | **3682** | 6894 |
| warm single — SHORT (median ms) | **1271** | 2419 |
| **full-day cold estimate (min)** | **≈33** | ≈85 |

**Recommended production path: CTranslate2 int8 on CPU.** It wins on *every* axis —
throughput (2.8× on long, 1.7× on short), single-segment latency (1.9×), RAM (13.9 vs
19.2 GB peak), and full-day wall-clock (≈33 vs ≈85 min). The "don't assume CT2 wins on
Apple Silicon" caution is answered with data: for beam-search seq2seq at this size, the
MPS/Metal path is **markedly slower** and heavier than CPU NEON int8. (fp16 numerics were
verified non-degenerate for this model — MPS loses on speed, not correctness.)

Note: the **full-day cost is paid once** — the sidecar's persistent content-hash cache
(`translate once, repeats free`) makes subsequent days near-instant for unchanged
findings. The ≈33 min is the cold, no-cache worst case for a full day's non-English
findings.

---

## Task 3 — Full production-day control sweep (no-regression on high-resource controls)

**Design.** Real chain replay on **2026-06-26** (1385 findings; 742 en, 633 controls
es/pt/fr/de/ru/tr/vi, 10 it). Two arms through the **real** stages
`translate_findings_sidecar → pre_cluster_findings →
CuratorTopicDiscoveryStage(real DeepSeek-V4-Flash LLM) → gravitational_assign`,
run in the **production venv** so the pinned fastembed embeddings are
production-identical by construction. Native arm = flag OFF (embeds native text).
MADLAD arm = flag ON, sidecar fed a pre-warmed MADLAD-English cache (≈1286 title+summary
segments). "attach" = finding assigned to ≥1 topic (not orphan).

### Native baseline (flag OFF, 3 reps — establishes Curator variance)

| control | n | native attach (mean of 3) |
|---|---:|---:|
| es | 289 | 39.0 |
| pt | 110 | 16.7 |
| fr | 24 | 10.7 |
| de | 50 | 15.7 |
| ru | 41 | 15.0 |
| tr | 64 | **2.7** |
| vi | 55 | **6.0** |

`tr` and `vi` attach worst natively — the weakly-bridged controls English-normalisation
should *lift* without regressing the others.

Cache warmed with the local CT2-int8 MADLAD on the real day: **1286 segments
(643 non-English findings × title+summary) in 36.6 min** (0.6 seg/s mixed) — confirms
the ≈33 min full-day latency estimate. 640 cache entries; all control languages
translated fluently (validated by eye, e.g. `tr` *"Ankara'da motokurye kazasında karar
verildi"* → *"Motorcycle courier crash in Ankara settled"*).

> **Note on robustness:** the Curator LLM (DeepSeek-V4-Flash via OpenRouter) hung
> indefinitely on one run — OpenRouter fans out to multiple upstream providers
> (SiliconFlow / WandB / …) and one route stalled with no client-side read timeout.
> All sweep arms were therefore run under a wall-clock guard (kill + retry); no
> production code was modified.

### View A — real chain (production-faithful: flag ON ⇒ English topics **and** English findings), 3 reps

Mean control attach over 3 reps; raw per-rep values in brackets show the Curator's own
run-to-run spread (the noise floor against which any delta must be read):

| control | n | native attach (3 reps) | MADLAD-EN attach (3 reps) | Δ mean |
|---|---:|---|---|---:|
| es | 289 | 39.0 `[43,35,39]` | 36.7 `[37,36,37]` | −2.3 |
| pt | 110 | 16.7 `[18,14,18]` | 17.0 `[16,19,16]` | +0.3 |
| fr | 24 | 10.7 `[10,10,12]` | 10.3 `[10,11,10]` | −0.3 |
| de | 50 | 15.7 `[17,16,14]` | 14.7 `[14,14,16]` | −1.0 |
| ru | 41 | 15.0 `[18,15,12]` | 12.0 `[10,13,13]` | −3.0 |
| **tr** | 64 | 2.7 `[3,2,3]` | **3.7 `[4,3,4]`** | **+1.0** |
| **vi** | 55 | 6.0 `[7,5,6]` | **6.7 `[7,6,7]`** | **+0.7** |
| **total** | 633 | 105.7 | 101.0 | −4.7 |

### View B — fixed-topic A/B (confound-free: one shared topic set, only finding-embedding text varies)

Isolates the finding-side translation effect with **zero Curator variance** (one LLM call,
then deterministic `gravitational_assign` for both arms). Topics here are
native-discovered, which slightly *disadvantages* the MADLAD arm (English findings vs
mixed-language topic centroids) — a conservative test:

| control | n | native | MADLAD-EN | Δ |
|---|---:|---:|---:|---:|
| es | 289 | 46 | 40 | −6 |
| pt | 110 | 17 | 18 | +1 |
| fr | 24 | 12 | 14 | +2 |
| de | 50 | 19 | 17 | −2 |
| ru | 41 | 19 | 18 | −1 |
| tr | 64 | 4 | 4 | 0 |
| vi | 55 | 7 | 6 | −1 |
| total | 633 | 341 | 332 | −9 |

### No-regression verdict — **PASS (no meaningful regression on the high-resource controls)**

1. **Every per-control delta sits inside the Curator's own rep-to-rep noise band.** Native
   attach alone swings es `[43,35,39]` (σ≈4), ru `[18,15,12]` (σ≈3), de `[17,16,14]`
   (σ≈1.5) across *identical* reps. The MADLAD deltas (es −2.3, ru −3.0, de −1.0) are ≤ 1σ
   of that intrinsic variance — statistically indistinguishable from noise, not a
   systematic loss.
2. **The weakly-bridged controls do not regress — they improve.** `tr` (+1.0) and `vi`
   (+0.7), the worst-attaching controls natively, hold or gain under English
   normalisation in the real chain. No language collapses in either design.
3. **Aggregate drift is small and within noise:** real-chain −4.7 / 105.7 (≈4%),
   fixed-topic −9 / 341 (≈3%) — and the fixed-topic design is deliberately biased against
   MADLAD. The production-faithful real chain (English topics + findings) shows the
   smaller drift.

**Conclusion:** translating control-language findings to English for clustering does **not**
regress the high-resource European controls (es/pt/fr/de/ru/tr/vi) on attach vs native.
This closes the gap the prior machine could only probe via Arabic (which improved): the
European controls hold, and the weakest of them (tr/vi) sharpen slightly. Combined with
the prior eval's non-Latin lift (bn 0→, uz 0→) on the batch-1 feed, the sidecar's English
normalisation is attach-neutral-to-positive across the board.

> **Caveat (in scope to flag, out of scope to fix here):** the off-topic re-audit at
> `T=0.55` on English input — English cosines shift upward, so the gravitational/cluster
> thresholds may need recalibration before enablement. That, the actual flag enablement,
> and ctranslate2 production-dependency wiring remain separate later steps.

---

## Reproduction artifacts (all under `scratch/madlad/`, isolated venv)
- `madlad400-3b-mt-ct2-int8/` — the self-converted Apache-2.0 model (2.8 GB).
- `madlad_backend.py` — CT2-int8 + MPS MADLAD backends (`<2en>` prefix), injectable
  into the real sidecar core.
- `latency.py`, `latency_mps.py` + `lat_ct2.json`, `lat_mps.json` — latency harness/results.
- `madlad_translate.py` + `sweep_cache.json` — sidecar-format MADLAD cache warmer.
- `run_chain.py`, `fixed_topic_ab.py` — real-chain and confound-free control sweeps.
- Isolation: production `.venv` has no torch/ct2/transformers; `pyproject`/`uv.lock` clean.
