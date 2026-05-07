#!/usr/bin/env python3
"""Independent Wire — Generate publication website from rendered Topic Packages."""

import json
import shutil
import subprocess
import sys
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


ROOT = Path(__file__).resolve().parent.parent


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
    """Format '2026-04-13' as 'April 13, 2026'."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
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
    """Ensure a TP HTML file exists, rendering it if necessary. Returns None on failure."""
    html_path = json_path.with_suffix(".html")
    if not html_path.exists():
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
        "word_count": article.get("word_count", 0),
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
            f'<span class="follow-up-label">Follow-up to:</span> '
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
    <div class="meta-item"><span class="meta-number">{meta['sources_count']}</span><span class="meta-label">Sources</span></div>
    <div class="meta-item"><span class="meta-number">{meta['languages_count']}</span><span class="meta-label">Languages</span></div>
    <div class="meta-item"><span class="meta-number">{meta['stakeholders_count']}</span><span class="meta-label">Stakeholders</span></div>
    <div class="meta-item"><span class="meta-number">{meta['divergences_count']}</span><span class="meta-label">Divergences</span></div>
  </div>
  <div class="card-footer"><span>{meta['word_count']:,} words &middot; {_format_date(meta['date'])}</span><a href="{_esc(meta['html_filename'])}" class="read-link">&rarr; READ DOSSIER</a></div>
</article>"""


def build_index(all_meta: list[dict], reports_dir: Path | None = None) -> str:
    """Build the full index.html content.

    ``reports_dir`` is forwarded to ``build_card`` so follow-up links
    whose target HTML has been removed by the cutoff cleanup degrade
    to plain text rather than rendering as dead anchors on the index.
    """
    # Group by date descending
    by_date: dict[str, list[dict]] = {}
    for m in sorted(all_meta, key=lambda x: (x["date"], x["id"]), reverse=True):
        by_date.setdefault(m["date"], []).append(m)

    cards_html = ""
    for date_str in sorted(by_date.keys(), reverse=True):
        date_entries = sorted(by_date[date_str], key=lambda x: x["id"])
        count = len(date_entries)
        cards_html += f'<div class="date-bar"><span>{_format_date(date_str).upper()}</span><span>{count} DOSSIER{"S" if count != 1 else ""}</span></div>\n'
        # Reset per date — each day's first card reads TOPIC 01 regardless
        # of how many cards earlier dates contributed.
        card_index = 0
        for meta in date_entries:
            card_index += 1
            cards_html += build_card(meta, card_index, reports_dir) + "\n"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Independent Wire</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Space+Grotesk:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="alternate" type="application/rss+xml" title="Independent Wire" href="feed.xml">
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
}}
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

/* Footer */
footer {{
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
}}
footer a {{
  color: #000;
  text-decoration: underline;
}}

@media (max-width: 768px) {{
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
}}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>Independent Wire</h1>
  <p class="tagline">An independent newsroom &mdash; Open &middot; Transparent &middot; For everyone</p>
</header>

<main>
{cards_html}
</main>

<footer>
<p>Generated by <a href="https://github.com/deniz-schwenk/independent-wire">Independent Wire</a></p>
<p>This content was produced by AI agents</p>
<p>AGPL-3.0 &mdash; Because transparency is not a feature, it is a promise</p>
<p><a href="feed.xml">RSS Feed</a></p>
</footer>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# feed.xml
# ---------------------------------------------------------------------------

def build_feed(all_meta: list[dict]) -> str:
    """Build RSS 2.0 feed."""
    items = ""
    for meta in sorted(all_meta, key=lambda x: (x["date"], x["id"]), reverse=True):
        items += f"""    <item>
      <title>{xml_escape(meta['headline'])}</title>
      <link>https://independentwire.org/reports/{xml_escape(meta['id'])}.html</link>
      <description>{xml_escape(meta['summary'])}</description>
      <pubDate>{_rfc822_date(meta['date'])}</pubDate>
      <guid>https://independentwire.org/reports/{xml_escape(meta['id'])}.html</guid>
    </item>
"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Independent Wire</title>
    <link>https://independentwire.org</link>
    <description>An independent newsroom. Open. Transparent. For everyone.</description>
    <language>en</language>
    <atom:link href="https://independentwire.org/feed.xml" rel="self" type="application/rss+xml"/>
{items}  </channel>
</rss>"""


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

    print(f"\nPublished {len(all_meta)} topic packages, index.html updated")


if __name__ == "__main__":
    main()
