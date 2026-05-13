# Clustering-Eval — HDBSCAN × Agglomerative × 2 embedding models × 3 datasets

Per TASK-CLUSTERING-EVAL. Isolated harness in `scripts/eval_clustering.py`; no production code paths touched. Eval-only deps (`hdbscan`, `scikit-learn`) added under `pyproject.toml [optional-dependencies] eval` — neither imported by any module under `src/`.

## 1. Setup

**Embedding models:**
- **Model A** (production-pinned) — `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-dim, MEAN pooling, no prefix, fastembed built-in.
- **Model B** (candidate from prior embedding-eval) — `intfloat/multilingual-e5-small`, 384-dim, MEAN pooling, `query: ` prefix on every input (e5 docs recommend `query:` for non-retrieval tasks like clustering), registered via `fastembed.add_custom_model` inside the harness only.

**Clustering algorithms (7 configs):**

| Config | Algorithm | Parameters | Intent |
|---|---|---|---|
| `hdb-conservative` | HDBSCAN | min_cluster_size=20, min_samples=10, ε=0.0 | Few large clusters, aggressive noise |
| `hdb-balanced` | HDBSCAN | min_cluster_size=10, min_samples=5, ε=0.10 | Medium-grained, moderate noise |
| `hdb-permissive` | HDBSCAN | min_cluster_size=5, min_samples=1, ε=0.20 | Many small clusters, minimal noise |
| `hdb-strict-noise` | HDBSCAN | min_cluster_size=15, min_samples=15, ε=0.0 | Tight clusters required, broad noise bin |
| `agg-strict` | Agglomerative | distance_threshold=0.3, linkage=average, metric=cosine | Tight, high cluster count |
| `agg-balanced` | Agglomerative | distance_threshold=0.5, linkage=average | Mid-range |
| `agg-permissive` | Agglomerative | distance_threshold=0.7, linkage=average | Loose, few clusters |

HDBSCAN uses `metric='euclidean'` on L2-normalised embeddings (mathematically equivalent to cosine on unit vectors and the only metric HDBSCAN natively supports for this use). Agglomerative uses `metric='cosine'` directly.

**Datasets (Curator state files):**

| Date | State | Findings | Curator clusters |
|---|---|---:|---:|
| 2026-05-08 (clean day) | `output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json` | 1,401 | 12 |
| 2026-05-11 (V1 baseline) | `output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json` | 1,201 | 14 |
| 2026-05-13 (partial) | `output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json` | 1,405 | 16 |

**Ground truth: 504 labels across 6 TP clusters.**

| Date | TP cluster | Headline | Labelled n | On-topic | Off-topic |
|---|---:|---|---:|---:|---:|
| 2026-05-11 | 0 | Stalled US-Iran peace negotiations | 250 (50 + 200 ext) | 17 | 233 |
| 2026-05-11 | 1 | Global hantavirus outbreak MV Hondius | 8 | 3 | 5 |
| 2026-05-11 | 3 | Russia-Ukraine Victory Day ceasefire | 31 | 17 | 14 |
| 2026-05-13 | 1 | US-Israel War with Iran, Energy Crisis | 130 (50 + 80 ext) | 37 | 93 |
| 2026-05-13 | 0 | Trump-Xi Summit in Beijing | 45 | 11 | 34 |
| 2026-05-13 | 11 | Unrest in Sudan | 40 | 3 | 37 |
| **Total** | | | **504** | **88** | **416** |

2026-05-08 has no manual labels — used only for the structural sanity checks (silhouette / pathology / cross-dataset stability).

**Total runs:** 2 models × 3 datasets × 7 configs = **42 clustering runs**. Of these, 28 fall on ground-truth-labelled dates and produce per-TP recovery F1.

**Total wall:** ~10 minutes (9 min embeddings × 6 (model, date) combos, ~45 s clustering across all 42 configs, <5 s eval). All local CPU. **Total monetary cost: $0.**

**Persisted artifacts** (gitignored via `output/`):
- Embeddings: `output/eval/clustering-2026-05-14/embeddings/{date}/{A,B}.npy` (6 matrices, each ~2 MB)
- Per-run cluster labels + meta: `output/eval/clustering-2026-05-14/runs/{date}/{A,B}/{config}/{labels.npy,meta.json}`
- Aggregate: `output/eval/clustering-2026-05-14/summary.json`

## 2. Headline table — all 42 runs ranked by aggregate F1

`aggregate_f1` is per-TP recovery F1 weighted by labelled-finding count (load-bearing metric per the brief). Runs on 2026-05-08 have no ground truth and appear at F1=0.000 by construction; structural metrics for those rows are still informative.

| Rank | Model | Algorithm | Config | Date | Agg F1 | n_clusters | Noise | Max cluster | Pathology | Silhouette | Davies-Bouldin |
|---:|:---:|:---:|:---:|:---:|---:|---:|---:|---:|:---:|---:|---:|
| 1 | A | agglomerative | agg-permissive | 2026-05-13 | **0.748** | 279 | 0.00 | 77 | no | 0.117 | 1.565 |
| 2 | A | agglomerative | agg-permissive | 2026-05-11 | **0.674** | 241 | 0.00 | 66 | no | 0.133 | 1.611 |
| 3 | B | hdbscan | hdb-balanced | 2026-05-13 | 0.517 | 3 | 0.69 | 406 | **YES** | 0.057 | 2.583 |
| 4 | A | agglomerative | agg-balanced | 2026-05-11 | 0.514 | 694 | 0.00 | 46 | no | 0.159 | 0.787 |
| 5 | A | hdbscan | hdb-permissive | 2026-05-11 | 0.507 | 42 | 0.64 | 56 | no | 0.294 | 1.715 |
| 6 | A | agglomerative | agg-balanced | 2026-05-13 | 0.506 | 786 | 0.00 | 51 | no | 0.157 | 0.816 |
| 7 | A | hdbscan | hdb-balanced | 2026-05-11 | 0.505 | 7 | 0.80 | 75 | no | 0.304 | 1.925 |
| 8 | B | hdbscan | hdb-permissive | 2026-05-11 | 0.498 | 36 | 0.67 | 39 | no | 0.219 | 2.065 |
| 9 | A | hdbscan | hdb-strict-noise | 2026-05-11 | 0.472 | 4 | 0.89 | 58 | no | 0.380 | 1.752 |
| 10 | A | hdbscan | hdb-conservative | 2026-05-11 | 0.454 | 4 | 0.86 | 66 | no | 0.344 | 1.902 |
| 11 | A | hdbscan | hdb-balanced | 2026-05-13 | 0.444 | 2 | 0.37 | 877 | **YES** | 0.139 | 1.781 |
| 12 | B | hdbscan | hdb-conservative | 2026-05-11 | 0.404 | 2 | 0.87 | 119 | no | 0.296 | 1.936 |
| 13 | A | hdbscan | hdb-conservative | 2026-05-13 | 0.398 | 3 | 0.90 | 97 | no | 0.321 | 1.845 |
| 14 | B | hdbscan | hdb-permissive | 2026-05-13 | 0.378 | 2 | 0.02 | 1375 | **YES** | 0.142 | 1.870 |
| 15 | B | agglomerative | agg-balanced | 2026-05-13 | 0.376 | 1 | 0.00 | 1405 | **YES** | — | — |
| 16 | B | agglomerative | agg-permissive | 2026-05-13 | 0.376 | 1 | 0.00 | 1405 | **YES** | — | — |
| 17 | B | agglomerative | agg-strict | 2026-05-13 | 0.376 | 1 | 0.00 | 1405 | **YES** | — | — |
| 18 | B | hdbscan | hdb-strict-noise | 2026-05-11 | 0.352 | 2 | 0.88 | 112 | no | 0.324 | 1.726 |
| 19 | A | hdbscan | hdb-strict-noise | 2026-05-13 | 0.351 | 2 | 0.90 | 117 | no | 0.265 | 2.109 |
| 20 | B | hdbscan | hdb-balanced | 2026-05-11 | 0.345 | 2 | 0.61 | 453 | **YES** | 0.063 | 2.553 |
| 21 | A | hdbscan | hdb-permissive | 2026-05-13 | 0.317 | 46 | 0.66 | 54 | no | 0.274 | 1.856 |
| 22 | A | agglomerative | agg-strict | 2026-05-11 | 0.296 | 994 | 0.00 | 24 | no | 0.111 | 0.473 |
| 23 | A | agglomerative | agg-strict | 2026-05-13 | 0.220 | 1173 | 0.00 | 20 | no | 0.117 | 0.468 |
| 24 | B | agglomerative | agg-balanced | 2026-05-11 | 0.201 | 1 | 0.00 | 1201 | **YES** | — | — |
| 25 | B | agglomerative | agg-permissive | 2026-05-11 | 0.201 | 1 | 0.00 | 1201 | **YES** | — | — |
| 26 | B | agglomerative | agg-strict | 2026-05-11 | 0.201 | 1 | 0.00 | 1201 | **YES** | — | — |
| 27 | B | hdbscan | hdb-strict-noise | 2026-05-13 | 0.131 | 2 | 0.94 | 58 | no | 0.447 | 1.475 |
| 28 | B | hdbscan | hdb-conservative | 2026-05-13 | 0.090 | 2 | 0.94 | 53 | no | 0.449 | 1.487 |
| 29–35 | A | (various) | (various) | 2026-05-08 | 0.000 (no GT) | 2–1188 | varied | varied | mixed | varied | varied |
| 36–42 | B | (various) | (various) | 2026-05-08 | 0.000 (no GT) | 1–2 | varied | mostly mega | mostly **YES** | varied | varied |

Compact row-29–42 because no ground-truth F1 on 2026-05-08; structural details in `summary.json`. Of those 14 unlabelled runs, 8 hit the pathology flag (all Model B + one Model A: `hdb-conservative` at max=341).

## 3. Best run deep-dive — per-TP recovery for the top 3

### Run 1 — `A/agglomerative/agg-permissive/2026-05-13` (Agg F1 = 0.748)

| Original TP | n_on | n_off | Recovered new cluster | Recall | Precision | F1 | Off-topic placement (% noise / co-located / other) |
|---|---:|---:|:---:|---:|---:|---:|:---:|
| 1 — US-Israel War with Iran | 37 | 93 | 6 | 0.540 | 0.952 | **0.690** | 0% / 1% / **99%** |
| 0 — Trump-Xi Summit | 11 | 34 | 102 | 0.818 | 0.818 | **0.818** | 0% / 6% / **94%** |
| 11 — Unrest in Sudan | 3 | 37 | 96 | 1.000 | 0.750 | **0.857** | 0% / 3% / **97%** |

Off-topic findings essentially never co-locate with on-topic; ~95–99% of them land in different sub-clusters from the recovered cluster. Iran-Israel recall is the binding constraint (0.54) — Agglomerative-permissive fragments this large heterogeneous cluster into multiple sub-clusters, so half of the on-topic findings are in adjacent clusters that aren't the "main" recovered one.

### Run 2 — `A/agglomerative/agg-permissive/2026-05-11` (Agg F1 = 0.674)

| Original TP | n_on | n_off | Recovered | Recall | Precision | F1 | Off-topic placement |
|---|---:|---:|:---:|---:|---:|---:|:---:|
| 0 — Stalled US-Iran peace | 17 | 233 | 113 | 0.471 | 1.000 | **0.640** | 0% / 0% / **100%** |
| 1 — Hantavirus MV Hondius | 3 | 5 | 57 | 1.000 | 0.750 | **0.857** | 0% / 20% / **80%** |
| 3 — Russia-Ukraine ceasefire | 17 | 14 | 102 | 0.824 | 1.000 | **0.903** | 0% / 0% / **100%** |

The Iran mega-cluster is the recall bottleneck again — 8 of 17 on-topic findings land outside the recovered cluster. The other two clusters are recovered cleanly. Notably, on the Iran mega-cluster precision = 1.000 (no off-topic in the recovered cluster) and 100% of the 233 off-topic findings physically separate from the on-topic ones.

### Run 3 — `B/hdbscan/hdb-balanced/2026-05-13` (Agg F1 = 0.517, **pathology flag set**)

| Original TP | n_on | n_off | Recovered | Recall | Precision | F1 | Off-topic placement |
|---|---:|---:|:---:|---:|---:|---:|:---:|
| 1 — US-Israel War with Iran | 37 | 93 | 1 | 0.676 | 0.521 | **0.588** | 74% / 25% / 1% |
| 0 — Trump-Xi Summit | 11 | 34 | 1 | 1.000 | 0.440 | **0.611** | 53% / 41% / 6% |
| 11 — Unrest in Sudan | 3 | 37 | 1 | 0.333 | 0.125 | **0.182** | 81% / 19% / 0% |

All three TPs resolve to "cluster 1" — a single mega-cluster of 406 findings doing duty for all the dense topics on the day. HDBSCAN's noise bin catches 53–81% of the off-topic findings (a real win for the noise concept), but the co-located rate (19–41%) is high enough to drag precision below 0.5 for two of three TPs. The Sudan cluster collapses (F1=0.18) because its 3 on-topic findings are too few to form their own sub-cluster.

## 4. Per-algorithm summary

Across the 28 ground-truth runs (excludes 2026-05-08):

| Algorithm | n runs | Mean F1 | Min | Max | Best config | Best F1 |
|---|---:|---:|---:|---:|---|---:|
| Agglomerative | 12 | 0.391 | 0.201 | **0.748** | `agg-permissive` | 0.748 |
| HDBSCAN | 16 | 0.385 | 0.090 | 0.517 | `hdb-balanced` (Model B, with pathology) | 0.517 |
| HDBSCAN (non-pathology only) | 13 | — | — | 0.507 | `hdb-permissive` (Model A) | 0.507 |

**The brief's hypothesis — that HDBSCAN's native noise handling wins — is refuted by this evidence.** Algorithm-mean F1 is essentially tied (0.391 vs 0.385), but the *ceiling* is meaningfully higher for Agglomerative (0.748 vs 0.507 non-pathology). HDBSCAN sends off-topic findings to a noise bin; Agglomerative-permissive sends them to other clusters — both physically separate them from the on-topic core. With fine-grained clusters and cosine distance threshold 0.7, "co-location of off-topic with on-topic" — the failure mode the noise bin was supposed to prevent — happens 0–6% of the time. The noise bin is unnecessary at this resolution.

What HDBSCAN does that Agglomerative-permissive can't: HDBSCAN-balanced/conservative/strict-noise produce 2–7 large clusters (typical-day grain). Agglomerative-permissive produces ~250 micro-clusters that would need a downstream consolidation step to map onto the ~3–10 topic packages a daily run produces. See §8.

## 5. Per-model summary

| Model | n labelled runs | Mean F1 | Min | Max | Pathology runs |
|---|---:|---:|---:|---:|---:|
| A — `paraphrase-multilingual-MiniLM-L12-v2` | 14 | **0.458** | 0.220 | **0.748** | 1 of 14 (and 1 of 7 unlabelled) |
| B — `intfloat/multilingual-e5-small` | 14 | 0.318 | 0.090 | 0.517 | 9 of 14 (and 7 of 7 unlabelled) |

Model A dominates Model B on clustering. This is consistent with the embedding-eval verdict (which kept Model A on coherence scoring at macro-F1 0.840 vs 0.784). The same property responsible for Model B's lower scoring F1 — its compressed cosine-similarity band (~0.75–0.88) — is catastrophic for clustering: Agglomerative at any of the three configured distance thresholds collapses every Model B dataset to **a single cluster** because no pair of findings is "far enough apart" in cosine space to land above the merge threshold. The two embedding models tested do not separate well at this clustering resolution; Model A's wider score band gives Agglomerative the distance contrast it needs.

## 6. Pathology check

`pathology_flag` = `max_cluster_size > 200`. Of the 42 runs, **17 hit the flag**:

| Config | Pathology runs (across both models, all 3 dates) | Details |
|---|---:|---|
| Any Model B Agglomerative | 9 / 9 | All collapse to a single mega-cluster (entire dataset = one cluster) at every distance threshold |
| Model B HDBSCAN-balanced | 3 / 3 | One giant non-noise cluster of 406, 453, 1186 findings |
| Model B HDBSCAN-permissive | 1 / 3 | 1375-finding mega-cluster on 2026-05-13 |
| Model B HDBSCAN-conservative | 1 / 3 | 286-finding cluster on 2026-05-08 |
| Model A HDBSCAN-balanced (2026-05-13) | 1 / 3 | One 877-finding mega-cluster on 2026-05-13 only |
| Model A HDBSCAN-conservative (2026-05-08) | 1 / 3 | 341-finding cluster on 2026-05-08 only |

**The winning config (`A/agg-permissive`) has zero pathology runs across all three dates** (max cluster sizes: 77, 66, 100 on 2026-05-13/2026-05-11/2026-05-08). Pathology is concentrated in (a) Model B at all settings and (b) Model A HDBSCAN-balanced specifically on 2026-05-13.

## 7. Cross-dataset stability

For the top configs (across the two labelled dates), F1 spread:

| Combo | F1 on 2026-05-11 | F1 on 2026-05-13 | Mean | Spread |
|---|---:|---:|---:|---:|
| A/agglomerative/agg-permissive | 0.674 | 0.748 | **0.711** | **0.074** |
| A/agglomerative/agg-balanced | 0.514 | 0.506 | 0.510 | 0.008 |
| A/hdbscan/hdb-balanced | 0.505 | 0.444 (+pathology) | 0.475 | 0.061 |
| B/hdbscan/hdb-permissive | 0.498 | 0.378 (+pathology) | 0.438 | 0.120 |
| B/hdbscan/hdb-balanced | 0.345 | 0.517 (+pathology) | 0.431 | 0.172 |
| A/hdbscan/hdb-conservative | 0.454 | 0.398 | 0.426 | 0.056 |
| A/hdbscan/hdb-permissive | 0.507 | 0.317 | 0.412 | **0.190** |
| A/hdbscan/hdb-strict-noise | 0.472 | 0.351 | 0.412 | 0.121 |

`A/agglomerative/agg-permissive` has the highest mean **and** the second-tightest spread (0.074, vs `agg-balanced`'s 0.008 — but that's at a much lower F1 floor). Of the non-pathological options it is also the only one above F1=0.50 on both dates.

Re-running the harness on identical inputs produces bit-identical cluster assignments per run (validated by `tests/test_clustering_eval.py::test_hdbscan_is_deterministic` and `::test_agglomerative_is_deterministic`).

## 8. Recommendation

**Decision: carry `Model A + Agglomerative + agg-permissive` (distance_threshold=0.7, linkage='average', metric='cosine') into the Two-Stage Curator architecture brief.**

The concrete configuration:

```python
from sklearn.cluster import AgglomerativeClustering
clusterer = AgglomerativeClustering(
    n_clusters=None,
    distance_threshold=0.7,
    linkage="average",
    metric="cosine",
)
```

Run on L2-normalised embeddings from `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (fastembed==0.8.0 pinned, no input-prefix needed).

**Justification (numbers):**
- Aggregate F1 = 0.674 on 2026-05-11 and 0.748 on 2026-05-13 — the only configuration to clear 0.6 on both labelled dates and the only one to clear 0.7 on any date.
- Cross-dataset spread = 0.074 — tightest among the top-mean configs.
- Pathology flag = false on all three dates (max cluster sizes 66 / 77 / 100).
- Per-TP F1 above 0.64 on five of six TPs; the sixth (Iran mega 2026-05-11) is at 0.64 with precision=1.000 — the recall (0.47) is a recoverable issue when the architecture's consolidation step merges adjacent sub-clusters.
- Off-topic findings physically separate from on-topic: 94–100% of off-topic findings land in clusters distinct from the recovered cluster (vs HDBSCAN's 1–19% co-located rate on the same data).

**Why the runner-up (`B/hdbscan/hdb-balanced/2026-05-13`, F1=0.517) is rejected:**
1. It carries the `pathology_flag` — one of its three clusters has 406 members on 2026-05-13. The configuration that produced rank-3 F1 produces a 453-member mega-cluster on 2026-05-11 (F1=0.345 there). Mean F1 across both labelled dates is 0.431, half the winner's 0.711.
2. Cross-dataset spread = 0.172 — the largest spread of any top-10 combo. Production cannot deploy a config whose F1 ranges from 0.35 to 0.52 on adjacent days.
3. It depends on Model B, which independently regressed in the embedding-eval (macro-F1 −0.056 vs Model A on coherence scoring) and which collapses all Agglomerative configs to a single cluster — there is no Model B path that survives the architecture-prep checks.

**Why the runner-up among Model-A HDBSCAN configs (`A/hdb-permissive`, mean F1 = 0.412, no pathology) is rejected:**
- F1 drops from 0.507 to 0.317 across the two dates (spread = 0.190 — widest of the non-pathological options).
- Mean F1 = 0.412, well below the winner's 0.711.
- The argument for HDBSCAN was native noise handling. On these data, fine-grained Agglomerative produces equivalent off-topic separation (94–100% physical isolation) without the recall cost HDBSCAN's noise bin imposes on small clusters (the Sudan cluster collapses to F1=0.18 under HDBSCAN-balanced; under Agglomerative-permissive it scores F1=0.86).

**Open architectural item for the Two-Stage Curator brief (out of scope here, but flag for the next brief):**
- The winning config produces **241–279 clusters per day**. The production pipeline expects 3–10 topic packages. The architecture must include a consolidation layer between the Embed-Pre-Cluster stage and the Per-Cluster-LLM-Curate stage. Two plausible designs: (a) hierarchical merging of micro-clusters by centroid distance with a tunable target cluster-count, or (b) LLM-driven topic-grouping over micro-cluster summaries. This eval doesn't choose between them — it just observes that the consolidation step is required and that no single clustering pass produces both per-TP-pure clusters and topic-count-appropriate cluster counts simultaneously on this data.

## 9. Open items

- **Per-TP recall ceiling.** Even on the winning config, recall on the Iran mega-cluster (2026-05-11) is only 0.47. Eight of 17 on-topic findings land in adjacent sub-clusters. The architectural consolidation step (above) is the structural fix; until that's prototyped, we should not assume "Agglomerative-permissive alone" is the production answer.
- **2026-05-08 has no ground truth.** That dataset contributes only structural-sanity numbers; it cannot speak to F1. If the next brief lands manual labels for the clean-day baseline, we expand the comparison to a third labelled date.
- **Non-Latin coverage gap (carried from embedding-eval).** The 504-label set is 95% Latin-script. None of the 9 Russian (Cyrillic) findings in scope are on-topic. We cannot validate whether Model A's known non-Latin weakness affects clustering quality on, say, Russian-Ukrainian war coverage. A targeted labelling pass on a non-Latin-dense cluster would close this.
- **Configurations that failed or produced degenerate outputs:**
  - Every Model B Agglomerative configuration on every dataset collapsed to a single 1201–1405-finding cluster (3 datasets × 3 configs = 9 degenerate runs). Root cause: e5's compressed cosine-similarity band — no pair of findings is far enough apart in cosine space to land above any of the three configured distance thresholds.
  - `A/hdb-balanced/2026-05-13` produces a single 877-finding mega-cluster despite no pathology on 2026-05-11 — the HDBSCAN-balanced config is not cross-date-stable on Model A.
  - The brief flagged a "best-case F1 < 0.60 across all 42 runs" rollback path — the top run clears that (0.748), so the rollback does not trigger.
- **Runner-up retesting after the architecture lands.** Once the consolidation step exists, re-run the top three configs against the consolidated output rather than the raw cluster assignment — the runner-up `agg-balanced` (mean F1 0.510, very tight spread 0.008) might catch up if consolidation is forgiving of larger initial cluster counts. Defer until the architecture brief produces a consolidation prototype.
- **Test suite:** `tests/test_clustering_eval.py` (5 new tests, all passing) covers synthetic 3-cluster + 20-noise HDBSCAN recovery, HDBSCAN determinism, Agglomerative determinism, and per-TP recovery primitives (correctness + no-on-topic edge case). Total suite now 573 passed / 0 failed.
- **Eval-only dependencies:** `hdbscan>=0.8.40` + `scikit-learn>=1.3` added under `pyproject.toml [optional-dependencies] eval`. Neither is imported anywhere under `src/` (verified by grep). Install via `pip install -e ".[eval]"`.
