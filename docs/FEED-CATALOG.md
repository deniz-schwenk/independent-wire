# Independent Wire — WorldMonitor Feed Reference

**Source:** [github.com/koala73/worldmonitor](https://github.com/koala73/worldmonitor) `src/config/feeds.ts`
**Extracted:** 2026-04-07
**Status:** 74 feeds in sources.json v0.3 (63 enabled, 11 disabled due to 403/404). Target achieved.
**Purpose:** Reference catalog for feed expansion. No code imported.
**Rule:** Google News proxy URLs (news.google.com/rss/search) are BANNED. Must find direct RSS URLs.

**Legend:**
- ✅ = In sources.json (enabled)
- ❌ = In sources.json (disabled — 403/404)
- 🎯 = Priority candidate (needs direct RSS URL)
- ⏭️ = Skip (not relevant for news pipeline)
- ⚠️ = Uses Google News proxy (need direct URL replacement)
- 🚫 = Excluded (tech/finance/startup category)

---

## WorldMonitor Category: `politics` (World News)

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| BBC World | `feeds.bbci.co.uk/news/world/rss.xml` | 🎯 | Direct RSS ✓ |
| Guardian World | `theguardian.com/world/rss` | 🎯 | Direct RSS ✓ |
| AP News | ⚠️ Google News proxy | 🎯 | Need direct URL |
| Reuters World | ⚠️ Google News proxy | 🎯 | Need direct URL |
| CNN World | ⚠️ Google News proxy | ⏭️ | US-centric |


## WorldMonitor Category: `europe`

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| France 24 | `france24.com/en/rss` | 🎯 | Direct RSS ✓. Also FR/ES/AR |
| EuroNews | `euronews.com/rss?format=xml` | 🎯 | Direct RSS ✓. 8 languages |
| Le Monde | `lemonde.fr/en/rss/une.xml` | 🎯 | Direct RSS ✓. EN + FR |
| DW News | `rss.dw.com/xml/rss-en-all` | 🎯 | Direct RSS ✓. EN/DE/ES |
| El País | `feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada` | 🎯 | Direct RSS ✓. ES |
| El Mundo | `e00-elmundo.uecdn.es/elmundo/rss/portada.xml` | ⏭️ | ES only |
| BBC Mundo | `bbc.com/mundo/index.xml` | 🎯 | Direct RSS ✓. ES |
| Tagesschau | `tagesschau.de/xml/rss2/` | 🎯 | Direct RSS ✓. DE |
| Bild | `bild.de/feed/alles.xml` | ⏭️ | Tabloid |
| Der Spiegel | `spiegel.de/schlagzeilen/tops/index.rss` | 🎯 | Direct RSS ✓. DE |
| Die Zeit | `newsfeed.zeit.de/index` | ⏭️ | DE only, secondary |
| ANSA | `ansa.it/sito/notizie/topnews/topnews_rss.xml` | 🎯 | Direct RSS ✓. IT wire service |
| Corriere della Sera | `corriere.it/rss/homepage.xml` | ⏭️ | IT only |
| Repubblica | `repubblica.it/rss/homepage/rss2.0.xml` | ⏭️ | IT only |
| NOS Nieuws | `feeds.nos.nl/nosnieuwsalgemeen` | 🎯 | Direct RSS ✓. NL public |
| NRC | `nrc.nl/rss/` | ⏭️ | NL only |
| SVT Nyheter | `svt.se/nyheter/rss.xml` | ⏭️ | SV only |
| BBC Turkce | `feeds.bbci.co.uk/turkce/rss.xml` | ⏭️ | TR only |
| Hurriyet | `hurriyet.com.tr/rss/anasayfa` | ⏭️ | TR only |
| TVN24 | `tvn24.pl/swiat.xml` | ⏭️ | PL only |
| BBC Russian | `feeds.bbci.co.uk/russian/rss.xml` | 🎯 | Direct RSS ✓. RU independent view |
| Meduza | `meduza.io/rss/all` | 🎯 | Direct RSS ✓. RU independent (exile) |
| Novaya Gazeta Europe | `novayagazeta.eu/feed/rss` | 🎯 | Direct RSS ✓. RU independent |
| TASS | ⚠️ Google News proxy | ⏭️ | State-directed, proxy banned |
| RT | `rt.com/rss/` | 🎯 | Direct RSS ✓. State-directed (transparency) |
| Kyiv Independent | ⚠️ Google News proxy | 🎯 | Need direct: kyivindependent.com/feed/ |
| Moscow Times | `themoscowtimes.com/rss/news` | ✅ | Already in sources.json |

## WorldMonitor Category: `middleeast`

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| BBC Middle East | `feeds.bbci.co.uk/news/world/middle_east/rss.xml` | 🎯 | Direct RSS ✓ |
| Al Jazeera | `aljazeera.com/xml/rss/all.xml` | ✅ | Already in sources.json |
| Al Arabiya EN | ⚠️ Google News proxy | 🎯 | EN blocks cloud IPs per WM notes |
| Al Arabiya AR | `alarabiya.net/tools/mrss/?cat=main` | 🎯 | Direct RSS ✓. AR |
| Guardian ME | `theguardian.com/world/middleeast/rss` | ⏭️ | Duplicate of Guardian World |
| BBC Persian | `feeds.bbci.co.uk/persian/...` | ⏭️ | FA only |
| Iran International | ⚠️ Google News proxy | 🎯 | Need direct URL |
| Fars News | ⚠️ Google News proxy | ⏭️ | State-directed, proxy banned |
| Haaretz | ⚠️ Google News proxy | 🎯 | Need direct: haaretz.com/cmlink/... |
| Arab News | ⚠️ Google News proxy | 🎯 | 403 from cloud IPs per WM |
| The National | ⚠️ Google News proxy | ⏭️ | UAE, proxy banned |
| Oman Observer | `omanobserver.om/rssFeed/1` | ⏭️ | Niche |
| Rudaw | ⚠️ Google News proxy | ⏭️ | Kurdish, proxy banned |
| Press TV | — | ✅ | Already in sources.json |
| Anadolu Agency | — | ✅ | Already in sources.json |
| Middle East Eye | — | ✅ | Already in sources.json |


## WorldMonitor Category: `africa`

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| Africa News | ⚠️ Google News proxy | ⏭️ | Generic query, proxy banned |
| Sahel Crisis | ⚠️ Google News proxy | ⏭️ | Generic query, proxy banned |
| News24 | `feeds.news24.com/articles/news24/TopStories/rss` | 🎯 | Direct RSS ✓. South Africa |
| BBC Africa | `feeds.bbci.co.uk/news/world/africa/rss.xml` | 🎯 | Direct RSS ✓ |
| Jeune Afrique | `jeuneafrique.com/feed/` | 🎯 | Direct RSS ✓. FR. Francophone Africa |
| Africanews | `africanews.com/feed/rss` | 🎯 | Direct RSS ✓. EN + FR |
| BBC Afrique | `bbc.com/afrique/index.xml` | 🎯 | Direct RSS ✓. FR |
| Premium Times | `premiumtimesng.com/feed` | ✅ | Already in sources.json |
| Vanguard Nigeria | `vanguardngr.com/feed/` | 🎯 | Direct RSS ✓ |
| Channels TV | `channelstv.com/feed/` | 🎯 | Direct RSS ✓ |
| Daily Trust | `dailytrust.com/feed/` | 🎯 | Direct RSS ✓ |
| ThisDay | `thisdaylive.com/feed` | ⏭️ | 5th Nigerian source, diminishing returns |
| AllAfrica | — | ✅ | Already in sources.json |
| Daily Nation | — | ✅ | Already in sources.json |

## WorldMonitor Category: `latam`

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| Latin America | ⚠️ Google News proxy | ⏭️ | Generic query |
| BBC Latin America | `feeds.bbci.co.uk/news/world/latin_america/rss.xml` | 🎯 | Direct RSS ✓ |
| Reuters LatAm | ⚠️ Google News proxy | ⏭️ | Proxy banned |
| Guardian Americas | `theguardian.com/world/americas/rss` | ⏭️ | Duplicate |
| Clarín | `clarin.com/rss/lo-ultimo/` | 🎯 | Direct RSS ✓. ES. Argentina |
| O Globo | ⚠️ Google News proxy | 🎯 | Need direct URL |
| Folha de S.Paulo | `feeds.folha.uol.com.br/emcimadahora/rss091.xml` | 🎯 | Direct RSS ✓. PT. Brazil |
| Brasil Paralelo | `brasilparalelo.com.br/noticias/rss.xml` | ⏭️ | Niche |
| El Tiempo | `eltiempo.com/rss/mundo_latinoamerica.xml` | 🎯 | Direct RSS ✓. ES. Colombia |
| La Silla Vacía | `lasillavacia.com/rss` | ⏭️ | Niche Colombian |
| Infobae | `infobae.com/arc/outboundfeeds/rss/` | 🎯 | Direct RSS ✓. ES. Pan-LatAm |
| Mexico News Daily | `mexiconewsdaily.com/feed/` | ⏭️ | EN, niche |
| InSight Crime | `insightcrime.org/feed/` | 🎯 | Direct RSS ✓. LatAm security OSINT |
| France 24 LatAm | `france24.com/en/americas/rss` | ⏭️ | Duplicate of France24 |
| Agencia Brasil | — | ✅ | Already in sources.json |
| La Nacion | — | ✅ | Already in sources.json |
| El Financiero | — | ✅ | Already in sources.json |


## WorldMonitor Category: `asia`

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| Asia News | ⚠️ Google News proxy | ⏭️ | Generic query |
| BBC Asia | `feeds.bbci.co.uk/news/world/asia/rss.xml` | 🎯 | Direct RSS ✓ |
| The Diplomat | `thediplomat.com/feed/` | 🎯 | Direct RSS ✓. Asia-Pacific analysis |
| SCMP | `scmp.com/rss/91/feed/` | ✅ | Already in sources.json |
| Reuters Asia | ⚠️ Google News proxy | ⏭️ | Proxy banned |
| Xinhua | ⚠️ Google News proxy | 🎯 | Need direct: xinhuanet.com RSS |
| Japan Today | `japantoday.com/feed/atom` | 🎯 | Direct RSS ✓. Atom format |
| Nikkei Asia | ⚠️ Google News proxy | 🎯 | Need direct URL |
| Asahi Shimbun | `asahi.com/rss/asahi/newsheadlines.rdf` | ⏭️ | JA only |
| The Hindu | `thehindu.com/news/national/feeder/default.rss` | 🎯 | Direct RSS ✓ |
| Indian Express | `indianexpress.com/section/india/feed/` | 🎯 | Direct RSS ✓ |
| NDTV | `feeds.feedburner.com/ndtvnews-top-stories` | ✅ | Already in sources.json |
| CNA | `channelnewsasia.com/api/v1/rss-outbound-feed` | ✅ | Already in sources.json |
| Bangkok Post | ⚠️ Google News proxy | 🎯 | Need direct: bangkokpost.com/rss |
| VnExpress | `vnexpress.net/rss/tin-moi-nhat.rss` | 🎯 | Direct RSS ✓. VI |
| Yonhap News | `yonhapnewstv.co.kr/browse/feed/` | ✅ | Already (en.yna.co.kr) |
| ABC News Australia | `abc.net.au/news/feed/2942460/rss.xml` | 🎯 | Direct RSS ✓ |
| Guardian Australia | `theguardian.com/australia-news/rss` | ⏭️ | Duplicate |
| Island Times (Palau) | `islandtimes.org/feed/` | ⏭️ | Too niche |
| CGTN | — | ✅ | Already in sources.json |
| Dawn | — | ✅ | Already in sources.json |

## WorldMonitor Category: `thinktanks`

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| Foreign Policy | `foreignpolicy.com/feed/` | 🎯 | Direct RSS ✓ |
| Atlantic Council | `atlanticcouncil.org/feed/` | 🎯 | Direct RSS ✓ (via Railway relay) |
| Foreign Affairs | `foreignaffairs.com/rss.xml` | 🎯 | Direct RSS ✓ |
| CSIS | ⚠️ Google News proxy | 🎯 | Need direct URL |
| RAND | `rand.org/pubs/articles.xml` | 🎯 | Direct RSS ✓ |
| Brookings | ⚠️ Google News proxy | 🎯 | Need direct URL |
| Carnegie | ⚠️ Google News proxy | 🎯 | Need direct URL |
| War on the Rocks | `warontherocks.com/feed` | 🎯 | Direct RSS ✓ |
| Responsible Statecraft | `responsiblestatecraft.org/feed/` | 🎯 | Direct RSS ✓ |
| RUSI | ⚠️ Google News proxy | ⏭️ | Proxy banned |
| FPRI | `fpri.org/feed/` | 🎯 | Direct RSS ✓ |
| Jamestown | `jamestown.org/feed/` | 🎯 | Direct RSS ✓. Eurasia/China |

## WorldMonitor Category: `crisis`

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| CrisisWatch (ICG) | `crisisgroup.org/rss` | 🎯 | Direct RSS ✓ |
| IAEA | `iaea.org/feeds/topnews` | 🎯 | Direct RSS ✓ |
| WHO | `who.int/rss-feeds/news-english.xml` | 🎯 | Direct RSS ✓ |
| UNHCR | ⚠️ Google News proxy | 🎯 | Need direct URL |
| UN News | `news.un.org/feed/subscribe/en/news/all/rss.xml` | ✅ | Already in sources.json |
| IPS News | — | ✅ | Already in sources.json |

## WorldMonitor: Propaganda Risk Classifications (reference)

From `SOURCE_PROPAGANDA_RISK` in feeds.ts:

| Risk | Sources |
|------|---------|
| **high** | Xinhua (CN), TASS (RU), RT (RU), Sputnik (RU), CGTN (CN), Press TV (IR), KCNA (KP) |
| **medium** | Al Jazeera (QA), Al Arabiya (SA), TRT World (TR), France 24 (FR), DW News (DE), VOA (US), Kyiv Independent (UA bias), Moscow Times (anti-Kremlin bias) |
| **low** | Reuters, AP, AFP, BBC, Guardian, FT, Bellingcat, Brasil Paralelo, EuroNews, Le Monde |

---

## Skipped WorldMonitor Categories

- `tech` — TechCrunch, Verge, Ars Technica, Hacker News
- `ai` — AI/ML specific feeds (ArXiv, VentureBeat AI)
- `startups` / `vcblogs` / `regionalStartups` — VC/startup ecosystem
- `github` / `ipo` / `funding` / `producthunt` — Developer/business
- `outages` — AWS/Cloud status (IT ops, not journalism)
- `layoffs` — Tech layoffs tracking

Categories `finance`, `energy`, `gov`, and `security` are selectively included — see sections below.



## WorldMonitor Category: `energy`

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| Oil & Gas | ⚠️ Google News proxy | ⏭️ | Generic query |
| Nuclear Energy | ⚠️ Google News proxy | ⏭️ | Generic query |
| Reuters Energy | ⚠️ Google News proxy | ⏭️ | No free RSS |
| Mining & Resources | ⚠️ Google News proxy | ⏭️ | Generic query |

> **Note:** WorldMonitor only has Google News proxies for energy. We need dedicated energy RSS sources.
> Candidates to research: OPEC news feed, IEA, Platts/S&P Global energy, Rigzone.

## WorldMonitor Category: `gov` (Government Primary Sources)

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| White House | ⚠️ Google News proxy | ⏭️ | Proxy banned |
| State Dept | ⚠️ Google News proxy | 🎯 | Need direct: state.gov/rss |
| Pentagon | ⚠️ Google News proxy | ⏭️ | Proxy banned |
| Treasury | ⚠️ Google News proxy | ⏭️ | Niche |
| DOJ | ⚠️ Google News proxy | ⏭️ | Niche |
| Federal Reserve | `federalreserve.gov/feeds/press_all.xml` | 🎯 | Direct RSS ✓ |
| SEC | `sec.gov/news/pressreleases.rss` | ⏭️ | Niche |
| CDC | ⚠️ Google News proxy | ⏭️ | Proxy banned |
| UN News | `news.un.org/feed/subscribe/en/news/all/rss.xml` | ✅ | Already in sources.json |
| CISA | `cisa.gov/cybersecurity-advisories/all.xml` | 🎯 | Direct RSS ✓. Cyber advisories |

> **Note:** WorldMonitor only covers US gov. For global perspective we should research:
> EU Commission press, UK Gov (gov.uk), Kremlin EN, Chinese MFA, Indian MEA.

## WorldMonitor Category: `finance` (selective)

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| CNBC | `cnbc.com/id/100003114/device/rss/rss.html` | ⏭️ | Market ticker noise |
| MarketWatch | ⚠️ Google News proxy | ⏭️ | Market ticker noise |
| Yahoo Finance | `finance.yahoo.com/news/rssindex` | ⏭️ | Market ticker noise |
| Financial Times | `ft.com/rss/home` | 🎯 | Direct RSS ✓. Geopolitical econ |
| Reuters Business | ⚠️ Google News proxy | ⏭️ | No free RSS |

> **Decision:** Only FT qualifies — geopolitical economic reporting, not market tickers.

## WorldMonitor Category: `security` (selective)

From the `security` section in feeds.ts:

| Source | URL | Status | Notes |
|--------|-----|--------|-------|
| Krebs on Security | `krebsonsecurity.com/feed/` | 🎯 | Direct RSS ✓. Investigative |
| The Hacker News | `feeds.feedburner.com/TheHackersNews` | ⏭️ | Technical advisories |
| Dark Reading | `darkreading.com/rss.xml` | ⏭️ | Technical advisories |
| Schneier on Security | `schneier.com/feed/` | ⏭️ | Technical/policy |

> **Decision:** Only Krebs qualifies — investigative journalism on state-sponsored attacks,
> election security, infrastructure hacks. The rest are technical security advisories.


---

## Sources Without Free RSS — Transparency Policy

The following high-value sources do not offer free RSS feeds. Their content enters
Independent Wire through the **Researcher Agent's web_search**, not through feed ingestion.
This is documented transparently, not hidden.

| Source | Why no RSS | How content enters pipeline |
|--------|-----------|---------------------------|
| Reuters | Paid wire service. RSS discontinued. | Researcher web_search finds Reuters articles |
| AP (Associated Press) | Paid wire service. No public RSS. | Researcher web_search finds AP articles |
| AFP (Agence France-Presse) | Paid wire service. No public RSS. | Researcher web_search finds AFP articles |
| Haaretz | Paywall + cloud IP blocks | Researcher web_search |
| Nikkei Asia | Paywall + Google News proxy only | Researcher web_search |
| Al Arabiya EN | Blocks cloud IPs (per WorldMonitor notes) | Researcher web_search; AR RSS available |

**Principle:** We do not use Google News proxy URLs to circumvent access restrictions.
If a source does not offer a free, direct RSS feed, we respect that decision and rely
on our Researcher Agent to find their articles during the research phase.

---

## Summary: Feed Expansion Candidates

### Batch 1 — Direct RSS available, high priority (add to sources.json now)

**Wire / International (Tier 1-2):**
BBC World, Guardian World, France 24, DW News, NPR

**Europe:**
Le Monde, Tagesschau, Der Spiegel, EuroNews, ANSA, BBC Russian, Meduza, Novaya Gazeta Europe, Kyiv Independent, RT

**Middle East:**
BBC Middle East

**Africa:**
BBC Africa, Africanews, Jeune Afrique, News24, Vanguard Nigeria, Channels TV, Daily Trust

**Latin America:**
BBC Latin America, Clarín, Folha de S.Paulo, El Tiempo, Infobae, InSight Crime

**Asia:**
BBC Asia, The Diplomat, Japan Today, The Hindu, Indian Express, VnExpress, ABC Australia

**Think Tanks (Tier 3):**
Foreign Policy, Atlantic Council, Foreign Affairs, RAND, War on the Rocks,
Responsible Statecraft, FPRI, Jamestown, CrisisWatch (ICG)

**International Orgs:**
IAEA, WHO

**Finance (selective):**
Financial Times

**Security (selective):**
Krebs on Security

**Government (selective):**
Federal Reserve, CISA

**Total Batch 1: ~45 new feeds → ~66 total (21 existing + 45 new)**

### Batch 2 — Need URL research or manual testing

Al Arabiya AR, Xinhua direct RSS, Nikkei Asia alternative,
Bangkok Post direct, O Globo direct, Brookings direct, Carnegie direct,
CSIS direct, UNHCR direct, State Dept direct RSS
