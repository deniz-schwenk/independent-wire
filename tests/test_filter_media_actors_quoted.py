"""Tests for the filter_media_actors_quoted topic-stage.

The stage drops `type: media` entries from every source's `actors_quoted`
list, leaves all other types and shapes untouched, and is a no-op when
no source carries a media actor.
"""

from __future__ import annotations

import asyncio
import logging

from src.bus import RunBus, TopicBus
from src.stages.topic_stages import filter_media_actors_quoted


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus = None):
    return (rb or RunBus()).as_readonly()


def test_filter_media_actors_quoted_drops_type_media_entries():
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "outlet": "Al Jazeera",
            "actors_quoted": [
                {"name": "Channel 14", "role": "Outlet", "type": "media"},
                {"name": "Donald Trump", "role": "US President", "type": "government"},
                {"name": "Israel Hayom", "role": "Daily", "type": "media"},
            ],
        }
    ]

    tb_after = _run(filter_media_actors_quoted, tb, _ro())

    actors = tb_after.final_sources[0]["actors_quoted"]
    assert len(actors) == 1
    assert actors[0]["name"] == "Donald Trump"
    assert actors[0]["type"] == "government"


def test_filter_media_actors_quoted_empty_and_missing_pass_through():
    """Sources with empty `actors_quoted` and sources missing the field
    altogether both pass through unchanged."""
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "A", "actors_quoted": []},
        {"id": "src-002", "outlet": "B"},  # no actors_quoted key at all
    ]

    tb_after = _run(filter_media_actors_quoted, tb, _ro())

    assert tb_after.final_sources[0]["actors_quoted"] == []
    assert "actors_quoted" not in tb_after.final_sources[1]
    # Other fields preserved.
    assert tb_after.final_sources[0]["outlet"] == "A"
    assert tb_after.final_sources[1]["outlet"] == "B"


def test_filter_media_actors_quoted_preserves_all_non_media_types():
    """Every non-media value from the Phase 1 type vocabulary survives the
    filter — only `media` is dropped."""
    non_media_types = [
        "government",
        "legislature",
        "judiciary",
        "military",
        "industry",
        "civil_society",
        "academia",
        "international_org",
        "affected_community",
    ]
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "outlet": "Reuters",
            "actors_quoted": [
                {"name": f"actor-{t}", "role": "x", "type": t}
                for t in non_media_types
            ]
            + [
                {"name": "BBC", "role": "Outlet", "type": "media"},
            ],
        }
    ]

    tb_after = _run(filter_media_actors_quoted, tb, _ro())

    actors = tb_after.final_sources[0]["actors_quoted"]
    types_kept = [a["type"] for a in actors]
    assert sorted(types_kept) == sorted(non_media_types)
    assert "media" not in types_kept


def test_filter_media_actors_quoted_no_op_when_no_media():
    """When no source has a media actor, the stage returns the bus
    unchanged (passes through cleanly)."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "outlet": "Reuters",
            "actors_quoted": [
                {"name": "Donald Trump", "role": "US President", "type": "government"},
            ],
        }
    ]

    tb_after = _run(filter_media_actors_quoted, tb, _ro())

    assert tb_after.final_sources == tb.final_sources


def test_filter_media_actors_quoted_handles_non_dict_entries():
    """Non-dict actor entries are preserved as-is (defensive, doesn't
    crash on malformed upstream data)."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                "stray-string-entry",
                {"name": "BBC", "type": "media"},
                {"name": "Trump", "type": "government"},
            ],
        }
    ]

    tb_after = _run(filter_media_actors_quoted, tb, _ro())

    actors = tb_after.final_sources[0]["actors_quoted"]
    assert "stray-string-entry" in actors
    assert any(isinstance(a, dict) and a.get("name") == "Trump" for a in actors)
    assert not any(isinstance(a, dict) and a.get("type") == "media" for a in actors)


def test_filter_media_actors_quoted_logs_tally(caplog):
    """The stage logs an INFO line summarising drops per topic."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                {"name": "BBC", "type": "media"},
                {"name": "Trump", "type": "government"},
            ],
        },
        {
            "id": "src-002",
            "actors_quoted": [
                {"name": "Channel 14", "type": "media"},
            ],
        },
    ]

    with caplog.at_level(logging.INFO, logger="src.stages.topic_stages"):
        _run(filter_media_actors_quoted, tb, _ro())

    matches = [
        r for r in caplog.records
        if "filter_media_actors_quoted" in r.getMessage()
    ]
    assert matches, "expected a logger.info tally line"
    msg = matches[0].getMessage()
    assert "dropped 2 actors" in msg
    assert "2 source" in msg


def test_filter_media_actors_quoted_empty_final_sources_returns_bus_unchanged():
    """No sources at all → no-op."""
    tb = TopicBus()
    tb.final_sources = []
    tb_after = _run(filter_media_actors_quoted, tb, _ro())
    assert tb_after.final_sources == []


def test_filter_media_actors_quoted_does_not_mutate_input_source():
    """The stage deep-copies the source it modifies; the input dict on
    the bus is not mutated in place (downstream consumers reading the
    pre-stage view would otherwise see a corrupted snapshot)."""
    src_original = {
        "id": "src-001",
        "actors_quoted": [
            {"name": "BBC", "type": "media"},
            {"name": "Trump", "type": "government"},
        ],
    }
    tb = TopicBus()
    tb.final_sources = [src_original]

    _run(filter_media_actors_quoted, tb, _ro())

    # Input dict must still carry both entries.
    assert len(src_original["actors_quoted"]) == 2
    assert src_original["actors_quoted"][0]["name"] == "BBC"
