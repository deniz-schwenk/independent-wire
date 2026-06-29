#!/usr/bin/env python3
"""Independent Wire — Generate publication website from rendered Topic Packages."""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from scripts import render_labels as RL


ROOT = Path(__file__).resolve().parent.parent

# Canonical site base — drives og:url / og:image absolute links. Matches
# `site/CNAME`. Local previews are unaffected because relative asset
# paths in the body remain unchanged.
SITE_BASE = "https://independent-wire.org"
SITE_TITLE = "Independent Wire"
SITE_TAGLINE = "An independent newsroom — Open · Transparent · For everyone"

# Read the small IW brand-mark SVG once at module load and inline it
# into the footer. `<img src=...>` would render in an isolated browser
# context that doesn't inherit Google Fonts, so the IW glyph would fall
# back to system sans-serif. Inlining lets the SVG inherit Space Grotesk
# from the host document. The XML processing instruction is stripped
# because HTML5 doesn't accept PIs in the body.
IW_SMALL_LIGHT_SVG = re.sub(
    r"<\?xml[^?]*\?>\s*",
    "",
    (ROOT / "site" / "assets" / "iw-small-light.svg").read_text(encoding="utf-8"),
).strip()


def load_site_config() -> dict:
    """Load `config/site_config.json` if it exists. Returns ``{}`` when the
    file is missing — callers treat the absence as "no cutoff applied",
    preserving backwards compatibility for local dev runs."""
    config_path = ROOT / "config" / "site_config.json"
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def _date_from_tp_filename(path: Path) -> str | None:
    """Extract the YYYY-MM-DD date fragment from a `tp-YYYY-MM-DD-NNN.{json,html}`
    filename. Returns ``None`` for filenames that don't match the pattern."""
    parts = path.stem.split("-")
    if len(parts) >= 4 and parts[0] == "tp":
        date = "-".join(parts[1:4])
        try:
            datetime.strptime(date, "%Y-%m-%d")
            return date
        except ValueError:
            return None
    return None


def filter_jsons_by_cutoff(
    tp_jsons: list[Path], cutoff: str | None
) -> tuple[list[Path], list[Path]]:
    """Split ``tp_jsons`` into ``(kept, excluded)`` lists based on the
    publication cutoff date. ``kept`` are TPs whose embedded date is
    on-or-after ``cutoff``; ``excluded`` are everything earlier. With
    ``cutoff=None`` everything is kept (no filter)."""
    if not cutoff:
        return list(tp_jsons), []
    kept: list[Path] = []
    excluded: list[Path] = []
    for p in tp_jsons:
        date = _date_from_tp_filename(p)
        if date is not None and date < cutoff:
            excluded.append(p)
        else:
            kept.append(p)
    return kept, excluded


def remove_pre_cutoff_reports(reports_dir: Path, cutoff: str | None) -> int:
    """Remove ``tp-*.html`` files in ``reports_dir`` whose embedded date is
    before ``cutoff``. Returns the count of files removed. No-op when
    ``cutoff`` is ``None`` or no matching files exist."""
    if not cutoff or not reports_dir.is_dir():
        return 0
    removed = 0
    for p in reports_dir.glob("tp-*.html"):
        date = _date_from_tp_filename(p)
        if date is not None and date < cutoff:
            p.unlink()
            removed += 1
    return removed


def _format_date(date_str: str) -> str:
    """Format '2026-04-13' as 'April 13, 2026' (en) / '13. April 2026' (de).
    German months come from the label map, not the locale."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if RL.get_lang() == "de":
        return f"{dt.day}. {RL.month_name(dt.month, dt.strftime('%B'))} {dt.year}"
    return dt.strftime("%B %d, %Y").replace(" 0", " ")


def _rfc822_date(date_str: str) -> str:
    """Format '2026-04-13' as RFC 822 date for RSS."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return format_datetime(dt)


def find_latest_date_dir(output_dir: Path) -> str | None:
    """Find the latest date subdirectory under output_dir."""
    date_dirs = sorted(
        (d.name for d in output_dir.iterdir() if d.is_dir() and len(d.name) == 10),
        reverse=True,
    )
    return date_dirs[0] if date_dirs else None


def find_tp_files(output_dir: Path, date: str | None = None) -> list[Path]:
    """Find tp-*.json files for a specific date directory."""
    if date is None:
        date = find_latest_date_dir(output_dir)
        if date is None:
            return []
    date_dir = output_dir / date
    if not date_dir.is_dir():
        return []
    # Only include TPs whose ID matches the target date (skip strays from other runs)
    return sorted(f for f in date_dir.glob(f"tp-{date}-*.json"))


def ensure_html(json_path: Path, render_script: Path) -> Path | None:
    """Ensure a TP HTML file exists and is up to date. Returns None on failure.

    Renders the HTML if it doesn't exist, or if the JSON is newer than the
    HTML (e.g. after a ``--reuse`` partial run that rewrote the JSON but
    left the previous HTML on disk). mtime comparison is the same idiom
    Make uses for source-vs-derivative freshness checks.
    """
    html_path = json_path.with_suffix(".html")
    needs_render = (
        not html_path.exists()
        or json_path.stat().st_mtime > html_path.stat().st_mtime
    )
    if needs_render:
        if html_path.exists():
            print(f"  Re-rendering {json_path.name} (JSON newer than HTML)")
        else:
            print(f"  Rendering {json_path.name}...")
        result = subprocess.run(
            [sys.executable, str(render_script), str(json_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  WARNING: Failed to render {json_path.name}, skipping")
            return None
    return html_path


def extract_metadata(json_path: Path) -> dict:
    """Extract card metadata from a TP JSON file."""
    tp = json.loads(json_path.read_text(encoding="utf-8"))
    article = tp.get("article", {})
    bias = tp.get("bias_analysis", {})
    follow_up = tp.get("metadata", {}).get("follow_up")
    return {
        "id": tp["id"],
        "date": tp["metadata"]["date"],
        "headline": article.get("headline", ""),
        "subheadline": article.get("subheadline", ""),
        "summary": article.get("summary", ""),
        "word_count": article.get("word_count", len(article.get("body", "").split())),
        "sources_count": len(tp.get("sources", [])),
        "languages_count": len(bias.get("source", {}).get("by_language", {})),
        "stakeholders_count": (
            bias.get("framing", {}).get("distinct_actor_count", 0)
        ),
        "divergences_count": len(tp.get("divergences", [])),
        "html_filename": f"reports/{tp['id']}.html",
        "follow_up": follow_up,
    }


def resolve_follow_up_links(reports_dir: Path) -> None:
    """Scan HTML files in reports/ for FOLLOW_UP_LINK placeholders and resolve them."""
    import re
    pattern = re.compile(r"<!-- FOLLOW_UP_LINK:(tp-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{3}) -->")
    for html_path in reports_dir.glob("tp-*.html"):
        content = html_path.read_text(encoding="utf-8")
        def replace_link(m: re.Match) -> str:
            tp_id = m.group(1)
            link_path = reports_dir / f"{tp_id}.html"
            if link_path.exists():
                return f'<a href="{tp_id}.html" style="font-family: \'Space Mono\', monospace; color: #000;">&rarr; Read previous</a>'
            return ""  # Remove placeholder if target doesn't exist
        new_content = pattern.sub(replace_link, content)
        if new_content != content:
            html_path.write_text(new_content, encoding="utf-8")
            print(f"  Resolved follow-up link in {html_path.name}")


def _esc(text: str) -> str:
    """HTML-escape text."""
    import html
    return html.escape(str(text)) if text else ""


# ---------------------------------------------------------------------------
# index.html
# ---------------------------------------------------------------------------

def build_card(meta: dict, index: int, reports_dir: Path | None = None) -> str:
    """Build an HTML card for one Topic Package.

    When ``reports_dir`` is provided, follow-up references whose target
    HTML does not exist in ``reports_dir`` are rendered as plain text
    rather than as a hyperlink. This avoids dead links on the index when
    the cutoff filter has removed the previous-coverage file (e.g. a
    May-7 follow-up to a pre-cutoff May-5 TP). Callers that don't need
    the existence check can omit ``reports_dir``; the link is rendered
    unconditionally in that case.
    """
    topic_num = f"TOPIC {index:02d} / {meta['id']}"
    follow_up_hint = ""
    follow_up = meta.get("follow_up")
    if follow_up:
        prev_headline = _esc(follow_up.get("previous_headline", ""))
        prev_date = follow_up.get("previous_date", "")
        prev_tp_id = follow_up.get("previous_tp_id", "")
        formatted_date = _format_date(prev_date) if prev_date else ""
        prev_href = f"reports/{prev_tp_id}.html" if prev_tp_id else "#"
        target_exists = True
        if reports_dir is not None and prev_tp_id:
            target_exists = (reports_dir / f"{prev_tp_id}.html").exists()
        if target_exists:
            headline_html = (
                f'<a href="{_esc(prev_href)}" class="follow-up-link">'
                f'&ldquo;{prev_headline}&rdquo;</a>'
            )
        else:
            headline_html = (
                f'<span class="follow-up-link">&ldquo;{prev_headline}&rdquo;</span>'
            )
        follow_up_hint = (
            f'  <div class="follow-up-hint">'
            f'<span class="follow-up-label">{RL.L("ui", "follow_up_to", "Follow-up to:")}</span> '
            f'{headline_html} '
            f'<span class="follow-up-date">({formatted_date})</span>'
            f'</div>\n'
        )
    return f"""<article class="tp-card">
  <span class="topic-id">{_esc(topic_num)}</span>
  <h2><a href="{_esc(meta['html_filename'])}">{_esc(meta['headline'])}</a></h2>
  <p class="subheadline">{_esc(meta['subheadline'])}</p>
  <p class="summary">{_esc(meta['summary'])}</p>
{follow_up_hint}  <div class="meta-bar">
    <div class="meta-item"><span class="meta-number">{meta['sources_count']}</span><span class="meta-label">{RL.L("meta_bar", "Sources", "Sources")}</span></div>
    <div class="meta-item"><span class="meta-number">{meta['languages_count']}</span><span class="meta-label">{RL.L("meta_bar", "Languages", "Languages")}</span></div>
    <div class="meta-item"><span class="meta-number">{meta['stakeholders_count']}</span><span class="meta-label">{RL.L("meta_bar", "Stakeholders", "Stakeholders")}</span></div>
    <div class="meta-item"><span class="meta-number">{meta['divergences_count']}</span><span class="meta-label">{RL.L("meta_bar", "Divergences", "Divergences")}</span></div>
  </div>
  <div class="card-footer"><span>{meta['word_count']:,} {RL.L("ui", "words", "words")} &middot; {_format_date(meta['date'])}</span><a href="{_esc(meta['html_filename'])}" class="read-link">&rarr; {RL.L("ui", "read_dossier", "READ DOSSIER")}</a></div>
</article>"""


def _short_id(tp_id: str) -> str:
    """Return the ``MM-DD-NNN`` tail of a ``tp-YYYY-MM-DD-NNN`` id."""
    parts = tp_id.split("-")
    return "-".join(parts[2:]) if len(parts) >= 5 else tp_id


def _sort_tier(entries: list[dict]) -> list[dict]:
    """Newest-first ordering within a tier: date descending, id ascending
    within the same date."""
    ordered = sorted(entries, key=lambda m: m["id"])        # id asc
    ordered.sort(key=lambda m: m["date"], reverse=True)      # date desc (stable)
    return ordered


def _bucket_bar(label: str, count: int, *, light: bool = False) -> str:
    """Tier header bar: left = label, right = dossier count. Generalises the
    original per-date ``.date-bar`` into a reusable bucket header.

    ``light=True`` renders the white ARCHIVE variant (white background, black
    label, 3px black top-rule) so the ARCHIVE header does not abut the black
    month-accordion summaries beneath it. Black is the default for the
    TODAY / YESTERDAY / EARLIER bars.
    """
    plural = "S" if count != 1 else ""
    cls = "bucket-bar bucket-bar-light" if light else "bucket-bar"
    return (
        f'<div class="{cls}"><span>{_esc(label)}</span>'
        f'<span>{RL.count_noun(count, "dossiers", str(count) + " DOSSIER" + plural)}</span></div>\n'
    )


def build_card_mid(meta: dict, reports_dir: Path | None = None) -> str:
    """TIER 1 (YESTERDAY) — mid card: id line, headline (h3), two-line
    subheadline, and a four-metric transparency footer (Sources / Languages /
    Stakeholders / Divergences). No summary, no stat meta-bar, no follow-up hint.

    ``reports_dir`` is accepted for signature symmetry with ``build_card``; mid
    cards carry no follow-up hint, so there is nothing to degrade and it is
    currently unused.
    """
    return f"""<article class="tp-card-mid">
  <span class="topic-id">{_esc(meta['id'])}</span>
  <h3><a href="{_esc(meta['html_filename'])}">{_esc(meta['headline'])}</a></h3>
  <p class="subheadline-mid">{_esc(meta['subheadline'])}</p>
  <div class="card-footer"><span class="mid-stats"><b>{meta['sources_count']}</b> {RL.L("meta_bar", "Sources", "Sources")} &middot; <b>{meta['languages_count']}</b> {RL.L("meta_bar", "Languages", "Languages")} &middot; <b>{meta['stakeholders_count']}</b> {RL.L("meta_bar", "Stakeholders", "Stakeholders")} &middot; <b>{meta['divergences_count']}</b> {RL.L("meta_bar", "Divergences", "Divergences")}</span><a href="{_esc(meta['html_filename'])}" class="read-link">&rarr; {RL.L("ui", "read", "READ")}</a></div>
</article>"""


def build_card_compact(meta: dict) -> str:
    """TIER 2 (EARLIER) — compact grid row: short id, headline (h4) + one-line
    truncated subheadline, prominent source count."""
    return f"""<div class="compact-row">
  <span class="compact-id">{_esc(_short_id(meta['id']))}</span>
  <div class="compact-body">
    <h4 class="compact-headline"><a href="{_esc(meta['html_filename'])}">{_esc(meta['headline'])}</a></h4>
    <span class="compact-sub">{_esc(meta['subheadline'])}</span>
  </div>
  <div class="compact-src"><span class="compact-src-num">{meta['sources_count']}</span><span class="compact-src-label">{RL.L("ui", "index_src_label", "SRC")}</span></div>
</div>"""


def build_archive_row(meta: dict) -> str:
    """TIER 3 (ARCHIVE) — index row inside a monthly accordion: short id,
    headline link, source count. Smaller and greyer than the compact row."""
    return f"""<div class="archive-row">
  <span class="archive-id">{_esc(_short_id(meta['id']))}</span>
  <a class="archive-headline" href="{_esc(meta['html_filename'])}">{_esc(meta['headline'])}</a>
  <span class="archive-src">{meta['sources_count']}<span class="archive-src-label">&nbsp;{RL.L("ui", "index_src_abbrev", "src")}</span></span>
</div>"""


def _build_tiers(all_meta: list[dict], reports_dir: Path | None) -> str:
    """Render the four age-decay tiers (TODAY / YESTERDAY / EARLIER / ARCHIVE).

    Tiers are anchored to ``today_ref`` — the newest dossier date in the set,
    NOT wall-clock — so the layout is a pure function of the published content.
    Empty tiers are omitted entirely (no bare bucket bars).
    """
    if not all_meta:
        return ""
    today_ref = max(m["date"] for m in all_meta)
    ref_dt = datetime.strptime(today_ref, "%Y-%m-%d")

    def age(m: dict) -> int:
        return (ref_dt - datetime.strptime(m["date"], "%Y-%m-%d")).days

    tier0 = _sort_tier([m for m in all_meta if age(m) == 0])
    tier1 = _sort_tier([m for m in all_meta if age(m) == 1])
    tier2 = _sort_tier([m for m in all_meta if 2 <= age(m) <= 6])
    tier3 = _sort_tier([m for m in all_meta if age(m) >= 7])

    html = ""

    # TIER 0 — TODAY: full hero cards (reuse build_card unchanged). Per-tier
    # index resets to 1 so the first hero reads TOPIC 01.
    if tier0:
        html += _bucket_bar(RL.L("ui", "tier_today", "TODAY"), len(tier0))
        for i, meta in enumerate(tier0, start=1):
            html += build_card(meta, i, reports_dir) + "\n"

    # TIER 1 — YESTERDAY: one date sub-marker (age==1 is always a single
    # calendar day), then mid cards.
    if tier1:
        html += _bucket_bar(RL.L("ui", "tier_yesterday", "YESTERDAY"), len(tier1))
        html += f'<div class="day-submarker">{_format_date(tier1[0]["date"])}</div>\n'
        for meta in tier1:
            html += build_card_mid(meta, reports_dir) + "\n"

    # TIER 2 — EARLIER: compact rows, grouped by day with a light sub-marker.
    if tier2:
        html += _bucket_bar(RL.L("ui", "tier_earlier", "EARLIER"), len(tier2))
        current_day: str | None = None
        for meta in tier2:
            if meta["date"] != current_day:
                current_day = meta["date"]
                html += (
                    f'<div class="day-submarker">{_format_date(current_day)}</div>\n'
                )
            html += build_card_compact(meta) + "\n"

    # TIER 3 — ARCHIVE: one <details> accordion per calendar month, newest open.
    if tier3:
        html += _bucket_bar(RL.L("ui", "tier_archive", "ARCHIVE"), len(tier3), light=True)
        by_month: dict[str, list[dict]] = {}
        for meta in tier3:  # already date-desc / id-asc from _sort_tier
            by_month.setdefault(meta["date"][:7], []).append(meta)
        for month_idx, month_key in enumerate(sorted(by_month.keys(), reverse=True)):
            rows = by_month[month_key]
            _mdt = datetime.strptime(month_key, "%Y-%m")
            month_label = (
                f"{RL.month_name(_mdt.month, _mdt.strftime('%B'))} {_mdt.year}".upper()
                if RL.get_lang() == "de"
                else _mdt.strftime("%B %Y").upper()
            )
            count = len(rows)
            plural = "S" if count != 1 else ""
            # All archive (Tier-3) months render collapsed on load — even the
            # newest. The reader expands a month deliberately. (Was: newest open.)
            open_attr = ""
            rows_html = "".join(build_archive_row(m) + "\n" for m in rows)
            html += (
                f'<details class="archive-month"{open_attr}>\n'
                f'<summary class="archive-month-summary">'
                f'<span class="archive-month-title">{month_label}</span>'
                f'<span class="archive-month-count">{RL.count_noun(count, "dossiers", str(count) + " DOSSIER" + plural)}</span>'
                f'</summary>\n'
                f'<div class="archive-month-body">\n{rows_html}</div>\n'
                f'</details>\n'
            )

    return html


def build_index(all_meta: list[dict], reports_dir: Path | None = None,
                lang: str = "en", lang_hrefs: dict | None = None) -> str:
    """Build the full index.html content.

    ``reports_dir`` is forwarded to ``build_card`` so follow-up links
    whose target HTML has been removed by the cutoff cleanup degrade
    to plain text rather than rendering as dead anchors on the index.
    """
    # Age-tiered "decay" layout (TODAY / YESTERDAY / EARLIER / ARCHIVE),
    # anchored to the newest dossier date in the set. See ``_build_tiers``.
    RL.set_lang(lang)
    if lang_hrefs is None:
        lang_hrefs = ({"en": "../index.html", "de": "index.html"} if lang == "de"
                      else {"en": "index.html", "de": "de/index.html"})
    lang_switch = RL.build_lang_switch(lang, lang_hrefs["en"], lang_hrefs["de"])
    cards_html = _build_tiers(all_meta, reports_dir)

    og_image = f"{SITE_BASE}/assets/og-card.svg"
    _index_html = f"""<!DOCTYPE html>
<html lang="{RL.html_lang()}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{SITE_TITLE}</title>
<link rel="canonical" href="{SITE_BASE}/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_TITLE}">
<meta property="og:title" content="{SITE_TITLE}">
<meta property="og:description" content="{SITE_TAGLINE}">
<meta property="og:url" content="{SITE_BASE}/">
<meta property="og:image" content="{og_image}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{SITE_TITLE}">
<meta name="twitter:description" content="{SITE_TAGLINE}">
<meta name="twitter:image" content="{og_image}">
<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">
<link rel="apple-touch-icon" sizes="180x180" href="/assets/apple-touch-icon.png">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Space+Grotesk:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="alternate" type="application/rss+xml" title="Independent Wire" href="/feed.xml">
<style>
:root {{
  --color-text: #000000;
  --color-text-secondary: #444444;
  --color-text-subtle: #999999;
  --color-primary: #3b82f6;
  --color-bg: #ffffff;
  --color-bg-subtle: #f5f5f5;
  --color-border: #000000;
  --color-border-light: #e0e0e0;
  --font-mono: 'Space Mono', 'Courier New', monospace;
  --font-sans: 'Space Grotesk', 'DM Sans', system-ui, sans-serif;
}}

*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: var(--font-sans);
  font-size: 16px;
  line-height: 1.6;
  color: var(--color-text);
  background: var(--color-bg);
}}

.container {{
  max-width: 740px;
  margin: 0 auto;
  padding: 2rem 1rem;
}}

/* Header */
header {{
  margin-bottom: 2.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 3px solid #000;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}}
header .brand {{ flex: 1 1 auto; min-width: 0; }}
header h1 {{
  font-family: var(--font-sans);
  font-size: 2rem;
  font-weight: 900;
  letter-spacing: -0.03em;
  text-transform: uppercase;
  color: #000;
  margin-bottom: 0.35rem;
}}
header .tagline {{
  font-family: var(--font-mono);
  color: #666;
  font-size: 0.75rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}}

/* Share button */
.share-btn {{
  flex: 0 0 auto;
  font-family: var(--font-mono);
  font-size: 0.7rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
  background: transparent; color: #000;
  border: 1.5px solid #000;
  padding: 0.6rem 1rem;
  min-height: 44px; min-width: 44px;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}}
.share-btn:hover {{ background: #000; color: #fff; }}
.share-btn:focus-visible {{ outline: 2px solid #000; outline-offset: 2px; }}

/* Date bar */
.date-bar {{
  background: #000;
  color: #fff;
  font-family: var(--font-mono);
  font-size: 0.8rem;
  letter-spacing: 0.12em;
  padding: 10px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 2rem;
  margin-bottom: 1.2rem;
}}

/* Follow-up hint */
.follow-up-hint {{
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: #444;
  margin: 0 0 12px 0;
}}
.follow-up-label {{
  color: #999;
}}
.follow-up-link {{
  color: #000;
  text-decoration: none;
}}
.follow-up-link:hover {{
  text-decoration: underline;
  text-decoration-color: #999;
  text-underline-offset: 2px;
}}
.follow-up-date {{
  color: #999;
}}

/* Cards */
.tp-card {{
  border: none;
  border-top: 3px solid #000;
  border-radius: 0;
  padding: 1.25rem 0;
  margin-bottom: 0.5rem;
}}
.topic-id {{
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: #999;
  letter-spacing: 0.15em;
  display: block;
  margin-bottom: 0.35rem;
  text-transform: uppercase;
}}
.tp-card h2 {{
  font-family: var(--font-sans);
  font-size: 1.5rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin-bottom: 0.35rem;
  line-height: 1.3;
}}
.tp-card h2 a {{
  color: #000;
  text-decoration: none;
}}
.tp-card h2 a:hover {{
  text-decoration: underline;
  text-decoration-thickness: 2px;
  text-underline-offset: 3px;
}}
.tp-card .subheadline {{
  color: #444;
  font-family: var(--font-sans);
  font-size: 0.95rem;
  margin-bottom: 0.5rem;
  border-left: 3px solid #000;
  padding-left: 0.75rem;
}}
.tp-card .summary {{
  font-family: var(--font-sans);
  font-size: 0.95rem;
  margin-bottom: 0.75rem;
  line-height: 1.55;
}}

/* Metadata bar */
.meta-bar {{
  display: flex;
  border: 1px solid #000;
  border-radius: 0;
  margin-bottom: 0.5rem;
}}
.meta-item {{
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  padding: 0.5rem 0.5rem;
  border-right: 1px solid #000;
}}
.meta-item:last-child {{
  border-right: none;
}}
.meta-number {{
  font-family: var(--font-mono);
  font-size: 1.4rem;
  font-weight: 700;
  color: #000;
}}
.meta-label {{
  font-family: var(--font-mono);
  font-size: 0.6rem;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}}

.card-footer {{
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: #999;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 0.25rem;
}}
.read-link {{
  color: #000;
  text-decoration: none;
  font-weight: 700;
  letter-spacing: 0.05em;
}}
.read-link:hover {{
  text-decoration: underline;
}}

/* ---- Age-decay tiers: bucket bars + mid / compact / archive ---- */
.bucket-bar {{
  background: #000;
  color: #fff;
  font-family: var(--font-mono);
  font-size: 0.8rem;
  letter-spacing: 0.12em;
  padding: 10px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 2rem;
  margin-bottom: 1.2rem;
}}
.bucket-bar-light {{
  background: #fff;
  color: #000;
  border-top: 3px solid #000;
  padding-left: 0;
  padding-right: 0;
  margin-bottom: 0.5rem;
}}

/* TIER 1 — YESTERDAY (mid card) */
.tp-card-mid {{
  border-top: 3px solid #000;
  padding: 1rem 0;
  margin-bottom: 0.4rem;
}}
.tp-card-mid h3 {{
  font-family: var(--font-sans);
  font-size: 1.3rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.3;
  margin: 0.15rem 0 0.4rem;
}}
.tp-card-mid h3 a {{ color: #000; text-decoration: none; }}
.tp-card-mid h3 a:hover {{
  text-decoration: underline;
  text-decoration-thickness: 2px;
  text-underline-offset: 3px;
}}
.subheadline-mid {{
  color: #333;
  font-family: var(--font-sans);
  font-size: 0.9rem;
  margin-bottom: 0.5rem;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}
.mid-stats {{
  text-transform: uppercase;
  line-height: 1.6;
}}
.mid-stats b {{
  color: #000;
  font-weight: 700;
}}

/* TIER 2 — EARLIER (compact row, day-grouped) */
.day-submarker {{
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: #999;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin: 1rem 0 0.4rem;
  display: flex;
  align-items: center;
}}
.day-submarker::after {{
  content: '';
  flex: 1;
  margin-left: 0.75rem;
  border-top: 1px dashed #ccc;
}}
.compact-row {{
  display: grid;
  grid-template-columns: 110px 1fr 70px;
  align-items: center;
  gap: 0.75rem;
  border-top: 1px solid var(--color-border-light);
  padding: 0.6rem 0;
}}
.compact-id {{
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: #999;
  letter-spacing: 0.1em;
}}
.compact-body {{ min-width: 0; }}
.compact-headline {{
  font-family: var(--font-sans);
  font-size: 1rem;
  font-weight: 700;
  line-height: 1.3;
  margin: 0;
}}
.compact-headline a {{ color: #000; text-decoration: none; }}
.compact-headline a:hover {{ text-decoration: underline; text-underline-offset: 2px; }}
.compact-sub {{
  display: block;
  font-family: var(--font-sans);
  font-size: 0.8rem;
  color: #666;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 0.1rem;
}}
.compact-src {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  text-align: right;
}}
.compact-src-num {{
  font-family: var(--font-mono);
  font-size: 1.3rem;
  font-weight: 700;
  color: #000;
  line-height: 1;
}}
.compact-src-label {{
  font-family: var(--font-mono);
  font-size: 0.55rem;
  color: #666;
  letter-spacing: 0.1em;
}}

/* TIER 3 — ARCHIVE (monthly accordions, native <details>) */
.archive-month {{ margin-bottom: 0.25rem; }}
.archive-month-summary {{
  list-style: none;
  cursor: pointer;
  background: #000;
  color: #fff;
  font-family: var(--font-mono);
  font-size: 0.8rem;
  letter-spacing: 0.12em;
  padding: 10px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 0.5rem;
}}
.archive-month-summary::-webkit-details-marker {{ display: none; }}
.archive-month-title {{ display: inline-flex; align-items: center; gap: 0.5rem; }}
.archive-month-title::before {{
  content: "\\203a";
  display: inline-block;
  font-weight: 700;
  transition: transform 150ms ease;
}}
details[open] > .archive-month-summary .archive-month-title::before {{
  transform: rotate(90deg);
}}
.archive-month-body {{ padding: 0.1rem 0 0.5rem; }}
.archive-row {{
  display: grid;
  grid-template-columns: 110px 1fr 40px;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.4rem 0;
  border-top: 1px solid var(--color-border-light);
}}
.archive-id {{
  font-family: var(--font-mono);
  font-size: 0.68rem;
  color: #999;
  letter-spacing: 0.08em;
}}
.archive-headline {{
  font-family: var(--font-sans);
  font-size: 0.85rem;
  font-weight: 500;
  color: #444;
  text-decoration: none;
  line-height: 1.35;
  min-width: 0;
}}
.archive-headline:hover {{ text-decoration: underline; text-underline-offset: 2px; color: #000; }}
.archive-src {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: #999;
  text-align: right;
  white-space: nowrap;
}}
.archive-src-label {{ font-size: 0.6rem; }}

/* Footer */
footer {{
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
}}
footer .footer-text {{ flex: 1 1 auto; }}
footer .footer-text p {{ margin: 0; }}
footer .footer-mark {{
  flex: 0 0 auto;
  width: 80px; height: 80px;
  display: block;
}}
footer .footer-mark svg {{ width: 100%; height: 100%; display: block; }}
footer a {{
  color: #000;
  text-decoration: underline;
}}

@media (max-width: 768px) {{
  header {{ flex-direction: column; align-items: flex-start; gap: 0.75rem; }}
  .meta-bar {{
    flex-wrap: wrap;
  }}
  .meta-item {{
    min-width: 4rem;
    border-right: none;
    border-bottom: 1px solid #000;
  }}
  .meta-item:last-child {{
    border-bottom: none;
  }}
  .tp-card h2 {{
    font-size: 1.2rem;
  }}
  footer {{ flex-direction: column-reverse; align-items: flex-start; gap: 1rem; }}
  footer .footer-mark {{ width: 64px; height: 64px; }}
  .tp-card-mid h3 {{ font-size: 1.1rem; }}
  .compact-row {{ grid-template-columns: 80px 1fr 52px; gap: 0.5rem; }}
  .compact-headline {{ font-size: 0.95rem; }}
  .compact-src-num {{ font-size: 1.1rem; }}
  .archive-row {{ grid-template-columns: 80px 1fr 40px; gap: 0.5rem; }}
  .tp-card-mid .card-footer {{ flex-wrap: wrap; gap: 0.3rem 0.6rem; }}
  .mid-stats {{ font-size: 0.65rem; }}
}}
{RL.lang_switch_css()}
{RL.support_block_css()}
</style>
</head>
<body>
<div class="container">
<header>
  <div class="brand">
    <h1>Independent Wire</h1>
    <p class="tagline">An independent newsroom &mdash; Open &middot; Transparent &middot; For everyone</p>
  </div>
  <div class="top-bar-right">{lang_switch}<button class="share-btn" data-url="{SITE_BASE}/" data-title="{SITE_TITLE}">Share</button></div>
</header>

<main>
{cards_html}
</main>

{RL.support_block()}
<footer>
<div class="footer-text">
<p>Generated by <a href="https://github.com/deniz-schwenk/independent-wire">Independent Wire</a></p>
<p>This content was produced by AI agents</p>
<p>AGPL-3.0 &mdash; Because transparency is not a feature, it is a promise</p>
<p><a href="index.html">Home</a> &middot; <a href="/about.html">About</a> &middot; <a href="/feed.xml">RSS Feed</a> &middot; <a href="/vision.pdf" download>Vision (PDF)</a> &middot; <a href="/impressum.html">Legal Notice</a> &middot; <a href="/privacy.html">Privacy</a></p>
</div>
<div class="footer-mark" aria-label="Independent Wire">{IW_SMALL_LIGHT_SVG}</div>
</footer>
</div>
<script>
document.querySelectorAll('.share-btn').forEach(btn => {{
  btn.addEventListener('click', async () => {{
    const url = btn.dataset.url;
    const title = btn.dataset.title;
    if (navigator.share) {{
      try {{ await navigator.share({{ title, url }}); }} catch (e) {{}}
    }} else {{
      try {{
        await navigator.clipboard.writeText(url);
        const original = btn.textContent;
        btn.textContent = 'Copied';
        setTimeout(() => {{ btn.textContent = original; }}, 1500);
      }} catch (e) {{}}
    }}
  }});
}});
</script>
</body>
</html>"""
    RL.set_lang("en")
    return _index_html


# ---------------------------------------------------------------------------
# feed.xml
# ---------------------------------------------------------------------------

def build_feed(all_meta: list[dict]) -> str:
    """Build RSS 2.0 feed."""
    items = ""
    for meta in sorted(all_meta, key=lambda x: (x["date"], x["id"]), reverse=True):
        items += f"""    <item>
      <title>{xml_escape(meta['headline'])}</title>
      <link>{SITE_BASE}/reports/{xml_escape(meta['id'])}.html</link>
      <description>{xml_escape(meta['summary'])}</description>
      <pubDate>{_rfc822_date(meta['date'])}</pubDate>
      <guid>{SITE_BASE}/reports/{xml_escape(meta['id'])}.html</guid>
    </item>
"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Independent Wire</title>
    <link>{SITE_BASE}</link>
    <description>An independent newsroom. Open. Transparent. For everyone.</description>
    <language>en</language>
    <atom:link href="{SITE_BASE}/feed.xml" rel="self" type="application/rss+xml"/>
{items}  </channel>
</rss>"""


# ---------------------------------------------------------------------------
# sitemap.xml + robots.txt
# ---------------------------------------------------------------------------

# Public static pages mapped into the sitemap, in footer order. Each is emitted
# only when the file actually exists under ``site/`` so every <loc> resolves.
STATIC_PAGES = ("about.html", "impressum.html", "privacy.html")


def build_sitemap(all_meta: list[dict], site_dir: Path) -> str:
    """Build a sitemaps.org-0.9 XML sitemap for the English edition.

    Covers the homepage, every published ``reports/{id}.html`` page, and the
    public static pages. ``all_meta`` is the same cutoff-filtered set the index
    and feed consume, so no pre-cutoff URL can leak in. Each report carries a
    ``<lastmod>`` from its publication date; the homepage's ``<lastmod>`` tracks
    the newest dossier. DE / hreflang alternates are out of scope (see
    TASK-SITEMAP-ROBOTS).
    """
    urls: list[str] = []

    # Homepage — lastmod follows the newest published dossier, if any.
    if all_meta:
        newest = max(m["date"] for m in all_meta)
        urls.append(
            f"  <url>\n    <loc>{SITE_BASE}/</loc>\n"
            f"    <lastmod>{newest}</lastmod>\n  </url>"
        )
    else:
        urls.append(f"  <url>\n    <loc>{SITE_BASE}/</loc>\n  </url>")

    # Reports — newest first, each with its publication date as <lastmod>.
    for meta in sorted(all_meta, key=lambda x: (x["date"], x["id"]), reverse=True):
        loc = f"{SITE_BASE}/reports/{xml_escape(meta['id'])}.html"
        urls.append(
            f"  <url>\n    <loc>{loc}</loc>\n"
            f"    <lastmod>{meta['date']}</lastmod>\n  </url>"
        )

    # Public static pages — only those present on disk, so every <loc> resolves.
    for page in STATIC_PAGES:
        if (site_dir / page).is_file():
            urls.append(f"  <url>\n    <loc>{SITE_BASE}/{page}</loc>\n  </url>")

    body = "\n".join(urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )


def build_robots(existing: str | None) -> str:
    """Return robots.txt content that allows all crawlers and points to the
    sitemap.

    With ``existing=None`` a minimal allow-all file is generated. When a
    robots.txt is already on disk, its content is preserved and only the
    ``Sitemap:`` directive is added or repaired (stale/duplicate ones are
    collapsed to a single correct line) — operator-authored crawl rules
    survive rather than being clobbered.
    """
    sitemap_line = f"Sitemap: {SITE_BASE}/sitemap.xml"
    if existing is None:
        return f"User-agent: *\nAllow: /\n{sitemap_line}\n"

    out: list[str] = []
    replaced = False
    for line in existing.splitlines():
        if line.strip().lower().startswith("sitemap:"):
            if not replaced:
                out.append(sitemap_line)  # repair in place; drop later dupes
                replaced = True
            continue
        out.append(line)
    if not replaced:
        while out and out[-1].strip() == "":
            out.pop()
        out.append(sitemap_line)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    render_script = repo_root / "scripts" / "render.py"
    site_dir = repo_root / "site"
    reports_dir = site_dir / "reports"

    # Parse args
    output_dir = repo_root / "output"
    target_date: str | None = None
    args = sys.argv[1:]
    while args:
        if args[0] == "--output-dir" and len(args) > 1:
            output_dir = Path(args[1])
            args = args[2:]
        elif args[0] == "--date" and len(args) > 1:
            target_date = args[1]
            args = args[2:]
        else:
            args = args[1:]

    # Load site config (cutoff date lives here).
    config = load_site_config()
    cutoff = config.get("published_from_date") or None

    # --date guard: refuse to publish a single date that pre-dates the cutoff.
    if target_date and cutoff and target_date < cutoff:
        print(
            f"ERROR: Cutoff date in config/site_config.json is {cutoff}. "
            f"Cannot publish TPs from {target_date} (before cutoff). "
            f"Update config or remove the cutoff to proceed.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Ensure directories
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Find TP JSON files — all dates unless --date is specified
    if target_date:
        date_dirs = [target_date]
    else:
        date_dirs = sorted(
            (d.name for d in output_dir.iterdir()
             if d.is_dir() and len(d.name) == 10 and d.name[:4].isdigit()),
            reverse=True,
        )
    if not date_dirs:
        print(f"No date directories found in {output_dir}")
        sys.exit(1)

    tp_jsons: list[Path] = []
    for dd in date_dirs:
        tp_jsons.extend(find_tp_files(output_dir, dd))
    if not tp_jsons:
        print(f"No tp-*.json files found in {output_dir}")
        sys.exit(1)

    # Apply publication cutoff: pre-cutoff TPs are not published. They stay on
    # disk in `output/{date}/` for local reference but never reach the public
    # site. Per D3 of TASK-PUBLISH-NUMBERING-AND-CUTOFF the cutoff covers
    # index.html, reports/, and the RSS feed.
    if cutoff:
        tp_jsons, excluded = filter_jsons_by_cutoff(tp_jsons, cutoff)
        if excluded:
            print(
                f"  Cutoff: {len(excluded)} TP(s) from before {cutoff} "
                f"excluded from publication"
            )
        # One-shot cleanup: any pre-cutoff HTML still living in
        # ``site/reports/`` from earlier deployment-test runs gets removed
        # so the public site matches the cutoff.
        removed = remove_pre_cutoff_reports(reports_dir, cutoff)
        if removed:
            print(
                f"  Cleanup: removed {removed} pre-cutoff HTML file(s) from "
                f"{reports_dir}"
            )
    if not tp_jsons:
        print(f"No tp-*.json files found at-or-after cutoff in {output_dir}")
        sys.exit(1)

    print(f"Publishing {len(tp_jsons)} Topic Package(s) from {len(date_dirs)} date(s)")

    # Step 1: Ensure HTML exists, copy to site/reports/
    all_meta: list[dict] = []
    for json_path in tp_jsons:
        # Skip TPs with 0 sources (older schema, not worth rendering)
        tp_data = json.loads(json_path.read_text(encoding="utf-8"))
        if len(tp_data.get("sources", [])) == 0:
            print(f"  Skipped {json_path.name} (0 sources)")
            continue

        html_path = ensure_html(json_path, render_script)
        if html_path is None:
            continue
        dest = reports_dir / f"{json_path.stem}.html"
        if not dest.exists() or dest.stat().st_size != html_path.stat().st_size:
            shutil.copy2(html_path, dest)
            print(f"  Copied {dest.name}")
        else:
            print(f"  Skipped {dest.name} (unchanged)")

        # Step 2: Extract metadata
        meta = extract_metadata(json_path)
        all_meta.append(meta)

    # Step 2b: Resolve follow-up placeholders in copied HTML files
    resolve_follow_up_links(reports_dir)

    # Step 3: Generate index.html
    index_html = build_index(all_meta, reports_dir=reports_dir)
    index_path = site_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    print(f"  Generated {index_path}")

    # Step 4: Generate feed.xml
    feed_xml = build_feed(all_meta)
    feed_path = site_dir / "feed.xml"
    feed_path.write_text(feed_xml, encoding="utf-8")
    print(f"  Generated {feed_path}")

    # Step 5: Generate sitemap.xml — machine-readable map of the published
    # English pages for search-engine discovery.
    sitemap_xml = build_sitemap(all_meta, site_dir)
    sitemap_path = site_dir / "sitemap.xml"
    sitemap_path.write_text(sitemap_xml, encoding="utf-8")
    print(f"  Generated {sitemap_path}")

    # Step 6: Generate / repair robots.txt — allow all crawlers, point to the
    # sitemap. Any existing operator-authored content is preserved.
    robots_path = site_dir / "robots.txt"
    existing_robots = (
        robots_path.read_text(encoding="utf-8") if robots_path.exists() else None
    )
    robots_txt = build_robots(existing_robots)
    robots_path.write_text(robots_txt, encoding="utf-8")
    print(f"  Generated {robots_path}")

    print(f"\nPublished {len(all_meta)} topic packages, index.html updated")


if __name__ == "__main__":
    main()
