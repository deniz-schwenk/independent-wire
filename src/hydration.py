"""Independent Wire — Hydration fetch + text extraction.

Respectful async fetcher for RSS-sourced article URLs. Takes a list of input
dicts (at minimum: ``url``, ``outlet``, ``language``, ``country``), fetches
each URL with aiohttp, extracts full-text with trafilatura, and returns a
same-length list where each input dict is extended with five originary fields:
``status``, ``extracted_text``, ``word_count``, ``error``, ``fetch_duration_ms``.

Design choices:

- **aiohttp, not httpx.** Empirically more tolerant of non-conforming server
  responses (Anadolu Agency sends duplicate ``Transfer-Encoding`` headers that
  httpx rejects — aiohttp accepts).
- **Permissive TLS.** SSL verification disabled at the connector level. Rules
  out TLS-version mismatches as a reason for connection failures. Only
  acceptable because we are a named, identifiable fetcher and outlets can
  block us by user-agent if they object.
- **robots.txt respected.** Domains that disallow our user-agent (or ``*``)
  return status ``robots_disallowed`` without any fetch attempt.
- **Per-domain rate limit.** At most one request every
  ``per_domain_rate_limit_s`` seconds to any single host. Different hosts
  run in parallel.
- **No bot-challenge circumvention.** Cloudflare / access-denied pages
  classify as ``bot_blocked`` and move on.
- **Failures are classified, never raised.** Every input URL produces exactly
  one output dict, even if every network call fails.

Status values (one of exactly these seven):

- ``success`` — HTTP 200, extraction ≥ partial threshold words.
- ``partial`` — HTTP 200, extraction < partial threshold words (paywall
  stubs, teaser content, empty extractions).
- ``bot_blocked`` — HTTP 403/429, or HTTP 200 body containing a known bot
  challenge marker.
- ``robots_disallowed`` — robots.txt disallows our user-agent for the URL.
- ``http_error`` — HTTP 4xx/5xx other than 403/429.
- ``connection_error`` — DNS failure, TLS error, connection refused, or
  another network-layer failure.
- ``timeout`` — whole request exceeded the configured timeout.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections import defaultdict
from typing import Any, Iterable, Literal, Mapping
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import aiohttp
import trafilatura

logger = logging.getLogger(__name__)


Status = Literal[
    "success",
    "partial",
    "bot_blocked",
    "robots_disallowed",
    "http_error",
    "connection_error",
    "timeout",
]

STATUS_VALUES: tuple[Status, ...] = (
    "success",
    "partial",
    "bot_blocked",
    "robots_disallowed",
    "http_error",
    "connection_error",
    "timeout",
)

DEFAULT_USER_AGENT = "Independent-Wire-Bot/1.0 +https://independentwire.org"
DEFAULT_PER_DOMAIN_RATE_LIMIT_S = 1.0
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_PARTIAL_WORD_THRESHOLD = 50

MAX_REDIRECTS = 5
ROBOTS_FETCH_TIMEOUT_S = 10.0

_BOT_CHALLENGE_MARKERS: tuple[str, ...] = (
    "cf-browser-verification",
    "Just a moment...",
    "challenge-platform",
    "_cf_chl_opt",
    "DDoS protection",
    "Attention Required! | Cloudflare",
    "Access denied",
    "Enable JavaScript and cookies to continue",
    "Please enable cookies",
)


# ---------- helpers ----------

class _DomainRateLimiter:
    """Serialize requests per domain with a minimum interval between them."""

    def __init__(self, min_interval_s: float) -> None:
        self._min_interval = max(0.0, float(min_interval_s))
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last: dict[str, float] = {}

    async def acquire(self, domain: str) -> None:
        async with self._locks[domain]:
            now = time.monotonic()
            elapsed = now - self._last.get(domain, 0.0)
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last[domain] = time.monotonic()


class _RobotsCache:
    """Per-domain robots.txt cache scoped to a single hydrate_urls call."""

    def __init__(self, *, user_agent: str, fetch_timeout_s: float) -> None:
        self._user_agent = user_agent
        self._fetch_timeout_s = fetch_timeout_s
        self._cache: dict[str, RobotFileParser | None] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def is_allowed(
        self,
        session: aiohttp.ClientSession,
        url: str,
        limiter: _DomainRateLimiter,
        domain: str,
    ) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._locks[origin]:
            if origin not in self._cache:
                # First request to this origin — use the rate limiter so the
                # robots.txt fetch counts against the per-domain budget.
                await limiter.acquire(domain)
                self._cache[origin] = await self._fetch_parser(session, origin)
        parser = self._cache[origin]
        if parser is None:
            # Permissive when robots.txt is unreachable or malformed —
            # standard crawler convention.
            return True
        return parser.can_fetch(self._user_agent, url)

    async def _fetch_parser(
        self,
        session: aiohttp.ClientSession,
        origin: str,
    ) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        timeout = aiohttp.ClientTimeout(total=self._fetch_timeout_s)
        try:
            async with session.get(
                robots_url,
                timeout=timeout,
                allow_redirects=True,
                max_redirects=MAX_REDIRECTS,
            ) as response:
                if response.status >= 400:
                    return None
                raw = await response.read()
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            logger.debug("robots.txt unreachable at %s: %s", robots_url, exc)
            return None

        text = _decode(raw, getattr(response, "charset", None))
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return parser


def _decode(raw: bytes, declared_charset: str | None) -> str:
    """Decode response body, preferring declared charset, falling back safely."""
    candidates: list[str] = []
    if declared_charset:
        candidates.append(declared_charset)
    candidates.extend(("utf-8", "latin-1"))
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def _looks_like_bot_challenge(body: str) -> bool:
    return any(marker in body for marker in _BOT_CHALLENGE_MARKERS)


def _blank_originary_fields() -> dict[str, Any]:
    return {
        "status": None,
        "extracted_text": None,
        "word_count": 0,
        "error": None,
        "fetch_duration_ms": 0,
    }


# ---------- per-URL worker ----------

async def _hydrate_one(
    session: aiohttp.ClientSession,
    entry: Mapping[str, Any],
    limiter: _DomainRateLimiter,
    robots_cache: _RobotsCache,
    *,
    partial_word_threshold: int,
) -> dict[str, Any]:
    output: dict[str, Any] = dict(entry)
    output.update(_blank_originary_fields())

    url = entry.get("url")
    if not isinstance(url, str) or not url:
        output["status"] = "connection_error"
        output["error"] = "invalid_url: missing or non-string"
        return output

    try:
        parts = urlsplit(url)
        domain = (parts.hostname or "").lower()
    except Exception as exc:
        output["status"] = "connection_error"
        output["error"] = f"invalid_url: {type(exc).__name__}: {exc}"
        return output

    if not domain or parts.scheme not in {"http", "https"}:
        output["status"] = "connection_error"
        output["error"] = "invalid_url: unsupported scheme or no host"
        return output

    start_mono = time.monotonic()

    # robots.txt check (cached per origin for the duration of the call).
    try:
        allowed = await robots_cache.is_allowed(session, url, limiter, domain)
    except Exception as exc:  # Defensive — cache itself should not raise.
        logger.warning("robots cache error for %s: %s", domain, exc)
        allowed = True

    if not allowed:
        output["status"] = "robots_disallowed"
        output["error"] = "disallowed by robots.txt"
        output["fetch_duration_ms"] = int((time.monotonic() - start_mono) * 1000)
        return output

    # Main fetch.
    await limiter.acquire(domain)
    status_code: int | None = None
    charset: str | None = None
    raw: bytes = b""
    try:
        async with session.get(
            url,
            allow_redirects=True,
            max_redirects=MAX_REDIRECTS,
        ) as response:
            status_code = response.status
            charset = response.charset
            raw = await response.read()
    except asyncio.TimeoutError:
        output["status"] = "timeout"
        output["error"] = "request exceeded timeout"
        output["fetch_duration_ms"] = int((time.monotonic() - start_mono) * 1000)
        return output
    except (aiohttp.ClientError, OSError, ssl.SSLError) as exc:
        output["status"] = "connection_error"
        output["error"] = f"{type(exc).__name__}: {exc}".strip()
        output["fetch_duration_ms"] = int((time.monotonic() - start_mono) * 1000)
        return output

    body = _decode(raw, charset)

    if status_code in (403, 429):
        output["status"] = "bot_blocked"
        output["error"] = f"HTTP {status_code}"
    elif status_code is not None and 400 <= status_code < 600:
        output["status"] = "http_error"
        output["error"] = f"HTTP {status_code}"
    elif _looks_like_bot_challenge(body):
        output["status"] = "bot_blocked"
        output["error"] = "bot-challenge markers in response body"
    else:
        try:
            extracted = trafilatura.extract(body) or ""
        except Exception as exc:
            logger.warning("trafilatura error for %s: %s", url, exc)
            extracted = ""
        word_count = len(extracted.split()) if extracted else 0
        if word_count >= partial_word_threshold:
            output["status"] = "success"
            output["extracted_text"] = extracted
            output["word_count"] = word_count
        else:
            output["status"] = "partial"
            output["extracted_text"] = extracted or None
            output["word_count"] = word_count
            if not extracted:
                output["error"] = "empty extraction"
            else:
                output["error"] = (
                    f"word_count {word_count} below threshold {partial_word_threshold}"
                )

    output["fetch_duration_ms"] = int((time.monotonic() - start_mono) * 1000)
    return output


# ---------- public API ----------

async def hydrate_urls(
    entries: Iterable[Mapping[str, Any]],
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    per_domain_rate_limit_s: float = DEFAULT_PER_DOMAIN_RATE_LIMIT_S,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    partial_word_threshold: int = DEFAULT_PARTIAL_WORD_THRESHOLD,
) -> list[dict[str, Any]]:
    """Fetch and extract full-text for each input URL.

    Args:
        entries: Iterable of input dicts. Each must contain at least ``url``,
            ``outlet``, ``language``, ``country``. Any additional keys pass
            through to the output unchanged.
        user_agent: UA string sent on every request.
        per_domain_rate_limit_s: Minimum seconds between successive requests
            to the same host.
        timeout_s: Total per-request timeout (applies to both robots.txt and
            the article fetch).
        partial_word_threshold: Word-count cutoff between ``success`` and
            ``partial``. Extractions at or above this count classify as
            ``success``; below classify as ``partial``.

    Returns:
        A list of dicts, one per input, in the same order. Each output dict
        contains all input keys plus these originary fields:

        - ``status`` (str): one of the seven values in ``STATUS_VALUES``.
        - ``extracted_text`` (str | None): trafilatura output when present.
        - ``word_count`` (int): whitespace-split count of ``extracted_text``
          (0 when no text was extracted).
        - ``error`` (str | None): short failure description, or ``None`` on
          success.
        - ``fetch_duration_ms`` (int): wall-clock ms for this URL's full
          fetch-and-extract step, including any rate-limit wait.

    Per-URL exceptions never propagate — failures are classified. The only
    way this function raises is if ``aiohttp`` itself fails to construct a
    session, which would be a programming or environment error.
    """
    entries_list = [dict(e) for e in entries]
    if not entries_list:
        return []

    limiter = _DomainRateLimiter(per_domain_rate_limit_s)
    robots_cache = _RobotsCache(
        user_agent=user_agent,
        fetch_timeout_s=min(ROBOTS_FETCH_TIMEOUT_S, timeout_s),
    )

    # Permissive SSL — see module docstring.
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=0, limit_per_host=0)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    headers = {"User-Agent": user_agent, "Accept": "*/*"}

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
        connector=connector,
    ) as session:
        tasks = [
            _hydrate_one(
                session,
                entry,
                limiter,
                robots_cache,
                partial_word_threshold=partial_word_threshold,
            )
            for entry in entries_list
        ]
        return await asyncio.gather(*tasks)
