"""Tests for scripts/evidence_terrain.py — bucket-aggregated topographic SVG."""

from __future__ import annotations

import re

from scripts.evidence_terrain import render_evidence_terrain


def test_render_terrain_returns_svg_string():
    """Smoke: well-formed SVG envelope; cartouche label visible in output."""
    svg = render_evidence_terrain(
        {"Germany": 5}, title="Test", date="May 5, 2026"
    )
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert "EUROPE & CENTRAL ASIA" in svg


def test_render_terrain_empty_input_still_renders():
    """Empty input still produces a valid SVG with all seven cartouches and
    a 0-source caption."""
    svg = render_evidence_terrain({}, title="Empty", date="")
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    expected_labels = [
        "EAST ASIA & PACIFIC",
        "EUROPE & CENTRAL ASIA",
        "LATIN AMERICA & CARIBBEAN",
        "MIDDLE EAST & NORTH AFRICA",
        "NORTH AMERICA",
        "SOUTH ASIA",
        "SUB-SAHARAN AFRICA",
    ]
    for label in expected_labels:
        assert label in svg, f"missing cartouche label {label!r}"
    # Total caption shows zero.
    assert "0 sources" in svg


def test_render_terrain_aggregates_to_buckets_correctly():
    """Counts in cartouches reflect the bucket aggregation."""
    svg = render_evidence_terrain(
        {"Germany": 3, "France": 2, "United States": 4, "Iran": 1},
        title="Agg test",
        date="May 5, 2026",
    )
    # Per-cartouche count text takes the form ">{N} sources<" or ">{1} source<".
    # Anchor on the cartouche label preceding the count to avoid catching
    # the same N elsewhere in the SVG (e.g. in iso path coords).
    def count_after(label: str) -> int:
        # Label appears in a <text>...</text>, then the count appears in the
        # next sibling <text>...</text> as "{N} source(s)".
        idx = svg.find(label)
        assert idx != -1, f"cartouche label {label!r} not found"
        rest = svg[idx:]
        m = re.search(r">(\d+)\s+source", rest)
        assert m is not None, f"no count text after {label!r}"
        return int(m.group(1))

    assert count_after("EUROPE & CENTRAL ASIA") == 5  # Germany 3 + France 2
    assert count_after("NORTH AMERICA") == 4          # US 4
    assert count_after("MIDDLE EAST & NORTH AFRICA") == 1  # Iran 1
    assert count_after("EAST ASIA & PACIFIC") == 0
    assert count_after("SOUTH ASIA") == 0
    assert count_after("SUB-SAHARAN AFRICA") == 0
    assert count_after("LATIN AMERICA & CARIBBEAN") == 0


def test_render_terrain_unbucketed_country_appears_in_footer():
    """A country not in any region bucket is reported in the footer line
    and is excluded from any bucket count."""
    svg = render_evidence_terrain(
        {"Atlantis": 3, "Germany": 2}, title="Unbucketed", date="May 5, 2026",
    )
    assert "3 sources from countries not regionally classified" in svg
    # Total still includes the unbucketed entry.
    assert "5 sources" in svg


def test_render_terrain_total_sources_caption_correct():
    """Total caption + TOTAL SOURCES anchor reflect the source sum."""
    by = {
        "Germany": 3,
        "United States": 4,
        "Iran": 2,
        "Brazil": 3,
        "China": 2,
        "Pakistan": 1,
        "Nigeria": 2,
    }
    svg = render_evidence_terrain(
        by, title="Big", date="May 5, 2026",
    )
    assert sum(by.values()) == 17
    assert "TOTAL SOURCES" in svg
    # The big-number tspan after TOTAL SOURCES carries the count.
    assert ">17<" in svg


def test_render_terrain_truncates_long_title():
    """A very long title is truncated to TITLE_MAX_LEN + ellipsis."""
    from scripts.evidence_terrain import TITLE_MAX_LEN

    long_title = "x" * 100
    svg = render_evidence_terrain(
        {"Germany": 1}, title=long_title, date="May 5, 2026",
    )
    # The original 100-char string must NOT appear; the truncated form does.
    assert long_title not in svg
    truncated = long_title[:TITLE_MAX_LEN] + "…"
    assert truncated in svg
