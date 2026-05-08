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
.cluster-counts {
  font-family: var(--font-mono); font-size: 0.75rem;
  color: var(--color-text-subtle); margin: 0.75rem 0 0;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.cluster-counts a { color: inherit; text-decoration: underline; }
.cluster-counts a:hover { color: var(--color-text); }
.card:target { background: var(--color-bg-subtle, #f5f5f4); }

/* Actors section */
.actors h2 { margin-top: 2rem; }
.actors-meta {
  font-family: var(--font-mono); font-size: 0.85rem;
  color: var(--color-text-secondary); margin: 0 0 1rem;
}
#actors-show-all {
  font-family: var(--font-mono); font-size: 0.75rem;
  background: transparent; border: 1px solid #000; cursor: pointer;
  padding: 0.3rem 0.75rem; margin-bottom: 1rem;
  text-transform: uppercase; letter-spacing: 0.05em;
}
#actors-show-all:hover { background: #000; color: var(--color-bg); }
.actor-list { list-style: none; padding: 0; margin: 0; }
.actor {
  padding: 1rem 0; border-top: 1px solid var(--color-border-light);
}
.actor:first-child { border-top: 0; padding-top: 0; }
.actor[hidden] { display: none; }
.actor:target { background: var(--color-bg-subtle, #f5f5f4); }
.actor-header {
  font-family: var(--font-sans); font-size: 1rem; margin-bottom: 0.4rem;
}
.actor-header strong { font-weight: 700; }
.actor-role { color: var(--color-text-secondary); margin-left: 0.4rem; }
.actor-type {
  font-family: var(--font-mono); font-size: 0.7rem;
  color: var(--color-text-subtle); margin-left: 0.4rem;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.actor-position-line {
  font-family: var(--font-sans); font-size: 0.9rem; line-height: 1.55;
  color: var(--color-text-secondary); margin: 0.35rem 0 0;
}
.actor-position-line a { color: inherit; text-decoration: underline; }
.actor-verbatim { font-style: italic; }
.actor-no-cluster { color: var(--color-text-subtle); font-size: 0.85rem; }

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

/* Coverage gaps */
.coverage-gap {
  font-family: var(--font-sans); font-size: 0.9rem; color: var(--color-text-secondary); line-height: 1.55;
  padding: 0.5rem 0; border-bottom: 1px solid var(--color-border-light);
}

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
  .card-grid { grid-template-columns: 1fr; }
  .meta-bar { flex-wrap: wrap; }
  .meta-item { min-width: 70px; border-right: none; border-bottom: 1px solid #000; }
  .meta-item:last-child { border-bottom: none; }
  .meta-number { font-size: 1.2rem; }
  .sources-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .article-body { font-size: 1rem; }
  footer { flex-direction: column-reverse; align-items: flex-start; gap: 1rem; }
  footer .footer-mark { width: 64px; height: 64px; }
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
        f'Follow-up to: &ldquo;{prev_headline}&rdquo; ({formatted_date})\n'
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
            f'title="{_esc(country)}: {count} source{"s" if count != 1 else ""}">'
            f'{_esc(label)}</span>'
        )

    badges_html = "\n".join(active_badges)
    return (
        f'<h2>Source Distribution</h2>\n'
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


def build_perspectives(tp: dict) -> str:
    """Render Perspective V2 position_clusters. One cluster = one card.

    Cluster cards show the position label, a one-line summary, and a
    monospace counts row: ``{n_actors} · {n_sources} · {n_regions} ·
    {n_languages}``. The actor count is wrapped in ``<a
    href="#cluster-{id}">`` so a click filters the Actors-section to
    this cluster's members. Per-actor data is rendered in the
    Actors-section (see ``build_actors_section``), not inline.
    """
    clusters = tp.get("perspectives", {}).get("position_clusters", [])
    if not clusters:
        return ""
    cards = []
    for c in clusters:
        if not isinstance(c, dict):
            continue
        label = c.get("position_label", "")
        summary = c.get("position_summary", "")
        cluster_id = c.get("id", "")
        n_actors = int(c.get("n_actors", 0) or 0)
        n_sources = int(c.get("n_sources", 0) or 0)
        n_regions = int(c.get("n_regions", 0) or 0)
        n_languages = int(c.get("n_languages", 0) or 0)

        actors_label = _plural(n_actors, "actor")
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
            f'<span>{_plural(n_sources, "source")}</span>'
            f' &middot; '
            f'<span>{_plural(n_regions, "region")}</span>'
            f' &middot; '
            f'<span>{_plural(n_languages, "language")}</span>'
            f'</p>\n'
        )

        cards.append(
            f'<div class="card" id="{_esc(cluster_id)}">\n'
            f'  <div class="card-header"><span class="card-actor">{_esc(label)}</span></div>\n'
            f'  <div class="card-position">{_esc(summary)}</div>\n'
            f'  {counts_line}'
            f'</div>\n'
        )
    return f'<h2>Perspectives &mdash; Position Clusters</h2>\n<div class="card-grid">\n{"".join(cards)}</div>\n'


def build_actors_section(tp: dict) -> str:
    """First-class Actors-section: every actor in ``canonical_actors``
    (the alias-resolved consumer-facing list, surfaced under the
    top-level ``actors`` key) listed once, with cluster memberships and
    source attributions.

    Renders between Positions and Sources. Each ``<li>`` carries:
    - ``id="actor-NNN"`` — direct anchor target (CSS ``:target`` styles
      it on a ``#actor-NNN`` URL).
    - ``data-clusters="cluster-pc-001 cluster-pc-005"`` — space-separated
      list of cluster filter tags. The inline JS shim listens to
      ``hashchange``: when the URL fragment matches ``#cluster-...``,
      actors whose ``data-clusters`` does not include that token are
      hidden and a "Show all" button surfaces.

    Per cluster the actor belongs to, one position-line is rendered with:
    the cluster anchor, the actor's ``quotes[].position`` text for that
    cluster (filtered by ``source_id ∈ cluster.source_ids``), the
    optional ``verbatim`` quote in italics, and the source-id anchor.
    """
    actors = tp.get("actors") or []
    clusters = tp.get("perspectives", {}).get("position_clusters", []) or []

    # Build cluster-id → set(source_id) for filtering quotes per
    # actor-cluster pair. Also remember each cluster's index so we can
    # reference "Cluster N" in human-readable form.
    cluster_sources: dict[str, set[str]] = {}
    cluster_index: dict[str, int] = {}
    for i, c in enumerate(clusters, start=1):
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        cluster_sources[cid] = set(c.get("source_ids") or [])
        cluster_index[cid] = i

    # Reverse: actor-id → list of cluster-ids the actor belongs to,
    # preserving the cluster order in which the agent emitted them.
    actor_clusters: dict[str, list[str]] = {}
    for c in clusters:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        for aid in c.get("actor_ids") or []:
            if not isinstance(aid, str):
                continue
            actor_clusters.setdefault(aid, []).append(cid)

    def _position_line(actor: dict, cluster_id: str) -> str:
        cluster_label = f"Cluster {cluster_index.get(cluster_id, '?')}"
        cluster_anchor = (
            f'<a href="#{_esc(cluster_id)}">{_esc(cluster_label)}</a>'
        )
        # Pick the first quote whose source_id grounds this cluster.
        # Architect-neutral: a single position-line per cluster keeps
        # the actor card scannable; multi-source quotes fall through
        # to the §3.4 source-actor-refs layer.
        quotes = actor.get("quotes") or []
        chosen = None
        for q in quotes:
            if not isinstance(q, dict):
                continue
            sid = q.get("source_id")
            if isinstance(sid, str) and sid in cluster_sources.get(cluster_id, set()):
                chosen = q
                break
        if chosen is None:
            return f'<p class="actor-position-line">{cluster_anchor}</p>'
        position = _esc(chosen.get("position", "") or "")
        verbatim = chosen.get("verbatim")
        verbatim_html = ""
        if isinstance(verbatim, str) and verbatim:
            verbatim_html = (
                f' <em class="actor-verbatim">&ldquo;{_esc(verbatim)}&rdquo;</em>'
            )
        sid = chosen.get("source_id", "")
        src_anchor = (
            f' (<a href="#{_esc(sid)}">{_esc(sid)}</a>)' if sid else ""
        )
        return (
            f'<p class="actor-position-line">{cluster_anchor}: '
            f'{position}{verbatim_html}{src_anchor}</p>'
        )

    items: list[str] = []
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        aid = actor.get("id", "")
        name = _esc(actor.get("name", ""))
        role = _esc(actor.get("role", ""))
        atype = _esc(actor.get("type", ""))
        belongs = actor_clusters.get(aid, [])
        data_clusters = " ".join(f"cluster-{cid}" for cid in belongs)
        position_lines = "".join(_position_line(actor, cid) for cid in belongs)
        if not position_lines:
            position_lines = (
                '<p class="actor-position-line actor-no-cluster">'
                'Mentioned in sources, no clustered position.</p>'
            )

        anon_html = (
            ' <em class="actor-anonymous">(anonymous)</em>'
            if actor.get("is_anonymous") else ""
        )
        items.append(
            f'<li id="{_esc(aid)}" class="actor" data-clusters="{data_clusters}">\n'
            f'  <div class="actor-header">'
            f'<strong>{name}</strong> '
            f'<span class="actor-role">{role}</span>{anon_html} '
            f'<span class="actor-type">{atype}</span>'
            f'</div>\n'
            f'  <div class="actor-positions">{position_lines}</div>\n'
            f'</li>\n'
        )

    n = len(items)
    if n == 0:
        return (
            '<section id="actors-section" class="actors">\n'
            '<h2>Actors</h2>\n'
            '<p class="actors-meta">0 actors quoted across this topic.</p>\n'
            '</section>\n'
        )

    actors_meta = (
        f'<p class="actors-meta">{n} actor{"" if n == 1 else "s"} '
        f'quoted across this topic. Click a cluster card&rsquo;s actor '
        f'count above to filter, or jump to a specific actor.</p>\n'
    )

    js_shim = (
        '<script>\n'
        '(function() {\n'
        '  const list = document.querySelector(\'.actor-list\');\n'
        '  const showAll = document.getElementById(\'actors-show-all\');\n'
        '  if (!list || !showAll) return;\n'
        '  function applyFilter() {\n'
        '    const m = (window.location.hash || \'\').match(/^#cluster-(\\S+)$/);\n'
        '    if (!m) {\n'
        '      list.querySelectorAll(\'.actor\').forEach(li => { li.hidden = false; });\n'
        '      showAll.hidden = true;\n'
        '      return;\n'
        '    }\n'
        '    const target = \'cluster-\' + m[1];\n'
        '    list.querySelectorAll(\'.actor\').forEach(li => {\n'
        '      const tags = (li.dataset.clusters || \'\').split(/\\s+/);\n'
        '      li.hidden = !tags.includes(target);\n'
        '    });\n'
        '    showAll.hidden = false;\n'
        '  }\n'
        '  showAll.addEventListener(\'click\', () => {\n'
        '    history.pushState(\'\', document.title, window.location.pathname);\n'
        '    applyFilter();\n'
        '  });\n'
        '  window.addEventListener(\'hashchange\', applyFilter);\n'
        '  applyFilter();\n'
        '})();\n'
        '</script>\n'
    )

    return (
        '<section id="actors-section" class="actors">\n'
        '<h2>Actors</h2>\n'
        f'{actors_meta}'
        '<button id="actors-show-all" type="button" hidden>Show all actors</button>\n'
        f'<ol class="actor-list">\n{"".join(items)}</ol>\n'
        f'{js_shim}'
        '</section>\n'
    )


def build_missing_voices(tp: dict) -> str:
    """Render Perspective V2 missing_positions as a simple bulleted list."""
    missing = tp.get("perspectives", {}).get("missing_positions", [])
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
    findings = bias.get("language", [])
    by_language = bias.get("source", {}).get("by_language", {})
    framing = bias.get("framing", {})
    source = bias.get("source", {})

    parts = []
    parts.append('<h2>Bias Analysis</h2>\n')

    # Stat line — deterministic aggregates for the dossier.
    cluster_count = framing.get("cluster_count", 0)
    distinct_actors = framing.get("distinct_actor_count", 0)
    source_total = source.get("total", len(tp.get("sources", [])))
    lang_count = len(by_language)
    parts.append(
        '<p class="bias-stats">'
        f'<span><strong>{cluster_count}</strong> position clusters</span>'
        '<span class="sep">&middot;</span>'
        f'<span><strong>{distinct_actors}</strong> distinct actors</span>'
        '<span class="sep">&middot;</span>'
        f'<span><strong>{source_total}</strong> sources</span>'
        '<span class="sep">&middot;</span>'
        f'<span><strong>{lang_count}</strong> languages</span>'
        '</p>\n'
    )

    # Summary line — always visible. V2 schema has no severity field.
    if findings:
        parts.append(
            f'<p style="font-family:var(--font-mono);font-size:0.85rem;'
            f'color:var(--color-text-secondary);">'
            f'{len(findings)} language bias finding{"s" if len(findings) != 1 else ""}'
            f'</p>\n'
        )
    else:
        parts.append(
            f'<p style="font-family:var(--font-mono);font-size:0.85rem;'
            f'color:var(--color-text-secondary);">'
            f'No language bias findings</p>\n'
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
    gaps = (
        tp.get("bias_analysis", {})
          .get("selection", {})
          .get("coverage_gaps", [])
        or tp.get("gaps", [])
    )
    if not gaps:
        return ""
    items = "\n".join(f'<div class="coverage-gap">{_esc(g)}</div>' for g in gaps)
    return f'<h2>Coverage Gaps</h2>\n{items}\n'


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

    Level 1: ``<details open>`` per outlet with ``<summary>`` showing
    outlet name, Country &middot; editorial_independence (or "not yet
    categorized" fallback), and the source count.

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
                canonical_name = canonical.get("name") or name
                actor_links.append(
                    f'<a href="#{_esc(aid)}">{_esc(canonical_name)}</a>'
                )
            if actor_links:
                actor_refs_html = (
                    f'<div class="source-actors-refs">'
                    f'Actors quoted: {", ".join(actor_links)}'
                    f'</div>'
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
                + '</li>\n'
            )

        blocks.append(
            f'<details class="outlet-block" id="outlet-{_esc(slug)}" open>\n'
            f'<summary>'
            f'<strong>{_esc(outlet)}</strong> '
            f'<span class="outlet-meta">{outlet_meta}</span> '
            f'<span class="outlet-source-count">'
            f'{n} source{"" if n == 1 else "s"}'
            f'</span>'
            f'</summary>\n'
            f'<ol class="source-list">\n{"".join(items)}</ol>\n'
            f'</details>\n'
        )

    return (
        f'<section id="sources-section" class="sources">\n'
        f'<h2>Sources</h2>\n'
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

    parts = ['<div class="transparency">\n<h2>Transparency Trail</h2>\n<dl>\n']

    if t.get("selection_reason"):
        parts.append(f'<dt>Selection Reason</dt><dd>{_esc(t["selection_reason"])}</dd>\n')

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
            tag_html = f'<span class="qa-tag tag-{tag}">{tag}</span>'
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
            f'QA Corrections &mdash; <strong>{applied_count} applied '
            f'&middot; {retracted_count} retracted</strong>'
        )
        parts.append(
            f'<dt>QA Corrections</dt><dd>'
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
            f'<dt class="pipeline-run">Pipeline Run</dt>'
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
            f'{n_src} source{"s" if n_src != 1 else ""} dropped'
        )
    if n_cls:
        summary_bits.append(
            f'{n_cls} cluster{"s" if n_cls != 1 else ""} dropped'
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
            '<p class="dropped-section-label">Sources</p>'
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
            '<p class="dropped-section-label">Clusters</p>'
            f'<ul class="dropped-list">{"".join(items)}</ul>'
        )

    return (
        '<dt>Strict-drop Pruning</dt>'
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
        '<div class="footer-text">\n'
        '<p>Generated by <a href="https://github.com/deniz-schwenk/independent-wire">Independent Wire</a></p>\n'
        '<p>This content was produced by AI agents</p>\n'
        '<p>AGPL-3.0 &mdash; Because transparency is not a feature, it is a promise</p>\n'
        '<p><a href="../feed.xml">RSS Feed</a></p>\n'
        '</div>\n'
        f'<div class="footer-mark" aria-label="Independent Wire">{IW_SMALL_LIGHT_SVG}</div>\n'
        '</footer>\n'
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def render(tp: dict) -> str:
    """Render a Topic Package dict to a self-contained HTML string."""
    css = build_css()
    headline = tp.get("article", {}).get("headline", "Independent Wire")
    tp_id = tp.get("id", "")
    canonical = f"{SITE_BASE}/reports/{tp_id}.html"

    top_bar = (
        '<div class="top-bar">\n'
        '<nav class="back-nav"><a href="../index.html">&larr; ALL DOSSIERS</a></nav>\n'
        f'<button class="share-btn" data-url="{_esc(canonical)}" '
        f'data-title="{_esc(headline)}">Share</button>\n'
        '</div>\n'
    )
    back_nav_bottom = '<nav class="back-nav back-nav-bottom"><a href="../index.html">&larr; ALL DOSSIERS</a></nav>\n'

    sections = [
        top_bar,
        build_header(tp),
        build_follow_up_ref(tp),
        build_meta_bar(tp),
        build_source_map(tp),
        build_reader_note(tp),
        build_article_body(tp),
        build_perspectives(tp),
        build_actors_section(tp),
        build_missing_voices(tp),
        build_divergences(tp),
        build_bias_card(tp),
        build_coverage_gaps(tp),
        build_sources_section(tp),
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
