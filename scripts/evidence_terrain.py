"""Evidence Terrain — deterministic topographic SVG of source distribution.

Aggregates a per-country source-count map to seven World-Bank region buckets
via :mod:`src.region_buckets`, then draws each active bucket as a Gaussian
summit on a stylised world floor-plan: hairline isolines for elevation,
soft per-bucket washes hugging each summit, leader lines + cartouches per
region, dashed shore contour, bottom rule, and a neutral caption with the
topic title, source count, and date.

The algorithm is a Python port of the JS mock in the design bundle
(`independent-wire-design-system/project/preview/component-evidence-
terrain.html`):

1. **Gaussian summation field.** Each active bucket contributes a 2-D
   Gaussian on the (u, v) world plane, centred at its anchor with sigma
   scaling on n (source count) and peak height also scaling on n. The
   summed field drives the black isolines; per-bucket fields drive the
   colour washes.
2. **Marching squares** at chosen elevation levels yields isoline
   segments (16-case lookup, no library).
3. **Polyline chaining** stitches segments into continuous polylines via
   endpoint matching.
4. **Oblique projection** from (u, v, h) to screen (x, y):
       x = cx + u * scale
       y = cy − v * scale * tilt − h * vScale
5. **Layered render**: paper background → per-bucket wash (each bucket's
   own Gaussian at WASH_THRESHOLD_FACTOR * peak) → black topographic
   isolines (summed field, 22 levels biased toward the summit) → dashed
   shore contour at SHORE_LEVEL → leader lines + cartouches → bottom rule
   + centred TOTAL SOURCES anchor + truncated topic-title caption →
   optional unbucketed footer line.

Module-level constants are tuned for a 7-bucket layout on a 1080×760
canvas. If the bucket count changes or the canvas is resized, the
anchors, cartouche offsets, and sigma/peak curves need re-derivation.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np

from src.region_buckets import get_buckets, lookup_region

logger = logging.getLogger(__name__)


# Seven anchor positions on the (u, v) world plane. u in [-1, 1] (left/
# right), v in [-1, 1] (front/back; v positive = back of canvas).
# Compositional priority is visual balance and clear separation between
# bucket summits at typical source distributions (1–25 per bucket).
ANCHORS: dict[str, tuple[float, float]] = {
    "north_america":            (-0.85,  0.55),
    "europe_central_asia":      (-0.05,  0.75),
    "south_asia":               ( 0.55,  0.30),
    "middle_east_north_africa": ( 0.20,  0.05),
    "east_asia_pacific":        ( 0.85, -0.45),
    "sub_saharan_africa":       (-0.15, -0.55),
    "latin_america_caribbean":  (-0.85, -0.50),
}


# Cartouche placement relative to each summit projection. ``side`` decides
# whether the leader line hooks into the cartouche from the left or right.
CARTOUCHES: dict[str, dict] = {
    "north_america":            {"dx": -50, "dy": -28, "side": "left"},
    "europe_central_asia":      {"dx":   0, "dy": -46, "side": "left"},
    "south_asia":               {"dx":  50, "dy": -16, "side": "right"},
    "middle_east_north_africa": {"dx":  56, "dy":  10, "side": "right"},
    "east_asia_pacific":        {"dx":  50, "dy":  46, "side": "right"},
    "sub_saharan_africa":       {"dx":   0, "dy":  62, "side": "left"},
    "latin_america_caribbean":  {"dx": -52, "dy":  46, "side": "left"},
}


# Sigma + peak-height curves. The mock used 0.22 base; we tighten a touch
# because seven anchors sit closer together than the mock's six.
SIGMA_BASE = 0.20
SIGMA_PER_SOURCE = 0.018
SIGMA_CAP_N = 12
PEAK_EXPONENT = 0.85
PEAK_SCALE = 0.15

# Canvas + projection.
CANVAS_W = 1080
CANVAS_H = 760
PROJ_CX = CANVAS_W * 0.5
PROJ_CY = CANVAS_H * 0.70
PROJ_SCALE = 360
PROJ_TILT = 0.55
PROJ_VSCALE = 320

# Field grid.
GRID_W = 200
GRID_H = 140
FIELD_U_MIN, FIELD_U_MAX = -1.25, 1.25
FIELD_V_MIN, FIELD_V_MAX = -1.0, 1.15

# Isolines.
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
    """Return (sigma, peak) for a bucket with ``n`` sources. n<=0 yields
    a baseline sigma + zero peak (used by zero-source cartouche placement)."""
    if n <= 0:
        return SIGMA_BASE, 0.0
    n_clamped = min(n, SIGMA_CAP_N)
    sigma = SIGMA_BASE + SIGMA_PER_SOURCE * n_clamped
    peak = PEAK_SCALE * (n_clamped ** PEAK_EXPONENT)
    return sigma, peak


def _grid_axes() -> tuple[np.ndarray, np.ndarray]:
    """Return (u_axis, v_axis) 1-D arrays defining grid sampling positions.
    v_axis[0] = FIELD_V_MIN (front), v_axis[-1] = FIELD_V_MAX (back)."""
    u = np.linspace(FIELD_U_MIN, FIELD_U_MAX, GRID_W)
    v = np.linspace(FIELD_V_MIN, FIELD_V_MAX, GRID_H)
    return u, v


def _bucket_field(bucket_key: str, n: int) -> np.ndarray:
    """Per-bucket Gaussian on the grid. Shape (GRID_H, GRID_W). Row r maps
    to v_axis[r], column c to u_axis[c]."""
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

# 16-case isoline lookup (matching the mock convention).
# Cell corners — by bit position:
#   1 = v00 (col=c,   row=r,   front-left)
#   2 = v10 (col=c+1, row=r,   front-right)
#   4 = v11 (col=c+1, row=r+1, back-right)
#   8 = v01 (col=c,   row=r+1, back-left)
# Edges:
#   B (bottom/front) = between v00 and v10 at v=v0
#   R (right)        = between v10 and v11 at u=u1
#   T (top/back)     = between v01 and v11 at v=v1
#   L (left)         = between v00 and v01 at u=u0
_MS_TABLE: dict[int, list[tuple[str, str]]] = {
    1:  [("L", "B")],
    2:  [("B", "R")],
    3:  [("L", "R")],
    4:  [("T", "R")],
    5:  [("L", "T"), ("B", "R")],
    6:  [("B", "T")],
    7:  [("L", "T")],
    8:  [("L", "T")],
    9:  [("T", "B")],
    10: [("L", "B"), ("T", "R")],
    11: [("T", "R")],
    12: [("L", "R")],
    13: [("B", "R")],
    14: [("L", "B")],
}


def _interp_pos(va: float, vb: float, level: float) -> float:
    """Linear-interp position (in [0, 1]) where ``level`` crosses [va, vb]."""
    denom = vb - va
    if denom == 0:
        return 0.5
    t = (level - va) / denom
    if t < 0:
        return 0.0
    if t > 1:
        return 1.0
    return t


def _edge_uv(
    edge: str, u0: float, u1: float, v0: float, v1: float,
    v00: float, v10: float, v01: float, v11: float, level: float,
) -> tuple[float, float]:
    """Return the (u, v) world coord where ``level`` crosses the named edge."""
    if edge == "B":
        return (u0 + _interp_pos(v00, v10, level) * (u1 - u0), v0)
    if edge == "R":
        return (u1, v0 + _interp_pos(v10, v11, level) * (v1 - v0))
    if edge == "T":
        return (u0 + _interp_pos(v01, v11, level) * (u1 - u0), v1)
    # edge == "L"
    return (u0, v0 + _interp_pos(v00, v01, level) * (v1 - v0))


def _isolines_at(field: np.ndarray, level: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Marching squares at ``level``. Returns segments in world (u, v)
    coordinates. Cells where every corner is on the same side of ``level``
    are skipped (no contribution)."""
    h, w = field.shape  # (GRID_H, GRID_W)
    u_axis, v_axis = _grid_axes()
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for r in range(h - 1):
        v0 = float(v_axis[r])
        v1 = float(v_axis[r + 1])
        for c in range(w - 1):
            v00 = float(field[r, c])
            v10 = float(field[r, c + 1])
            v01 = float(field[r + 1, c])
            v11 = float(field[r + 1, c + 1])
            code = 0
            if v00 >= level:
                code |= 1
            if v10 >= level:
                code |= 2
            if v11 >= level:
                code |= 4
            if v01 >= level:
                code |= 8
            if code == 0 or code == 15:
                continue
            entry = _MS_TABLE.get(code)
            if not entry:
                continue
            u0 = float(u_axis[c])
            u1 = float(u_axis[c + 1])
            for ea, eb in entry:
                p1 = _edge_uv(ea, u0, u1, v0, v1, v00, v10, v01, v11, level)
                p2 = _edge_uv(eb, u0, u1, v0, v1, v00, v10, v01, v11, level)
                segments.append((p1, p2))
    return segments


def _project(u: float, v: float, h: float) -> tuple[float, float]:
    """Oblique projection from world plane to screen coordinates."""
    x = PROJ_CX + u * PROJ_SCALE
    y = PROJ_CY - v * PROJ_SCALE * PROJ_TILT - h * PROJ_VSCALE
    return (x, y)


def _chain(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    eps_decimals: int = 4,
) -> list[list[tuple[float, float]]]:
    """Stitch isoline segments into continuous polylines via endpoint
    matching. Endpoints whose rounded representations agree are treated
    as the same point."""
    if not segments:
        return []

    def key(p: tuple[float, float]) -> tuple[int, int]:
        return (round(p[0], eps_decimals).__hash__(), round(p[1], eps_decimals).__hash__())

    used = [False] * len(segments)
    by_key: dict[tuple, list[int]] = {}
    for i, (a, b) in enumerate(segments):
        by_key.setdefault(key(a), []).append(i)
        by_key.setdefault(key(b), []).append(i)

    polylines: list[list[tuple[float, float]]] = []
    for i, (a, b) in enumerate(segments):
        if used[i]:
            continue
        used[i] = True
        chain = [a, b]
        # Extend forward.
        while True:
            tail = chain[-1]
            cands = by_key.get(key(tail), [])
            nxt: Optional[int] = None
            for j in cands:
                if used[j]:
                    continue
                sa, sb = segments[j]
                if key(sa) == key(tail):
                    nxt = j
                    chain.append(sb)
                    break
                if key(sb) == key(tail):
                    nxt = j
                    chain.append(sa)
                    break
            if nxt is None:
                break
            used[nxt] = True
        # Extend backward.
        while True:
            head = chain[0]
            cands = by_key.get(key(head), [])
            nxt = None
            for j in cands:
                if used[j]:
                    continue
                sa, sb = segments[j]
                if key(sa) == key(head):
                    nxt = j
                    chain.insert(0, sb)
                    break
                if key(sb) == key(head):
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


def _project_polyline(polyline: list[tuple[float, float]], level: float) -> list[tuple[float, float]]:
    """Project every (u, v) in a polyline to screen coords using h=level
    (we are on an isoline)."""
    return [_project(u, v, level) for (u, v) in polyline]


def _path_d(points: list[tuple[float, float]], close: bool = False) -> str:
    """Build an SVG ``d`` attribute from a list of (x, y) points."""
    if not points:
        return ""
    parts = [f"M{points[0][0]:.1f},{points[0][1]:.1f}"]
    for x, y in points[1:]:
        parts.append(f"L{x:.1f},{y:.1f}")
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
    """Truncate to ``n`` chars + ellipsis if longer. Result is at most n+1
    Unicode characters."""
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
    cartouches dimmed at zero — the absence of data is the data point.
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

    summed = _summed_field(bucket_counts)
    max_field = float(summed.max()) if summed.size else 0.0

    # Iso-levels: gamma-biased toward the summit (more rings near peak).
    if max_field <= ISOLINE_MIN:
        iso_levels: list[float] = []
    else:
        max_peak_band = max_field * 1.05
        iso_levels = [
            ISOLINE_MIN
            + (((i + 1) / ISOLINE_LEVELS) ** ISOLINE_GAMMA)
            * (max_peak_band - ISOLINE_MIN)
            for i in range(ISOLINE_LEVELS)
        ]

    buckets_meta = get_buckets()
    parts: list[str] = []

    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'class="evidence-terrain" role="img" '
        f'aria-label="Evidence terrain: {total} sources across '
        f'{sum(1 for n in bucket_counts.values() if n > 0)} regions">'
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

    # Per-bucket colour wash (each bucket's own Gaussian, hugging the summit).
    for bucket_key, n in bucket_counts.items():
        if n <= 0:
            continue
        color = buckets_meta.get(bucket_key, {}).get("color", "#999999")
        bf = _bucket_field(bucket_key, n)
        peak = float(bf.max())
        if peak <= 0:
            continue
        threshold = max(peak * WASH_THRESHOLD_FACTOR, ISOLINE_MIN)
        wash_segs = _isolines_at(bf, threshold)
        for chain in _chain(wash_segs):
            if len(chain) < 4:
                continue
            projected = _project_polyline(chain, threshold)
            d = _path_d(projected, close=True)
            if not d:
                continue
            parts.append(
                f'<path d="{d}" fill="{color}" fill-opacity="0.22" '
                f'stroke="none"/>'
            )

    # Black topographic isolines (summed field).
    n_levels = len(iso_levels)
    for li, level in enumerate(iso_levels):
        opacity = 0.18 + 0.55 * (li / max(n_levels - 1, 1))
        sw = 0.6 if li < n_levels * 0.35 else 0.9
        for chain in _chain(_isolines_at(summed, level)):
            if len(chain) < 2:
                continue
            projected = _project_polyline(chain, level)
            d = _path_d(projected)
            if not d:
                continue
            parts.append(
                f'<path d="{d}" fill="none" stroke="#000" '
                f'stroke-width="{sw}" stroke-opacity="{opacity:.2f}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )

    # Dashed shore contour at the lowest level.
    if max_field > SHORE_LEVEL:
        for chain in _chain(_isolines_at(summed, SHORE_LEVEL)):
            if len(chain) < 4:
                continue
            projected = _project_polyline(chain, SHORE_LEVEL)
            d = _path_d(projected)
            if not d:
                continue
            parts.append(
                f'<path d="{d}" fill="none" stroke="#000" '
                f'stroke-width="0.5" stroke-opacity="0.25" '
                f'stroke-dasharray="2 3"/>'
            )

    # Cartouches: [NAME] | [NUMBER] (or reversed when side="right") with
    # leader line summit -> vertical drop -> short horizontal hook.
    for bucket_key in ANCHORS:
        n = bucket_counts.get(bucket_key, 0)
        meta = buckets_meta.get(bucket_key, {})
        label = meta.get("label", bucket_key).upper()
        cart = CARTOUCHES[bucket_key]
        au, av = ANCHORS[bucket_key]
        _, peak_h = _bucket_sigma_peak(n)
        if n > 0:
            sx, sy = _project(au, av, peak_h)
        else:
            sx, sy = _project(au, av, 0.0)
        lx = sx + cart["dx"]
        ly = sy + cart["dy"]
        is_above = cart["dy"] < 0
        is_zero = n == 0
        ink = "#0a0a0a"
        ink_opacity = 0.42 if is_zero else 1.0

        # Cartouche typography.
        num_size = 16 if is_zero else (22 + min(14, n * 1.6))
        num_weight = 500 if is_zero else 700
        # Approximate widths (no exact text metrics in pure SVG).
        name_char_w = 6.6
        name_w = len(label) * name_char_w
        num_w = len(str(n)) * (num_size * 0.58)
        pad_name = 10
        pad_num = 18

        if cart["side"] == "left":
            # [NAME] | [NUMBER] — leader hooks into cartouche right edge.
            name_x = lx - (name_w + num_w + pad_name + pad_num)
            rule_x = name_x + name_w + pad_name
            num_x = rule_x + pad_num
            hook_end_x = lx - 4
        else:
            # [NUMBER] | [NAME] — leader hooks into cartouche left edge.
            num_x = lx
            rule_x = num_x + num_w + pad_num
            name_x = rule_x + pad_name
            hook_end_x = lx + 4

        cy0 = ly
        start_y = sy + (-3 if is_above else 3)

        # Leader path: summit dot -> vertical drop to cartouche line ->
        # short horizontal hook in.
        leader_d = (
            f"M {sx:.1f} {start_y:.1f} "
            f"L {sx:.1f} {cy0:.1f} "
            f"L {hook_end_x:.1f} {cy0:.1f}"
        )
        parts.append(
            f'<path d="{leader_d}" fill="none" stroke="{ink}" '
            f'stroke-width="0.7" stroke-opacity="{0.30 if is_zero else 0.6}"/>'
        )
        parts.append(
            f'<circle cx="{sx:.1f}" cy="{start_y:.1f}" r="1.7" '
            f'fill="{ink}" opacity="{0.4 if is_zero else 1.0}"/>'
        )

        # Hairline rule between name and number.
        rule_h = max(16.0, num_size * 0.65)
        parts.append(
            f'<line x1="{rule_x:.1f}" x2="{rule_x:.1f}" '
            f'y1="{cy0 - rule_h / 2:.1f}" y2="{cy0 + rule_h / 2:.1f}" '
            f'stroke="{ink}" stroke-width="0.7" '
            f'stroke-opacity="{0.30 if is_zero else 0.45}"/>'
        )

        # Region name (Space Mono, uppercase, letter-spaced). Labels come
        # from the trusted region_buckets.json so the ampersand stays
        # literal — same convention as the mock SVG.
        name_baseline_y = cy0 + 3.5
        parts.append(
            f'<text x="{name_x:.1f}" y="{name_baseline_y:.1f}" '
            f'font-family="\'Space Mono\', monospace" font-size="10" '
            f'font-weight="700" letter-spacing="0.08em" '
            f'text-anchor="start" fill="{ink}" '
            f'opacity="{ink_opacity:.2f}">{label}</text>'
        )

        # Number (Space Grotesk display).
        parts.append(
            f'<text x="{num_x:.1f}" y="{(cy0 + num_size * 0.34):.1f}" '
            f'font-family="\'Space Grotesk\', sans-serif" '
            f'font-size="{num_size:.0f}" font-weight="{num_weight}" '
            f'letter-spacing="-0.02em" text-anchor="start" '
            f'fill="{ink}" opacity="{ink_opacity:.2f}">{n}</text>'
        )

    # Bottom rule + centred TOTAL SOURCES anchor + caption.
    base_y = CANVAS_H - 100
    parts.append(
        f'<line x1="40" y1="{base_y}" x2="{CANVAS_W - 40}" y2="{base_y}" '
        f'stroke="#000" stroke-width="0.6" stroke-opacity="0.4"/>'
    )

    # Big-number + label, centered. Using a single <text> with a <tspan>
    # for the number so the count sits directly after "TOTAL SOURCES" in
    # source order — a downstream regex can pull `TOTAL SOURCES …<tspan>{N}`.
    parts.append(
        f'<text x="{PROJ_CX:.1f}" y="{base_y + 32}" '
        f'text-anchor="middle" '
        f'font-family="\'Space Mono\', monospace" '
        f'font-size="11" font-weight="700" letter-spacing="0.15em" '
        f'fill="#000">TOTAL SOURCES · '
        f'<tspan font-family="\'Space Grotesk\', sans-serif" '
        f'font-size="32" font-weight="800" letter-spacing="-0.02em">'
        f'{total}</tspan></text>'
    )

    # Caption: {title} · {N} sources · {date} (truncated, mono, muted).
    caption_parts: list[str] = []
    if title:
        caption_parts.append(_truncate(title))
    caption_parts.append(f"{total} source{'s' if total != 1 else ''}")
    if date:
        caption_parts.append(date)
    caption = " · ".join(caption_parts)
    parts.append(
        f'<text x="{PROJ_CX:.1f}" y="{base_y + 60}" '
        f'text-anchor="middle" '
        f'font-family="\'Space Mono\', monospace" '
        f'font-size="11" letter-spacing="0.10em" '
        f'fill="#444">{_esc(caption)}</text>'
    )

    if unbucketed > 0:
        parts.append(
            f'<text x="{PROJ_CX:.1f}" y="{base_y + 80}" '
            f'text-anchor="middle" '
            f'font-family="\'Space Mono\', monospace" '
            f'font-size="9" letter-spacing="0.04em" '
            f'fill="#666">{unbucketed} source'
            f'{"s" if unbucketed != 1 else ""} from countries '
            f'not regionally classified.</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


__all__ = ["render_evidence_terrain"]
