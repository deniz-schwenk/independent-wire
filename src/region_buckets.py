"""Region buckets — country to World-Bank-region mapping.

The bucket configuration lives at ``config/region_buckets.json`` and is the
single source of truth for the country -> region assignment used by the
source-distribution visualisation (Evidence Terrain) and source-balance
analytics. Schema is documented in the JSON file's ``_schema`` block.

Lookup contract: callers must pass a country name **already canonicalised**
via :func:`src.stages._helpers.normalise_country` upstream. This module
performs no aliasing; ``"USA"`` will not match ``"United States"`` here.
Aliasing is the upstream stage's responsibility.

Top-level JSON keys starting with ``_`` (``_schema``, ``_source``,
``_divergences``) are metadata and are ignored by the loader — only the
``buckets`` sub-dict feeds the country index.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "region_buckets.json"


@lru_cache(maxsize=1)
def _load_buckets() -> dict[str, dict]:
    """Load and cache the buckets sub-dict from the registry JSON.

    Returns ``{}`` on any I/O or parse failure so callers degrade
    gracefully — same pattern as ``outlet_registry._load_registry``.
    """
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("region_buckets: file not found at %s", _REGISTRY_PATH)
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("region_buckets: failed to load %s: %s", _REGISTRY_PATH, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    buckets = data.get("buckets")
    if not isinstance(buckets, dict):
        return {}
    return {k: v for k, v in buckets.items() if isinstance(v, dict)}


@lru_cache(maxsize=1)
def _country_to_bucket() -> dict[str, str]:
    """Inverted index ``{country: bucket_key}`` for O(1) lookup.

    Built from :func:`_load_buckets`. If a country is somehow claimed by
    two buckets (a JSON-build invariant violation), an ERROR is logged
    naming the country and both bucket keys; the first occurrence by
    dict-iteration order wins, keeping the inversion deterministic.
    """
    index: dict[str, str] = {}
    for bucket_key, bucket in _load_buckets().items():
        for country in bucket.get("countries") or []:
            if not isinstance(country, str):
                continue
            existing = index.get(country)
            if existing is not None and existing != bucket_key:
                logger.error(
                    "region_buckets: country %r claimed by both %r and %r; "
                    "keeping %r",
                    country,
                    existing,
                    bucket_key,
                    existing,
                )
                continue
            index[country] = bucket_key
    return index


def lookup_region(country: Optional[str]) -> Optional[str]:
    """Return the bucket key for ``country``, or ``None`` if unmapped.

    The input must be a canonical country name as produced by
    :func:`src.stages._helpers.normalise_country`. Empty string and
    ``None`` both return ``None`` defensively. No aliasing is performed
    here — pass-through misses are silent (no log noise) so the caller
    decides whether an unbucketed country is a fault.
    """
    if not country:
        return None
    return _country_to_bucket().get(country)


def get_buckets() -> dict[str, dict]:
    """Return a shallow copy of the buckets dict so callers cannot
    mutate the cached registry."""
    return dict(_load_buckets())


__all__ = ["lookup_region", "get_buckets"]
