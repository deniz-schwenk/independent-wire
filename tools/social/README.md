# SETN campaign-card renderer

Standalone, deterministic renderer that turns a **card JSON** into the final
SETN ("Same Event · Two Names") campaign image — a **1080×1080 PNG**,
pixel-faithful to the approved template **"Final 2B Broadsheet"**.

This is a self-contained tool. It is **not** part of the Independent Wire
pipeline — no stage, no landing slot, and it imports nothing from `src/`.

## How it works

A headless Chromium (Playwright) screenshots a self-contained local HTML page
built from `template/card.html`:

- All dynamic sizing is **deterministic** — the template's `DCLogic` component
  (design source of truth, kept verbatim in `template/source_template.html`)
  is re-implemented as plain JS in the page (no React, no DC runtime). No LLM
  anywhere.
- All fonts (Space Grotesk + Space Mono, the extracted `.woff2` subsets) are
  inlined as `data:` URIs at render time, so there is **zero network access**
  during rendering.
- The page waits for `document.fonts.ready` **before** measuring and **before**
  the screenshot; the screenshot is taken at `deviceScaleFactor=1`, viewport
  1080×1080, no scrollbars.

## Setup (once)

```bash
pip install -r requirements.txt      # playwright only
playwright install chromium          # downloads the browser (network, one-time)
```

## Usage

```bash
python render_card.py <card.json> [-o out.png]     # single card
python render_card.py --batch <dir>                # every *.json in <dir>
```

Default output is `<card-stem>.png` next to the input.

## Card JSON

| field | meaning |
|---|---|
| `wordA`, `wordB` | headline pair (no quotation marks) |
| `originalA`, `originalB` | verbatim quotes **including** typographic quotation marks; RTL strings carry a leading U+200F RLM — the renderer adds/strips nothing |
| `sourceA`, `sourceB` | source attributions |
| `dossierId`, `dossierDate` | footer triplet left cell |
| `layout` | `"auto"` (default) \| `"row"` \| `"stacked"` |

Unknown fields (e.g. a `delivery` block) are **ignored, not rejected**. Input
strings are never modified — no quote insertion, no RLM/mark trimming, no case
changes.

### Sizing (from the template's DCLogic, reproduced exactly)

`inner = 1080 − 2×88 = 904`. Row available `= inner − 120` (slash + 2×40 gap).
Both words are measured at 100px (weight 800, letter-spacing −0.04em, Space
Grotesk); `rowSize = min(150, floor(rowAvail·100 / combined))`, then a safety
loop `while rowSize > 40 and measured row width > inner: rowSize −= 2`. Stacked
uses `stackSize = min(190, fit widest word to 904)` with the same −2 loop.
`auto` stacks when `rowSize < 96`. Slash = `round(0.42 × rowSize)` in row mode,
fixed 48px in stacked mode.

## Template / assets provenance

`template/` was extracted **once** from the approved design export (bundler
format) via `extract_template.py`. That source bundle is not checked in (it was
provided out-of-band as `Kampagnenmotiv_Final.html`); re-run extraction only if
the approved template changes:

```bash
python extract_template.py path/to/Kampagnenmotiv_Final.html
```

- `template/fonts/*.woff2` — Space Grotesk + Space Mono Latin subsets (SIL Open
  Font License; shipped inside the approved bundle).
- `template/fonts.json` — the @font-face table (family/weight/style/unicode-range
  → local file), asset-UUID `src` rewritten to the extracted path.
- `template/source_template.html` — the raw `<x-dc>` markup + `DCLogic`, verbatim
  (design source of truth, for audit).
- `template/card.html` — the hand-derived plain-JS render page.

## Notes

- **RTL / Arabic:** the approved bundle ships no Arabic face, so Farsi/Arabic
  glyphs use the OS Arabic fallback (exactly as the template does). Direction
  and quotation-mark placement are handled by Chromium's bidi algorithm plus the
  input's leading RLM — the renderer changes nothing.
- **Determinism** is guaranteed on the **same machine** (acceptance: rendering
  the same JSON twice yields pixel-identical PNGs). Across machines/OSes the
  fallback Arabic face and font hinting may differ.

## Tests

```bash
pip install pytest
pytest test_render_card.py
```

Covers 1080×1080 output, RTL Farsi, auto/forced layout, determinism (pixel
hash), zero network, unknown-field tolerance, and input-string immutability.
`testdata/rtl_farsi.png` is the committed RTL reference render.
