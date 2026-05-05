"""Evidence Terrain — deterministic topographic SVG of source distribution.

Aggregates a per-country source-count map to seven World-Bank region buckets
via :mod:`src.region_buckets`, then renders each active bucket as an
isolated mountain on the right side of the canvas. A vertical legend on
the left lists every bucket; horizontal connector lines link each legend
row to its bucket's position on the terrain.

Algorithm — Python port of the JS mock at
``independent-wire-design-system/project/preview/component-evidence-
terrain.html`` (handoff hash Ab231lVDyYEjg_lYp32Yow), restructured per
the architect's rough visual:

1. **Per-region height field.** Each bucket samples its own Gaussian on a
   compact 90×90 grid centred on its anchor. Fields are NOT summed.
2. **Marching squares per region** at a level set scaled to the region's
   own peak. Ring count grows with ``sqrt(n)``.
3. **Polyline chaining** stitches the segments into continuous polylines.
4. **Painter's algorithm** depth-sort: regions render back-to-front by
   base-anchor screen-y. Closer mountains overlap farther ones.
5. **Oblique projection** ``(u, v, h) → (x, y)``:
       x = cx + u * scale
       y = cy − v * scale * tilt − h * vScale
6. **Left-edge legend** with seven rows ordered top-to-bottom by terrain
   ``y_base`` (so connectors are horizontal). Active rows render
   ``N | NAME`` on the left; zero rows render only the dim ``NAME`` and
   place a dim ``0`` at the bucket's terrain position. Connectors run
   horizontally at ``row_y = y_base`` from the legend column to the
   bucket's projected anchor x — pure horizontals never cross.
7. **Footer** carries a ``{N} TOTAL SOURCES`` caption centred under the
   terrain.

The terrain layer is clipped to the right ~75 % of the canvas so any
outer ring leakage from a high-source bump does not bleed into the
legend column.
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
CANVAS_H = 700                    # shrunk after TOTAL SOURCES moved into legend
LEGEND_RIGHT_EDGE = 270           # terrain clipped to x > LEGEND_RIGHT_EDGE
PROJ_CX = 700                     # terrain centre, shifted right of legend
PROJ_CY = 501.6                   # frozen so canvas-shrink doesn't move mountains
PROJ_SCALE = 290                  # tightened so terrain fits in the right 75%
PROJ_TILT = 0.55
PROJ_VSCALE = 250

# Per-region grid — compact bumps don't need a fine global grid.
GRID_W = 90
GRID_H = 90
SAMPLE_HALF_WINDOW = 0.9

# ---------------------------------------------------------------------------
# Per-region field shape. Bumps are isolated; fields are NOT summed.
# ---------------------------------------------------------------------------
SIGMA_BASE = 0.18
SIGMA_PER_SOURCE = 0.0035
SIGMA_CAP_N = 35
PEAK_EXPONENT = 0.78
PEAK_SCALE = 0.078

TINT_LEVEL_FACTOR = 0.55
TINT_OPACITY = 0.22

ISOLINE_MIN_LEVEL = 0.04
ISOLINE_GAMMA = 1.18
ISOLINE_LEVELS_MIN = 8
ISOLINE_LEVELS_MAX = 24

SHORE_LEVEL = 0.02

# ---------------------------------------------------------------------------
# Legend column (left side)
# ---------------------------------------------------------------------------
LEGEND_PAD_LEFT = 16
LEGEND_NUM_FS = 30                # active row big number
LEGEND_NUM_X_END = 76             # right-anchored end of the active number
LEGEND_RULE_X = 92                # vertical hairline rule
LEGEND_RULE_HEIGHT = 24
LEGEND_NAME_X = 106               # left-anchored start of the region name
LEGEND_NAME_FS = 14
LEGEND_NAME_LINE_HEIGHT = 16
LEGEND_NAME_LETTER_SPACING = "0.06em"
LEGEND_CONNECTOR_START_X = 244    # horizontal connector starts here (past the longest name)
TERMINUS_ZERO_FS = 22             # the "0" rendered at the bucket's terrain anchor
TERMINUS_DOT_RADIUS = 2.4         # filled summit dot for active buckets
ZERO_OPACITY = 0.35
ACTIVE_INK = "#0a0a0a"

# ---------------------------------------------------------------------------
# Footer / total-row
# ---------------------------------------------------------------------------
# Vertical step between the last region row (LAC) and the TOTAL SOURCES row.
# Matches the natural spacing between any two adjacent region rows (which is
# determined by the evenly-spaced anchor v values).
LEGEND_TOTAL_ROW_GAP = 40
# Hairline above the TOTAL SOURCES row that signals "this row is a sum,
# not an eighth region". Spans only the number + rule columns.
LEGEND_TOTAL_HAIRLINE_OPACITY = 0.5
LEGEND_TOTAL_HAIRLINE_WIDTH = 0.6
# Distance from the TOTAL SOURCES row to the unbucketed-countries footer
# line (only emitted when ``unbucketed > 0``).
LEGEND_UNBUCKETED_OFFSET = 30
LEGEND_UNBUCKETED_FS = 12


# ---------------------------------------------------------------------------
# Bucket anchor positions on the (u, v) world plane.
# v values are evenly spaced top-to-bottom so the legend rows (which align
# to each anchor's y_base) are also evenly spaced. u values keep a roughly
# geographic floor-plan: Americas left, Europe centre-back, Asia right,
# Africa centre-front.
# ---------------------------------------------------------------------------
ANCHORS: dict[str, tuple[float, float]] = {
    "europe_central_asia":      ( 0.05,  0.85),
    "east_asia_pacific":        ( 0.85,  0.60),
    "north_america":            (-0.85,  0.35),
    "middle_east_north_africa": ( 0.45,  0.10),
    "south_asia":               ( 0.92, -0.15),
    "sub_saharan_africa":       (-0.05, -0.40),
    "latin_america_caribbean":  (-0.78, -0.65),
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
    if n <= 0:
        return SIGMA_BASE, 0.0
    sigma = SIGMA_BASE + SIGMA_PER_SOURCE * min(n, SIGMA_CAP_N)
    peak = (n ** PEAK_EXPONENT) * PEAK_SCALE
    return sigma, peak


def _wrap_label(label: str) -> list[str]:
    """Wrap a region label to at most two lines.

    Splits on ``" & "`` when present (puts ``&`` on the first line).
    Otherwise, a label longer than 11 characters splits on its last
    space. Single-line labels are returned unchanged.
    """
    if " & " in label:
        a, b = label.split(" & ", 1)
        return [a + " &", b]
    if len(label) > 11 and " " in label:
        idx = label.rfind(" ")
        return [label[:idx], label[idx + 1:]]
    return [label]


def _esc(text: str) -> str:
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
                segments.append((
                    _project(pa[0], pa[1], level),
                    _project(pb[0], pb[1], level),
                ))
    return segments


def _chain_segs(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[list[tuple[float, float]]]:
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
    Empty input still produces a valid SVG with all seven legend rows
    visible (dimmed at zero, with a "0" placed at each bucket's terrain
    anchor position).
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
    # Plain-text marker for downstream regex searches.
    parts.append(
        f'<desc>{total} TOTAL SOURCES across {active_count} regions</desc>'
    )
    parts.append(
        '<defs>'
        '<radialGradient id="et-paper" cx="50%" cy="55%" r="75%">'
        '<stop offset="0%" stop-color="#fafaf7"/>'
        '<stop offset="100%" stop-color="#f1eee5"/>'
        '</radialGradient>'
        # Clip terrain so high-source bump rings can't bleed into the
        # legend column.
        f'<clipPath id="et-terrain-clip">'
        f'<rect x="{LEGEND_RIGHT_EDGE}" y="0" '
        f'width="{CANVAS_W - LEGEND_RIGHT_EDGE}" height="{CANVAS_H}"/>'
        f'</clipPath>'
        '</defs>'
    )
    parts.append(
        f'<rect x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}" '
        f'fill="url(#et-paper)"/>'
    )

    # Build per-region structures.
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

    # Painter's algorithm: render back-to-front by base-anchor screen-y.
    sorted_regions = sorted(regions, key=lambda r: r["base_anchor"][1])

    # Terrain group, clipped so rings never reach into the legend.
    parts.append(f'<g clip-path="url(#et-terrain-clip)">')
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

        # 2. Per-region topographic isolines (ring count grows with √n).
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
    parts.append('</g>')   # close terrain clip group

    # ---- Legend column on the left + horizontal connectors ---------------
    # Order rows by anchor v descending (back-to-front) so each legend row
    # sits at the same y as its bucket's projected base anchor — connectors
    # are pure horizontals and never cross.
    legend_order = sorted(ANCHORS.keys(), key=lambda k: -ANCHORS[k][1])

    for bucket_key in legend_order:
        meta = buckets_meta.get(bucket_key, {})
        # Labels come from the trusted region_buckets.json — uppercase + wrap
        # on " & " gives the design's preferred two-line display.
        label = meta.get("label", bucket_key).upper()
        name_lines = _wrap_label(label)
        au, av = ANCHORS[bucket_key]
        anchor_x, row_y = _project(au, av, 0.0)
        n = bucket_counts.get(bucket_key, 0)
        is_zero = n == 0

        # Connector — pure horizontal at row_y, from the legend right edge
        # to the bucket's projected anchor x.
        if is_zero:
            parts.append(
                f'<line x1="{LEGEND_CONNECTOR_START_X}" y1="{row_y:.1f}" '
                f'x2="{anchor_x:.1f}" y2="{row_y:.1f}" '
                f'stroke="{ACTIVE_INK}" stroke-width="0.5" '
                f'stroke-opacity="{ZERO_OPACITY}" stroke-dasharray="3 3"/>'
            )
        else:
            parts.append(
                f'<line x1="{LEGEND_CONNECTOR_START_X}" y1="{row_y:.1f}" '
                f'x2="{anchor_x:.1f}" y2="{row_y:.1f}" '
                f'stroke="{ACTIVE_INK}" stroke-width="0.7" '
                f'stroke-opacity="0.6"/>'
            )

        # Region name — left-aligned at NAME_X, possibly wrapped to two lines.
        name_h = len(name_lines) * LEGEND_NAME_LINE_HEIGHT
        first_baseline = row_y - name_h / 2 + 12
        text_opacity = ZERO_OPACITY if is_zero else 1.0
        for i, line in enumerate(name_lines):
            bl = first_baseline + i * LEGEND_NAME_LINE_HEIGHT
            parts.append(
                f'<text x="{LEGEND_NAME_X}" y="{bl:.1f}" '
                f'font-family="\'Space Mono\', monospace" '
                f'font-size="{LEGEND_NAME_FS}" font-weight="700" '
                f'letter-spacing="{LEGEND_NAME_LETTER_SPACING}" '
                f'text-anchor="start" fill="{ACTIVE_INK}" '
                f'opacity="{text_opacity:.2f}">{line}</text>'
            )

        # Same anatomy in every row: N (or "0") | rule | NAME. Zero rows
        # are dimmed but never lose the N column.
        num_baseline = row_y + LEGEND_NUM_FS * 0.34
        num_weight = "700" if is_zero else "800"
        num_opacity = ZERO_OPACITY if is_zero else 1.0
        rule_opacity = ZERO_OPACITY if is_zero else 0.55
        parts.append(
            f'<text x="{LEGEND_NUM_X_END}" y="{num_baseline:.1f}" '
            f'font-family="\'Space Grotesk\', sans-serif" '
            f'font-size="{LEGEND_NUM_FS}" font-weight="{num_weight}" '
            f'letter-spacing="-0.02em" text-anchor="end" '
            f'fill="{ACTIVE_INK}" opacity="{num_opacity:.2f}">{n}</text>'
        )
        parts.append(
            f'<line x1="{LEGEND_RULE_X}" x2="{LEGEND_RULE_X}" '
            f'y1="{row_y - LEGEND_RULE_HEIGHT / 2:.1f}" '
            f'y2="{row_y + LEGEND_RULE_HEIGHT / 2:.1f}" '
            f'stroke="{ACTIVE_INK}" stroke-width="0.8" '
            f'stroke-opacity="{rule_opacity:.2f}"/>'
        )

        if not is_zero:
            # Active terminus: small filled dot at the summit (vertically
            # aligned with the connector endpoint so the eye traces from
            # row to mountain peak).
            _, peak_h = _bucket_sigma_peak(n)
            summit_y = row_y - peak_h * PROJ_VSCALE
            parts.append(
                f'<circle cx="{anchor_x:.1f}" cy="{summit_y:.1f}" '
                f'r="{TERMINUS_DOT_RADIUS}" fill="{ACTIVE_INK}"/>'
            )

    # ---- 8th legend row: TOTAL SOURCES ----------------------------------
    # Compute the y of the last region row (LAC, the bottom-most row) and
    # place the totals row one row-step below it. A short hairline above
    # the totals row spans only the number + rule columns — the only
    # visual signal that this row is structurally a sum, not an eighth
    # region.
    last_region_row_y = max(
        _project(*ANCHORS[k], 0.0)[1] for k in legend_order
    )
    total_row_y = last_region_row_y + LEGEND_TOTAL_ROW_GAP
    hairline_y = last_region_row_y + LEGEND_TOTAL_ROW_GAP / 2

    parts.append(
        f'<line x1="{LEGEND_PAD_LEFT}" x2="{LEGEND_RULE_X}" '
        f'y1="{hairline_y:.1f}" y2="{hairline_y:.1f}" '
        f'stroke="{ACTIVE_INK}" '
        f'stroke-width="{LEGEND_TOTAL_HAIRLINE_WIDTH}" '
        f'stroke-opacity="{LEGEND_TOTAL_HAIRLINE_OPACITY}"/>'
    )

    # Number — same Space Grotesk display style as active region rows.
    total_num_baseline = total_row_y + LEGEND_NUM_FS * 0.34
    parts.append(
        f'<text x="{LEGEND_NUM_X_END}" y="{total_num_baseline:.1f}" '
        f'font-family="\'Space Grotesk\', sans-serif" '
        f'font-size="{LEGEND_NUM_FS}" font-weight="800" '
        f'letter-spacing="-0.02em" text-anchor="end" '
        f'fill="{ACTIVE_INK}">{total}</text>'
    )
    # Vertical hairline rule between number and label — same as region rows.
    parts.append(
        f'<line x1="{LEGEND_RULE_X}" x2="{LEGEND_RULE_X}" '
        f'y1="{total_row_y - LEGEND_RULE_HEIGHT / 2:.1f}" '
        f'y2="{total_row_y + LEGEND_RULE_HEIGHT / 2:.1f}" '
        f'stroke="{ACTIVE_INK}" stroke-width="0.8" stroke-opacity="0.55"/>'
    )
    # "TOTAL SOURCES" label — same Space Mono style as region names. No
    # connector follows; this row terminates at its label.
    total_label_baseline = total_row_y + LEGEND_NAME_FS * 0.4
    parts.append(
        f'<text x="{LEGEND_NAME_X}" y="{total_label_baseline:.1f}" '
        f'font-family="\'Space Mono\', monospace" '
        f'font-size="{LEGEND_NAME_FS}" font-weight="700" '
        f'letter-spacing="{LEGEND_NAME_LETTER_SPACING}" '
        f'text-anchor="start" fill="{ACTIVE_INK}">TOTAL SOURCES</text>'
    )

    if unbucketed > 0:
        # Small mono note shifted up to the new compact canvas; same form
        # as the prior footer line.
        parts.append(
            f'<text x="{LEGEND_NAME_X}" '
            f'y="{total_row_y + LEGEND_UNBUCKETED_OFFSET:.1f}" '
            f'text-anchor="start" '
            f'font-family="\'Space Mono\', monospace" '
            f'font-size="{LEGEND_UNBUCKETED_FS}" letter-spacing="0.04em" '
            f'fill="#0a0a0a" opacity="0.7">'
            f'{unbucketed} source{"s" if unbucketed != 1 else ""} '
            f'from countries not regionally classified.</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


__all__ = ["render_evidence_terrain"]
