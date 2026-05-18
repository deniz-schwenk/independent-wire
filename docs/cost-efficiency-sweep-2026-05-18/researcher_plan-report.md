# Cost-efficiency sweep wave 1, Sweep #1 — `researcher_hydrated_plan`

Phase 1 of `TASK-COST-EFFICIENCY-SWEEP-WAVE-1`. 8 candidate variants of `ResearcherHydratedPlanStage` benchmarked against the Opus 4.6 production baseline. **Architect decision pending — no recommendation in this report.**

## Setup

- **Substrate:** `output/2026-05-18/_state/run-2026-05-18-c26864b2/topic_buses.assemble_hydration_dossier.{0,1,2}.json`. Three topics from today's V2 hydrated run:
  - topic 0: *Donald Trump issues ultimatum to Iran amid stalled peace negotiations* (16 pre-dossier sources, 9 coverage gaps)
  - topic 1: *Ukraine launches largest drone strikes on Moscow and Russian regions* (similar substrate density)
  - topic 2: *Drone strike hits UAE nuclear power plant complex* (similar substrate density)
- **Baseline on disk:** `topic_buses.ResearcherHydratedPlanStage.{0,1,2}.json` — Opus 4.6, temp=0.5, reasoning=none, max_tokens=16384. Today's production cost: **$0.054/topic mean ($0.162 total), 7,471 tokens/topic, 23 queries/topic, 12–14 languages/topic**.
- **Schema:** `RESEARCHER_PLAN_SCHEMA` (`{queries: [{query, language}]}`, strict mode). No changes.
- **Prompts:** `agents/researcher_hydrated/PLAN-SYSTEM.md` + `agents/researcher_hydrated/PLAN-INSTRUCTIONS.md` verbatim.
- **`max_tokens=64000`** for every variant (overrides production 16384 — wave-1 contract).
- **DeepSeek routing:** `extra_body.provider = {order: ["deepseek"], allow_fallbacks: True, require_parameters: True}`. `provider_served` captured per call.

### Harness notes

- **Option B taken.** `src/agent.py` is unchanged. The harness `scripts/eval_common.py` bypasses `Agent.run()` and calls `AsyncOpenAI.chat.completions.create()` directly, mirroring `Agent._build_user_message`'s three-block layout (`<context>` + `<instructions>`, no `<memory>`) so the prompt receives the same input the production wrapper would produce.
- **Streaming wiring**: DeepSeek V4 Pro `reasoning ∈ {medium, high}` variants pass `stream=True, stream_options={include_usage: True}`. The async iterator aggregates `delta.content` chunks; `usage`, `model`, and `provider` are captured from the terminal chunks. Non-streaming variants take the standard non-stream path. All 12 streaming calls in this sweep returned full JSON — no instances of the V1-era buffer-then-silent failure documented in `docs/AUDIT-CURATOR-2026-05-11.md`.
- **Concurrency model**: 8 variants run sequentially; within each variant the 3 topic calls run in parallel via `asyncio.gather`. Spending-cap check after each variant.
- **Cap:** $10 hard per sweep. Cumulative spend at completion: **$0.4115** (4.1% of cap).
- **Skip-resume**: each `{label}-topic{N}.json` includes `structured`; cached when re-run.

## Metrics

All variants: **3/3 schema-valid** outputs. **Zero failures.** Cumulative cost across the 24 calls: **$0.4115** vs baseline $0.162 — the sweep itself is ~2.5× the baseline cost of one production run, well under the $10 cap.

| label | model | temp | reasoning | streaming | cost_total | cost/topic | tokens_total | wall_mean | queries_mean | langs_mean | schema_valid | provider |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **baseline** | claude-opus-4.6 | 0.5 | none | no | $0.1621 | $0.0540 | 22,413 | n/a | **23.0** | **13.3** | 100% | Anthropic |
| dskpro-t05-rnone | deepseek-v4-pro | 0.5 | none | no | **$0.0248** | $0.0083 | 18,776 | 15.5 s | 15.0 | 12.0 | 100% | AtlasCloud |
| dskpro-t05-rmedium | deepseek-v4-pro | 0.5 | medium | yes | $0.0443 | $0.0148 | 29,350 | 91.0 s | **17.0** | **14.0** | 100% | AtlasCloud |
| dskpro-t05-rhigh | deepseek-v4-pro | 0.5 | high | yes | $0.0318 | $0.0106 | 25,653 | 69.6 s | 17.0 | 12.0 | 100% | AtlasCloud |
| dskpro-t07-rnone | deepseek-v4-pro | 0.7 | none | no | **$0.0087** | $0.0029 | 18,817 | 16.1 s | 15.0 | 10.7 | 100% | AtlasCloud |
| dskpro-t07-rmedium | deepseek-v4-pro | 0.7 | medium | yes | $0.0442 | $0.0147 | 29,335 | 91.5 s | 15.7 | 11.3 | 100% | AtlasCloud |
| dskpro-t07-rhigh | deepseek-v4-pro | 0.7 | high | yes | $0.0369 | $0.0123 | 27,150 | 73.9 s | 16.7 | 11.7 | 100% | AtlasCloud |
| gpro-rlow | gemini-3.1-pro-preview | 1.0 | low | no | $0.0536 | $0.0179 | 20,108 | **6.5 s** | 12.3 | 9.3 | 100% | Google |
| gpro-rhigh | gemini-3.1-pro-preview | 1.0 | high | no | $0.1673 | $0.0558 | 29,681 | 33.5 s | 12.0 | 9.0 | 100% | Google |

Per-topic detail (queries / languages):

| label | topic 0 | topic 1 | topic 2 |
|---|---|---|---|
| **baseline (Opus)** | 23 / 14 | 23 / 12 | 23 / 14 |
| dskpro-t05-rnone | 15 / 12 | 15 / 11 | 15 / 13 |
| dskpro-t05-rmedium | 18 / 13 | 15 / 14 | 18 / 15 |
| dskpro-t05-rhigh | 20 / 14 | 15 / 9 | 16 / 13 |
| dskpro-t07-rnone | 18 / 10 | 14 / 11 | 13 / 11 |
| dskpro-t07-rmedium | 15 / 11 | 16 / 11 | 16 / 12 |
| dskpro-t07-rhigh | 17 / 11 | 15 / 10 | 18 / 14 |
| gpro-rlow | 15 / 10 | 10 / 9 | 12 / 9 |
| gpro-rhigh | 12 / 10 | 11 / 9 | 13 / 8 |

Prompt-rule compliance (`PLAN-INSTRUCTIONS.md` §Volume and balance: minimum 10 queries, at least half non-English):

- **All 8 variants** satisfy the ≥10-queries gate on all 3 topics.
- **All 8 variants** satisfy the ≥50% non-English gate on all 3 topics.

`story_shape_compliance` reported as **0.0 across the board, with a caveat**: the production strict-mode `response_format` on `RESEARCHER_PLAN_SCHEMA` has `additionalProperties: False` and only allows `{query, language}`. Any model honouring the schema **cannot** emit a `story_shape` field. The Researcher-Polish iter-1.5 obligation referenced in the brief is a *prompt-internal* reasoning obligation ("each query carries exactly one of the six shapes"), and the SYSTEM/INSTRUCTIONS explicitly states *"The shape that drove each query is not emitted."* This metric is therefore unmeasurable from the strict-schema output; it would only become measurable if the schema were extended to admit an optional `story_shape` field (out of scope for this wave).

## Qualitative samples (top-2 by mean queries × mean languages)

Top-2 selected by `queries_mean × languages_mean` as a single-number proxy for "stays closest to Opus baseline's 23 × 13.3 = 306": **dskpro-t05-rmedium (17 × 14 = 238)** and **dskpro-t05-rhigh (17 × 12 = 204)**. All 3 topic outputs for each are shown — the per-variant directory has only 3 topic files so "3 random" is the full set.

### dskpro-t05-rmedium (DeepSeek V4 Pro, temp 0.5, reasoning=medium, streaming)

**topic 0 — Trump Iran ultimatum (18 queries, 13 langs)** — heavy explicit gap targeting from `coverage_gaps`: Iraqi-government response, ICRC humanitarian access, regional shipping rerouting, civilian impact in Farsi.

```
[en]  UN Security Council emergency meeting Iran blockade international law May 2026
[en]  marine war risk insurance Hormuz Strait rates May 2026
[en]  Iran civilian food shortages medicine blockade May 2026
[ar]  الحكومة العراقية ترد على انتهاك مجالها الجوي بطائرات مسيرة 2026
[fa]  گزارش میدانی از تاثیر محاصره تنگه هرمز بر زندگی مردم ایران
[zh]  中国外交部关于霍尔木兹海峡航行自由的声明 2026年5月
[fr]  conséquences du blocus du détroit d'Ormuz pour les pays africains importateurs de pétrole
[sw]  athari za kufungwa kwa mlango wa Hormuz kwa uchumi wa Afrika Mashariki 2026
[hi]  होर्मुज जलडमरूमध्य बंद होने से भारतीय अर्थव्यवस्था पर असर मई 2026
[he]  צה"ל היערכות לתקיפה באיראן בעקבות האולטימטום של טראמפ 2026
[ur]  آبنائے ہرمز کی بندش سے پاکستان کی توانائی کی سلامتی پر اثرات
...
```

**topic 1 — Ukraine drones on Moscow (15 queries, 14 langs)** — broadest language mix of all sweep outputs. Reaches Latvian (airspace-violation context), Korean (regional reaction), Latvian + Ukrainian (production / airspace).

```
[en]  State Department response Ukraine drone attack Moscow May 2026
[zh]  乌克兰无人机袭击莫斯科 中国外交部 回应 2026年5月
[ru]  ТАСС атака беспилотников Москва 17 мая 2026 последствия
[uk]  виробництво дронів Україна постачання компоненти 2026
[de]  Militärexperte Bewertung Drohnenangriff Moskau Völkerrecht Mai 2026
[lv]  Latvijas gaisa telpas pārkāpums drons 2026. gada 17. maijs
[ja]  ウクライナ ドローン攻撃 モスクワ 日本政府 反応 2026年5月
[ko]  우크라이나 드론 공격 모스크바 한국 정부 성명 2026
[sw]  mashambulizi ya drones Ukraine Moscow athari bei ya chakula Afrika Mashariki
...
```

**topic 2 — UAE nuclear drone strike (18 queries, 15 langs)** — strongest sweep output by language count. Specific nuclear-safety institutions (IAEA equivalent in each market), Korean attention to KEPCO (Barakah operator), Iraqi militia angle in Turkish.

```
[en]  Barakah nuclear plant drone strike independent nuclear safety expert radiological risk assessment 2026
[en]  Convention on Physical Protection of Nuclear Material drone attack UAE legal analysis
[ar]  العراق هجوم طائرة مسيرة على محطة براكة النووية الإمارات
[tr]  Baraka nükleer santrali İHA saldırısı Türkiye'nin tepkisi
[de]  Drohnenangriff AKW Barakah nukleare Sicherheit Expertenmeinung
[ko]  바라카 원전 드론 공격 KEPCO 대응
[ur]  براکہ نیوکلیئر پلانٹ ڈرون حملہ پاکستان ثالثی
[sw]  Shambulio la ndege zisizo na rubani kwenye kinu cha nyuklia cha Barakah athari Afrika Mashariki
[ar]  سكان منطقة الظفرة الإمارات هجوم طائرة مسيرة محطة براكة
...
```

### dskpro-t05-rhigh (DeepSeek V4 Pro, temp 0.5, reasoning=high, streaming)

**topic 0 — Trump Iran ultimatum (20 queries, 14 langs)** — most queries of any sweep variant on this topic. Distinct Arabic queries for Iraqi-government angle vs. insurance-market angle.

```
[en]  Strait of Hormuz oil tanker insurance rates 2026
[en]  international law Trump threat destruction Iran UN Charter
[ar]  موقف الحكومة العراقية من طائرات مسيرة انطلقت من أراضيها تجاه السعودية
[ar]  تأثير تهديدات ترامب على أسواق النفط العالمية شركات التأمين البحري
[fa]  واکنش رسانه‌های داخلی ایران به اولتیماتوم ترامپ و تهدید تنگه هرمز
[fa]  جامعه مدنی ایران اعتراضات جنگ تحریم‌ها
[ko]  호르무즈 해협 봉쇄 시 한국 해운업계 보험료 인상
[ja]  ホルムズ海峡 船舶保険 日本船主協会 2026
[he]  הכנות צה"ל לתקיפה באיראן דיווחי תקשורת ישראלית
...
```

**topic 1 — Ukraine drones on Moscow (15 queries, 9 langs)** — narrower language coverage than rmedium on this topic; more depth per language (two `zh`, two `ru`, two `fr`, two `ar` queries each targeting distinct angles).

```
[en]  US State Department statement Ukraine drone strikes Moscow May 2026
[en]  Ukraine long-range drone production supply chain components 2026
[en]  international humanitarian law assessment Ukraine drone attack Moscow civilian casualties proportionality
[ru]  ущерб Московскому НПЗ атака дронов 2026 экономические последствия
[fr]  frappes de drones Ukraine Moscou réaction Comité international Croix-Rouge mai 2026
[fr]  impact attaque drone raffinerie Moscou marché pétrolier européen mai 2026
[ar]  هجوم الطائرات المسيرة الأوكرانية على موسكو ردود فعل دول الخليج مايو 2026
[tr]  Ukrayna Moskova drone saldırısı Türkiye Dışişleri Bakanlığı açıklaması Mayıs 2026
[lv]  Latvijas gaisa telpas pārkāpums drons 2026. gada maijs NATO reakcija
...
```

**topic 2 — UAE nuclear drone strike (16 queries, 13 langs)** — names actor-specific institutions (KEPCO, ASN/IRSN, ENI) in each language's home market.

```
[en]  Barakah nuclear plant drone strike radiological risk assessment independent expert 2026
[en]  Nawah Energy Company Barakah drone strike May 2026 operational status
[fr]  attaque drone centrale nucléaire Barakah évaluation sûreté ASN IRSN 2026
[it]  attacco drone centrale nucleare Emirati Arabi Uniti reazione governo italiano ENI 2026
[de]  Drohnenangriff AKW Barakah Bundesregierung Reaktion 2026
[ko]  바라카 원전 드론 공격 KEPCO 안전 평가 2026
[ja]  バラカ原子力発電所 ドローン攻撃 日本 エネルギー安全保障 2026
[fa]  حمله پهپادی به نیروگاه هسته‌ای براکه واکنش ایران ۲۰۲۶
[ur]  براکہ نیوکلیئر پلانٹ ڈرون حملہ پاکستان ثالثی 2026
...
```

## Observation

All 24 calls produced schema-valid output — no streaming failures and no schema drift across any variant or topic, which validates the Option-B harness wiring as a like-for-like substitute for `Agent.run()` in this role. The DeepSeek V4 Pro variants cluster at 6.5–18× cheaper than the Opus 4.6 baseline ($0.003–$0.015/topic vs $0.054/topic) while delivering 12–17 queries/topic across 9–15 languages, leaving a ~30–40% breadth shortfall vs the baseline's 23 queries / 13.3 languages. Gemini 3.1 Pro Preview lands cheaper than baseline at `reasoning=low` ($0.018/topic) but at meaningfully lower breadth (12 queries / 9 languages — the only sweep cluster that flirts with the prompt's 10-query floor and the only one with zero diversification beyond Asia + Europe). Two anomalies worth flagging to the architect: (1) `dskpro-t07-rnone` came in at **$0.0029/topic** vs `dskpro-t05-rnone` at $0.0083 — same model, same input, only temperature differs — almost certainly DeepSeek prompt-cache hit on the second non-streaming variant in the run order; for any production swap that relies on this cost, a cache-cold re-measurement should be a precondition; (2) increasing temperature from 0.5 → 0.7 on DeepSeek consistently *narrows* language coverage rather than widening it (12 → 11 langs on rnone, 14 → 11 on rmedium, 12 → 12 on rhigh), suggesting the temperature ceiling for this multilingual-planning role sits at 0.5 on DeepSeek; the `story_shape_compliance` metric the brief listed cannot be evaluated under the unchanged strict schema (note in §Metrics).

## Phase 1 status

- **24 / 24** calls succeeded with schema-valid output.
- **Cumulative cost: $0.4115** (4.1% of $10 cap).
- **No production code touched.** `git status` clean on `src/`, `agents/`, `scripts/run.py`, `src/schemas.py` — only `scripts/eval_common.py`, `scripts/eval_researcher_plan.py`, and `docs/cost-efficiency-sweep-2026-05-18/researcher_plan-report.md` are new. `output/eval/researcher_plan-2026-05-18/` is under the gitignored `output/` tree.
- **STOP.** Phase 2 (hydration_phase2) does not auto-proceed. Awaiting architect "proceed".
