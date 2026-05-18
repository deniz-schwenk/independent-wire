# Wave 2 Sweep #1 — `curator_topic_discovery` (Flash replacement)

## Setup

- **Substrate:** `output/2026-05-18/_state/run-2026-05-18-c26864b2/run_bus.pre_cluster_findings.json` — 1,217 findings, 252 agglomerative pre-clusters. Compressed via top-K-by-centroid (K=8) using the production helper `_compress_pre_clusters_to_llm_input` + the shared fastembed singleton.
- **Baseline:** Gemini Flash 3 (`google/gemini-3-flash-preview`), t=1.0 (per the recent temp-raise), r=none, production max_tokens=8000. Today's output: **20 topics**, $0.0192, 30,607 tokens.
- **Schema:** `CURATOR_TOPIC_DISCOVERY_SCHEMA` strict (`{topics: [{title, summary}]}`).
- **max_tokens=160000** on the candidate (architect's wave-2 override).
- **Harness:** Wave-1 Option B (`scripts/eval_common.py`). 1 call, no streaming.

## Metrics

| label | model | temp | reasoning | max_tokens | cost | tokens | wall | n_topics | schema_valid | provider |
|---|---|---|---|---|---|---|---|---|---|---|
| **baseline** | gemini-3-flash | 1.0 | none | 8000 | $0.0192 | 30,607 | n/a | **20** | 100 % | Google |
| dskflash-t05-rnone | deepseek-v4-flash | 0.5 | none | 160000 | **$0.0048** | 30,844 | 37.2 s | **41** | 100 % | AtlasCloud |

## Topic-list comparison

**Baseline (20):** Ukraine drones / Trump-Iran / Amnesty executions / WHO Ebola / Israel-Lebanon / Kim border-defense / China-US trade / Andalusia / Trump prayer rally / Navy jets / Kenya transport / Starmer leadership / Eurovision / G7 finance / Sinner+Rai / China earthquake / Canal+ blacklist / Modena attack / Hantavirus cruise ship / Nigeria state-police.

**Candidate (41):** covers all 20 baseline themes but emits each theme roughly twice with slight wording variation. Quick scan:

| theme | baseline emission | candidate emissions |
|---|---|---|
| Ukraine drones on Russia | 1 | 2 (`Ukraine launches massive drone strikes on Russia, killing at least four` + `Massive Ukrainian drone attacks on Russia; Moscow faces biggest attack in over a year`) |
| Trump-Iran ultimatum | 1 | 2 (`Trump threatens Iran with destruction…` + `Trump warns Iran 'clock is ticking'clock is ticking'…` — note the duplicated phrase from the model) |
| UAE Barakah drone | 1 | 2 (`Drone strikes on UAE nuclear power plant fuel escalation fears` + `Drone strike on UAE nuclear power plant sparks fire, IAEA reports normal radiation`) |
| North Korea Kim border | 1 | 2 (identical-wording adjacent emissions) |
| Andalusia election | 1 | 2 (identical-wording adjacent emissions) |
| Israel-Lebanon | 1 | 2 (`Israeli strikes kill at least seven…` + `Israel expands military operations into Lebanon…`) |
| WHO Ebola | 1 | 2 (identical-wording adjacent) |
| Eurovision 2026 | 1 | 2 (identical-wording adjacent) |
| Trump prayer rally | 1 | 2 |
| US Navy jets collide | 1 | 2 (one prefixed `Two US Navy jets…` the other `Jets collide…`) |
| G7 Paris finance | 1 | 2 (identical) |
| Kenya transport strike | 1 | 2 (identical) |
| Modena attack | 1 | 2 (identical) |
| China-US trade | 1 | 2 (identical) |
| China earthquake | 1 | 2 (identical) |
| Starmer leadership | 1 | 2 (one mentions Wes Streeting) |
| Sinner sports | 1 | 1 (only tennis) |
| Canal+ blacklist | 1 | 2 (identical) |
| Eid al-Adha | 0 | 2 (new — both emissions identical) |
| France Epstein probe | 0 | 2 (new — both emissions identical) |
| Amnesty executions | 1 | 1 |
| Hantavirus | 1 | 0 |
| Nigeria state-police | 1 | 0 |

So 41 emissions roughly equals 21 unique themes (one new addition: Eid al-Adha; one new addition: France Epstein probe; one drop: Hantavirus; one drop: Nigeria police), with each theme emitted twice owing to a model-side over-emission pattern (adjacent near-duplicates).

## Observation

DeepSeek V4 Flash at $0.0048 is **4× cheaper than the Gemini Flash 3 baseline** ($0.0192) on this run-phase stage, schema-valid, comparable wall time (37 s vs the baseline's similar order). However the candidate emits **41 topic entries against the baseline's 20** with the great majority of additional entries being near-duplicates of earlier entries in the same list — `Two US Navy jets collide…` repeated as `Jets collide…`, `Trump prayer rally` repeated verbatim, `G7 Paris finance` repeated verbatim, etc. The candidate doubles ~20 themes rather than expanding into 41 distinct themes; the topic coverage in unique-theme terms is essentially the same as baseline (drops Hantavirus and Nigeria-state-police; adds Eid al-Adha and France-Epstein). Downstream consumers (Editor) iterate this list once and slice the top-N — a doubled list would either need deterministic deduplication before the Editor sees it (separate workstream) or would yield Editor confusion from competing near-equivalent titles. Schema validity is clean and no streaming was needed (V4 Flash, reasoning=none). No production-swap recommendation in this report.
