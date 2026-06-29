"""Tests for the clustering translate-to-English sidecar
(TASK-CLUSTER-TRANSLATE-SIDECAR, src/stages/translate_sidecar.py).

No torch / transformers required — the translation backend is injected as a
fake. Covers: flag gating, content-hash cache (hit/miss/persist), graceful
degradation (no backend / backend error), the isolation-preserving
effective-finding helper, the stage no-op, and consumer wiring (pre_cluster
embeds English when the slot is populated).
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from src.bus import RunBus
from src.stages import translate_sidecar as ts


# ── Fakes ─────────────────────────────────────────────────────────────────
class FakeBackend:
    """Deterministic stand-in for NLLB: prefixes ``EN[<flores>]:`` so tests can
    assert the English text propagated. Records call count + segment count."""

    name = "fake"

    def __init__(self):
        self.calls = 0
        self.segments = 0

    def translate(self, texts, src_flores):
        self.calls += 1
        self.segments += len(texts)
        return [f"EN[{src_flores}]:{t}" if t else "" for t in texts]


class RaisingBackend:
    name = "raising"

    def translate(self, texts, src_flores):
        raise RuntimeError("backend boom")


class RecordingEmbedder:
    """Captures the texts handed to embed_batch; returns distinct unit-ish
    vectors so AgglomerativeClustering has something to chew on."""

    model_name = "fake-embedder"

    def __init__(self):
        self.seen: list[str] = []

    def embed_batch(self, texts):
        self.seen = list(texts)
        n = len(texts)
        return np.eye(n, 8, dtype=np.float64) + 0.01


def _findings(*specs):
    """specs: (language, title, summary) → finding dicts."""
    return [{"language": lg, "title": t, "summary": s} for lg, t, s in specs]


# ── Flag gating + pure helpers ────────────────────────────────────────────
def test_is_enabled_default_off(monkeypatch):
    monkeypatch.delenv(ts.ENABLE_ENV, raising=False)
    assert ts.is_enabled() is False


@pytest.mark.parametrize("val,expected", [("1", True), ("true", True), ("YES", True),
                                          ("0", False), ("", False), ("off", False)])
def test_is_enabled_reads_env(monkeypatch, val, expected):
    monkeypatch.setenv(ts.ENABLE_ENV, val)
    assert ts.is_enabled() is expected


def test_norm_lang_aliases():
    assert ts.norm_lang("English") == "en"
    assert ts.norm_lang("EN") == "en"
    assert ts.norm_lang("bn") == "bn"
    assert ts.norm_lang("  Arabic ") == "ar"
    assert ts.norm_lang(None) == "en"


def test_content_key_stable_and_discriminating():
    k1 = ts.content_key("bn", "title", "summary")
    assert k1 == ts.content_key("bn", "title", "summary")  # stable
    assert k1 != ts.content_key("ar", "title", "summary")  # lang-sensitive
    assert k1 != ts.content_key("bn", "title2", "summary")  # title-sensitive
    assert k1 != ts.content_key("bn", "title", "summary2")  # summary-sensitive


# ── effective-finding / clustering_findings ───────────────────────────────
def test_clustering_findings_none_when_slot_empty():
    rb = RunBus()
    rb.curator_findings = _findings(("bn", "t", "s"))
    assert rb.curator_findings_clustering == []
    assert ts.clustering_findings(rb) is None


def test_clustering_findings_substitutes_english_and_falls_back():
    rb = RunBus()
    rb.curator_findings = _findings(("bn", "native-t", "native-s"),
                                    ("en", "eng-t", "eng-s"))
    rb.curator_findings_clustering = [
        {"title": "EN-t", "summary": "EN-s", "translated": True, "src_lang": "bn"},
        {"title": "eng-t", "summary": "eng-s", "translated": False, "src_lang": "en"},
    ]
    eff = ts.clustering_findings(rb)
    # translated finding → English title/summary, description blanked
    assert eff[0]["title"] == "EN-t" and eff[0]["summary"] == "EN-s"
    assert eff[0]["description"] == ""
    # untranslated finding → native, untouched
    assert eff[1] == rb.curator_findings[1]


# ── translate_findings core ───────────────────────────────────────────────
def test_translate_findings_fresh_then_cache_hit(tmp_path):
    cache_file = tmp_path / "c.json"
    fs = _findings(("bn", "ব", "সংক্ষিপ্ত"), ("ar", "عنوان", "ملخص"))
    bk = FakeBackend()

    entries, stats = ts.translate_findings(fs, cache_file=cache_file, backend=bk)
    assert all(e["translated"] for e in entries)
    assert entries[0]["title"].startswith("EN[ben_Beng]:")
    assert entries[1]["title"].startswith("EN[arb_Arab]:")
    assert stats["n_translated_fresh"] == 2
    assert stats["n_translated_cache_hit"] == 0
    assert cache_file.exists()
    # one batch per FLORES code (bn, ar) → 2 calls, 4 segments
    assert bk.calls == 2 and bk.segments == 4

    # second run with a fresh backend → all cache hits, backend untouched
    bk2 = FakeBackend()
    entries2, stats2 = ts.translate_findings(fs, cache_file=cache_file, backend=bk2)
    assert stats2["n_translated_cache_hit"] == 2 and stats2["n_translated_fresh"] == 0
    assert bk2.calls == 0
    assert entries2[0]["title"] == entries[0]["title"]


def test_translate_findings_native_passthrough_reasons(tmp_path):
    fs = _findings(
        ("en", "english title", "english summary"),   # english
        ("xx", "unknown lang", "s"),                    # no FLORES mapping
        ("bn", "", ""),                                  # empty text
    )
    bk = FakeBackend()
    entries, stats = ts.translate_findings(fs, cache_file=tmp_path / "c.json", backend=bk)
    assert all(not e["translated"] for e in entries)
    assert stats["n_native_fallback"] == 3
    assert stats["native_reasons"]["english"] == 1
    assert stats["native_reasons"]["no_flores_mapping"] == 1
    assert stats["native_reasons"]["empty_text"] == 1
    assert bk.calls == 0  # nothing eligible to translate


def test_translate_findings_no_backend_degrades_to_native(tmp_path):
    fs = _findings(("bn", "ব", "স"))
    entries, stats = ts.translate_findings(
        fs, cache_file=tmp_path / "c.json", backend=None
    )
    # backend=None means caller passed nothing; module resolves singleton.
    # In CI no torch is installed → resolves to None → native fallback.
    assert entries[0]["translated"] is False
    assert stats["n_native_fallback"] == 1
    assert stats["native_reasons"].get("no_backend") == 1


def test_translate_findings_backend_error_degrades(tmp_path):
    fs = _findings(("bn", "ব", "স"), ("ar", "ع", "م"))
    entries, stats = ts.translate_findings(
        fs, cache_file=tmp_path / "c.json", backend=RaisingBackend()
    )
    assert all(e["translated"] is False for e in entries)
    assert stats["native_reasons"].get("backend_error") == 2


def test_translate_findings_title_summary_separate_segments(tmp_path):
    """Title and summary are translated as distinct segments so the Curator's
    sample-title gets a clean English title."""
    fs = _findings(("bn", "TITLE", "SUMMARY"))
    bk = FakeBackend()
    entries, _ = ts.translate_findings(fs, cache_file=tmp_path / "c.json", backend=bk)
    assert entries[0]["title"] == "EN[ben_Beng]:TITLE"
    assert entries[0]["summary"] == "EN[ben_Beng]:SUMMARY"
    assert bk.segments == 2


# ── The stage ─────────────────────────────────────────────────────────────
def test_stage_disabled_is_noop(monkeypatch):
    monkeypatch.delenv(ts.ENABLE_ENV, raising=False)
    rb = RunBus()
    rb.curator_findings = _findings(("bn", "ব", "স"))
    out = asyncio.run(ts.translate_findings_sidecar(rb))
    assert out.curator_findings_clustering == []
    # curator_findings untouched
    assert out.curator_findings == rb.curator_findings


def test_stage_enabled_populates_slot(monkeypatch, tmp_path):
    monkeypatch.setenv(ts.ENABLE_ENV, "1")
    monkeypatch.setenv(ts.CACHE_ENV, str(tmp_path / "c.json"))
    bk = FakeBackend()
    monkeypatch.setattr(ts, "_resolve_backend", lambda: bk)
    rb = RunBus()
    rb.curator_findings = _findings(("bn", "ব", "স"), ("en", "e", "e"))
    out = asyncio.run(ts.translate_findings_sidecar(rb))
    clt = out.curator_findings_clustering
    assert len(clt) == 2
    assert clt[0]["translated"] is True and clt[0]["title"].startswith("EN[")
    assert clt[1]["translated"] is False  # english passthrough
    # original-language findings still byte-identical (isolation firewall)
    assert out.curator_findings[0]["title"] == "ব"


# ── Consumer wiring: pre_cluster embeds English when slot populated ────────
def test_pre_cluster_embeds_english_when_slot_populated():
    from src.stages.pre_cluster import make_pre_cluster_findings

    emb = RecordingEmbedder()
    stage = make_pre_cluster_findings(embedder=emb, distance_threshold=0.5)
    rb = RunBus()
    rb.curator_findings = _findings(("bn", "native-bengali", "native-sum"),
                                    ("ar", "native-arabic", "native-sum2"))
    rb.curator_findings_clustering = [
        {"title": "english one", "summary": "es1", "translated": True, "src_lang": "bn"},
        {"title": "english two", "summary": "es2", "translated": True, "src_lang": "ar"},
    ]
    asyncio.run(stage(rb))
    joined = " ".join(emb.seen)
    assert "english one" in joined and "english two" in joined
    assert "native-bengali" not in joined  # native text did NOT reach the embedder


def test_pre_cluster_embeds_native_when_slot_empty():
    from src.stages.pre_cluster import make_pre_cluster_findings

    emb = RecordingEmbedder()
    stage = make_pre_cluster_findings(embedder=emb, distance_threshold=0.5)
    rb = RunBus()
    rb.curator_findings = _findings(("bn", "native-bengali", "s"))
    asyncio.run(stage(rb))
    assert any("native-bengali" in t for t in emb.seen)


# ── Cache file format ─────────────────────────────────────────────────────
def test_cache_file_roundtrip(tmp_path):
    cache_file = tmp_path / "c.json"
    fs = _findings(("bn", "ব", "স"))
    ts.translate_findings(fs, cache_file=cache_file, backend=FakeBackend())
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data["model"] == ts.MODEL_NAME
    assert len(data["entries"]) == 1
    loaded = ts.load_cache(cache_file)
    key = ts.content_key("bn", "ব", "স")
    assert loaded[key]["title_en"].startswith("EN[")
