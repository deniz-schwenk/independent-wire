"""Evidence Terrain — deterministic topographic SVG of source distribution.

The renderer aggregates a per-country source-count map to seven World-Bank
region buckets via :mod:`src.region_buckets`, then draws each bucket as a
Gaussian summit on a stylised world floor-plan: hairline isolines for
elevation, soft regional washes for identity, leader lines and cartouches
for labels. Mountains where coverage concentrates, plains where it does not.

Algorithm (port of the JS mock in preview/component-evidence-terrain.html):

1. Gaussian summation field on a 2D grid. Each active bucket contributes a
   Gaussian centred at its anchor (u, v) with sigma scaling on n (source
   count) and peak height also scaling on n. The summed field drives the
   black isolines.
2. Marching squares on the field at chosen elevation levels yields isoline
   segments.
3. Segments are chained into continuous polylines via endpoint matching.
4. Oblique projection from world plane (u, v, h) to screen (x, y):
       x = cx + u * scale
       y = cy − v * scale * tilt − h * vScale
5. Layered SVG render: paper background → per-bucket wash (each bucket's
   own Gaussian at WASH_THRESHOLD_FACTOR * peak) → black isolines (summed
   field, 22 levels biased toward the summit) → dashed shore contour →
   leader lines + cartouches → bottom rule + caption.

The module-level constants are tuned for a 7-bucket layout on the canvas
dimensions below. If a future workstream changes the canvas size or the
bucket count, they need to be re-derived.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np

from src.region_buckets import get_buckets, lookup_region

logger = logging.getLogger(__name__)


# u/v world plane: u in [-1, 1] (left/right), v in [-1, 1] (front/back).
# v positive = back of canvas, v negative = front.
ANCHORS: dict[str, tuple[float, float]] = {
    "north_america":            (-0.85,  0.55),
    "europe_central_asia":      (-0.10,  0.75),
    "south_asia":               ( 0.55,  0.30),
    "middle_east_north_africa": ( 0.10,  0.00),
    "east_asia_pacific":        ( 0.85, -0.50),
    "sub_saharan_africa":       (-0.20, -0.50),
    "latin_america_caribbean":  (-0.85, -0.50),
}

# Cartouche placement relative to summit projection.
CARTOUCHES: dict[str, dict] = {
    "north_america":            {"dx": -34, "dy": -22, "side": "left"},
    "europe_central_asia":      {"dx":   0, "dy": -42, "side": "left"},
    "south_asia":               {"dx":  44, "dy": -16, "side": "right"},
    "middle_east_north_africa": {"dx":  46, "dy":   8, "side": "right"},
    "east_asia_pacific":        {"dx":  44, "dy":  50, "side": "right"},
    "sub_saharan_africa":       {"dx":   0, "dy":  60, "side": "left"},
    "latin_america_caribbean":  {"dx": -40, "dy":  50, "side": "left"},
}

SIGMA_BASE = 0.18
SIGMA_PER_SOURCE = 0.018
SIGMA_CAP_N = 12
PEAK_EXPONENT = 0.85
PEAK_SCALE = 0.15

CANVAS_W = 1080
CANVAS_H = 700
PROJ_CX = CANVAS_W * 0.5
PROJ_CY = CANVAS_H * 0.78
PROJ_SCALE = 360
PROJ_TILT = 0.55
PROJ_VSCALE = 320

GRID_W = 200
GRID_H = 140
FIELD_U_MIN, FIELD_U_MAX = -1.25, 1.25
FIELD_V_MIN, FIELD_V_MAX = -1.0, 1.15

ISOLINE_LEVELS = 22
ISOLINE_MIN = 0.04
ISOLINE_GAMMA = 1.15
SHORE_LEVEL = 0.015
WASH_THRESHOLD_FACTOR = 0.55

TITLE_MAX_LEN = 80


# ---------------------------------------------------------------------------
# Field computation
# ---------------------------------------------------------------------------


def _bucket_sigma_peak(n: int) -> tuple[float, float]:
    """Return (sigma, peak) for a bucket with ``n`` sources."""
    if n <= 0:
        return SIGMA_BASE, 0.0
    n_clamped = min(n, SIGMA_CAP_N)
    sigma = SIGMA_BASE + SIGMA_PER_SOURCE * n_clamped
    peak = PEAK_SCALE * (n_clamped ** PEAK_EXPONENT)
    return sigma, peak


def _grid_axes() -> tuple[np.ndarray, np.ndarray]:
    """Return (u, v) 1-D arrays defining the grid sampling positions."""
    u = np.linspace(FIELD_U_MIN, FIELD_U_MAX, GRID_W)
    v = np.linspace(FIELD_V_MIN, FIELD_V_MAX, GRID_H)
    return u, v


def _bucket_field(bucket_key: str, n: int) -> np.ndarray:
    """Return the Gaussian field this bucket alone contributes to the
    grid. Shape is (GRID_H, GRID_W)."""
    u_axis, v_axis = _grid_axes()
    au, av = ANCHORS[bucket_key]
    sigma, peak = _bucket_sigma_peak(n)
    if peak == 0.0:
        return np.zeros((GRID_H, GRID_W), dtype=np.float64)
    uu, vv = np.meshgrid(u_axis, v_axis)
    return peak * np.exp(-(((uu - au) ** 2 + (vv - av) ** 2) / (2.0 * sigma * sigma)))


def _summed_field(bucket_counts: dict[str, int]) -> np.ndarray:
    """Sum every active bucket's Gaussian into one field."""
    field = np.zeros((GRID_H, GRID_W), dtype=np.float64)
    for bucket_key, n in bucket_counts.items():
        if n <= 0 or bucket_key not in ANCHORS:
            continue
        field += _bucket_field(bucket_key, n)
    return field


# ---------------------------------------------------------------------------
# Marching squares + polyline chaining
# ---------------------------------------------------------------------------

# 16-case isoline lookup. Each case lists the cell-edge pairs that connect
# to form a segment for that corner-mask. Edges:
#   0 = bottom (between TL and TR? no — using the standard convention:)
# Convention used here, with corners labelled (TL=0, TR=1, BR=2, BL=3) by
# bit position, corners on grid cell with grid-row r and grid-column c:
#   TL = field[r, c]      -> bit 0
#   TR = field[r, c+1]    -> bit 1
#   BR = field[r+1, c+1]  -> bit 2
#   BL = field[r+1, c]    -> bit 3
# Edges are labelled 0..3 going clockwise from the top edge:
#   0 = top    (between TL and TR)
#   1 = right  (between TR and BR)
#   2 = bottom (between BR and BL)
#   3 = left   (between BL and TL)
_MS_TABLE: dict[int, list[tuple[int, int]]] = {
    0: [],
    1: [(0, 3)],
    2: [(0, 1)],
    3: [(1, 3)],
    4: [(1, 2)],
    5: [(0, 1), (2, 3)],   # ambiguous — pick a consistent split
    6: [(0, 2)],
    7: [(2, 3)],
    8: [(2, 3)],
    9: [(0, 2)],
    10: [(0, 3), (1, 2)],  # ambiguous
    11: [(1, 2)],
    12: [(1, 3)],
    13: [(0, 1)],
    14: [(0, 3)],
    15: [],
}


def _interp(a: float, b: float, t: float) -> float:
    """Linear interpolation between ``a`` and ``b`` at fraction ``t``."""
    return a + (b - a) * t


def _edge_point(
    edge: int, r: int, c: int, field: np.ndarray, level: float,
) -> tuple[float, float]:
    """Return the (col, row) sub-pixel coordinate where ``level`` cuts the
    given edge of cell (r, c). Coordinates are in grid space, fractional."""
    tl = field[r, c]
    tr = field[r, c + 1]
    br = field[r + 1, c + 1]
    bl = field[r + 1, c]
    if edge == 0:
        # top edge: TL -> TR, between (c, r) and (c+1, r)
        denom = tr - tl
        t = 0.5 if denom == 0 else (level - tl) / denom
        return (c + t, r)
    if edge == 1:
        # right edge: TR -> BR
        denom = br - tr
        t = 0.5 if denom == 0 else (level - tr) / denom
        return (c + 1, r + t)
    if edge == 2:
        # bottom edge: BL -> BR
        denom = br - bl
        t = 0.5 if denom == 0 else (level - bl) / denom
        return (c + t, r + 1)
    # edge == 3, left edge: TL -> BL
    denom = bl - tl
    t = 0.5 if denom == 0 else (level - tl) / denom
    return (c, r + t)


def _marching_squares(
    field: np.ndarray, level: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Extract isoline segments from the 2-D field at ``level``. Each
    segment is ((x1, y1), (x2, y2)) in grid coordinates."""
    h, w = field.shape
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for r in range(h - 1):
        for c in range(w - 1):
            tl = field[r, c]
            tr = field[r, c + 1]
            br = field[r + 1, c + 1]
            bl = field[r + 1, c]
            mask = 0
            if tl >= level:
                mask |= 1
            if tr >= level:
                mask |= 2
            if br >= level:
                mask |= 4
            if bl >= level:
                mask |= 8
            for edge_a, edge_b in _MS_TABLE[mask]:
                p1 = _edge_point(edge_a, r, c, field, level)
                p2 = _edge_point(edge_b, r, c, field, level)
                segments.append((p1, p2))
    return segments


def _grid_to_world(point: tuple[float, float]) -> tuple[float, float]:
    """Convert grid-space (col, row) to world-plane (u, v)."""
    col, row = point
    u = FIELD_U_MIN + (col / (GRID_W - 1)) * (FIELD_U_MAX - FIELD_U_MIN)
    v = FIELD_V_MIN + (row / (GRID_H - 1)) * (FIELD_V_MAX - FIELD_V_MIN)
    return (u, v)


def _project(u: float, v: float, h: float) -> tuple[float, float]:
    """Oblique projection from world plane to screen coordinates."""
    x = PROJ_CX + u * PROJ_SCALE
    y = PROJ_CY - v * PROJ_SCALE * PROJ_TILT - h * PROJ_VSCALE
    return (x, y)


def _project_with_field(point: tuple[float, float], field: np.ndarray) -> tuple[float, float]:
    """Project a grid-space point to screen coords using the field for h."""
    col, row = point
    # Bilinear-sample the field for h
    c0 = int(math.floor(col))
    r0 = int(math.floor(row))
    c1 = min(c0 + 1, GRID_W - 1)
    r1 = min(r0 + 1, GRID_H - 1)
    c0 = max(0, min(c0, GRID_W - 1))
    r0 = max(0, min(r0, GRID_H - 1))
    fc = col - c0
    fr = row - r0
    h = (
        field[r0, c0] * (1 - fc) * (1 - fr)
        + field[r0, c1] * fc * (1 - fr)
        + field[r1, c0] * (1 - fc) * fr
        + field[r1, c1] * fc * fr
    )
    u, v = _grid_to_world(point)
    return _project(u, v, float(h))


def _chain_segments(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    eps: float = 1e-6,
) -> list[list[tuple[float, float]]]:
    """Stitch isoline segments into continuous polylines via endpoint
    matching. Endpoints within ``eps`` are treated as identical."""
    # Bucket segments by quantised endpoints for O(N) chaining.
    def key(p: tuple[float, float]) -> tuple[int, int]:
        return (int(round(p[0] / eps)), int(round(p[1] / eps)))

    used = [False] * len(segments)
    by_key: dict[tuple[int, int], list[int]] = {}
    for i, (a, b) in enumerate(segments):
        by_key.setdefault(key(a), []).append(i)
        by_key.setdefault(key(b), []).append(i)

    polylines: list[list[tuple[float, float]]] = []
    for i in range(len(segments)):
        if used[i]:
            continue
        used[i] = True
        a, b = segments[i]
        chain = [a, b]
        # Walk forward from b
        while True:
            k = key(chain[-1])
            nxt: Optional[int] = None
            for j in by_key.get(k, []):
                if used[j]:
                    continue
                sa, sb = segments[j]
                if key(sa) == k:
                    nxt = j
                    chain.append(sb)
                    break
                if key(sb) == k:
                    nxt = j
                    chain.append(sa)
                    break
            if nxt is None:
                break
            used[nxt] = True
        # Walk backward from a
        while True:
            k = key(chain[0])
            nxt = None
            for j in by_key.get(k, []):
                if used[j]:
                    continue
                sa, sb = segments[j]
                if key(sa) == k:
                    nxt = j
                    chain.insert(0, sb)
                    break
                if key(sb) == k:
                    nxt = j
                    chain.insert(0, sa)
                    break
            if nxt is None:
                break
            used[nxt] = True
        polylines.append(chain)
    return polylines


# ---------------------------------------------------------------------------
# SVG emission helpers
# ---------------------------------------------------------------------------


def _path_d(points: list[tuple[float, float]], close: bool = False) -> str:
    """Build an SVG ``d`` attribute from a list of (x, y) points."""
    if not points:
        return ""
    parts = [f"M{points[0][0]:.2f},{points[0][1]:.2f}"]
    for x, y in points[1:]:
        parts.append(f"L{x:.2f},{y:.2f}")
    if close:
        parts.append("Z")
    return " ".join(parts)


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


def _truncate(text: str, n: int = TITLE_MAX_LEN) -> str:
    """Truncate to ``n`` chars + ellipsis if longer. The ellipsis is a
    single Unicode character so the result is at most n+1 characters."""
    if not text:
        return ""
    if len(text) <= n:
        return text
    return text[:n] + "…"


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def render_evidence_terrain(
    by_country: dict[str, int],
    title: str = "",
    date: str = "",
) -> str:
    """Return a complete ``<svg>`` element as a string.

    Inputs are aggregated to bucket-level via :func:`lookup_region`.
    Unbucketed countries are reported as a separate count in the footer.
    Empty or all-zero input still produces a valid SVG showing all seven
    cartouches at zero — the absence of data is the data point.
    """
    by_country = by_country or {}

    # 1. Aggregate to buckets, count unbucketed sources separately.
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

    # 2. Build the summed field used by isolines + shore.
    summed = _summed_field(bucket_counts)
    max_field = float(summed.max()) if summed.size else 0.0

    # 3. Black isoline levels — bias toward the summit (more lines near max).
    if max_field <= ISOLINE_MIN:
        iso_levels: list[float] = []
    else:
        iso_levels = [
            ISOLINE_MIN
            + (max_field - ISOLINE_MIN) * (((i + 1) / ISOLINE_LEVELS) ** (1 / ISOLINE_GAMMA))
            for i in range(ISOLINE_LEVELS)
        ]

    buckets_meta = get_buckets()
    parts: list[str] = []

    # 4. SVG root + defs.
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'class="evidence-terrain" role="img" '
        f'aria-label="Evidence terrain: {total} sources across '
        f'{sum(1 for n in bucket_counts.values() if n > 0)} regions">'
    )
    parts.append(
        '<defs>'
        f'<radialGradient id="et-paper" cx="50%" cy="50%" r="65%">'
        '<stop offset="0%" stop-color="#fdfcf8"/>'
        '<stop offset="100%" stop-color="#f0ece2"/>'
        '</radialGradient>'
        '</defs>'
    )

    # 5. Paper background.
    parts.append(
        f'<rect x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}" '
        f'fill="url(#et-paper)"/>'
    )

    # 6. Per-bucket colour wash (each bucket's own gaussian, threshold).
    for bucket_key, n in bucket_counts.items():
        if n <= 0:
            continue
        color = buckets_meta.get(bucket_key, {}).get("color", "#999999")
        bf = _bucket_field(bucket_key, n)
        peak = float(bf.max())
        if peak <= 0:
            continue
        threshold = peak * WASH_THRESHOLD_FACTOR
        wash_segs = _marching_squares(bf, threshold)
        chains = _chain_segments(wash_segs)
        for chain in chains:
            projected = [_project_with_field(p, summed) for p in chain]
            close = (
                len(projected) > 2
                and abs(chain[0][0] - chain[-1][0]) < 1e-3
                and abs(chain[0][1] - chain[-1][1]) < 1e-3
            )
            d = _path_d(projected, close=close)
            if not d:
                continue
            parts.append(
                f'<path d="{d}" fill="{color}" fill-opacity="0.13" '
                f'stroke="none"/>'
            )

    # 7. Black topographic isolines (summed field).
    for level in iso_levels:
        segs = _marching_squares(summed, level)
        chains = _chain_segments(segs)
        for chain in chains:
            projected = [_project_with_field(p, summed) for p in chain]
            d = _path_d(projected)
            if not d:
                continue
            parts.append(
                f'<path d="{d}" fill="none" stroke="#1a1a1a" '
                f'stroke-width="0.55" stroke-opacity="0.62"/>'
            )

    # 8. Dashed shore contour at the lowest level.
    if max_field > SHORE_LEVEL:
        shore_segs = _marching_squares(summed, SHORE_LEVEL)
        for chain in _chain_segments(shore_segs):
            projected = [_project_with_field(p, summed) for p in chain]
            d = _path_d(projected)
            if not d:
                continue
            parts.append(
                f'<path d="{d}" fill="none" stroke="#1a1a1a" '
                f'stroke-width="0.55" stroke-opacity="0.45" '
                f'stroke-dasharray="3 3"/>'
            )

    # 9. Leader lines + cartouches.
    for bucket_key in ANCHORS:
        n = bucket_counts.get(bucket_key, 0)
        meta = buckets_meta.get(bucket_key, {})
        label = meta.get("label", bucket_key).upper()
        cart = CARTOUCHES[bucket_key]
        au, av = ANCHORS[bucket_key]
        _, peak_h = _bucket_sigma_peak(n)
        sx, sy = _project(au, av, peak_h)
        cx_box = sx + cart["dx"]
        cy_box = sy + cart["dy"]
        # Cartouche dimensions sized to the label.
        box_w = max(108.0, 8.0 * len(label) + 24.0)
        box_h = 30.0
        side = cart["side"]
        if side == "left":
            hook_x = cx_box + box_w / 2
        else:
            hook_x = cx_box - box_w / 2
        hook_y = cy_box

        active = n > 0
        text_color = "#1a1a1a" if active else "#999999"
        leader_opacity = 0.55 if active else 0.22

        # Leader line from summit projection to cartouche hook.
        parts.append(
            f'<line x1="{sx:.2f}" y1="{sy:.2f}" '
            f'x2="{hook_x:.2f}" y2="{hook_y:.2f}" '
            f'stroke="#1a1a1a" stroke-width="0.6" '
            f'stroke-opacity="{leader_opacity:.2f}"/>'
        )
        # Cartouche rectangle (paper fill so isolines show through edge).
        rx = cx_box - box_w / 2
        ry = cy_box - box_h / 2
        parts.append(
            f'<rect x="{rx:.2f}" y="{ry:.2f}" '
            f'width="{box_w:.2f}" height="{box_h:.2f}" '
            f'fill="#fdfcf8" fill-opacity="0.92" '
            f'stroke="#1a1a1a" stroke-width="0.7" '
            f'stroke-opacity="{0.85 if active else 0.35}"/>'
        )
        # Region label (small caps style via uppercase + letter-spacing).
        # Labels come from the trusted region_buckets.json config, so the
        # ampersand stays literal — same convention as the mock SVG.
        parts.append(
            f'<text x="{cx_box:.2f}" y="{(cy_box - 2):.2f}" '
            f'font-family="\'Space Mono\', \'Courier New\', monospace" '
            f'font-size="9" font-weight="700" letter-spacing="0.08em" '
            f'text-anchor="middle" dominant-baseline="middle" '
            f'fill="{text_color}">{label}</text>'
        )
        # Source count below the label.
        parts.append(
            f'<text x="{cx_box:.2f}" y="{(cy_box + 9):.2f}" '
            f'font-family="\'Space Grotesk\', \'DM Sans\', system-ui, sans-serif" '
            f'font-size="11" font-weight="500" '
            f'text-anchor="middle" dominant-baseline="middle" '
            f'fill="{text_color}">{n} source{"s" if n != 1 else ""}</text>'
        )

    # 10. Bottom rule and caption.
    rule_y = CANVAS_H - 60
    parts.append(
        f'<line x1="60" y1="{rule_y}" x2="{CANVAS_W - 60}" y2="{rule_y}" '
        f'stroke="#1a1a1a" stroke-width="0.7" stroke-opacity="0.55"/>'
    )
    caption_parts = [_truncate(title) if title else ""]
    caption_parts.append(f"{total} source{'s' if total != 1 else ''}")
    if date:
        caption_parts.append(date)
    caption = " · ".join([p for p in caption_parts if p])
    parts.append(
        f'<text x="60" y="{rule_y + 22}" '
        f'font-family="\'Space Mono\', \'Courier New\', monospace" '
        f'font-size="11" font-weight="600" letter-spacing="0.06em" '
        f'fill="#1a1a1a">{_esc(caption)}</text>'
    )

    # Right-side TOTAL SOURCES anchor (mirrors the mock).
    parts.append(
        f'<text x="{CANVAS_W - 60}" y="{rule_y + 22}" '
        f'font-family="\'Space Mono\', \'Courier New\', monospace" '
        f'font-size="9" font-weight="700" letter-spacing="0.16em" '
        f'fill="#1a1a1a" text-anchor="end">'
        f'TOTAL SOURCES · <tspan font-size="13">{total}</tspan>'
        f'</text>'
    )

    # 11. Optional unbucketed footer.
    if unbucketed > 0:
        parts.append(
            f'<text x="60" y="{rule_y + 40}" '
            f'font-family="\'Space Mono\', \'Courier New\', monospace" '
            f'font-size="9" font-weight="500" letter-spacing="0.04em" '
            f'fill="#666666">'
            f'{unbucketed} source{"s" if unbucketed != 1 else ""} from '
            f'countries not regionally classified.'
            f'</text>'
        )

    parts.append('</svg>')
    return "\n".join(parts)


__all__ = ["render_evidence_terrain"]
