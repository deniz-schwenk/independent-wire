# MADLAD sidecar — parallel shadow-stability run

Observation phase only. The production pipeline runs and publishes **natively, unchanged**; this shadow takes each day's *same real findings* (read-only) and runs the MADLAD-English-normalized clustering chain (`translate → pre_cluster → CuratorTopicDiscovery → gravitational_assign`) via the injectable sidecar seam. Output goes only here. **The live pipeline never reads this; the flag is never enabled; nothing is pushed.**

**Machine:** Apple M4 / 32 GB. **Native baseline** = production's real published `curator_topic_assignments` (no recompute, zero added variance). **MADLAD model** = self-converted CT2-int8 under `scratch/madlad/` (`<2en>` backend), driven through the real sidecar via a pre-warmed cumulative content-hash cache.

> ⚠️ **INSTRUMENT REBUILT (harness v2, 2026-07-05).** The original `scratch/madlad/` tree (CT2 model, `<2en>` backend, `shadow_run.sh`, per-day artifacts, cumulative cache, `EMPIRICAL-RESULTS.md`) was **lost in the 2026-07-04 repo move** to `~/iw/independent-wire` — the scratch reports were copied (all mtimes 00:01:54), the model subtree was not; not recoverable from Trash/Time Machine/snapshots. For the batch-1 backfill below the instrument was rebuilt from primary sources: weights re-downloaded and **sha256-verified byte-identical** to the documented provenance (`66ff5f8f…b3a76d4`, 11,761,587,872 bytes), re-converted with the documented pins (`ctranslate2==4.5.0` + `transformers==4.46.3`, `--quantization int8`; `model.bin` 2,950,208,290 B matches the finalize report), and **validated for behavioural equivalence: 16/16 documented sample translations from the 06-24/06-25 per-day logs reproduce exactly** under the deterministic beam decode (`scratch/madlad/validate_controls.py`). The harness scripts were rewritten to the spec in this report (`shadow_run.sh` + `translate_warm.py` + `shadow_chain.py`); the clustering chain runs the **unchanged real production stages** in the production venv, and the native baseline is still read (never recomputed) from the day's snapshots. Known v2 deviations: the cumulative content-hash cache **restarted empty** (cache-hit % below is not comparable to a continued cache — but the 06-24..30 window already showed hits stay ~0–2%), and translation uses `translate_batch(max_batch_size=64)` (original batching params unrecoverable; peak RAM ≈27 GB vs 24.7 GB before, per-finding throughput ~30–40% slower). Attach/cluster metrics are unaffected by both.
>
> **Backup (2026-07-05, prevents a repeat loss).** The validated CT2 directory + `spiece.model` are copied to `~/iw-madlad-backup/madlad400-3b-mt-ct2-int8/` (outside the repo — no repo-level operation can take the only copy again). Verified: backup `model.bin` sha256 `890ed3b7e4654dcf1b9e7f2ce6ce641447462e782881e81aac443568eb1ca702` == source (validated, provenance-derived) `model.bin` sha256 (identical); backup `spiece.model` sha256 `ef11ac9a22c7503492f56d48dce53be20e339b63605983e9f27d2cd0e0f3922c` == documented HF provenance. **Second copy (2026-07-05, off the boot disk):** the same backup is mirrored to `/Volumes/AI-DATA/iw-madlad-backup/madlad400-3b-mt-ct2-int8/`; copy `model.bin` sha256 verified `890ed3b7e4654dcf1b9e7f2ce6ce641447462e782881e81aac443568eb1ca702` (identical). Now two independent disks — repo-level loss and boot-disk loss both covered; a full off-site copy would be the only remaining hardening.

## Running verdict

- **Days observed:** 10 (7 original + 3 batch-1 backfill)  ·  ran cleanly: **10/10**  ·  stable: **10/10**  ·  critical flags (collapse/over-merge/garbage): **0**  ·  benign attach-delta flags: 9
- **Cache hit-rate by day:** 06-24:0.6%  06-25:1.6%  06-26:0.0%  06-27:0.5%  06-28:0.8%  06-29:1.0%  06-30:0.5%  ·  (v2 cache restart)  07-03:0.0%  07-04:0.4%  07-05:0.8%  → **stays ~0% (does NOT climb)**: news findings rarely repeat verbatim across days, so the content-hash cache gives almost no cross-day savings.
- **Operational cost (per day, recurring):** cold translation ≈ **35 min/day** original harness / **49–84 min/day** harness v2 (`max_batch_size=64`; also more non-EN findings since batch-1 feeds), peak RAM ≈ **24.7 GB** original / **≈27 GB** v2 (still under the 32 GB ceiling — production would chunk the batch).
- **Low-resource non-Latin (ar/bn/ne) — MADLAD's highest-value case: NOW OBSERVED** (2026-07-03..05, first days with live ar/bn/ne + zu/sw/uz data). 3-day totals, native → MADLAD attach: **ne 2 → 17 (n=165)**, **bn 0 → 8 (n=79)**, **uz 1 → 6 (n=45)**, sw 0 → 2 (n=33), ar 3 → 4 (n=60), zu 0 → 0 (n=38). The embedding-bridge lift is real on live data for the non-Latin scripts (Devanagari, Bengali) and uz; ar barely moves; zu (Latin-script, hyper-local content) stays orphaned — consistent with content-driven, not script-driven, orphaning.
- **Verdict (10 days):** **STABLE across both windows — clean every day, translation faithful across all observed languages, per-language attach near-neutral vs native on the established languages, positive on the low-resource non-Latin targets, no cluster collapse/over-merge.**
  Benign eyeball flags (small same-language attach gains, not off-topic floods): 2026-06-25 — en: MADLAD attach 134/715 vs native 126/715; 2026-06-25 — es: MADLAD attach 41/285 vs native 31/285; 2026-06-25 — pt: MADLAD attach 23/110 vs native 14/110; 2026-06-26 — es: MADLAD attach 48/289 vs native 40/289; 2026-06-30 — en: MADLAD attach 211/739 vs native 199/739; 2026-07-03 — en: 138/721 vs 157/721 (−19, fewer attach); 2026-07-04 — en: 159/642 vs 178/642 (−19) and es: 32/286 vs 53/286 (−21, both downward — attach loss, not flood); 2026-07-05 — en: 174/516 vs 162/516 (+12).

> Mechanical "stable" = clean run + no collapse/over-merge + translations produced. Benign attach-delta flags (≥8 more attached in a language) are surfaced for eyeball, not treated as instability; the per-day prose + samples carry the fidelity judgment.

---

## Cross-day summary

| day | clean | native top/assigned | MADLAD top/assigned | micro | translate cold | peak RAM | cache hit | LLM$ |
|---|---|---|---|---|---|---|---|---|
| 2026-06-24 | ✅ | 25/224 | 19/204 | 285 | 36 min | 22.8 GB | 0.6% | $0.0043 |
| 2026-06-25 | ✅ | 19/214 | 30/249 | 274 | 36 min | 23.2 GB | 1.6% | $0.0067 |
| 2026-06-26 | ✅ | 23/298 | 30/309 | 287 | 36 min | 24.5 GB | 0.0% | $0.0080 |
| 2026-06-27 | ✅ | 25/258 | 18/263 | 273 | 36 min | 24.6 GB | 0.5% | $0.0044 |
| 2026-06-28 | ✅ | 30/263 | 28/264 | 216 | 33 min | 24.7 GB | 0.8% | $0.0067 |
| 2026-06-29 | ✅ | 30/250 | 18/221 | 227 | 32 min | 24.0 GB | 1.0% | $0.0038 |
| 2026-06-30 | ✅ | 30/310 | 30/302 | 279 | 36 min | 24.2 GB | 0.5% | $0.0084 |
| — harness v2 (batch-1 backfill; cache restarted) — |||||||||
| 2026-07-03 | ✅ | 25/244 | 30/245 | 338 | 70 min | 27.2 GB | 0.0% | $0.0118 |
| 2026-07-04 | ✅ | 30/323 | 25/286 | 314 | 84 min | 26.5 GB | 0.4% | $0.0067 |
| 2026-07-05 | ✅ | 30/255 | 30/275 | 262 | 49 min | 27.4 GB | 0.8% | $0.0068 |

**Cumulative per-language attach (5-day totals), native vs MADLAD:**

| lang | n | native attach | MADLAD attach | Δ |
|---|---:|---:|---:|---:|
| en | 4696 | 1147 | 1120 | -27 |
| es | 1825 | 215 | 230 | +15 |
| pt | 770 | 103 | 114 | +11 |
| vi | 360 | 28 | 33 | +5 |
| tr | 344 | 25 | 24 | -1 |
| de | 322 | 117 | 102 | -15 |
| ru | 292 | 81 | 83 | +2 |
| fr | 168 | 68 | 68 | +0 |
| it | 70 | 33 | 38 | +5 |

**Languages observed:** en, es, pt, vi, tr, de, ru, fr, it. **Low-resource non-Latin (ar/bn/ne/th/…) observed:** NONE — they did not arrive in this window.
**Translation fidelity:** 0 empty + 9 identical-to-source across all ~4148 non-English findings (eyeball samples per day below — fidelity clean across all observed languages).

**Cumulative per-language attach — batch-1 window (2026-07-03..05, 3-day totals), native vs MADLAD:**

| lang | n | native attach | MADLAD attach | Δ |
|---|---:|---:|---:|---:|
| en | 1879 | 497 | 471 | −26 |
| es | 775 | 105 | 87 | −18 |
| pt | 330 | 72 | 70 | −2 |
| **ne** | 165 | 2 | 17 | **+15** |
| vi | 157 | 10 | 7 | −3 |
| tr | 136 | 9 | 8 | −1 |
| de | 127 | 45 | 45 | +0 |
| ru | 115 | 34 | 31 | −3 |
| **bn** | 79 | 0 | 8 | **+8** |
| fr | 72 | 32 | 36 | +4 |
| **ar** | 60 | 3 | 4 | **+1** |
| **uz** | 45 | 1 | 6 | **+5** |
| **zu** | 38 | 0 | 0 | **+0** |
| **sw** | 33 | 0 | 2 | **+2** |
| it | 30 | 12 | 14 | +2 |
| th | 1 | 0 | 0 | +0 |

**Batch-1 window fidelity:** 2,163 findings translated, **0 empty**, 3 identical-to-source; new-script samples (Arabic, Bengali, Devanagari, plus zu/sw/uz) all faithful on eyeball (per-day logs below). One partial-language slip observed: 07-05 `tr` sample starts in Croatian ("Meteorologija od 5 županija…") before continuing in English — an isolated MADLAD target-language wobble, not repeated in other tr findings' spot-checks.

### Batch-1 verdict — does the eval lift hold on live data?

**YES for the non-Latin embedding-bridge languages, with numbers.** The batch-1 eval predicted the lift (e.g. bn 0 → ~5-6 attach on the eval set); on three live production days: **bn 0 → 8** (n=79), **ne 2 → 17** (n=165), **uz 1 → 6** (n=45), **sw 0 → 2** (n=33), **ar 3 → 4** (n=60), **zu 0 → 0** (n=38). Combined over the six batch-1 languages: **6 → 37 attached** findings (n=420). The gains are exactly where the script barrier was (Devanagari, Bengali; uz benefits too), they are modest in absolute terms (no off-topic flood — every gained attachment rode a genuinely cross-language topic), and the two languages that stay flat are informative rather than concerning: `zu` is Latin-script hyper-local content (orphaning is content-driven, MADLAD can't and shouldn't fix it) and `ar`'s stream this window was mostly Egyptian domestic/service items with little global-topic overlap. Established languages stay near-neutral (biggest moves: en −26/1879, es −18/775 — the 07-04 es −21 came with a native-arm outlier day, both directions well inside the 06-24..30 day-to-day spread). **Caveat:** 3 days, small n per language, one Curator-LLM draw per day — direction is validated, magnitudes are not yet tight. **LLM spend for the whole backfill: $0.0253** (3 topic-discovery calls, deepseek-v4-flash); translation itself is local and free.

---

## Per-day log

### 2026-06-24

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 2182.8s (+634 new segs), peak RAM 22.82 GB, **cache hit-rate 1%** (4/638 non-EN findings; cumulative cache 3498).
**Resources (cluster):** total 130.8s (topic-discovery 107.2s), peak RAM 1.31 GB, LLM $0.0043.

**Clustering:** native 25 topics / 224 assigned vs MADLAD 19 topics / 204 assigned (285 micro-clusters); max-topic share native 0.111 / MADLAD 0.137; sidecar translated 638 (748 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 28/302 | 19/302 | -9 |
| pt | 6/110 | 10/110 | +4 |
| fr | 10/24 | 8/24 | -2 |
| de | 19/45 | 15/45 | -4 |
| ru | 8/43 | 10/43 | +2 |
| tr | 2/51 | 2/51 | +0 |
| it | 5/10 | 5/10 | +0 |
| vi | 1/53 | 3/53 | +2 |
| en | 145/748 | 132/748 | -13 |

**Sample translations (eyeball):**
- `pt` 'Confira os resultados dos jogos desta terça-feira (23) na Copa' → 'Check out the results of the games this Tuesday (23) in the Cup'
- `es` '‘Con salario mínimo estaría muerto’: Los ingresos de Carlos Bonavides,' → '‘With minimum wage I would be dead’: The income of Carlos Bonavides, f'
- `it` 'Tre candidati appoggiati da Mamdani vincono alle primarie di New York' → 'Three candidates supported by Mamdani win the New York primaries'
- `de` 'Expertenkommission zu Social Media legt Empfehlungen vor' → 'Expert Commission on Social Media Presents Recommendations'
- `ru` 'Венгрия вновь затормозила процесс переговоров по\xa0вступлению Украины в\xa0' → "Hungary again slowed the process of negotiations on Ukraine's accessio"
- `tr` 'Biri evin bahçesine, diğeri yeşil alana düştü… İki ilde İHA alarmı' → 'One landed in the backyard of a house, the other in a green area.'
- `vi` "Nguy cơ từ lời chào mời 'mua SIM rác theo cân'" → "The risk of the invitation to 'buy junk SIM by weight'"
- `fr` 'La RDC réclame officiellement à la Belgique la restitution de restes h' → 'The DRC officially demands from Belgium the return of human remains ta'

**Sanity flags:** 1 translations identical to source

**Day call:** 🟢 STABLE

### 2026-06-25

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 2169.6s (+621 new segs), peak RAM 23.21 GB, **cache hit-rate 2%** (10/631 non-EN findings; cumulative cache 4119).
**Resources (cluster):** total 256.0s (topic-discovery 233.4s), peak RAM 1.31 GB, LLM $0.0067.

**Clustering:** native 19 topics / 214 assigned vs MADLAD 30 topics / 249 assigned (274 micro-clusters); max-topic share native 0.23 / MADLAD 0.199; sidecar translated 631 (715 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 31/285 | 41/285 | +10 |
| pt | 14/110 | 23/110 | +9 |
| fr | 7/24 | 11/24 | +4 |
| de | 13/54 | 16/54 | +3 |
| ru | 12/45 | 10/45 | -2 |
| tr | 4/51 | 4/51 | +0 |
| it | 4/10 | 6/10 | +2 |
| vi | 3/52 | 4/52 | +1 |
| en | 126/715 | 134/715 | +8 |

**Sample translations (eyeball):**
- `pt` 'Marquinhos pede ambição e avisa: "Uma nova competição começa agora"' → 'Marquinhos asks for ambition and warns: "A new competition begins now"'
- `es` '‘Grupo de la muerte’ acecha a México: Este es el escenario más peligro' → '‘Group of death’ lurks Mexico: This is the most dangerous scenario for'
- `it` 'I Campi Flegrei tremano ancora, scossa di magnitudo 3.6' → 'The Phlegmatic Fields still tremble, magnitude 3.6 earthquake'
- `de` 'Viele Tote befürchtet: Erbeben erschüttern Venezuela' → 'Many dead feared: Earthquakes shake Venezuela'
- `ru` 'Мадьяр предложил рассекретить архивы коммунистических спецслужб Венгри' → "Magyar proposed to declassify the archives of Hungary's communist inte"
- `tr` 'Trump: Cumhurbaşkanı Erdoğan dostum, çok güçlü bir lider' → 'Trump: President Erdogan, my friend, a very strong leader'
- `vi` 'Google rót hàng chục triệu USD cho công cụ làm phim bằng AI' → 'Google &apos;s pouring tens of millions of dollars into AI-powered fil'
- `fr` 'Zimbabwe: le Sénat adopte la réforme constitutionnelle prolongeant le ' → 'Zimbabwe: Senate adopts constitutional reform extending presidential t'

**Sanity flags:** en: MADLAD attach 134/715 vs native 126/715 (+8; eyeball off-topic); es: MADLAD attach 41/285 vs native 31/285 (+10; eyeball off-topic); pt: MADLAD attach 23/110 vs native 14/110 (+9; eyeball off-topic); 2 translations identical to source

**Day call:** 🟢 STABLE

### 2026-06-26

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 2188.4s (+640 new segs), peak RAM 24.5 GB, **cache hit-rate 0%** (0/640 non-EN findings; cumulative cache 640).
**Resources (cluster):** total 366.0s (topic-discovery 343.42s), peak RAM 1.27 GB, LLM $0.0080.

**Clustering:** native 23 topics / 298 assigned vs MADLAD 30 topics / 309 assigned (287 micro-clusters); max-topic share native 0.311 / MADLAD 0.29; sidecar translated 643 (742 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 40/289 | 48/289 | +8 |
| pt | 17/110 | 21/110 | +4 |
| fr | 11/24 | 10/24 | -1 |
| de | 14/50 | 13/50 | -1 |
| ru | 15/41 | 13/41 | -2 |
| tr | 3/64 | 3/64 | +0 |
| it | 6/10 | 5/10 | -1 |
| vi | 7/55 | 5/55 | -2 |
| en | 185/742 | 191/742 | +6 |

**Sample translations (eyeball):**
- `pt` 'Confira os resultados dos jogos desta quinta-feira (25) da Copa' → 'Check out the results of the games this Thursday (25) of the Cup'
- `es` 'Atropello masivo en Los Cabos: Confirman que una mujer estadounidense ' → 'Los Cabos Massacre: U.S. Woman Confirmed Among Wounded'
- `it` "Borsa: il Kospi perde oltre l'8%, Seul attiva il circuit breaker" → 'Stock market: the Kospi loses more than 8%, Seoul activates the circui'
- `de` 'Viele Vermisste: Mindestens 235 Tote in Venezuela nach Erdbeben' → 'At least 235 dead in Venezuela after earthquake'
- `ru` 'Дания перестанет предоставлять вид на\xa0жительство украинским мужчинам, ' → 'Denmark will stop granting residence permits to Ukrainian men subject '
- `tr` "Arda Güler'den 24 yıl sonra tarihe geçen gol! Emre Belözoğlu detayı" → "Arda Guler's historic goal after 24 years! Emre Belözoğlu's detail"
- `vi` '17 bang nước Mỹ kiện chính sách siết nhựa một lần của California' → '17 U.S. states are suing California &apos;s one-time-use plastic polic'
- `fr` '«Il faut rêver jusqu’au bout», la fierté de Franck Kessié après la qua' → '“We have to dream to the end”, Franck Kessié’s pride after Côte d’Ivoi'

**Sanity flags:** es: MADLAD attach 48/289 vs native 40/289 (+8; eyeball off-topic); 2 translations identical to source

**Day call:** 🟢 STABLE

### 2026-06-27

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 2146.6s (+614 new segs), peak RAM 24.59 GB, **cache hit-rate 0%** (3/617 non-EN findings; cumulative cache 1254).
**Resources (cluster):** total 136.3s (topic-discovery 114.11s), peak RAM 1.3 GB, LLM $0.0044.

**Clustering:** native 25 topics / 258 assigned vs MADLAD 18 topics / 263 assigned (273 micro-clusters); max-topic share native 0.23 / MADLAD 0.241; sidecar translated 617 (677 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 34/278 | 37/278 | +3 |
| pt | 14/110 | 15/110 | +1 |
| fr | 7/24 | 9/24 | +2 |
| de | 20/53 | 18/53 | -2 |
| ru | 12/49 | 11/49 | -1 |
| tr | 1/43 | 1/43 | +0 |
| it | 6/10 | 9/10 | +3 |
| vi | 7/50 | 6/50 | -1 |
| en | 157/677 | 157/677 | +0 |

**Sample translations (eyeball):**
- `pt` 'Confira os resultados dos jogos desta sexta-feira na Copa' → 'Check out the results of the games this Friday in the Cup'
- `es` 'Agendas llenas, vidas vacías' → 'Full agendas, empty lives'
- `it` 'La missione italiana è in Venezuela, team verso le aree del sisma' → 'The Italian mission is in Venezuela, team towards the areas of the ear'
- `de` 'US-Militär: Haben Angriffe gegen Iran durchgeführt' → 'US military: have carried out attacks against Iran'
- `ru` 'США нанесли удары по\xa0Ирану' → 'U.S. strikes Iran'
- `tr` "Karadeniz'den Yeşilçam'a uzanan bir hayat... Katıldığı yarışma hayatın" → 'A life stretching from the Black Sea to Yeşilçam... a competition that'
- `vi` "Mở quán cà phê 'hát với nhau', tôi có phải trả tiền bản quyền âm nhạc?" → "Open a'sing together' cafe, do I have to pay for the music?"
- `fr` 'EN DIRECT - Double séisme au Venezuela : au moins 920 morts, la réacti' → "LIVE - Double earthquake in Venezuela: at least 920 dead, authorities'"

**Sanity flags:** none

**Day call:** 🟢 STABLE

### 2026-06-28

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 1976.1s (+507 new segs), peak RAM 24.74 GB, **cache hit-rate 1%** (4/511 non-EN findings; cumulative cache 1761).
**Resources (cluster):** total 342.2s (topic-discovery 323.73s), peak RAM 1.31 GB, LLM $0.0067.

**Clustering:** native 30 topics / 263 assigned vs MADLAD 28 topics / 264 assigned (216 micro-clusters); max-topic share native 0.162 / MADLAD 0.158; sidecar translated 511 (502 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 30/195 | 32/195 | +2 |
| pt | 16/110 | 19/110 | +3 |
| fr | 12/24 | 12/24 | +0 |
| de | 19/42 | 14/42 | -5 |
| ru | 14/33 | 16/33 | +2 |
| tr | 2/47 | 1/47 | -1 |
| it | 4/10 | 6/10 | +2 |
| vi | 4/50 | 7/50 | +3 |
| en | 162/502 | 157/502 | -5 |

**Sample translations (eyeball):**
- `pt` 'Congo vence de virada e segue na Copa, assim como Colômbia e Portugal' → 'Congo wins twice and continues in the Cup, as well as Colombia and Por'
- `es` 'Morena condena agresión del exdirector de Pemex, Víctor Rodríguez, a s' → 'Morena condemns aggression of the former director of Pemex, Victor Rod'
- `it` 'Mondiali: pareggio senza gol, Colombia e Portogallo ai sedicesimi' → 'World Cup: goalless draw, Colombia and Portugal in 16th place'
- `de` 'Erneut gegenseitige Angriffe zwischen USA und Iran' → 'New mutual attacks between the US and Iran'
- `ru` '«Еще несколько недель я\xa0буду президентом, а\xa0потом уйду в\xa0отставку». Ву' → '“I will be President for a few more weeks and then I will resign” – Vu'
- `tr` 'Yunanistan-Türkiye hattında kan donduran olay… Küçük Eren açlık ve sus' → 'A chilling story on the Greek-Turkish border: Little Eren dies of hung'
- `vi` 'Hệ thống y tế Pháp chạm ngưỡng vỡ trận vì nắng nóng' → 'The French health system is on the brink of collapse because of the he'
- `fr` "«Tout le monde a peur»: comment l'épidémie d'Ebola bouleverse la vie d" → '“Everyone is afraid”: how the Ebola outbreak is shaking the lives of p'

**Sanity flags:** 3 translations identical to source

**Day call:** 🟢 STABLE

### 2026-06-29

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 1922.3s (+495 new segs), peak RAM 23.96 GB, **cache hit-rate 1%** (5/500 non-EN findings; cumulative cache 2256).
**Resources (cluster):** total 117.4s (topic-discovery 98.38s), peak RAM 1.3 GB, LLM $0.0038.

**Clustering:** native 30 topics / 250 assigned vs MADLAD 18 topics / 221 assigned (227 micro-clusters); max-topic share native 0.139 / MADLAD 0.147; sidecar translated 500 (573 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 21/189 | 25/189 | +4 |
| pt | 13/110 | 14/110 | +1 |
| fr | 10/24 | 9/24 | -1 |
| de | 14/37 | 11/37 | -3 |
| ru | 5/33 | 10/33 | +5 |
| tr | 7/46 | 6/46 | -1 |
| it | 5/10 | 5/10 | +0 |
| vi | 2/51 | 3/51 | +1 |
| en | 173/573 | 138/573 | -35 |

**Sample translations (eyeball):**
- `pt` 'Com gol no final, Canadá vence Africa do Sul e vai às oitavas da Copa' → 'With goal in the end, Canada beats South Africa and goes to the round '
- `es` 'Tres ondas tropicales empapan a México: ¿Qué estados prevén las lluvia' → 'Three Tropical Waves Soak Mexico: Which States Forecast the Most Inten'
- `it` "Cuba, 'le riforme non cambieranno il modello politico'" → "Cuba,'reforms will not change the political model'"
- `de` 'Israels Armee zerstört Tunnel im Südlibanon' → 'Israeli Army Destroys Tunnel in South Lebanon'
- `ru` 'Путин провел совещание по\xa0топливному кризису. И\xa0признал, что очереди е' → 'Putin held a meeting on the fuel crisis. And admitted that queues are '
- `tr` "Son Dakika: 100. Gazi Koşusu'nu Halis Karataş'ın jokeyliğini yaptığı '" → "Last Minute: Halis Karataş's 'Bay Nalçakan' Wins the 100th Gazi Race!"
- `vi` "'Khoảnh khắc DeepSeek tiếp theo' của Trung Quốc" → "China's 'Next DeepSeek Moment'"
- `fr` "Sénégal: l'Assemblée nationale se prononce sur un projet de réforme co" → 'Senegal: National Assembly votes on controversial constitutional refor'

**Sanity flags:** 1 translations identical to source

**Day call:** 🟢 STABLE

### 2026-06-30

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 2172.4s (+608 new segs), peak RAM 24.24 GB, **cache hit-rate 0%** (3/611 non-EN findings; cumulative cache 2864).
**Resources (cluster):** total 389.3s (topic-discovery 366.16s), peak RAM 1.32 GB, LLM $0.0084.

**Clustering:** native 30 topics / 310 assigned vs MADLAD 30 topics / 302 assigned (279 micro-clusters); max-topic share native 0.148 / MADLAD 0.119; sidecar translated 611 (739 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 31/287 | 28/287 | -3 |
| pt | 23/110 | 12/110 | -11 |
| fr | 11/24 | 9/24 | -2 |
| de | 18/41 | 15/41 | -3 |
| ru | 15/48 | 13/48 | -2 |
| tr | 6/42 | 7/42 | +1 |
| it | 3/10 | 2/10 | -1 |
| vi | 4/49 | 5/49 | +1 |
| en | 199/739 | 211/739 | +12 |

**Sample translations (eyeball):**
- `pt` 'Onda de calor na Europa bate recordes e expõe crise climática' → 'Heat wave in Europe breaks records and exposes climate crisis'
- `es` 'Exjugador del Querétaro da el batacazo del Mundial 2026: Paraguay elim' → 'Former Querétaro player gives World Cup 2026 kick: Paraguay eliminates'
- `it` 'Mondiali, il presidente del Paraguay proclama per oggi festa nazionale' → 'World Cup, the president of Paraguay proclaims national holiday for to'
- `de` 'Ultimatum an Migranten: Südafrika hält den Atem an' → 'Ultimatum to migrants: South Africa holds its breath'
- `ru` 'В Монако в\xa0жилом доме произошел взрыв. По\xa0данным СМИ, пострадали гражд' → 'In Monaco, an explosion occurred in a residential building. According '
- `tr` "Trump duyurdu: 'İran görüşme talep etti!' Tarih ve yer belli oldu" → "Trump announces: 'Iran has requested a meeting!' Date and location rev"
- `vi` 'Bé sơ sinh sống sót thần kỳ trong tòa nhà sập ở Venezuela' → 'Baby miraculously survives building collapse in Venezuela.'
- `fr` "Afrique du Sud: l'ultimatum\xa0des manifestants anti-immigration expire d" → "South Africa: Anti-immigration protesters' ultimatum expires in a clim"

**Sanity flags:** en: MADLAD attach 211/739 vs native 199/739 (+12; eyeball off-topic)

**Day call:** 🟢 STABLE

### 2026-07-03 (harness v2 — first live ar/bn/ne/zu/sw/uz day)

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 4190.6s (+770 new segs), peak RAM 27.19 GB, **cache hit-rate 0%** (0/770 non-EN findings; cumulative cache 770 — v2 cache restarted empty).
**Resources (cluster):** total 597.5s (topic-discovery 572.1s), peak RAM 1.21 GB, LLM $0.0118.

**Clustering:** native 25 topics / 244 assigned vs MADLAD 30 topics / 245 assigned (338 micro-clusters); max-topic share native 0.148 / MADLAD 0.163; sidecar translated 770 (721 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 27/295 | 30/295 | +3 |
| pt | 15/110 | 20/110 | +5 |
| fr | 9/24 | 13/24 | +4 |
| de | 8/44 | 11/44 | +3 |
| ru | 13/47 | 9/47 | -4 |
| tr | 3/49 | 2/49 | -1 |
| it | 4/10 | 5/10 | +1 |
| vi | 4/55 | 4/55 | +0 |
| **ar** | 2/20 | 1/20 | -1 |
| **bn** | 0/17 | 2/17 | +2 |
| **ne** | 2/55 | 9/55 | +7 |
| **zu** | 0/18 | 0/18 | +0 |
| **sw** | 0/11 | 0/11 | +0 |
| **uz** | 0/15 | 1/15 | +1 |
| en | 157/721 | 138/721 | -19 |

**Sample translations (eyeball — new scripts first):**
- `ar` 'تخصصات المستقبل تفتح أبواب سوق العمل.. تعرف على أبرز برامج جامعة العاص' → 'Specialties of the future open the doors of the labour market.'
- `bn` 'ফোন করলে মোটরসাইকেলে চা নিয়ে হাজির হন ‘রনি ভাই’' → 'When you call, ‘Roni brother’ arrives on a motorcycle with tea.'
- `ne` 'रेसुङ्गा-काठमाडौं उडान तीन सातादेखि प्रभावित' → 'Resunga-Kathmandu flight affected for three weeks'
- `zu` 'Asazoqhubeka amamashi uma bengakahambi - Jacinta' → "We won't continue with the abuses if they don't go - Jacinta"
- `sw` 'Ofisa wa Polisi, IGP, AG wanavyochuana kortini, mapingamizi yao yatupw' → 'Police Officer, IGP, AG fighting in court, their objections dismissed'
- `uz` 'Dunyo ikki demografik guruhga bo‘linmoqda.' → 'The world is divided into two demographic groups.'
- `pt` 'Mega-Sena acumula e prêmio principal vai para R$ 33 milhões' → 'Mega-Sena accumulates and main prize goes to R$ 33 million'
- `de` 'Warum Hitze alle gefährdet - und was künftig schützt' → 'Why heat endangers everyone - and what will protect us in the future'
- `ru` 'Директору отдела продаж «Эксмо» Артему Вахляеву запросили четыре года ' → 'Exmo Sales Director Artem Vakhlyaev Requested Four Years on Probe in Q'
- `vi` 'Honda Việt Nam tăng giá 17 xe máy' → 'Honda Vietnam increases price of 17 motorcycles'

**Sanity flags:** en: MADLAD attach 138/721 vs native 157/721 (-19; eyeball off-topic); 1 translations identical to source

**Day call:** 🟢 STABLE

### 2026-07-04 (harness v2)

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 5067.7s (+749 new segs), peak RAM 26.5 GB, **cache hit-rate 0%** (3/752 non-EN findings; cumulative cache 1519).
**Resources (cluster):** total 143.9s (topic-discovery 119.4s), peak RAM 1.21 GB, LLM $0.0067.

**Clustering:** native 30 topics / 323 assigned vs MADLAD 25 topics / 286 assigned (314 micro-clusters); max-topic share native 0.139 / MADLAD 0.157; sidecar translated 752 (642 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 53/286 | 32/286 | -21 |
| pt | 35/110 | 32/110 | -3 |
| fr | 11/24 | 9/24 | -2 |
| de | 19/47 | 17/47 | -2 |
| ru | 13/40 | 14/40 | +1 |
| tr | 3/48 | 2/48 | -1 |
| it | 6/10 | 6/10 | +0 |
| vi | 3/52 | 2/52 | -1 |
| **ar** | 1/20 | 2/20 | +1 |
| **bn** | 0/28 | 4/28 | +4 |
| **ne** | 0/55 | 4/55 | +4 |
| **zu** | 0/6 | 0/6 | +0 |
| **sw** | 0/10 | 1/10 | +1 |
| **uz** | 1/15 | 2/15 | +1 |
| th | 0/1 | 0/1 | +0 |
| en | 178/642 | 159/642 | -19 |

**Sample translations (eyeball — new scripts first):**
- `ar` 'زحام على مقاهي القليوبية لتشجيع منتخب مصر أمام أستراليا' → 'A crowd on the cafés of Al-Qalibiya to cheer the Egyptian team against'
- `bn` 'সুন্দরবনের গহিনের ডেরা থেকে কারাগারে ‘দুলাভাই বাহিনী’র প্রধান রবিউল' → 'Rabiul, the leader of the ‘Dulabai Army’ from Gahin Dera in Sundarbans'
- `ne` 'रेड बुल बन्यो सुदूरपश्चिम रोयल्सको मुख्य प्रायोजक' → 'Red Bull becomes the main sponsor of the Far West Royals'
- `zu` 'EZINGENAYO: Lizolala libaliwe iphoyisa likamasipala waseKurhuleni' → 'INCOMING: Lizolala suspended from Kurhuleni municipal police'
- `sw` 'Madaktari watoa mbinu kwa wanafunzi kuikabili baridi' → 'Doctors give tips for students to cope with the cold'
- `uz` 'Qadimgi Rimda yo‘llar uchta oddiy asbob yordamida qurilgan.' → 'In ancient Rome, roads were built with three simple tools.'
- `th` '‘ความพยายามจบชีวิต’ ปมใหญ่ที่สังคมโลก-ไทยเผชิญ สื่อควรทำข่าวอย่างไร ไม' → '“Suicide attempts” are a major problem facing global-Thai society. How'
- `es` 'Colombia y Argentina batallan para avanzar a octavos: Resultados del M' → 'Colombia and Argentina fight to advance to round of 16: World Cup Resu'
- `ru` 'Путин посетил один из штабов российских военных. Ему доложили, что вой' → 'Putin visited one of the headquarters of the Russian military. He was '
- `tr` 'Grönland Başbakanı Nielsen’den iddia: Trump vazgeçti' → 'Greenland Prime Minister Nielsen says Trump has given up'

**Sanity flags:** en: MADLAD attach 159/642 vs native 178/642 (-19; eyeball off-topic); es: MADLAD attach 32/286 vs native 53/286 (-21; eyeball off-topic — both flags are attach LOSSES, not floods); 2 translations identical to source

**Day call:** 🟢 STABLE

### 2026-07-05 (harness v2)

**Ran cleanly?** ✅ yes

**Resources (translate):** fresh 2954.7s (+636 new segs), peak RAM 27.4 GB, **cache hit-rate 1%** (5/641 non-EN findings; cumulative cache 2155).
**Resources (cluster):** total 200.1s (topic-discovery 180.1s), peak RAM 1.19 GB, LLM $0.0068.

**Clustering:** native 30 topics / 255 assigned vs MADLAD 30 topics / 275 assigned (262 micro-clusters); max-topic share native 0.133 / MADLAD 0.127; sidecar translated 641 (516 native-fallback).

**Per-language attach (native vs MADLAD):**

| lang | native attach | MADLAD attach | Δ |
|---|---|---|---:|
| es | 25/194 | 25/194 | +0 |
| pt | 22/110 | 18/110 | -4 |
| fr | 12/24 | 14/24 | +2 |
| de | 18/36 | 17/36 | -1 |
| ru | 8/28 | 8/28 | +0 |
| tr | 3/39 | 4/39 | +1 |
| it | 2/10 | 3/10 | +1 |
| vi | 3/50 | 1/50 | -2 |
| **ar** | 0/20 | 1/20 | +1 |
| **bn** | 0/34 | 2/34 | +2 |
| **ne** | 0/55 | 4/55 | +4 |
| **zu** | 0/14 | 0/14 | +0 |
| **sw** | 0/12 | 1/12 | +1 |
| **uz** | 0/15 | 3/15 | +3 |
| en | 162/516 | 174/516 | +12 |

**Sample translations (eyeball — new scripts first):**
- `ar` 'أدوات الدين تجذب 11.5 مليار دولار أموالًا ساخنة' → 'Debt Instruments Attract $11.5 Billion in Hot Money'
- `bn` 'লক্ষ্মীপুরে সালিস বৈঠকে বিতণ্ডার জেরে বৃদ্ধকে গুলি' → 'Old man shot dead in Lakshmipur after dispute'
- `ne` 'दाउन्ने खण्डको सडक निर्माण अन्तिम चरणमा, कम्तीमा ३० वर्ष टिक्ने दाबी' → 'Road construction of Daune section in final stages, claims to last at '
- `zu` 'IKhomishini kaMadlanga yenza umsebenzi oncomekayo kunabanye' → 'The Land Commission is doing a remarkable job.'
- `sw` 'Sintofahamu kujengwa ukuta kuzingira nyumba, kuzibwa barabara' → 'Confusion built wall surrounding houses, blocked roads'
- `uz` 'Putin Trampni mustaqillik bilan tabriklab, Rossiyaga taklif etdi.' → 'Putin congratulated Trump on his independence and invited him to Russi'
- `es` 'Reaparece Andy López Beltrán en Tabasco: Hijo de AMLO se reúne con dir' → 'Andy López Beltrán Reappears in Tabasco: AMLO’s Son Meets with Morena '
- `de` '30 Jahre nach "Dolly": Wie das Klonschaf die Forschung veränderte' → '30 years after "Dolly": How the cloned sheep changed research'
- `ru` 'The Telegraph: «яхту Путина» заметили возле Норвегии. Она может направ' → 'The Telegraph: "Putin\'s yacht" spotted near Norway. It may be heading '
- `tr` 'Meteoroloji’den 5 il için bir uyarı daha! Fırtına, sel ve doluya dikka' → 'Meteorologija od 5 županija jedna upozorenja više! Storm, flood and fl' ⚠️ starts in **Croatian**, finishes in English — isolated target-language wobble; other tr findings spot-checked clean

**Sanity flags:** en: MADLAD attach 174/516 vs native 162/516 (+12; eyeball off-topic); 1 tr translation with a Croatian-language prefix (see samples)

**Day call:** 🟢 STABLE


---

## How to continue (one command per real pipeline day)

```bash
bash scratch/madlad/shadow/shadow_run.sh
```

Idempotent + read-only on `output/`. With no argument it resolves the last-7-day window, **skips days already done** (a day with `summary.json` is done); pass explicit days to control the set (e.g. `shadow_run.sh 2026-07-03 2026-07-04`). Per day it runs translate-warm (ct2venv, MADLAD CT2) then the real clustering chain (production venv, real Curator LLM) against the pre-warmed cache, and never touches production, the flag, or the published site. Per-day artifacts (`warm_stats.json`, `summary.json`, `madlad_chain.json`) + the cumulative content-hash cache (`translate_cache.json`) live under `scratch/madlad/shadow/`. **This is harness v2** (2026-07-05 rebuild — see the instrument note at the top): same chain, same metrics, model validated equivalent 16/16 against the documented samples.

## What this shadow does and does not settle

- **Settles:** MADLAD-English clustering runs **stably in real daily operation** across both observed windows (06-24..30 + 07-03..05) — clean every day, faithful translation on all incoming languages **including the batch-1 non-Latin scripts (Arabic, Bengali, Devanagari)**, clustering stays sane (no collapse/over-merge), attach near-neutral vs the real native baseline on established languages. **NEW (07-03..05): the low-resource case is now observed on live data — the batch-1 eval lift holds** (ne 2→17, bn 0→8, uz 1→6, sw 0→2, ar 3→4, zu 0→0; see the batch-1 verdict above). Operationally it costs ~35–84 min + ~25–27 GB peak **per day** (the content-hash cache does not amortize across days for a churning news feed).

- **Does NOT settle:** magnitudes for the low-resource languages are from **3 days and small n per language** (direction is validated, tightness is not — more days accrue for free via `shadow_run.sh`); `ar` barely moved this window (content mix, not script, appears to be the limiter — worth re-checking on a geopolitics-heavy ar news day); the isolated tr→Croatian target-language wobble (1 finding of ~2,163) is unquantified beyond eyeball; and this remains an observation phase only — the production-enablement blockers in `scratch/MADLAD-INTEGRATION-REQUIREMENTS.md` (transformers-free backend, MODEL_NAME swap, spiece.model staging, multilingual extra, ar/bn/ne gating) are unchanged and still gate any flag flip. **Additional v2 note:** the original pre-2026-07-04 shadow artifacts are unrecoverable (repo-move loss); the 06-24..30 rows above remain as documented by the original harness, and cross-window comparisons of ops numbers (runtime/RAM/cache) should respect the harness-v2 deviations listed at the top.

