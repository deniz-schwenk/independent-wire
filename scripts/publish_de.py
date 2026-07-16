#!/usr/bin/env python3
"""German publish — standalone, post-translation. NOT part of the pipeline.

Renders the German page from the German JSON (output/<date>/de/tp-*.de.json) plus the
source Topic Package, reusing scripts/render.py (lang='de') and scripts/publish.py
(build_index, lang='de'), and writes the German site into site/de/ — site/de/index.html +
site/de/reports/*.html — WITHOUT touching the English site/. German prose comes from the
de JSON (spliced into the TP by JSON path); every controlled-vocabulary label is looked up
in config/de_render_labels.json (never translated at render time).

Invoked by the translate-de post-run flow (translate_de_run.sh) after the daily
translation completes. It is never imported by scripts/run.py.

Usage:
  publish_de.py                  # all dates that have a de/ folder
  publish_de.py --date 2026-06-19
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts import render          # noqa: E402  (render.render(tp, lang='de', ...))
from scripts import publish         # noqa: E402  (build_index, lang='de')
from scripts import render_labels as RL  # noqa: E402  (position_count metric)

OUTPUT_DIR = REPO / "output"
SITE_DIR = REPO / "site"
DE_SITE = SITE_DIR / "de"
DE_REPORTS = DE_SITE / "reports"

# Path tokens: bare keys and [index]/[id] segments. "article.body#p{n}" is handled apart.
_TOK = re.compile(r"[^.\[\]]+|\[[^\]]+\]")
_BODY_P = re.compile(r"^article\.body#p(\d+)$")


def _set_path(obj, path: str, value) -> None:
    """Set obj at the given de-JSON path. [n] is a list index; [id] matches a list element
    whose `id` equals the token (e.g. sources[src-001]). Missing paths are skipped."""
    toks = _TOK.findall(path)
    cur = obj
    for i, tok in enumerate(toks):
        last = i == len(toks) - 1
        if tok.startswith("["):
            inner = tok[1:-1]
            if not isinstance(cur, list):
                return
            if inner.isdigit():
                idx = int(inner)
                if not (0 <= idx < len(cur)):
                    return
                if last:
                    cur[idx] = value
                    return
                cur = cur[idx]
            else:
                cur = next((e for e in cur if isinstance(e, dict)
                            and str(e.get("id")) == inner), None)
                if cur is None or last:
                    return
        else:
            if last:
                if isinstance(cur, dict):
                    cur[tok] = value
                return
            if not isinstance(cur, dict):
                return
            cur = cur.get(tok)
        if cur is None:
            return


def splice_de(tp: dict, de_items: list[dict]) -> dict:
    """Return a deep copy of the TP with German `final` text overlaid by path. The body is
    reassembled from its translated paragraphs (article.body#p0..pN)."""
    g = copy.deepcopy(tp)
    body_paras: dict[int, str] = {}
    for it in de_items:
        final = it.get("final")
        path = it.get("path")
        if final is None or not path:
            continue
        m = _BODY_P.match(path)
        if m:
            body_paras[int(m.group(1))] = final
            continue
        _set_path(g, path, final)
    if body_paras:
        g.setdefault("article", {})["body"] = "\n\n".join(
            body_paras[i] for i in sorted(body_paras))
    return g


def _spliced(tp_json: Path, de_json: Path) -> dict:
    tp = json.loads(tp_json.read_text(encoding="utf-8"))
    de = json.loads(de_json.read_text(encoding="utf-8"))
    return splice_de(tp, de.get("items", []))


def render_tp_de(tp_json: Path, de_json: Path) -> tuple[str, str]:
    g = _spliced(tp_json, de_json)
    tp_id = g.get("id", tp_json.stem)
    # switch targets relative to site/de/reports/<id>.html
    hrefs = {"en": f"../../reports/{tp_id}.html", "de": f"{tp_id}.html"}
    return tp_id, render.render(g, lang="de", lang_hrefs=hrefs)


def de_meta(tp_json: Path, de_json: Path) -> dict:
    """Index-card metadata with German headline/subheadline/summary (same shape as
    publish.extract_metadata, but built from the spliced German TP)."""
    g = _spliced(tp_json, de_json)
    article = g.get("article", {})
    bias = g.get("bias_analysis", {})
    return {
        "id": g["id"],
        "date": g["metadata"]["date"],
        "headline": article.get("headline", ""),
        "subheadline": article.get("subheadline", ""),
        "summary": article.get("summary", ""),
        "word_count": article.get("word_count", len(article.get("body", "").split())),
        "sources_count": len(g.get("sources", [])),
        "languages_count": len(bias.get("source", {}).get("by_language", {})),
        # Distinct mapped positions; None -> metric omitted (older-schema TPs).
        "positions_count": RL.position_count(g),
        "divergences_count": len(g.get("divergences", [])),
        "html_filename": f"reports/{g['id']}.html",
        "follow_up": g.get("metadata", {}).get("follow_up"),
    }


def _pairs(target_date: str | None) -> list[tuple[Path, Path]]:
    """(tp_json, de_json) pairs for every translated TP (optionally one date)."""
    out = []
    de_dirs = ([OUTPUT_DIR / target_date / "de"] if target_date
               else sorted(p / "de" for p in OUTPUT_DIR.glob("20*-*-*") if (p / "de").is_dir()))
    for de_dir in de_dirs:
        if not de_dir.is_dir():
            continue
        day = de_dir.parent.name
        for de_json in sorted(de_dir.glob("tp-*.de.json")):
            tp_id = de_json.name[:-len(".de.json")]
            tp_json = OUTPUT_DIR / day / f"{tp_id}.json"
            if tp_json.exists():
                out.append((tp_json, de_json))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="German publish (site/de/) — post-translation")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: all translated dates)")
    a = ap.parse_args()

    pairs = _pairs(a.date)
    if not pairs:
        print(f"publish_de: no translated TPs found"
              f"{' for ' + a.date if a.date else ''} — nothing to do.")
        return 0

    DE_REPORTS.mkdir(parents=True, exist_ok=True)
    metas: list[dict] = []
    for tp_json, de_json in pairs:
        tp_id, html = render_tp_de(tp_json, de_json)
        (DE_REPORTS / f"{tp_id}.html").write_text(html, encoding="utf-8")
        metas.append(de_meta(tp_json, de_json))
        print(f"  rendered site/de/reports/{tp_id}.html")

    # German index — same builder, lang='de'; switch links to the English index.
    index_html = publish.build_index(
        metas, reports_dir=DE_REPORTS, lang="de",
        lang_hrefs={"en": "../index.html", "de": "index.html"})
    (DE_SITE / "index.html").write_text(index_html, encoding="utf-8")
    print(f"  generated site/de/index.html ({len(metas)} dossier(s))")
    print(f"publish_de: wrote {len(metas)} German page(s) into {DE_SITE} "
          f"(English site/ untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
