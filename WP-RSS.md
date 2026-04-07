# WP-RSS — RSS/API Feed Integration

## Goal

Add a feed ingestion layer that runs independently of the LLM pipeline. A simple Python script collects headlines from RSS feeds and the GDELT API, writes structured JSON to `raw/`, and the Pipeline merges these findings with Collector output before passing everything to the Curator.

## Context for Claude Code

- **Local clone:** `/Users/denizschwenk/Documents/independent-wire/repo-clone/`
- **Reference codebase (read-only):** `/Users/denizschwenk/Documents/nanobot-main/`
- **Run tests:** `source .venv/bin/activate && source .env && python -m pytest tests/ -v`
- **Source list:** `config/sources.json` (to be created, see below)
- **Architecture doc:** `docs/ARCHITECTURE.md` — section "What This Architecture Enables" mentions: "24/7 RSS daemon: Separate process writes to raw/. Pipeline reads from raw/ on each run. No framework change."

## Architecture Decisions (already made)

1. RSS findings go directly to the **Curator**, NOT through the Collector. The Collector searches, RSS delivers. Both are equal inputs for curation.
2. The feed script runs **independently** — via cron or manually before a pipeline run. No LLM involved, no API keys needed (except GDELT, which is free).
3. Feed data is written to `raw/YYYY-MM-DD/` as JSON. The Pipeline reads whatever is there when it starts. If nothing is there, the pipeline runs fine with just Collector output.
4. **No paid APIs.** Only free RSS feeds and the free GDELT API.


## What to Build

### Part 1: `config/sources.json`

Create a JSON file listing all feed sources. Each entry has:

```json
{
  "name": "Al Jazeera",
  "url": "https://www.aljazeera.com/xml/rss/all.xml",
  "type": "rss",
  "region": "Middle East",
  "language": "en",
  "bias_note": "Critical, Qatar-funded",
  "enabled": true
}
```

For GDELT, `type` is `"api"` and `url` is the GDELT API endpoint.

**Starter set — 21 sources (all free):**

RSS feeds (20):
1. Al Jazeera (EN) — aljazeera.com — MENA
2. Tehran Times — tehrantimes.com — Iran
3. Anadolu Agency (EN) — aa.com.tr — Turkey
4. Middle East Eye — middleeasteye.net — MENA
5. Xinhua (EN) — xinhuanet.com — China
6. CGTN — cgtn.com — China
7. TASS (EN) — tass.ru — Russia
8. Ukrinform (EN) — ukrinform.net — Ukraine
9. AllAfrica — allafrica.com — Pan-Africa
10. Daily Nation — nation.africa — Kenya
11. Guardian Nigeria — guardian.ng — Nigeria
12. Agencia Brasil — agenciabrasil.ebc.com.br — Brazil (PT)
13. La Nación — lanacion.com.ar — Argentina (ES)
14. El Universal — eluniversal.com.mx — Mexico (ES)
15. PTI — ptinews.com — India
16. Dawn — dawn.com — Pakistan
17. CNA — channelnewsasia.com — Singapore
18. Yonhap (EN) — yonhapnews.co.kr — South Korea
19. UN News — news.un.org — International
20. ReliefWeb — reliefweb.int — International

API (1):
21. GDELT — gdeltproject.org — Global, 100+ languages, free API

**Important:** The actual RSS feed URLs need to be discovered per source. Most are at `/rss`, `/feed`, `/xml/rss/all.xml`, or similar. The script should try common patterns or the URLs can be looked up during implementation.


### Part 2: `scripts/fetch_feeds.py`

A standalone async Python script that:

1. Reads `config/sources.json`
2. For each enabled RSS source: fetches the feed using `feedparser`, extracts the last 24 hours of entries
3. For GDELT: calls the free API to get recent articles (last 24h)
4. Normalizes each entry into the same format as Collector findings:
   ```json
   {
     "title": "Article headline",
     "summary": "First 2-3 sentences or description from feed",
     "source_url": "https://full-article-url",
     "source_name": "Al Jazeera",
     "language": "en",
     "region": "Middle East",
     "feed_source": true
   }
   ```
   The `feed_source: true` flag distinguishes these from Collector web_search findings.
5. Deduplicates by URL
6. Writes output to `raw/YYYY-MM-DD/feeds.json`
7. Logs: how many feeds fetched, how many entries total, how many failed feeds

**Dependencies:** Add `feedparser` to `pyproject.toml`. No other new dependencies — `httpx` is already available for GDELT.

**Error handling:** If a feed is unreachable, log a warning and continue. Never crash on a single broken feed.

**Runtime:** Should complete in under 30 seconds for 21 feeds.

### Part 3: Pipeline Integration

Modify `Pipeline.curate()` in `src/pipeline.py`:

1. Before calling the Curator agent, check if `raw/{date}/feeds.json` exists
2. If it exists, load the feed findings and merge them with `raw_findings` from the Collector
3. Pass the combined list to the Curator
4. Log how many feed findings were merged: "Merged X feed findings with Y collector findings"

The Curator already receives findings as a list of dicts — no schema change needed. The `feed_source` flag lets the Curator (and later analysis) distinguish between web-searched and feed-sourced material.


## Usage

```bash
# Fetch feeds manually before a pipeline run
source .venv/bin/activate && python scripts/fetch_feeds.py

# Then run the pipeline (which picks up raw/ automatically)
source .env && python scripts/run.py

# Or automate via cron (every 6 hours)
# 0 */6 * * * cd /path/to/repo && .venv/bin/python scripts/fetch_feeds.py
```

## Files Created/Modified

| File | Action |
|------|--------|
| `config/sources.json` | **Create** — feed source list |
| `scripts/fetch_feeds.py` | **Create** — feed fetcher script |
| `src/pipeline.py` | **Modify** — merge feed findings in `curate()` |
| `pyproject.toml` | **Modify** — add `feedparser` dependency |

## Definition of Done

1. `python scripts/fetch_feeds.py` runs and writes `raw/YYYY-MM-DD/feeds.json`
2. The JSON contains findings from at least 15 of the 20 RSS feeds (some may be temporarily down)
3. Each finding has all 7 fields populated (title, summary, source_url, source_name, language, region, feed_source)
4. `python scripts/run.py` merges feed findings with Collector output before passing to Curator
5. Pipeline logs show "Merged X feed findings with Y collector findings"
6. All existing tests still pass

## What NOT to Do

- Don't build a daemon or background service. A simple script is enough.
- Don't add LLM processing to the feed script. It's pure data ingestion.
- Don't filter or rank feed entries. The Curator does that.
- Don't scrape full article text. Title + summary/description from the feed is sufficient.
- Don't add paid API integrations. GDELT is free, everything else is RSS.
