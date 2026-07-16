"""Shared render-time label resolution + the DE/EN language switch.

English is the IDENTITY default: when the active language is not 'de' (or the map is
missing), every lookup returns the English string passed in — so the English render path
is byte-for-byte unchanged. German labels are looked up (never translated at render time)
from config/de_render_labels.json. Both scripts/render.py (topic-package page) and
scripts/publish.py (index page) import this so the German page and the switch are built
the same way on both page types.

This is render-path infrastructure: it loads one static JSON and does dict lookups — no
LLM, no coupling to the translation feature or the pipeline.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_MAP_PATH = _REPO / "config" / "de_render_labels.json"

# Active render language for the current page. English is identity; render()/the German
# publisher set this to 'de' around a German page and back to 'en' afterwards.
_LANG = "en"


@functools.lru_cache(maxsize=1)
def _map() -> dict:
    try:
        return json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def set_lang(lang: str) -> None:
    global _LANG
    _LANG = "de" if lang == "de" else "en"


def get_lang() -> str:
    return _LANG


def html_lang() -> str:
    """The value for <html lang="...">."""
    return _LANG


def L(category: str, key, en_default: str) -> str:
    """labels[category][key] in German, else the English default (identity in EN)."""
    if _LANG != "de":
        return en_default
    cat = _map().get(category)
    if not isinstance(cat, dict):
        return en_default
    v = cat.get(str(key))
    return v if isinstance(v, str) and v else en_default


def Ldef(subcat: str, key, en_default: str) -> str:
    """definitions[subcat][key] in German, else the English default."""
    if _LANG != "de":
        return en_default
    sub = _map().get("definitions", {}).get(subcat, {})
    v = sub.get(str(key))
    return v if isinstance(v, str) and v else en_default


def month_name(n: int, en_default: str) -> str:
    """German month name for month number 1-12, else the English default."""
    return L("month_name", str(int(n)), en_default)


def noun(n: int, noun_key: str, en_default: str) -> str:
    """Just the German singular/plural noun word for a count (no number prepended), else
    the English default. For markup that styles the count separately from the noun."""
    if _LANG != "de":
        return en_default
    forms = _map().get("count_noun", {}).get(noun_key)
    if not isinstance(forms, dict):
        return en_default
    return forms.get("one" if n == 1 else "other") or forms.get("other") or en_default


def count_noun(n: int, noun_key: str, en_default: str) -> str:
    """German '{n} {singular|plural}' for a count, else the English default string.

    The label map's count_noun[noun_key] = {"one": <sg>, "other": <pl>} carries the German
    forms (the English-side pluralization in render.py:_plural can't produce them)."""
    if _LANG != "de":
        return en_default
    forms = _map().get("count_noun", {}).get(noun_key)
    if not isinstance(forms, dict):
        return en_default
    word = forms.get("one" if n == 1 else "other") or forms.get("other")
    return f"{n} {word}" if word else en_default


# --------------------------------------------------- shared stats-box metric

def position_count(tp: dict) -> int | None:
    """Number of distinct mapped positions for the stats box, or ``None`` when
    the metric should be omitted.

    Reads ``tp["perspectives"]["position_clusters"]`` — the count of mapped
    opinion positions, the project's core claim in one figure. Returns ``None``
    (metric omitted, never rendered as 0) when the slot is missing or empty, as
    on older-schema TPs. Shared by both stats-box builders (``publish.py`` index
    cards, ``render.py`` dossier meta bar) so the two page types stay in sync —
    this is not a label, it is render-path infrastructure."""
    clusters = (tp.get("perspectives") or {}).get("position_clusters")
    if isinstance(clusters, list) and clusters:
        return len(clusters)
    return None


# ----------------------------------------------------------- DE/EN switch

def build_lang_switch(current_lang: str, en_href: str, de_href: str) -> str:
    """A fixed switch placed next to the share button on both page types. Shows 'en' and
    'de' (with a small honest 'beta' marker), the current one marked active; each links to
    the same page in the other language."""
    def opt(code: str, href: str, active: bool, beta: bool = False) -> str:
        cls = "lang-opt lang-opt--active" if active else "lang-opt"
        aria = ' aria-current="page"' if active else ""
        beta_html = '<sup class="lang-beta">beta</sup>' if beta else ""
        return f'<a class="{cls}" href="{href}"{aria}><span class="lang-code">{code}</span>{beta_html}</a>'
    is_de = current_lang == "de"
    en = opt("en", en_href, not is_de)
    de = opt("de", de_href, is_de, beta=True)
    return (f'<div class="lang-switch" role="navigation" aria-label="Language / Sprache">'
            f'{en}{de}</div>')


def lang_switch_css() -> str:
    """CSS for the switch + the right-side group that holds switch + share button.
    Injected into both render.py's page CSS and publish.py's index CSS."""
    return """
/* Language switch (DE/EN) — fixed next to the share button on both page types */
.top-bar-right { display: inline-flex; align-items: center; gap: 0.6rem; }
.lang-switch {
  display: inline-flex; align-items: stretch;
  border: 1.5px solid #000;
  font-family: var(--font-mono);
  font-size: 0.7rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
}
.lang-switch .lang-opt {
  display: inline-flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 0 0.7rem; min-height: 44px; min-width: 3.2rem;
  color: #000; text-decoration: none; background: transparent;
  text-align: center;
}
.lang-switch .lang-opt + .lang-opt { border-left: 1.5px solid #000; }
.lang-switch .lang-opt--active { background: #000; color: #fff; }
.lang-switch .lang-opt:hover:not(.lang-opt--active) { background: #f0f0f0; }
.lang-switch .lang-code { display: block; line-height: 1; }
.lang-switch .lang-beta {
  display: block; font-size: 0.5rem; margin: 1px 0 0 0; line-height: 1;
  text-transform: lowercase; opacity: 0.85;
}
.lang-switch .lang-opt--active .lang-beta { color: #fff; }
"""


# ------------------------------------------------------- support / donate block

def support_block() -> str:
    """Support/donate block placed directly above the footer on BOTH page types
    (index + dossier) and BOTH languages. An inverted black call-out card, white text
    throughout, framed by thin white top + bottom rules so it reads as distinct furniture,
    not part of the footer. A display heading, one honest mono line, a full-width primary
    Liberapay button (♥, opens in a new tab), a quiet inline Ko-fi one-time link beneath
    it, and a left-bar blockquote explaining the recurring/one-time split. Localised via
    the label map (English is identity); built here once so index + dossier stay byte
    identical, the same way the DE/EN switch is shared."""
    heading = L("ui", "support_heading", "Keep it independent.")
    line = L(
        "ui", "support_line",
        "No ads, no investors, no paywall. Donations cover the daily running costs "
        "and keep Independent Wire independent.",
    )
    button = L("ui", "support_button", "Donate via Liberapay")
    kofi_intro = L("ui", "support_kofi_intro", "Prefer to give once?")
    button_kofi = L("ui", "support_button_kofi", "One-time via Ko-fi")
    choice = L(
        "ui", "support_choice",
        "Liberapay is for recurring support — our preferred home. Ko-fi covers "
        "one-time gifts (and recurring too, if you'd rather).",
    )
    return (
        '<section class="support-block" aria-label="Support Independent Wire">\n'
        f'  <p class="support-heading">{heading}</p>\n'
        f'  <p class="support-line">{line}</p>\n'
        '  <a class="support-btn" href="https://liberapay.com/independent-wire.org/donate" '
        'target="_blank" rel="noopener">'
        f'<span class="support-btn-heart" aria-hidden="true">♥</span> {button}</a>\n'
        '  <p class="support-kofi">'
        f'{kofi_intro} '
        '<a class="support-kofi-link" href="https://ko-fi.com/independentwire" '
        f'target="_blank" rel="noopener">{button_kofi} <span aria-hidden="true">→</span></a>'
        '</p>\n'
        f'  <blockquote class="support-choice">{choice}</blockquote>\n'
        '</section>\n'
    )


def support_block_css() -> str:
    """CSS for support_block(); injected into both render.py's page CSS and publish.py's
    index CSS — same shared-furniture pattern as lang_switch_css()."""
    return """
/* Support / donate block — inverted black call-out card directly above the footer on
   both page types. Thin white top + bottom rules (inset by the block's horizontal
   padding) frame the card so it reads as distinct furniture, not part of the footer. */
.support-block {
  margin-top: 3rem;
  background: #000;
  color: #fff;
  padding: 2.25rem 2rem;
}
.support-block::before,
.support-block::after {
  content: "";
  display: block;
  border-top: 1.5px solid #fff;
}
.support-block::before { margin-bottom: 1.75rem; }
.support-block::after { margin-top: 1.75rem; }
.support-block .support-heading {
  font-family: var(--font-sans);
  font-size: 1.75rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.15;
  color: #fff;
  margin: 0 0 0.75rem;
}
.support-block .support-line {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  line-height: 1.6;
  color: #fff;
  margin: 0 0 1.5rem;
  max-width: 62ch;
}
/* Primary (Liberapay) button — full-width white fill, black text, mono uppercase.
   Hover inverts to a white-outlined black button, matching the approved hover feel. */
.support-block .support-btn {
  display: block;
  width: 100%;
  box-sizing: border-box;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  background: #fff;
  color: #000;
  text-decoration: none;
  padding: 1.1rem 1.5rem;
  min-height: 44px;
  border: 1.5px solid #fff;
  transition: background 120ms ease, color 120ms ease;
}
.support-block .support-btn .support-btn-heart { margin-right: 0.5em; }
.support-block .support-btn:hover { background: #000; color: #fff; }
.support-block .support-btn:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
/* Ko-fi — demoted to a quiet inline one-time link beneath the primary button. */
.support-block .support-kofi {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  line-height: 1.6;
  color: #fff;
  margin: 0.85rem 0 0;
}
.support-block .support-kofi-link {
  color: #fff;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.support-block .support-kofi-link:hover { text-decoration: none; }
.support-block .support-kofi-link:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
/* Choice line as a left-bar blockquote — muted grey, quiet, mono. */
.support-block .support-choice {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  line-height: 1.5;
  color: #999;
  border-left: 3px solid #fff;
  padding-left: 1rem;
  margin: 1.5rem 0 0;
  max-width: 72ch;
}
"""
