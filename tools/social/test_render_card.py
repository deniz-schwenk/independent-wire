"""Acceptance + smoke tests for the SETN card renderer.

Runs at unit-test level (no pipeline). Needs the tool's own environment:

    pip install -r requirements.txt && playwright install chromium
    pip install pytest
    pytest tools/social/test_render_card.py

Covers task acceptance: 1080x1080 output, RTL Farsi, auto/forced layout,
determinism (pixel-identical on the same machine), zero network, unknown-field
tolerance, and input-string immutability.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import render_card as rc

HERE = Path(__file__).resolve().parent
TESTDATA = HERE / "testdata"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ── pure-Python page assembly (no browser) ───────────────────────────────────
def test_build_page_does_not_modify_input_strings():
    """The verbatim RTL string (RLM + typographic quotes) must appear in the
    embedded card data exactly — no quote insertion, no RLM/mark trimming."""
    card = json.loads((TESTDATA / "rtl_farsi.json").read_text(encoding="utf-8"))
    page = rc._build_page(card)
    assert card["originalB"] == "‏“دزدی دریایی”"
    # exact string embedded (JSON-encoded, so match the escaped form)
    assert json.dumps(card["originalB"], ensure_ascii=False)[1:-1] in page
    # fonts inlined as data: URIs, zero external refs
    assert "data:font/woff2;base64," in page
    assert "__FONTFACE__" not in page and "__CARD_JSON__" not in page
    assert "http://" not in page and "https://" not in page


def test_build_page_ignores_unknown_fields():
    """A card with an extra `delivery` block builds without error and does not
    leak the unknown block into the embedded card data."""
    card = json.loads((TESTDATA / "rtl_farsi.json").read_text(encoding="utf-8"))
    assert "delivery" in card  # fixture carries an unknown block
    page = rc._build_page(card)
    assert "delivery" not in page


# ── rendered-output acceptance (browser) ─────────────────────────────────────
@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp("cards")
    meta = {}
    for jf in sorted(TESTDATA.glob("*.json")):
        meta[jf.stem] = rc.render_card(jf, out / f"{jf.stem}.png")
    return meta


def test_all_cards_are_1080_square(rendered):
    for stem, meta in rendered.items():
        assert meta["width"] == 1080 and meta["height"] == 1080, stem
        assert Path(meta["out"]).exists()


def test_no_network_requests(rendered):
    """Acceptance #5: zero external requests during any render."""
    for stem, meta in rendered.items():
        assert meta["network_requests"] == [], (stem, meta["network_requests"])


def test_rtl_farsi_renders(rendered):
    """Acceptance #2: the real Farsi sample renders (auto → row here)."""
    m = rendered["rtl_farsi"]
    assert m["layout"] == "row"
    assert Path(m["out"]).stat().st_size > 0


def test_long_words_auto_switch_to_stacked(rendered):
    """Acceptance #3a: a long-word pair in auto mode stacks."""
    assert rendered["long_stacked"]["layout"] == "stacked"


def test_layout_row_forced(rendered):
    """Acceptance #3b: layout='row' forces row even for long words that would
    otherwise auto-stack."""
    assert rendered["layout_row"]["layout"] == "row"


def test_layout_stacked_forced(rendered):
    """Acceptance #3b: layout='stacked' forces stacked even for short words
    that would otherwise auto-row."""
    assert rendered["layout_stacked"]["layout"] == "stacked"


def test_determinism_pixel_identical(tmp_path):
    """Acceptance #4: same JSON twice on the same machine → identical PNG."""
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    rc.render_card(TESTDATA / "rtl_farsi.json", a)
    rc.render_card(TESTDATA / "rtl_farsi.json", b)
    assert _sha(a) == _sha(b)
