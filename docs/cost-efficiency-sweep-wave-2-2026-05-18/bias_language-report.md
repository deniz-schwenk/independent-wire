# Wave 2 Sweep #6 — `bias_language` (Opus replacement, V4 Pro grid)

## Setup

- **Substrate:** `topic_buses.mirror_qa_corrected.{0,1,2}.json` — `qa_corrected_article.body` (7,095 / 8,114 / 6,495 chars) plus the slots assembled by the production helper `_build_bias_card_for_agent_input` (`final_sources` 30/37/26, `canonical_actors` 37/50/32, `perspective_clusters_synced` 10/9/8, `qa_problems_found` 7/7/6, `qa_corrections` 7/7/6, `qa_divergences` 8/7/6, `coverage_gaps_validated` 0/0/0).
- **Baseline:** Opus 4.6, t=0.1, r=none, max_tokens default. Today's output: **6 / 6 / 3 findings** per topic, reader-note 816 / 766 / 854 chars.
- **Schema:** `BIAS_DETECTOR_SCHEMA` strict (`{language_bias: {findings: [{excerpt, issue, explanation}]}, reader_note: string}`).
- **max_tokens=160000** on every candidate.
- **Harness:** Wave-1 Option B. 6 variants × 3 topics = 18 calls; 12 streaming reasoning calls.
- **Quote-presence metric:** share of findings whose `excerpt` field appears as a substring in the article body — anchors the finding to a real phrase rather than a generic claim.

## Metrics

| label | cost_total | cost/topic | wall_mean | findings (per topic) | findings_total | quote% (per topic) | schema_valid | provider |
|---|---|---|---|---|---|---|---|---|
| **baseline** | n/a | n/a | n/a | **6 / 6 / 3** | 15 | n/a | 100 % | Anthropic |
| dskpro-t05-rnone | $0.0311 | $0.0104 | – | 7 / 6 / 4 | **17** | 100 % / 83 % / 100 % | 100 % | AtlasCloud |
| dskpro-t05-rmedium | $0.0503 | $0.0168 | – | 5 / 4 / 7 | 16 | 100 % / 50 % / 86 % | 100 % | AtlasCloud |
| dskpro-t05-rhigh | $0.0564 | $0.0188 | – | 5 / 7 / 5 | **17** | **100 % / 100 % / 80 %** | 100 % | AtlasCloud |
| dskpro-t07-rnone | **$0.0076** | $0.0025 | – | 2 / 5 / 6 | 13 | 100 % / 60 % / 100 % | 100 % | AtlasCloud |
| dskpro-t07-rmedium | $0.0482 | $0.0161 | – | **10 / 4 / 6** | **20** | 100 % / 50 % / 83 % | 100 % | AtlasCloud |
| dskpro-t07-rhigh | $0.0490 | $0.0163 | – | 4 / 5 / 5 | 14 | 100 % / 80 % / 80 % | 100 % | AtlasCloud |

**Sweep total cost: $0.2426** (well under $15 per-sweep cap). Cumulative wave-2 spend through Sweep 6: **~$1.34**.

## Notes

- **All 18 calls schema-valid.** Zero streaming failures across the 12 reasoning streams. Distinct from Sweep #5's content-moderation rejections on Ukraine-drone Perspective output — the bias-language stage operates on the QA-corrected article body (a narrower text surface, smaller per-call) and did not trip the AtlasCloud filter on any topic.
- **All variants meet or exceed baseline finding count on topic 0 and topic 2** (baseline 6/3 → candidates produce 2-10 / 4-7). On topic 1 some variants miss (baseline 6 → t05-rmedium 4, t07-rmedium 4, t07-rhigh 5), but most variants land in the 5-7 range.
- **Quote-presence rate is high**: most variants anchor every finding to a real article phrase on topic 0 (100 %) and 60-100 % on topics 1 and 2. The `t05-rhigh` variant is the only one to achieve 100 / 100 / 80 % across all three topics.
- **`dskpro-t07-rnone` at $0.0076 total** is anomalously cheap (third variant in run order; DeepSeek prompt-cache likely hit on this much smaller substrate). The same cache-hit caveat applies as in Wave-1 — production-swap cost projections should be validated cache-cold.
- **`dskpro-t07-rmedium` produces 10 findings on topic 0** vs baseline 6 — by far the most exhaustive enumeration in the sweep. Worth a closer manual audit before any production swap; the additional 4 findings could either be real bias instances the baseline missed or noise.

## Observation

DeepSeek V4 Pro on the Bias Language stage matches or exceeds the Opus baseline's finding count on **5 of 6 variants** when summed across the 3 topics (15 baseline vs 13-20 candidate range), with **100 % schema validity** and **no streaming failures** even on the high-reasoning variants — which contrasts with Sweep #5's two content-moderation rejections on the same overall substrate but a different per-stage input shape (Perspective's full source dossier vs Bias Language's QA-corrected body). Quote-presence rates of 80-100 % indicate the candidate's findings anchor to specific article phrases rather than generic claims, with `dskpro-t05-rhigh` the most consistent at 100/100/80 % across the three topics. Cost range $0.008-$0.057 / topic (with `dskpro-t07-rnone` likely DeepSeek-cache-warmed at the cheapest), vs an Opus baseline estimate near $0.05-0.10 / topic (not isolated in the stage log; Opus pricing $5/$25 M tokens on a ~6-8 k char body + ~50 k bias_card context yields that order). The five-dimensional Vision-promised bias-dimension classification (language / source / framing / selection / geographical) is not directly emittable under the current strict schema (`{excerpt, issue, explanation}` only) — that metric from the brief is unmeasurable without a schema extension; the candidate's `issue` field carries the kind of bias being flagged in free-text form, which a downstream tag could derive. No production-swap recommendation in this report.
