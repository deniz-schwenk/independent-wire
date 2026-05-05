"""Evidence Terrain — deterministic topographic SVG of source distribution.

Aggregates a per-country source-count map to seven World-Bank region buckets
via :mod:`src.region_buckets`, then renders each active bucket as an
isolated mountain on a stylised world floor-plan: per-region marching-
squares contour rings (one bucket at a time so neighbours never coalesce
into a single massif), soft regional washes hugging each summit, and
relative-to-summit cartouches with leader lines + region-name + count.

Algorithm — Python port of the JS mock at
``independent-wire-design-system/project/preview/component-evidence-
terrain.html``:

1. **Per-region height field.** Each bucket samples its own Gaussian on a
   compact 90×90 grid centred on its anchor (sample window
   ``[a.u ± 0.9, a.v ± 0.9]``). Fields are NOT summed across buckets, so
   adjacent peaks always read as distinct mountains.
2. **Marching squares per region** at a level set scaled to the region's
   own peak. Ring count grows with ``sqrt(n)`` so taller mountains carry
   denser contours.
3. **Polyline chaining** stitches the marching-squares segments into
   continuous polylines.
4. **Painter's algorithm**: regions are rendered back-to-front sorted by
   base-anchor screen-y. Closer mountains visually overlap further ones.
5. **Oblique projection** from world (u, v, h) to screen (x, y):
       x = cx + u * scale
       y = cy − v * scale * tilt − h * vScale
6. **Cartouches** are always rendered for all seven buckets (dimmed when
   ``n == 0``). Each cartouche's ``dx, dy`` offset from its summit (or
   base anchor when zero) plus the leader-line geometry (vertical drop
   + short hook) follow the mock layout exactly.
7. **Footer** carries a TOTAL SOURCES anchor; topic title and date are
   not duplicated inside the SVG (they already appear in the page's
   ``<h1>`` / date bar).

Constants are tuned for a 1080×760 viewBox rendered at ~700 px width on
the TP page (scale factor ~0.65). Font sizes below are chosen so
physical render size stays ≥ 11 px on screen. If the canvas size or
bucket count changes, the anchors, cartouche offsets, sigma/peak curves,
and projection need to be re-derived.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from src.region_buckets import get_buckets, lookup_region

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canvas + projection
# ---------------------------------------------------------------------------
CANVAS_W = 1080
CANVAS_H = 760
PROJ_CX = CANVAS_W * 0.5
PROJ_CY = CANVAS_H * 0.66
PROJ_SCALE = 380
PROJ_TILT = 0.55
PROJ_VSCALE = 250

# Per-region grid — compact bumps don't need a fine global grid.
GRID_W = 90
GRID_H = 90
SAMPLE_HALF_WINDOW = 0.9    # sample u/v in [a.u-0.9, a.u+0.9] × ditto v

# ---------------------------------------------------------------------------
# Per-region field shape. Bumps are isolated; fields are NOT summed.
# ---------------------------------------------------------------------------
SIGMA_BASE = 0.18
SIGMA_PER_SOURCE = 0.0035
SIGMA_CAP_N = 35
PEAK_EXPONENT = 0.78
PEAK_SCALE = 0.078

# Tint / wash hugs the upper slope.
TINT_LEVEL_FACTOR = 0.55     # threshold = peak * 0.55
TINT_OPACITY = 0.22

# Topographic levels per region — count grows with √n; biased toward summit.
ISOLINE_MIN_LEVEL = 0.04
ISOLINE_GAMMA = 1.18
ISOLINE_LEVELS_MIN = 8
ISOLINE_LEVELS_MAX = 24

# Shore (outermost dashed contour).
SHORE_LEVEL = 0.02

# ---------------------------------------------------------------------------
# Cartouche typography (SVG-space sizes; physical size = svg_fs × ~0.65)
# ---------------------------------------------------------------------------
NAME_FONT_SIZE = 15
NAME_LINE_HEIGHT = 17
NAME_CHAR_WIDTH = 9.0
NUM_FONT_SIZE_BASE = 30
NUM_FONT_SIZE_SLOPE = 0.42
NUM_FONT_SIZE_BONUS_CAP = 14
ZERO_NUM_FONT_SIZE = 22
PAD_NAME = 14
PAD_NUM = 22

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
FOOTER_RULE_OFFSET = 56          # baseline rule at y = CANVAS_H − 56
FOOTER_CAPTION_OFFSET = 36       # caption baseline = rule_y + 36
FOOTER_TOTAL_FONT_SIZE = 38
FOOTER_LABEL_FONT_SIZE = 14


# ---------------------------------------------------------------------------
# Bucket anchor positions on the (u, v) world plane.
# u ∈ [-1, 1] horizontal; v ∈ [-1, 1] depth (positive = back of canvas).
# Composed as a balanced floor-plan that keeps bumps separated even at
# typical (1–35 per bucket) source distributions.
# ---------------------------------------------------------------------------
ANCHORS: dict[str, tuple[float, float]] = {
    "north_america":            (-0.85,  0.35),
    "europe_central_asia":      ( 0.05,  0.70),
    "east_asia_pacific":        ( 0.85,  0.55),
    "middle_east_north_africa": ( 0.45,  0.05),
    "south_asia":               ( 0.92, -0.10),
    "sub_saharan_africa":       (-0.05, -0.45),
    "latin_america_caribbean":  (-0.78, -0.55),
}


# ---------------------------------------------------------------------------
# Cartouche placement relative to each summit projection.
# ``side`` = which edge of the cartouche the leader-line hooks into.
# ---------------------------------------------------------------------------
CARTOUCHES: dict[str, dict] = {
    "north_america":            {"dx":    0, "dy": -54, "side": "right"},
    "europe_central_asia":      {"dx":    0, "dy": -54, "side": "right"},
    "east_asia_pacific":        {"dx":    0, "dy": -54, "side": "left"},
    "middle_east_north_africa": {"dx":   86, "dy": -22, "side": "right"},
    "south_asia":               {"dx": -100, "dy":  20, "side": "left"},
    "sub_saharan_africa":       {"dx":    0, "dy":  74, "side": "right"},
    "latin_america_caribbean":  {"dx":    0, "dy":  74, "side": "right"},
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
    yields a baseline sigma + zero peak."""
    if n <= 0:
        return SIGMA_BASE, 0.0
    sigma = SIGMA_BASE + SIGMA_PER_SOURCE * min(n, SIGMA_CAP_N)
    peak = (n ** PEAK_EXPONENT) * PEAK_SCALE
    return sigma, peak


def _wrap_label(label: str) -> list[str]:
    """Wrap a region label to at most two lines on " & "; otherwise keep
    as a single line."""
    if " & " in label:
        a, b = label.split(" & ", 1)
        return [a + " &", b]
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
# Per-region height field
# ---------------------------------------------------------------------------


def _region_field(
    anchor: tuple[float, float], n: int,
    u_min: float, u_max: float, v_min: float, v_max: float,
) -> tuple[list[list[float]], float, float]:
    """Sample a Gaussian centred on ``anchor`` over a 90×90 grid spanning
    [u_min, u_max] × [v_min, v_max]. Returns (field, peak, sigma).

    ``field[r][c]`` is row r (v-axis) and column c (u-axis); row 0 is
    the front of the canvas (v_min)."""
    sigma, peak = _bucket_sigma_peak(n)
    if peak == 0.0:
        return ([[0.0] * GRID_W for _ in range(GRID_H)], 0.0, sigma)
    au, av = anchor
    inv_two_sig2 = 1.0 / (2.0 * sigma * sigma)
    field = [[0.0] * GRID_W for _ in range(GRID_H)]
    du = (u_max - u_min) / (GRID_W - 1)
    dv = (v_max - v_min) / (GRID_H - 1)
    for r in range(GRID_H):
        v = v_min + r * dv
        dvv = v - av
        dvv2 = dvv * dvv
        row = field[r]
        for c in range(GRID_W):
            u = u_min + c * du
            duu = u - au
            row[c] = peak * math.exp(-(duu * duu + dvv2) * inv_two_sig2)
    return field, peak, sigma


# ---------------------------------------------------------------------------
# Marching squares + polyline chaining (per-region)
# ---------------------------------------------------------------------------


# 16-case isoline lookup. Bit positions: 1=v00 (front-left), 2=v10
# (front-right), 4=v11 (back-right), 8=v01 (back-left). Edges: B=front
# (v00↔v10), R=right (v10↔v11), T=back (v01↔v11), L=left (v00↔v01).
_MS_TABLE: dict[int, list[tuple[str, str]]] = {
    1:  [("L", "B")], 2: [("B", "R")], 3: [("L", "R")], 4: [("T", "R")],
    5:  [("L", "T"), ("B", "R")], 6: [("B", "T")], 7: [("L", "T")],
    8:  [("L", "T")], 9: [("T", "B")], 10: [("L", "B"), ("T", "R")],
    11: [("T", "R")], 12: [("L", "R")], 13: [("B", "R")], 14: [("L", "B")],
}


def _isolines_at(
    field: list[list[float]], level: float,
    u_min: float, u_max: float, v_min: float, v_max: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Run marching squares at ``level`` over a region-local field.
    Returns segments in screen coordinates (already projected at h=level)."""
    h = GRID_H
    w = GRID_W
    du = (u_max - u_min) / (w - 1)
    dv = (v_max - v_min) / (h - 1)
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def lerp(va: float, vb: float) -> float:
        denom = vb - va
        if denom == 0:
            return 0.5
        t = (level - va) / denom
        if t < 0:
            return 0.0
        if t > 1:
            return 1.0
        return t

    for r in range(h - 1):
        v0 = v_min + r * dv
        v1 = v0 + dv
        row = field[r]
        nrow = field[r + 1]
        for c in range(w - 1):
            v00 = row[c]
            v10 = row[c + 1]
            v01 = nrow[c]
            v11 = nrow[c + 1]
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
            u0 = u_min + c * du
            u1 = u0 + du

            def edge_uv(name: str) -> tuple[float, float]:
                if name == "B":
                    return (u0 + lerp(v00, v10) * du, v0)
                if name == "R":
                    return (u1, v0 + lerp(v10, v11) * dv)
                if name == "T":
                    return (u0 + lerp(v01, v11) * du, v1)
                return (u0, v0 + lerp(v00, v01) * dv)

            for ea, eb in entry:
                pa = edge_uv(ea)
                pb = edge_uv(eb)
                # Project at h = level (we are on an isoline of value ``level``).
                segments.append((
                    _project(pa[0], pa[1], level),
                    _project(pb[0], pb[1], level),
                ))
    return segments


def _chain_segs(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[list[tuple[float, float]]]:
    """Stitch segments into continuous polylines via endpoint matching."""
    if not segments:
        return []

    def key(p: tuple[float, float]) -> tuple[int, int]:
        return (round(p[0] * 100), round(p[1] * 100))

    used = [False] * len(segments)
    by_key: dict[tuple[int, int], list[int]] = {}
    for i, (a, b) in enumerate(segments):
        by_key.setdefault(key(a), []).append(i)
        by_key.setdefault(key(b), []).append(i)

    polylines: list[list[tuple[float, float]]] = []
    for i, (a, b) in enumerate(segments):
        if used[i]:
            continue
        used[i] = True
        line = [a, b]
        # Extend forward.
        while True:
            tail = line[-1]
            cands = by_key.get(key(tail), [])
            nxt: Optional[int] = None
            for j in cands:
                if used[j]:
                    continue
                sa, sb = segments[j]
                if key(sa) == key(tail):
                    nxt = j
                    line.append(sb)
                    break
                if key(sb) == key(tail):
                    nxt = j
                    line.append(sa)
                    break
            if nxt is None:
                break
            used[nxt] = True
        # Extend backward.
        while True:
            head = line[0]
            cands = by_key.get(key(head), [])
            nxt = None
            for j in cands:
                if used[j]:
                    continue
                sa, sb = segments[j]
                if key(sa) == key(head):
                    nxt = j
                    line.insert(0, sb)
                    break
                if key(sb) == key(head):
                    nxt = j
                    line.insert(0, sa)
                    break
            if nxt is None:
                break
            used[nxt] = True
        polylines.append(line)
    return polylines


def _path_d(points: list[tuple[float, float]], close: bool = False) -> str:
    """Build an SVG ``d`` attribute from a list of (x, y) points."""
    if not points:
        return ""
    out = [f"M{points[0][0]:.1f},{points[0][1]:.1f}"]
    for x, y in points[1:]:
        out.append(f"L{x:.1f},{y:.1f}")
    if close:
        out.append("Z")
    return " ".join(out)


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
    active_count = sum(1 for n in bucket_counts.values() if n > 0)

    buckets_meta = get_buckets()
    parts: list[str] = []

    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'class="evidence-terrain" role="img" '
        f'aria-label="Evidence terrain: {total} sources across '
        f'{active_count} regions">'
    )
    # The <desc> carries the literal "{N} TOTAL SOURCES" string so plain
    # text searches across the rendered HTML (including the published-TP
    # verification snippet using ``re.search(r'(\d+)\s*TOTAL SOURCES')``)
    # match without depending on the visible two-element caption layout.
    parts.append(
        f'<desc>{total} TOTAL SOURCES across {active_count} regions</desc>'
    )
    parts.append(
        '<defs>'
        '<radialGradient id="et-paper" cx="50%" cy="55%" r="75%">'
        '<stop offset="0%" stop-color="#fafaf7"/>'
        '<stop offset="100%" stop-color="#f1eee5"/>'
        '</radialGradient>'
        '</defs>'
    )
    parts.append(
        f'<rect x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}" '
        f'fill="url(#et-paper)"/>'
    )

    # Build per-region structures (field, peak, summit, base anchor projection).
    regions: list[dict] = []
    for bucket_key in ANCHORS:
        n = bucket_counts.get(bucket_key, 0)
        au, av = ANCHORS[bucket_key]
        u_min = au - SAMPLE_HALF_WINDOW
        u_max = au + SAMPLE_HALF_WINDOW
        v_min = av - SAMPLE_HALF_WINDOW
        v_max = av + SAMPLE_HALF_WINDOW
        if n > 0:
            field, peak, sigma = _region_field(
                (au, av), n, u_min, u_max, v_min, v_max,
            )
        else:
            field, peak, sigma = [], 0.0, SIGMA_BASE
        summit = _project(au, av, peak)
        base_anchor = _project(au, av, 0.0)
        regions.append({
            "key": bucket_key, "n": n, "anchor": (au, av),
            "field": field, "peak": peak, "sigma": sigma,
            "u_min": u_min, "u_max": u_max,
            "v_min": v_min, "v_max": v_max,
            "summit": summit, "base_anchor": base_anchor,
        })

    # Painter's algorithm: render back-to-front by base-anchor screen-y so
    # closer mountains overlap farther ones.
    sorted_regions = sorted(regions, key=lambda r: r["base_anchor"][1])

    for r in sorted_regions:
        if r["n"] <= 0:
            continue
        bucket_key = r["key"]
        n = r["n"]
        peak = r["peak"]
        field = r["field"]
        u_min, u_max = r["u_min"], r["u_max"]
        v_min, v_max = r["v_min"], r["v_max"]
        color = buckets_meta.get(bucket_key, {}).get("color", "#999999")

        # 1. Soft regional wash on the upper slope.
        tint_level = peak * TINT_LEVEL_FACTOR
        for line in _chain_segs(
            _isolines_at(field, tint_level, u_min, u_max, v_min, v_max)
        ):
            if len(line) < 4:
                continue
            d = _path_d(line, close=True)
            if not d:
                continue
            parts.append(
                f'<path d="{d}" fill="{color}" '
                f'fill-opacity="{TINT_OPACITY}" stroke="none"/>'
            )

        # 2. Per-region topographic isolines. Ring count grows with √n so
        # taller mountains carry denser contours.
        n_levels = max(
            ISOLINE_LEVELS_MIN,
            min(ISOLINE_LEVELS_MAX, round(8 + math.sqrt(n) * 2.4)),
        )
        for li in range(n_levels):
            t = li / max(n_levels - 1, 1)
            level = ISOLINE_MIN_LEVEL + (t ** ISOLINE_GAMMA) * (
                peak * 1.02 - ISOLINE_MIN_LEVEL
            )
            opacity = 0.20 + 0.55 * t
            sw = 0.7 if li < n_levels * 0.35 else 1.0
            for line in _chain_segs(
                _isolines_at(field, level, u_min, u_max, v_min, v_max)
            ):
                if len(line) < 2:
                    continue
                d = _path_d(line)
                if not d:
                    continue
                parts.append(
                    f'<path d="{d}" fill="none" stroke="#000" '
                    f'stroke-width="{sw}" stroke-opacity="{opacity:.2f}" '
                    f'stroke-linecap="round" stroke-linejoin="round"/>'
                )

        # 3. Shore — outermost dashed contour.
        for line in _chain_segs(
            _isolines_at(field, SHORE_LEVEL, u_min, u_max, v_min, v_max)
        ):
            if len(line) < 4:
                continue
            d = _path_d(line)
            if not d:
                continue
            parts.append(
                f'<path d="{d}" fill="none" stroke="#000" '
                f'stroke-width="0.45" stroke-opacity="0.25" '
                f'stroke-dasharray="2 3"/>'
            )

    # Cartouches: always rendered for all seven buckets (dimmed at zero).
    for r in regions:
        bucket_key = r["key"]
        n = r["n"]
        meta = buckets_meta.get(bucket_key, {})
        # Labels come from the trusted region_buckets.json — uppercase + wrap
        # on " & " gives the design's preferred two-line display where the
        # ampersand sits at the end of the first line.
        label = meta.get("label", bucket_key).upper()
        name_lines = _wrap_label(label)
        cart = CARTOUCHES[bucket_key]

        is_zero = n == 0
        ink = "#0a0a0a"
        ink_opacity = 0.42 if is_zero else 1.0

        # Where the leader meets the visualisation: the projected summit
        # for non-empty buckets, the base anchor for empty ones.
        sx, sy = r["summit"] if not is_zero else r["base_anchor"]

        # Cartouche placement.
        lx = sx + cart["dx"]
        ly = sy + cart["dy"]
        is_above = cart["dy"] < 0

        # Typography sizing.
        if is_zero:
            num_size = float(ZERO_NUM_FONT_SIZE)
            num_weight = 500
        else:
            num_size = float(NUM_FONT_SIZE_BASE
                              + min(NUM_FONT_SIZE_BONUS_CAP,
                                    n * NUM_FONT_SIZE_SLOPE))
            num_weight = 700
        max_chars = max(len(s) for s in name_lines)
        name_w = max_chars * NAME_CHAR_WIDTH
        num_w = len(str(n)) * (num_size * 0.58)
        total_w = name_w + num_w + PAD_NAME + PAD_NUM

        # Cartouche internal layout.
        if cart["side"] == "left":
            # [NAME] | [NUMBER] — leader hooks into right edge of cartouche.
            name_x = lx - total_w
            rule_x = name_x + name_w + PAD_NAME
            num_x = rule_x + PAD_NUM
        else:
            # [NUMBER] | [NAME] — leader hooks into left edge.
            num_x = lx
            rule_x = num_x + num_w + PAD_NUM
            name_x = rule_x + PAD_NAME

        cy0 = ly

        # Leader path: drop + hook.
        start_y = sy + (-3 if is_above else 3)
        hook_end_x = lx - 4 if cart["side"] == "left" else lx + 4
        leader_d = (
            f"M {sx:.1f} {start_y:.1f} "
            f"L {sx:.1f} {cy0:.1f} "
            f"L {hook_end_x:.1f} {cy0:.1f}"
        )
        parts.append(
            f'<path d="{leader_d}" fill="none" stroke="{ink}" '
            f'stroke-width="0.9" '
            f'stroke-opacity="{0.28 if is_zero else 0.6}"/>'
        )

        # Anchor dot at summit.
        dot_r = 1.6 if is_zero else 2.2
        dot_op = 0.4 if is_zero else 1.0
        parts.append(
            f'<circle cx="{sx:.1f}" cy="{start_y:.1f}" r="{dot_r}" '
            f'fill="{ink}" opacity="{dot_op}"/>'
        )

        # Vertical hairline rule between name and number.
        rule_h = max(20.0, num_size * 0.7)
        parts.append(
            f'<line x1="{rule_x:.1f}" x2="{rule_x:.1f}" '
            f'y1="{cy0 - rule_h / 2:.1f}" y2="{cy0 + rule_h / 2:.1f}" '
            f'stroke="{ink}" stroke-width="0.8" '
            f'stroke-opacity="{0.28 if is_zero else 0.5}"/>'
        )

        # Region name (Space Mono, possibly two lines).
        name_h = len(name_lines) * NAME_LINE_HEIGHT
        first_baseline = cy0 - name_h / 2 + 13
        for i, line in enumerate(name_lines):
            bl = first_baseline + i * NAME_LINE_HEIGHT
            parts.append(
                f'<text x="{name_x:.1f}" y="{bl:.1f}" '
                f'font-family="\'Space Mono\', monospace" '
                f'font-size="{NAME_FONT_SIZE}" font-weight="700" '
                f'letter-spacing="0.06em" '
                f'text-anchor="start" fill="{ink}" '
                f'opacity="{ink_opacity:.2f}">{line}</text>'
            )

        # Number (Space Grotesk display).
        parts.append(
            f'<text x="{num_x:.1f}" y="{cy0 + num_size * 0.34:.1f}" '
            f'font-family="\'Space Grotesk\', sans-serif" '
            f'font-size="{num_size:.0f}" font-weight="{num_weight}" '
            f'letter-spacing="-0.02em" text-anchor="start" '
            f'fill="{ink}" opacity="{ink_opacity:.2f}">{n}</text>'
        )

    # Footer: hairline rule + centred TOTAL SOURCES caption.
    base_y = CANVAS_H - FOOTER_RULE_OFFSET
    parts.append(
        f'<line x1="60" y1="{base_y}" x2="{CANVAS_W - 60}" y2="{base_y}" '
        f'stroke="#000" stroke-width="0.7" stroke-opacity="0.4"/>'
    )

    cap_x = CANVAS_W * 0.5
    cap_y = base_y + FOOTER_CAPTION_OFFSET

    # Big number, right-aligned at cap_x − 8 (number ends just left of centre).
    parts.append(
        f'<text x="{cap_x - 8:.1f}" y="{cap_y:.1f}" text-anchor="end" '
        f'font-family="\'Space Grotesk\', sans-serif" '
        f'font-weight="800" font-size="{FOOTER_TOTAL_FONT_SIZE}" '
        f'letter-spacing="-0.02em" fill="#000">{total}</text>'
    )
    # Label, left-aligned at cap_x + 8.
    parts.append(
        f'<text x="{cap_x + 8:.1f}" y="{cap_y - 4:.1f}" text-anchor="start" '
        f'font-family="\'Space Mono\', monospace" '
        f'font-size="{FOOTER_LABEL_FONT_SIZE}" font-weight="700" '
        f'letter-spacing="0.18em" fill="#000">TOTAL SOURCES</text>'
    )

    if unbucketed > 0:
        parts.append(
            f'<text x="{cap_x:.1f}" y="{cap_y + 22:.1f}" '
            f'text-anchor="middle" '
            f'font-family="\'Space Mono\', monospace" '
            f'font-size="13" letter-spacing="0.04em" '
            f'fill="#0a0a0a" opacity="0.7">'
            f'{unbucketed} source{"s" if unbucketed != 1 else ""} '
            f'from countries not regionally classified.</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


__all__ = ["render_evidence_terrain"]
