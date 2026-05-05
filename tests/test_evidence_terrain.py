"""Tests for scripts/evidence_terrain.py — bucket-aggregated topographic SVG."""

from __future__ import annotations

import inspect
import re

import pytest

from scripts.evidence_terrain import (
    CANVAS_H,
    CANVAS_W,
    CARTOUCHES,
    FOOTER_TOTAL_Y,
    render_evidence_terrain,
)


def test_render_terrain_returns_svg_string():
    """Smoke: well-formed SVG envelope with non-trivial body length."""
    svg = render_evidence_terrain({"Germany": 5})
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    # Body should be substantial (washes + per-bucket isolines + cartouches).
    assert len(svg) > 5000
    # Cartouche label appears (wrapped on " & " for Europe & Central Asia).
    assert "EUROPE &" in svg
    assert "CENTRAL ASIA" in svg


def test_render_terrain_empty_input_still_renders():
    """Empty input produces a valid SVG with all seven cartouches dimmed."""
    svg = render_evidence_terrain({})
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    # Every region label appears (possibly wrapped) — check the first
    # token of each so wrap variants don't break the test.
    expected_first_tokens = [
        "EAST ASIA &",          # EAST ASIA & PACIFIC
        "EUROPE &",             # EUROPE & CENTRAL ASIA
        "LATIN AMERICA &",      # LATIN AMERICA & CARIBBEAN
        "MIDDLE EAST &",        # MIDDLE EAST & NORTH AFRICA
        "NORTH",                # NORTH AMERICA (wraps to NORTH / AMERICA)
        "SOUTH ASIA",           # single line, ≤11 chars
        "SUB-SAHARAN",          # SUB-SAHARAN AFRICA wraps
    ]
    for token in expected_first_tokens:
        assert token in svg, f"missing cartouche token {token!r}"
    # TOTAL SOURCES caption shows zero.
    m = re.search(r"TOTAL SOURCES[^<]*<tspan[^>]*>(\d+)</tspan>", svg)
    assert m is not None
    assert int(m.group(1)) == 0


def test_render_terrain_aggregates_to_buckets_correctly():
    """Counts in cartouches reflect the bucket aggregation."""
    svg = render_evidence_terrain(
        {"Germany": 3, "France": 2, "United States": 4, "Iran": 1}
    )

    def count_after_wrapped_label(first_line: str) -> int:
        idx = svg.find(first_line)
        assert idx != -1, f"label first line {first_line!r} not found"
        # The number text follows the label in source order; it's emitted
        # as ``<text ...>{N}</text>`` after the cartouche's last name line.
        m = re.search(r">(\d+)</text>", svg[idx:])
        assert m is not None, f"no count text after {first_line!r}"
        return int(m.group(1))

    assert count_after_wrapped_label("EUROPE &") == 5            # Germany 3 + France 2
    assert count_after_wrapped_label("NORTH") == 4               # US 4
    assert count_after_wrapped_label("MIDDLE EAST &") == 1       # Iran 1
    assert count_after_wrapped_label("EAST ASIA &") == 0
    assert count_after_wrapped_label("SOUTH ASIA") == 0
    assert count_after_wrapped_label("SUB-SAHARAN") == 0
    assert count_after_wrapped_label("LATIN AMERICA &") == 0


def test_render_terrain_unbucketed_country_appears_in_footer():
    """A country not in any region bucket is reported in the footer line
    and is excluded from any bucket count."""
    svg = render_evidence_terrain({"Atlantis": 3, "Germany": 2})
    assert "3 sources from countries not regionally classified" in svg
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
    svg = render_evidence_terrain(by)
    assert sum(by.values()) == 17
    m = re.search(r"TOTAL SOURCES[^<]*<tspan[^>]*>(\d+)</tspan>", svg)
    assert m is not None, "TOTAL SOURCES + tspan number not found"
    assert int(m.group(1)) == 17


def test_render_terrain_no_text_outside_viewbox():
    """Every <text>/<tspan> x and y attribute sits inside the viewBox.
    Cartouche text overflowing the canvas would render outside the visible
    SVG; this is the regression guard for that class of layout bug."""
    svg = render_evidence_terrain(
        {"Germany": 5, "Iran": 3, "United States": 4, "Brazil": 2}
    )
    # Match every x="N" and y="N" on text/tspan elements.
    text_blocks = re.findall(r"<(?:text|tspan)[^>]+>", svg)
    assert text_blocks, "no <text>/<tspan> elements found"
    max_x = 0.0
    max_y = 0.0
    for block in text_blocks:
        for attr, lo, hi, label in [("x", 0, CANVAS_W, "x"), ("y", 0, CANVAS_H, "y")]:
            for m in re.finditer(rf'{attr}="([\d.\-]+)"', block):
                val = float(m.group(1))
                assert lo <= val <= hi, (
                    f"text {label}={val} out of viewBox [{lo}, {hi}] "
                    f"in element: {block}"
                )
                if attr == "x":
                    max_x = max(max_x, val)
                else:
                    max_y = max(max_y, val)
    # Sanity: max observed values are well within bounds.
    assert max_x <= CANVAS_W
    assert max_y <= CANVAS_H


def test_render_terrain_cartouche_zones_dont_overlap():
    """The seven cartouche positions plus the FOOTER_TOTAL position (centre
    of the bottom caption) must sit in disjoint 200×60 zones.

    Static check on the constants — fires if a future edit moves a
    cartouche into a colliding zone."""
    zones: list[tuple[str, float, float]] = [
        (key, float(c["x"]), float(c["y"])) for key, c in CARTOUCHES.items()
    ]
    zones.append(("__footer_total__", float(CANVAS_W) * 0.5, float(FOOTER_TOTAL_Y)))

    box_w = 200.0
    box_h = 60.0
    half_w = box_w / 2
    half_h = box_h / 2

    def overlap(a: tuple[str, float, float], b: tuple[str, float, float]) -> bool:
        _, ax, ay = a
        _, bx, by = b
        return abs(ax - bx) < box_w and abs(ay - by) < box_h

    n = len(zones)
    for i in range(n):
        for j in range(i + 1, n):
            assert not overlap(zones[i], zones[j]), (
                f"cartouche zones overlap: {zones[i][0]} at "
                f"({zones[i][1]}, {zones[i][2]}) vs {zones[j][0]} at "
                f"({zones[j][1]}, {zones[j][2]}); each is {box_w}×{box_h}"
            )

    # Spot-check separation: closest pair on the right column.
    sa = next(z for z in zones if z[0] == "south_asia")
    mena = next(z for z in zones if z[0] == "middle_east_north_africa")
    assert abs(sa[2] - mena[2]) >= box_h


def test_render_terrain_signature_no_title_no_date():
    """Public surface accepts only ``by_country``; ``title`` and ``date``
    were removed in V2."""
    # Empty call works.
    svg = render_evidence_terrain(by_country={})
    assert svg.startswith("<svg")

    # Extra kwargs raise TypeError.
    with pytest.raises(TypeError):
        render_evidence_terrain(by_country={}, title="X")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        render_evidence_terrain(by_country={}, date="May 5, 2026")  # type: ignore[call-arg]

    # Signature has exactly one parameter.
    sig = inspect.signature(render_evidence_terrain)
    assert list(sig.parameters) == ["by_country"]
