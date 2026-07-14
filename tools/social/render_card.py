#!/usr/bin/env python3
"""Deterministic SETN campaign-card renderer — "Final 2B Broadsheet".

Standalone tool: turns one card JSON into a 1080x1080 PNG, pixel-faithful to the
approved motif. Not part of the pipeline; imports nothing from ``src/``. A
headless Chromium (Playwright) screenshots a self-contained local HTML page
built from ``template/card.html`` with all fonts inlined as data: URIs — zero
network access at render time. All dynamic sizing is deterministic (the DCLogic
algorithm re-implemented in plain JS in the page); no LLM anywhere.

CLI:
    python render_card.py <card.json> [-o out.png]
    python render_card.py --batch <dir>      # render every *.json in <dir>

Card JSON fields: wordA, wordB, originalA, originalB, sourceA, sourceB,
dossierId, dossierDate, layout ("auto"|"row"|"stacked", default "auto").
Unknown fields (e.g. a `delivery` block) are ignored, not rejected. Input
strings are never modified (no quote insertion, no RLM/mark trimming, no case
changes).

Setup (once):  pip install -r requirements.txt && playwright install chromium
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "template"
CARD_HTML = TEMPLATE_DIR / "card.html"
FONTS_JSON = TEMPLATE_DIR / "fonts.json"

CANVAS = 1080

# Card fields the page consumes. Unknown keys in the input are dropped here
# (ignored, not rejected). Strings pass through verbatim.
_CARD_FIELDS = (
    "wordA", "wordB", "originalA", "originalB",
    "sourceA", "sourceB", "dossierId", "dossierDate", "layout",
)


def _build_fontface_css() -> str:
    """@font-face rules with each woff2 inlined as a data: URI (zero network)."""
    faces = json.loads(FONTS_JSON.read_text(encoding="utf-8"))
    rules: list[str] = []
    for f in faces:
        woff2 = (TEMPLATE_DIR / f["file"]).read_bytes()
        b64 = base64.b64encode(woff2).decode("ascii")
        parts = [
            "@font-face{",
            f"font-family:'{f['family']}';",
            f"font-style:{f['style']};",
            f"font-weight:{f['weight']};",
            "font-display:swap;",
            f'src:url(data:font/woff2;base64,{b64}) format("woff2");',
        ]
        if f.get("unicode_range"):
            parts.append(f"unicode-range:{f['unicode_range']};")
        parts.append("}")
        rules.append("".join(parts))
    return "\n".join(rules)


def _build_page(card: dict) -> str:
    """Assemble the self-contained render page: template + inlined fonts + data."""
    html = CARD_HTML.read_text(encoding="utf-8")
    data = {k: card[k] for k in _CARD_FIELDS if k in card}
    # JSON embedded in a <script type="application/json"> — escape "</" so a
    # value containing "</script>" cannot close the tag early (valid JSON).
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/* __FONTFACE__ */", _build_fontface_css())
    html = html.replace("__CARD_JSON__", payload)
    return html


def render_card(
    card_path: str | Path,
    out_path: str | Path | None = None,
    *,
    assert_no_network: bool = True,
) -> dict:
    """Render one card JSON to a PNG. Returns metadata dict.

    ``assert_no_network`` raises if the page issues any http(s)/ws request
    (acceptance #5). Returns ``{out, width, height, network_requests}``.
    """
    from playwright.sync_api import sync_playwright

    card_path = Path(card_path)
    card = json.loads(card_path.read_text(encoding="utf-8"))
    if out_path is None:
        out_path = card_path.with_suffix(".png")
    out_path = Path(out_path)

    page_html = _build_page(card)
    external: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        page_file = Path(td) / "page.html"
        page_file.write_text(page_html, encoding="utf-8")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--force-color-profile=srgb", "--hide-scrollbars"],
            )
            ctx = browser.new_context(
                viewport={"width": CANVAS, "height": CANVAS},
                device_scale_factor=1,
            )
            page = ctx.new_page()

            def _on_request(req):
                scheme = req.url.split(":", 1)[0].lower()
                if scheme in ("http", "https", "ws", "wss"):
                    external.append(req.url)

            page.on("request", _on_request)
            page.goto(page_file.as_uri())
            page.wait_for_function("window.__RENDERED__ === true", timeout=30000)
            meta = page.evaluate("window.__CARD_META__") or {}
            page.locator("#card").screenshot(path=str(out_path), type="png")
            browser.close()

    if assert_no_network and external:
        raise RuntimeError(
            f"render_card: {len(external)} external network request(s) during "
            f"render (expected zero): {external[:5]}"
        )

    return {
        "out": str(out_path),
        "width": CANVAS,
        "height": CANVAS,
        "network_requests": external,
        "layout": meta.get("layout"),
        "row_font_size": meta.get("rowFontSize"),
        "row_slash_size": meta.get("rowSlashSize"),
        "stack_font_size": meta.get("stackFontSize"),
    }


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a SETN campaign card to PNG.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("card", nargs="?", help="path to a card JSON file")
    g.add_argument("--batch", metavar="DIR", help="render every *.json in DIR")
    ap.add_argument("-o", "--out", help="output PNG path (single-card mode)")
    args = ap.parse_args(argv)

    if args.batch:
        d = Path(args.batch)
        cards = sorted(d.glob("*.json"))
        if not cards:
            print(f"no *.json found in {d}", file=sys.stderr)
            return 1
        for c in cards:
            meta = render_card(c)
            print(f"rendered {c.name} -> {meta['out']}")
        return 0

    meta = render_card(args.card, args.out)
    print(f"rendered {args.card} -> {meta['out']}  ({meta['width']}x{meta['height']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
