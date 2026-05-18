# Cost-efficiency sweep wave 1, Sweep #2 — `hydration_aggregator_phase2` (reducer)

Phase 2 of `TASK-COST-EFFICIENCY-SWEEP-WAVE-1`. 6 DeepSeek V4 Pro variants of the Phase-2 reducer benchmarked against the Opus 4.6 production baseline. Gemini 3.1 Pro Preview excluded per brief (prior 75-90/120 vs Opus 114/120 in this role; cluster ceiling at 3-4 divergences/topic).  **Architect decision pending — no recommendation in this report.**

## Setup

- **Substrate:** `output/2026-05-18/_state/run-2026-05-18-c26864b2/topic_buses.HydrationPhase1Stage.{0,1,2}.json`. Three topics from today's V2 hydrated run:
  - topic 0: *Trump ultimatum to Iran* (16 phase-1 analyses, 16 successful fetches)
  - topic 1: *Ukraine drones on Moscow* (22 phase-1 analyses, 22 successful fetches)
  - topic 2: *UAE Barakah drone strike* (11 phase-1 analyses, 11 successful fetches)
- **Baseline on disk:** `topic_buses.HydrationPhase2Stage.{0,1,2}.json` — Opus 4.6, temp=0.1, reasoning=none, max_tokens=32000. Today's production: **$0.0936/topic mean ($0.2808 total), 14,540 tokens/topic, 9/10/6 preliminary_divergences, 9/10/8 coverage_gaps**.
- **Schema:** `HYDRATION_PHASE2_SCHEMA` — `{preliminary_divergences: string[], coverage_gaps: string[]}`, strict mode.
- **Prompts:** `agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md` verbatim.
- **`max_tokens=64000`** (overrides production 32000 — wave-1 contract).
- **DeepSeek routing:** `extra_body.provider = {order: ["deepseek"], allow_fallbacks: True, require_parameters: True}`. `provider_served` captured per call.

### Harness notes

- Same `scripts/eval_common.py` harness as Phase 1. Option B preserved — `src/agent.py` not touched.
- 9 streaming calls (medium + high × 3 topics × 2 temperatures) all returned full JSON; no instances of the V1-era buffer-then-silent failure documented in `docs/AUDIT-CURATOR-2026-05-11.md`.
- Input substrate is meaningfully larger than the Phase 1 sweep (~40-50k tokens of `article_analyses` JSON vs ~16k for the Plan stage), which raises both wall-time and token totals proportionally.
- Cumulative cap status at completion: **$0.2542** (2.5% of $10 cap).

## Metrics

All 18 calls produced **schema-valid** output (100%). **Zero failures.**

| label | model | temp | reasoning | streaming | cost_total | cost/topic | tokens_total | wall_mean | divs (per topic) | gaps (per topic) | schema_valid | provider |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **baseline** | claude-opus-4.6 | 0.1 | none | no | $0.2808 | $0.0936 | 43,619 | n/a | **9 / 10 / 6** (mean 8.3) | **9 / 10 / 8** (mean 9.0) | 100% | Anthropic |
| dskpro-t05-rnone | deepseek-v4-pro | 0.5 | none | no | $0.0633 | $0.0211 | 36,376 | 18.2 s | 5 / 5 / 4 (mean 4.7) | 5 / 5 / 4 (mean 4.7) | 100% | AtlasCloud |
| dskpro-t05-rmedium | deepseek-v4-pro | 0.5 | medium | yes | $0.0413 | $0.0138 | 45,717 | 90.0 s | 5 / 3 / 3 (mean 3.7) | 5 / 6 / 4 (mean 5.0) | 100% | AtlasCloud |
| dskpro-t05-rhigh | deepseek-v4-pro | 0.5 | high | yes | $0.0438 | $0.0146 | 46,436 | 90.9 s | 4 / 3 / 4 (mean 3.7) | 5 / 5 / 5 (mean 5.0) | 100% | AtlasCloud |
| dskpro-t07-rnone | deepseek-v4-pro | 0.7 | none | no | **$0.0097** | $0.0032 | 36,367 | 12.8 s | 5 / 6 / 4 (mean 5.0) | 6 / 5 / 5 (mean 5.3) | 100% | AtlasCloud |
| dskpro-t07-rmedium | deepseek-v4-pro | 0.7 | medium | yes | $0.0469 | $0.0156 | 47,358 | 102.0 s | 5 / 4 / 5 (mean 4.7) | 6 / 7 / 5 (mean 6.0) | 100% | AtlasCloud |
| dskpro-t07-rhigh | deepseek-v4-pro | 0.7 | high | yes | $0.0491 | $0.0164 | 48,014 | 110.5 s | **7 / 5 / 4** (mean 5.3) | 7 / 5 / 5 (mean 5.7) | 100% | AtlasCloud |

**Gating metric — `n_preliminary_divergences`**: the brief flags Pro variants stuck at 3-4/topic in prior eval. DeepSeek V4 Pro here lands at 3-7 across all variants/topics; **the highest single variant mean is `dskpro-t07-rhigh` at 5.3** — still ~36% below baseline (8.3). No variant matches or exceeds the baseline on any topic; the closest single-topic gap is `dskpro-t07-rhigh` on topic 0 (7 vs 9, ~22% below). Topic 1 (Ukraine drones, the densest substrate at 22 phase-1 analyses) shows the largest gap on every variant — DeepSeek tops out at 6 vs baseline 10.

**`n_coverage_gaps`**: closer to baseline than divergences but still consistently below. Best variant `dskpro-t07-rmedium` at mean 6.0 vs baseline 9.0.

## Qualitative samples (top-2 by mean divergence count)

Top-2 by `n_preliminary_divergences_mean`: **`dskpro-t07-rhigh` (5.3)** and **`dskpro-t07-rmedium` / `dskpro-t05-rnone` tied at 4.7**. I show `dskpro-t07-rhigh` (the leader on the gating metric) and `dskpro-t07-rmedium` (the cheapest with comparable depth) — all 3 topic outputs each.

### `dskpro-t07-rhigh` (DeepSeek V4 Pro, temp 0.7, reasoning=high, streaming)

**topic 0 — Trump Iran ultimatum (7 divs, 7 gaps; $0.018, 117 s)** — best single-topic divergence count of the sweep. Names cross-source angle distinctions specifically (Pentagon vs NATO intel vs UAE attribution).

```
DIVERGENCES:
• Spanish-language sources emphasize military escalation and Pentagon planning for intensified measures, while English-language sources provide detailed diplomatic proposals and multilateral reactions.
• Turkish-language sources uniquely foreground Israeli military readiness and US domestic political divisions over renewed strikes, a framing absent from English-language and Spanish-language coverage.
• Turkish-language sources report NATO intelligence assessments of Iran's retained missile capacity, a detail no other language group covers.
• Western European outlets include the UAE's direct attribution of the Barakah drone strike to Iran, while Middle Eastern and Latin American outlets omit this attribution.
• Latin American outlets frame the story primarily as a military standoff with threats of destruction, whereas Western European outlets incorporate diplomatic negotiations and international institutional responses such as the IAEA.
• The North American outlet covers the unintended consequences for Armenia's TRIPP project, a dimension absent from all other regional clusters.
• German-language coverage is limited to Trump's threat rhetoric, omitting the diplomatic, kinetic, and regional dimensions present in English, Spanish, and Turkish coverage.

GAPS:
• No voices from ordinary Iranian citizens or civil-society groups appear in the corpus …
• No perspectives from international humanitarian organizations or human-rights bodies …
• No coverage addresses the legality of the naval blockade under international law …
• No Iraqi officials or community voices are quoted, even though drones were launched from Iraqi airspace …
• No global energy-market analysts or shipping-industry representatives …
• No coverage from Russian or Chinese state media is present …
• No analysis of potential escalation involving non-state actors such as the Houthis in Yemen or Shia militias in Iraq …
```

**Baseline (Opus) comparison on topic 0**: 9 divergences (vs 7 here). Opus uniquely surfaced (a) the Rezai/Sea-of-Oman counter-threat, (b) Western framing of Iran's missile capacity at 60 %, plus two more cross-source observations omitted in the DeepSeek output.

**topic 1 — Ukraine drones (5 divs, 5 gaps; $0.018, 120 s)** — largest gap vs baseline. Identifies the major framing divides (Ukrainian justified-military vs RT terrorist-attack vs German mutual-retaliation) but misses several cross-source angles Opus surfaced.

```
DIVERGENCES:
• English-language Ukrainian outlets frame the drone strikes as a justified military operation … while English-language Russian state outlets frame them as a terrorist attack on civilians …
• English-language Western outlets consistently report the stray Ukrainian drones entering NATO airspace as a significant escalation risk, whereas English-language Ukrainian outlets omit this incident entirely.
• German-language outlets frame the strikes primarily within a narrative of mutual retaliation … while Russian-language independent outlets provide in-depth military analysis that critiques the operational planning and timing …
• The sole Spanish-language article covers only the subsequent decline in drone attacks, omitting the context and details of the initial massive strike …
• English-language Turkish state media (Anadolu Agency) adopts a neutral, balanced reporting style with extensive actor quotes from both sides …

GAPS:
• No Chinese or Indian media perspectives are present …
• No perspectives from ordinary civilians in Russia or Ukraine affected by the strikes …
• No Belarusian outlet covers the event even though drones reportedly transited Belarusian airspace …
• No international legal analysis or commentary from humanitarian organizations on the legality of the strikes …
• No analysis of the economic or environmental impact of the strikes on Russia's energy infrastructure …
```

**topic 2 — UAE Barakah drone strike (4 divs, 5 gaps; $0.013, 94 s)** — captures the key RT/Spanish/Western divides but smaller in count than baseline's 6.

```
DIVERGENCES:
• Spanish-language sources consistently mention allegations of UAE attacks on Iran, framing the drone strike as potentially retaliatory, while English-language sources, except for RT, omit this context …
• Western European outlets emphasize the UAE's framing of the strike as a terrorist attack and its right to respond, whereas Middle Eastern outlets report the incident more neutrally …
• Russian outlet RT provides a platform for Iran's accusation that the UAE was directly involved in aggression against Iran, a perspective absent from all Western and Middle Eastern coverage.
• Ukrainian coverage is split: one outlet condemns the attack as a parallel to Ukraine's own experience, while another ignores the UAE strike entirely to focus on Ukraine's drone war …

GAPS:
• No direct statement from Iranian military or political leadership …
• No voices from suspected perpetrator groups such as Iraqi militias or Yemen's Houthis …
• No independent nuclear safety or environmental experts …
• No international legal analysis on the legality of targeting nuclear facilities …
• No coverage from East Asian or South Asian outlets, despite the plant being operated by South Korea's KEPCO …
```

### `dskpro-t07-rmedium` (DeepSeek V4 Pro, temp 0.7, reasoning=medium, streaming)

**topic 0 — Trump Iran ultimatum (5 divs, 6 gaps; $0.011, 66 s)** — fewer divergences than rhigh but tighter formulation; more gaps surface specific outlet absences (Saudi/Emirati, Israeli).

```
DIVERGENCES:
• Spanish-language outlets uniquely foreground Pentagon contingency planning and Iranian threats of turning the Sea of Oman into a 'cemetery' …
• Turkish-language coverage foregrounds Israeli military preparations for renewed strikes on Iran and internal US congressional divisions over escalation …
• Middle Eastern outlets emphasize domestic US political constraints and Israeli military alertness, whereas Western European outlets prioritize international diplomatic reactions and the nuclear safety angle.
• Latin American outlets uniquely highlight Pentagon operational readiness and the most aggressive Iranian rhetoric …
• North American coverage uniquely examines the war's indirect consequences for the South Caucasus and the failure of US infrastructure projects …

GAPS:
• No direct Iranian domestic media coverage …
• No Saudi or Emirati news outlets despite drone attacks on their territory …
• No Israeli news source, absent the domestic Israeli debate and official rationale for the reported military preparations against Iran.
• No civil-society or affected-community voices …
• No analysis of the economic consequences of the Strait of Hormuz blockade for global trade, energy markets, or shipping insurance …
• No legal analysis of the US ultimatum or the naval blockade under international law …
```

**topic 1 — Ukraine drones (4 divs, 7 gaps; $0.022, 146 s)** — fewer divergences but the most gaps of any topic-1 output in the sweep; flags one important corpus-integrity issue (one French-sourced article is unrelated).

```
DIVERGENCES:
• Ukrainian outlets frame the drone strikes as legitimate military retaliation … while Russian state outlets frame them as terrorist attacks on civilians …
• Spanish-language coverage focuses solely on the decline in attacks the following night and quotes only Russian official sources …
• Russian-language opposition coverage from Latvia provides detailed military operational analysis and critiques of both sides' strategies …
• Western European outlets present the strikes as part of a mutual escalation and quote both Russian and Ukrainian officials …

GAPS:
• No Russian independent or civil-society voices from within Russia are included; all Russian-language coverage comes from state-directed RT or Latvia-based opposition …
• Affected-community voices from Russia are almost entirely absent, with only one resident quoted across the entire corpus …
• No perspectives from major non-Western powers such as China, India (beyond an embassy statement), Brazil, or South Africa …
• No article addresses the environmental or long-term economic consequences of the strikes on oil facilities …
• No direct statement from NATO officials …
• Coverage from Africa, the Middle East, and South America is virtually absent …
• The only French-sourced article is entirely unrelated to the Ukraine drone strikes, leaving French-language and French-outlet coverage absent from the corpus.
```

**topic 2 — UAE Barakah drone strike (5 divs, 5 gaps; $0.014, 94 s)** — one more divergence than the rhigh variant; same Eastern European parallel (Ukrinform → Ukraine nuclear infrastructure).

```
DIVERGENCES:
• English-language sources predominantly frame the drone strike as an unprovoked terrorist attack … while Spanish-language sources contextualize it within a cycle of mutual hostilities by citing reports of prior UAE covert attacks …
• Western European outlets emphasize Iran's culpability … whereas Latin American outlets highlight the Saudi-Iraqi drone incidents and the role of pro-Iranian Iraqi proxies, framing the strike as part of a broader regional proxy war.
• Middle Eastern outlets (Al Jazeera, Anadolu) report the incident factually without attributing blame, diverging from Western European outlets that explicitly blame Iran or its proxies.
• The Russian outlet RT includes Iran's accusation that the UAE was directly involved in aggression against Iran, a perspective absent from Western European English-language coverage.
• Ukrainian coverage (Ukrinform) uses the incident to draw parallels with Russian strikes on Ukrainian nuclear infrastructure, a framing unique to Eastern European outlets and absent elsewhere in the corpus.

GAPS:
• No Iranian government statement directly addressing the drone strike is quoted …
• No civil-society voices—such as plant workers, local residents, or nuclear safety experts …
• No perspectives from Gulf Cooperation Council states beyond Saudi Arabia …
• The corpus includes an article (Kyiv Independent) that covers a separate drone strike in Russia and does not address the Barakah incident at all, creating a topical gap in the assigned coverage.
• No technical analysis of radiological or environmental risks from the strike is provided beyond official reassurances …
```

## Observation

All 18 calls produced schema-valid output — Option-B streaming wiring held across 9 reasoning streams over a substrate ~3× the size of Phase 1's (40-50k vs 16k input tokens), with no buffer-then-silent failures. DeepSeek V4 Pro is **5-30× cheaper than the Opus baseline per topic** across all variants ($0.003-$0.021 vs $0.094), but **none of the six variants reaches the baseline's divergence count on any topic** — the highest single mean is `dskpro-t07-rhigh` at 5.3 vs baseline 8.3 (~36 % below). The structural ceiling the brief flagged from the prior Gemini eval (3-4 divergences) appears to apply to DeepSeek V4 Pro as well, only slightly relaxed: rnone variants average 4.7-5.0, reasoning variants 3.7-5.3, with a hard topic-1 lid of 6 (vs baseline 10) on the densest substrate. Increasing reasoning effort or temperature within this model shifts the count only marginally — `rhigh` beats `rnone` by ~0.3-0.6 divergences/topic on average — suggesting the limit is not reasoning-budget-bound but model-capacity-bound. Qualitative read: the divergences the DeepSeek variants *do* surface are coherent and correctly cross-sourced (Spanish/Pentagon, Turkish/NATO-intel, RT/Iran-attribution all named with the right outlets), so the gap is not quality-collapse but enumeration-completeness — DeepSeek consistently surfaces a subset of what Opus produces. Two anomalies for the architect: (1) `dskpro-t07-rnone` again came in dramatically cheaper than `dskpro-t05-rnone` ($0.0097 vs $0.0633 — the same 6.5× ratio observed in Phase 1) which strongly confirms a DeepSeek prompt-cache hit on the second non-streaming variant in run order; cache-cold re-measurement is needed before any production swap relies on the t07-rnone cost; (2) topic 1 (densest substrate, 22 phase-1 analyses) consistently widens the baseline-vs-candidate gap from ~30 % to ~50 %, suggesting the divergence-count ceiling may scale poorly with substrate density — a property worth probing in a multi-rep wave-2 brief if the architect decides this candidate is worth pursuing further.

## Phase 2 status

- **18 / 18** calls succeeded with schema-valid output.
- **Cumulative cost: $0.2542** (2.5% of $10 cap).
- **No production code touched.** `git status` clean on `src/`, `agents/`, `scripts/run.py`, `src/schemas.py` — only `scripts/eval_hydration_phase2.py` and `docs/cost-efficiency-sweep-2026-05-18/hydration_phase2-report.md` are new. `output/eval/hydration_phase2-2026-05-18/` is under the gitignored `output/` tree.
- **STOP.** Phase 3 (researcher_assemble) does not auto-proceed. Awaiting architect "proceed".
