# Wave 2 Sweep #5 — `perspective` (Opus replacement, V4 Pro grid)

## Setup

- **Substrate:** `topic_buses.normalize_pre_research.{0,1,2}.json` — passed to the wrapper read-set: `editor_selected_topic`, `final_sources` (30/37/26), `canonical_actors_{stated,reported,mentioned}` (26+13+5 / 34+28+0 / 18+18+0), `merged_preliminary_divergences` (14/17/11), `merged_coverage_gaps` (14/15/13).
- **Baseline:** Opus 4.6, t=0.1, r=none, max_tokens default. Today's output: **10 / 9 / 8 position clusters** per topic, 5 / 5 / 5 missing-positions.
- **Schema:** `PERSPECTIVE_SCHEMA` strict (`{position_clusters: [{position_label, position_summary, source_ids, stated, reported, mentioned}], missing_positions: [{type, description}]}`).
- **max_tokens=160000** on every candidate.
- **Harness:** Wave-1 Option B. 6 variants × 3 topics = 18 calls; 12 streaming reasoning calls.

## Metrics

| label | cost_total | cost/topic | wall_mean | clusters (per topic) | clusters_mean | actor coverage (per topic) | schema_valid | provider |
|---|---|---|---|---|---|---|---|---|
| **baseline** | n/a | n/a | n/a | **10 / 9 / 8** | **9.0** | — | 100 % | Anthropic |
| dskpro-t05-rnone | $0.1658 | $0.0553 | – | **8 / 7 / 7** | 7.3 | 76 % / 64 % / 78 % | **100 %** | AtlasCloud |
| dskpro-t05-rmedium | $0.0997 | $0.0332 | – | 7 / 5 / 6 | 6.0 | 51 % / 56 % / 69 % | 100 % | AtlasCloud |
| dskpro-t05-rhigh | $0.0793 | $0.0264 | – | 8 / **0** / 7 ⚠ | 5.0 | 81 % / 0 % / 78 % | 67 % | AtlasCloud |
| dskpro-t07-rnone | **$0.0615** | $0.0205 | – | **9** / 6 / 7 | 7.3 | 54 % / 52 % / 75 % | 100 % | AtlasCloud |
| dskpro-t07-rmedium | $0.1148 | $0.0383 | – | 8 / 7 / 6 | 7.0 | 65 % / 44 % / 75 % | 100 % | AtlasCloud |
| dskpro-t07-rhigh | $0.0690 | $0.0230 | – | 7 / **0** / 6 ⚠ | 4.3 | 78 % / 0 % / 75 % | 67 % | AtlasCloud |

**Sweep total cost: $0.5900** (under $15 cap). Cumulative wave-2 spend through Sweep 5: ~$1.00.

## Failures

| variant | topic | error |
|---|---|---|
| dskpro-t05-rhigh | 1 | `APIError: Upstream error from Alibaba: Output data may contain inappropriate content.` (0 s wall, $0.00 — AtlasCloud rejected the output mid-stream before any tokens reached the response) |
| dskpro-t07-rhigh | 1 | Same — content-moderation rejection |

Both failures are **only on topic 1 (Ukraine drone strikes on Moscow — civilian casualties / war reporting)** and **only on the `reasoning=high` streaming variants**. Non-reasoning and `reasoning=medium` variants on the same topic-1 substrate succeeded (7 / 5 / 7 clusters respectively). Distinct from the Wave-1 Sweep #3 "buffer-then-silent" failure mode — this one is an explicit synchronous error from the provider returning before any content streamed. The harness caught it cleanly and continued with the remaining variants.

## Qualitative cluster-label spot-check — topic 0 (Trump-Iran)

| baseline cluster (10) | candidate `dskpro-t05-rnone` cluster (8) | match? |
|---|---|---|
| Iran must accept US terms immediately or face total destruction | Iran must accept US demands immediately or face total destruction | ✓ verbatim-equivalent |
| Iran's proposals are responsible / US is the obstacle | US' maximalist demands / lack of concessions / impasse | ✓ same position |
| Iran retains military capability / will forcefully resist | Iran will militarily resist the US naval blockade / retaliate | ✓ |
| Drone attacks represent dangerous escalation / nuclear safety / regional sovereignty | Drone attacks on Saudi Arabia and UAE represent dangerous escalation / sovereignty / IHL | ✓ |
| Strait of Hormuz blockade / catastrophic economic consequences / diplomacy | Hormuz blockade / wider conflict / global economic disruption / diplomacy | ✓ |
| Trump's threats of civilizational destruction / violate IHL / urgent global action | Trump's threats of civilizational destruction / IHL / urgent global action | ✓ verbatim-equivalent |
| US domestic opposition / military escalation / congressional authorization required | Sending US troops / domestic political backlash / constitutional crisis | ✓ same position, slightly different framing |
| (new in baseline) Hawkish US voices / target Iran's energy infrastructure | — (missing in candidate) | absent |
| (new in baseline) Israel completed military preparations / ready to act | — (missing in candidate) | absent |
| (new in baseline) Regional mediators (Pakistan, Russia) / facilitate diplomatic compromise | — (missing in candidate) | absent |
| — | (new in candidate) Conflict destabilizing Middle East / US military presence is the root cause | added; defensible |

Cluster *positions* the candidate produces map cleanly onto the baseline's editorial divisions; the candidate omits 3 of the baseline's 10 clusters (Hawkish-US-voices, Israeli-military-prep, Regional-mediators) and adds 1 (Middle-East-destabilization). Net: 7 of 8 candidate clusters have a direct baseline counterpart with similar position language. Actor coverage 76 % on this topic (20 of 26 input actor-ids land in at least one cluster's stated/reported/mentioned sub-list).

## Observation

DeepSeek V4 Pro on the Perspective stage produces **cluster labels that map cleanly to the baseline's editorial divisions** (verbatim-equivalent on the dominant clusters, with the candidate omitting 1-3 of the baseline's 8-10 clusters per topic and occasionally adding 1 new defensible cluster). The cluster *count* is 7.3 mean on the cheapest 100%-valid variant (`dskpro-t05-rnone`) vs baseline mean 9.0 — about 19 % shy of baseline. Actor coverage hits 64-78 % on the rnone variants (i.e. 64-78 % of input canonical-actor IDs land in at least one cluster's stated/reported/mentioned sub-list) — the baseline coverage isn't isolated in stage logs but is structurally close to 1.0 given Opus' habit of exhaustive enumeration; the candidate omits a real fraction of input actors from any cluster reference. Cost range $0.02-$0.06 / topic vs an Opus baseline near $0.10-0.20 (not isolated in the stage log) — ~3-10× cheaper. **Two streaming-high-reasoning variants hit a provider-side content-moderation rejection on topic 1's Ukraine drone substrate** ("Output data may contain inappropriate content" — AtlasCloud upstream), reducing those two variants to 2/3 successful topics. This is a new failure mode vs Wave-1 (which only saw streaming-protocol issues, not content rejections). The non-reasoning and medium-reasoning variants on the same substrate succeeded; the content filter appears specifically sensitive to whatever the high-reasoning trace produces on war/civilian-casualty content. No production-swap recommendation in this report.
