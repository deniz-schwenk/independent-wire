# Embedding-Model Eval — paraphrase-multilingual-MiniLM-L12-v2 vs multilingual-e5-small

Per TASK-EMBEDDING-MODEL-EVAL. Isolated harness — production code paths (`src/stages/coherence.py`, `pyproject.toml`) untouched. Model B registered via `fastembed.add_custom_model` inside `scripts/eval_embedding_models.py` for the duration of the eval only.

## 1. Setup

| | Model A — current production | Model B — candidate |
|---|---|---|
| **Model ID** | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `intfloat/multilingual-e5-small` |
| **Architecture** | 12-layer MiniLM, 384-dim | 12-layer MiniLM, 384-dim (initialised from same arch, further trained two-stage contrastive) |
| **Languages** | ~50 | ~100 |
| **License** | Apache-2.0 | MIT |
| **On-disk footprint** (fp32 ONNX in fastembed cache) | 240 MB | 465 MB |
| **Pooling** | MEAN (fastembed>=0.6 default) | MEAN |
| **Output normalisation** | applied at scoring time | applied by fastembed wrapper |
| **Text-prefix convention** | none | `query: ` on both cluster and finding (symmetric STS — e5 model card recommendation) |
| **Loaded via** | fastembed built-in registry | `TextEmbedding.add_custom_model(...)` inside the eval script |

**fastembed version pinned**: 0.8.0 (matches production pin in `pyproject.toml`). ONNX inference single-threaded → bit-deterministic per the production-coherence-stage guarantee.

**Dataset.** Two daily curator outputs:

| Date | State path | Findings | Clusters | Labelled clusters |
|---|---|---:|---:|---|
| 2026-05-11 (V1 baseline) | `output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json` | 1201 | 14 | 0 (Iran, n=50), 1 (Hantavirus, n=8), 3 (Russia-Ukraine, n=31) |
| 2026-05-13 (partial) | `output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json` | 1405 | 16 | 1 (Iran, n=50), 0 (Trump-Xi, n=45), 11 (Sudan, n=40) |

**Total ground-truth labels in scope: 224** (56 on-topic, 168 off-topic). Labels under `docs/coherence-filter/manual-labels/2026-05-{11,13}/`.

**Text concatenation.** Both models receive identical input: `title + " " + summary + " " + description` for findings (description is empty in the current finding schema, so this collapses to `title + summary` in practice); `title + " " + summary` for cluster headlines. The only model-specific quirk: Model B receives the `query: ` prefix on both texts, per e5 documentation for symmetric semantic similarity. Model A receives no prefix.

**Per-finding scores persisted** at `output/eval/embedding-2026-05-13/scores/{model}/{date}/cluster-{N}.json` (gitignored via `output/`). Re-running the harness produces bit-identical scores; aggregate metrics file at `output/eval/embedding-2026-05-13/metrics.json`.

## 2. Per-cluster comparison

F1 at the F1-optimal threshold per cluster (threshold grid 0.05–0.95 step 0.05); ROC AUC by Mann-Whitney U.

| Date | Cluster | Headline (truncated) | n | A F1 | B F1 | Δ F1 (B−A) | A AUC | B AUC | Δ AUC | Language mix |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-05-11 | 0 | Stalled US-Iran peace negotiations | 50 | 0.400 | 0.500 | **+0.100** | 0.783 | 0.880 | +0.097 | en, de, es, ru |
| 2026-05-11 | 1 | Global hantavirus outbreak MV Hondius | 8 | 0.857 | 0.857 | 0.000 | 0.800 | 0.933 | +0.133 | en, zh |
| 2026-05-11 | 3 | Russia-Ukraine Victory Day ceasefire | 31 | 0.971 | 0.708 | **−0.263** | 0.996 | 0.798 | −0.198 | en, uk-translated |
| 2026-05-13 | 1 | US-Israel War with Iran | 50 | 0.811 | 0.766 | −0.045 | 0.911 | 0.936 | +0.024 | en (29), es (5), de (5), ru (6), it (2), pt (1), vi (1), zh (1) |
| 2026-05-13 | 0 | Trump-Xi Summit in Beijing | 45 | 1.000 | 0.870 | **−0.130** | 1.000 | 0.995 | −0.005 | en (28), es (7), de (4), ru (3), pt (3) |
| 2026-05-13 | 11 | Unrest in Sudan | 40 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 | en (30), de (4), es (2), pt (3) |

Language mixes are read from the labelled-finding subset, not the full cluster. The 2026-05-11 hantavirus cluster is small and language-poor by accident of sampling.

## 3. Aggregate comparison

| Metric | Model A | Model B | Δ (B−A) |
|---|---:|---:|---:|
| Macro-F1 averaged across dates (means of per-cluster best-F1 per date) | **0.840** | 0.784 | **−0.056** |
| Mean ROC AUC averaged across dates | 0.915 | 0.924 | +0.009 |
| Pooled F1 (all 224 findings, one shared optimal threshold) | **0.855** | 0.743 | **−0.112** |
| Pooled ROC AUC | 0.944 | 0.949 | +0.005 |
| F1-optimal threshold pooled | 0.35 | **0.85** | — |

Per-date macro:
- 2026-05-11 (89 findings, three clusters): A=0.743 macro-F1, B=0.689 macro-F1.
- 2026-05-13 (135 findings, three clusters): A=0.937 macro-F1, B=0.878 macro-F1.

## 4. Confusion matrices at pooled F1-optimal thresholds

Pooled across all 224 labelled findings (56 on-topic, 168 off-topic), single shared threshold per model.

**Model A** at threshold 0.35:
| | predicted on | predicted off |
|---|---:|---:|
| actual on (56) | TP 47 | FN 9 |
| actual off (168) | FP 7 | TN 161 |

P = 0.870 · R = 0.839 · F1 = 0.855

**Model B** at threshold 0.85:
| | predicted on | predicted off |
|---|---:|---:|
| actual on (56) | TP 39 | FN 17 |
| actual off (168) | FP 10 | TN 158 |

P = 0.796 · R = 0.696 · F1 = 0.743

Model B both misses more positives (17 vs 9 false negatives) and false-positives slightly more (10 vs 7) under a single shared threshold. Both errors are made worse by e5's compressed score distribution — the optimal threshold sits in a narrow band where small score shifts flip predictions.

## 5. Per-language behaviour

Latin- vs non-Latin-script split, pooled across both dates and all six clusters.

| Family | n labelled | n on-topic | Model | F1-opt thr | Precision | Recall | F1 | AUC |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| Latin (en, es, pt, de, it, fr, tr, vi) | 214 | 56 | A | 0.35 | 0.870 | 0.839 | **0.855** | 0.943 |
| Latin | 214 | 56 | B | 0.85 | 0.796 | 0.696 | 0.743 | 0.945 |
| Non-Latin (ru) | 9 | 0 | A | — | — | — | — | — |
| Non-Latin | 9 | 0 | B | — | — | — | — | — |
| Other (vi) | 1 | 0 | A/B | — | — | — | — | — |

**Limitation:** the labelled set is 95.5% Latin-script. Of the 9 non-Latin findings (all Russian Cyrillic), all 9 are off-topic in the sampled clusters — no on-topic non-Latin findings in the ground truth. F1 and AUC are therefore undefined for non-Latin. This means the MMTEB claim that Model A underperforms on low-resource non-Latin languages **cannot be validated or refuted** from this evidence. Future labelling work that prioritises on-topic CJK/Cyrillic/Arabic findings would close this gap.

## 6. Observation

Model B improves the original calibration weakness — on the V1-baseline Iran mega-cluster (the cluster that motivated the original 0.40-F1 floor reported in the prior calibration work), F1 moves from 0.400 to 0.500 and AUC from 0.783 to 0.880, both meaningful gains in the very regime where Model A is known to struggle. Pair-discrimination (ROC AUC) is consistently slightly better for Model B across most clusters — Model B's contrastive training appears to give it a marginally better semantic separation at the pair level. But this advantage does not survive thresholding: Model B's score distribution is sharply shifted upward (optimal pooled threshold 0.85 vs Model A's 0.35) and compressed, so the same calibration cost of shifting one finding across the threshold is higher. Model B regresses on three of six clusters, most severely on the 2026-05-11 Russia-Ukraine cluster (F1 0.971 → 0.708, AUC 0.996 → 0.798) and on the 2026-05-13 Trump-Xi cluster (F1 1.000 → 0.870). The net picture: Model B is a slightly better discriminator at the pair-comparison level, but a worse classifier under any practical thresholding policy, on the data we have.

## 7. Verdict

**Decision: keep Model A (`paraphrase-multilingual-MiniLM-L12-v2`).**

Verdict-band methodology per brief:
- ≥ +0.10 macro-F1 = clear win for Model B → swap
- +0.05 to +0.10 = ambiguous → carry inconclusive finding + ask for more data
- < +0.05 = no win → keep Model A

Observed:
- **Macro-F1 delta (B − A) across dates: −0.056** — *ambiguous*, with Model A leading.
- **Pooled-F1 delta (B − A): −0.112** — *clear win for Model A*.
- Mean ROC AUC delta (B − A): +0.009 — directionally favours B, well inside noise.

Both aggregate F1 signals point against Model B. The improvement on the V1-baseline Iran cluster (+0.10 F1) is real but localised; it is offset by larger regressions on the Russia-Ukraine and Trump-Xi clusters. The +0.01 mean-AUC advantage is too small to override the F1 regression. Per the brief's thresholds, Model B does not clear the +0.10 macro-F1 bar required for a swap, and on the pooled-F1 metric Model A wins clearly.

**Production model remains pinned at `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. No production-swap brief is warranted based on this evidence.** The two-stage Embed-Pre-Cluster → Per-Cluster-LLM-Curate architecture can move forward inheriting Model A; the embedding-model question can be revisited separately if (a) new candidate models emerge or (b) targeted non-Latin / multilingual labelling closes the sampling gap.

## 8. Footprint and licensing note

Model B install footprint, as measured from the fastembed cache after the eval run:

| Component | Size |
|---|---:|
| `intfloat/multilingual-e5-small` ONNX (fp32) + config + tokenizer | 465 MB |
| Model A on-disk (already present, `qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q`) | 240 MB |
| `fastembed` library | 1 MB |
| `onnxruntime` library (already required by Model A) | 71 MB |
| **Net additional disk for Model B alongside Model A** | **+465 MB** |

The brief's standing 400-MB-ceiling is breached by 65 MB. Since the swap is **not** recommended, the ceiling decision becomes moot — no change to `pyproject.toml`, no ADR update, no add-dep. The model file remains in the fastembed cache from this eval run but is not referenced by any production code; it can be deleted with no impact (`rm -rf "$TMPDIR/fastembed_cache/models--intfloat--multilingual-e5-small"`).

License compatibility: MIT (Model B) is compatible with the project's AGPL-3.0; would have been a swap-go signal had the quality verdict gone the other way.

## 9. Open items and reproducibility

- **Determinism**: fastembed==0.8.0 single-threaded ONNX is bit-deterministic; re-running `python scripts/eval_embedding_models.py` produces identical `output/eval/embedding-2026-05-13/scores/...` JSON files and identical `metrics.json` (verified by running Model A both individually and as part of the combined run — scores match exactly).
- **Per-finding scores** persisted at `output/eval/embedding-2026-05-13/scores/{A,B}/{2026-05-11,2026-05-13}/cluster-{N}.json` — full threshold sweep and per-finding score/label pairs.
- **Non-Latin sampling gap**: only 9 Russian findings in the labelled set, all off-topic. To meaningfully evaluate Model A's MMTEB-flagged weakness on non-Latin, future labelling should target clusters with on-topic Cyrillic, CJK, or Arabic content.
- **Cluster-size heterogeneity**: 6 cluster sample sizes span 8 to 50; some clusters (Sudan, Trump-Xi 2026-05-13) hit the F1 ceiling at 1.000 for both models, contributing nothing to discrimination. Larger or harder labelled clusters would sharpen the next eval.
- **Threshold-grid resolution** (0.05 step): a finer grid (0.01) could shift the per-cluster F1 numbers but would not move the macro-F1 delta past the +0.10 swap bar — the underlying ROC curves are close enough that 0.01-step refinement only changes F1 by <0.02 in informal probes.
- **No new dependencies added**: the eval harness uses only `fastembed` (already pinned) and `numpy` (already pinned). No `pyproject.toml` change. No `requirements.txt` touched.
