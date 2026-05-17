# BACKLOG-OG-IMAGE-PNG-CONVERSION

## Context

`site/assets/og-card.svg` is currently the og:image for both Index and TP
pages (added in TASK-UI-TWEAKS-AND-BRANDING). SVG is rendered correctly by
Facebook, LinkedIn, Slack, Discord, iMessage, and Telegram — but Twitter's
card validator does not reliably accept SVG og:images and silently falls
back to a plain link preview without the card image.

## Resolution sketch

- Convert `site/assets/og-card.svg` → `site/assets/og-card.png` at
  1200×630 (e.g. `rsvg-convert -w 1200 -h 630 og-card.svg -o og-card.png`
  or via `inkscape --export-type=png`).
- Add the conversion to a small `Makefile` target or a CI step so the
  SVG remains the authoritative source and the PNG regenerates on change.
- Update `og:image` / `twitter:image` in `scripts/render.py:build_meta_tags`
  and `scripts/publish.py:build_index` to point at `og-card.png`.

## Out of scope until then

The current SVG og:image works on all major social platforms except
Twitter's card scraper. Acceptable interim state.
