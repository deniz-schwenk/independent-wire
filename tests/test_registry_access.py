"""TASK-REGISTRY-A1 — unified catalog access flags + on_demand seed ingestion.

Two concerns:
  1. the daily-path guard in ``fetch_feeds.load_sources`` (on_demand invisible,
     missing-access treated-as-daily + warned once, disabled still filtered);
  2. ingestion round-trip invariants on the committed ``config/sources.json``
     (80 daily untouched, 83 on_demand present + normalised).
"""
import json
import logging
from pathlib import Path

import scripts.fetch_feeds as ff
from scripts.fetch_feeds import load_sources

ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
FEEDS = CATALOG["feeds"]
DAILY = [f for f in FEEDS if f.get("access") == "daily"]
ON_DEMAND = [f for f in FEEDS if f.get("access") == "on_demand"]


def _point_at(monkeypatch, tmp_path, feeds):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "sources.json").write_text(
        json.dumps({"version": 1, "feeds": feeds}), encoding="utf-8")
    monkeypatch.setattr(ff, "ROOT", tmp_path)


# --------------------------------------------------------------- guard ------
def test_on_demand_is_invisible_to_the_daily_path(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path, [
        {"name": "D1", "url": "u1", "type": "rss", "access": "daily", "enabled": True},
        {"name": "OD1", "url": "u2", "type": "rss", "access": "on_demand", "enabled": True},
        {"name": "OD2", "url": "u3", "type": "rss", "access": "on_demand"},
    ])
    got = load_sources()
    assert [f["name"] for f in got] == ["D1"]
    assert all(f["access"] == "daily" for f in got)


def test_missing_access_is_treated_as_daily_and_warns_once(monkeypatch, tmp_path, caplog):
    _point_at(monkeypatch, tmp_path, [
        {"name": "NoAccess", "url": "u1", "type": "rss", "enabled": True},
        {"name": "OD", "url": "u2", "type": "rss", "access": "on_demand"},
    ])
    with caplog.at_level(logging.WARNING, logger="fetch_feeds"):
        got = load_sources()
    assert [f["name"] for f in got] == ["NoAccess"]  # backward-compatible: missing -> daily
    access_warnings = [r for r in caplog.records if "access" in r.message.lower()]
    assert len(access_warnings) == 1  # loud, exactly once per run
    assert "NoAccess" in access_warnings[0].message


def test_disabled_daily_entry_still_filtered(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path, [
        {"name": "On", "url": "u1", "type": "rss", "access": "daily", "enabled": True},
        {"name": "Off", "url": "u2", "type": "rss", "access": "daily", "enabled": False},
    ])
    assert [f["name"] for f in load_sources()] == ["On"]


def test_no_warning_when_every_entry_has_access(monkeypatch, tmp_path, caplog):
    _point_at(monkeypatch, tmp_path, [
        {"name": "D", "url": "u1", "type": "rss", "access": "daily", "enabled": True},
        {"name": "OD", "url": "u2", "type": "rss", "access": "on_demand"},
    ])
    with caplog.at_level(logging.WARNING, logger="fetch_feeds"):
        load_sources()
    assert not [r for r in caplog.records if "access" in r.message.lower()]


# ---------------------------------------------------- ingestion round-trip --
def test_catalog_split_counts():
    assert len(DAILY) == 80
    assert len(ON_DEMAND) == 83
    assert all(f.get("access") in ("daily", "on_demand") for f in FEEDS)


def test_daily_entries_untouched_by_ingestion():
    # daily entries keep the original feed shape + access:daily and gain NO seed fields
    for f in DAILY:
        assert f["access"] == "daily"
        assert {"seed_review", "tier_observed", "access_type", "outlet_hostname"}.isdisjoint(f)


def test_on_demand_entries_shape_and_language_normalisation():
    hosts = set()
    for f in ON_DEMAND:
        assert f["access"] == "on_demand"
        assert f["access_type"] == "public"          # provenance: public endpoints only
        assert f["seed_review"] == "pending"         # observed, not confirmed
        assert f["outlet_hostname"] and f["url"]
        assert f["name"]
        assert isinstance(f["languages"], list) and f["languages"]
        # every language ISO-normalised (2-char lower) — no "English"-style literals
        for lang in f["languages"]:
            assert isinstance(lang, str) and len(lang) == 2 and lang.islower(), (f["name"], lang)
        assert "region_bucket" in f and "country" in f
        assert isinstance(f["proposed_beat_tags"], list)
        assert set(f["evidence"]) == {"appearance_count", "distinct_topics", "first_seen", "last_seen"}
        hosts.add(f["outlet_hostname"])
    assert len(hosts) == 83  # no duplicate hostnames ingested
