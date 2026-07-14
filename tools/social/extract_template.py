#!/usr/bin/env python3
"""One-time extractor for the SETN card template bundle.

Reads the approved "Final 2B Broadsheet" design export (bundler format) and
writes the pieces the renderer needs into ``tools/social/template/``:

  * ``fonts/<uuid>.woff2``  — every embedded webfont (Space Grotesk / Space
    Mono, Latin subsets); the JS blobs (React, dc-runtime, ds-bundle) are
    dropped — the renderer re-implements the dynamic logic in plain JS.
  * ``fonts.json``          — ordered @font-face table (family/weight/style/
    unicode-range → local file) with the asset-UUID src rewritten to the
    extracted relative path. The renderer inlines these as data: URIs so the
    render page needs zero network and zero file:// font loads.
  * ``source_template.html``— the raw ``<x-dc>`` markup + the DCLogic
    component, verbatim. This is the design SOURCE OF TRUTH kept for audit;
    ``card.html`` is the hand-derived plain-JS render page built from it.

This is not part of the pipeline and imports nothing from ``src/``. Run once;
the outputs are checked in. Re-run only when the approved template changes.

    python tools/social/extract_template.py [SRC.html]

Default SRC: ``scratch/social/Kampagnenmotiv_Final.html``.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "template"
FONTS_DIR = TEMPLATE_DIR / "fonts"
DEFAULT_SRC = HERE.parents[1] / "scratch" / "social" / "Kampagnenmotiv_Final.html"

_WOFF2_MAGIC = b"wOF2"


def _decode_blob(entry: dict) -> bytes:
    raw = base64.b64decode(entry["data"])
    if entry.get("compressed"):
        raw = gzip.decompress(raw)
    return raw


def extract(src_path: Path) -> None:
    html = src_path.read_text(encoding="utf-8")

    manifest = json.loads(
        re.search(
            r'<script type="__bundler/manifest">\s*(\{.*?\})\s*</script>',
            html,
            re.DOTALL,
        ).group(1)
    )
    template = json.loads(
        re.search(
            r'<script type="__bundler/template">\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        ).group(1)
    )

    FONTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fonts only — drop JS assets (React runtime / dc-runtime / ds-bundle).
    font_uuids: set[str] = set()
    for uuid, entry in manifest.items():
        raw = _decode_blob(entry)
        if raw[:4] != _WOFF2_MAGIC:
            continue  # JS blob — the render page re-implements the logic
        (FONTS_DIR / f"{uuid}.woff2").write_bytes(raw)
        font_uuids.add(uuid)

    # 2. @font-face table with asset-UUID src rewritten to the local file.
    faces: list[dict] = []
    for block in re.findall(r"@font-face\s*\{(.*?)\}", template, re.DOTALL):
        uid_m = re.search(r'url\("([0-9a-f-]+)"\)', block)
        if not uid_m or uid_m.group(1) not in font_uuids:
            continue
        uid = uid_m.group(1)
        fam = re.search(r"font-family:\s*'([^']+)'", block)
        wt = re.search(r"font-weight:\s*(\d+)", block)
        st = re.search(r"font-style:\s*(\w+)", block)
        ur = re.search(r"unicode-range:\s*([^;]+);", block)
        faces.append(
            {
                "family": fam.group(1) if fam else "",
                "weight": int(wt.group(1)) if wt else 400,
                "style": st.group(1) if st else "normal",
                "unicode_range": ur.group(1).strip() if ur else None,
                "file": f"fonts/{uid}.woff2",
            }
        )
    (TEMPLATE_DIR / "fonts.json").write_text(
        json.dumps(faces, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 3. Raw design source of truth (x-dc markup + DCLogic), for audit.
    (TEMPLATE_DIR / "source_template.html").write_text(template, encoding="utf-8")

    print(f"extracted {len(font_uuids)} fonts, {len(faces)} @font-face rules")
    print(f"  -> {FONTS_DIR}")
    print(f"  -> {TEMPLATE_DIR / 'fonts.json'}")
    print(f"  -> {TEMPLATE_DIR / 'source_template.html'}")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.is_file():
        sys.exit(f"source template not found: {src}")
    extract(src)
