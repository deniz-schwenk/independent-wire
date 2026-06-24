# BACKLOG — German static pages (About / Impressum / Privacy)

**Status:** Parked. Not urgent — an incompleteness, not a bug.

## Context
The German edition (`site/de/`) renders only the index and dossiers. The
footer/header links for About, Legal Notice (Impressum), Privacy and RSS were
made root-absolute in `ec1ea0e` (fixing the prior `/de/` 404s), so from the
German edition they now resolve to the shared **root** pages — which are
English (`lang="en"`). A German-edition reader therefore gets English
About/legal pages: reachable and correct in content, but not localized.

Original pages (hand-authored, English, email JS-obfuscated): About `b8a98b0`,
Legal Notice + Privacy `6c012c3`. Source copy for a translation lives in
`site/about.html`.

## Why staged (the three pages differ in cost and risk)
- **German About** (`site/de/about.html`) — low effort, low risk. The polished
  English About copy already exists; translate it, render with the German
  header/footer, obfuscated `hello@`. Safe to do anytime.
- **German Impressum + Privacy** (`site/de/impressum.html`,
  `site/de/privacy.html`) — **legal text**. Must NOT go through the translation
  pipeline. DDG/§5 (Impressum) and DSGVO (Privacy) wording has to be correct;
  this is a careful human drafting session, not a quick render.

## Legal note (not legal advice)
For a Germany-operated site, a German Impressum is the more robust path. The
English Impressum is reachable and carries the required details, but German is
safer. Operator's call — flagged for completeness.

## Implementation dependency (important)
The footer is currently **one shared string** for both editions, with shared
pages as root-absolute (`ec1ea0e`). Adding German static pages means the German
edition's About/Impressum/Privacy links must target the `/de/` versions while
English targets root — i.e. this **re-introduces lang-aware footer link
construction** (exactly what `ec1ea0e` deliberately flattened). Any activation
must handle that with a `lang` param choosing `/de/about.html` vs `/about.html`,
etc. Keep `Home` (`index.html`) and dossier back-nav (`../index.html`)
edition-relative, as they already are.

## When activated
- **Stage 1 — German About** (CC task): add `site/de/about.html` (translated
  copy, German furniture, obfuscated `hello@`); make the German footer/header
  About link target `/de/about.html`; re-render DE.
- **Stage 2 — German Impressum + Privacy** (careful drafting first, then CC):
  draft correct German legal copy (Architect/operator), then add
  `site/de/impressum.html` + `site/de/privacy.html` with the obfuscated
  `deniz@` helper, and point the German footer Legal/Privacy links at the
  `/de/` versions.

## Cross-refs
- Footer root-absolute fix: `ec1ea0e`
- Original EN static pages: About `b8a98b0`, Legal/Privacy `6c012c3`
- English About copy (translation source): `site/about.html`
