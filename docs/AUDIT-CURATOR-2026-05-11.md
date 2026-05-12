# AUDIT-CURATOR-2026-05-11

## 1. Setup

- **Baseline reference (no new run):** `output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json` — Gemini-3-Flash, temp=0.2, reasoning=none, max_tokens=64000. Top cluster size 1004, off_topic_pct 81.3 % (the documented over-clustering pathology).
- **Audit run date:** 2026-05-12 (CET local)
- **Harness:** `scripts/eval_curator_models.py` (built fresh — `scripts/test_multimodel_curator.py` from a prior session was retained as historical reference; its title-only vs compressed two-test pattern didn't fit the 20-variant matrix with per-call provider overrides, reasoning-by-temperature grid, max_tokens-by-reasoning-level, and hard cost cap)
- **Code change:** `src/agent.py` `AgentResult` extended with optional `provider: str = ""` and `response_id: str = ""` fields (backwards-compatible — defaults to empty), captured from `response.provider` / `response.id` on the final chat-completions call. Pre-existing `extra_body_override` and `reasoning` plumbing was already sufficient for the matrix; no other harness-driven changes.
- **Total spend:** $3.6657 across 20 variants (€-equivalent well under the €15 hard cap)
- **Run wall-clock:** ~7 h cumulative across 3 process restarts (one mid-audit `max_tokens` bump from 64k/96k/128k → 320k/320k/320k after two `dskpro` reasoning=medium variants returned 0 clusters at the original cap; one fresh restart after 4 dskflash variants stalled in `src/agent.py` malformed-JSON retry loops, costing ~30 min of silent wall time before manual intervention).
- **Skip-resume support** in the harness: variants whose `{label}.json` is already on disk with `n_topics > 0` reload from cache rather than re-paying.

## 2. Per-variant metrics table

Sorted by `off_topic_pct` ascending (cleanest top clusters on top). Wall-clock seconds reflect each variant's individual LLM call (not cumulative).

| Label | Model | Temp | Reasoning | Max tok | Wall (s) | Cost ($) | Tokens | # Clusters | Top size | On | Off | Off % | Jaccard vs baseline | Provider served |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **baseline** | gemini-3-flash | 0.2 | none | 64000 | n/a | n/a | n/a | 14 | **1004** | 188 | 816 | **81.3** | 1.00 | (V1 disk) |
| dskpro-t-05-r-none | dsk-v4-pro | 0.5 | none | 64000 | 181 | 0.0467 | 136075 | 68 | 12 | 12 | 0 | 0.0 | 0.01 | AtlasCloud |
| dskpro-t-07-r-none | dsk-v4-pro | 0.7 | none | 320000 | 321 | 0.0627 | 140795 | 141 | 10 | 10 | 0 | 0.0 | 0.01 | AtlasCloud |
| dskflash-t-05-r-medium | dsk-v4-flash | 0.5 | medium | 320000 | 10253 | 0.0301 | 175758 | 19 | 22 | 22 | 0 | 0.0 | 0.02 | Parasail |
| dskflash-t-07-r-none | dsk-v4-flash | 0.7 | none | 320000 | 299 | 0.0198 | 134578 | 38 | 3 | 3 | 0 | 0.0 | 0.00 | Parasail |
| dskflash-t-07-r-high | dsk-v4-flash | 0.7 | high | 320000 | 2397 | 0.0336 | 188297 | 20 | 24 | 22 | 2 | 8.3 | 0.02 | Parasail |
| dskflash-t-05-r-none | dsk-v4-flash | 0.5 | none | 320000 | 2412 | 0.0447 | 227714 | 42 | 18 | 16 | 2 | 11.1 | 0.01 | Parasail |
| dskpro-t-07-r-high | dsk-v4-pro | 0.7 | high | 320000 | 267 | 0.2595 | 140905 | 50 | 31 | 27 | 4 | 12.9 | 0.02 | AtlasCloud |
| dskflash-t-10-r-none | dsk-v4-flash | 1.0 | none | 320000 | 125 | 0.0203 | 136200 | 46 | 46 | 40 | 6 | 13.0 | 0.03 | AtlasCloud |
| dskflash-t-10-r-high | dsk-v4-flash | 1.0 | high | 320000 | 920 | 0.0246 | 151445 | 18 | 52 | 41 | 11 | 21.1 | 0.03 | Parasail |
| flash-t-10-r-none | gemini-3-flash | 1.0 | none | 64000 | 22 | 0.0755 | 134059 | 12 | 137 | 64 | 73 | 53.3 | 0.13 | Google |
| flash-t-10-r-medium | gemini-3-flash | 1.0 | medium | 96000 | 78 | 0.1071 | 144607 | 15 | 150 | 70 | 80 | 53.3 | 0.13 | Google |
| dskpro-t-10-r-high | dsk-v4-pro | 1.0 | high | 320000 | 1045 | 0.1958 | 180531 | 23 | 98 | 44 | 54 | 55.1 | 0.08 | AtlasCloud |
| dskpro-t-10-r-medium | dsk-v4-pro | 1.0 | medium | 320000 | 189 | 0.2348 | 133608 | 15 | 120 | 36 | 84 | 70.0 | 0.07 | AtlasCloud |
| dskpro-t-10-r-none | dsk-v4-pro | 1.0 | none | 64000 | 116 | 0.2308 | 132430 | 43 | 317 | 92 | 225 | 71.0 | 0.18 | AtlasCloud |
| dskflash-t-07-r-medium | dsk-v4-flash | 0.7 | medium | 320000 | 3690 | 0.0250 | 157361 | 20 | **1178** | 219 | 959 | **81.4** | 0.85 | Parasail |
| dskflash-t-05-r-high | dsk-v4-flash | 0.5 | high | 320000 | 2345 | 0.0291 | 172144 | 20 | **1103** | 190 | 913 | **82.8** | 0.88 | Parasail |
| dskflash-t-10-r-medium | dsk-v4-flash | 1.0 | medium | 320000 | 460 | 0.0216 | 140742 | 19 | **1092** | 172 | 920 | **84.2** | 0.83 | Parasail |
| dskpro-t-05-r-medium | dsk-v4-pro | 0.5 | medium | 320000 | 5237 | 0.7140 | 279868 | **0** | 0 | 0 | 0 | n/a | n/a | AtlasCloud |
| dskpro-t-05-r-high | dsk-v4-pro | 0.5 | high | 320000 | 5237 | 0.9460 | 348511 | **0** | 0 | 0 | 0 | n/a | n/a | AtlasCloud |
| dskpro-t-07-r-medium | dsk-v4-pro | 0.7 | medium | 320000 | 4743 | 0.5440 | 229564 | **0** | 0 | 0 | 0 | n/a | n/a | AtlasCloud |

Truncation policy: 3 variants emitted 0 clusters even at 320k. Per brief, recorded with empty output and not auto-bumped a second time. See §6 Open Items.

## 3. Observation

The over-clustering pathology is **not Flash-specific** — three DeepSeek-V4-Flash variants (`dskflash-t-05-r-high`, `dskflash-t-07-r-medium`, `dskflash-t-10-r-medium`) replicate it almost identically, producing top clusters of 1092 / 1103 / 1178 findings with off_topic_pct 82-84 % and Jaccard 0.83-0.88 against the V1 baseline top cluster (i.e. they're clustering the same 1000+ findings the baseline did). The pathology appears to be **a property of the dskflash model class at certain reasoning levels** rather than a property of Gemini-Flash specifically. Gemini-Flash at temp=1.0 collapses to a smaller top cluster (137-150) but still keeps ~53 % off-topic — better than baseline but not clean.

The cleanest top clusters come from **DeepSeek-V4-Pro at temp ≤0.7 with reasoning=none** (top 10-12, 0 % off-topic, 68-141 clusters in total) — but the inverse extreme: aggressive *under*-clustering with micro-clusters and a low-saturation top. The middle ground that produces both a moderately-sized top cluster (20-50 findings) AND clean content (≤21 % off-topic) is **`dskflash-t-07-r-high`** (top=24, off=8.3 %, 20 clusters), **`dskflash-t-05-r-none`** (top=18, off=11.1 %, 42 clusters), and **`dskpro-t-07-r-high`** (top=31, off=12.9 %, 50 clusters).

Three `dskpro` + reasoning≥medium variants at temp ≤0.7 **persistently fail** to produce parseable curator JSON even at 320k max_tokens (`dskpro-t-05-r-medium`, `dskpro-t-05-r-high`, `dskpro-t-07-r-medium` — confirmed across two independent runs each). The model consumes 230-350k tokens on reasoning and emits no JSON envelope. This is provider-routing-coupled: AtlasCloud serves dskpro under the `{"order": ["deepseek"], "allow_fallbacks": True}` policy, not deepseek-direct.

## 4. Manual sample — heuristic sanity-check

The on-topic regex matches `iran|tehran|trump|peace|negot|nuclear|israel|netanyahu|hezbollah|houthi|yemen|hormuz|oil|tanker|red sea|gaza|hamas|war|sanction|missile|enrichment|ayatollah|khamenei|pezeshkian|araghchi|witkoff|persia|persian|middle east|naher osten|medio oriente|saudi|qatar|lebanon|syria|emirates|teheran`. Brief: ~5-10 % false-pos/neg rate, directional only.

### Top-3 cleanest (off_topic_pct = 0.0 %) — 10 random titles from each top cluster

These variants had **0 off-topic-flagged** titles, so I'm showing random on-topic-flagged titles instead. The question: did the heuristic UNDER-flag (let off-topic content through unnoticed)?

**`dskpro-t-05-r-none`** (top cluster = 12 findings, all heuristic-on-topic):

- ✓ New 'Nakba' in Jerusalem: Israel steps up Silwan demolitions near Al-Aqsa
- ✓ Iran war day 73: Trump and Tehran clash over latest peace proposals
- ✓ Iran says US making 'unreasonable' demands in negotiations to end war
- ✓ Iran peace plan demands war compensation, sovereignty over Hormuz
- ✓ Iran says its proposal was generous as US insists on 'unreasonable demands'
- ✓ Hezbollah using fibre optic drones to evade Israeli jamming
- ✓ Turkish, Egyptian foreign ministers discuss Iran-US negotiations in phone call
- ✓ Iran describes its proposal to end war with US as 'legitimate' and 'generous'
- ✓ Iran says presence of French, British ships in Hormuz will be met with 'decisive, immediate response'
- ✓ Trump calls Iran response "totally unacceptable"

**`dskpro-t-07-r-none`** (top cluster = 10 findings, all heuristic-on-topic): essentially the same dossier — 10/10 unambiguously on-topic. Iran, Trump, Tehran, Hezbollah, Hormuz, peace negotiations.

**`dskflash-t-05-r-medium`** (top cluster = 22 findings, all heuristic-on-topic):

- ✓ Iran says its proposal was generous as US insists on 'unreasonable demands'
- ✓ Trump says 'we'll blow them up' if Iran uranium site accessed
- ✓ New 'Nakba' in Jerusalem: Israel steps up Silwan demolitions near Al-Aqsa
- ✓ Trump's deadly trap: By rejecting Iran's proposal, US enters a strategic nightmare with no escape
- ✓ Former Qatar PM: Netanyahu using Iran war to reshape Middle East
- ✓ US suffers 'total defeat' in war against Iran, faces irreversible strategic collapse: Neocon analyst
- ✓ Iran says presence of French, British ships in Hormuz will be met with 'decisive, immediate response'
- ✓ If Starmer is serious about stamping out antisemitism, he must end Britain's blind support for Israel
- ✓ Yemen's Ansarullah warns US after Trump rejected Iran's proposal
- ✓ Iran war day 73: Trump and Tehran clash over latest peace proposals

**Heuristic verdict on top-3:** the heuristic is NOT under-flagging on the cleanest variants. All 30 sampled top-cluster titles are unambiguously on-topic (Iran, Trump, Israel, Hezbollah, Yemen, Hormuz, Netanyahu). The 0 % off-topic flag is correct.

### Bottom-3 most-polluted (off_topic_pct ≥81 %) — 10 random off-topic-flagged titles each

**`dskflash-t-07-r-medium`** (top cluster = 1178; 959 heuristic-off-topic):

- ✗ Ataque coordenado por Vorcaro contra BC seguiu cartilha de agência, com contratos de R$ 8 milhões  *(Brazilian banking scandal)*
- ✗ Amnesty demands probe of alleged civilians death in military airstrike in Niger  *(Niger, not Iran)*
- ✗ Hong Kong's property recovery could be more robust than many think  *(HK real estate)*
- ✗ La Oreja de Van Gogh suprime el tema por el que Amaia Montero tuvo que pedir disculpas  *(Spanish band gossip)*
- ✗ Philippine VP Sara Duterte impeached for a second time  *(Philippine politics)*
- ✗ N. Korea marches in Russia's Victory Day parade  *(North Korea / Russia)*
- ✗ KFA seeks gov't approval for North Korean women's football team visit  *(Korean football)*
- ✗ Los lujosos XV años de la hija del alcalde morenista de Chignahuapan desatan polémica  *(Mexican municipal gossip)*
- ✗ Jaime de Marichalar, silencio sepulcral sobre el gran momento que está viviendo Victoria Federica  *(Spanish royal gossip)*
- ✗ Kenya: President Ruto Signs New Tax and Investment Laws  *(Kenya tax law)*

**`dskflash-t-05-r-high`** (top cluster = 1103; 913 heuristic-off-topic):

- ✗ Desaparecen al menos 35 pescadores tras bombardeos de Chad contra yihadistas nigerianos  *(Chad fishermen)*
- ✗ La primera ministra de Letonia asumirá temporalmente la cartera de Defensa  *(Latvia)*
- ✗ Kazakhstan sticking with OPEC  *(Kazakhstan / OPEC — borderline; OPEC arguably energy/oil-adjacent)*
- ✗ El empleo aguanta… por ahora  *(Spain employment)*
- ✗ Teste de americano que estava em cruzeiro dá positivo para hantavírus  *(cruise ship hantavirus)*
- ✗ Eugenia Martínez de Irujo: "No va nada conmigo ni la ostentación ni las pretensiones"  *(Spanish duchess gossip)*
- ✗ No power outages expected on Monday – Ukrenergo  *(Ukrainian power grid)*
- ✗ Drone operators destroy Russian flag installed in Kostiantynivka  *(Ukraine war — would have matched 'war' but didn't)*
- ✗ Esas ideas geniales  *(Spanish opinion piece, vague title)*
- ✗ (URGENT) KOSPI opens 3.7 pct higher at fresh high  *(South Korean stock market)*

**`dskflash-t-10-r-medium`** (top cluster = 1092; 920 heuristic-off-topic):

- ✗ Passengers leave hantavirus-hit cruise ship in Tenerife  *(cruise ship hantavirus)*
- ✗ Ankara'da facia: Yem karma makinesine kapılan çocuk hayatını kaybetti  *(Turkish industrial accident)*
- ✗ Cármen cancelou multa de R$ 600 mil aplicada por Moraes  *(Brazilian judiciary)*
- ✗ Singaporean killed in Dukono eruption  *(Indonesian volcano)*
- ✗ Suspected gunmen kill UNIBEN student  *(Nigerian crime)*
- ✗ S. Korea, NATO officials discuss defense industry cooperation  *(Korea-NATO)*
- ✗ El cantante marroquí Saad Lamjarred, juzgado en Francia por un nuevo caso de violación  *(Moroccan singer trial)*
- ✗ Mortes: Professora querida, formou gerações de estudantes  *(Brazilian obituary)*
- ✗ Starmer intenta relanzar su gobierno tras el peor resultado laborista en décadas  *(UK politics)*
- ✗ Does Kazakhstan's power-generating capacity match its AI ambitions?  *(Kazakhstan AI)*

**Heuristic verdict on bottom-3:** the heuristic is correctly identifying off-topic content. All 30 sampled off-topic-flagged titles are unambiguously off-topic vs the Iran story. **No false-positive over-flagging** observed. One borderline case (Kazakhstan OPEC) is reasonable to flag either way. One known miss: "Drone operators destroy Russian flag in Kostiantynivka" — this would have matched `\bwar\b` if the title carried that word; the regex didn't catch it because Russia-Ukraine specific lexicon (`drone`, `Kostiantynivka`) isn't in the keyword set. Under-flagging at the ~5 % rate the brief anticipated.

**Net:** the 81-84 % off-topic-pct numbers on the three pathological dskflash variants are sound. The 0 % numbers on the cleanest dskpro / dskflash-no-reasoning variants are also sound.

## 5. Recommendation

**Swap Curator production to `dskflash-t-07-r-high` (DeepSeek-V4-Flash, temp=0.7, reasoning=high) with a fallback option of `dskflash-t-05-r-none` (DeepSeek-V4-Flash, temp=0.5, reasoning=none).**

Justification:

- `dskflash-t-07-r-high` produced the cleanest *balanced* output — top cluster of 24 findings with only 8.3 % off-topic, 20 total clusters. The top is small enough not to need downstream source-capping (well below the cap=50 threshold) and the long tail isn't pulverised. Cost $0.034 / 40 min wall (vs Flash baseline $0.08 / 22 s).
- `dskflash-t-05-r-none` is the cost/latency-tighter alternative: $0.045 / 40 min, top=18, off=11.1 %, 42 clusters. Top size is even smaller. Wall-clock matches the high-reasoning variant due to per-token sampling latency on the Parasail provider.
- `dskpro-t-07-r-high` at top=31 / off=12.9 % is also a candidate but costs 7× more ($0.26 vs $0.034). Worth keeping in mind if dskflash availability becomes a problem.

**Avoid:**
- All four pure-temp=1.0 variants regardless of family — over half their top cluster is off-topic (53-71 %). Bumping Gemini-Flash temperature alone won't fix the pathology.
- `dskflash-t-10-r-medium`, `dskflash-t-05-r-high`, `dskflash-t-07-r-medium` — these directly replicate the V1 baseline pathology (top 1092-1178, off ≥81 %).
- `dskpro` at reasoning ≥medium with temp ≤0.7 — three out of four such variants persistently truncate at 320k max_tokens.

**Important caveats before flipping the production config:**

1. The single-day sample (2026-05-11) is one diffuse hot-topic day with the Iran story dominating. The pathology was observed on 2026-05-11 + 2026-05-02 but absent on 2026-04-30 / 05-04 / 05-05 / 05-07 / 05-08 per the brief. A multi-day cross-check on quieter days (e.g. 2026-04-30) is recommended before the production swap to confirm the recommended variant doesn't *under*-cluster on slow news days.
2. DeepSeek-V4-Flash is currently routed by OpenRouter via the **Parasail** fallback (and AtlasCloud for some calls), not deepseek-direct. The `allow_fallbacks: True` policy is intentional but production should monitor whether routing variance affects output stability over time.
3. The audit harness mirrored production agent construction (SYSTEM.md + INSTRUCTIONS.md + CURATOR_SCHEMA + `_prepare/_rebuild/_enrich` helpers); the rendered TP shape should be unaffected by the model swap. No prompt changes are needed.

## 6. Open items

- **Provider routing.** DeepSeek-V4-Pro routed to AtlasCloud, DeepSeek-V4-Flash routed to Parasail, neither to "deepseek" direct. `allow_fallbacks: True` was intentional per brief but worth documenting in production config when the swap lands. `provider_served` field added to `AgentResult` to surface this on every call.
- **Persistent truncation failures.** Three `dskpro` reasoning≥medium variants at temp ≤0.7 consistently emit 0-cluster output even at 320k max_tokens. Token usage 230-350k on reasoning, no JSON output. Pattern reproducible across multiple independent runs of the same variants. These don't fit the simple "bump max_tokens" recipe — they appear to be a hard incompatibility between `dskpro` + medium-or-high reasoning + low temperature + the curator-schema + AtlasCloud serving. Not actionable here; just documented.
- **Mid-audit max_tokens bump.** The two Gemini-Flash variants completed at the original 64k / 96k caps in the first run and were reloaded from disk by the resume logic at the second/third runs. Their `max_tokens` field in the per-variant payload reflects 64k / 96k, not 320k. They did not truncate (134k / 145k total tokens used inside the cap). All 18 DeepSeek variants ran at 320k. Not a comparability problem — flash didn't hit its ceiling — but worth flagging.
- **Internal-retry orchestration churn.** Several DeepSeek variants spent 30-200 minutes in `src/agent.py`-internal malformed-JSON retry loops on the first long-running attempt. A fresh-process restart cleared most of these in under 10 minutes for the same variants. Not strictly a model-quality issue but an audit-throughput problem; if we audit at this scale again, consider tightening `MAX_RETRIES` for evaluation harnesses specifically.
- **Heuristic under-flagging on Russia-Ukraine content.** Ukraine-specific terms (`drone`, place names like Kostiantynivka) aren't in the keyword set. A future audit may want to add `ukraine|russia|kyiv|moscow|putin|zelensky` to the regex if Russia-Ukraine becomes a confounder. For this audit it doesn't move the conclusion — the 1000+ pathological clusters are clearly off-topic dominated by 80+ %.

## 7. Cost summary

Per-variant cost and overall:

| Family | Sum cost | n_variants | mean per-variant |
|---|---:|---:|---:|
| flash (Gemini) | $0.1826 | 2 | $0.0913 |
| dskpro (DeepSeek-V4-Pro) | $3.2843 | 9 | $0.3649 |
| dskflash (DeepSeek-V4-Flash) | $0.2488 | 9 | $0.0276 |
| **Total** | **$3.6657** | **20** | $0.1833 |

Cost cap: $17 (~€15). Headroom remaining at audit end: $13.34. Cap not tripped at any point.

Hot-spending notes:
- `dskpro-t-05-r-high` alone: $0.946 (a truncated 0-cluster output)
- `dskpro-t-07-r-medium`: $0.544 (0 clusters)
- `dskpro-t-05-r-medium`: $0.714 (0 clusters)
- The three persistent dskpro failures consumed $2.20 = 60 % of total audit spend for zero useful output.

If the audit is repeated, skipping `dskpro` reasoning≥medium at temp ≤0.7 would save ~$2 and ~3 hours of wall-time.

## 8. Reproducibility

One variant per family with full OpenRouter `response_id` and request shape:

### Flash (Gemini-3-Flash)

- **Variant:** `flash-t-10-r-none`
- **Response id:** `gen-1778540273-u8fqv7yKikfCpyqtIVcM`
- **Provider served:** Google
- **Model:** `google/gemini-3-flash-preview`
- **Request:** temperature=1.0, reasoning={effort: "none"}, max_tokens=64000, response_format=CURATOR_SCHEMA strict-mode, provider=default OpenRouter routing
- **System+Instructions:** `agents/curator/SYSTEM.md` + `agents/curator/INSTRUCTIONS.md` (HEAD on audit day)
- **User message:** "Review these findings. Cluster related findings into topics. Score each topic's newsworthiness on a 1-10 scale."
- **Context:** prepared findings (1201 items after `_prepare_curator_input` URL-dedup pass)

### DeepSeek-V4-Pro

- **Variant:** `dskpro-t-05-r-none`
- **Response id:** `gen-1778540273-aqgOEWcUjVe6sabHGQyW`
- **Provider served:** AtlasCloud
- **Model:** `deepseek/deepseek-v4-pro`
- **Request:** temperature=0.5, reasoning={effort: "none"}, max_tokens=64000 (this variant completed in run 1 before the 320k bump), response_format=CURATOR_SCHEMA strict-mode, provider={order: ["deepseek"], allow_fallbacks: True}

### DeepSeek-V4-Flash

- **Variant:** `dskflash-t-05-r-none`
- **Response id:** `gen-1778562178-GlongdlhfjOUGEqvTx6p`
- **Provider served:** Parasail
- **Model:** `deepseek/deepseek-v4-flash`
- **Request:** temperature=0.5, reasoning={effort: "none"}, max_tokens=320000, response_format=CURATOR_SCHEMA strict-mode, provider={order: ["deepseek"], allow_fallbacks: True}

Raw per-variant outputs are at `output/eval/curator-2026-05-11/{label}.json` (gitignored). Aggregated metrics at `output/eval/curator-2026-05-11/_metrics.json`.
