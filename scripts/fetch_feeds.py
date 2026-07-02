#!/usr/bin/env python3
"""Independent Wire — Fetch RSS/API feeds and write raw findings to disk.

Runs independently of the LLM pipeline. No API keys needed (all feeds are free).
Output: raw/YYYY-MM-DD/feeds.json
"""

import asyncio
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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
        entry_dt: datetime | None = None
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
            "published_at": entry_dt.isoformat() if entry_dt else None,
        })

    return entries


async def fetch_rss(client: httpx.AsyncClient, source: dict, cutoff: datetime) -> list[dict]:
    """Fetch and parse a single RSS feed."""
    url = source["url"]
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
        resp.raise_for_status()
        # Parse the raw bytes, not resp.text: httpx decodes with the HTTP
        # header charset (or utf-8) and hands feedparser a pre-decoded str,
        # which bypasses feedparser's own XML-prolog encoding detection. Feeds
        # that declare their encoding only in the `<?xml ... encoding=?>` prolog
        # (common for the non-Latin streams) are then silently garbled while
        # `bozo` stays false (CODE-REVIEW-2026-07-02 M-P4).
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            logger.warning("Feed '%s' returned invalid RSS: %s", source["name"], feed.bozo_exception)
            return []
        entries = parse_rss_entries(feed, source, cutoff)
        logger.info("Feed '%s': %d entries", source["name"], len(entries))
        return entries
    except Exception as e:
        logger.warning("Feed '%s' failed: %s", source["name"], e)
        return []


def _parse_gdelt_seendate(seendate: str) -> Optional[str]:
    """Parse GDELT's compact ``YYYYMMDDTHHMMSSZ`` timestamp into ISO 8601.

    Returns ``None`` if the input is empty or unparseable — the caller emits
    ``published_at: None`` (selector contract: null, not missing key)."""
    if not seendate:
        return None
    try:
        dt = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


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
            seendate = art.get("seendate", "")
            entries.append({
                "title": title,
                "summary": seendate,
                "source_url": art.get("url", ""),
                "source_name": art.get("domain", "GDELT"),
                "language": art.get("language", "English"),
                "region": "Global",
                "feed_source": True,
                "published_at": _parse_gdelt_seendate(seendate),
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


# --- Undated-entry cross-day suppression (CODE-REVIEW-2026-07-02 M-P5) --------
# Feed entries whose pubDate is missing or unparseable bypass the 24h cutoff in
# ``parse_rss_entries`` (``published_at`` is None → no time filter applies), so
# without state they re-enter the pipeline and reach the Curator every single
# day. We keep a small persistent seen-set of undated entries keyed by a stable
# fingerprint (article URL, else source+title). Lifecycle:
#   * An undated entry enters the pipeline ONCE — the first day it is seen —
#     and is suppressed on every later day while it keeps reappearing.
#   * Each sighting refreshes the key's last-seen date; keys unseen for
#     ``UNDATED_SEEN_RETENTION_DAYS`` are pruned so the file cannot grow without
#     bound (a re-appearance after that window enters once more — negligible).
# The file lives at ``raw/undated_seen.json`` (gitignored, beside the per-day
# ``feeds.json``). It is process-local operational state, not part of any Topic
# Package, and is safe to delete (worst case: each still-live undated entry
# re-enters once).
UNDATED_SEEN_PATH = ROOT / "raw" / "undated_seen.json"
UNDATED_SEEN_RETENTION_DAYS = 30


def _undated_fingerprint(finding: dict) -> str:
    """Stable cross-day identity for an undated entry: the article URL when
    present (most stable), else source_name + title."""
    url = (finding.get("source_url") or "").strip()
    basis = url or f"{finding.get('source_name', '')}\x1f{finding.get('title', '')}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _load_undated_seen(path: Path) -> dict[str, str]:
    """Load ``{fingerprint: last_seen_YYYY-MM-DD}``; empty on any read error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in entries.items()} if isinstance(entries, dict) else {}


def _save_undated_seen(path: Path, entries: dict[str, str]) -> None:
    """Atomically persist the seen-set (write-temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def suppress_repeat_undated(
    findings: list[dict],
    seen: dict[str, str],
    today: str,
    *,
    retention_days: int = UNDATED_SEEN_RETENTION_DAYS,
) -> tuple[list[dict], int]:
    """Drop undated findings already seen on a PRIOR day; keep every dated
    finding and every first-time undated finding.

    Mutates ``seen`` in place: records/refreshes each undated key with
    ``today`` and prunes keys older than ``retention_days``. Returns
    ``(kept_findings, dropped_count)``.
    """
    prune_before = (
        datetime.strptime(today, "%Y-%m-%d") - timedelta(days=retention_days)
    ).strftime("%Y-%m-%d")
    for stale in [k for k, last in seen.items() if last < prune_before]:
        del seen[stale]

    kept: list[dict] = []
    dropped = 0
    for f in findings:
        if f.get("published_at") is not None:
            kept.append(f)  # dated → already governed by the 24h cutoff
            continue
        key = _undated_fingerprint(f)
        if key in seen:
            seen[key] = today  # still appearing → keep suppressed, refresh last-seen
            dropped += 1
            continue
        seen[key] = today  # first sighting → enter once, remember it
        kept.append(f)
    return kept, dropped


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

    # Suppress undated entries already seen on a prior day (M-P5). Dated entries
    # are untouched — they are governed by the 24h cutoff in parse_rss_entries.
    seen = _load_undated_seen(UNDATED_SEEN_PATH)
    all_findings, undated_dropped = suppress_repeat_undated(all_findings, seen, today)
    _save_undated_seen(UNDATED_SEEN_PATH, seen)

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
        "Done in %.1fs: %d feeds OK, %d failed, %d entries "
        "(%d duplicates removed, %d repeat-undated suppressed), written to %s",
        elapsed, feeds_ok, feeds_failed, len(all_findings), dupes, undated_dropped, out_path,
    )


if __name__ == "__main__":
    asyncio.run(main())
