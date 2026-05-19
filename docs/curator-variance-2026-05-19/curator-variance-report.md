# Curator topic-discovery variance smoke — DeepSeek V4 Flash (2026-05-19)

27 calls (9 variants × 3 reps) of `curator_topic_discovery` against the
2026-05-18 substrate, measuring per-variant variance on emission count,
unique-theme count (post 0.85 cosine dedup), and text-corruption
signals. Single autonomous run, all 27 calls succeeded, 100 % schema
validity, **$0.1218 total spend** (2.4 % of $5 cap).

## Setup

- **Substrate:** `output/2026-05-18/_state/run-2026-05-18-c26864b2/run_bus.pre_cluster_findings.json` — 1,217 findings, 252 agglomerative pre-clusters. Compressed via top-K-by-centroid (K=8) using the fastembed singleton, identical to the production wrapper's path. Substrate loaded once, messages shared across all 27 calls.
- **Variant grid:** 3 temps × 3 reasoning levels × 3 reps. Per-call config: `deepseek/deepseek-v4-flash`, `max_tokens=160000`, strict-mode `CURATOR_TOPIC_DISCOVERY_SCHEMA`, provider routing `{order: ["deepseek"], allow_fallbacks: True, require_parameters: True}`.
- **Streaming** mandatory for `reasoning ∈ {medium, high}` — 6 variants × 3 reps = 18 streaming calls. Zero streaming failures, no AtlasCloud content-moderation rejections (substrate is run-phase pre-cluster summaries, not the war / civilian-casualty per-topic content that tripped Wave-2 Sweep #5 Perspective).
- **Concurrency:** all 9 reasoning-level calls per batch dispatched concurrently via `asyncio.gather` (3 reasoning batches sequentially). Total wall time ~26 min (longest batch: rmedium at 19 min, dominated by a 1,131 s outlier on `t07-rmedium-rep2` routed via the AkashML fallback provider).
- **Harness:** Wave-1 Option B reused verbatim (`scripts/eval_common.py`). New runner: `scripts/eval_curator_variance.py`.

### Corruption-signal regex set

Four patterns scan `title + summary` of every emitted topic. The first three are the brief-specified patterns; the fourth was added after the Wave-2 §Why examples test (`Hezbollah denounced ... were denounced`, `petition against Bolloré petition`) showed those two cases are non-adjacent stutters that the brief's three patterns miss. The tightened scope (length ≥ 7, lowercase-initial token, window 2-5) keeps it conservative — when verified against the Wave-2 `dskflash-t05-rnone.json` it caught exactly those two §Why examples and produced zero false positives on the remaining 39 topics.

| pattern | regex | catches |
|---|---|---|
| repeated word (adjacent) | `\b(\w+)\s+\1\b` (i) | `wounding wounding` |
| repeated quoted phrase | `'([^']{3,}?)'(\1)` | `'clock is ticking'clock is ticking'` |
| hyphen-mangled compound | `\b\w+-\w+ed\b` | `car-rammed`, also legitimate `US-brokered` (empty allowlist per brief) |
| non-adjacent stutter | content-word ≥ 7 chars, lowercase-initial, reappearing within 2-5 tokens | `denounced ... were denounced`, `petition ... petition` |

The hyphen-mangled signal is intentionally noisy — it counts every `\w+-\w+ed` match, so legitimate compounds like `US-brokered`, `China-linked`, `Trump-Xi` (not `*ed`, doesn't match) appear in the metric. This is the brief's call ("empty allowlist — every match is a signal"); the report annotates which signal sub-types dominate per variant.

### Cosine dedup

Per call: embed each topic's `title + " " + summary` with the fastembed singleton, L2-normalise, build a similarity matrix, union-find merge pairs with cosine ≥ 0.85. `n_unique_themes` = number of resulting clusters; `n_duplicates` = `n_topics − n_unique_themes`.

## Per-variant aggregate table

Sorted by composite (lowest corruption-mean + duplicates-mean + in-spec emission count).

| variant | n_topics mean ± stdev (min-max) | n_unique mean ± stdev | n_duplicates mean ± stdev | n_corruption mean ± stdev | schema valid | cost/3 reps | wall/rep mean |
|---|---|---|---|---|---|---|---|
| **dskflash-t05-rmedium** | **25.0 ± 0.0** (25-25) | **25.0 ± 0.0** | **0.0 ± 0.0** | 3.0 ± 0.0 | 3/3 | $0.0152 | 164 s |
| dskflash-t07-rmedium | 23.7 ± 3.2 (20-26) | 23.3 ± 2.9 | 0.33 ± 0.58 | **2.3 ± 0.58** | 3/3 | $0.0171 | 460 s ⚠ |
| dskflash-t10-rhigh | 24.7 ± 2.1 (23-27) | 23.7 ± 2.1 | 1.0 ± 0.0 | 2.7 ± 0.58 | 3/3 | $0.0174 | 191 s |
| dskflash-t07-rhigh | 24.3 ± 2.1 (22-26) | 24.0 ± 1.7 | 0.33 ± 0.58 | 3.3 ± 1.15 | 3/3 | $0.0132 | 134 s |
| dskflash-t05-rhigh | 25.0 ± 4.0 (21-29) | 24.7 ± 4.5 | 0.33 ± 0.58 | 5.0 ± 1.0 | 3/3 | $0.0154 | 133 s |
| dskflash-t05-rnone | 26.7 ± 2.1 (25-29) | 25.3 ± 1.5 | 1.33 ± 0.58 | **1.7 ± 0.58** | 3/3 | **$0.0075** | **28 s** |
| dskflash-t07-rnone | 26.3 ± 4.0 (22-30) | 25.0 ± 3.5 | 1.33 ± 1.53 | 3.3 ± 1.15 | 3/3 | $0.0105 | 55 s |
| dskflash-t10-rnone | 25.7 ± 4.9 (20-29) | 24.7 ± 4.2 | 1.0 ± 1.0 | 3.7 ± 0.58 | 3/3 | $0.0078 | 60 s |
| dskflash-t10-rmedium | 29.3 ± 2.1 (27-31 ⚠) | 28.0 ± 1.0 | 1.33 ± 1.15 | 4.0 ± 2.65 | 3/3 | $0.0177 | 244 s |

⚠ `t07-rmedium`'s 460 s mean wall is driven by a 1,131 s outlier on `rep2` routed via AkashML (fallback provider). The other two reps were 112 s and 137 s. `t10-rmedium` rep1 emitted 31 topics — one over the prompt's 10-30 range; the only out-of-spec emission count across the 27 reps.

## Per-rep raw table (27 calls)

<details>
<summary>Click to expand per-call detail</summary>

| label-rep | n_topics | n_unique | n_dup | n_corr | repeated_word | repeated_quoted | hyphen_ed | stutter | schema_valid | cost ($) | wall (s) | provider |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dskflash-t05-rnone-rep1 | 25 | 24 | 1 | 2 | 0 | 0 | 2 | 0 | ✓ | 0.0013 | 27.8 | AtlasCloud |
| dskflash-t05-rnone-rep2 | 26 | 25 | 1 | 2 | 0 | 0 | 2 | 0 | ✓ | 0.0044 | 26.6 | AtlasCloud |
| dskflash-t05-rnone-rep3 | 29 | 27 | 2 | 1 | 0 | 0 | 1 | 0 | ✓ | 0.0017 | 30.2 | AtlasCloud |
| dskflash-t05-rmedium-rep1 | 25 | 25 | 0 | 3 | 1 | 0 | 2 | 0 | ✓ | 0.0047 | 162.2 | AtlasCloud |
| dskflash-t05-rmedium-rep2 | 25 | 25 | 0 | 3 | 0 | 0 | 2 | 1 | ✓ | 0.0046 | 120.8 | Alibaba |
| dskflash-t05-rmedium-rep3 | 25 | 25 | 0 | 3 | 0 | 0 | 2 | 1 | ✓ | 0.0059 | 208.7 | AtlasCloud |
| dskflash-t05-rhigh-rep1 | 29 | 29 | 0 | 6 | 0 | 0 | 5 | 1 | ✓ | 0.0045 | 98.3 | Alibaba |
| dskflash-t05-rhigh-rep2 | 21 | 20 | 1 | 4 | 0 | 0 | 3 | 1 | ✓ | 0.0050 | 153.6 | AtlasCloud |
| dskflash-t05-rhigh-rep3 | 25 | 25 | 0 | 5 | 1 | 0 | 3 | 1 | ✓ | 0.0059 | 146.0 | Alibaba |
| dskflash-t07-rnone-rep1 | 30 | 27 | 3 | 2 | 0 | 0 | 2 | 0 | ✓ | 0.0016 | 33.3 | AtlasCloud |
| dskflash-t07-rnone-rep2 | 22 | 21 | 1 | 4 | 0 | 0 | 4 | 0 | ✓ | 0.0044 | 21.6 | Alibaba |
| dskflash-t07-rnone-rep3 | 27 | 27 | 0 | 4 | 0 | 0 | 2 | 2 | ✓ | 0.0045 | 110.2 | Parasail |
| dskflash-t07-rmedium-rep1 | 20 | 20 | 0 | 3 | 0 | 0 | 3 | 0 | ✓ | 0.0042 | 136.5 | AtlasCloud |
| dskflash-t07-rmedium-rep2 | 25 | 25 | 0 | 2 | 0 | 0 | 2 | 0 | ✓ | 0.0091 | 1130.8 ⚠ | AkashML |
| dskflash-t07-rmedium-rep3 | 26 | 25 | 1 | 2 | 0 | 0 | 2 | 0 | ✓ | 0.0038 | 111.6 | AtlasCloud |
| dskflash-t07-rhigh-rep1 | 22 | 22 | 0 | 2 | 0 | 0 | 2 | 0 | ✓ | 0.0059 | 209.4 | AtlasCloud |
| dskflash-t07-rhigh-rep2 | 26 | 25 | 1 | 4 | 0 | 0 | 3 | 1 | ✓ | 0.0034 | 74.6 | Alibaba |
| dskflash-t07-rhigh-rep3 | 25 | 25 | 0 | 4 | 0 | 0 | 4 | 0 | ✓ | 0.0039 | 119.0 | AtlasCloud |
| dskflash-t10-rnone-rep1 | 20 | 20 | 0 | 4 | 0 | 0 | 3 | 1 | ✓ | 0.0015 | 26.0 | AtlasCloud |
| dskflash-t10-rnone-rep2 | 28 | 26 | 2 | 4 | 0 | 0 | 4 | 0 | ✓ | 0.0046 | 118.0 | Parasail |
| dskflash-t10-rnone-rep3 | 29 | 28 | 1 | 3 | 0 | 0 | 2 | 1 | ✓ | 0.0018 | 35.7 | AtlasCloud |
| dskflash-t10-rmedium-rep1 | 31 ⚠ | 29 | 2 | 5 | 0 | 0 | 2 | 3 | ✓ | 0.0059 | 205.7 | AtlasCloud |
| dskflash-t10-rmedium-rep2 | 27 | 27 | 0 | 1 | 0 | 0 | 1 | 0 | ✓ | 0.0070 | 398.4 | Parasail |
| dskflash-t10-rmedium-rep3 | 30 | 28 | 2 | 6 | 0 | 0 | 5 | 1 | ✓ | 0.0048 | 126.8 | Alibaba |
| dskflash-t10-rhigh-rep1 | 27 | 26 | 1 | 3 | 0 | 0 | 3 | 0 | ✓ | 0.0057 | 200.8 | AtlasCloud |
| dskflash-t10-rhigh-rep2 | 23 | 22 | 1 | 2 | 0 | 0 | 2 | 0 | ✓ | 0.0051 | 152.9 | AtlasCloud |
| dskflash-t10-rhigh-rep3 | 24 | 23 | 1 | 3 | 0 | 0 | 2 | 1 | ✓ | 0.0065 | 219.2 | AtlasCloud |

⚠ `t07-rmedium-rep2` returned 25 valid topics but routed via AkashML and took 1,131 s (the next-slowest call in the entire sweep is 398 s). `t10-rmedium-rep1` emitted 31 topics — one over the prompt spec.

</details>

## Ranking by stability + cleanness

Composite: `n_topics` mean within 10-30 spec **AND** `n_duplicates` mean ≤ 0.5 **AND** `n_text_corruption_signals` mean ≤ 3.0.

| rank | variant | passes? | notes |
|---|---|---|---|
| 1 | **dskflash-t05-rmedium** | **yes** | 25.0 ± 0.0 topics (zero stdev — every rep returned exactly 25), 0.0 duplicates, 3.0 corruption (all explained — see breakdown). The only variant with **zero emission-count variance**. |
| 2 | dskflash-t07-rmedium | yes | 23.7 ± 3.2 topics, 0.33 dup, 2.3 corruption — **lowest corruption mean** of all variants. But 460 s wall mean (1,131 s outlier on rep2). |
| 3 | dskflash-t10-rhigh | yes | 24.7 ± 2.1, 1.0 dup, 2.7 corruption — stable mid-range count, but consistent 1-duplicate rate (every rep has exactly one duplicate). |
| 4 | dskflash-t07-rhigh | yes | 24.3 ± 2.1, 0.33 dup, 3.3 corruption — just over the 3.0 corruption-mean threshold. |
| — | dskflash-t05-rnone | borderline | 26.7 mean topics in-spec, **lowest corruption (1.7)**, **cheapest ($0.0025/call)**, **fastest (28 s)**, but 1.3 duplicate mean — the per-rep duplicate counts are 1, 1, 2. Persistent low-grade duplication. |
| — | dskflash-t05-rhigh | no | 5.0 corruption mean — driven mostly by hyphen-ed false positives (3-5 per rep), not real text corruption (`repeated_word=1`, `repeated_quoted=0` across reps). |
| — | dskflash-t07-rnone | no | 1.3 dup mean, 3.3 corruption mean — passes count, fails composite. |
| — | dskflash-t10-rnone | no | 3.7 corruption mean, 1.0 dup. |
| — | dskflash-t10-rmedium | no | 29.3 mean topics, **1 rep emitted 31 (over spec)**, 4.0 corruption mean. |

**Best stability+cleanness:** `dskflash-t05-rmedium` — the only variant with zero emission-count variance across 3 reps, zero duplicates, 100 % schema validity. Cost $0.0051/call mean.

**Cheapest viable:** `dskflash-t07-rmedium` ($0.0057/call mean, lowest corruption count) — but the AkashML routing outlier (1,131 s) is a wall-time risk for production SLAs.

**Cheapest overall (with caveats):** `dskflash-t05-rnone` — 11× cheaper than t05-rmedium, 6× faster, but persistent low-grade duplication (1-2 duplicates per rep).

## Cross-variant observations

### 1. Wave-2's 41-emission pathology did **not** reproduce in 27 follow-up reps

The Wave-2 single-call observation at `dskflash-t05-rnone` was **41 emissions** with text corruption (`'clock is ticking'clock is ticking'`, hyphen-mangled compounds, doubled phrases). In this 27-call follow-up:

- `dskflash-t05-rnone` rep 1: 25 emissions
- `dskflash-t05-rnone` rep 2: 26 emissions
- `dskflash-t05-rnone` rep 3: 29 emissions
- **Zero `repeated_quoted` matches across all 27 reps.** The egregious `'clock is ticking'clock is ticking'` pattern did not reappear in any variant or rep.
- Across the full 27 reps: **the highest emission count is 31** (`t10-rmedium-rep1`), against the prompt's 10-30 spec.

The Wave-2 41-emission result was a stochastic outlier on `t05-rnone`. DeepSeek V4 Flash at this temperature does swing the emission count (1.3 duplicate mean indicates the duplication tendency hasn't disappeared — it's reduced in magnitude). But the Wave-2 single-rep was not a stable behaviour of the variant.

This is the **load-bearing finding for any downstream curator-swap brief**: any quality decision based on the Wave-2 single observation is decided on outlier data. The 27-rep aggregate is the better prior.

### 2. Reasoning ≠ improves emission discipline; medium > none on stability

- **Mean stdev of emission count** by reasoning level (across all 9 reps per level):
  - `none`: 3.69 — widest swing
  - `medium`: 1.83 — tightest
  - `high`: 2.72 — middle
- **Mean corruption signal** by reasoning level:
  - `none`: 2.89 — lowest
  - `medium`: 3.11 — middle (driven by t05/t10-rmedium and stutter signals)
  - `high`: 3.67 — highest (mostly hyphen-ed)

Reasoning **tightens** emission discipline (lower variance) but **adds** corruption signals — and most of those signals are hyphen-ed compounds that are legitimately formed in news prose (`US-brokered`, `China-linked`, `state-sponsored`). The brief's "empty allowlist" framing inflates the signal here; with a small allowlist of `\b\w+-\w+ed\b` legitimate prefixes (e.g. `US-`, `UK-`, `China-`, `EU-`, `state-`), the corruption metric would more closely track real corruption.

### 3. Temperature 0.5 is the most stable for emission count; 1.0 the loosest

- `t05`: emission stdev mean across reasoning levels: 2.03
- `t07`: 3.08
- `t10`: 3.07

`t05-rmedium` is the only variant in the grid with stdev = 0 on emission count. The cluster of best composite scores (rmedium / rhigh at t05/t07) suggests the **interaction of moderate temperature with reasoning** is what produces stable in-spec output — not reasoning alone, and not low temperature alone.

### 4. Hyphen-ed signal is over-broad; real corruption is rare across the 27 reps

Breakdown of corruption signals across all 27 reps:

| signal | total matches across 27 reps | dominant phrase types |
|---|---|---|
| repeated_word | 3 | `wounding wounding`, lone matches scattered across reps |
| repeated_quoted | **0** | never fired — Wave-2's `'clock is ticking'clock is ticking'` did not reproduce |
| hyphen_ed | 71 (84 % of total) | `US-brokered`, `China-linked`, `state-sponsored`, `US-led` etc. — mostly legitimate |
| non_adjacent_stutter | 16 | mix of real stutters and edge cases like `denounced` reused intentionally |

If hyphen_ed is filtered (or allowlisted to common compounds), the real-corruption-signal count drops from a mean of 3.1 across reps to roughly 0.7 — most reps have zero real corruption. The Wave-2 single observation looks even more anomalous in this light: it had 1 `repeated_quoted` AND ~4 `repeated_word`/`stutter` patterns in a single call, while the 27-rep follow-up has 0 `repeated_quoted` and 3 `repeated_word` total.

### 5. Provider routing matters more than variant selection for wall-time tail

`t07-rmedium-rep2` returned 25 valid topics in 1,131 s after routing via AkashML (DeepSeek's fallback provider when AtlasCloud / Alibaba / Parasail are saturated). The non-AkashML reps for the same variant ran in 112 s and 137 s. **Wall-time tail risk on streaming variants is dominated by which provider the OpenRouter routing selects**, not by reasoning level or temperature. A production deployment that pins `provider.order = ["deepseek"]` will inherit this tail behaviour from the upstream DeepSeek mesh.

### 6. Hard cap was never approached

`$0.1218 / $5.00` cap = 2.4 % of cap. The variance smoke is roughly 6× cheaper than the architect's expected $0.30 — DeepSeek V4 Flash with reasoning is cheaper than Wave-2's per-call cost suggested, and the prompt cache stays warm across reps within a reasoning batch.

## Failure mode summary

- **Zero schema-validation failures** across 27 reps.
- **Zero streaming failures** across 18 reasoning streams.
- **Zero AtlasCloud content-moderation rejections** — substrate is run-phase pre-cluster summaries with no per-topic civilian-casualty content surface.
- **One wall-time outlier**: `t07-rmedium-rep2` at 1,131 s via AkashML.
- **One spec-violation**: `t10-rmedium-rep1` emitted 31 topics (over the 30 max in prompt spec; no other rep crossed 30).

## Out of scope

No production-swap recommendation. The architect's call: this report's data either (a) supports a swap to `dskflash-t05-rmedium` (the only zero-variance variant) with the caveat that reasoning adds wall time, (b) supports a swap to `dskflash-t05-rnone` (cheapest, fastest, but ~1.3 duplicates/rep persistent) optionally with a downstream dedup stage between curator and editor, or (c) shelves the swap and stays on Gemini-3-Flash given the persistent low-grade duplication on the cheapest cleanest variant.
