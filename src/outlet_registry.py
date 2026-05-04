"""Outlet registry — canonical metadata lookup keyed by hostname.

The registry lives at ``config/outlet_registry.json`` and is the single
source of truth for outlet country/language/type. Hydration enrichment
(``src/hydration.py:_hydrate_one``) consults this registry to fill the
``country`` and ``outlet`` fields on fetch results, replacing the
silent-null pass-through that produced ``country: null`` on Hydrated
sources before the fix.

Match order in :func:`lookup_outlet`:

1. Exact hostname (lowercased, ``www.`` stripped).
2. Parent-domain fallback — strip the leading subdomain label and retry,
   recursing until the domain has only two labels left or a hit is found.

A miss logs a single WARNING per process per unknown hostname so the
operator sees which outlets need to be added without flooding the log.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "outlet_registry.json"

# In-process cache of hostnames that produced a miss, so we log each
# unknown only once.
_warned_misses: set[str] = set()


def _normalise_hostname(url: str) -> str:
    """Return the lowercase hostname for ``url`` with any leading ``www.``
    stripped.

    Empty string is returned for inputs that don't parse to a hostname,
    so callers can do a single membership test against the registry
    without re-parsing.
    """
    if not isinstance(url, str) or not url:
        return ""
    try:
        # urlparse handles bare-host inputs ("example.com/path") poorly
        # (treats the whole thing as path) — prepend a scheme when missing.
        if "://" not in url:
            url = "http://" + url
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, dict]:
    """Load and cache the registry JSON. Returns ``{}`` on any I/O or
    parse failure — callers fall back to whatever the input dict
    already carried, so a missing or broken registry degrades to the
    pre-fix behaviour rather than crashing the pipeline.
    """
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("outlet_registry: file not found at %s", _REGISTRY_PATH)
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("outlet_registry: failed to load %s: %s", _REGISTRY_PATH, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    # Strip schema metadata keys (anything starting with ``_``).
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


def lookup_outlet(url: str) -> Optional[dict]:
    """Return the canonical metadata dict for the URL's outlet, or
    ``None`` if no registry entry matches.

    Exact hostname is tried first. If absent, the leading subdomain
    label is stripped and the lookup retries against the parent domain
    until either a hit is found or only two labels remain. The first hit
    along that chain wins.

    On a final miss, a single WARNING is logged per unknown hostname per
    process so the operator can see which outlets need entries without
    duplicate noise on every URL.
    """
    host = _normalise_hostname(url)
    if not host:
        return None

    registry = _load_registry()
    if not registry:
        return None

    # Exact match.
    if host in registry:
        return registry[host]

    # Parent-domain fallback. Walk leading-subdomain labels off until we
    # either match or reach a two-label domain.
    parts = host.split(".")
    while len(parts) > 2:
        parts = parts[1:]
        candidate = ".".join(parts)
        if candidate in registry:
            return registry[candidate]

    # Miss — log once per host.
    if host not in _warned_misses:
        _warned_misses.add(host)
        logger.warning("outlet_registry: no entry for hostname %r", host)
    return None


def reset_miss_cache() -> None:
    """Clear the in-process miss cache. Test-only — never called from
    pipeline code."""
    _warned_misses.clear()


__all__ = ["lookup_outlet", "_normalise_hostname", "reset_miss_cache"]
