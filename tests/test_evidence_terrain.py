"""Tests for scripts/evidence_terrain.py — bucket-aggregated topographic SVG."""

from __future__ import annotations

import re

from scripts.evidence_terrain import (
    CANVAS_H,
    CANVAS_W,
    render_evidence_terrain,
)


def test_render_terrain_returns_svg_string():
    """Smoke: well-formed SVG envelope with non-trivial body length."""
    svg = render_evidence_terrain({"Germany": 5})
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    # Body should be substantial (background + per-region rings + cartouches).
    assert len(svg) > 5000
    # Cartouche label appears (wrapped on " & " for Europe & Central Asia).
    assert "EUROPE &" in svg
    assert "CENTRAL ASIA" in svg


def test_render_terrain_empty_input_renders_all_seven_dimmed():
    """Empty input renders all seven legend rows with a dimmed "0" and
    a dimmed region name."""
    svg = render_evidence_terrain({})
    assert svg.startswith("<svg")
    # Every region's first label line appears (handles two-line wraps).
    expected_first_tokens = [
        "EAST ASIA &",          # EAST ASIA & PACIFIC
        "EUROPE &",             # EUROPE & CENTRAL ASIA
        "LATIN AMERICA &",      # LATIN AMERICA & CARIBBEAN
        "MIDDLE EAST &",        # MIDDLE EAST & NORTH AFRICA
        "NORTH",                # NORTH AMERICA wraps (13 chars > 11)
        "SOUTH ASIA",           # single line, ≤11 chars
        "SUB-SAHARAN",          # SUB-SAHARAN AFRICA wraps on space
    ]
    for token in expected_first_tokens:
        assert token in svg, f"missing legend label token {token!r}"
    # Every legend row renders "0" plus the footer total ("0") = 8 zeros.
    zero_count = len(re.findall(r">0</text>", svg))
    assert zero_count >= 7, f"expected ≥7 zeros, got {zero_count}"
    # Zero-row elements (numbers, names, rules, connectors) all dimmed at
    # opacity 0.35.
    assert svg.count('opacity="0.35"') >= 7


def test_render_terrain_aggregates_to_buckets_correctly():
    """{"Germany": 3, "France": 2} → europe_central_asia row shows 5;
    every other bucket shows 0."""
    svg = render_evidence_terrain({"Germany": 3, "France": 2})

    def count_after(label_first_line: str) -> int:
        idx = svg.find(label_first_line)
        assert idx != -1, f"label {label_first_line!r} not found"
        m = re.search(r">(\d+)</text>", svg[idx:])
        assert m is not None, f"no count text after {label_first_line!r}"
        return int(m.group(1))

    assert count_after("EUROPE &") == 5
    assert count_after("NORTH") == 0   # NORTH AMERICA wraps to NORTH / AMERICA
    assert count_after("MIDDLE EAST &") == 0
    assert count_after("EAST ASIA &") == 0
    assert count_after("SOUTH ASIA") == 0
    assert count_after("SUB-SAHARAN") == 0
    assert count_after("LATIN AMERICA &") == 0


def test_render_terrain_unbucketed_country_appears_in_footer():
    """A country not in any region bucket is reported in the footer line
    and is excluded from any bucket count."""
    svg = render_evidence_terrain({"Atlantis": 3, "Germany": 2})
    assert "3 sources from countries not regionally classified" in svg
    # Total (footer caption) reflects the unbucketed total too.
    m = re.search(r"(\d+)\s*TOTAL SOURCES", svg)
    assert m is not None
    assert int(m.group(1)) == 5


def test_render_terrain_total_sources_caption_correct():
    """Total caption shows the correct sum across all buckets."""
    by = {
        "Germany": 3,
        "United States": 4,
        "Iran": 2,
        "Brazil": 3,
        "China": 2,
        "Pakistan": 1,
        "Nigeria": 2,
    }
    svg = render_evidence_terrain(by)
    assert sum(by.values()) == 17
    m = re.search(r"(\d+)\s*TOTAL SOURCES", svg)
    assert m is not None, "TOTAL SOURCES caption not found"
    assert int(m.group(1)) == 17


def test_render_terrain_no_text_outside_viewbox():
    """Every <text>/<tspan> x and y attribute sits inside the viewBox.
    Cartouche text outside the canvas would render outside the visible
    SVG; this is the regression guard for that class of layout bug."""
    svg = render_evidence_terrain(
        {"Germany": 5, "Iran": 3, "United States": 4, "Brazil": 2,
         "Nigeria": 2, "Pakistan": 1, "China": 2}
    )
    text_blocks = re.findall(r"<(?:text|tspan)[^>]+>", svg)
    assert text_blocks, "no <text>/<tspan> elements found"
    for block in text_blocks:
        for m in re.finditer(r'x="([\d.\-]+)"', block):
            v = float(m.group(1))
            assert 0.0 <= v <= float(CANVAS_W), (
                f"text x={v} outside [0, {CANVAS_W}] in: {block}"
            )
        for m in re.finditer(r'y="([\d.\-]+)"', block):
            v = float(m.group(1))
            assert 0.0 <= v <= float(CANVAS_H), (
                f"text y={v} outside [0, {CANVAS_H}] in: {block}"
            )
