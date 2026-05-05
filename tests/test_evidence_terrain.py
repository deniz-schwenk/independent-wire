"""Tests for scripts/evidence_terrain.py — bucket-aggregated topographic SVG."""

from __future__ import annotations

import re

from scripts.evidence_terrain import TITLE_MAX_LEN, render_evidence_terrain


def test_render_terrain_returns_svg_string():
    """Smoke: well-formed SVG envelope with non-trivial body length."""
    svg = render_evidence_terrain(
        {"Germany": 5}, title="Test", date="May 5, 2026"
    )
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    # Body should be substantial (washes + isolines + cartouches + caption).
    assert len(svg) > 5000
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
        {"Germany": 3, "France": 2},
        title="Agg test",
        date="May 5, 2026",
    )

    def count_for(label: str) -> int:
        idx = svg.find(label)
        assert idx != -1, f"cartouche label {label!r} not found"
        # The number text follows the label in source order, in the same
        # cartouche group. Match the next ">N</text>" after the label.
        m = re.search(r">(\d+)</text>", svg[idx:])
        assert m is not None, f"no count text after {label!r}"
        return int(m.group(1))

    assert count_for("EUROPE & CENTRAL ASIA") == 5
    assert count_for("NORTH AMERICA") == 0
    assert count_for("MIDDLE EAST & NORTH AFRICA") == 0
    assert count_for("EAST ASIA & PACIFIC") == 0
    assert count_for("SOUTH ASIA") == 0
    assert count_for("SUB-SAHARAN AFRICA") == 0
    assert count_for("LATIN AMERICA & CARIBBEAN") == 0


def test_render_terrain_unbucketed_country_appears_in_footer():
    """A country not in any region bucket is reported in the footer line
    and is excluded from any bucket count."""
    svg = render_evidence_terrain(
        {"Atlantis": 3, "Germany": 2}, title="Unbucketed", date="May 5, 2026",
    )
    assert "3 sources from countries not regionally classified" in svg
    # Total still includes the unbucketed entry.
    m = re.search(r"TOTAL SOURCES[^<]*<tspan[^>]*>(\d+)</tspan>", svg)
    assert m is not None
    assert int(m.group(1)) == 5


def test_render_terrain_total_sources_caption_correct():
    """TOTAL SOURCES anchor reflects the source sum exactly."""
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
    m = re.search(r"TOTAL SOURCES[^<]*<tspan[^>]*>(\d+)</tspan>", svg)
    assert m is not None, "TOTAL SOURCES + tspan number not found"
    assert int(m.group(1)) == 17


def test_render_terrain_truncates_long_title():
    """A 100-char title is truncated to TITLE_MAX_LEN + ellipsis (≤81 chars)."""
    long_title = "x" * 100
    svg = render_evidence_terrain(
        {"Germany": 1}, title=long_title, date="May 5, 2026",
    )
    assert long_title not in svg
    truncated = long_title[:TITLE_MAX_LEN] + "…"
    assert truncated in svg
    assert len(truncated) == TITLE_MAX_LEN + 1
    assert TITLE_MAX_LEN + 1 <= 81
