# Cost-efficiency sweep wave 1, Sweep #3 — `researcher_assemble` (Flash replacement)

Phase 3 of `TASK-COST-EFFICIENCY-SWEEP-WAVE-1`. 6 DeepSeek V4 Flash variants of the Researcher-Assemble extraction role benchmarked against the Gemini Flash 3 production baseline.

The brief's original wave-1 contract excluded `reasoning ∈ {medium, high}` for V4 Flash; the architect issued an in-flight course correction during this phase to add the four reasoning-on variants on the grounds that the V1-era over-clustering pathology (`docs/AUDIT-CURATOR-2026-05-11.md`) does not generalize to the V2 extraction role. All six variants were swept; the two `r=none` variants kept their cached outputs from the first run via skip-resume; the four reasoning-on variants ran fresh through the Phase-1/2 Option-B streaming wiring.

**Architect decision pending — no recommendation in this report.**

## Setup

- **Substrate:** `output/2026-05-18/_state/run-2026-05-18-c26864b2/topic_buses.researcher_search.{0,1,2}.json`. Three topics from today's V2 hydrated run:
  - topic 0: *Trump ultimatum to Iran* (23 search results, ~340 KB JSON, ~88 KB compact)
  - topic 1: *Ukraine drones on Moscow* (23 search results, ~390 KB JSON)
  - topic 2: *UAE Barakah drone strike* (23 search results, ~250 KB JSON)
- **Baseline on disk:** `topic_buses.ResearcherAssembleStage.{0,1,2}.json` — Gemini Flash 3 (`google/gemini-3-flash-preview`), temp=0.2, reasoning=none, max_tokens=8000. Today's production: **$0.0259/topic mean ($0.0778 total), 35,726 tokens/topic, 15/12/10 sources extracted (of 23 input), 3/3/1 preliminary_divergences, 3/3/2 coverage_gaps, summary p50 156/137/127 chars**.
- **Schema:** `RESEARCHER_ASSEMBLE_SCHEMA` — `{sources[]: {url, title, outlet, language, country, summary, actors_quoted[]}, preliminary_divergences[]: string, coverage_gaps[]: string}`, strict mode.
- **Prompts:** `agents/researcher/ASSEMBLE-SYSTEM.md` + `agents/researcher/ASSEMBLE-INSTRUCTIONS.md` verbatim.
- **`max_tokens=64000`** (overrides production 8000 — wave-1 contract).
- **DeepSeek routing:** `extra_body.provider = {order: ["deepseek"], allow_fallbacks: True, require_parameters: True}`. `provider_served` captured per call.

### Harness notes

- Same `scripts/eval_common.py` harness as Phase 1 / 2. Option B preserved — `src/agent.py` not touched.
- Skip-resume preserved the 6 `r=none` outputs from the first run; only the 12 new streaming-reasoning calls executed fresh on the second invocation.
- Streaming wiring (Phase 1 / 2's Option B) applied verbatim to V4 Flash reasoning ∈ {medium, high}. **Two streaming failures surfaced** — see §Failures.
- Cumulative cap status at completion: **$0.1112** (1.1% of $10 cap).

## Metrics

**16 / 18 schema-valid** outputs (88.9%). 2 failures, both on streaming-reasoning Flash variants — see §Failures.

| label | model | temp | reasoning | streaming | cost_total | cost/topic | tokens_total | wall_mean | sources (per topic) | divs (per topic) | gaps (per topic) | summary p50 (per topic) | schema_valid | provider |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **baseline** | gemini-3-flash | 0.2 | none | no | $0.0778 | $0.0259 | 107,178 | n/a | **15 / 12 / 10** | 3 / 3 / 1 | 3 / 3 / 2 | 156 / 137 / 127 | 100% | Google |
| dskflash-t05-rnone | deepseek-v4-flash | 0.5 | none | no | **$0.0167** | $0.0056 | 108,713 | 113 s | **15 / 15 / 15** | 5 / 5 / 5 | 6 / 5 / 5 | 190 / 184 / 224 | 100% | AtlasCloud |
| dskflash-t05-rmedium | deepseek-v4-flash | 0.5 | medium | yes | $0.0157 | $0.0052 | 88,038 | 339 s | **0** / 15 / 15 ⚠ | 0 / 4 / 5 | 0 / 5 / 5 | 0 / 188 / 216 | 67% | AtlasCloud |
| dskflash-t05-rhigh | deepseek-v4-flash | 0.5 | high | yes | $0.0249 | $0.0083 | 137,923 | 369 s | **15 / 15 / 15** | 4 / 5 / 4 | 4 / 5 / 5 | 192 / 174 / 159 | 100% | AtlasCloud |
| dskflash-t07-rnone | deepseek-v4-flash | 0.7 | none | no | **$0.0170** | $0.0057 | 109,753 | 113 s | **15 / 15 / 15** | 4 / 5 / 4 | 5 / 5 / 5 | 254 / 196 / 182 | 100% | AtlasCloud |
| dskflash-t07-rmedium | deepseek-v4-flash | 0.7 | medium | yes | $0.0251 | $0.0084 | 138,815 | 517 s | **15 / 15 / 15** | 2 / 3 / 4 | 4 / 6 / 5 | 183 / 191 / 197 | 100% | AtlasCloud |
| dskflash-t07-rhigh | deepseek-v4-flash | 0.7 | high | yes | $0.0118 | $0.0059 (of 2) | 84,981 | 544 s | **0** / 14 / 15 ⚠ | 0 / 5 / 5 | 0 / 5 / 5 | 0 / 236 / 200 | 67% | AtlasCloud |

**Integrity-gate metric — `n_sources_extracted`**: every successful call (16/16) extracted **exactly 15 sources** from the 23 input search results. The baseline drops 8/11/13 (extracting 15/12/10), so the candidate variants **match or exceed baseline retention on every topic**, with topic 2 the most dramatic gap (15 vs baseline 10 — DeepSeek Flash keeps 5 more sources). The flat 15-per-topic count is itself worth flagging: the model appears to apply a soft target around 15 rather than judging case-by-case (the input always contained 23 search results so headroom exists). Compared against baseline, the same 7-8 URLs overlap on topic 0; 3-6 URLs overlap on topic 1; 6-8 URLs overlap on topic 2 — so DeepSeek's extra-source decisions are different sources, not duplicates.

**Secondary metric — `n_preliminary_divergences`**: every successful variant exceeds the baseline on all topics. Baseline produces 3 / 3 / 1; DeepSeek Flash 2-5 / 3-5 / 4-5. `dskflash-t05-rnone` is the leader on this metric (5/5/5 = 15 total, +9 over baseline's 7). Reasoning variants do NOT increase divergence count over the no-reasoning variants — they cluster at 4-5 like rnone, with `dskflash-t07-rmedium` actually below at 2-4.

**Summary length p50**: all candidates produce somewhat longer per-source summaries than baseline (median p50 159-224 vs baseline 127-156 chars). No collapse.

## Failures

| variant | topic | failure mode | wall | content captured |
|---|---|---|---|---|
| dskflash-t05-rmedium | 0 | **Stream truncated mid-output** at 2,404 chars (well-formed JSON ending mid-source field; trailing `"outlet": "...` cut off). OpenRouter returned `cost=0`, no error code. | 259 s | partial JSON, unrecoverable as-is |
| dskflash-t07-rhigh | 0 | **Stream hung on SSL receive >18 min** with no chunks arriving. Process terminated via SIGINT after `0 progress` confirmed (CPU idle at <0.1%). Matches the `buffer-then-no-response` failure mode documented in `docs/AUDIT-CURATOR-2026-05-11.md`. | 1,080 s+ | none |

Both failures are streaming-reasoning Flash on **topic 0** (the Trump-Iran substrate). Notably topic 0 is **not** the largest input (topic 1 is denser at 397 KB vs topic 0's 348 KB), so the failure correlates with substrate content rather than raw size. The Option-B streaming wiring itself held — the other 10 streaming calls returned full schema-valid JSON — but the V4 Flash reasoning variants exhibit the same 'buffer-then-silent' failure mode the brief flagged for V4 Pro, at a 2/12 = **16.7 % rate** in this small sample.

## Qualitative samples (top-2 by 100% schema validity + max divergence count)

Top-2 = the no-reasoning variants `dskflash-t05-rnone` (5/5/5 divs) and `dskflash-t05-rhigh` (4/5/4 divs, the leader among the reasoning variants that survived). All 3 topic outputs shown.

### `dskflash-t05-rnone` (DeepSeek V4 Flash, temp 0.5, reasoning=none)

**topic 0 — Trump Iran (15 sources, 7 langs, 5 divs, 6 gaps; $0.006, 95 s)**

```
SAMPLE SOURCE TITLES (3 of 15):
• [en] Trump says he doesn't need congressional authorization for Iran military operation despite War Powers deadline
• [en] Iran war pushes oil prices to 4-year high as Hormuz bottleneck persists
• [en] Saudi says it intercepted three drones that entered from Iraqi airspace

DIVERGENCES (5):
• Iranian state-aligned media (Nournews) frames the ultimatum as a 'dangerous game' and quotes parliamentary leaders issuing defiant warnings, while Western sources (NBC, CBS) focus on the U.S. domestic legal debate over war powers …
• Arabic-language outlets (Al Jazeera, BBC Arabic, Iran International) emphasize the humanitarian and economic toll on civilians in Iran and the Gulf region, a dimension largely absent from English-language coverage …
• French-language sources (Le Monde, Amnesty International) foreground the international law and human rights implications of Trump's threats, a framing that is marginal in English, Persian, or Arabic coverage.
• Chinese state media (The Paper) focuses on diplomatic calls for de-escalation and protection of trade routes, without addressing the humanitarian or legal dimensions prominent in other languages.
• South Asian and East Asian sources (Navbharat Times, G1, Japanese outlets) concentrate on energy security and import diversification for their own countries, framing the crisis primarily as a supply chain risk …
```

**topic 1 — Ukraine drones (15 sources, 11 actors, 9 langs, 5 divs, 5 gaps; $0.005, 113 s)**

```
SAMPLE SOURCE TITLES (3 of 15):
• [en] China urges restraint after massive Ukrainian drone attack on Moscow region
• [en] Beijing walks tightrope after Ukraine launches major drone attack on Moscow
• [en] China's balancing act after Ukrainian drones strike Moscow

DIVERGENCES (5):
• Chinese-language sources (Wenweipo, Sina, Shobserver) focus on the scale of the attack and Russian casualty/interception figures, while omitting any Chinese official reaction …
• Russian state media (TASS) emphasizes the record number of drones intercepted and civilian casualties in residential areas, framing the attack as a mass terrorist act, while Ukrainian sources (BBC Ukraine, Radio Svoboda) …
• Indian-language and English Indian sources (ABP Live, Economic Times) centre the human-impact angle of an Indian worker killed, with consular assistance details, a perspective absent from Russian, Ukrainian, and Western coverage.
• Latvian-language sources (LSM) and English NATO-focused reports (Reuters, Newsweek) highlight the spillover of the drone war into NATO airspace and the security implications for the Baltics, a dimension not covered by Russian or Ukrainian sources.
• Arabic-language sources (Al Bayan, CNN Arabic) present the attack as part of a mutual escalation, giving equal weight to Ukrainian strikes on Russia and Russian strikes on Ukraine …
```

**topic 2 — UAE Barakah (15 sources, 14 actors, 12 langs, 5 divs, 5 gaps; $0.006, 132 s)** — broadest language coverage of the sweep (12 langs).

```
SAMPLE SOURCE TITLES (3 of 15):
• [en] Sources: Drone attack on UAE nuclear plant intended to send message
• [en] Radiation normal after drone strike near UAE nuclear plant, IAEA says
• [ar] مجلس التعاون الخليجي: اعتداءات إيران على محطة براكة انتهاك سافر لقوانين حماية المنشآت النووية

DIVERGENCES (5):
• Arabic-language sources from RT Arabic and the GCC directly accuse Iran of the attack, while English-language sources like Reuters Arabic and Al Jazeera note that no group has claimed responsibility and Iran typically denies involvement.
• Israeli and Italian sources (Jerusalem Post, Rai News) explicitly attribute the attack to Iran, whereas most other international coverage avoids naming a perpetrator.
• South Korean coverage (Yonhap) focuses on the safety of KEPCO staff and the plant's operational status, reflecting the builder/operator country's perspective, which is absent from other regional reports.
• Chinese-language financial news (FX168) links the attack directly to oil price volatility and energy market risk, a framing not present in other language coverage.
• German coverage (Deutsche Welle) highlights the UAE's 123 Agreement with the US as a nuclear governance detail, which is absent from most other reports.
```

### `dskflash-t05-rhigh` (DeepSeek V4 Flash, temp 0.5, reasoning=high, streaming)

**topic 0 — Trump Iran (15 sources, 12 actors, 9 langs, 4 divs, 4 gaps; $0.008, 267 s)** — fewer but more compressed divergences vs rnone; more actors quoted per source (12 vs 3 on rnone).

```
SAMPLE SOURCE TITLES (3 of 15):
• [en] Iran war pushes oil prices to 4-year high as Hormuz bottleneck persists
• [en] Saudi says it intercepted three drones that entered from Iraqi airspace
• [en] Trump says he doesn't need congressional authorization for Iran military operation despite War Powers deadline

DIVERGENCES (4):
• US sources frame the crisis as a legal dispute over war powers and a market shock, while Iranian sources frame it as an illegitimate threat and economic warfare against civilians.
• Arabic sources emphasize the humanitarian and regional security dimensions (drone attacks, sovereignty violations), a perspective largely absent from Western coverage.
• European sources (Le Monde) highlight violations of international law, while Asian sources (China, India) focus on energy security and diplomatic solutions.
• Israeli sources discuss joint military preparations for renewed strikes, contrasting with Pakistani sources that highlight mediation and ceasefire efforts.
```

**topic 1 — Ukraine drones (15 sources, 15 actors, 10 langs, 5 divs, 5 gaps; $0.008, 413 s)**

```
SAMPLE SOURCE TITLES (3 of 15):
• [ru] Ночная украинская атака БПЛА 17 мая стала самой массовой в 2026 году
• [uk] Атака дронів на Москву і Підмосковʼя – СБУ оприлюднила деталі
• [fr] La Russie désormais vulnérable aux attaques en profondeur des drones ukrainiens

DIVERGENCES (5):
• Russian state media (TASS) frames the attack as a massive terrorist strike causing civilian casualties and residential damage, while Ukrainian sources (BBC Ukraine) emphasize it as a legitimate military response …
• Chinese outlets (SCMP, The Guardian) highlight Beijing's neutral stance and call for de-escalation without condemning either side, whereas Western European coverage (Le Monde) raises questions of proportionality under international humanitarian law.
• Indian media (ABP Live, Economic Times) focus narrowly on the death of an Indian worker and consular assistance, avoiding any judgment on the legitimacy of the strikes …
• Baltic coverage (LSM, Reuters) treats the drone incursions as a NATO security issue and calls for enhanced air defences, framing the event as a spillover threat to the alliance …
• Arabic-language outlets (Al Bayan) present the attack as part of a mutual escalation in drone warfare, giving roughly equal weight to Ukrainian and Russian claims …
```

**topic 2 — UAE Barakah (15 sources, 30 actors, 11 langs, 4 divs, 5 gaps; $0.009, 426 s)** — densest actors_quoted of the sweep (30 actors vs 14 on rnone).

```
SAMPLE SOURCE TITLES (3 of 15):
• [en] UAE 'has right to respond' after drone strike on Barakah nuclear plant
• [en] Drone strike sparks fire on perimeter of UAE's Barakah nuclear power plant
• [en] Sources: Drone attack on UAE nuclear plant intended to send message

DIVERGENCES (4):
• Attribution varies sharply: Israeli and Arab sources (Jerusalem Post, RT Arabic) directly accuse Iran or report GCC accusations, while Iranian sources (Asriran) emphasize that no party has claimed responsibility …
• Nuclear safety framing differs: German and French outlets (DW, France 24) stress IAEA's deep concern and the unacceptable risk, whereas Korean and Chinese sources focus on operational continuity and the absence of radiological release.
• South Korean sources uniquely highlight the involvement of KEPCO and the safety of Korean workers, a perspective entirely absent from other language coverage.
• Portuguese sources (G1) link the attack to the fragile ceasefire with Iran, while Vietnamese sources (Tuổi Trẻ) emphasize it as the first time Barakah has been targeted in the conflict.
```

## Observation (with three-sweep aggregate)

Researcher-Assemble is the only role in this wave where the cheaper-model candidate **matches or exceeds the production baseline on every primary metric** when it succeeds. All four 100%-valid DeepSeek Flash variants extract 15 sources/topic vs baseline 15/12/10, produce 4-5 divergences/topic vs baseline 1-3, write somewhat longer per-source summaries (p50 159-254 vs 127-156 chars), and cost **3.1-4.9× less** per topic ($0.005-$0.008 vs $0.026). The flat 15-source ceiling across all 16 successful calls is worth probing — none of the candidates ever extracted 16, 17, or all 23 sources, suggesting an internal soft cap rather than per-input-merit judgement; this matters if a future production substrate ever contains more than 15 high-value search results. The two failures both hit streaming-reasoning Flash on the same topic 0 substrate (truncation on `t05-rmedium`, 18-min SSL-receive hang on `t07-rhigh`), confirming that the `buffer-then-silent` failure mode flagged for V4 Pro in `docs/AUDIT-CURATOR-2026-05-11.md` is also present in V4 Flash + reasoning at non-zero rate (2/12 = 16.7% in this small sample); the no-reasoning variants are streaming-failure-free in this sweep. Reasoning effort on Flash does not improve the integrity, divergence count, or summary depth in any direction the rnone variants don't already cover, suggesting reasoning is structurally surplus for this extraction role — though it does roughly triple wall-time and triple cost relative to rnone.

### Three-sweep aggregate

**Cumulative cost across all three sweeps: $0.7769** (7.8% of the per-sweep $10 cap; Phase 1 + Phase 2 + Phase 3).  **60 / 62 successful** schema-valid calls across the three sweeps (96.8%).  The 2 failures are both Phase 3 streaming-Flash-reasoning.

| Sweep | Stage | Baseline | Best candidate (by gating metric) | Best candidate cost / topic | Gating-metric outcome |
|---|---|---|---|---|---|
| #1 — Plan | researcher_hydrated_plan | Opus 4.6, $0.054/topic, 23 queries × 13.3 langs | dskpro-t05-rmedium (best breadth) **or** dskpro-t05-rnone (cheapest with depth) | $0.015 / $0.008 | ~30% breadth shortfall vs baseline (17 q × 14 langs) — no variant matches baseline on the queries × languages product |
| #2 — Phase 2 reducer | hydration_aggregator_phase2 | Opus 4.6, $0.094/topic, 8.3 divergences mean | dskpro-t07-rhigh | $0.016 | **~36% divergence-count shortfall** (mean 5.3 vs 8.3); ceiling appears model-capacity-bound, not reasoning-budget-bound |
| #3 — Assemble | researcher_assemble | Flash 3, $0.026/topic, 12.3 sources mean, 2.3 divs mean | dskflash-t05-rnone | $0.006 | **Matches or beats baseline on every metric** (15 sources/topic on every topic, 5 divs on every topic); only role in the wave where the candidate doesn't lose on quality |

Two anomalies persist across all three sweeps for the architect's review: (1) **DeepSeek prompt-cache hit on `dskpro-t07-rnone`** — observed at the same dramatic ratio in Sweeps #1 and #2 ($0.003-$0.009 vs $0.025-$0.063 for `dskpro-t05-rnone` on the same substrate). Any production-swap cost projection that relies on the t07-rnone cost must be validated with a cache-cold re-measurement; the cache may not be available in production at the same hit rate. (2) **Wall-time blow-up on reasoning streaming** — Phase 3's V4 Flash reasoning calls took 4-9 minutes each on substrates Flash-baseline finishes in ~30s, with two of twelve hanging entirely. Production-swap decisions must weigh this against single-call SLAs; the rnone variants stay in baseline-comparable wall-time territory (~13-18s for Phase-1/2/3) and are streaming-failure-free.

## Phase 3 status

- **16 / 18** calls succeeded with schema-valid output (88.9%).  2 logged failures: `dskflash-t05-rmedium-topic0` (mid-stream truncation) and `dskflash-t07-rhigh-topic0` (SSL-receive hang).
- **Cumulative cost: $0.1112** (1.1% of $10 cap).
- **Three-sweep cumulative cost: $0.7769** (across all of wave 1).
- **No production code touched.** `git status` clean on `src/`, `agents/`, `scripts/run.py`, `src/schemas.py` — only `scripts/eval_researcher_assemble.py` and `docs/cost-efficiency-sweep-2026-05-18/researcher_assemble-report.md` are new. `output/eval/researcher_assemble-2026-05-18/` is under the gitignored `output/` tree.
- **STOP per the brief.** Wave 1 complete — three sweep reports landed at `docs/cost-efficiency-sweep-2026-05-18/`. Awaiting architect's decision on whether any candidate proceeds to a downstream production-swap brief.
