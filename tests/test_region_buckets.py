"""Tests for src/region_buckets.py — country -> WB-region lookup."""

from __future__ import annotations

import json
from pathlib import Path

from src.region_buckets import get_buckets, lookup_region


def test_lookup_region_known_country():
    assert lookup_region("Germany") == "europe_central_asia"


def test_lookup_region_russia_in_europe_central_asia():
    # Regression: the legacy REGION_CONFIG mapped Russia to "South & Central
    # Asia". The new mapping follows WB and assigns it to Europe & Central Asia.
    assert lookup_region("Russia") == "europe_central_asia"


def test_lookup_region_turkey_in_mena_divergence():
    # Documented divergence: Turkey -> MENA (not Europe & Central Asia).
    assert lookup_region("Turkey") == "middle_east_north_africa"


def test_lookup_region_pakistan_in_south_asia_divergence():
    # Documented divergence: Pakistan stays in South Asia (not WB-2024 MENA-AP).
    assert lookup_region("Pakistan") == "south_asia"


def test_lookup_region_afghanistan_in_south_asia_divergence():
    # Same divergence covers Afghanistan.
    assert lookup_region("Afghanistan") == "south_asia"


def test_lookup_region_unknown_country_returns_none():
    assert lookup_region("Atlantis") is None


def test_lookup_region_empty_input_returns_none():
    assert lookup_region("") is None
    assert lookup_region(None) is None


def test_all_outlet_registry_countries_bucketed():
    """Operational invariant: every country we actually see in production
    (i.e. mentioned in config/outlet_registry.json) must have a bucket."""
    registry_path = (
        Path(__file__).resolve().parent.parent
        / "config"
        / "outlet_registry.json"
    )
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    missing: list[tuple[str, str]] = []
    for hostname, entry in data.items():
        if hostname.startswith("_") or not isinstance(entry, dict):
            continue
        country = entry.get("country")
        if not country:
            continue
        if lookup_region(country) is None:
            missing.append((hostname, country))
    assert not missing, (
        f"countries in outlet_registry.json without a region bucket: {missing}"
    )


def test_buckets_count_is_seven():
    assert len(get_buckets()) == 7


def test_no_country_in_two_buckets():
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for bucket_key, bucket in get_buckets().items():
        for country in bucket.get("countries") or []:
            if country in seen:
                duplicates.append((country, seen[country], bucket_key))
            else:
                seen[country] = bucket_key
    assert not duplicates, f"countries in two buckets: {duplicates}"
