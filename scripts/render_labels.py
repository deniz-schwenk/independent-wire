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
