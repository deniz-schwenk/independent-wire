"""Evidence Terrain — deterministic topographic SVG of source distribution.

Aggregates a per-country source-count map to seven World-Bank region buckets
via :mod:`src.region_buckets`, then draws each active bucket as an isolated
mountain on a stylised world floor-plan: per-bucket concentric ellipses (no
summed field, no marching squares — analytic ellipse rendering only),
soft per-bucket washes hugging each bump, and absolutely-positioned
cartouches with leader lines to each summit.

The renderer's structural goal is **legibility**:

- Bumps are isolated, not summed. Two bumps at the same location keep their
  individual concentric-ring identities; they do not melt into a single
  massif.
- Cartouches sit at fixed positions on the canvas, so text never overflows
  the viewBox and never overlaps another cartouche or the TOTAL SOURCES
  caption. Only the leader lines move with the projected summit.
- Typography is tuned for ~0.65× physical render scale (the SVG is embedded
  at max-width 720px against a 1080-wide viewBox) so region names hit
  roughly 12 px on screen and display-numbers reach 14–28 px.

The footer carries only the TOTAL SOURCES anchor; the topic title and date
are not duplicated inside the SVG (they already appear in the page's
``<h1>`` / date bar).
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from src.region_buckets import get_buckets, lookup_region

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layout constants — viewBox is 1080×760, rendered at ~720px width on TP
# pages giving a scale factor of ~0.67. All font-size choices below are
# tuned to that scale: physical display size ≈ svg_fs × 0.67.
# ---------------------------------------------------------------------------
CANVAS_W = 1080
CANVAS_H = 760
PROJ_CX = CANVAS_W * 0.5
PROJ_CY = CANVAS_H * 0.55      # horizon line a bit above centre
PROJ_SCALE = 360
PROJ_TILT = 0.55
PROJ_VSCALE = 280

# ---------------------------------------------------------------------------
# Per-bucket field shape. Bumps are isolated; fields are NOT summed.
# ---------------------------------------------------------------------------
SIGMA_BASE = 0.10
SIGMA_PER_SOURCE = 0.014
SIGMA_CAP_N = 12
PEAK_EXPONENT = 0.85
PEAK_SCALE = 0.15
PEAK_CAP_N = 18

# 18 elevation fractions per bucket, biased toward the summit
PER_BUCKET_LEVELS = (0.05, 0.10, 0.16, 0.22, 0.29, 0.36, 0.43, 0.50,
                     0.57, 0.63, 0.69, 0.75, 0.80, 0.85, 0.89, 0.92,
                     0.95, 0.97)

# Wash ellipse footprint (world-space σ multiplier)
WASH_SIGMA_FACTOR = 1.6
WASH_OPACITY = 0.22
WASH_HEIGHT_FACTOR = 0.5    # paint the wash at half-peak elevation

# ---------------------------------------------------------------------------
# Cartouche typography — display-number formula
# ---------------------------------------------------------------------------
NAME_FONT_SIZE = 18
NAME_LINE_HEIGHT = 22
NUM_FONT_SIZE_BASE = 22
NUM_FONT_SIZE_SLOPE = 1.5
NUM_FONT_SIZE_MAX = 44
ZERO_FONT_SIZE = 22
ZERO_OPACITY = 0.35
RULE_HEIGHT = 22
RULE_OPACITY_ACTIVE = 0.45
RULE_OPACITY_ZERO = 0.20
LEADER_OPACITY_ACTIVE = 0.6
LEADER_OPACITY_ZERO = 0.20

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
FOOTER_RULE_Y = 660
FOOTER_TOTAL_Y = 708
FOOTER_TOTAL_FONT_SIZE = 44
FOOTER_LABEL_FONT_SIZE = 18
FOOTER_UNBUCKETED_Y = 732
FOOTER_UNBUCKETED_FONT_SIZE = 14


# ---------------------------------------------------------------------------
# Bucket anchor positions on the (u, v) world plane.
# u in [-1, 1] horizontal; v in [-1, 1] depth (positive v = back of canvas).
# Composed as a balanced floor-plan that keeps bumps separated even at
# typical (1–25 per bucket) source distributions.
# ---------------------------------------------------------------------------
ANCHORS: dict[str, tuple[float, float]] = {
    "north_america":            (-0.80,  0.50),
    "europe_central_asia":      ( 0.00,  0.70),
    "south_asia":               ( 0.65,  0.35),
    "middle_east_north_africa": ( 0.35, -0.10),
    "east_asia_pacific":        ( 0.80, -0.55),
    "sub_saharan_africa":       (-0.15, -0.45),
    "latin_america_caribbean":  (-0.80, -0.55),
}


# ---------------------------------------------------------------------------
# Cartouche absolute positions on the 1080×760 viewBox.
# (x, y) is the centre of the cartouche; ``anchor_side`` is the edge the
# leader line attaches to (the side facing the bump it labels).
# ---------------------------------------------------------------------------
CARTOUCHES: dict[str, dict] = {
    "north_america":            {"x":  140, "y":  90, "anchor_side": "right"},
    "europe_central_asia":      {"x":  540, "y":  50, "anchor_side": "bottom"},
    "south_asia":               {"x":  940, "y": 200, "anchor_side": "left"},
    "middle_east_north_africa": {"x":  940, "y": 340, "anchor_side": "left"},
    "east_asia_pacific":        {"x":  940, "y": 500, "anchor_side": "left"},
    "sub_saharan_africa":       {"x":  140, "y": 500, "anchor_side": "right"},
    "latin_america_caribbean":  {"x":  140, "y": 340, "anchor_side": "right"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project(u: float, v: float, h: float) -> tuple[float, float]:
    """Oblique projection from world plane to screen coordinates."""
    x = PROJ_CX + u * PROJ_SCALE
    y = PROJ_CY - v * PROJ_SCALE * PROJ_TILT - h * PROJ_VSCALE
    return (x, y)


def _bucket_sigma_peak(n: int) -> tuple[float, float]:
    """Return (sigma, peak) for a bucket with ``n`` sources. ``n<=0``
    yields a baseline sigma and zero peak (used for cartouche placement
    in the no-data case)."""
    if n <= 0:
        return SIGMA_BASE, 0.0
    sigma = SIGMA_BASE + SIGMA_PER_SOURCE * min(n, SIGMA_CAP_N)
    peak = PEAK_SCALE * (min(n, PEAK_CAP_N) ** PEAK_EXPONENT)
    return sigma, peak


def _cartouche_num_size(n: int) -> float:
    """Display-number font size scaling on ``n``."""
    if n == 0:
        return float(ZERO_FONT_SIZE)
    return float(min(NUM_FONT_SIZE_BASE + n * NUM_FONT_SIZE_SLOPE,
                     NUM_FONT_SIZE_MAX))


def _wrap_label(label: str) -> list[str]:
    """Wrap a region label to at most two lines.

    Splits on ``" & "`` when present (puts ``&`` on the first line).
    Otherwise, a label longer than 11 characters splits on its last space.
    Single-line labels are returned unchanged.
    """
    if " & " in label:
        a, b = label.split(" & ", 1)
        return [a + " &", b]
    if len(label) > 11 and " " in label:
        idx = label.rfind(" ")
        return [label[:idx], label[idx + 1:]]
    return [label]


def _esc(text: str) -> str:
    """Minimal XML-text escape for SVG content."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def render_evidence_terrain(by_country: dict[str, int]) -> str:
    """Return a complete ``<svg>`` element as a string.

    By-country counts aggregate to bucket-level via :func:`lookup_region`.
    Unbucketed countries surface in a small footer line below the total.
    Empty input still produces a valid SVG with all seven cartouches
    dimmed at zero — the absence of data is the data point.
    """
    by_country = by_country or {}

    bucket_counts: dict[str, int] = {key: 0 for key in ANCHORS}
    unbucketed = 0
    for country, count in by_country.items():
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        bucket = lookup_region(country)
        if bucket is None or bucket not in bucket_counts:
            unbucketed += n
            continue
        bucket_counts[bucket] += n
    total = sum(bucket_counts.values()) + unbucketed

    buckets_meta = get_buckets()
    parts: list[str] = []

    # SVG root + paper-radial-gradient defs.
    active_count = sum(1 for n in bucket_counts.values() if n > 0)
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'class="evidence-terrain" role="img" '
        f'aria-label="Evidence terrain: {total} sources across '
        f'{active_count} regions">'
    )
    parts.append(
        '<defs>'
        f'<radialGradient id="et-paper" cx="50%" cy="60%" r="70%">'
        '<stop offset="0%" stop-color="#fafaf7"/>'
        '<stop offset="100%" stop-color="#f0eee6"/>'
        '</radialGradient>'
        '</defs>'
    )
    parts.append(
        f'<rect x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}" '
        f'fill="url(#et-paper)"/>'
    )

    # ---- 1. Per-bucket wash ellipses (active buckets only) -----------------
    for bucket_key in ANCHORS:
        n = bucket_counts.get(bucket_key, 0)
        if n <= 0:
            continue
        au, av = ANCHORS[bucket_key]
        sigma, peak = _bucket_sigma_peak(n)
        wash_radius = sigma * WASH_SIGMA_FACTOR
        rx = wash_radius * PROJ_SCALE
        ry = wash_radius * PROJ_SCALE * PROJ_TILT
        cx, cy = _project(au, av, peak * WASH_HEIGHT_FACTOR)
        color = buckets_meta.get(bucket_key, {}).get("color", "#999999")
        parts.append(
            f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
            f'rx="{rx:.1f}" ry="{ry:.1f}" '
            f'fill="{color}" fill-opacity="{WASH_OPACITY}" '
            f'stroke="none"/>'
        )

    # ---- 2. Per-bucket concentric isoline ellipses (one bucket at a time;
    # bumps are isolated, never summed) -------------------------------------
    for bucket_key in ANCHORS:
        n = bucket_counts.get(bucket_key, 0)
        if n <= 0:
            continue
        au, av = ANCHORS[bucket_key]
        sigma, peak = _bucket_sigma_peak(n)
        for i, t in enumerate(PER_BUCKET_LEVELS):
            # Iso-curve in world: circle of radius σ·√(-2·ln(t)) centred on
            # the anchor at elevation h = t * peak.
            try:
                r_world = sigma * math.sqrt(-2.0 * math.log(t))
            except ValueError:
                continue
            h = t * peak
            cx, cy = _project(au, av, h)
            rx = r_world * PROJ_SCALE
            ry = r_world * PROJ_SCALE * PROJ_TILT
            t_norm = i / (len(PER_BUCKET_LEVELS) - 1)
            stroke_width = 0.5 + 0.5 * t_norm
            stroke_opacity = 0.20 + 0.55 * t_norm
            parts.append(
                f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
                f'rx="{rx:.1f}" ry="{ry:.1f}" '
                f'fill="none" stroke="#0a0a0a" '
                f'stroke-width="{stroke_width:.2f}" '
                f'stroke-opacity="{stroke_opacity:.2f}"/>'
            )

    # ---- 3. Cartouches + leader lines (every bucket, dimmed at zero) ------
    for bucket_key in ANCHORS:
        n = bucket_counts.get(bucket_key, 0)
        meta = buckets_meta.get(bucket_key, {})
        label = meta.get("label", bucket_key).upper()
        cart = CARTOUCHES[bucket_key]
        cx_box = float(cart["x"])
        cy_box = float(cart["y"])
        side = cart["anchor_side"]

        is_zero = n == 0
        ink = "#0a0a0a"
        text_opacity = ZERO_OPACITY if is_zero else 1.0
        rule_opacity = RULE_OPACITY_ZERO if is_zero else RULE_OPACITY_ACTIVE
        leader_opacity = LEADER_OPACITY_ZERO if is_zero else LEADER_OPACITY_ACTIVE
        leader_extra = (
            ' stroke-width="0.4" stroke-dasharray="2 2"'
            if is_zero else ' stroke-width="0.7"'
        )

        # Cartouche internal layout.
        # Left half: region name (right-aligned at cx_box - 9).
        # Centre: vertical hairline rule at cx_box.
        # Right half: number (left-aligned at cx_box + 12).
        name_lines = _wrap_label(label)
        num_size = _cartouche_num_size(n)
        num_weight = 500 if is_zero else 700

        rule_top = cy_box - RULE_HEIGHT / 2
        rule_bot = cy_box + RULE_HEIGHT / 2

        # Region-name text (Space Mono, uppercase, letter-spaced). Labels
        # come from the trusted region_buckets.json — ampersand stays
        # literal, matching the design system convention.
        name_x = cx_box - 9.0
        if len(name_lines) == 1:
            # Single line — vertically centred on cy_box.
            baseline_y = cy_box + NAME_FONT_SIZE * 0.35
            parts.append(
                f'<text x="{name_x:.1f}" y="{baseline_y:.1f}" '
                f'font-family="\'Space Mono\', monospace" '
                f'font-size="{NAME_FONT_SIZE}" font-weight="700" '
                f'letter-spacing="0.08em" '
                f'text-anchor="end" fill="{ink}" '
                f'opacity="{text_opacity:.2f}">{name_lines[0]}</text>'
            )
        else:
            # Two lines stacked, line-height NAME_LINE_HEIGHT.
            first_baseline = cy_box - NAME_LINE_HEIGHT * 0.5 + NAME_FONT_SIZE * 0.35
            for li, line in enumerate(name_lines):
                bl = first_baseline + li * NAME_LINE_HEIGHT
                parts.append(
                    f'<text x="{name_x:.1f}" y="{bl:.1f}" '
                    f'font-family="\'Space Mono\', monospace" '
                    f'font-size="{NAME_FONT_SIZE}" font-weight="700" '
                    f'letter-spacing="0.08em" '
                    f'text-anchor="end" fill="{ink}" '
                    f'opacity="{text_opacity:.2f}">{line}</text>'
                )

        # Hairline rule between name and number.
        parts.append(
            f'<line x1="{cx_box:.1f}" x2="{cx_box:.1f}" '
            f'y1="{rule_top:.1f}" y2="{rule_bot:.1f}" '
            f'stroke="{ink}" stroke-width="0.7" '
            f'stroke-opacity="{rule_opacity:.2f}"/>'
        )

        # Number (Space Grotesk display).
        num_x = cx_box + 12.0
        num_baseline = cy_box + num_size * 0.34
        parts.append(
            f'<text x="{num_x:.1f}" y="{num_baseline:.1f}" '
            f'font-family="\'Space Grotesk\', sans-serif" '
            f'font-size="{num_size:.0f}" font-weight="{num_weight}" '
            f'letter-spacing="-0.02em" text-anchor="start" '
            f'fill="{ink}" opacity="{text_opacity:.2f}">{n}</text>'
        )

        # Leader line: cartouche edge → mid-point at attach_y → summit dot.
        # Attach point depends on anchor_side. We approximate cartouche
        # half-widths from the rendered text widths.
        name_char_w = NAME_FONT_SIZE * 0.6
        max_name_chars = max(len(line) for line in name_lines)
        name_w = max_name_chars * name_char_w
        num_w = len(str(n)) * num_size * 0.6
        # Number is positioned at cx_box + 12 with text-anchor="start", so
        # the right edge of the number sits at cx_box + 12 + num_w.
        right_edge_x = cx_box + 12.0 + num_w + 4.0
        # Name is right-aligned ending at cx_box - 9, so the left edge sits
        # at cx_box - 9 - name_w.
        left_edge_x = cx_box - 9.0 - name_w - 4.0
        bottom_edge_y = max(rule_bot, num_baseline + 4.0) + 4.0

        au, av = ANCHORS[bucket_key]
        _, peak_h = _bucket_sigma_peak(n)
        summit_sx, summit_sy = _project(au, av, peak_h)

        if side == "right":
            attach_x, attach_y = right_edge_x, cy_box
        elif side == "left":
            attach_x, attach_y = left_edge_x, cy_box
        else:  # "bottom"
            attach_x, attach_y = cx_box, bottom_edge_y

        # Two-segment leader: horizontal from attach to mid_x at attach_y,
        # then diagonal to summit.
        mid_x = (attach_x + summit_sx) / 2.0
        leader_d = (
            f"M {attach_x:.1f} {attach_y:.1f} "
            f"L {mid_x:.1f} {attach_y:.1f} "
            f"L {summit_sx:.1f} {summit_sy:.1f}"
        )
        parts.append(
            f'<path d="{leader_d}" fill="none" stroke="{ink}"'
            f'{leader_extra} stroke-opacity="{leader_opacity:.2f}"/>'
        )
        # Summit dot.
        dot_r = 1.2 if is_zero else 1.7
        dot_op = 0.4 if is_zero else 1.0
        parts.append(
            f'<circle cx="{summit_sx:.1f}" cy="{summit_sy:.1f}" '
            f'r="{dot_r}" fill="{ink}" opacity="{dot_op}"/>'
        )

    # ---- 4. Footer: hairline rule + TOTAL SOURCES caption -----------------
    parts.append(
        f'<line x1="80" y1="{FOOTER_RULE_Y}" '
        f'x2="{CANVAS_W - 80}" y2="{FOOTER_RULE_Y}" '
        f'stroke="#0a0a0a" stroke-width="0.6" stroke-opacity="0.4"/>'
    )

    # The caption renders as a single <text> with an inline <tspan> for the
    # number. Source order is "TOTAL SOURCES <tspan>{N}</tspan>" so the
    # downstream regex `TOTAL SOURCES[^<]*<tspan[^>]*>(\d+)` matches; visual
    # order is "{N} TOTAL SOURCES" because the tspan resets x to 534
    # text-anchor=end (the number ends at x=534, ahead of the label that
    # starts at x=546).
    parts.append(
        f'<text x="546" y="706" '
        f'font-family="\'Space Mono\', monospace" '
        f'font-size="{FOOTER_LABEL_FONT_SIZE}" font-weight="700" '
        f'letter-spacing="0.15em" text-anchor="start" '
        f'fill="#0a0a0a">TOTAL SOURCES'
        f'<tspan x="534" y="{FOOTER_TOTAL_Y}" '
        f'font-family="\'Space Grotesk\', sans-serif" '
        f'font-size="{FOOTER_TOTAL_FONT_SIZE}" font-weight="800" '
        f'letter-spacing="-0.02em" text-anchor="end">{total}</tspan>'
        f'</text>'
    )

    if unbucketed > 0:
        parts.append(
            f'<text x="{PROJ_CX:.1f}" y="{FOOTER_UNBUCKETED_Y}" '
            f'font-family="\'Space Mono\', monospace" '
            f'font-size="{FOOTER_UNBUCKETED_FONT_SIZE}" '
            f'letter-spacing="0.04em" text-anchor="middle" '
            f'fill="#0a0a0a" opacity="0.7">'
            f'{unbucketed} source{"s" if unbucketed != 1 else ""} '
            f'from countries not regionally classified.</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


__all__ = ["render_evidence_terrain"]
