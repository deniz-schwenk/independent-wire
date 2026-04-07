# Task: Replace Google News Proxy Feeds With Real Sources

## Context
The previous feed-fix round replaced 6 broken feeds with Google News RSS proxies (`news.google.com/rss/search?q=site:...`). This is not acceptable — it creates a dependency on Google's undocumented API and returns Google's algorithmic selection instead of the outlet's own editorial choices. It also contradicts our architecture principle of no commercial dependencies.

## What to do

Replace every Google News proxy in `config/sources.json` with a **direct RSS feed from a real news outlet**. If the original outlet's RSS is truly dead, pick a credible alternative from the same region. Do NOT use Google News proxies under any circumstances.

### Feeds to replace

| Current Entry | Region | What to do |
|---------------|--------|------------|
| Tehran Times (Google proxy) | Middle East | Replace with **IRNA English** (irna.ir) or **Press TV** (presstv.ir). Try their RSS pages. If neither works, use **Al-Monitor** |
| Xinhua (Google proxy) | East Asia | Replace with **Global Times** (globaltimes.cn) RSS — they have a working feed. Or try **South China Morning Post** RSS |
| Guardian Nigeria (Google proxy) | Africa | Replace with **Premium Times Nigeria** (premiumtimesng.com) — they have RSS. Or **Punch Nigeria** (punchng.com) |
| PTI (Google proxy) | South Asia | Replace with **The Hindu** (thehindu.com/news/international/?service=rss) or **NDTV** (ndtv.com) RSS |
| El Universal (Google proxy) | Latin America | Replace with **Animal Político** (animalpolitico.com) or **Proceso** (proceso.com.mx) — prefer Spanish-language feed. Or **Infobae México** |
| ReliefWeb (Google proxy) | International | Replace with **IRIN News / The New Humanitarian** (thenewhumanitarian.org) — they have RSS and cover the same humanitarian space |

### Also fix

| Feed | Region | Problem |
|------|--------|---------|
| TASS | Europe | Still returns 0 entries with current URL. TASS is likely geo-blocked from US servers. Replace with **Meduza** (meduza.io/en/rss/all) — independent Russian outlet, English RSS available |

## Rules

1. **NO Google News proxies** — `news.google.com` URLs are banned. Every feed must point to the outlet's own domain
2. **Keep the JSON structure** — `name`, `url`, `type`, `region`, `language`, `bias_note`, `enabled`
3. **Prefer non-English feeds** — if an outlet has a Spanish, Portuguese, Farsi, Chinese, or Russian feed, use that. Set `language` accordingly
4. **Update bias_note** — reflect the actual outlet (not "via Google News proxy")
5. **Do NOT touch feeds that already work** — Al Jazeera, Anadolu, Middle East Eye, CGTN, Ukrinform, AllAfrica, Daily Nation, Agencia Brasil, La Nacion, Dawn, CNA, Yonhap, UN News are fine
6. **Do NOT change the GDELT entry**

## How to test

```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
source .venv/bin/activate
python scripts/fetch_feeds.py
```

Each feed should return entries > 0. If a replacement doesn't work, try the next alternative listed above. Iterate until all feeds work with direct URLs (no Google proxies).

## After fixing

Report:
- Which outlets now replace the Google proxies (old → new)
- Entry count per feed
- Confirm: zero Google News proxy URLs remain in sources.json
