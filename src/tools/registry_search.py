"""Independent Wire — deterministic, LLM-free `registry` search backend.

Phase A2 of BACKLOG-RESEARCHER-REGISTRY ("ONE catalog, two access patterns").
This module implements the `registry` provider that plugs into the
``IW_SEARCH_PROVIDER`` dispatch map in :mod:`src.tools.web_search` beside
``perplexity``. When selected it performs **topic-conditional retrieval** over
the catalog's ``access == "on_demand"`` entries (ingested in A1) instead of a
paid Sonar call:

    1. deterministic endpoint selection (language + country/region + beat-tag
       overlap, Python only — no embedder, no LLM),
    2. encoding-safe RSS fetch (raw bytes + feedparser, identical
       User-Agent/redirect/timeout semantics to ``scripts/fetch_feeds.py``),
    3. dated-only filtering — items without a parseable pubdate are dropped and
       counted (the registry's core advantage over Sonar: 100 % dated sources),
    4. LLM-free relevance ranking with the *shared pinned embedder singleton*
       (:func:`src.stages.coherence._get_default_embedder` — never a second
       instance),
    5. results returned in the EXACT plain-text shape the Sonar path returns
       today (``N. title\\n   url\\n   snippet``, the documented
       ``web_search_tool.execute`` contract that ``researcher_search`` parses),
       so the researcher stages cannot tell which provider served them.

Cost is $0/query (no API). Interface: ``async _search_registry(query, n) -> str``.

The only signal that crosses the ``execute(query=...)`` tool boundary is the
query string, so region/language/actor-country signals are DERIVED from the
query text. This is not a weak proxy: the planner emits deliberately
multilingual, entity-rich queries (e.g. "NATO summit Ankara Turkey ... Russia
Kyiv", "Türkiye NATO zirvesi Ankara Rusya"), so the language (script), the
actor-countries (named entities) and the topic terms (→ beat tags) are all
present in the query itself.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from calendar import timegm
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import feedparser
import httpx

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
_SOURCES_PATH = ROOT / "config" / "sources.json"

# Same UA / redirect / timeout as scripts/fetch_feeds.py::fetch_rss so on_demand
# hosts see byte-identical request behavior to the daily discovery path.
_USER_AGENT = "IndependentWire/0.1 (news aggregator)"
_FETCH_TIMEOUT = 15.0

# How many on_demand endpoints to fetch per query. Bounded to keep wall-time
# sane; overridable via env for the A3 shadow / tuning. The union of endpoints
# selected across a topic's ~20 queries is additionally bounded by the process
# fetch cache (each URL is fetched at most once per process).
MAX_ENDPOINTS_DEFAULT = 12

# Selection weights. Language is the strongest retrieval signal (an Arabic query
# should reach Arabic outlets); actor-country next; observed beat tags are noisy
# (raw topic words mined from past appearances) so they weigh least.
_W_LANG = 3.0
_W_COUNTRY = 2.0
_W_TAG = 1.0


def _max_endpoints() -> int:
    try:
        v = int(os.environ.get("IW_REGISTRY_MAX_ENDPOINTS", MAX_ENDPOINTS_DEFAULT))
        return v if v > 0 else MAX_ENDPOINTS_DEFAULT
    except (TypeError, ValueError):
        return MAX_ENDPOINTS_DEFAULT


# ── Process-lifetime caches (feeds do not change within a run) ───────────────
_CATALOG_CACHE: Optional[list[dict]] = None
_FEED_CACHE: dict[str, list[dict]] = {}
_COUNTRY_VOCAB: Optional[dict[str, tuple[str, Optional[str]]]] = None

# Loud, machine-readable stats from the most recent call — the channel the A3
# shadow reads (the tool interface can only return a string).
_LAST_STATS: dict[str, Any] = {}


def _reset_caches() -> None:
    """Clear process caches + last-stats. For tests and long-lived processes."""
    global _CATALOG_CACHE, _COUNTRY_VOCAB
    _CATALOG_CACHE = None
    _COUNTRY_VOCAB = None
    _FEED_CACHE.clear()
    _LAST_STATS.clear()


# ── Catalog ──────────────────────────────────────────────────────────────────
def load_on_demand_catalog(path: Optional[Path] = None) -> list[dict]:
    """Return the catalog's ``on_demand`` entries, honoring ``enabled: false``.

    Cached for the process lifetime when the default path is used. daily
    entries are never returned — the guard that keeps on_demand invisible to
    the 06:00 path (A1) is mirrored here in reverse: this backend sees ONLY
    on_demand.
    """
    global _CATALOG_CACHE
    if path is None and _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    src = path or _SOURCES_PATH
    data = json.loads(src.read_text(encoding="utf-8"))
    entries = [
        f
        for f in data.get("feeds", [])
        if f.get("access") == "on_demand" and f.get("enabled", True)
    ]
    if path is None:
        _CATALOG_CACHE = entries
    return entries


# ── Language detection from query script ─────────────────────────────────────
# Dominant non-Latin script → candidate ISO languages present in the catalog.
# Latin is ambiguous (en/tr/es/fr/de/pt/it/pl/ro/hu/vi…) → no language signal,
# selection then leans on country/region + beat-tag overlap instead.
_SCRIPT_TO_LANGS: dict[str, set[str]] = {
    "ARABIC": {"ar", "fa", "ur"},
    "CYRILLIC": {"ru", "uk"},
    "HAN": {"zh", "ja"},
    "HIRAGANA": {"ja"},
    "KATAKANA": {"ja"},
    "HANGUL": {"ko"},
    "DEVANAGARI": {"hi"},
    "GREEK": {"el"},
    "HEBREW": {"he"},
    "THAI": {"th"},
}


def _char_script(ch: str) -> Optional[str]:
    if ch.isascii() or not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    if name.startswith("CJK") or "IDEOGRAPH" in name:
        return "HAN"
    for key in _SCRIPT_TO_LANGS:
        if key == "HAN":
            continue  # synthetic key — reached only via the CJK branch above;
            # skip so "HANGUL SYLLABLE ..." does not collide with the "HAN" prefix
        if name.startswith(key):
            return key
    if name.startswith("LATIN"):
        return None  # accented Latin — still ambiguous
    return None


def detect_query_languages(query: str) -> set[str]:
    """Best-effort ISO-639-1 candidates for a query's dominant non-Latin script.

    Empty set for Latin-script queries (deliberately — the language is
    unknowable from script alone, so we do not filter on it).
    """
    counts: dict[str, int] = {}
    for ch in query:
        script = _char_script(ch)
        if script:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return set()
    # Japanese kana is unambiguous; prefer it over the shared Han→{zh,ja}.
    if counts.get("HIRAGANA") or counts.get("KATAKANA"):
        return {"ja"}
    dominant = max(counts, key=lambda k: counts[k])
    return set(_SCRIPT_TO_LANGS.get(dominant, set()))


# ── Country / region detection from query text ───────────────────────────────
def _build_country_vocab() -> dict[str, tuple[str, Optional[str]]]:
    """``lowercased name/alias -> (canonical country, region_bucket)``.

    Built from the World-Bank region_buckets vocabulary plus the common-alias
    table, both already load-bearing elsewhere. Cached.
    """
    global _COUNTRY_VOCAB
    if _COUNTRY_VOCAB is not None:
        return _COUNTRY_VOCAB
    from src.region_buckets import get_buckets, lookup_region  # local: avoid cycle
    from src.stages._helpers import COUNTRY_ALIASES

    vocab: dict[str, tuple[str, Optional[str]]] = {}
    for bucket_key, meta in get_buckets().items():
        for country in meta.get("countries") or []:
            vocab[country.lower()] = (country, bucket_key)
    for alias, canonical in COUNTRY_ALIASES.items():
        vocab.setdefault(alias.lower(), (canonical, lookup_region(canonical)))
    _COUNTRY_VOCAB = vocab
    return vocab


def _country_region_hits(query: str) -> tuple[set[str], set[str]]:
    """Countries and region_buckets named in the query (word-boundary match)."""
    qlower = query.lower()
    countries: set[str] = set()
    buckets: set[str] = set()
    for name, (canonical, bucket) in _build_country_vocab().items():
        if re.search(r"\b" + re.escape(name) + r"\b", qlower):
            countries.add(canonical)
            if bucket:
                buckets.add(bucket)
    return countries, buckets


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2}


# ── Endpoint selection (deterministic, no embedder) ──────────────────────────
def score_entry(
    entry: dict,
    qtokens: set[str],
    qlangs: set[str],
    countries: set[str],
    buckets: set[str],
) -> float:
    """Lexical topic-affinity score for one on_demand entry against a query."""
    score = 0.0
    if qlangs and (set(entry.get("languages") or []) & qlangs):
        score += _W_LANG
    if (entry.get("country") in countries) or (entry.get("region_bucket") in buckets):
        score += _W_COUNTRY
    tag_tokens: set[str] = set()
    for tag in entry.get("proposed_beat_tags") or []:
        tag_tokens |= _tokenize(str(tag))
    score += _W_TAG * len(tag_tokens & qtokens)
    return score


def _sort_key(entry: dict, score: float) -> tuple:
    ev = entry.get("evidence") or {}
    # score desc, then observed authority: more appearances, better tier
    # (tier 1 = top), then hostname for a total, stable order.
    return (
        -score,
        -(ev.get("appearance_count") or 0),
        entry.get("tier_observed") or 99,
        entry.get("outlet_hostname") or "",
    )


def select_endpoints(
    query: str, catalog: list[dict], max_endpoints: Optional[int] = None
) -> tuple[list[dict], str]:
    """Pick up to ``max_endpoints`` on_demand entries for a query.

    Returns ``(entries, basis)`` where basis is ``"topic_signal"`` when at
    least one entry matched a language/country/tag signal, else
    ``"prior_fallback"`` (ranked by observed newsworthiness — logged loudly by
    the caller).
    """
    cap = max_endpoints or _max_endpoints()
    qtokens = _tokenize(query)
    qlangs = detect_query_languages(query)
    countries, buckets = _country_region_hits(query)

    scored = [
        (e, score_entry(e, qtokens, qlangs, countries, buckets)) for e in catalog
    ]
    basis = "topic_signal" if any(s > 0 for _, s in scored) else "prior_fallback"
    scored.sort(key=lambda es: _sort_key(es[0], es[1]))
    return [e for e, _ in scored[:cap]], basis


# ── Fetch (encoding-safe, dated-only) ────────────────────────────────────────
def _parse_pubdate(entry: Any) -> Optional[str]:
    """ISO-8601 pubdate from a feedparser entry, or None if unparseable.

    Mirrors scripts/fetch_feeds.py::parse_rss_entries — struct_time via
    ``timegm`` (UTC) so a missing/garbled date yields None (→ item dropped)."""
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return None
    try:
        return datetime.fromtimestamp(timegm(published), tz=timezone.utc).isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def parse_feed_dated_items(content: bytes, entry: dict) -> tuple[list[dict], int]:
    """Parse raw feed bytes → (dated_items, n_undated_dropped).

    Encoding-safe: feedparser.parse on the raw bytes (NOT resp.text) so
    prolog-declared encodings on the non-Latin streams are honored
    (CODE-REVIEW-2026-07-02 M-P4, same as fetch_feeds). Items without a
    parseable pubdate are excluded and counted — the registry's dated-only
    promise.
    """
    feed = feedparser.parse(content)
    items: list[dict] = []
    undated = 0
    for e in feed.entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        pub = _parse_pubdate(e)
        if pub is None:
            undated += 1
            continue
        summary = (e.get("summary") or e.get("description") or "").strip()
        if summary:
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            if len(summary) > 500:
                summary = summary[:497] + "..."
        items.append(
            {
                "title": title,
                "url": (e.get("link") or "").strip(),
                "content": summary,
                "published_at": pub,
                "outlet": entry.get("name"),
                "outlet_hostname": entry.get("outlet_hostname"),
            }
        )
    return items, undated


async def fetch_endpoint(
    client: httpx.AsyncClient, entry: dict
) -> tuple[list[dict], int]:
    """Fetch one endpoint → (dated_items, n_undated_dropped). Cached per URL.

    One alt retry on failure; no further retries. Cache stores only the dated
    items (undated count is 0 on a cache hit — already dropped at fetch time)."""
    url = entry.get("url") or ""
    if not url:
        return [], 0
    if url in _FEED_CACHE:
        return _FEED_CACHE[url], 0
    content: Optional[bytes] = None
    for attempt in range(2):  # initial + one alt attempt
        try:
            resp = await client.get(url, follow_redirects=True, timeout=_FETCH_TIMEOUT)
            resp.raise_for_status()
            content = resp.content
            break
        except Exception as exc:  # noqa: BLE001 — network is best-effort
            if attempt == 1:
                logger.warning(
                    "registry_search: endpoint %r (%s) failed: %s",
                    entry.get("name"),
                    url,
                    exc,
                )
    if content is None:
        _FEED_CACHE[url] = []
        return [], 0
    items, undated = parse_feed_dated_items(content, entry)
    _FEED_CACHE[url] = items
    return items, undated


# ── Relevance ranking (shared pinned embedder singleton) ─────────────────────
def rank_items(
    query: str, items: list[dict], n: int, embedder: Any = None
) -> list[dict]:
    """Return the ``n`` items most relevant to the query by cosine similarity
    over embeddings of ``title + summary``.

    REUSES the process-wide pinned embedder singleton
    (:func:`src.stages.coherence._get_default_embedder`) — passing ``embedder``
    is for tests only; production never instantiates a second embedder."""
    if not items:
        return []
    if embedder is None:
        from src.stages.coherence import _get_default_embedder

        embedder = _get_default_embedder()

    import numpy as np

    texts: Sequence[str] = [query] + [
        (it.get("title", "") + " " + it.get("content", "")).strip() for it in items
    ]
    vecs = embedder.embed_batch(texts)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    unit = vecs / norms
    sims = unit[1:] @ unit[0]
    order = sorted(range(len(items)), key=lambda i: (-float(sims[i]), i))
    return [items[i] for i in order[:n]]


# ── Provider entrypoint ──────────────────────────────────────────────────────
def _format_registry_results(query: str, items: list[dict], n: int) -> str:
    """Emit the documented ``execute`` contract shape (``N. title / url /
    snippet``) — reuses web_search._format_results so there is ONE formatter and
    the output parses with the researcher's own ``_ENTRY_PATTERN``."""
    from src.tools.web_search import _format_results  # lazy: avoid import cycle

    return _format_results(query, items, n)


async def _search_registry(query: str, n: int) -> str:
    """The `registry` provider: topic-conditional retrieval over on_demand feeds.

    Signature matches every other provider in ``web_search.PROVIDERS``
    (``query``, ``n``) — the only signal crossing the tool boundary is the
    query string. Returns the Sonar-parity plain-text block. Cost: $0.
    """
    t0 = time.monotonic()
    catalog = load_on_demand_catalog()
    endpoints, basis = select_endpoints(query, catalog)

    all_items: list[dict] = []
    n_undated = 0
    seen_urls: set[str] = set()
    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        for entry in endpoints:  # sequential per host
            items, undated = await fetch_endpoint(client, entry)
            n_undated += undated
            for it in items:
                url = it.get("url") or ""
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                all_items.append(it)

    ranked = rank_items(query, all_items, n)
    output = _format_registry_results(query, ranked, n)

    wall_ms = int((time.monotonic() - t0) * 1000)
    _LAST_STATS.clear()
    _LAST_STATS.update(
        {
            "provider_used": "registry",
            "query": query,
            "n_endpoints_selected": len(endpoints),
            "selection_basis": basis,
            "n_items_fetched": len(all_items),
            "n_undated_dropped": n_undated,
            "n_returned": len(ranked),
            "cost_usd": 0.0,
            "wall_ms": wall_ms,
        }
    )
    logger.info(
        "registry_search: provider=registry basis=%s n_endpoints_selected=%d "
        "n_items_fetched=%d n_undated_dropped=%d n_returned=%d cost_usd=0.0 "
        "wall_ms=%d query=%r",
        basis,
        len(endpoints),
        len(all_items),
        n_undated,
        len(ranked),
        wall_ms,
        query,
    )
    return output
