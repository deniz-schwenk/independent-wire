#!/usr/bin/env python3
"""Independent Wire — Fetch RSS/API feeds and write raw findings to disk.

Runs independently of the LLM pipeline. No API keys needed (all feeds are free).
Output: raw/YYYY-MM-DD/feeds.json
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("fetch_feeds")

GDELT_API_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query=sourcelang:eng&mode=ArtList&maxrecords=50"
    "&sort=DateDesc&format=json&timespan=1h"
)


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def load_sources() -> list[dict]:
    """Load enabled feed sources from config/sources.json."""
    path = ROOT / "config" / "sources.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [s for s in data["feeds"] if s.get("enabled", True)]


def parse_rss_entries(feed_data, source: dict, cutoff: datetime) -> list[dict]:
    """Extract entries from a parsed RSS feed, filtering to last 24h."""
    entries = []
    for entry in feed_data.entries:
        # Parse published date
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            from calendar import timegm
            entry_dt = datetime.fromtimestamp(timegm(published), tz=timezone.utc)
            if entry_dt < cutoff:
                continue

        title = entry.get("title", "").strip()
        if not title:
            continue

        summary = entry.get("summary", entry.get("description", "")).strip()
        # Strip HTML tags from summary
        if summary:
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            # Truncate to ~500 chars
            if len(summary) > 500:
                summary = summary[:497] + "..."

        link = entry.get("link", "").strip()

        entries.append({
            "title": title,
            "summary": summary,
            "source_url": link,
            "source_name": source["name"],
            "language": source.get("language", "en"),
            "region": source.get("region", ""),
            "feed_source": True,
        })

    return entries


async def fetch_rss(client: httpx.AsyncClient, source: dict, cutoff: datetime) -> list[dict]:
    """Fetch and parse a single RSS feed."""
    url = source["url"]
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        if feed.bozo and not feed.entries:
            logger.warning("Feed '%s' returned invalid RSS: %s", source["name"], feed.bozo_exception)
            return []
        entries = parse_rss_entries(feed, source, cutoff)
        logger.info("Feed '%s': %d entries", source["name"], len(entries))
        return entries
    except Exception as e:
        logger.warning("Feed '%s' failed: %s", source["name"], e)
        return []


async def fetch_gdelt(client: httpx.AsyncClient, source: dict) -> list[dict]:
    """Fetch recent articles from the GDELT API."""
    try:
        resp = await client.get(GDELT_API_URL, follow_redirects=True, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])
        entries = []
        for art in articles[:50]:
            title = art.get("title", "").strip()
            if not title:
                continue
            entries.append({
                "title": title,
                "summary": art.get("seendate", ""),
                "source_url": art.get("url", ""),
                "source_name": art.get("domain", "GDELT"),
                "language": art.get("language", "English"),
                "region": "Global",
                "feed_source": True,
            })
        logger.info("GDELT: %d entries", len(entries))
        return entries
    except Exception as e:
        logger.warning("GDELT failed: %s", e)
        return []


def deduplicate(findings: list[dict]) -> list[dict]:
    """Deduplicate findings by URL."""
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for f in findings:
        url = f.get("source_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique.append(f)
    return unique


async def main():
    setup_logging()
    start = time.time()
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)

    logger.info("Fetching feeds for %s...", today)

    sources = load_sources()
    rss_sources = [s for s in sources if s.get("type") == "rss"]
    api_sources = [s for s in sources if s.get("type") == "api"]

    logger.info("Loaded %d RSS feeds, %d API sources", len(rss_sources), len(api_sources))

    all_findings: list[dict] = []
    feeds_ok = 0
    feeds_failed = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": "IndependentWire/0.1 (news aggregator)"}
    ) as client:
        # Fetch RSS feeds concurrently
        tasks = [fetch_rss(client, s, cutoff) for s in rss_sources]
        results = await asyncio.gather(*tasks)
        for i, entries in enumerate(results):
            if entries:
                all_findings.extend(entries)
                feeds_ok += 1
            else:
                feeds_failed += 1

        # Fetch API sources
        for s in api_sources:
            if "gdelt" in s["url"]:
                entries = await fetch_gdelt(client, s)
            else:
                logger.warning("Unknown API source: %s", s["name"])
                entries = []
            if entries:
                all_findings.extend(entries)
                feeds_ok += 1
            else:
                feeds_failed += 1

    # Deduplicate
    before = len(all_findings)
    all_findings = deduplicate(all_findings)
    dupes = before - len(all_findings)

    # Write output
    out_dir = ROOT / "raw" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "feeds.json"
    out_path.write_text(
        json.dumps(all_findings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    elapsed = time.time() - start
    logger.info(
        "Done in %.1fs: %d feeds OK, %d failed, %d entries (%d duplicates removed), written to %s",
        elapsed, feeds_ok, feeds_failed, len(all_findings), dupes, out_path,
    )


if __name__ == "__main__":
    asyncio.run(main())
