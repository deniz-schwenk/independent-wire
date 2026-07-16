#!/usr/bin/env python3
"""Independent Wire — Fetch RSS/API feeds and write raw findings to disk.

Runs independently of the LLM pipeline. No API keys needed (all feeds are free).
Output: raw/YYYY-MM-DD/feeds.json
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import feedparser
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.url_canonical import canonical_url  # noqa: E402  (ROOT on sys.path)

logger = logging.getLogger("fetch_feeds")


def _dedup_url_key(finding: dict) -> str:
    """Canonical dedup key for a finding's URL: the tracking-param/casing/
    fragment/trailing-slash-normalized form when the URL is usable, else the
    stripped raw URL (so blank/relative URLs behave exactly as before). URL
    variants of the same article (e.g. ``?traffic_source=rss``) collapse to one
    key here, before any LLM stage sees them."""
    raw = (finding.get("source_url") or "").strip()
    return canonical_url(raw) or raw

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
    """Load enabled ``daily`` feed sources from config/sources.json.

    Access-flag guard (TASK-REGISTRY-A1, "ONE catalog, two access patterns"):
    only entries with ``access == "daily"`` feed the daily 06:00 chain. The
    ``on_demand`` slice (the registry retrieval catalog) is invisible here — it
    is fetched per-topic by the researcher arm, not unconditionally. A missing
    ``access`` field is treated as ``"daily"`` (backward-compatible), but logged
    loudly once per run so the schema gap cannot pass silently.
    """
    path = ROOT / "config" / "sources.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    enabled = [s for s in data["feeds"] if s.get("enabled", True)]
    missing_access = [s for s in enabled if "access" not in s]
    if missing_access:
        logger.warning(
            "sources.json: %d enabled feed(s) have no 'access' field; "
            "treating as 'daily' (add access: daily|on_demand): %s",
            len(missing_access),
            ", ".join(sorted(s.get("name", "?") for s in missing_access))[:300],
        )
    return [s for s in enabled if s.get("access", "daily") == "daily"]


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
    """Deduplicate findings by canonical URL (in-run).

    Keys on :func:`_dedup_url_key` so tracking-param / casing / fragment /
    trailing-slash variants of the same article collapse; the first occurrence
    in ingestion order wins (deterministic tie-break). URL-less findings are
    never deduped (each is kept)."""
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for f in findings:
        url = _dedup_url_key(f)
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
    """Stable cross-day identity for an undated entry: the canonical article URL
    when present (most stable), else source_name + title. Sharing
    :func:`_dedup_url_key` keeps a tracking-param variant from re-entering the
    pipeline as a "new" undated sighting."""
    url = _dedup_url_key(finding)
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


# --- Intraday collector: append-only day store + window entrypoint -----------
# BACKLOG-INTRADAY-COLLECTOR.md is the spec; its Design sketch + Invariants apply
# verbatim. The store is raw/{run_date}/feeds.json — the SAME file the 06:00 run
# reads. Collector windows (10:00/14:00/18:00/22:00/02:00 local) fetch the delta
# and dedup-append into the NEXT 06:00 run's store; the 06:00 run performs the
# final delta fetch itself and then consumes the accumulated store. Nothing here
# is active until the collector LaunchAgent is loaded (a separate landing).


def target_run_date(now_local: datetime) -> str:
    """The store date-key (YYYY-MM-DD) a collector window feeds into.

    A window collects into the NEXT 06:00 production run's store. The 06:00
    boundary splits the day: a window at/after 06:00 local feeds *tomorrow's*
    run (10:00/14:00/18:00/22:00 → next calendar day); the pre-dawn 02:00 window
    feeds *today's* 06:00 run (same calendar day). The 06:00 slot itself is the
    main run, not a collector window, so it never routes through here."""
    d = now_local.date()
    if now_local.hour >= 6:
        d = d + timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _store_identity(f: dict) -> str:
    """Deterministic dedup identity for a finding in the day store: the canonical
    article URL when present (the stable GUID-equivalent), else source_name +
    title. The URL branch uses :func:`_dedup_url_key`, so a tracking-param variant
    arriving in a later collector window collapses onto the record already in the
    store — and because :func:`merge_append` preserves that earlier record, the
    earliest ``first_seen`` (and its original URL) wins. The title fallback
    additionally catches url-less items that reappear in a later window
    (``deduplicate`` leaves those un-deduped — harmless within one fetch, but they
    would accumulate across windows)."""
    url = _dedup_url_key(f)
    if url:
        return "u\x1f" + url
    return "t\x1f" + (f.get("source_name") or "") + "\x1f" + (f.get("title") or "")


def load_store(path: Path) -> list[dict]:
    """Load an existing day store (``raw/{date}/feeds.json``). Missing or
    unreadable file → ``[]`` (cold start). Never raises: a corrupt store must not
    crash a collector window (worst case: this window rewrites it from fetch)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return []
    return data if isinstance(data, list) else []


def write_store(path: Path, findings: list[dict]) -> None:
    """Serialise the day store with the exact format the single-fetch path has
    always used (``indent=2, ensure_ascii=False``) so cold-start output stays
    byte-for-byte identical modulo the additive ``first_seen`` key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(findings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def merge_append(
    existing: list[dict], fresh: list[dict], now_iso: str
) -> tuple[list[dict], int]:
    """Append-only merge of freshly-fetched ``fresh`` into the ``existing`` store.

    Every existing entry is preserved untouched and in order; a fresh entry is
    appended only when its :func:`_store_identity` is not already in the store.
    Newly-appended entries get an additive ``first_seen`` ISO timestamp (set once,
    on first append; existing entries keep theirs). Returns
    ``(merged_store, n_appended)``.

    Cold start (``existing == []``) is an identity: no fresh entry is dropped, so
    the store is exactly ``fresh`` with ``first_seen`` stamped — today's
    single-fetch shape. Fresh is *not* re-deduped against itself here (it is
    already URL-deduped by :func:`deduplicate`), which is what preserves the
    cold-start byte-equality invariant."""
    seen = {_store_identity(e) for e in existing}
    merged: list[dict] = list(existing)
    appended = 0
    for f in fresh:
        if _store_identity(f) in seen:
            continue
        nf = dict(f)
        nf.setdefault("first_seen", now_iso)
        merged.append(nf)
        appended += 1
    return merged, appended


async def gather_fresh_findings(
    now_utc: datetime, *, undated_seen_path: Path
) -> tuple[list[dict], dict]:
    """Fetch every enabled source, in-run URL-dedup, and cross-day undated
    suppression — the shared fetch core for both the 06:00 run and every
    collector window. Returns ``(findings, stats)``; ``findings`` is the cleaned
    delta ready to merge-append into a store. ``undated_seen_path`` is threaded so
    tests/smokes point it at a temp root (never the real ``raw/``)."""
    today = now_utc.strftime("%Y-%m-%d")
    cutoff = now_utc - timedelta(hours=24)

    sources = load_sources()
    rss_sources = [s for s in sources if s.get("type") == "rss"]
    api_sources = [s for s in sources if s.get("type") == "api"]
    logger.info(
        "Loaded %d RSS feeds, %d API sources", len(rss_sources), len(api_sources)
    )

    all_findings: list[dict] = []
    feeds_ok = 0
    feeds_failed = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": "IndependentWire/0.1 (news aggregator)"}
    ) as client:
        # Fetch RSS feeds concurrently
        tasks = [fetch_rss(client, s, cutoff) for s in rss_sources]
        results = await asyncio.gather(*tasks)
        for entries in results:
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

    # Deduplicate (URL-based, in-run)
    raw_count = len(all_findings)
    all_findings = deduplicate(all_findings)
    dupes = raw_count - len(all_findings)

    # Suppress undated entries already seen on a prior day (M-P5). Dated entries
    # are untouched — they are governed by the 24h cutoff in parse_rss_entries.
    seen = _load_undated_seen(undated_seen_path)
    all_findings, undated_dropped = suppress_repeat_undated(all_findings, seen, today)
    _save_undated_seen(undated_seen_path, seen)

    stats = {
        "feeds_ok": feeds_ok,
        "feeds_failed": feeds_failed,
        "raw_count": raw_count,
        "dupes": dupes,
        "undated_dropped": undated_dropped,
    }
    return all_findings, stats


async def main():
    """Production 06:00 entrypoint (invoked with no args by daily_run.sh /
    run.py). Fetches the day's delta and MERGE-APPENDS it into
    ``raw/{today}/feeds.json`` — preserving any entries a collector window already
    accumulated. Cold start (no collector ran, file absent) degrades to today's
    single-fetch write byte-for-byte (modulo the additive ``first_seen``)."""
    setup_logging()
    start = time.time()
    now_utc = datetime.now(tz=timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    raw_root = ROOT / "raw"

    logger.info("Fetching feeds for %s...", today)

    fresh, stats = await gather_fresh_findings(
        now_utc, undated_seen_path=raw_root / "undated_seen.json"
    )

    out_path = raw_root / today / "feeds.json"
    existing = load_store(out_path)
    merged, appended = merge_append(existing, fresh, now_utc.isoformat())
    write_store(out_path, merged)

    elapsed = time.time() - start
    logger.info(
        "Done in %.1fs: %d feeds OK, %d failed, %d entries "
        "(%d duplicates removed, %d repeat-undated suppressed), written to %s",
        elapsed, stats["feeds_ok"], stats["feeds_failed"], len(merged),
        stats["dupes"], stats["undated_dropped"], out_path,
    )
    if existing:
        logger.info(
            "  (merge mode: %d pre-existing collector entries preserved, "
            "%d appended this run)", len(existing), appended,
        )


# --- Collector window entrypoint (inactive until the LaunchAgent is loaded) --
def _write_collector_log(log_dir: Path | None, run_date: str, line: str) -> None:
    """Append one window line to ``{log_dir}/collector-{run_date}.log`` (default
    ~/iw-logs). Best-effort — a logging failure must never fail a fetch."""
    if log_dir is None:
        log_dir = Path.home() / "iw-logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / f"collector-{run_date}.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        logger.warning("collector: could not write window log (%s)", exc)


# --- Phase 3: MADLAD translation prewarm (flag-gated, OFF by default) ---------
# Spreads the MADLAD load across the collector windows: each window translates
# the non-Latin delta into the SAME cache the 06:00 sidecar reads, so 06:00 sees
# cache hits instead of one ~24.7 GB translate-the-world peak. All translation
# logic (backend, batching, cache format/path) is REUSED from
# src.stages.translate_sidecar.translate_findings — this module only adds the
# non-Latin selection and the flag gate on top.
#
# The env var + truthy contract mirror translate_sidecar.ENABLE_ENV / is_enabled
# (the authoritative gate). We re-check the flag here WITHOUT importing the heavy
# sidecar module, so a flag-OFF window pays no import cost and its store is
# byte-identical to Phase 1.
_TRANSLATE_ENABLE_ENV = "IW_CLUSTER_TRANSLATE"
_TRANSLATE_TRUTHY = {"1", "true", "yes", "on", "y", "t"}


def _translate_prewarm_enabled() -> bool:
    return os.environ.get(_TRANSLATE_ENABLE_ENV, "").strip().lower() in _TRANSLATE_TRUTHY


def _peak_rss_gb() -> float | None:
    """Best-effort peak process RSS in GB. macOS ``ru_maxrss`` is bytes, Linux
    KB. Returns ``None`` if unmeasurable (never raises)."""
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        scale = 1e9 if sys.platform == "darwin" else 1e6  # bytes vs KB
        return round(peak / scale, 2)
    except Exception:  # noqa: BLE001
        return None


def _non_latin_delta(delta: list[dict]) -> list[dict]:
    """The findings in ``delta`` whose language maps to a NON-LATIN script — the
    prewarm selection (spec: "non-Latin DELTA"). Script classification is
    single-sourced from the sidecar's FLORES map (``*_Latn`` = Latin). English
    and unmapped-language findings are excluded (the sidecar would pass them
    through as native anyway)."""
    from src.stages import translate_sidecar as ts

    out: list[dict] = []
    for f in delta:
        lang = ts.norm_lang(f.get("language"))
        if lang in ts.ENGLISH_LANGS:
            continue
        flores = ts.FLORES.get(lang)
        if flores is not None and not flores.endswith("_Latn"):
            out.append(f)
    return out


def _prewarm_translation_cache(
    delta: list[dict], *, window_label: str, run_date: str, log_dir: Path | None
) -> dict:
    """Translate the non-Latin delta via the sidecar backend into the exact cache
    the 06:00 sidecar reads (``translate_findings(persist=True)`` writes to
    ``cache_path()`` — the model-named cache, or the ``IW_CLUSTER_TRANSLATE_CACHE``
    override). Reuses the sidecar's backend/gate/cache verbatim.

    Caller has already confirmed the flag is on. Best-effort: ``translate_findings``
    never raises, and any unexpected error here degrades to a logged no-op — a
    prewarm failure must never fail the fetch that already wrote the store."""
    non_latin = _non_latin_delta(delta)
    if not non_latin:
        logger.info(
            "collector prewarm [%s]: 0 non-Latin in %d-item delta — no-op",
            window_label, len(delta),
        )
        return {"non_latin": 0, "fresh": 0, "cache_hit": 0, "wall_s": 0.0, "peak_rss_gb": None}

    from src.stages import translate_sidecar as ts

    t0 = time.time()
    try:
        _entries, stats = ts.translate_findings(non_latin, persist=True)
    except Exception as exc:  # noqa: BLE001 — never fail the fetch on a prewarm error
        logger.error(
            "collector prewarm [%s]: translation failed (%s) — skipped",
            window_label, exc,
        )
        return {"non_latin": len(non_latin), "fresh": 0, "cache_hit": 0, "error": str(exc)}
    dt = time.time() - t0
    peak = _peak_rss_gb()

    result = {
        "non_latin": len(non_latin),
        "fresh": stats.get("n_translated_fresh", 0),      # findings translated this window
        "cache_hit": stats.get("n_translated_cache_hit", 0),
        "native_fallback": stats.get("n_native_fallback", 0),
        "cache_path": stats.get("cache_path"),
        "wall_s": round(dt, 1),
        "peak_rss_gb": peak,
    }
    line = (
        f"  prewarm [{window_label}]: non_latin={len(non_latin)} "
        f"findings_fresh={result['fresh']} cache_hit={result['cache_hit']} "
        f"native={result['native_fallback']} wall={dt:.1f}s "
        f"peak_rss={peak}GB cache={result['cache_path']}"
    )
    logger.info(line.strip())
    _write_collector_log(log_dir, run_date, line)
    return result


async def collect_window(
    *,
    raw_root: Path,
    run_date: str,
    now_utc: datetime,
    window_label: str,
    log_dir: Path | None = None,
    fetch_fn=None,
) -> dict:
    """Run one collector window: fetch the delta, dedup-append into
    ``{raw_root}/{run_date}/feeds.json``, log loudly, return stats.

    ``raw_root`` is mandatory and fully controls where the store lives — tests
    and smokes MUST point it at a temp root; a stray write into the real
    ``raw/{tomorrow}/feeds.json`` would contaminate the next production run.
    ``fetch_fn`` (defaulting to :func:`gather_fresh_findings`) is the injection
    seam that lets tests exercise the append machinery offline.

    Concurrent-window safety: the 4h collector grid guarantees windows never
    overlap (a fetch is seconds–minutes), so the file-based ``undated_seen.json``
    and the store's read-modify-write are never touched concurrently. No locking
    is needed (spec: document, don't over-engineer)."""
    start = time.time()
    fetch = fetch_fn or gather_fresh_findings
    fresh, stats = await fetch(now_utc, undated_seen_path=raw_root / "undated_seen.json")

    out_path = raw_root / run_date / "feeds.json"
    existing = load_store(out_path)
    merged, appended = merge_append(existing, fresh, now_utc.isoformat())
    write_store(out_path, merged)

    elapsed = time.time() - start
    result = {
        "window": window_label,
        "run_date": run_date,
        "fetched": stats.get("raw_count", len(fresh)),
        "new_after_dedup": appended,
        "store_total": len(merged),
        "store_before": len(existing),
        "wall_s": round(elapsed, 1),
    }
    line = (
        f"{now_utc.isoformat()} [{window_label}] target={run_date} "
        f"fetched={result['fetched']} new_after_dedup={appended} "
        f"store_total={len(merged)} wall={elapsed:.1f}s"
    )
    logger.info("collector window: %s", line)
    _write_collector_log(log_dir, run_date, line)

    # Phase 3 — MADLAD prewarm of the non-Latin delta into the cache the 06:00
    # sidecar reads. Flag-gated: when IW_CLUSTER_TRANSLATE is unset (production
    # default) this branch is skipped entirely — no heavy import, and the store
    # already written above stays byte-identical to Phase 1. Prewarm only writes
    # the SEPARATE translation cache; it never touches the store.
    if _translate_prewarm_enabled() and appended:
        result["prewarm"] = _prewarm_translation_cache(
            merged[len(existing):],
            window_label=window_label,
            run_date=run_date,
            log_dir=log_dir,
        )

    return result


async def collector_main(args) -> None:
    """``--collector-window`` entrypoint: compute the target store date from the
    local clock (unless ``--run-date`` overrides), run one window, exit."""
    setup_logging()
    now_utc = datetime.now(tz=timezone.utc)
    now_local = datetime.now().astimezone()
    raw_root = (
        Path(args.raw_root).expanduser().resolve()
        if args.raw_root
        else ROOT / "raw"
    )
    run_date = args.run_date or target_run_date(now_local)
    log_dir = Path(args.log_dir).expanduser() if args.log_dir else None
    window_label = args.window_label or now_local.strftime("%H:%M")

    await collect_window(
        raw_root=raw_root,
        run_date=run_date,
        now_utc=now_utc,
        window_label=window_label,
        log_dir=log_dir,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fetch RSS/API feeds. No args = production 06:00 run "
        "(merge-append into today's store). --collector-window = one intraday "
        "collector window.",
    )
    p.add_argument(
        "--collector-window",
        action="store_true",
        dest="collector_window",
        help="Run one intraday collector window (fetch delta, dedup-append into "
        "the NEXT 06:00 run's store) and exit.",
    )
    p.add_argument(
        "--raw-root",
        default=None,
        help="Override the raw/ root. Tests and smokes MUST set this to a temp "
        "dir — a stray write into the real raw/ would contaminate a production run.",
    )
    p.add_argument(
        "--run-date",
        default=None,
        help="Override the target store date (YYYY-MM-DD). Default: computed from "
        "the local clock via target_run_date().",
    )
    p.add_argument(
        "--log-dir",
        default=None,
        help="Override the collector log dir (default ~/iw-logs).",
    )
    p.add_argument(
        "--window-label",
        default=None,
        help="Label for this window in logs (default: local HH:MM).",
    )
    return p


def cli() -> None:
    args = _build_arg_parser().parse_args()
    if args.collector_window:
        asyncio.run(collector_main(args))
    else:
        asyncio.run(main())


if __name__ == "__main__":
    cli()
