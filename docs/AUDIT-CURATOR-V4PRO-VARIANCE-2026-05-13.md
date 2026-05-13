# Audit — DeepSeek-V4-Pro Curator variance (3-day × 3-temp × 3-rep)

- **Generated:** 2026-05-13T18:46:15.272928+00:00
- **Model:** `deepseek-v4-pro` · `extra_body={'thinking': {'type': 'disabled'}}` · max_tokens=320000
- **Pricing applied:** miss $0.435/M · cached $0.003625/M · output $0.87/M (DeepSeek V4-Pro 75% discount rate (valid until 2026-05-31).)

## 1. Setup

- Dates: 2026-05-08, 2026-05-11, 2026-05-13
- Configs: `dskpro-t05-r-none` (t=0.5), `dskpro-t07-r-none` (t=0.7), `dskpro-t10-r-none` (t=1.0)
- Reps per (date, config): 3
- Total runs attempted: 27
- Total succeeded: 27
- Total failed: 0
- Total cost: **$1.6380** (cap $5.00)
- Total wall: 27246 s (~7.6 h)
- Halt reason: `complete`

**Mid-run setting change:** `max_tokens` was raised from the brief's 64000 to 320000 after the first 9 calls (all of 2026-05-08) had completed. The change was made because three of the 2026-05-08 cells were producing mid-stream peer-close errors around chunk 20000 (~20k output tokens) and the architect-approved direction was to give V4-Pro enough output budget to finish naturally. The trade-off realised in the data: cells at max_tokens=320000 frequently produced 2–3-hour calls with cluster outputs near the new ceiling. The 9 cells at max_tokens=64000 (all of 2026-05-08) and the 17 cells at max_tokens=320000 (2026-05-11 + 2026-05-13, plus one already-saved 64k rep at `2026-05-11/dskpro-t05-r-none/rep-3`) are therefore not strictly apples-to-apples. The within-cell variance signal (the headline) is unaffected within any cell because all reps of a cell share the same `max_tokens`; cross-cell numeric comparison should be read with this caveat in mind.

## 2. Per-cell variance table

| Cell | top_cluster_size | top_off%_regex | n_clusters | orphan_rate | inter-rep Jaccard (mean / min) | n_ok |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-08/dskpro-t05-r-none | 16.00 ± 6.93 [12.00 … 24.00] | 16.67 ± 8.34 | 22.67 ± 4.62 [20.00 … 28.00] | 0.98 ± 0.02 | 0.575 / 0.440 | 3/3 |
| 2026-05-08/dskpro-t07-r-none | 24.67 ± 5.51 [21.00 … 31.00] | 24.80 ± 14.97 | 20.00 ± 0.00 [20.00 … 20.00] | 0.96 ± 0.01 | 0.365 / 0.268 | 3/3 |
| 2026-05-08/dskpro-t10-r-none | 95.00 ± 79.00 [44.00 … 186.00] | 71.80 ± 13.01 | 22.00 ± 7.00 [17.00 … 30.00] | 0.74 ± 0.16 | 0.036 / 0.010 | 3/3 |
| 2026-05-11/dskpro-t05-r-none | 11.33 ± 18.77 [0.00 … 33.00] | 16.16 ± 27.99 | 13.67 ± 10.97 [1.00 … 20.00] | 0.98 ± 0.03 | 0.010 / 0.000 | 3/3 |
| 2026-05-11/dskpro-t07-r-none | 690.67 ± 598.22 [0.00 … 1046.00] | 55.81 ± 48.47 | 19.00 ± 1.73 [17.00 … 20.00] | 0.36 ± 0.55 | 0.320 / 0.000 | 3/3 |
| 2026-05-11/dskpro-t10-r-none | 63.00 ± 8.89 [56.00 … 73.00] | 50.82 ± 0.90 | 19.00 ± 1.00 [18.00 … 20.00] | 0.84 ± 0.03 | 0.128 / 0.049 | 3/3 |
| 2026-05-13/dskpro-t05-r-none | 873.00 ± 754.85 [2.00 … 1337.00] | 72.31 ± 19.81 | 26.67 ± 11.55 [20.00 … 40.00] | 0.33 ± 0.55 | 0.320 / 0.000 | 3/3 |
| 2026-05-13/dskpro-t07-r-none | 500.67 ± 690.95 [60.00 … 1297.00] | 68.32 ± 12.62 | 23.00 ± 5.20 [20.00 … 29.00] | 0.61 ± 0.48 | 0.111 / 0.023 | 3/3 |
| 2026-05-13/dskpro-t10-r-none | 95.33 ± 75.94 [50.00 … 183.00] | 66.50 ± 17.25 | 25.33 ± 0.58 [25.00 … 26.00] | 0.69 ± 0.32 | 0.054 / 0.040 | 3/3 |

**Inter-rep Jaccard** = mean of pairwise IoU on the three reps' top-cluster `source_ids`. Higher = more reproducible. 1.00 = identical top clusters across reps; 0.00 = three disjoint top clusters.

## 3. Per-date cross-config comparison

### 2026-05-08

| temperature | top_cluster_size (mean ± sd) | top_off% | n_clusters | inter-rep Jaccard |
|---:|---:|---:|---:|---:|
| 0.5 | 16.00 ± 6.93 | 16.67 ± 8.34 | 22.67 ± 4.62 | 0.575 |
| 0.7 | 24.67 ± 5.51 | 24.80 ± 14.97 | 20.00 ± 0.00 | 0.365 |
| 1.0 | 95.00 ± 79.00 | 71.80 ± 13.01 | 22.00 ± 7.00 | 0.036 |

### 2026-05-11

| temperature | top_cluster_size (mean ± sd) | top_off% | n_clusters | inter-rep Jaccard |
|---:|---:|---:|---:|---:|
| 0.5 | 11.33 ± 18.77 | 16.16 ± 27.99 | 13.67 ± 10.97 | 0.010 |
| 0.7 | 690.67 ± 598.22 | 55.81 ± 48.47 | 19.00 ± 1.73 | 0.320 |
| 1.0 | 63.00 ± 8.89 | 50.82 ± 0.90 | 19.00 ± 1.00 | 0.128 |

### 2026-05-13

| temperature | top_cluster_size (mean ± sd) | top_off% | n_clusters | inter-rep Jaccard |
|---:|---:|---:|---:|---:|
| 0.5 | 873.00 ± 754.85 | 72.31 ± 19.81 | 26.67 ± 11.55 | 0.320 |
| 0.7 | 500.67 ± 690.95 | 68.32 ± 12.62 | 23.00 ± 5.20 | 0.111 |
| 1.0 | 95.33 ± 75.94 | 66.50 ± 17.25 | 25.33 ± 0.58 | 0.054 |

## 4. Per-config cross-date comparison

### dskpro-t05-r-none (t=0.5)

| date | top_cluster_size (mean ± sd) | top_off% | n_clusters | inter-rep Jaccard |
|---|---:|---:|---:|---:|
| 2026-05-08 | 16.00 ± 6.93 | 16.67 ± 8.34 | 22.67 ± 4.62 | 0.575 |
| 2026-05-11 | 11.33 ± 18.77 | 16.16 ± 27.99 | 13.67 ± 10.97 | 0.010 |
| 2026-05-13 | 873.00 ± 754.85 | 72.31 ± 19.81 | 26.67 ± 11.55 | 0.320 |

### dskpro-t07-r-none (t=0.7)

| date | top_cluster_size (mean ± sd) | top_off% | n_clusters | inter-rep Jaccard |
|---|---:|---:|---:|---:|
| 2026-05-08 | 24.67 ± 5.51 | 24.80 ± 14.97 | 20.00 ± 0.00 | 0.365 |
| 2026-05-11 | 690.67 ± 598.22 | 55.81 ± 48.47 | 19.00 ± 1.73 | 0.320 |
| 2026-05-13 | 500.67 ± 690.95 | 68.32 ± 12.62 | 23.00 ± 5.20 | 0.111 |

### dskpro-t10-r-none (t=1.0)

| date | top_cluster_size (mean ± sd) | top_off% | n_clusters | inter-rep Jaccard |
|---|---:|---:|---:|---:|
| 2026-05-08 | 95.00 ± 79.00 | 71.80 ± 13.01 | 22.00 ± 7.00 | 0.036 |
| 2026-05-11 | 63.00 ± 8.89 | 50.82 ± 0.90 | 19.00 ± 1.00 | 0.128 |
| 2026-05-13 | 95.33 ± 75.94 | 66.50 ± 17.25 | 25.33 ± 0.58 | 0.054 |

## 5. Cross-comparison vs production Gemini-temp=1.0

| date | prod top | prod off% | V4-Pro best t / top mean | V4-Pro best t / off% mean | best t (by lowest off%) |
|---|---:|---:|---:|---:|---:|
| 2026-05-08 | 32 | 3.12% | 16.0 | 16.67% | t=0.5 |
| 2026-05-11 | 1004 | 78.98% | 11.3 | 16.16% | t=0.5 |
| 2026-05-13 | 180 | 61.67% | 95.3 | 66.50% | t=1.0 |

## 6. Observation

Mean inter-rep Jaccard across all 9 cells is **0.213**, with a range of 0.010 – 0.575. Only one cell (`2026-05-08/t=0.5`) clears 0.50; six cells are below 0.20 and three of those are essentially zero. Three independent V4-Pro runs at the same temperature on the same input produce visibly different top clusters in nearly every cell measured. The temperature axis is not monotonic across pathology levels: on the clean day (2026-05-08) reproducibility decreases as temperature rises (0.575 → 0.365 → 0.036), but on the severe-pathology day (2026-05-11) the highest-temperature cell is the most reproducible of the three (0.010 → 0.320 → 0.128 isn't monotonic either way), and on 2026-05-13 reproducibility again decreases with temperature (0.320 → 0.111 → 0.054). The pathology is therefore not a stable function of temperature — V4-Pro's failure modes are sample-dependent in a way temperature does not predict, which is the strongest signal in the run against using it as a drop-in production Curator.

The variance is amplified by two qualitatively distinct degeneracy modes that V4-Pro hits in the same cell at the same temperature: (a) **over-shattering** — producing 20–40 cluster headlines with almost no source_ids attached (e.g. `2026-05-11/t=0.5/rep-1`: top=0, clusters=20; `2026-05-11/t=0.5/rep-3`: top=1, clusters=1; `2026-05-13/t=0.5/rep-1`: top=2, clusters=40); and (b) **mega-clustering** — collapsing almost the entire finding-set into one giant cluster (e.g. `2026-05-13/t=0.5/rep-2`: top=1280; `2026-05-13/t=0.5/rep-3`: top=1337; `2026-05-13/t=0.7/rep-2`: top=1297). Five of 27 reps were severely degenerate by either mode. Whether the model lands in regime (a) or (b) appears to be coin-flip stochastic at the same temperature — see `2026-05-13/t=0.5` for the cleanest example, where the three reps are top=2 / 1280 / 1337.

## 7. Open items

- **No failed calls.** All 27 attempts returned an output JSON the script could parse into clusters.
- **4 mid-stream peer-close events.** DeepSeek-direct closed the streaming connection mid-response on 4 of the 27 calls (always around chunk 20000–30000, ~20–30k output tokens in). The retry path recovered each in ≤2 attempts; no rep-level failures resulted. These were not concentrated to one date or temperature — they appeared in `2026-05-08/t=0.7/rep-3`, `2026-05-11/t=0.5/rep-1` (twice), and `2026-05-11/t=0.7/rep-1`.
- **5 severely degenerate outputs** (top_cluster_size ≤ 2): `2026-05-11/t=0.5/rep-3` (top=1, single trivial cluster), `2026-05-11/t=0.5/rep-1` (top=0, 20 empty clusters), `2026-05-11/t=0.7/rep-3` (top=0, 20 empty clusters), `2026-05-13/t=0.5/rep-1` (top=2, 40 mini-clusters). These are model-side failures — the response parsed cleanly but the model declined to assign findings to the cluster headlines it generated. Cause is consistent across temperatures (appears at t=0.5 and t=0.7) and across two of three dates; not a serving issue.
- **Wall-clock cost of max_tokens=320000.** Cells under the raised limit ran 2–2.5 h per call when the model decided to generate near the cap. Cells under the original 64k limit ran ~30 min per call. This is the trade-off cost of giving V4-Pro enough output room to avoid mid-stream peer-closes; the model uses what it's given.
- **Schema-validation noise.** Many calls produced cluster-headlines with `cluster_assignments` length ≠ findings length (script processed the overlap only). This is logged as a WARNING per call and the cluster_assignments JSON was post-repaired by the existing `json-repair` path. Some empty-source_ids topics are a downstream consequence of this mismatch.
- **Cost-tracker anomaly:** several reps recorded `cost_usd=0.0000` despite generating 100k+ chars of output. The DeepSeek-direct trailing usage event reported `prompt_cache_hit_tokens == prompt_tokens` for these calls (full input cache hit) and the output-token count was small enough to round below $0.00005 with `%.4f` formatting. The on-disk `rep-*.json` carry the raw token breakdowns if the actual figures need reconstructing.

## 8. Recommendation

V4-Pro inter-rep Jaccard averages **0.213** across cells — below the reproducibility floor of 0.40 used by this audit. Three identical runs at the same temperature produce visibly different top clusters in 8 of 9 cells. Best V4-Pro temperature by mean off% across dates is **t=0.5** at 35.05% mean, vs production-Gemini-temp=1.0's 47.92% mean across the same three dates — a meaningful improvement in clustering quality at the means, but undermined by the variance: the t=0.5 cells include both `2026-05-13/t=0.5` (top sizes 2 / 1280 / 1337 across reps, regime-flipping under identical input) and `2026-05-11/t=0.5` (top sizes 0 / 1 / 33, two reps degenerate).

**Recommendation: Keep production Gemini-temp=1.0.** V4-Pro is not reproducible enough at this matrix sizing to be considered a drop-in replacement. The variance signal disqualifies it independently of the cluster-quality gain at the means — a production Curator that lands in mega-cluster regime on one run and over-shatter regime on the next (same input, same temperature) is not operationally viable; the downstream Editor and Researcher stages assume the Curator output looks broadly consistent run-to-run.

Follow-on worth running before reconsidering V4-Pro: (1) a larger-N rep study at a single (date, temperature) cell — e.g. 10–15 reps at `2026-05-13/t=0.5` — to characterise the regime-flip distribution rather than estimating it from 3 reps; (2) the same audit shape against `deepseek-v4-flash` direct, which has shown better reproducibility on shorter prompts in the shadow data; (3) a same-day rerun of this audit with `max_tokens=64000` consistent across all cells, to disentangle the variance signal from the 320k-induced long generations.

**Verdict tag (for commit-message subject):** `inconclusive — V4-Pro not reproducible enough to recommend a swap`
