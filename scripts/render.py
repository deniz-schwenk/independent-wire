#!/usr/bin/env python3
"""Independent Wire — Render a Topic Package JSON to self-contained HTML."""

import html
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from scripts.evidence_terrain import render_evidence_terrain
from scripts import render_labels as RL
from src.region_buckets import get_buckets, lookup_region

# Canonical site base — drives og:url / og:image absolute links. Matches
# `site/CNAME`. Local previews still work because relative asset paths in
# the page body remain unchanged; only social-card crawlers consume the
# absolute URLs.
SITE_BASE = "https://independent-wire.org"

# Read the small IW brand-mark SVG once at module load and inline it
# into the footer. Inlining (rather than `<img src=...>`) is required so
# the SVG inherits the host document's Google Fonts (Space Grotesk /
# Space Mono); `<img>`-embedded SVGs render in an isolated browser
# context that falls back to a system sans-serif. The XML processing
# instruction is stripped because HTML5 doesn't accept PIs in the body.
IW_SMALL_LIGHT_SVG = re.sub(
    r"<\?xml[^?]*\?>\s*",
    "",
    (Path(__file__).resolve().parent.parent / "site" / "assets" / "iw-small-light.svg")
    .read_text(encoding="utf-8"),
).strip()

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
    """Format YYYY-MM-DD to 'April 13, 2026' (en) / '13. April 2026' (de).
    German months come from the label map, not the locale (strftime emits English)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str or ""
    if RL.get_lang() == "de":
        return f"{dt.day}. {RL.month_name(dt.month, dt.strftime('%B'))} {dt.year}"
    return dt.strftime("%B %d, %Y").replace(" 0", " ")


def _badge(text: str, color: str) -> str:
    """Return a styled inline badge."""
    return (
        f'<span class="badge" style="background:{color}15;color:{color};'
        f'border:1px solid {color}40">{_esc(text)}</span>'
    )


# Color maps
SIGNIFICANCE_COLORS = {"critical": "#9f1239", "notable": "#ca8a04", "minor": "#64748b"}
DIVERGENCE_COLORS = {"factual": "#9f1239", "framing": "#7c3aed", "omission": "#ca8a04", "emphasis": "#0369a1"}
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

/* Source network SVG (legacy class — keeps any historical templates working) */
.source-network { width: 100%; max-width: 700px; margin: 0.5rem auto 1rem; display: block; }
/* Evidence terrain SVG */
.evidence-terrain { width: 100%; max-width: 700px; margin: 0.5rem auto 1rem; display: block; }
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

/* Cluster cards — one card per row, full container width. Two-
   column variant retired so the Cluster-ID pill, position label,
   summary, tier-grouped actors, and counts row all read across the
   full width (the cluster card is information-dense and benefits
   from the horizontal space). */
.card-grid { display: grid; grid-template-columns: 1fr; gap: 1rem; }
/* Cluster-ID pill at top-left of each cluster card. Shares
   ``.actor-card-cluster-box`` styling with the actor-card pills so
   the cross-reference renders identically on both sides. The pill
   needs a margin below to separate it from the position-label
   header that follows. */
.card > .actor-card-cluster-box {
  display: inline-block;
  margin-bottom: 0.5rem;
}
.card {
  border: 1px solid #000; border-radius: 0; padding: 1rem 1.25rem;
  background: var(--color-bg);
}
.card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem; }
.card-actor { font-family: var(--font-sans); font-weight: 700; font-size: 1rem; }
.card-meta { font-family: var(--font-mono); font-size: 0.8rem; color: var(--color-text-subtle); margin-bottom: 0.5rem; }
.card-position { font-family: var(--font-sans); font-size: 0.9rem; line-height: 1.55; color: var(--color-text-secondary); }
.card-quote { font-style: italic; font-size: 0.88rem; color: var(--color-text-subtle); margin-top: 0.5rem; border-left: 2px solid #000; padding-left: 0.75rem; }
.cluster-counts {
  font-family: var(--font-mono); font-size: 0.75rem;
  color: var(--color-text-subtle); margin: 0.75rem 0 0;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.cluster-counts a { color: inherit; text-decoration: underline; }
.cluster-counts a:hover { color: var(--color-text); }
.card:target { background: var(--color-bg-subtle, #f5f5f4); }

/* Single-voices bracket — visually distinguished from real shared-
   position clusters. Dashed left accent + neutral tinted background
   read as "this is a different kind of grouping" without breaking the
   page's existing card rhythm. */
.single-voices-bracket {
  border-left: 4px dashed #000;
  background: var(--color-bg-subtle, #f5f5f4);
  margin-top: 1rem;
}
.single-voices-bracket-tag {
  font-family: var(--font-mono); font-size: 0.7rem;
  color: var(--color-text-subtle); text-transform: uppercase;
  letter-spacing: 0.08em; margin-left: 0.5rem;
}

/* Cluster three-level actor sub-blocks (stated / reported / mentioned) */
.cluster-tier { margin-top: 0.85rem; }
.cluster-tier-label {
  font-family: var(--font-mono); font-size: 0.7rem; font-weight: 700;
  color: var(--color-text-subtle); margin: 0 0 0.35rem;
  text-transform: uppercase; letter-spacing: 0.08em;
}
.cluster-tier-actors {
  list-style: none; padding: 0; margin: 0;
  font-family: var(--font-sans);
}
.cluster-tier-actor {
  font-size: 0.85rem; line-height: 1.5;
  margin: 0.15rem 0; color: var(--color-text-secondary);
}
.cluster-tier-actor strong { color: var(--color-text); font-weight: 600; }
.cluster-tier-actor a { color: inherit; text-decoration: underline; }
.cluster-actor-role { color: var(--color-text-secondary); }
.cluster-actor-type {
  font-family: var(--font-mono); font-size: 0.65rem;
  color: var(--color-text-subtle); margin-left: 0.25rem;
  text-transform: uppercase; letter-spacing: 0.05em;
}

/* Editorial-outlet attribution — rendered on position cards with zero
   actors in place of the missing tier sub-lists. Lighter visual weight
   than tier blocks (smaller font, italic, muted color) since this is
   the secondary path; the card itself carries the visual frame. */
.cluster-editorial-attribution {
  margin-top: 0.85rem;
}
.cluster-editorial-attribution p {
  font-family: var(--font-sans); font-size: 0.85rem; font-style: italic;
  line-height: 1.5; color: var(--color-text-secondary); margin: 0;
}
.cluster-editorial-attribution strong {
  font-style: normal; font-weight: 600; color: var(--color-text);
}

/* Actors section — flat card grid with type-tab filter */
.actors h2 { margin-top: 2.5rem; }
.actors-meta {
  font-family: var(--font-sans); font-size: 0.95rem;
  color: var(--color-text-secondary);
  margin: 1rem 0 1.5rem;
  border-left: 3px solid #000; padding-left: 0.75rem;
}

.actors-tabs {
  display: flex; flex-wrap: wrap; gap: 0;
  margin-bottom: 1.5rem;
}
.actor-tab {
  font-family: var(--font-mono); font-size: 0.8rem;
  background: transparent; border: 1px solid #000;
  padding: 0.5rem 1rem; cursor: pointer;
  text-transform: uppercase; letter-spacing: 0.05em;
  color: #000; margin: 0 -1px -1px 0;
}
.actor-tab-count { margin-left: 0.4rem; color: var(--color-text-subtle); }
.actor-tab--active { background: #000; color: var(--color-bg); }
.actor-tab--active .actor-tab-count { color: var(--color-bg); }
.actor-tab:not(.actor-tab--active):hover {
  background: var(--color-bg-subtle, #f5f5f4);
}

/* Two-column grid with a vertical centre rule. The ::before pseudo
   spans the full grid height and sits in the middle of the column
   gap, matching the horizontal `border-top` rhythm on each card.
   Disabled on mobile via the @media block when the grid collapses
   to a single column. */
.actor-card-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0 1.5rem;
  position: relative;
}
.actor-card-grid::before {
  content: '';
  position: absolute;
  top: 0; bottom: 0;
  left: 50%; width: 1px;
  background: var(--color-border-light);
  transform: translateX(-50%);
  pointer-events: none;
}
.actor-card {
  border-top: 1px solid var(--color-border-light);
  padding: 1rem 0;
}
.actor-card[hidden] { display: none; }
.actor-card:target { background: var(--color-bg-subtle, #f5f5f4); }
.actor-card-header {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 0.25rem; gap: 0.5rem;
}
.actor-card-name {
  font-family: var(--font-sans); font-weight: 700; font-size: 1rem;
}
.actor-card-name a { color: inherit; text-decoration: none; }
.actor-card-src-count {
  font-family: var(--font-mono); font-size: 0.75rem;
  color: var(--color-text-subtle);
  text-transform: uppercase; letter-spacing: 0.05em;
  white-space: nowrap;
}
.actor-card-role {
  font-family: var(--font-sans); font-size: 0.9rem;
  color: var(--color-text-secondary);
  margin: 0 0 0.5rem;
}
.actor-card-cluster-refs, .actor-card-source-refs {
  display: flex; flex-wrap: wrap; gap: 0.2rem;
  margin-top: 0.4rem;
}
.actor-card-cluster-box {
  font-family: var(--font-mono); font-size: 0.7rem;
  background: transparent; border: 1px solid #000;
  padding: 0.2rem 0.5rem;
  text-transform: uppercase; letter-spacing: 0.05em;
  color: #000; text-decoration: none;
}
.actor-card-cluster-box:hover { background: var(--color-bg-subtle, #f5f5f4); }
.actor-card-cluster-box--bracket { border-style: dashed; }
/* Source-ref boxes — tightened (Correction 3, 2026-05-20) so ≥ 5
   `src-NNN` boxes fit per row at the desktop card width
   (container 740px → ~334px per card column). Lowercase label,
   minimal horizontal padding, no letter-spacing. */
.actor-card-source-box {
  font-family: var(--font-mono); font-size: 0.7rem;
  background: var(--color-bg-subtle, #f5f5f4);
  padding: 0.2rem 0.35rem;
  color: #000; text-decoration: none;
  letter-spacing: 0;
}
.actor-card-source-box:hover { background: var(--color-border-light); }

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
  content: "−  ";
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

/* Bias-card stat line */
.bias-stats {
  font-family: var(--font-mono); font-size: 0.85rem;
  color: var(--color-text-secondary);
  margin: 0 0 0.5rem; text-transform: uppercase; letter-spacing: 0.05em;
  display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: baseline;
}
.bias-stats strong { color: var(--color-text); font-weight: 700; }
.bias-stats .sep { color: var(--color-text-subtle); }


/* QA correction details */
.qa-tag {
  display: inline-block; padding: 0.05rem 0.4rem; margin-right: 0.35rem;
  font-family: var(--font-mono); font-size: 0.65rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em;
  border: 1px solid currentColor;
}
.qa-tag.tag-applied { color: #0f766e; }
.qa-tag.tag-retracted { color: #9f1239; }
.qa-detail {
  margin: 0.35rem 0 0.5rem 1rem; padding: 0.5rem 0.75rem;
  background: var(--color-bg-subtle); border-left: 3px solid var(--color-border-light);
  font-family: var(--font-sans); font-size: 0.82rem;
}
.qa-problem-type {
  display: inline-block; padding: 0.05rem 0.4rem; margin-bottom: 0.35rem;
  font-family: var(--font-mono); font-size: 0.65rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em;
  background: #ca8a0415; color: #ca8a04; border: 1px solid #ca8a0440;
}
.qa-excerpt {
  font-style: italic; margin: 0.25rem 0;
  border-left: 2px solid var(--color-border-light); padding-left: 0.6rem;
  color: var(--color-text-secondary);
}
.qa-explanation { margin-top: 0.35rem; line-height: 1.55; }
.qa-corrections-wrapper > summary {
  font-family: var(--font-mono); font-size: 0.78rem; color: var(--color-text-secondary);
  cursor: pointer; padding: 0.25rem 0; letter-spacing: 0.05em; text-transform: uppercase;
}
.qa-corrections-wrapper .qa-corrections { margin-top: 0.5rem; }
/* Mentioned Actors — same collapsible-footnote treatment as
   QA Corrections. Wraps the inner bracket card
   (`.single-voices-bracket`) and renders after the Position cards
   (2026-05-21: relocation from prominent section to collapsible). */
.mentioned-actors-wrapper > summary {
  font-family: var(--font-mono); font-size: 0.78rem; color: var(--color-text-secondary);
  cursor: pointer; padding: 0.25rem 0; letter-spacing: 0.05em; text-transform: uppercase;
}
.mentioned-actors-wrapper .mentioned-actors-body { margin-top: 0.75rem; }

/* Sources section — two-level outlet blocks */
.sources-meta {
  font-family: var(--font-mono); font-size: 0.85rem;
  color: var(--color-text-secondary); margin: 0 0 1rem;
}
.sources-by-outlet { display: flex; flex-direction: column; gap: 0.5rem; }
.outlet-block { border: 1px solid var(--color-border-light); padding: 0.5rem 0.75rem; }
.outlet-block > summary {
  font-family: var(--font-sans); cursor: pointer; padding: 0.35rem 0;
  display: flex; gap: 0.75rem; align-items: baseline; flex-wrap: wrap;
}
.outlet-block > summary strong { font-size: 1rem; }
.outlet-meta {
  font-family: var(--font-mono); font-size: 0.75rem;
  color: var(--color-text-subtle); text-transform: uppercase; letter-spacing: 0.05em;
}
.outlet-source-count {
  margin-left: auto; font-family: var(--font-mono); font-size: 0.75rem;
  color: var(--color-text-subtle); text-transform: uppercase; letter-spacing: 0.05em;
}
.source-list { list-style: none; padding: 0; margin: 0.5rem 0 0; }
.source {
  padding: 0.75rem 0; border-top: 1px solid var(--color-border-light);
}
.source:first-child { border-top: 0; }
.source:target { background: var(--color-bg-subtle, #f5f5f4); }
.source-header { font-family: var(--font-sans); font-size: 0.95rem; }
.source-id {
  font-family: var(--font-mono); font-size: 0.75rem;
  color: var(--color-text-subtle); margin-right: 0.4rem;
}
.source-headline { color: var(--color-primary); text-decoration: none; }
.source-headline:hover { text-decoration: underline; }
.source-meta {
  font-family: var(--font-mono); font-size: 0.7rem;
  color: var(--color-text-subtle); margin: 0.25rem 0;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.source-summary {
  font-family: var(--font-sans); font-size: 0.85rem; line-height: 1.55;
  color: var(--color-text-secondary); margin: 0.25rem 0;
}
.source-bias-note {
  font-family: var(--font-sans); font-size: 0.82rem;
  color: var(--color-text-subtle); margin: 0.25rem 0;
}
.source-actors-refs {
  font-family: var(--font-sans); font-size: 0.8rem;
  color: var(--color-text-subtle); margin-top: 0.35rem;
}
.source-actors-refs a { color: inherit; text-decoration: underline; }

/* Transparency trail */
.transparency { font-family: var(--font-mono); color: var(--color-text-subtle); font-size: 0.82rem; line-height: 1.6; }
.transparency h2 { font-family: var(--font-mono); color: var(--color-text-subtle); font-size: 1rem; }
.transparency dt { font-weight: 700; margin-top: 0.5rem; text-transform: uppercase; }
.transparency dd { margin: 0 0 0.5rem; padding-left: 0; }
.transparency ul { margin: 0.25rem 0; padding-left: 1.25rem; }
.transparency dt.pipeline-run { border-top: 1px solid var(--color-border-light); padding-top: 0.75rem; margin-top: 0.75rem; }
.transparency dd.pipeline-run { border-bottom: 1px solid var(--color-border-light); padding-bottom: 0.75rem; margin-bottom: 0.75rem; }

/* Strict-drop pruning collapsible */
.dropped-details > summary {
  font-family: var(--font-mono); font-size: 0.78rem; color: var(--color-text-secondary);
  cursor: pointer; padding: 0.25rem 0; letter-spacing: 0.05em; text-transform: uppercase;
}
.dropped-detail { margin-top: 0.5rem; }
.dropped-section-label {
  font-family: var(--font-mono); font-size: 0.7rem; color: var(--color-text-subtle);
  text-transform: uppercase; letter-spacing: 0.1em;
  margin: 0.5rem 0 0.25rem;
}
.dropped-list { list-style: none; padding-left: 0; margin: 0; }
.dropped-list > li {
  padding: 0.25rem 0; border-bottom: 1px solid var(--color-border-light);
  font-family: var(--font-sans); font-size: 0.82rem; color: var(--color-text-secondary);
}
.dropped-list > li:last-child { border-bottom: none; }
.dropped-id {
  display: inline-block; font-family: var(--font-mono); font-weight: 700;
  color: var(--color-text); margin-right: 0.4rem;
}
.dropped-outlet { color: var(--color-text); }
.dropped-label { font-family: var(--font-sans); }

/* Top bar — back-nav left, share button right */
.top-bar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 1.5rem;
}
.top-bar .back-nav { margin-bottom: 0; }

/* Share button */
.share-btn {
  font-family: var(--font-mono);
  font-size: 0.7rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
  background: transparent; color: #000;
  border: 1.5px solid #000;
  padding: 0.6rem 1rem;
  min-height: 44px; min-width: 44px;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}
.share-btn:hover { background: #000; color: #fff; }
.share-btn:focus-visible { outline: 2px solid #000; outline-offset: 2px; }

/* Footer */
footer {
  margin-top: 3rem;
  padding-top: 1.5rem;
  border-top: 3px solid #000;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1.5rem;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: #666;
  line-height: 2;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  text-align: left;
}
footer .footer-text { flex: 1 1 auto; }
footer .footer-text p { margin: 0; }
footer .footer-mark {
  flex: 0 0 auto;
  width: 80px; height: 80px;
  display: block;
}
footer .footer-mark svg { width: 100%; height: 100%; display: block; }
footer a { color: #000; text-decoration: underline; }

/* Responsive */
@media (max-width: 768px) {
  .container { padding: 1rem; }
  h1 { font-size: 1.4rem; }
  .actor-card-grid { grid-template-columns: 1fr; }
  .actor-card-grid::before { display: none; }
  .actors-tabs { font-size: 0.7rem; }
  .actor-tab { padding: 0.4rem 0.6rem; font-size: 0.7rem; }
  .meta-bar { flex-wrap: wrap; }
  .meta-item { min-width: 70px; border-right: none; border-bottom: 1px solid #000; }
  .meta-item:last-child { border-bottom: none; }
  .meta-number { font-size: 1.2rem; }
  .sources-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .article-body { font-size: 1rem; }
  footer { flex-direction: column-reverse; align-items: flex-start; gap: 1rem; }
  footer .footer-mark { width: 64px; height: 64px; }
}
""" + RL.lang_switch_css() + RL.support_block_css()


def build_header(tp: dict) -> str:
    article = tp.get("article", {})
    meta = tp.get("metadata", {})
    return (
        f'<h1>{_esc(article.get("headline", ""))}</h1>\n'
        f'<p class="subtitle">{_esc(article.get("subheadline", ""))}</p>\n'
        f'<p class="date">{_format_date(meta.get("date", ""))}</p>\n'
    )


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= n:
        return text
    return text[: max(0, n - 1)].rstrip() + "…"


def build_meta_tags(tp: dict) -> str:
    """Build Open Graph + Twitter Card meta tags for a TP page."""
    article = tp.get("article", {})
    tp_id = tp.get("id", "")
    headline = article.get("headline", "Independent Wire")
    description = _truncate(article.get("summary", ""), 200)
    canonical = f"{SITE_BASE}/reports/{tp_id}.html"
    image = f"{SITE_BASE}/assets/og-card.svg"
    return (
        f'<link rel="canonical" href="{_esc(canonical)}">\n'
        f'<meta property="og:type" content="article">\n'
        f'<meta property="og:site_name" content="Independent Wire">\n'
        f'<meta property="og:title" content="{_esc(headline)}">\n'
        f'<meta property="og:description" content="{_esc(description)}">\n'
        f'<meta property="og:url" content="{_esc(canonical)}">\n'
        f'<meta property="og:image" content="{_esc(image)}">\n'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{_esc(headline)}">\n'
        f'<meta name="twitter:description" content="{_esc(description)}">\n'
        f'<meta name="twitter:image" content="{_esc(image)}">\n'
    )


def build_share_script() -> str:
    """Inline Web Share API + clipboard fallback for `.share-btn` elements."""
    return (
        '<script>\n'
        "document.querySelectorAll('.share-btn').forEach(btn => {\n"
        "  btn.addEventListener('click', async () => {\n"
        "    const url = btn.dataset.url;\n"
        "    const title = btn.dataset.title;\n"
        "    if (navigator.share) {\n"
        "      try { await navigator.share({ title, url }); } catch (e) {}\n"
        "    } else {\n"
        "      try {\n"
        "        await navigator.clipboard.writeText(url);\n"
        "        const original = btn.textContent;\n"
        "        btn.textContent = 'Copied';\n"
        "        setTimeout(() => { btn.textContent = original; }, 1500);\n"
        "      } catch (e) {}\n"
        "    }\n"
        "  });\n"
        "});\n"
        '</script>\n'
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
        f'{RL.L("ui", "follow_up_to", "Follow-up to:")} &ldquo;{prev_headline}&rdquo; ({formatted_date})\n'
        f'<!-- FOLLOW_UP_LINK:{prev_tp_id} -->\n'
        '</div>\n'
    )


def build_meta_bar(tp: dict) -> str:
    sources_count = len(tp.get("sources", []))
    bias = tp.get("bias_analysis", {})
    lang_count = len(bias.get("source", {}).get("by_language", {}))
    persp_count = (
        bias.get("framing", {}).get("distinct_actor_count", 0)
    )
    div_count = len(tp.get("divergences", []))

    items = [
        (sources_count, RL.L("meta_bar", "Sources", "Sources")),
        (lang_count, RL.L("meta_bar", "Languages", "Languages")),
        (persp_count, RL.L("meta_bar", "Stakeholders", "Stakeholders")),
        (div_count, RL.L("meta_bar", "Divergences", "Divergences")),
    ]
    inner = "\n".join(
        f'<div class="meta-item"><span class="meta-number">{n}</span>'
        f'<span class="meta-label">{label}</span></div>'
        for n, label in items
    )
    return f'<div class="meta-bar">\n{inner}\n</div>\n'


def _country_region_color(country: str) -> str:
    """Return the bucket colour for a country, or grey for unbucketed."""
    bucket_key = lookup_region(country)
    if bucket_key is None:
        return "#6b7280"
    return get_buckets()[bucket_key].get("color", "#6b7280")


def build_source_map(tp: dict) -> str:
    """Build evidence terrain SVG + country badge legend.

    by_country is rebuilt from tp.sources (post-prune) so the map's
    'TOTAL SOURCES' figure stays in sync with the meta-bar header.
    bias_analysis.source.by_country is computed pre-prune and would
    diverge on dossiers where strict-drop pruning removed sources.
    """
    by_country: dict[str, int] = {}
    for src in tp.get("sources", []):
        country = src.get("country") or "Unknown"
        by_country[country] = by_country.get(country, 0) + 1

    svg_html = render_evidence_terrain(by_country)

    # Country badges sorted by count descending, coloured by region bucket.
    sorted_countries = sorted(by_country.items(), key=lambda x: -x[1])
    active_badges = []
    for country, count in sorted_countries:
        color = _country_region_color(country)
        label = f"{country} ({count})" if count > 1 else country
        active_badges.append(
            f'<span class="country-badge" style="background:{color}12;color:{color};'
            f'border:1px solid {color}30" '
            f'title="{_esc(country)}: {RL.count_noun(count, "sources", str(count) + " source" + ("s" if count != 1 else ""))}">'
            f'{_esc(label)}</span>'
        )

    badges_html = "\n".join(active_badges)
    return (
        f'<h2>{RL.L("section_heading", "Source Distribution", "Source Distribution")}</h2>\n'
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


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    """Return ``"1 actor"`` / ``"2 actors"`` style strings. ``plural``
    defaults to ``singular + 's'``."""
    word = singular if n == 1 else (plural or f"{singular}s")
    return f"{n} {word}"


_CLUSTER_TIERS: tuple[tuple[str, str], ...] = (
    ("stated", "Stated"),
    ("reported", "Reported"),
    ("mentioned", "Mentioned"),
)


def _cluster_id_pill(cluster_id: str, idx: int) -> str:
    """Position-ID pill — the small ``Position N`` box shared between
    the Actors-section (per-actor cross-references) and the
    Perspectives-section (top-of-card identifier on each position
    card). Same text, same styling, same anchor target — so the two
    sides of the cross-reference render identically. Returns the
    bare ``<a>`` element; wrapping context is up to the caller.

    The function and CSS-class names retain the legacy ``cluster``
    token (internal identifiers, not user-visible). Only the rendered
    text was renamed from ``Cluster N`` to ``Position N`` on
    2026-05-21."""
    return (
        f'<a class="actor-card-cluster-box" href="#{_esc(cluster_id)}">'
        f'Position {idx}</a>'
    )


def _cluster_actor_entry(
    actor: dict, cluster_source_ids: set[str]
) -> str:
    """Render a single actor entry inside a cluster sub-block.

    Markup parallels the Actors-section header: name (anchor to the
    Actors-section row), role, type-badge. The per-actor source-id
    list previously rendered here was moved to the Actors-section
    card to keep cluster cards scannable (5-20 source tags per actor
    was overwhelming). Readers who want the full source attribution
    click the actor name to jump to the Actors-section.

    ``cluster_source_ids`` is retained on the signature for API
    stability and future use; it is no longer read here.
    """
    del cluster_source_ids  # retained for signature stability; see docstring
    aid = actor.get("id", "")
    name = _esc(actor.get("name", ""))
    role = _esc(actor.get("role", ""))
    atype = _esc(RL.L("actor_type", actor.get("type", ""), actor.get("type", "")))
    name_html = (
        f'<a href="#{_esc(aid)}">{name}</a>' if aid else name
    )
    return (
        f'<li class="cluster-tier-actor">'
        f'<strong>{name_html}</strong> '
        f'<span class="cluster-actor-role">{role}</span> '
        f'<span class="cluster-actor-type">{atype}</span>'
        f'</li>'
    )


def build_perspectives(tp: dict) -> str:
    """Render Perspective V2 position_clusters. One cluster = one card.

    Cluster cards show the position label, a one-line summary, three
    optional actor sub-blocks (Stated / Reported / Mentioned), and a
    monospace counts row: ``{n_actors} · {n_sources} · {n_regions} ·
    {n_languages}``. The three sub-blocks partition the cluster's
    ``actor_ids`` by evidentiary tier; an empty sub-list is omitted
    entirely. The actor count is wrapped in ``<a
    href="#cluster-{id}">`` so a click filters the Actors-section to
    this cluster's members.
    """
    clusters = tp.get("perspectives", {}).get("position_clusters", [])
    if not clusters:
        return ""
    actors = tp.get("actors") or []
    actor_index: dict[str, dict] = {}
    for actor in actors:
        if isinstance(actor, dict):
            aid = actor.get("id")
            if isinstance(aid, str) and aid:
                actor_index[aid] = actor

    # Index sources by id, retaining the order they appear in tp["sources"]
    # so the editorial-attribution block (rendered for zero-actor cards)
    # lists outlets in the same visual order as the rest of the dossier.
    sources_seq = tp.get("sources") or []
    source_outlet_by_id: dict[str, str] = {}
    for src in sources_seq:
        if not isinstance(src, dict):
            continue
        sid = src.get("id")
        outlet = src.get("outlet")
        if isinstance(sid, str) and sid and isinstance(outlet, str) and outlet:
            source_outlet_by_id[sid] = outlet

    cards = []
    # 1-based emission index matches `build_actors_section`'s
    # cluster-index, so the ``Cluster N`` pill on a cluster card
    # carries the same N as the pills referencing it from actor cards.
    for cluster_idx, c in enumerate(clusters, start=1):
        if not isinstance(c, dict):
            continue
        label = c.get("position_label", "")
        summary = c.get("position_summary", "")
        cluster_id = c.get("id", "")
        n_actors = int(c.get("n_actors", 0) or 0)
        n_sources = int(c.get("n_sources", 0) or 0)
        n_regions = int(c.get("n_regions", 0) or 0)
        n_languages = int(c.get("n_languages", 0) or 0)
        cluster_source_ids = {
            sid for sid in (c.get("source_ids") or []) if isinstance(sid, str)
        }

        tier_blocks: list[str] = []
        for tier_key, tier_label in _CLUSTER_TIERS:
            tier_aids = [
                a for a in (c.get(tier_key) or []) if isinstance(a, str)
            ]
            if not tier_aids:
                continue
            entries = [
                _cluster_actor_entry(actor_index[aid], cluster_source_ids)
                for aid in tier_aids
                if aid in actor_index
            ]
            if not entries:
                continue
            tier_blocks.append(
                f'  <div class="cluster-tier cluster-tier-{tier_key}">\n'
                f'    <h4 class="cluster-tier-label">{RL.L("position_classifier", tier_key, tier_label)}</h4>\n'
                f'    <ul class="cluster-tier-actors">{"".join(entries)}</ul>\n'
                f'  </div>\n'
            )

        # Editorial-attribution fallback for zero-actor cards. When the
        # cluster has no actors backing it across any tier, the position
        # is editorially carried by the outlets in its source set; name
        # them inline so the card isn't visually empty. Outlets here do
        # NOT enter the actor list (they remain sources, not actors).
        attribution_block = ""
        if not tier_blocks:
            seen: set[str] = set()
            ordered_outlets: list[str] = []
            for src in sources_seq:
                if not isinstance(src, dict):
                    continue
                sid = src.get("id")
                if not (isinstance(sid, str) and sid in cluster_source_ids):
                    continue
                outlet = source_outlet_by_id.get(sid)
                if not outlet or outlet in seen:
                    continue
                seen.add(outlet)
                ordered_outlets.append(outlet)
            if ordered_outlets:
                outlets_html = ", ".join(
                    f"<strong>{_esc(o)}</strong>" for o in ordered_outlets
                )
                attribution_block = (
                    f'  <div class="cluster-editorial-attribution">\n'
                    f'    <p>{RL.L("ui", "editorial_position_attributed_to", "Editorial position attributed to:")} '
                    f'{outlets_html}</p>\n'
                    f'  </div>\n'
                )

        actors_label = RL.count_noun(n_actors, "actors", _plural(n_actors, "actor"))
        if cluster_id:
            actors_html = (
                f'<a href="#cluster-{_esc(cluster_id)}">{actors_label}</a>'
            )
        else:
            actors_html = actors_label

        counts_line = (
            f'<p class="cluster-counts">'
            f'<span class="cluster-counts-actors">{actors_html}</span>'
            f' &middot; '
            f'<span>{RL.count_noun(n_sources, "sources", _plural(n_sources, "source"))}</span>'
            f' &middot; '
            f'<span>{RL.count_noun(n_regions, "regions", _plural(n_regions, "region"))}</span>'
            f' &middot; '
            f'<span>{RL.count_noun(n_languages, "languages", _plural(n_languages, "language"))}</span>'
            f'</p>\n'
        )

        # Cluster-ID pill at top-left of the card. Same markup as the
        # ``Cluster N`` pill used on actor cards, so the cross-reference
        # is visually symmetric. Omitted when the cluster has no id —
        # the pill's anchor target would be meaningless.
        pill_html = (
            f'  {_cluster_id_pill(cluster_id, cluster_idx)}\n'
            if cluster_id else ""
        )

        cards.append(
            f'<div class="card" id="{_esc(cluster_id)}">\n'
            f'{pill_html}'
            f'  <div class="card-header"><span class="card-actor">{_esc(label)}</span></div>\n'
            f'  <div class="card-position">{_esc(summary)}</div>\n'
            f'{"".join(tier_blocks)}'
            f'{attribution_block}'
            f'  {counts_line}'
            f'</div>\n'
        )
    return (f'<h2>{RL.L("section_heading", "Perspectives — Positions", "Perspectives &mdash; Positions")}</h2>\n'
            f'<div class="card-grid">\n{"".join(cards)}</div>\n')


# Tier sub-list field names on the mentioned_actors bracket. Mirrors
# the tier-label pairs in `_CLUSTER_TIERS` but the bracket uses the
# `actors_*` prefix to make it textually obvious that the bracket is
# not a regular position cluster. CSS class names retain the legacy
# ``single-voices-bracket`` / ``cluster-tier-*`` tokens — internal
# identifiers, not user-visible.
_MENTIONED_ACTORS_TIERS: tuple[tuple[str, str], ...] = (
    ("actors_stated", "Stated"),
    ("actors_reported", "Reported"),
    ("actors_mentioned", "Mentioned"),
)


def build_mentioned_actors_section(tp: dict) -> str:
    """Render the deterministic mentioned-actors section, when present.

    Reads `tp["perspectives"]["mentioned_actors"]` — a dict written by
    the `derive_mentioned_actors` topic-stage (renamed 2026-05-21 from
    `derive_single_voices`; threshold dropped so every non-cluster
    actor qualifies).

    The card itself mirrors the structural shape of a position card
    (position label + summary + tier-grouped actor list + counts) and
    is visually distinguished via the legacy ``single-voices-bracket``
    CSS class (dashed left accent + tinted background) and a small
    "Bracket" tag in the header. The DOM anchor is
    ``id="mentioned-actors"`` — explicitly separate from position-card
    ``pc-NNN`` anchors so cross-references from the Actors-section can
    distinguish the two.

    The card is wrapped in a default-closed
    ``<details class="mentioned-actors-wrapper">`` collapsible. The
    summary line reads ``Mentioned Actors — N noted`` (singular ``note``
    when N=1) — mirroring the QA Corrections / Coverage Limits
    collapsible-footnote pattern.

    The section is omitted entirely (no empty ``<details>`` shell) when:
    - the slot is absent (legacy fallback for pre-this-change TPs); or
    - `actor_ids[]` is empty (no non-cluster actor exists).
    """
    ma = tp.get("perspectives", {}).get("mentioned_actors")
    if not isinstance(ma, dict) or not ma:
        return ""
    actor_ids = [a for a in (ma.get("actor_ids") or []) if isinstance(a, str)]
    if not actor_ids:
        return ""

    label = ma.get("position_label", "Mentioned actors")
    summary = ma.get("summary", "")

    actors = tp.get("actors") or []
    actor_index: dict[str, dict] = {}
    for actor in actors:
        if isinstance(actor, dict):
            aid = actor.get("id")
            if isinstance(aid, str) and aid:
                actor_index[aid] = actor

    tier_blocks: list[str] = []
    for tier_key, tier_label in _MENTIONED_ACTORS_TIERS:
        tier_aids = [
            a for a in (ma.get(tier_key) or []) if isinstance(a, str)
        ]
        if not tier_aids:
            continue
        entries = [
            _cluster_actor_entry(actor_index[aid], set())
            for aid in tier_aids
            if aid in actor_index
        ]
        if not entries:
            continue
        tier_blocks.append(
            f'  <div class="cluster-tier cluster-tier-{tier_key}">\n'
            f'    <h4 class="cluster-tier-label">{RL.L("position_classifier", tier_key.replace("actors_", ""), tier_label)}</h4>\n'
            f'    <ul class="cluster-tier-actors">{"".join(entries)}</ul>\n'
            f'  </div>\n'
        )

    counts = ma.get("counts") or {}
    n_actors = int(counts.get("actors", 0) or 0)
    n_sources = int(counts.get("sources", 0) or 0)
    n_regions = int(counts.get("regions", 0) or 0)
    n_languages = int(counts.get("languages", 0) or 0)
    counts_line = (
        f'<p class="cluster-counts">'
        f'<span class="cluster-counts-actors">'
        f'<a href="#mentioned-actors">{_plural(n_actors, "actor")}</a>'
        f'</span>'
        f' &middot; '
        f'<span>{_plural(n_sources, "source")}</span>'
        f' &middot; '
        f'<span>{_plural(n_regions, "region")}</span>'
        f' &middot; '
        f'<span>{_plural(n_languages, "language")}</span>'
        f'</p>\n'
    )

    inner_card = (
        '<div class="card single-voices-bracket" id="mentioned-actors">\n'
        '  <div class="card-header">'
        f'<span class="card-actor">{_esc(label)}</span>'
        f'<span class="single-voices-bracket-tag">{RL.L("ui", "single_voices_bracket_tag", "Bracket")}</span>'
        '</div>\n'
        f'  <div class="card-position">{_esc(summary)}</div>\n'
        f'{"".join(tier_blocks)}'
        f'  {counts_line}'
        '</div>\n'
    )

    # Singular `note` for N=1, plural `noted` otherwise — mirrors the
    # "X note(s)" pattern of QA Corrections / Coverage Limits but uses
    # the verb-form "noted" to read as "N actors noted in the corpus."
    summary_line = (
        f'{RL.L("ui", "mentioned_actors", "Mentioned Actors")} &mdash; <strong>{n_actors} '
        f'{RL.L("ui", "noted_verb", "note" + ("d" if n_actors != 1 else ""))}</strong>'
    )
    return (
        f'<details class="mentioned-actors-wrapper">\n'
        f'  <summary>{summary_line}</summary>\n'
        f'  <div class="mentioned-actors-body">\n'
        f'{inner_card}'
        f'  </div>\n'
        f'</details>\n'
    )


# Canonical actor-type enum (declared order from
# `agents/perspective/INSTRUCTIONS.md`). Drives the tab bar layout and
# group rendering order. Any actor whose `type` is not in this enum
# still renders — under an "Other" group at the end of the card grid,
# visible only on the ALL tab (no per-type tab targets it).
_ACTOR_TYPE_ENUM: tuple[str, ...] = (
    "government",
    "legislature",
    "judiciary",
    "military",
    "industry",
    "civil_society",
    "academia",
    "media",
    "international_org",
    "affected_community",
)


def _tab_label(t: str) -> str:
    """Tab labels render in uppercase with underscores converted to
    spaces (`civil_society` → `CIVIL SOCIETY`); German via the label map."""
    if not t:
        return RL.L("actor_type", "_other", "OTHER").upper()
    return RL.L("actor_type", t, t.replace("_", " ")).upper()


def build_actors_section(tp: dict) -> str:
    """Actors-section as flat card grid with type-tab filter.

    Replaces the prior 4-column table (Issue 7, commit 557cea5) and
    its first iteration (commit 5c51953, grouped sub-headings) with a
    single continuous card grid. The section serves as a navigation
    bridge — position cards and the mentioned-actors bracket back-link
    to ``#actor-NNN`` anchors that live on the cards.

    Layout:
    - Header: plain ``<h2>Actors</h2>`` (matches every other section
      heading — no §-prefix, no right-aligned count).
    - Sub-line: ``N actors quoted across this topic. Jump from any
      name above to find every position and source the actor figures
      in.``
    - Tab bar: ``ALL N`` first, then one tab per populated
      `_ACTOR_TYPE_ENUM` entry in declared order. Tabs with zero
      actors in this dossier are omitted entirely (corrected from the
      earlier "render as disabled" treatment).
    - Card grid: one continuous 2-column grid. Cards are emitted in
      enum order across the underlying type groups (within each
      group, sorted by source-ref count desc with actor name as
      tie-break). No visible sub-headings — group boundaries are
      visually seamless when ALL is active; clicking a type tab
      hides cards from other types.

    Per-card content:
    - Top-left: actor name (anchor target ``id="actor-NNN"``).
      ``(anonymous)`` suffix preserved when ``actor.is_anonymous``.
    - Top-right: ``N SRC``.
    - Second line: role text.
    - Position-ref boxes: outlined boxes labelled ``Position N``
      linking to ``#pc-NNN``. Bracket actors get a dashed-border
      ``Mentioned actors`` box linking to ``#mentioned-actors``.
    - Source-ref boxes: filled boxes labelled ``src-NNN`` linking to
      ``#src-NNN``. Tightened so ≥ 5 boxes fit in a single card-width
      row at desktop.

    Tab filtering: minimal inline JS sets `hidden` on every
    ``.actor-card`` whose ``data-actor-type`` does not match the
    active tab. ALL clears the filter.
    """
    actors_in = tp.get("actors") or []
    clusters = tp.get("perspectives", {}).get("position_clusters", []) or []
    mentioned_actors = (
        tp.get("perspectives", {}).get("mentioned_actors") or {}
    )

    # cluster_id → 1-based emission index. Drives the human-readable
    # "Position N" link text.
    cluster_index: dict[str, int] = {}
    for i, c in enumerate(clusters, start=1):
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if isinstance(cid, str) and cid:
            cluster_index[cid] = i

    # actor_id → list of cluster_ids the actor appears in (any tier),
    # in cluster-emission order.
    actor_clusters: dict[str, list[str]] = {}
    for c in clusters:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        for aid in c.get("actor_ids") or []:
            if not isinstance(aid, str):
                continue
            actor_clusters.setdefault(aid, []).append(cid)

    # Bracket-actor set.
    bracket_actor_ids: set[str] = {
        a for a in (mentioned_actors.get("actor_ids") or [])
        if isinstance(a, str)
    } if isinstance(mentioned_actors, dict) else set()

    # Filter to dict-shaped actors and bucket by type.
    actors: list[dict] = [a for a in actors_in if isinstance(a, dict)]
    n_total = len(actors)
    by_type: dict[str, list[dict]] = {}
    for actor in actors:
        atype = actor.get("type") or ""
        by_type.setdefault(atype, []).append(actor)

    # Render order: enum types first, then any extra types found in
    # the data (preserved insertion order). Empty enum types are
    # included in the iteration so the per-type tab count can be
    # rendered later — but tabs with zero count are skipped.
    extra_types = [
        t for t in by_type.keys()
        if t and t not in _ACTOR_TYPE_ENUM
    ]
    render_types: list[str] = list(_ACTOR_TYPE_ENUM) + extra_types

    # Sub-line.
    if RL.get_lang() == "de":
        _actor_word = "Akteur" if n_total == 1 else "Akteure"
        actors_meta_html = (
            f'<p class="actors-meta">{n_total} {_actor_word}, '
            f'die in diesem Thema zitiert werden. Springen Sie von einem '
            f'Namen oben zu jeder Position und Quelle, in der der Akteur '
            f'vorkommt.</p>\n'
        )
    else:
        actors_meta_html = (
            f'<p class="actors-meta">{n_total} '
            f'actor{"" if n_total == 1 else "s"} quoted across this topic. '
            f'Jump from any name above to find every position and source '
            f'the actor figures in.</p>\n'
        )

    if n_total == 0:
        return (
            '<section id="actors-section" class="actors">\n'
            f'<h2>{RL.L("section_heading", "Actors", "Actors")}</h2>\n'
            f'{actors_meta_html}'
            '</section>\n'
        )

    # -- Tab bar (populated types only) --
    tab_buttons: list[str] = []
    tab_buttons.append(
        '<button class="actor-tab actor-tab--active" '
        'type="button" data-type-target="all">'
        f'<span class="actor-tab-name">{RL.L("ui", "actor_tab_all", "ALL")}</span> '
        f'<span class="actor-tab-count">{n_total}</span>'
        '</button>'
    )
    for atype in _ACTOR_TYPE_ENUM:
        count = len(by_type.get(atype, []))
        if count == 0:
            # Correction 1: zero-count tabs hidden entirely.
            continue
        tab_buttons.append(
            f'<button class="actor-tab" type="button" '
            f'data-type-target="{_esc(atype)}">'
            f'<span class="actor-tab-name">{_esc(_tab_label(atype))}</span> '
            f'<span class="actor-tab-count">{count}</span>'
            '</button>'
        )
    tabs_html = (
        '<div class="actors-tabs" role="tablist">\n'
        + "".join(tab_buttons)
        + '\n</div>\n'
    )

    # -- Card grid --
    def _actor_source_ids(actor: dict) -> list[str]:
        """Dedup actor.source_ids preserving first-appearance order."""
        seen: set[str] = set()
        ordered: list[str] = []
        for sid in actor.get("source_ids") or []:
            if not isinstance(sid, str) or not sid or sid in seen:
                continue
            seen.add(sid)
            ordered.append(sid)
        return ordered

    def _build_card(actor: dict, atype: str) -> str:
        aid = actor.get("id", "")
        name = _esc(actor.get("name", ""))
        role = _esc(actor.get("role", ""))
        anon_html = (
            f' <em class="actor-anonymous">{RL.L("ui", "anonymous", "(anonymous)")}</em>'
            if actor.get("is_anonymous") else ""
        )
        sids = _actor_source_ids(actor)
        n_src = len(sids)

        cluster_boxes: list[str] = []
        for cid in actor_clusters.get(aid, []):
            idx = cluster_index.get(cid)
            if idx is None:
                continue
            cluster_boxes.append(_cluster_id_pill(cid, idx))
        if aid in bracket_actor_ids:
            cluster_boxes.append(
                '<a class="actor-card-cluster-box actor-card-cluster-box--bracket"'
                f' href="#mentioned-actors">{RL.L("ui", "mentioned_actors", "Mentioned actors")}</a>'
            )
        cluster_refs_html = (
            f'<div class="actor-card-cluster-refs">{"".join(cluster_boxes)}</div>\n'
            if cluster_boxes else ""
        )

        if sids:
            source_box_html = "".join(
                f'<a class="actor-card-source-box" href="#{_esc(sid)}">'
                f'{_esc(sid)}</a>'
                for sid in sids
            )
            source_refs_html = (
                f'<div class="actor-card-source-refs">{source_box_html}</div>\n'
            )
        else:
            source_refs_html = ""

        role_html = (
            f'<p class="actor-card-role">{role}</p>\n' if role else ""
        )

        return (
            f'<article id="{_esc(aid)}" class="actor-card" '
            f'data-actor-type="{_esc(atype)}">\n'
            '  <div class="actor-card-header">\n'
            f'    <strong class="actor-card-name">{name}{anon_html}</strong>\n'
            f'    <span class="actor-card-src-count">{n_src} SRC</span>\n'
            '  </div>\n'
            f'  {role_html}'
            f'  {cluster_refs_html}'
            f'  {source_refs_html}'
            '</article>\n'
        )

    # Concatenate cards in enum order; within each underlying type
    # group, sort by source-ref count desc with name as tie-break.
    card_blocks: list[str] = []
    for atype in render_types:
        members = by_type.get(atype, [])
        if not members:
            continue
        sorted_members = sorted(
            members,
            key=lambda a: (
                -len(_actor_source_ids(a)),
                (a.get("name") or "").lower(),
            ),
        )
        for actor in sorted_members:
            card_blocks.append(_build_card(actor, atype))

    cards_html = "".join(card_blocks)
    grid_html = (
        f'<div class="actor-card-grid">\n{cards_html}</div>\n'
    )

    js_shim = (
        '<script>\n'
        '(function() {\n'
        '  const section = document.getElementById(\'actors-section\');\n'
        '  if (!section) return;\n'
        '  const tabs = section.querySelectorAll(\'.actor-tab\');\n'
        '  const cards = section.querySelectorAll(\'.actor-card\');\n'
        '  tabs.forEach(tab => {\n'
        '    tab.addEventListener(\'click\', () => {\n'
        '      const target = tab.dataset.typeTarget || \'all\';\n'
        '      cards.forEach(card => {\n'
        '        card.hidden = (target !== \'all\' && card.dataset.actorType !== target);\n'
        '      });\n'
        '      tabs.forEach(t => t.classList.toggle(\'actor-tab--active\', t === tab));\n'
        '    });\n'
        '  });\n'
        '})();\n'
        '</script>\n'
    )

    return (
        '<section id="actors-section" class="actors">\n'
        f'<h2>{RL.L("section_heading", "Actors", "Actors")}</h2>\n'
        f'{actors_meta_html}'
        f'{tabs_html}'
        f'{grid_html}'
        f'{js_shim}'
        '</section>\n'
    )


def build_what_is_missing_section(tp: dict) -> str:
    """Render the Consolidator's ``what_is_missing`` output as a
    prominent section directly before Sources.

    Reads ``tp["what_is_missing"]`` (written by the LLM
    ``ConsolidatorStage`` — see ``REPORT-DIAGNOSTIC-2026-05-23.md``)
    and surfaces its two arrays under sub-headers:

    - ``Voices missing`` — stakeholders, regions, languages, or media
      spheres whose perspective the corpus does not reach.
    - ``Topics missing`` — aspects, dimensions, angles, or themes the
      corpus does not cover.

    Edge cases:

    - Both lists empty → return empty string (section omitted).
    - Only one list populated → render that sub-header alone.
    - ``what_is_missing`` key absent or non-dict (legacy TP rendered
      before the Consolidator landed) → return empty string.
    - Non-string entries in either list are silently dropped — only
      non-empty strings survive into the rendered ``<li>`` items.
    """
    raw = tp.get("what_is_missing")
    if not isinstance(raw, dict):
        return ""

    def _clean(entries: object) -> list[str]:
        if not isinstance(entries, list):
            return []
        return [e for e in entries if isinstance(e, str) and e]

    voices = _clean(raw.get("voices_missing"))
    topics = _clean(raw.get("topics_missing"))
    if not voices and not topics:
        return ""

    parts: list[str] = [f'<h2>{RL.L("section_heading", "What is missing", "What is missing")}</h2>\n']
    if voices:
        items = "".join(f"<li>{_esc(v)}</li>" for v in voices)
        parts.append(f'<h3>{RL.L("section_heading", "Voices missing", "Voices missing")}</h3>\n')
        parts.append(f'<ul class="missing-positions">{items}</ul>\n')
    if topics:
        items = "".join(f"<li>{_esc(t)}</li>" for t in topics)
        parts.append(f'<h3>{RL.L("section_heading", "Topics missing", "Topics missing")}</h3>\n')
        parts.append(f'<ul class="missing-positions">{items}</ul>\n')
    return "".join(parts)


def build_divergences(tp: dict) -> str:
    divs = tp.get("divergences", [])
    if not divs:
        return ""

    items = []
    for d in divs:
        dtype = d.get("type", "emphasis")
        dcolor = DIVERGENCE_COLORS.get(dtype, "#64748b")
        resolution = d.get("resolution", "unresolved")
        res_label = RL.L("resolution", resolution, RESOLUTION_LABELS.get(resolution, resolution))

        desc = _esc(d.get("description", ""))
        desc = _resolve_source_refs(desc)

        note = _esc(d.get("resolution_note", ""))
        note_html = f'<div class="divergence-resolution"><strong>{_esc(res_label)}:</strong> {note}</div>' if note else ""

        items.append(
            f'<div class="divergence">\n'
            f'  <div class="divergence-header">{_badge(RL.L("divergence_type", dtype, dtype), dcolor)}</div>\n'
            f'  <div class="divergence-desc">{desc}</div>\n'
            f'  {note_html}\n'
            f'</div>\n'
        )
    return f'<h2>{RL.L("section_heading", "Divergences", "Divergences")}</h2>\n{"".join(items)}'


def build_bias_card(tp: dict) -> str:
    bias = tp.get("bias_analysis", {})
    # Filter out self-retracted findings (finding_valid == False) added
    # by the Language Bias Analyzer's second-pass review. Legacy-
    # permissive: a finding missing the field entirely is treated as
    # valid so pre-2026-05-19 TPs still render correctly without
    # backfill. Order of first appearance is preserved.
    findings = [
        f for f in bias.get("language", [])
        if not (isinstance(f, dict) and f.get("finding_valid") is False)
    ]
    by_language = bias.get("source", {}).get("by_language", {})
    framing = bias.get("framing", {})
    source = bias.get("source", {})

    parts = []
    parts.append(f'<h2>{RL.L("section_heading", "Bias Analysis", "Bias Analysis")}</h2>\n')

    # Stat line — deterministic aggregates for the dossier.
    cluster_count = framing.get("cluster_count", 0)
    distinct_actors = framing.get("distinct_actor_count", 0)
    source_total = source.get("total", len(tp.get("sources", [])))
    lang_count = len(by_language)
    parts.append(
        '<p class="bias-stats">'
        f'<span><strong>{cluster_count}</strong> {RL.noun(cluster_count, "position_clusters", "position clusters")}</span>'
        '<span class="sep">&middot;</span>'
        f'<span><strong>{distinct_actors}</strong> {RL.noun(distinct_actors, "distinct_actors", "distinct actors")}</span>'
        '<span class="sep">&middot;</span>'
        f'<span><strong>{source_total}</strong> {RL.noun(source_total, "sources", "sources")}</span>'
        '<span class="sep">&middot;</span>'
        f'<span><strong>{lang_count}</strong> {RL.noun(lang_count, "languages", "languages")}</span>'
        '</p>\n'
    )

    # Summary line — always visible. V2 schema has no severity field.
    if findings:
        parts.append(
            f'<p style="font-family:var(--font-mono);font-size:0.85rem;'
            f'color:var(--color-text-secondary);">'
            f'{RL.count_noun(len(findings), "language_bias_findings", str(len(findings)) + " language bias finding" + ("s" if len(findings) != 1 else ""))}'
            f'</p>\n'
        )
    else:
        parts.append(
            f'<p style="font-family:var(--font-mono);font-size:0.85rem;'
            f'color:var(--color-text-secondary);">'
            f'{RL.L("ui", "no_language_bias_findings", "No language bias findings")}</p>\n'
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
            f'{_badge(RL.L("bias_issue", issue, issue), issue_color)}\n'
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
            f'margin-top:1.5rem">{RL.L("section_heading", "Source Balance by Language", "Source Balance by Language")}</h3>\n'
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
            f'{RL.L("ui", "show_detailed_findings", "Show detailed findings")}</summary>\n'
            f'<div style="margin-top:0.5rem">\n'
            f'{findings_html}'
            f'{bar_html}'
            f'</div>\n'
            f'</details>\n'
        )

    return "".join(parts)


_OUTLET_COUNTRY_BY_NAME: dict[str, str] | None = None


def _outlet_country_lookup(name: str) -> str | None:
    """Build a reverse outlet-name → country lookup from
    ``config/outlet_registry.json`` once and cache it. Returns ``None``
    when no entry matches. Different hostnames pointing at the same
    outlet name resolve to the first country observed (rare, defensive)."""
    global _OUTLET_COUNTRY_BY_NAME
    if _OUTLET_COUNTRY_BY_NAME is None:
        registry_path = Path(__file__).resolve().parents[1] / "config" / "outlet_registry.json"
        try:
            raw = json.loads(registry_path.read_text())
        except FileNotFoundError:
            raw = {}
        out: dict[str, str] = {}
        for key, value in raw.items():
            if key.startswith("_") or not isinstance(value, dict):
                continue
            outlet_name = value.get("outlet")
            country = value.get("country")
            if isinstance(outlet_name, str) and isinstance(country, str):
                out.setdefault(outlet_name, country)
        _OUTLET_COUNTRY_BY_NAME = out
    return _OUTLET_COUNTRY_BY_NAME.get(name)


def _outlet_meta_line(outlet_name: str, sample_source: dict) -> str:
    """Compose the Country · editorial_independence subheader per
    Decision 6 of TASK-RENDER-RESTRUCTURE-V2:

    - Both present:        ``"{Country} · {editorial_independence}"``
    - Country only:        ``"{Country} · not yet categorized"``
    - Independence only:   ``"{editorial_independence}"``
    - Neither:             ``"not yet categorized"``

    Country resolution: prefer ``sample_source.country``; fall back to
    the outlet-name reverse-lookup against ``config/outlet_registry.json``;
    omit when both are absent.

    The "not yet categorized" wording is editorial — it telegraphs the
    data gap and a commitment to closing it.
    """
    independence = sample_source.get("editorial_independence")
    country = sample_source.get("country")
    if not country:
        country = _outlet_country_lookup(outlet_name)

    if independence and country:
        return f"{_esc(country)} &middot; {_esc(independence)}"
    if independence:
        return _esc(independence)
    if country:
        return f"{_esc(country)} &middot; not yet categorized"
    return "not yet categorized"


def _slugify(value: str) -> str:
    """Lower, ASCII-only, hyphenated. Used for outlet anchor IDs only."""
    out = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return out or "outlet"


def build_sources_section(tp: dict) -> str:
    """Two-level Sources section grouped by outlet.

    Level 1: ``<details>`` per outlet (collapsed by default) with
    ``<summary>`` showing outlet name, Country &middot;
    editorial_independence (or "not yet categorized" fallback), and the
    source count. The summary stays visible when collapsed, so source
    presence and the per-outlet count remain discoverable; only the
    per-source detail list is hidden until the reader expands it.

    Level 2: ``<ol>`` of per-source ``<li id="src-NNN">`` entries with
    headline link, country/language/date metadata, summary, optional
    italic ``bias_note`` line, and an inline actors-refs list whose
    names anchor into the Actors-section.

    Outlet sorting is alphabetical by ``outlet`` field.
    """
    sources = tp.get("sources") or []
    if not sources:
        return ""

    # Build the canonical-actor lookup. ``tp["actors"]`` carries
    # ``canonical_actors`` post Phase 2 — the alias-resolved consumer
    # view. Source-level actors_quoted entries may reference an actor
    # under a name variant that isn't the canonical name (e.g. a source
    # cites "Russia's Defense Ministry" while the canonical entry is
    # "Russian Defense Ministry"). Resolve those via the alias mapping
    # so the rendered link text shows the canonical name and the anchor
    # target points at the canonical actor's `actor-NNN` ID.
    canonical_by_name: dict[str, dict] = {}
    canonical_by_id: dict[str, dict] = {}
    for actor in tp.get("actors") or []:
        if isinstance(actor, dict):
            aid = actor.get("id")
            name = actor.get("name")
            if isinstance(aid, str) and aid:
                canonical_by_id[aid] = actor
            if isinstance(name, str) and name:
                canonical_by_name[name] = actor

    # Alias mapping: source-side variant name → canonical actor entry.
    alias_to_canonical: dict[str, dict] = {}
    for entry in tp.get("actor_alias_mapping") or []:
        if not isinstance(entry, dict):
            continue
        alias_name = entry.get("alias_name")
        canonical_id = entry.get("canonical_id")
        if not isinstance(alias_name, str) or not alias_name:
            continue
        if not isinstance(canonical_id, str) or not canonical_id:
            continue
        canonical_actor = canonical_by_id.get(canonical_id)
        if canonical_actor is not None:
            alias_to_canonical[alias_name] = canonical_actor

    # Combined lookup: try canonical names first, then alias names.
    actors_by_name: dict[str, dict] = dict(canonical_by_name)
    for alias_name, canonical_actor in alias_to_canonical.items():
        actors_by_name.setdefault(alias_name, canonical_actor)

    # source_id → list of (actor, first-matching-quote) tuples. Drives
    # the per-source third-level disclosable block. Each actor appears
    # at most once per source — the first quote whose source_id matches
    # wins. Quotes with neither `position` nor `verbatim` are filtered
    # at render time (see the "usable" check below).
    source_to_quote_entries: dict[str, list[tuple[dict, dict]]] = {}
    for actor in tp.get("actors") or []:
        if not isinstance(actor, dict):
            continue
        seen_sids_for_actor: set[str] = set()
        for q in actor.get("quotes") or []:
            if not isinstance(q, dict):
                continue
            sid_q = q.get("source_id")
            if not isinstance(sid_q, str) or not sid_q:
                continue
            if sid_q in seen_sids_for_actor:
                continue
            seen_sids_for_actor.add(sid_q)
            source_to_quote_entries.setdefault(sid_q, []).append((actor, q))

    by_outlet: dict[str, list[dict]] = {}
    for s in sources:
        if not isinstance(s, dict):
            continue
        outlet = s.get("outlet") or "(unknown outlet)"
        by_outlet.setdefault(outlet, []).append(s)

    n_outlets = len(by_outlet)
    n_languages = len({
        s.get("language") for s in sources
        if isinstance(s, dict) and s.get("language")
    })
    if RL.get_lang() == "de":
        _q = "Quelle" if len(sources) == 1 else "Quellen"
        _m = "Medium" if n_outlets == 1 else "Medien"
        _s = "Sprache" if n_languages == 1 else "Sprachen"
        meta_line = (
            f'{len(sources)} {_q} aus {n_outlets} {_m} in {n_languages} {_s}.'
        )
    else:
        meta_line = (
            f'{len(sources)} source{"" if len(sources) == 1 else "s"} '
            f'from {n_outlets} outlet{"" if n_outlets == 1 else "s"} '
            f'across {n_languages} language{"" if n_languages == 1 else "s"}.'
        )

    blocks: list[str] = []
    for outlet in sorted(by_outlet.keys(), key=str.lower):
        entries = by_outlet[outlet]
        n = len(entries)
        outlet_meta = _outlet_meta_line(outlet, entries[0])
        slug = _slugify(outlet)

        items: list[str] = []
        for s in entries:
            sid = s.get("id", "")
            num = sid.replace("src-", "").lstrip("0") or "0"
            url = s.get("url", "")
            title = s.get("title", "")
            if url:
                headline_html = (
                    f'<a class="source-headline" href="{_esc(url)}" '
                    f'target="_blank" rel="noopener">{_esc(title)}</a>'
                )
            else:
                headline_html = f'<span class="source-headline">{_esc(title)}</span>'

            meta_parts: list[str] = []
            for field in ("country", "language", "estimated_date"):
                value = s.get(field)
                if isinstance(value, str) and value:
                    meta_parts.append(f'<span>{_esc(value)}</span>')
            meta_html = " &middot; ".join(meta_parts)

            summary_text = s.get("summary") or ""
            summary_html = (
                f'<p class="source-summary">{_esc(summary_text)}</p>'
                if summary_text else ""
            )

            bias_note = s.get("bias_note")
            bias_note_html = ""
            if isinstance(bias_note, str) and bias_note:
                bias_note_html = (
                    f'<p class="source-bias-note">'
                    f'<em>{_esc(bias_note)}</em></p>'
                )

            actor_refs_html = ""
            actor_links: list[str] = []
            seen_aids: set[str] = set()
            for entry in s.get("actors_quoted") or []:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                if not isinstance(name, str) or not name:
                    continue
                canonical = actors_by_name.get(name)
                if canonical is None:
                    # Source actor with no canonical match — neither a
                    # direct hit on canonical_actors[].name nor an
                    # entry in actor_alias_mapping[]. Common case: A2
                    # type=media filter dropped the actor before the
                    # resolver ran. Skip silently.
                    continue
                aid = canonical.get("id", "")
                # Dedup by canonical id: multiple quotes from the same
                # actor in this source's actors_quoted[] collapse to one
                # link. Preserves order of first appearance. Name
                # variants ("Trump" vs "Donald Trump") that resolve to
                # the same canonical actor collapse as well.
                if aid in seen_aids:
                    continue
                seen_aids.add(aid)
                canonical_name = canonical.get("name") or name
                actor_links.append(
                    f'<a href="#{_esc(aid)}">{_esc(canonical_name)}</a>'
                )
            if actor_links:
                actor_refs_html = (
                    f'<div class="source-actors-refs">'
                    f'{RL.L("ui", "actors_quoted", "Actors quoted:")} {", ".join(actor_links)}'
                    f'</div>'
                )

            # Third-level disclosable block: per-actor quote details.
            # For each actor with a usable quote (position OR verbatim)
            # whose source_id matches this source, emit one entry with
            # the actor anchor, role, position summary, optional
            # verbatim, and a source-language tag when language != en.
            # Omit the block entirely when no entry is usable.
            quote_block_html = ""
            quote_entries = source_to_quote_entries.get(sid, [])
            usable_entries = [
                (qa, qq) for qa, qq in quote_entries
                if (qq.get("position") or qq.get("verbatim"))
            ]
            if usable_entries:
                source_lang = s.get("language")
                lang_tag = ""
                if isinstance(source_lang, str) and source_lang and source_lang != "en":
                    lang_tag = (
                        f' <code class="source-quote-lang">'
                        f'{_esc(source_lang)}</code>'
                    )
                entry_items: list[str] = []
                for qa, qq in usable_entries:
                    aid_q = qa.get("id", "")
                    actor_name = _esc(qa.get("name", ""))
                    actor_role = _esc(qa.get("role", ""))
                    name_html = (
                        f'<a href="#{_esc(aid_q)}">{actor_name}</a>'
                        if aid_q else actor_name
                    )
                    position = _esc(qq.get("position") or "")
                    position_html = (
                        f'<p class="source-quote-position">{position}</p>'
                        if position else ""
                    )
                    verbatim = qq.get("verbatim")
                    verbatim_html = ""
                    if isinstance(verbatim, str) and verbatim:
                        verbatim_html = (
                            f'<p class="source-quote-verbatim">'
                            f'<em>&ldquo;{_esc(verbatim)}&rdquo;</em>'
                            f'{lang_tag}</p>'
                        )
                    role_html = (
                        f' <span class="actor-role">{actor_role}</span>'
                        if actor_role else ""
                    )
                    entry_items.append(
                        f'<li class="source-quote-entry">'
                        f'<strong>{name_html}</strong>{role_html}'
                        f'{position_html}{verbatim_html}'
                        f'</li>'
                    )
                quote_block_html = (
                    '  <details class="source-quotes">\n'
                    f'    <summary>{RL.L("ui", "quote_details", "Quote details")}</summary>\n'
                    '    <ul class="source-quote-list">'
                    f'{"".join(entry_items)}</ul>\n'
                    '  </details>\n'
                )

            items.append(
                f'<li id="{_esc(sid)}" class="source">\n'
                f'  <div class="source-header">'
                f'<span class="source-id">[{num}]</span> {headline_html}'
                f'</div>\n'
                + (f'  <div class="source-meta">{meta_html}</div>\n' if meta_html else "")
                + f'  {summary_html}\n'
                + (f'  {bias_note_html}\n' if bias_note_html else "")
                + (f'  {actor_refs_html}\n' if actor_refs_html else "")
                + quote_block_html
                + '</li>\n'
            )

        blocks.append(
            f'<details class="outlet-block" id="outlet-{_esc(slug)}">\n'
            f'<summary>'
            f'<strong>{_esc(outlet)}</strong> '
            f'<span class="outlet-meta">{outlet_meta}</span> '
            f'<span class="outlet-source-count">'
            f'{RL.count_noun(n, "sources", str(n) + " source" + ("" if n == 1 else "s"))}'
            f'</span>'
            f'</summary>\n'
            f'<ol class="source-list">\n{"".join(items)}</ol>\n'
            f'</details>\n'
        )

    return (
        f'<section id="sources-section" class="sources">\n'
        f'<h2>{RL.L("section_heading", "Sources", "Sources")}</h2>\n'
        f'<p class="sources-meta">{meta_line}</p>\n'
        f'<div class="sources-by-outlet">\n{"".join(blocks)}</div>\n'
        f'</section>\n'
    )


# Back-compat alias — legacy callers (and tests) may still import the
# old name. Both point at the same restructured builder.
build_sources_table = build_sources_section


def build_transparency(tp: dict) -> str:
    t = tp.get("transparency", {})
    if not t:
        return ""

    parts = [f'<div class="transparency">\n<h2>{RL.L("section_heading", "Transparency Trail", "Transparency Trail")}</h2>\n<dl>\n']

    # selection_reason is the one reader-facing editorial field in the transparency trail
    # that is translated (the rest — QA corrections, removed sources — stay English by
    # design). The German is spliced into metadata.selection_reason (its de-JSON path);
    # transparency.selection_reason is the untranslated denormalized copy the English page
    # reads. On the German page prefer the German, falling back to the transparency copy.
    sel = t.get("selection_reason")
    if RL.get_lang() == "de":
        sel = tp.get("metadata", {}).get("selection_reason") or sel
    if sel:
        parts.append(f'<dt>{RL.L("ui", "selection_reason", "Selection Reason")}</dt><dd>{_esc(sel)}</dd>\n')

    corrections = t.get("qa_corrections", [])
    problems = t.get("qa_problems_found", [])
    if corrections:
        applied_count = sum(
            1 for c in corrections
            if isinstance(c, dict) and c.get("correction_needed", False)
        )
        retracted_count = len(corrections) - applied_count

        items = []
        for i, c in enumerate(corrections):
            if isinstance(c, dict):
                text = c.get("proposed_correction", "")
                applied = c.get("correction_needed", False)
            else:
                text = str(c)
                applied = True
            tag = "applied" if applied else "retracted"
            problem = problems[i] if i < len(problems) and isinstance(problems[i], dict) else {}
            ptype = problem.get("problem", "")
            excerpt = problem.get("article_excerpt", "")
            explanation = problem.get("explanation", "")
            tag_html = f'<span class="qa-tag tag-{tag}">{RL.L("ui", f"qa_{tag}", tag)}</span>'
            if ptype or excerpt or explanation:
                detail_bits = []
                if ptype:
                    detail_bits.append(
                        f'<span class="qa-problem-type">{_esc(ptype)}</span>'
                    )
                if excerpt:
                    detail_bits.append(
                        f'<blockquote class="qa-excerpt">{_esc(excerpt)}'
                        f'</blockquote>'
                    )
                if explanation:
                    detail_bits.append(
                        f'<p class="qa-explanation">{_esc(explanation)}</p>'
                    )
                items.append(
                    f'<li><details>'
                    f'<summary>{tag_html} {_esc(text)}</summary>'
                    f'<div class="qa-detail">{"".join(detail_bits)}</div>'
                    f'</details></li>'
                )
            else:
                items.append(f'<li>{tag_html} {_esc(text)}</li>')

        # Outer collapsible wrapping the per-correction list. Default
        # closed so the Transparency-Trail stays scannable; readers
        # expand to see excerpt and explanation per correction.
        outer_summary = (
            f'{RL.L("ui", "qa_corrections", "QA Corrections")} &mdash; '
            f'<strong>{applied_count} {RL.L("ui", "qa_applied", "applied")} '
            f'&middot; {retracted_count} {RL.L("ui", "qa_retracted", "retracted")}</strong>'
        )
        parts.append(
            f'<dt>{RL.L("ui", "qa_corrections", "QA Corrections")}</dt><dd>'
            f'<details class="qa-corrections-wrapper">'
            f'<summary>{outer_summary}</summary>'
            f'<ul class="qa-corrections">{"".join(items)}</ul>'
            f'</details></dd>\n'
        )

    dropped_sources = [
        d for d in (t.get("dropped_sources") or []) if isinstance(d, dict)
    ]
    dropped_clusters = [
        d for d in (t.get("dropped_clusters") or []) if isinstance(d, dict)
    ]
    if dropped_sources or dropped_clusters:
        parts.append(_dropped_block(dropped_sources, dropped_clusters))

    run = t.get("pipeline_run", {})
    if run:
        parts.append(
            f'<dt class="pipeline-run">{RL.L("ui", "pipeline_run", "Pipeline Run")}</dt>'
            f'<dd class="pipeline-run">{_esc(run.get("run_id", ""))} &middot; {_esc(run.get("date", ""))}</dd>\n'
        )

    parts.append('</dl>\n</div>\n')
    return "".join(parts)


def _dropped_block(
    dropped_sources: list[dict], dropped_clusters: list[dict]
) -> str:
    """Render the strict-drop collapsible inside the Transparency Trail.

    Surfaces which sources / clusters `prune_unused_sources_and_clusters`
    removed because no downstream consumer cited them. Default closed —
    expanding it lists per-entry detail (id, outlet, summary snippet for
    sources; id, position_label for clusters).
    """
    n_src = len(dropped_sources)
    n_cls = len(dropped_clusters)
    summary_bits: list[str] = []
    if n_src:
        summary_bits.append(
            f'{RL.count_noun(n_src, "sources", str(n_src) + " source" + ("s" if n_src != 1 else ""))}'
            f' {RL.L("ui", "dropped_word", "dropped")}'
        )
    if n_cls:
        summary_bits.append(
            f'{RL.count_noun(n_cls, "clusters", str(n_cls) + " cluster" + ("s" if n_cls != 1 else ""))}'
            f' {RL.L("ui", "dropped_word", "dropped")}'
        )
    summary = " &middot; ".join(summary_bits)

    body_parts: list[str] = []
    if dropped_sources:
        items = []
        for d in dropped_sources:
            sid = _esc(d.get("id", ""))
            outlet = _esc(d.get("outlet", ""))
            summary_snippet = _esc(d.get("summary", ""))
            items.append(
                f'<li><span class="dropped-id">{sid}</span> '
                f'<span class="dropped-outlet">{outlet}</span>'
                f'{f" &mdash; {summary_snippet}" if summary_snippet else ""}'
                f'</li>'
            )
        body_parts.append(
            f'<p class="dropped-section-label">{RL.L("ui", "dropped_sources_label", "Sources")}</p>'
            f'<ul class="dropped-list">{"".join(items)}</ul>'
        )
    if dropped_clusters:
        items = []
        for d in dropped_clusters:
            cid = _esc(d.get("id", ""))
            label = _esc(d.get("position_label", ""))
            items.append(
                f'<li><span class="dropped-id">{cid}</span> '
                f'<span class="dropped-label">{label}</span></li>'
            )
        body_parts.append(
            f'<p class="dropped-section-label">{RL.L("ui", "dropped_clusters_label", "Clusters")}</p>'
            f'<ul class="dropped-list">{"".join(items)}</ul>'
        )

    return (
        f'<dt>{RL.L("ui", "strict_drop_pruning", "Strict-drop Pruning")}</dt>'
        '<dd><details class="dropped-details">'
        f'<summary>{summary}</summary>'
        '<div class="dropped-detail">'
        f'{"".join(body_parts)}'
        '</div>'
        '</details></dd>\n'
    )


def build_glossary() -> str:
    """Build a static tag reference glossary. Same content for every TP."""
    def _gb(tag: str, color: str) -> str:
        return (
            f'<span class="badge" style="background:{color}15;color:{color};'
            f'border:1px solid {color}40">{tag}</span>'
        )

    h3 = ('font-family: var(--font-sans); font-size: 0.9rem; font-weight: 700; '
          'margin-top: 1rem; margin-bottom: 0.5rem; text-transform: uppercase; '
          'letter-spacing: 0.05em')

    # (enum_key, badge_color, English definition). English is the source of truth; the
    # German term + definition are looked up in config/de_render_labels.json.
    divergence = [
        ("factual", "#9f1239", "Sources disagree on a verifiable fact: a date, number, name, or whether something happened."),
        ("framing", "#7c3aed", "Sources describe the same event using different language or implied meaning. Example: one outlet calls a payment &ldquo;compensation,&rdquo; another calls it &ldquo;sanctions relief.&rdquo;"),
        ("omission", "#ca8a04", "One or more sources report something that other sources leave out entirely."),
        ("emphasis", "#0369a1", "Sources cover the same event but give different aspects different weight or prominence. Example: one outlet leads with casualty figures; another treats them as a footnote to the political negotiations."),
    ]
    bias = [
        ("evaluative_adjective", "#ca8a04", "A descriptive word that signals the writer&rsquo;s judgment rather than a neutral fact. Examples: &ldquo;staggering,&rdquo; &ldquo;sharp,&rdquo; &ldquo;dramatic.&rdquo;"),
        ("intensifier", "#0369a1", "A word that amplifies a statement without adding information. Examples: &ldquo;very,&rdquo; &ldquo;extremely,&rdquo; &ldquo;deeply.&rdquo;"),
        ("loaded_term", "#9f1239", "Vocabulary carrying strong political or emotional connotations that a more neutral word would avoid. Examples: &ldquo;regime&rdquo; vs. &ldquo;government,&rdquo; &ldquo;crackdown&rdquo; vs. &ldquo;enforcement.&rdquo;"),
        ("hedging", "#64748b", "Phrases that soften or obscure a claim, making attribution less clear. Examples: &ldquo;some say,&rdquo; &ldquo;allegedly,&rdquo; &ldquo;reportedly.&rdquo;"),
    ]
    stakeholder = [
        ("academia", "Researchers, professors, think tanks, and university-based experts."),
        ("affected_community", "People directly impacted by the events themselves &mdash; civilians, displaced persons, local populations. Voices from within the group, not their spokespersons."),
        ("civil_society", "Non-state organizations representing collective interests (NGOs, human rights groups, trade unions, religious bodies)."),
        ("government", "Executive branch officials, ministries, heads of state, and their spokespersons."),
        ("industry", "Private companies, trade associations, and commercial actors."),
        ("international_org", "Multilateral bodies and their representatives (UN agencies, IMF, IAEA, Red Cross, regional alliances)."),
        ("judiciary", "Judges, courts, prosecutors, and legal bodies acting in their official capacity."),
        ("legislature", "Parliament, Congress, or equivalent body. Kept separate from &ldquo;government&rdquo; because legislatures often hold positions that differ from their own executive branch."),
        ("media", "Journalists, editorial boards, and outlets quoted for their position or analysis, not as sources of factual reporting."),
        ("military", "Armed forces personnel, commanders, and defense ministries."),
    ]

    parts = [
        '<details class="glossary" style="margin-top: 2rem; border-top: 3px solid #000; '
        'padding-top: 1rem">\n'
        '<summary style="font-family: var(--font-mono); font-size: 0.8rem; '
        'color: var(--color-text-subtle); cursor: pointer; letter-spacing: 0.05em; '
        'text-transform: uppercase; padding: 0.5rem 0">'
        f'{RL.L("ui", "about_labels_summary", "About these labels")}</summary>\n'
        '<div style="margin-top: 0.75rem; font-family: var(--font-mono); '
        'font-size: 0.8rem; color: var(--color-text-secondary); line-height: 1.6">\n'
        '<p style="margin-bottom: 1rem; font-style: italic">'
        f'{RL.L("ui", "about_labels_intro", "Not every tag needs a definition &mdash; those listed below cover the full vocabulary used across the dossier.")}</p>\n'
    ]

    def _section(heading_en, dl_style, rows, term_cat, build_term):
        out = [f'<h3 style="{h3}">{RL.L("section_heading", heading_en, heading_en)}</h3>\n',
               f'<dl style="{dl_style}">\n']
        for row in rows:
            out.append(build_term(row))
            key, en_def = row[0], row[-1]
            out.append(f'<dd style="margin-left: 0">{RL.Ldef(term_cat, key, en_def)}</dd>\n')
        out.append('</dl>\n')
        return "".join(out)

    parts.append(_section(
        "Divergence types", "margin-bottom: 1rem", divergence, "divergence_type",
        lambda r: f'<dt style="margin-top: 0.5rem">{_gb(RL.L("divergence_type", r[0], r[0]), r[1])}</dt>'))
    parts.append(_section(
        "Bias issues", "margin-bottom: 1rem", bias, "bias_issue",
        lambda r: f'<dt style="margin-top: 0.5rem">{_gb(RL.L("bias_issue", r[0], r[0]), r[1])}</dt>'))
    parts.append(_section(
        "Stakeholder types", "margin-bottom: 0", stakeholder, "actor_type",
        lambda r: f'<dt style="font-weight: 700; margin-top: 0.5rem">{RL.L("actor_type", r[0], r[0])}</dt>'))

    parts.append('</div>\n')
    parts.append('</details>\n')
    return "".join(parts)


def build_footer() -> str:
    return (
        '<footer>\n'
        '<div class="footer-text">\n'
        # Brand furniture — stays ENGLISH on both EN and DE pages (operator decision;
        # not routed through the DE label lookup).
        '<p>Generated by <a href="https://github.com/deniz-schwenk/independent-wire">Independent Wire</a></p>\n'
        '<p>This content was produced by AI agents</p>\n'
        '<p>AGPL-3.0 &mdash; Because transparency is not a feature, it is a promise</p>\n'
        '<p><a href="/feed.xml">RSS Feed</a></p>\n'
        '</div>\n'
        f'<div class="footer-mark" aria-label="Independent Wire">{IW_SMALL_LIGHT_SVG}</div>\n'
        '</footer>\n'
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def render(tp: dict, lang: str = "en", lang_hrefs: dict | None = None) -> str:
    """Render a Topic Package dict to a self-contained HTML string.

    lang='de' renders the German page: German prose is already spliced into ``tp`` (by the
    German publisher) and every controlled-vocabulary label is looked up in
    config/de_render_labels.json. English (the default) is unchanged. ``lang_hrefs`` sets
    the DE/EN switch targets; the default assumes the file is served from site/reports/
    (en) or site/de/reports/ (de)."""
    RL.set_lang(lang)
    css = build_css()
    headline = tp.get("article", {}).get("headline", "Independent Wire")
    tp_id = tp.get("id", "")
    canonical = f"{SITE_BASE}/reports/{tp_id}.html"

    if lang_hrefs is None:
        if lang == "de":
            lang_hrefs = {"en": f"../../reports/{tp_id}.html", "de": f"{tp_id}.html"}
        else:
            lang_hrefs = {"en": f"{tp_id}.html", "de": f"../de/reports/{tp_id}.html"}
    switch = RL.build_lang_switch(lang, lang_hrefs["en"], lang_hrefs["de"])
    all_dossiers = RL.L("ui", "back_nav_all_dossiers", "ALL DOSSIERS")

    top_bar = (
        '<div class="top-bar">\n'
        f'<nav class="back-nav"><a href="../index.html">&larr; {all_dossiers}</a></nav>\n'
        '<div class="top-bar-right">\n'
        f'{switch}'
        f'<button class="share-btn" data-url="{_esc(canonical)}" '
        f'data-title="{_esc(headline)}">Share</button>\n'
        '</div>\n'
        '</div>\n'
    )
    back_nav_bottom = (f'<nav class="back-nav back-nav-bottom">'
                       f'<a href="../index.html">&larr; {all_dossiers}</a></nav>\n')

    sections = [
        top_bar,
        build_header(tp),
        build_follow_up_ref(tp),
        build_meta_bar(tp),
        build_source_map(tp),
        build_reader_note(tp),
        build_article_body(tp),
        build_perspectives(tp),
        build_mentioned_actors_section(tp),
        build_actors_section(tp),
        build_divergences(tp),
        build_bias_card(tp),
        # Consolidator-output section — voices + topics missing.
        # Positioned directly before Sources per architectural intent
        # (post 3f59ab9 Consolidator refactor).
        build_what_is_missing_section(tp),
        build_sources_section(tp),
        build_transparency(tp),
        build_glossary(),
        back_nav_bottom,
        RL.support_block(),
        build_footer(),
    ]

    body = "\n".join(s for s in sections if s)

    html_out = (
        f'<!DOCTYPE html>\n'
        f'<html lang="{RL.html_lang()}">\n'
        f'<head>\n'
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">\n'
        f'<link rel="apple-touch-icon" sizes="180x180" href="/assets/apple-touch-icon.png">\n'
        f'<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Space+Grotesk:wght@400;600;700;800&display=swap" rel="stylesheet">\n'
        f'<title>{_esc(headline)}</title>\n'
        f'{build_meta_tags(tp)}'
        f'<style>\n{css}</style>\n'
        f'</head>\n'
        f'<body>\n'
        f'<div class="container">\n'
        f'{body}'
        f'</div>\n'
        f'{build_share_script()}'
        f'</body>\n'
        f'</html>\n'
    )
    RL.set_lang("en")   # reset module label-context so the next render starts clean
    return html_out


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
