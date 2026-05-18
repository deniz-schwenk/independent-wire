# Hallucination audit — `researcher_assemble` candidate `dskflash-t05-rnone`

Phase 1 of `TASK-PRODUCTION-SWAP-RESEARCHER-ASSEMBLE`. Two-check audit of today's Wave-1 Sweep #3 candidate outputs against the substrate they were generated from. Hard gate for the production swap.

## Setup

- **Candidate outputs** (3 topics × 15 sources = 45 URLs, 28 actors_quoted entries):
  - `output/eval/researcher_assemble-2026-05-18/dskflash-t05-rnone-topic0.json`
  - `output/eval/researcher_assemble-2026-05-18/dskflash-t05-rnone-topic1.json`
  - `output/eval/researcher_assemble-2026-05-18/dskflash-t05-rnone-topic2.json`
- **Substrate snapshots** (23 search queries × ~5 sub-results = ~110-115 search results per topic):
  - `output/2026-05-18/_state/run-2026-05-18-c26864b2/topic_buses.researcher_search.{0,1,2}.json`
  - Inner shape: each `researcher_search_results[N]` carries `{query, language, results}` where `results` is a JSON-encoded array of `{title, url, content}` sub-results.
- **URL normalization rules** (applied before comparison):
  - Strip query params matching `^(utm_|ref$|fbclid|gclid)`
  - Strip trailing slashes (path, not root)
  - Treat `http://` and `https://` as equivalent (canonicalized to `https`)
  - Lowercase host
- **Substrate URL pool extraction**: parse each query's `results` JSON. **One query** in topic 2 (`query[22]` — Vietnamese, "tấn công drone nhà máy điện hạt nhân Barakah UAE an ninh năng lượng 2026") has an inner-JSON parse error (`Expecting property name enclosed in double quotes: line 10 column 3`); for that query a regex fallback extracts `"url": "..."` and `"content": "..."` pairs from the raw string. This substrate-side artefact is not the candidate's fault — the URL the model returned for that query *is* present in the raw substrate text.
- **Random seed for Check B**: `random.seed(20260518)`.

## Check A — URL integrity (45 URLs)

For each candidate `sources[i].url`, classify against the substrate URL pool of the corresponding topic.

### Per-topic detail

**Topic 0** — Trump Iran (substrate pool: 115 normalized URLs; no inner-JSON parse failures)

| # | classification | URL |
|---|---|---|
| 0 | ✓ exact_match | https://www.nbcnews.com/politics/white-house/trump-congressional-authorization-iran-military-operation-war-powers-rcna343094 |
| 1 | ✓ exact_match | https://www.cbsnews.com/live-updates/iran-war-trump-oil-prices-hegseth-costs-strait-of-hormuz/ |
| 2 | ✓ exact_match | https://www.reuters.com/world/middle-east/saudi-says-it-intercepted-three-drones-that-entered-iraqi-airspace-2026-05-17/ |
| 3 | ✓ exact_match | https://www.reuters.com/world/middle-east/saudi-warplanes-struck-militias-iraq-during-war-sources-say-2026-05-13/ |
| 4 | ✓ exact_match | https://www.bbc.com/persian/articles/cy012ywknyko |
| 5 | ✓ exact_match | https://nournews.ir/fa/news/307864/پاسخ-قالیباف-به-تهدید-ترامپ-… |
| 6 | ✓ exact_match | https://www.aljazeera.net/ebusiness/2026/3/26/كيف-يهدد-اختناق-… |
| 7 | ✓ exact_match | https://www.bbc.com/arabic/articles/c77mg0nj8gzo |
| 8 | ✓ exact_match | https://www.iranintl.com/ar/202604137311 |
| 9 | ✓ exact_match | https://www.thepaper.cn/newsDetail_forward_32382651 |
| 10 | ✓ exact_match | https://www.lemonde.fr/international/article/2026/04/07/guerre-en-iran-la-rhetorique-guerriere-de-donald-trump-au-prisme… |
| 11 | ✓ exact_match | https://www.amnesty.org/fr/latest/news/2026/04/iran-president-trumps-apocalyptic-threats-of-large-scale-civilian-devastation/ |
| 12 | ✓ exact_match | https://www.aljazeera.com/news/2026/5/7/africa-sees-winners-and-losers-as-iran-war-pushes-up-oil-prices |
| 13 | ✓ exact_match | https://g1.globo.com/economia/noticia/2026/04/14/bloqueio-ormuz-petroleo-combustiveis.ghtml |
| 14 | ✓ exact_match | https://navbharattimes.indiatimes.com/india/iran-america-war-tension-impact-of-hormuz-strait-closure-on-india-oil-imports… |

**Topic 1** — Ukraine drones on Moscow (substrate pool: 114 normalized URLs; no inner-JSON parse failures)

| # | classification | URL |
|---|---|---|
| 0 | ✓ exact_match | https://www.reuters.com/world/europe/china-urges-restraint-after-ukraine-drone-attack-moscow-region-2026-05-18/ |
| 1 | ✓ exact_match | https://www.aljazeera.com/news/2026/5/18/beijing-walks-tightrope-after-ukraine-launches-major-drone-attack-on-moscow |
| 2 | ✓ exact_match | https://www.theguardian.com/world/2026/may/18/china-balancing-act-after-ukrainian-drones-strike-moscow |
| 3 | ✓ exact_match | https://www.abplive.com/news/world/one-indian-worker-died-and-three-other-injured-in-ukrainian-drone-attack-launched-in… |
| 4 | ✓ exact_match | https://economictimes.com/news/international/world-news/indian-national-killed-in-moscow-drone-strike-during-major-ukrai… |
| 5 | ✓ exact_match | https://tass.ru/proisshestviya/27436599 |
| 6 | ✓ exact_match | https://tass.ru/moskovskaya-oblast/27435849 |
| 7 | ✓ exact_match | https://www.bbc.com/ukrainian/articles/clypkn0nll1o |
| 8 | ✓ exact_match | https://www.radiosvoboda.org/a/rosiya-naftova-haluz-npz-udary-drony-ukrayiny-analiz/33581322.html |
| 9 | ✓ exact_match | https://www.lemonde.fr/international/article/2026/05/17/la-russie-desormais-vulnerable-aux-attaques-en-profondeur-des-dr… |
| 10 | ✓ exact_match | https://www.hrw.org/fr/world-report/2026/country-chapters/ukraine |
| 11 | ✓ exact_match | https://legrandcontinent.eu/es/2026/05/11/economia-rusa-ataques-ucranianos-de-drones-han-impedido-rusia-aprovechar-preci… |
| 12 | ✓ exact_match | https://www.albayan.ae/news/world/russia/1293476 |
| 13 | ✓ exact_match | https://www.lsm.lv/raksts/zinas/latvija/07.05.2026-latvijas-teritorija-nokritusi-2-droni-beidzies-gaisa-telpas-apdraudej… |
| 14 | ✓ exact_match | https://www.yna.co.kr/view/AKR20260514003300108 |

**Topic 2** — UAE Barakah drone strike (substrate pool: 110 normalized URLs from parsed queries + regex-recovered URLs from the 1 malformed inner-JSON query)

| # | classification | URL |
|---|---|---|
| 0 | ✓ exact_match | https://www.jpost.com/middle-east/article-896446 |
| 1 | ✓ exact_match | https://www.iranintl.com/en/202605177815 |
| 2 | ✓ exact_match | https://arabic.rt.com/middle_east/1790098-مجلس-التعاون-… |
| 3 | ✓ exact_match | https://www.reuters.com/ar/world/QAYIOS7ZTFIVLNLGY6ANZZLGJI-2026-05-17/ |
| 4 | ✓ exact_match | https://www.aa.com.tr/ar/الدول-العربية/فصيل-… |
| 5 | ✓ exact_match | https://www.dw.com/de/vereinigte-arabische-emirate-vae-barakah-iran-krieg-drohnenangriff-atomkraftwerk-brand/a-77189018 |
| 6 | ✓ exact_match | https://www.france24.com/fr/moyen-orient/20260517-les-emirats-dénoncent-une-agression-inacceptable… |
| 7 | ✓ exact_match | https://www.infobae.com/america/mundo/2026/05/17/un-ataque-con-dron-provoco-un-incendio-en-la-central-nuclear-de-barakah… |
| 8 | ✓ exact_match | https://www.yna.co.kr/amp/view/AKR20260517056151009 |
| 9 | ✓ exact_match | https://www.24k99.com/top/2605/7449659.shtml |
| 10 | ✓ exact_match | https://www.asahi.com/articles/ASV5K5WMPV5KUHBI00XM.html |
| 11 | ✓ exact_match | https://hindi.webdunia.com/international-hindi-news/uae-barakah-nuclear-power-plant-drone-attack-abu-dhabi-fire-india-re… |
| 12 | ✓ exact_match | https://www.rainews.it/amp/articoli/ultimora/drone-su-emirati-rogo-centrale-nucleare-f3e1b2fb-a127-4b3b-8367-065493ed2cf… |
| 13 | ✓ exact_match | https://g1.globo.com/mundo/noticia/2026/05/17/ataque-de-drone-provoca-incendio-em-usina-nuclear-dos-emirados-arabes-e-au… |
| 14 | ✓ exact_match | https://tuoitre.vn/nha-may-dien-hat-nhan-cua-uae-bi-drone-danh-trung-20260517200308028.htm (recovered via regex fallback on query[22]'s malformed inner JSON) |

### Check A summary

| classification | count |
|---|---|
| exact_match | **45** |
| normalized_match | 0 |
| no_match (fabrication) | **0** |
| **TOTAL** | **45** |

**Check A verdict: PASS** — 0 fabricated URLs across all 45. Every URL the model emitted is present in the substrate. No normalization tolerance was even needed; all 45 matched exactly to the raw substrate URL.

## Check B — Quote integrity (10 random `actors_quoted`)

`random.seed(20260518)` → 10 samples drawn from the union of 28 actors_quoted entries across the 3 topic outputs.

| # | topic / source | actor | position (candidate) | substrate evidence | class |
|---|---|---|---|---|---|
| 1 | 2 / [10] Asahi (ja) | UAE Foreign Ministry | "Condemned the targeting of nuclear facilities as a violation of international law." | "外務省は原子力施設を標的とする行為は国際法違反と非難。" (The Foreign Ministry condemned the targeting of nuclear facilities as a violation of international law.) | ✓ supported |
| 2 | 1 / [6] TASS (ru) | Moscow Mayor Sergei Sobyanin | "Reported that air defence forces shot down more than 120 drones heading toward the capital over the past day." | "Мэр Москвы сообщил, что силами ПВО за сутки было сбито более 120 БПЛА, летевших в сторону столицы." (The Moscow Mayor reported that air defence forces shot down more than 120 UAVs heading toward the capital over the past day.) | ✓ supported |
| 3 | 2 / [10] Asahi (ja) | IAEA | "Stressed that military actions threatening nuclear safety are unacceptable." | "原子力の安全を脅かす軍事行動は許容されないと強調した" (Stressed that military actions threatening nuclear safety are not acceptable.) | ✓ supported |
| 4 | 1 / [4] Economic Times (en) | Embassy of India in Russia | "Stated it is closely cooperating with the company's management and local authorities to provide necessary assistance." | "It cites an official statement from the Embassy of India in Russia, which says it is closely cooperating with the company's management and local authorities to provide necessary assistance." | ✓ supported (verbatim) |
| 5 | 1 / [1] Al Jazeera (en) | China's Foreign Ministry | "Expressed concern over escalation and repeated calls for dialogue, while carefully avoiding language that would alienate Russia or European partners." | "China expressed 'concern' over the escalation and repeated calls for dialogue, while carefully avoiding language that would alienate either Russia or key European partners." | ✓ supported (verbatim — note that the substrate frames the actor as "China" rather than "China's Foreign Ministry", but the position itself is verbatim and the ministry-level attribution is the conventional reading for state-level diplomatic posture) |
| 6 | 2 / [8] Yonhap (ko) | KEPCO | "Confirmed that no South Korean staff were harmed and that the attack targeted external power facilities, not the reactor core." | "한국전력(KEPCO)…한전은 파견 직원 피해가 없다고 밝혔다" (KEPCO stated that there is no damage to dispatched staff) — the staff-safety claim is directly attributed to KEPCO. The "external power facilities, not the reactor core" framing is in the substrate (the article describes "바라카 원전 내부 경계 외곽 발전기가 드론 공격" — a generator outside the inner perimeter of the Barakah plant was hit) but the substrate attributes that description to the Abu Dhabi government announcement, not KEPCO. The model compressed two attributions in the article into one position string. | ◐ plausible-not-explicit |
| 7 | 2 / [6] France 24 (fr) | AIEA (IAEA) | "Expressed 'great concern' about risks to nuclear safety." | "l'AIEA exprime sa « grande inquiétude » quant aux risques pour la sûreté nucléaire" | ✓ supported (verbatim translation) |
| 8 | 2 / [6] France 24 (fr) | UAE government | "Described the attack as an 'unacceptable aggression' and a 'dangerous escalation', calling it a terrorist attack." | "Abou Dhabi parle d' « agression inacceptable » et de « dangereuse escalade » … Le gouvernement évoque une attaque « terroriste »" | ✓ supported (verbatim translation) |
| 9 | 1 / [8] Radio Svoboda (uk) | Security Service of Ukraine (SBU) | "Claims that drone strikes have taken about 37% of Russia's oil refining capacity offline." | "За даними СБУ, удари безпілотників вивели з ладу близько 37% нафтопереробних потужностей Росії." (According to the SBU, drone strikes have put out of service about 37% of Russia's oil refining capacity.) | ✓ supported (verbatim figure + attribution) |
| 10 | 0 / [5] Nournews (fa) | Mohammad Bagher Ghalibaf (Speaker of the Iranian Parliament) | "Warns that Trump's 'baseless moves' will turn America into a real hell for American families and set the region on fire due to obedience to Netanyahu's orders; calls for respect for the Iranian nation." Verbatim quote: "حرکت‌های بی‌اساس ترامپ آمریکا را به جهنمی واقعی برای خانواده‌های آمریکایی تبدیل می‌کند و منطقه را به‌دلیل اطاعت از دستورات نتانیاهو به آتش خواهد کشید" | Substrate carries the identical Farsi sentence: "«حرکت‌های بی‌اساس» ترامپ آمریکا را به «جهنمی واقعی» برای خانواده‌های آمریکایی تبدیل می‌کند و منطقه را به‌دلیل اطاعت از دستورات نتانیاهو به آتش خواهد کشید" | ✓ supported (verbatim quote pulled from substrate) |

### Check B summary

| classification | count |
|---|---|
| ✓ supported | **9** |
| ◐ plausible-not-explicit | **1** |
| ✗ no support | **0** |
| ⚠ contradiction | **0** |
| **TOTAL** | **10** |

The one ◐ (sample 6, KEPCO) is a multi-clause attribution where one clause is directly attested to the named actor and the second clause is a substrate-attested fact attributed to a different actor in the substrate. No fabrication; minor compression. Below the contradiction and no-support thresholds.

**Check B verdict: PASS** — 0 contradictions, 0 no-support, ≤ the ≤1-no-support threshold.

## Verdict

**GO** — both gates clear. Check A: 45 / 45 URLs verified against substrate (0 fabrications). Check B: 9 directly supported quotes, 1 plausible-not-explicit (minor multi-clause attribution compression), 0 no-support, 0 contradictions. Candidate `dskflash-t05-rnone` is cleared for the Phase 2 production swap pending architect "proceed".
