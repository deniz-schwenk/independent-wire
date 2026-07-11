"""Vendored MADLAD-400 ``<2en>`` tokenizer-equivalence test
(Acceptance #1 of TASK-MADLAD-ENABLE-PREP).

Proves the production sentencepiece-only tokenization path
(``src/stages/translate_sidecar._madlad_encode`` / ``_madlad_decode``) reproduces
the frozen transformers-derived reference in
``tests/data/madlad_tok_equiv_golden.json`` — WITHOUT importing torch or
transformers. Requires only ``sentencepiece`` and the pinned 256000-vocab
``spiece.model``. When either is absent (e.g. the default production ``.venv``,
which has no ``multilingual`` extra) the tests skip cleanly — loud under
``pytest -rs``, never a silent pass.

The golden was captured from ``transformers.AutoTokenizer(google/madlad400-3b-mt)``
and verified byte-identical to the sentencepiece path at capture time; this test
re-derives it with sentencepiece ONLY, so it also guards against a wrong/rotated
``spiece.model`` (a mismatched spm silently corrupts token ids).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from src.stages import translate_sidecar as ts

_GOLDEN = Path(__file__).parent / "data" / "madlad_tok_equiv_golden.json"


def _find_spiece() -> str | None:
    """Resolve spiece.model: explicit env → configured CT2 dir → HF hub cache."""
    env = os.environ.get(ts.SPIECE_ENV, "").strip()
    if env and Path(env).exists():
        return env
    ct2 = os.environ.get(ts.CT2_DIR_ENV, "").strip()
    if ct2 and (Path(ct2) / "spiece.model").exists():
        return str(Path(ct2) / "spiece.model")
    home = os.path.expanduser("~/.cache/huggingface")
    hits = glob.glob(
        f"{home}/**/models--google--madlad400-3b-mt/**/spiece.model", recursive=True
    )
    return hits[0] if hits else None


@pytest.fixture(scope="module")
def golden():
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def madlad_sp():
    spm = pytest.importorskip(
        "sentencepiece", reason="sentencepiece not installed (needs the 'multilingual' extra)"
    )
    spiece = _find_spiece()
    if not spiece:
        pytest.skip(
            f"spiece.model not found (set {ts.SPIECE_ENV} or {ts.CT2_DIR_ENV}/spiece.model)"
        )
    proc = spm.SentencePieceProcessor()
    proc.Load(spiece)
    return proc, spiece


def test_torch_transformers_not_required():
    """The tokenization path must not pull torch/transformers into the process —
    the whole point of the sentencepiece-only backend (spec §3)."""
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_spiece_matches_frozen_vocab(golden, madlad_sp):
    _, spiece = madlad_sp
    sha = hashlib.sha256(Path(spiece).read_bytes()).hexdigest()
    assert sha == golden["spiece_sha256"], (
        "spiece.model vocab mismatch vs the frozen reference — a wrong spm "
        "silently corrupts token ids into garbage translations"
    )


def test_special_piece_ids(golden, madlad_sp):
    sp, _ = madlad_sp
    for piece, expected in golden["special_pieces"].items():
        assert sp.piece_to_id(piece) == expected, f"{piece} id drifted"


def test_encode_matches_golden(golden, madlad_sp):
    sp, _ = madlad_sp
    for case in golden["cases"]:
        pieces = ts._madlad_encode(sp, case["text"])
        assert pieces == case["pieces"], (
            f"encode mismatch for {case['lang']}: {case['text']!r}"
        )
        ids = [sp.piece_to_id(p) for p in pieces]
        assert ids == case["ids"], f"id mismatch for {case['lang']}"
        assert pieces[-1] == golden["eos_piece"]
        assert golden["target_prefix"] in pieces  # <2en> source-prefix present


def test_decode_roundtrip_matches_golden(golden, madlad_sp):
    sp, _ = madlad_sp
    for case in golden["cases"]:
        decoded = ts._madlad_decode(sp, case["pieces"])
        assert decoded == case["decode_roundtrip"], f"decode mismatch for {case['lang']}"
