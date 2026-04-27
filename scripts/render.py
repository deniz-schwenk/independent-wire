#!/usr/bin/env python3
"""Independent Wire — Render a Topic Package JSON to self-contained HTML."""

import html
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Radial source network — region config (matches approved React reference)
# ---------------------------------------------------------------------------
# Angles in degrees, 0=right, clockwise. Each region: (start, end, color, countries)
REGION_CONFIG: dict[str, dict] = {
    "Middle East & N. Africa": {"start": 330, "end": 30,  "color": "#8b5cf6",
        "countries": ["Iran", "Turkey", "Saudi Arabia", "United Arab Emirates", "Jordan", "Egypt", "Israel", "Qatar", "Iraq"]},
    "East Asia":               {"start": 30,  "end": 75,  "color": "#0891b2",
        "countries": ["China", "Japan", "South Korea", "Taiwan"]},
    "South & Central Asia":    {"start": 75,  "end": 120, "color": "#0d9488",
        "countries": ["India", "Pakistan", "Bangladesh", "Russia"]},
    "SE Asia & Oceania":       {"start": 120, "end": 165, "color": "#059669",
        "countries": ["Indonesia", "Philippines", "Thailand", "Australia", "Vietnam"]},
    "Sub-Saharan Africa":      {"start": 165, "end": 210, "color": "#d97706",
        "countries": ["Nigeria", "South Africa", "Kenya", "Ethiopia"]},
    "Americas":                {"start": 210, "end": 255, "color": "#3b82f6",
        "countries": ["United States", "Canada", "Mexico"]},
    "Latin America":           {"start": 255, "end": 295, "color": "#2563eb",
        "countries": ["Brazil", "Argentina", "Colombia", "Chile"]},
    "Europe":                  {"start": 295, "end": 330, "color": "#6366f1",
        "countries": ["United Kingdom", "Germany", "Spain", "France", "Italy", "Poland", "Ukraine", "Netherlands"]},
}

COUNTRY_DISPLAY: dict[str, str] = {
    "United States": "US", "United Kingdom": "UK", "United Arab Emirates": "UAE",
    "Saudi Arabia": "S. Arabia", "South Korea": "S. Korea", "South Africa": "S. Africa",
}

# ---------------------------------------------------------------------------
# Country name → ISO 3166-1 alpha-2 mapping
# ---------------------------------------------------------------------------
COUNTRY_TO_ISO = {
    "United States": "US", "United Kingdom": "GB", "Germany": "DE",
    "France": "FR", "Italy": "IT", "Spain": "ES", "Portugal": "PT",
    "Netherlands": "NL", "Belgium": "BE", "Switzerland": "CH",
    "Austria": "AT", "Poland": "PL", "Sweden": "SE", "Norway": "NO",
    "Denmark": "DK", "Finland": "FI", "Greece": "GR", "Ireland": "IE",
    "Czech Republic": "CZ", "Romania": "RO", "Hungary": "HU",
    "China": "CN", "Japan": "JP", "South Korea": "KR", "India": "IN",
    "Pakistan": "PK", "Bangladesh": "BD", "Indonesia": "ID",
    "Thailand": "TH", "Vietnam": "VN", "Philippines": "PH",
    "Malaysia": "MY", "Singapore": "SG", "Taiwan": "TW",
    "Russia": "RU", "Ukraine": "UA", "Kazakhstan": "KZ",
    "Iran": "IR", "Iraq": "IQ", "Turkey": "TR", "Israel": "IL",
    "Saudi Arabia": "SA", "United Arab Emirates": "AE", "Qatar": "QA",
    "Kuwait": "KW", "Oman": "OM", "Bahrain": "BH", "Yemen": "YE",
    "Jordan": "JO", "Lebanon": "LB", "Syria": "SY", "Palestine": "PS",
    "Egypt": "EG", "South Africa": "ZA", "Nigeria": "NG", "Kenya": "KE",
    "Ethiopia": "ET", "Ghana": "GH", "Morocco": "MA", "Algeria": "DZ",
    "Tunisia": "TN", "Libya": "LY", "Sudan": "SD",
    "Brazil": "BR", "Mexico": "MX", "Argentina": "AR", "Colombia": "CO",
    "Chile": "CL", "Peru": "PE", "Venezuela": "VE",
    "Canada": "CA", "Australia": "AU", "New Zealand": "NZ",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """HTML-escape text."""
    return html.escape(str(text)) if text else ""


def _contains_rtl(text: str) -> bool:
    """Return True if text contains RTL characters (Arabic/Farsi/Hebrew)."""
    return any(unicodedata.bidirectional(c) in ("R", "AL", "AN") for c in text)


def _detect_lang(text: str) -> str | None:
    """Detect script for a text span. Returns lang code or None.

    Scans the full text and uses a priority system:
    - Arabic/Farsi script chars → "fa"
    - Hiragana or Katakana present → "ja" (even if kanji also present)
    - CJK unified ideographs only (no kana) → "zh"
    - Cyrillic → "ru"
    """
    has_arabic = False
    has_cjk = False
    has_kana = False
    has_cyrillic = False

    for c in text:
        cp = ord(c)
        if 0x0600 <= cp <= 0x06FF or 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF:
            has_arabic = True
        elif 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:
            has_kana = True
        elif 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            has_cjk = True
        elif 0x0400 <= cp <= 0x04FF:
            has_cyrillic = True

    if has_arabic:
        return "fa"
    if has_kana:
        return "ja"
    if has_cjk:
        return "zh"
    if has_cyrillic:
        return "ru"
    return None


def _wrap_non_latin(text: str) -> str:
    """Wrap non-Latin quoted passages with appropriate lang/dir spans."""
    def _wrap_match(m: re.Match) -> str:
        quote_char = m.group(1) or m.group(3) or ""
        inner = m.group(2)
        lang = _detect_lang(inner)
        if not lang:
            return m.group(0)
        attrs = f'lang="{lang}"'
        if lang == "fa":
            attrs += ' dir="rtl"'
        close_quote = "'" if quote_char == "\u2018" else ("\u2019" if quote_char == "\u2018" else
                      "\u201d" if quote_char == "\u201c" else quote_char)
        return f'{quote_char}<span {attrs}>{_esc(inner)}</span>{m.group(3) or close_quote}'

    # Match quoted blocks that contain non-ASCII (likely non-Latin)
    result = re.sub(
        r"(['\"\u2018\u201c])([^'\"\u2019\u201d]+?)(['\"\u2019\u201d])",
        _wrap_match,
        text,
    )
    return result


def _resolve_source_refs(body_html: str) -> str:
    """Replace [src-NNN] with clickable superscript links."""
    def replace_ref(match: re.Match) -> str:
        num = int(match.group(1))
        return f'<a href="#src-{num:03d}" class="source-ref"><sup>[{num}]</sup></a>'
    return re.sub(r"\[src-(\d+)\]", replace_ref, body_html)


def _format_date(date_str: str) -> str:
    """Format YYYY-MM-DD to 'April 13, 2026'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%B %d, %Y").replace(" 0", " ")
    except (ValueError, TypeError):
        return date_str or ""


def _badge(text: str, color: str) -> str:
    """Return a styled inline badge."""
    return (
        f'<span class="badge" style="background:{color}15;color:{color};'
        f'border:1px solid {color}40">{_esc(text)}</span>'
    )


# Color maps
REPRESENTATION_COLORS = {
    "strong": "#0f766e", "moderate": "#ca8a04", "weak": "#9f1239",
    "dominant": "#0f766e", "substantial": "#ca8a04", "marginal": "#9f1239",
}
SIGNIFICANCE_COLORS = {"critical": "#9f1239", "notable": "#ca8a04", "minor": "#64748b"}
DIVERGENCE_COLORS = {"factual": "#9f1239", "framing": "#7c3aed", "omission": "#ca8a04", "emphasis": "#0369a1"}
SEVERITY_COLORS = {"low": "#0f766e", "moderate": "#ca8a04", "high": "#9f1239"}
RESOLUTION_LABELS = {"resolved": "Resolved", "partially_resolved": "Partially resolved", "unresolved": "Unresolved"}


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_css() -> str:
    return """\
:root {
  --color-text: #000000;
  --color-text-secondary: #444444;
  --color-text-subtle: #999999;
  --color-primary: #3b82f6;
  --color-bg: #ffffff;
  --color-bg-subtle: #f5f5f5;
  --color-border: #000000;
  --color-border-light: #e0e0e0;
  --color-strong: #0f766e;
  --color-moderate: #ca8a04;
  --color-weak: #9f1239;
  --color-factual: #9f1239;
  --color-framing: #7c3aed;
  --color-omission: #ca8a04;
  --color-emphasis: #0369a1;
  --font-mono: 'Space Mono', 'Courier New', monospace;
  --font-sans: 'Space Grotesk', 'DM Sans', system-ui, sans-serif;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  margin: 0; padding: 0;
  font-family: var(--font-sans);
  color: var(--color-text);
  background: var(--color-bg);
  line-height: 1.6;
}
.container { max-width: 740px; margin: 0 auto; padding: 2rem 1.5rem; }
h1 { font-family: var(--font-sans); font-size: 1.8rem; line-height: 1.25; margin: 0 0 0.5rem; font-weight: 800; letter-spacing: -0.02em; }
h2 {
  font-family: var(--font-sans); font-size: 1.25rem; font-weight: 700; margin: 2.5rem 0 1rem;
  padding-bottom: 0.5rem; border-bottom: 3px solid var(--color-border);
}
.subtitle {
  color: var(--color-text-secondary); font-family: var(--font-sans); font-size: 1.05rem;
  margin: 0 0 0.25rem; border-left: 3px solid #000; padding-left: 0.75rem;
}
.date { font-family: var(--font-mono); color: var(--color-text-subtle); font-size: 0.9rem; margin-bottom: 1.5rem; text-transform: uppercase; }

/* Metadata bar */
.meta-bar {
  display: flex; flex-wrap: wrap; padding: 0;
  border: 1px solid #000; margin-bottom: 2rem;
}
.meta-item {
  text-align: center; flex: 1; min-width: 100px; padding: 0.75rem 0.5rem;
  border-right: 1px solid #000;
}
.meta-item:last-child { border-right: none; }
.meta-number { font-family: var(--font-mono); font-size: 1.4rem; font-weight: 700; color: #000; display: block; }
.meta-label { font-family: var(--font-mono); font-size: 0.6rem; color: #666; text-transform: uppercase; letter-spacing: 0.1em; }

/* Back navigation */
.back-nav {
  margin-bottom: 1.5rem;
}
.back-nav a {
  font-family: var(--font-mono); font-size: 0.7rem; color: #999;
  text-decoration: none; letter-spacing: 0.1em; text-transform: uppercase;
}
.back-nav a:hover { color: #000; text-decoration: underline; }
.back-nav-bottom { margin-top: 2rem; margin-bottom: 0; }

/* Source network SVG */
.source-network { width: 100%; max-width: 700px; margin: 0.5rem auto 1rem; display: block; }
.source-node { cursor: pointer; }
.source-node .name-label {
  opacity: 0; transition: opacity 0.15s ease;
  font-family: var(--font-mono); font-size: 10px; fill: #000; font-weight: 700;
}
.source-node .conn-line { transition: opacity 0.15s ease; }
.source-node:hover .name-label { opacity: 1; }
.source-node:hover .conn-line { opacity: 0.4; stroke-width: 2; }
.source-node:hover circle { stroke-width: 2.5; }

/* Country badges */
.country-grid {
  display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 1rem 0; justify-content: center;
}
.country-badge {
  padding: 3px 10px; border-radius: 0; font-family: var(--font-mono); font-size: 12px; font-weight: 500;
}

/* Reader note */
.reader-note {
  border: 1px solid #000; border-left: 3px solid #000;
  background: var(--color-bg-subtle); padding: 1rem 1.25rem; margin-bottom: 2rem;
  border-radius: 0; font-family: var(--font-sans); font-size: 0.95rem; line-height: 1.65;
  color: var(--color-text-secondary);
}

/* Article body */
.article-body { font-family: var(--font-sans); font-size: 1.125rem; line-height: 1.7; }
.article-body p { margin: 0 0 1.25rem; }
.source-ref { color: var(--color-primary); text-decoration: none; }
.source-ref:hover { text-decoration: underline; }
.source-ref sup { font-size: 0.7em; }
.word-count { font-family: var(--font-mono); color: var(--color-text-subtle); font-size: 0.85rem; text-align: right; margin-top: 0.5rem; }

/* Badges */
.badge {
  display: inline-block; padding: 0.15rem 0.5rem; border-radius: 0;
  font-family: var(--font-mono); font-size: 0.7rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em; white-space: nowrap;
}

/* Stakeholder cards */
.card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.card {
  border: 1px solid #000; border-radius: 0; padding: 1rem 1.25rem;
  background: var(--color-bg);
}
.card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem; }
.card-actor { font-family: var(--font-sans); font-weight: 700; font-size: 1rem; }
.card-meta { font-family: var(--font-mono); font-size: 0.8rem; color: var(--color-text-subtle); margin-bottom: 0.5rem; }
.card-position { font-family: var(--font-sans); font-size: 0.9rem; line-height: 1.55; color: var(--color-text-secondary); }
.card-quote { font-style: italic; font-size: 0.88rem; color: var(--color-text-subtle); margin-top: 0.5rem; border-left: 2px solid #000; padding-left: 0.75rem; }

/* Missing voices */
.missing-voice {
  border: 1px solid #000; border-radius: 0; padding: 0.85rem 1.1rem;
  margin-bottom: 0.6rem;
}
.missing-voice-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem; }
.missing-voice-type { font-family: var(--font-sans); font-weight: 600; font-size: 0.95rem; }
.missing-voice-desc { font-family: var(--font-sans); font-size: 0.88rem; color: var(--color-text-secondary); line-height: 1.55; }

/* Divergences */
.divergence {
  border: 1px solid #000; border-radius: 0; padding: 0.85rem 1.1rem;
  margin-bottom: 0.6rem;
}
.divergence-header { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.35rem; }
.divergence-desc { font-family: var(--font-sans); font-size: 0.9rem; line-height: 1.55; margin-bottom: 0.35rem; }
.divergence-resolution { font-family: var(--font-sans); font-size: 0.82rem; color: var(--color-text-subtle); line-height: 1.5; }

/* Bias details collapse */
details summary {
  list-style: none;
}
details summary::-webkit-details-marker {
  display: none;
}
details summary::before {
  content: "+  ";
  font-size: 0.7rem;
  margin-right: 0.25rem;
}
details[open] summary::before {
  content: "\2212  ";
}

/* Bias findings */
.bias-finding {
  border-left: 3px solid #000; padding: 0.5rem 0 0.5rem 1rem;
  margin-bottom: 0.75rem;
}
.bias-excerpt { background: var(--color-bg-subtle); padding: 0.15rem 0.35rem; border-radius: 0; font-style: italic; }
.bias-explanation { font-family: var(--font-sans); font-size: 0.88rem; color: var(--color-text-secondary); margin-top: 0.25rem; }

/* Bar chart */
.bar-chart { margin: 1rem 0; }
.bar-row { display: flex; align-items: center; margin-bottom: 0.35rem; }
.bar-label { width: 30px; font-family: var(--font-mono); font-size: 0.8rem; font-weight: 600; color: var(--color-text-secondary); text-transform: uppercase; }
.bar-track { flex: 1; height: 20px; background: var(--color-bg-subtle); border-radius: 0; margin: 0 0.5rem; overflow: hidden; }
.bar-fill { height: 100%; background: #000; border-radius: 0; transition: width 0.3s; }
.bar-count { width: 24px; font-family: var(--font-mono); font-size: 0.8rem; color: var(--color-text-subtle); text-align: right; }

/* Coverage gaps */
.coverage-gap {
  font-family: var(--font-sans); font-size: 0.9rem; color: var(--color-text-secondary); line-height: 1.55;
  padding: 0.5rem 0; border-bottom: 1px solid var(--color-border-light);
}

/* Sources table */
.sources-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.sources-table th {
  font-family: var(--font-mono); text-align: left; padding: 0.5rem 0.75rem;
  border-bottom: 3px solid #000;
  font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--color-text-subtle);
}
.sources-table td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--color-border-light); vertical-align: top; }
.sources-table a { color: var(--color-primary); text-decoration: none; }
.sources-table a:hover { text-decoration: underline; }
.source-num { font-family: var(--font-mono); font-weight: 600; color: var(--color-text-subtle); }

/* Transparency trail */
.transparency { font-family: var(--font-mono); color: var(--color-text-subtle); font-size: 0.82rem; line-height: 1.6; }
.transparency h2 { font-family: var(--font-mono); color: var(--color-text-subtle); font-size: 1rem; }
.transparency dt { font-weight: 700; margin-top: 0.5rem; text-transform: uppercase; }
.transparency dd { margin: 0 0 0.5rem; padding-left: 0; }
.transparency ul { margin: 0.25rem 0; padding-left: 1.25rem; }

/* Footer */
footer {
  margin-top: 3rem;
  padding-top: 1.5rem;
  border-top: 3px solid #000;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: #666;
  line-height: 2;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  text-align: left;
}
footer a { color: #000; text-decoration: underline; }

/* Responsive */
@media (max-width: 768px) {
  .container { padding: 1rem; }
  h1 { font-size: 1.4rem; }
  .card-grid { grid-template-columns: 1fr; }
  .meta-bar { flex-wrap: wrap; }
  .meta-item { min-width: 70px; border-right: none; border-bottom: 1px solid #000; }
  .meta-item:last-child { border-bottom: none; }
  .meta-number { font-size: 1.2rem; }
  .sources-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .article-body { font-size: 1rem; }
}
"""


def build_header(tp: dict) -> str:
    article = tp.get("article", {})
    meta = tp.get("metadata", {})
    return (
        f'<h1>{_esc(article.get("headline", ""))}</h1>\n'
        f'<p class="subtitle">{_esc(article.get("subheadline", ""))}</p>\n'
        f'<p class="date">{_format_date(meta.get("date", ""))}</p>\n'
    )


def build_follow_up_ref(tp: dict) -> str:
    """Build follow-up reference block (only when metadata.follow_up exists)."""
    follow_up = tp.get("metadata", {}).get("follow_up")
    if not follow_up:
        return ""
    prev_headline = _esc(follow_up.get("previous_headline", ""))
    prev_date = follow_up.get("previous_date", "")
    prev_tp_id = follow_up.get("previous_tp_id", "")
    formatted_date = _format_date(prev_date) if prev_date else ""
    return (
        '<div class="follow-up-ref" style="font-family: \'Space Mono\', monospace; font-size: 0.85rem; '
        'color: #444; padding: 12px 16px; border-left: 3px solid #000; margin: 16px 0; '
        f'background: #f5f5f5;">\n'
        f'Follow-up to: &ldquo;{prev_headline}&rdquo; ({formatted_date})\n'
        f'<!-- FOLLOW_UP_LINK:{prev_tp_id} -->\n'
        '</div>\n'
    )


def build_meta_bar(tp: dict) -> str:
    sources_count = len(tp.get("sources", []))
    bias = tp.get("bias_analysis", {})
    lang_count = len(bias.get("source_balance", {}).get("by_language", {}))
    persp_count = len(tp.get("perspectives", []))
    div_count = len(tp.get("divergences", []))

    items = [
        (sources_count, "Sources"),
        (lang_count, "Languages"),
        (persp_count, "Stakeholders"),
        (div_count, "Divergences"),
    ]
    inner = "\n".join(
        f'<div class="meta-item"><span class="meta-number">{n}</span>'
        f'<span class="meta-label">{label}</span></div>'
        for n, label in items
    )
    return f'<div class="meta-bar">\n{inner}\n</div>\n'


def _render_source_network(sources_by_country: dict[str, int]) -> str:
    """Generate radial source network SVG matching the approved React reference.

    Deterministic layout: 8 fixed angular sectors, straight connection lines,
    flat-fill nodes with feDropShadow filter, segment arcs with tick marks.
    """
    import math

    CX, CY = 380, 380
    R_CENTER = 44
    R_NODE_INNER = 185
    R_NODE_OUTER = 235
    R_ARC = 280
    R_LABEL = 305
    W, H = 760, 760
    PADDING_DEG = 6  # degrees padding from sector edges

    # Resolve compound country names ("Israel/France" -> Israel, France)
    active: dict[str, int] = {}
    for name, count in sources_by_country.items():
        if "/" in name:
            for part in name.split("/"):
                part = part.strip()
                active[part] = active.get(part, 0) + count
        else:
            active[name] = active.get(name, 0) + count

    total_sources = sum(sources_by_country.values())

    def to_rad(deg: float) -> float:
        return deg * math.pi / 180

    def polar(angle_deg: float, radius: float) -> tuple[float, float]:
        """angle_deg: 0=right, clockwise (standard SVG/screen coords)."""
        rad = to_rad(angle_deg)
        return CX + radius * math.cos(rad), CY + radius * math.sin(rad)

    def normalize(start: int, end: int) -> tuple[float, float]:
        s, e = float(start), float(end)
        if e < s:
            e += 360
        return s, e

    def sector_positions(start: int, end: int, n: int) -> list[float]:
        """Evenly distribute n items within [start+pad, end-pad]."""
        s, e = normalize(start, end)
        span = e - s
        s_pad = s + PADDING_DEG
        e_pad = e - PADDING_DEG
        usable = e_pad - s_pad
        if n <= 0:
            return []
        if n == 1:
            return [s_pad + usable / 2]
        step = usable / (n - 1)
        return [s_pad + i * step for i in range(n)]

    def arc_path(start_deg: int, end_deg: int, radius: float) -> str:
        s, e = normalize(start_deg, end_deg)
        x1, y1 = polar(s, radius)
        x2, y2 = polar(e, radius)
        span = e - s
        large = 1 if span > 180 else 0
        return f"M{x1:.1f},{y1:.1f} A{radius},{radius} 0 {large} 1 {x2:.1f},{y2:.1f}"

    # Pre-compute node data per region
    NodeInfo = tuple  # (country, x, y, r, count)
    region_nodes: dict[str, list[NodeInfo]] = {}

    for rname, cfg in REGION_CONFIG.items():
        countries = cfg["countries"]
        start, end = cfg["start"], cfg["end"]
        active_in = [c for c in countries if c in active]
        if not active_in:
            region_nodes[rname] = []
            continue
        n = len(active_in)
        angles = sector_positions(start, end, n)
        nodes = []
        for i, (country, angle) in enumerate(zip(active_in, angles)):
            count = active[country]
            r = 16 if count == 1 else (21 if count == 2 else 26)
            # Alternate inner/outer radius for crowded sectors
            if n >= 2:
                radius = R_NODE_INNER if i % 2 == 0 else R_NODE_OUTER
            else:
                radius = (R_NODE_INNER + R_NODE_OUTER) / 2  # 210px
            nx, ny = polar(angle, radius)
            nodes.append((country, nx, ny, r, count))
        region_nodes[rname] = nodes

    # SVG start (no filter defs — brutalist: no shadows)
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-40 -40 {W + 80} {H + 80}"'
        f' class="source-network" role="img"'
        f' aria-label="Source network: {total_sources} sources from {len(active)} countries">',
    ]

    # --- 1. Segment arcs + tick marks ---
    for rname, cfg in REGION_CONFIG.items():
        start, end = cfg["start"], cfg["end"]
        # Arc
        d = arc_path(start, end, R_ARC)
        parts.append(
            f'<path d="{d}" fill="none" stroke="#e0e0e0" '
            f'stroke-width="0.75" opacity="0.6"/>'
        )
        # Tick mark at start boundary
        x1, y1 = polar(start, 265)
        x2, y2 = polar(start, 295)
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#e0e0e0" stroke-width="0.75" opacity="0.4"/>'
        )

    # --- 2-4. Country groups: connection line + node + count + name label ---
    for rname, cfg in REGION_CONFIG.items():
        color = cfg["color"]
        for country, nx, ny, r, count in region_nodes[rname]:
            display = COUNTRY_DISPLAY.get(country, country)
            font_size = 13 if r > 20 else 11

            # Connection line endpoints
            angle = math.atan2(ny - CY, nx - CX)
            sx = CX + R_CENTER * math.cos(angle)
            sy = CY + R_CENTER * math.sin(angle)
            ex = nx - r * math.cos(angle)
            ey = ny - r * math.sin(angle)

            parts.append(f'<g class="source-node">')
            # Connection line
            parts.append(
                f'<line class="conn-line" x1="{sx:.1f}" y1="{sy:.1f}" '
                f'x2="{ex:.1f}" y2="{ey:.1f}" '
                f'stroke="#000" stroke-width="1" opacity="0.12"/>'
            )
            # Node circle
            parts.append(
                f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="{r}" '
                f'fill="{color}" '
                f'stroke="#000" stroke-width="1.5">'
                f'<title>{_esc(display)} ({count} source{"s" if count != 1 else ""})</title>'
                f'</circle>'
            )
            # Count label
            parts.append(
                f'<text class="count-label" x="{nx:.1f}" y="{ny + 4:.1f}" '
                f'font-size="{font_size}" font-family="\'Space Mono\', \'Courier New\', monospace" fill="white" '
                f'font-weight="700" text-anchor="middle" pointer-events="none">'
                f'{count}</text>'
            )
            # Name label (hidden, shown on hover via CSS)
            parts.append(
                f'<text class="name-label" x="{nx:.1f}" y="{ny + r + 14:.1f}" '
                f'font-family="\'Space Mono\', \'Courier New\', monospace" text-anchor="middle" '
                f'font-size="10" font-weight="700" fill="#000">'
                f'{_esc(display)}</text>'
            )
            parts.append('</g>')

    # --- 5. Central node (brutalist: pure black, no shadow) ---
    parts.append(
        f'<circle cx="{CX}" cy="{CY}" r="{R_CENTER}" '
        f'fill="#000"/>'
    )
    # 6. Central labels
    parts.append(
        f'<text x="{CX}" y="{CY - 6}" font-size="22" '
        f'font-family="\'Space Mono\', \'Courier New\', monospace" fill="white" font-weight="700" '
        f'text-anchor="middle" dominant-baseline="middle">{total_sources}</text>'
    )
    parts.append(
        f'<text x="{CX}" y="{CY + 14}" font-size="9" '
        f'font-family="\'Space Mono\', \'Courier New\', monospace" fill="white" '
        f'letter-spacing="0.1em" text-anchor="middle">SOURCES</text>'
    )

    # --- 7. Region labels ---
    for rname, cfg in REGION_CONFIG.items():
        start, end = cfg["start"], cfg["end"]
        color = cfg["color"]
        s, e = normalize(start, end)
        mid = s + (e - s) / 2
        lx, ly = polar(mid, R_LABEL)

        has_sources = len(region_nodes[rname]) > 0
        fill = "#64748b" if has_sources else "#cbd5e1"

        # Text anchor based on horizontal position
        if lx > CX + 40:
            anchor = "start"
        elif lx < CX - 40:
            anchor = "end"
        else:
            anchor = "middle"

        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="8.5" '
            f'font-family="\'Space Mono\', \'Courier New\', monospace" fill="{fill}" font-weight="600" '
            f'letter-spacing="0.1em" text-anchor="{anchor}" '
            f'dominant-baseline="middle">{_esc(rname.upper())}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _country_region_color(country: str) -> str:
    """Find the region color for a country."""
    for cfg in REGION_CONFIG.values():
        if country in cfg["countries"]:
            return cfg["color"]
    return "#94a3b8"


def build_source_map(tp: dict) -> str:
    """Build radial source network SVG + country badge legend."""
    bias = tp.get("bias_analysis", {})
    by_country = bias.get("source_balance", {}).get("by_country", {})

    svg_html = _render_source_network(by_country)

    # Country badges sorted by count descending, colored by region
    sorted_countries = sorted(by_country.items(), key=lambda x: -x[1])
    active_badges = []
    for country, count in sorted_countries:
        color = _country_region_color(country)
        label = f"{country} ({count})" if count > 1 else country
        active_badges.append(
            f'<span class="country-badge" style="background:{color}12;color:{color};'
            f'border:1px solid {color}30" '
            f'title="{_esc(country)}: {count} source{"s" if count != 1 else ""}">'
            f'{_esc(label)}</span>'
        )

    badges_html = "\n".join(active_badges)
    return (
        f'<h2>Source Countries</h2>\n'
        f'{svg_html}\n'
        f'<div class="country-grid" style="margin-top:0.75rem">\n{badges_html}\n</div>\n'
    )


def build_reader_note(tp: dict) -> str:
    note = tp.get("bias_analysis", {}).get("reader_note", "")
    if not note:
        return ""
    return f'<div class="reader-note">{_esc(note)}</div>\n'


def build_article_body(tp: dict) -> str:
    article = tp.get("article", {})
    body = article.get("body", "")
    word_count = article.get("word_count", len(body.split()))

    # Split into paragraphs
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    parts = []
    for para in paragraphs:
        text = _esc(para)
        text = _resolve_source_refs(text)
        text = _wrap_non_latin_in_html(text)
        parts.append(f"<p>{text}</p>")

    body_html = "\n".join(parts)
    return (
        f'<div class="article-body">\n{body_html}\n</div>\n'
        f'<p class="word-count">{word_count:,} words</p>\n'
    )


def _wrap_non_latin_in_html(text: str) -> str:
    """Wrap non-Latin character runs with lang/dir spans in already-escaped HTML.

    Single-pass approach: finds contiguous runs of non-Latin characters (plus
    any interspersed spaces/punctuation that are surrounded by non-Latin chars)
    and wraps each run exactly once. Does not capture adjacent Latin text.
    """
    # Match runs of non-Latin characters, allowing spaces and basic punctuation
    # between them (e.g., multi-word Farsi/Chinese phrases), but not HTML tags
    # or entities like &quot;
    def _wrap_run(m: re.Match) -> str:
        span = m.group(0)
        decoded = html.unescape(span)
        lang = _detect_lang(decoded)
        if not lang:
            return span
        attrs = f'lang="{lang}"'
        if lang == "fa":
            attrs += ' dir="rtl"'
        return f'<span {attrs}>{span}</span>'

    # Pattern: one or more non-ASCII characters, optionally followed by
    # (spaces/punctuation + more non-ASCII characters). This keeps the match
    # tight to actual non-Latin text without spilling into adjacent English.
    # Excludes HTML tags/entities by not matching < or &.
    result = re.sub(
        r"[^\x00-\x7F](?:[^\x00-\x7F]|\s(?=[^\x00-\x7F]))*",
        _wrap_run,
        text,
    )

    return result


def build_perspectives(tp: dict) -> str:
    """Render Perspektiv V2 position_clusters. One cluster = one card,
    with representation badge, summary, and a flat list of quoted actors.
    """
    clusters = tp.get("perspectives", [])
    if not clusters:
        return ""
    cards = []
    for c in clusters:
        if not isinstance(c, dict):
            continue
        rep = c.get("representation", "marginal")
        rep_color = REPRESENTATION_COLORS.get(rep, "#64748b")
        rep_badge = _badge(rep, rep_color)
        label = c.get("position_label", "")
        summary = c.get("position_summary", "")

        actor_items: list[str] = []
        for a in c.get("actors", []) or []:
            if not isinstance(a, dict):
                continue
            name = _esc(a.get("name", ""))
            role = _esc(a.get("role", ""))
            quote = a.get("quote")
            quote_html = ""
            if quote and str(quote).strip().lower() not in ("null", "none", "n/a"):
                quote_html = (
                    f'<div class="card-quote">{_esc(str(quote))}</div>'
                )
            actor_items.append(
                f'<li><strong>{name}</strong> — {role}{quote_html}</li>'
            )

        actors_block = (
            f'<ul class="cluster-actors">{"".join(actor_items)}</ul>'
            if actor_items else ""
        )

        cards.append(
            f'<div class="card">\n'
            f'  <div class="card-header"><span class="card-actor">{_esc(label)}</span>{rep_badge}</div>\n'
            f'  <div class="card-position">{_esc(summary)}</div>\n'
            f'  {actors_block}\n'
            f'</div>\n'
        )
    return f'<h2>Perspectives &mdash; Position Clusters</h2>\n<div class="card-grid">\n{"".join(cards)}</div>\n'


def build_missing_voices(tp: dict) -> str:
    """Render Perspektiv V2 missing_positions as a simple bulleted list."""
    missing = (
        tp.get("bias_analysis", {})
          .get("perspectives", {})
          .get("missing_positions", [])
    )
    if not missing:
        return ""
    items = []
    for m in missing:
        if not isinstance(m, dict):
            continue
        mtype = _esc(m.get("type", ""))
        desc = _esc(m.get("description", ""))
        items.append(f'<li><strong>{mtype}</strong> — {desc}</li>')
    if not items:
        return ""
    return f'<h2>What\'s missing</h2>\n<ul class="missing-positions">{"".join(items)}</ul>'


def build_divergences(tp: dict) -> str:
    divs = tp.get("divergences", [])
    if not divs:
        return ""

    items = []
    for d in divs:
        dtype = d.get("type", "emphasis")
        dcolor = DIVERGENCE_COLORS.get(dtype, "#64748b")
        resolution = d.get("resolution", "unresolved")
        res_label = RESOLUTION_LABELS.get(resolution, resolution)

        desc = _esc(d.get("description", ""))
        desc = _resolve_source_refs(desc)

        note = _esc(d.get("resolution_note", ""))
        note_html = f'<div class="divergence-resolution"><strong>{_esc(res_label)}:</strong> {note}</div>' if note else ""

        items.append(
            f'<div class="divergence">\n'
            f'  <div class="divergence-header">{_badge(dtype, dcolor)}</div>\n'
            f'  <div class="divergence-desc">{desc}</div>\n'
            f'  {note_html}\n'
            f'</div>\n'
        )
    return f'<h2>Divergences</h2>\n{"".join(items)}'


def build_bias_card(tp: dict) -> str:
    bias = tp.get("bias_analysis", {})
    lang_bias = bias.get("language_bias", {})
    findings = lang_bias.get("findings", [])
    severity = lang_bias.get("severity", "low")
    by_language = bias.get("source_balance", {}).get("by_language", {})

    parts = []
    parts.append('<h2>Bias Analysis</h2>\n')

    # Summary line — always visible
    sev_color = SEVERITY_COLORS.get(severity, "#64748b")
    if findings:
        parts.append(
            f'<p style="font-family:var(--font-mono);font-size:0.85rem;'
            f'color:var(--color-text-secondary);">'
            f'{len(findings)} language bias finding{"s" if len(findings) != 1 else ""}'
            f' &middot; Severity: {_badge(severity, sev_color)}</p>\n'
        )
    else:
        parts.append(
            f'<p style="font-family:var(--font-mono);font-size:0.85rem;'
            f'color:var(--color-text-secondary);">'
            f'No language bias findings &middot; Severity: {_badge(severity, sev_color)}</p>\n'
        )

    # Build findings HTML
    findings_parts = []
    for f in findings:
        issue = f.get("issue", "")
        issue_color = {
            "evaluative_adjective": "#ca8a04",
            "intensifier": "#0369a1",
            "loaded_term": "#9f1239",
            "hedging": "#64748b",
        }.get(issue, "#64748b")
        findings_parts.append(
            f'<div class="bias-finding">\n'
            f'  <span class="bias-excerpt">{_esc(f.get("excerpt", ""))}</span> '
            f'{_badge(issue, issue_color)}\n'
            f'  <div class="bias-explanation">{_esc(f.get("explanation", ""))}</div>\n'
            f'</div>\n'
        )
    findings_html = "".join(findings_parts)

    # Build bar chart HTML
    bar_parts = []
    if by_language:
        max_count = max(by_language.values()) if by_language else 1
        bar_parts.append(
            '<h3 style="font-family:var(--font-sans);font-size:1rem;'
            'margin-top:1.5rem">Source Balance by Language</h3>\n'
        )
        bar_parts.append('<div class="bar-chart">\n')
        for lang_code, count in sorted(by_language.items(), key=lambda x: -x[1]):
            pct = (count / max_count) * 100
            bar_parts.append(
                f'<div class="bar-row">'
                f'<span class="bar-label">{_esc(lang_code)}</span>'
                f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%"></div></div>'
                f'<span class="bar-count">{count}</span>'
                f'</div>\n'
            )
        bar_parts.append('</div>\n')
    bar_html = "".join(bar_parts)

    # Collapsible details — only if there's content to collapse
    if findings_html or bar_html:
        parts.append(
            f'<details style="margin-top:0.75rem">\n'
            f'<summary style="font-family:var(--font-mono);font-size:0.8rem;'
            f'color:var(--color-text-subtle);cursor:pointer;letter-spacing:0.05em;'
            f'text-transform:uppercase;padding:0.5rem 0">'
            f'Show detailed findings</summary>\n'
            f'<div style="margin-top:0.5rem">\n'
            f'{findings_html}'
            f'{bar_html}'
            f'</div>\n'
            f'</details>\n'
        )

    return "".join(parts)


def build_coverage_gaps(tp: dict) -> str:
    gaps = tp.get("bias_analysis", {}).get("coverage_gaps", [])
    if not gaps:
        return ""
    items = "\n".join(f'<div class="coverage-gap">{_esc(g)}</div>' for g in gaps)
    return f'<h2>Coverage Gaps</h2>\n{items}\n'


def build_sources_table(tp: dict) -> str:
    sources = tp.get("sources", [])
    if not sources:
        return ""

    rows = []
    for s in sources:
        sid = s.get("id", "")
        num = sid.replace("src-", "").lstrip("0") or "0"
        title = s.get("title", "")
        url = s.get("url", "")
        title_html = f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(title)}</a>' if url else _esc(title)
        rows.append(
            f'<tr id="{_esc(sid)}">'
            f'<td class="source-num">{num}</td>'
            f'<td>{_esc(s.get("outlet", ""))}</td>'
            f'<td>{title_html}</td>'
            f'<td>{_esc(s.get("language", ""))}</td>'
            f'<td>{_esc(s.get("country", ""))}</td>'
            f'</tr>'
        )

    return (
        f'<h2>Sources</h2>\n'
        f'<div class="sources-table-wrap">\n'
        f'<table class="sources-table">\n'
        f'<thead><tr><th>#</th><th>Outlet</th><th>Title</th><th>Lang</th><th>Country</th></tr></thead>\n'
        f'<tbody>\n{"".join(rows)}\n</tbody>\n'
        f'</table>\n</div>\n'
    )


def build_transparency(tp: dict) -> str:
    t = tp.get("transparency", {})
    if not t:
        return ""

    parts = ['<div class="transparency">\n<h2>Transparency Trail</h2>\n<dl>\n']

    if t.get("selection_reason"):
        parts.append(f'<dt>Selection Reason</dt><dd>{_esc(t["selection_reason"])}</dd>\n')

    corrections = t.get("qa_proposed_corrections", [])
    if corrections:
        items = "\n".join(f"<li>{_esc(c)}</li>" for c in corrections)
        parts.append(f'<dt>QA Proposed Corrections</dt><dd><ul>{items}</ul></dd>\n')

    run = t.get("pipeline_run", {})
    if run:
        parts.append(
            f'<dt>Pipeline Run</dt><dd>{_esc(run.get("run_id", ""))} &middot; {_esc(run.get("date", ""))}</dd>\n'
        )

    parts.append('</dl>\n</div>\n')
    return "".join(parts)


def build_glossary() -> str:
    """Build a static tag reference glossary. Same content for every TP."""
    def _gb(tag: str, color: str) -> str:
        return (
            f'<span class="badge" style="background:{color}15;color:{color};'
            f'border:1px solid {color}40">{tag}</span>'
        )

    return (
        '<details class="glossary" style="margin-top: 2rem; border-top: 3px solid #000; '
        'padding-top: 1rem">\n'
        '<summary style="font-family: var(--font-mono); font-size: 0.8rem; '
        'color: var(--color-text-subtle); cursor: pointer; letter-spacing: 0.05em; '
        'text-transform: uppercase; padding: 0.5rem 0">'
        'About these labels</summary>\n'
        '<div style="margin-top: 0.75rem; font-family: var(--font-mono); '
        'font-size: 0.8rem; color: var(--color-text-secondary); line-height: 1.6">\n'
        '<p style="margin-bottom: 1rem; font-style: italic">'
        'Not every tag needs a definition &mdash; those listed below cover the full '
        'vocabulary used across the dossier.</p>\n'

        '<h3 style="font-family: var(--font-sans); font-size: 0.9rem; font-weight: 700; '
        'margin-top: 1rem; margin-bottom: 0.5rem; text-transform: uppercase; '
        'letter-spacing: 0.05em">Divergence types</h3>\n'
        '<dl style="margin-bottom: 1rem">\n'
        f'<dt style="margin-top: 0.5rem">{_gb("factual", "#9f1239")}</dt>'
        '<dd style="margin-left: 0">Sources disagree on a verifiable fact: a date, number, '
        'name, or whether something happened.</dd>\n'
        f'<dt style="margin-top: 0.5rem">{_gb("framing", "#7c3aed")}</dt>'
        '<dd style="margin-left: 0">Sources describe the same event using different language '
        'or implied meaning. Example: one outlet calls a payment &ldquo;compensation,&rdquo; '
        'another calls it &ldquo;sanctions relief.&rdquo;</dd>\n'
        f'<dt style="margin-top: 0.5rem">{_gb("omission", "#ca8a04")}</dt>'
        '<dd style="margin-left: 0">One or more sources report something that other sources '
        'leave out entirely.</dd>\n'
        f'<dt style="margin-top: 0.5rem">{_gb("emphasis", "#0369a1")}</dt>'
        '<dd style="margin-left: 0">Sources cover the same event but give different aspects '
        'different weight or prominence. Example: one outlet leads with casualty figures; '
        'another treats them as a footnote to the political negotiations.</dd>\n'
        '</dl>\n'

        '<h3 style="font-family: var(--font-sans); font-size: 0.9rem; font-weight: 700; '
        'margin-top: 1rem; margin-bottom: 0.5rem; text-transform: uppercase; '
        'letter-spacing: 0.05em">Bias issues</h3>\n'
        '<dl style="margin-bottom: 1rem">\n'
        f'<dt style="margin-top: 0.5rem">{_gb("evaluative_adjective", "#ca8a04")}</dt>'
        '<dd style="margin-left: 0">A descriptive word that signals the writer&rsquo;s '
        'judgment rather than a neutral fact. Examples: &ldquo;staggering,&rdquo; '
        '&ldquo;sharp,&rdquo; &ldquo;dramatic.&rdquo;</dd>\n'
        f'<dt style="margin-top: 0.5rem">{_gb("intensifier", "#0369a1")}</dt>'
        '<dd style="margin-left: 0">A word that amplifies a statement without adding '
        'information. Examples: &ldquo;very,&rdquo; &ldquo;extremely,&rdquo; '
        '&ldquo;deeply.&rdquo;</dd>\n'
        f'<dt style="margin-top: 0.5rem">{_gb("loaded_term", "#9f1239")}</dt>'
        '<dd style="margin-left: 0">Vocabulary carrying strong political or emotional '
        'connotations that a more neutral word would avoid. Examples: &ldquo;regime&rdquo; '
        'vs. &ldquo;government,&rdquo; &ldquo;crackdown&rdquo; vs. '
        '&ldquo;enforcement.&rdquo;</dd>\n'
        f'<dt style="margin-top: 0.5rem">{_gb("hedging", "#64748b")}</dt>'
        '<dd style="margin-left: 0">Phrases that soften or obscure a claim, making '
        'attribution less clear. Examples: &ldquo;some say,&rdquo; &ldquo;allegedly,&rdquo; '
        '&ldquo;reportedly.&rdquo;</dd>\n'
        '</dl>\n'

        '<h3 style="font-family: var(--font-sans); font-size: 0.9rem; font-weight: 700; '
        'margin-top: 1rem; margin-bottom: 0.5rem; text-transform: uppercase; '
        'letter-spacing: 0.05em">Stakeholder types</h3>\n'
        '<dl style="margin-bottom: 0">\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">academia</dt>'
        '<dd style="margin-left: 0">Researchers, professors, think tanks, and '
        'university-based experts.</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">affected_community</dt>'
        '<dd style="margin-left: 0">People directly impacted by the events themselves '
        '&mdash; civilians, displaced persons, local populations. Voices from within the '
        'group, not their spokespersons.</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">civil_society</dt>'
        '<dd style="margin-left: 0">Non-state organizations representing collective '
        'interests (NGOs, human rights groups, trade unions, religious bodies).</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">government</dt>'
        '<dd style="margin-left: 0">Executive branch officials, ministries, heads of state, '
        'and their spokespersons.</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">industry</dt>'
        '<dd style="margin-left: 0">Private companies, trade associations, and commercial '
        'actors.</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">international_org</dt>'
        '<dd style="margin-left: 0">Multilateral bodies and their representatives '
        '(UN agencies, IMF, IAEA, Red Cross, regional alliances).</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">judiciary</dt>'
        '<dd style="margin-left: 0">Judges, courts, prosecutors, and legal bodies acting in '
        'their official capacity.</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">legislature</dt>'
        '<dd style="margin-left: 0">Parliament, Congress, or equivalent body. Kept separate '
        'from &ldquo;government&rdquo; because legislatures often hold positions that differ '
        'from their own executive branch.</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">media</dt>'
        '<dd style="margin-left: 0">Journalists, editorial boards, and outlets quoted for '
        'their position or analysis, not as sources of factual reporting.</dd>\n'
        '<dt style="font-weight: 700; margin-top: 0.5rem">military</dt>'
        '<dd style="margin-left: 0">Armed forces personnel, commanders, and defense '
        'ministries.</dd>\n'
        '</dl>\n'
        '</div>\n'
        '</details>\n'
    )


def build_footer() -> str:
    return (
        '<footer>\n'
        '<p>Generated by <a href="https://github.com/deniz-schwenk/independent-wire">Independent Wire</a></p>\n'
        '<p>This content was produced by AI agents</p>\n'
        '<p>AGPL-3.0 &mdash; Because transparency is not a feature, it is a promise</p>\n'
        '<p><a href="../feed.xml">RSS Feed</a></p>\n'
        '</footer>\n'
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def render(tp: dict) -> str:
    """Render a Topic Package dict to a self-contained HTML string."""
    css = build_css()
    headline = tp.get("article", {}).get("headline", "Independent Wire")

    back_nav = '<nav class="back-nav"><a href="../index.html">&larr; ALL DOSSIERS</a></nav>\n'
    back_nav_bottom = '<nav class="back-nav back-nav-bottom"><a href="../index.html">&larr; ALL DOSSIERS</a></nav>\n'

    sections = [
        back_nav,
        build_header(tp),
        build_follow_up_ref(tp),
        build_meta_bar(tp),
        build_source_map(tp),
        build_reader_note(tp),
        build_article_body(tp),
        build_perspectives(tp),
        build_missing_voices(tp),
        build_divergences(tp),
        build_bias_card(tp),
        build_coverage_gaps(tp),
        build_sources_table(tp),
        build_transparency(tp),
        build_glossary(),
        back_nav_bottom,
        build_footer(),
    ]

    body = "\n".join(s for s in sections if s)

    return (
        f'<!DOCTYPE html>\n'
        f'<html lang="en">\n'
        f'<head>\n'
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Space+Grotesk:wght@400;600;700;800&display=swap" rel="stylesheet">\n'
        f'<title>{_esc(headline)}</title>\n'
        f'<style>\n{css}</style>\n'
        f'</head>\n'
        f'<body>\n'
        f'<div class="container">\n'
        f'{body}'
        f'</div>\n'
        f'</body>\n'
        f'</html>\n'
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/render.py <topic-package.json>", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        tp = json.load(f)

    html_content = render(tp)
    output_path = input_path.with_suffix(".html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(output_path)


if __name__ == "__main__":
    main()
