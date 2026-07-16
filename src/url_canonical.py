"""Deterministic canonical-URL normalization for dedup keys.

A single pure function used both at ingestion (fetch/collector merge path) and
as the TP source-assembly safety net, so that URL variants of the same article
— identical except for a tracking query param, casing, a fragment, or a
trailing slash — collapse to one finding/source *before* any LLM stage sees
them (deterministic-before-LLM).

The canonical form is a **dedup key only**. It is never published: the
surviving record keeps its ORIGINAL ``url`` string. Callers therefore treat a
``None`` return as "not a usable absolute URL — never dedup this one" and fall
back to the record's own identity.

Reproducer that motivated the tracking-param blocklist: tp-2026-07-14-001
shipped the same Al Jazeera article twice (``src-026`` vs ``src-033``) because
one URL carried ``?traffic_source=rss`` and the other did not — the older,
query-preserving normalizer kept them distinct.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

# Query params that identify a traffic source / campaign / click, never the
# article. Removed from the dedup key so tracking-param variants collapse.
# Exact matches are case-insensitive; ``utm_*`` is a case-insensitive PREFIX
# match (utm_source, utm_medium, utm_campaign, utm_term, utm_content, …).
# Deliberately conservative: every OTHER query param is preserved, because many
# sites carry the article key in the query (e.g. ``?id=12345``).
_TRACKING_PARAMS_EXACT = frozenset(
    {
        "traffic_source",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "cmpid",
    }
)
_TRACKING_PREFIXES = ("utm_",)


def _is_tracking_param(name: str) -> bool:
    low = name.lower()
    if low in _TRACKING_PARAMS_EXACT:
        return True
    return any(low.startswith(p) for p in _TRACKING_PREFIXES)


def canonical_url(url: object) -> Optional[str]:
    """Return a canonical dedup key for ``url``, or ``None`` when it is not a
    usable absolute URL (non-string, blank, or netloc-less) — in which case the
    caller must never dedup on it.

    Canonicalization (deterministic, pure):
    - lowercase the scheme and host (netloc),
    - strip the URL fragment,
    - strip a single trailing slash on the path,
    - remove ONLY known tracking query params (:data:`_TRACKING_PARAMS_EXACT`
      plus the ``utm_*`` prefix); every other param is preserved, in its
      original order, including blank values (``?x=`` stays).

    NOT done: dropping ``www.``, reordering surviving params, or touching any
    non-tracking param — two URLs that differ in a real query value stay
    distinct.
    """
    if not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if not parts.netloc:
        return None  # relative / unparseable -> never dedup

    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = parts.path
    if path.endswith("/"):
        path = path[:-1]  # strip a single trailing slash

    rebuilt = f"{scheme}://{host}{path}"
    if parts.query:
        survivors = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _is_tracking_param(k)
        ]
        if survivors:
            rebuilt += "?" + urlencode(survivors)
    return rebuilt
