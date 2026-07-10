"""Shared helpers for the MADLAD shadow's ct2venv-side scripts (translate warm
+ control validation).

REBUILD NOTE (2026-07-05): the original scratch/madlad/ tree (CT2 model,
<2en> backend, shadow_run.sh, EMPIRICAL-RESULTS.md) was lost in the Jul-4
repo move to ~/iw/independent-wire (scratch reports were copied, the model
subtree was not). This file replicates the *pure* constants/functions of
src/stages/translate_sidecar.py (ENGLISH_LANGS / FLORES / norm_lang /
content_key) so the warm script can run inside the pinned conversion venv,
which has no pydantic/src deps. Equivalence with the real sidecar is
enforced at run time: shadow_chain.py (prod venv, real module) aborts if any
non-English finding misses the warmed cache — i.e. any key drift is loud,
never silent.

MADLAD-400 usage: target language via source prefix token, "<2en> " + text.
Deterministic decode: beam_size=4, no sampling — matches the sidecar's NLLB
settings (NUM_BEAMS=4, MAX_LENGTH=200) and the 2026-06-30 finalize report.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile

# Must equal src/stages/translate_sidecar.py::MODEL_NAME — it is baked into
# the content-hash cache key the real sidecar looks up.
SIDECAR_MODEL_NAME = "facebook/nllb-200-distilled-600M"

MADLAD_HF_ID = "google/madlad400-3b-mt"
NUM_BEAMS = 4
MAX_DECODING_LENGTH = 200

ENGLISH_LANGS = frozenset({"en", "eng", "english", "en-us", "en-gb", "en_us", "en_gb"})

FLORES = {
    "de": "deu_Latn", "es": "spa_Latn", "fr": "fra_Latn", "it": "ita_Latn",
    "pt": "por_Latn", "ru": "rus_Cyrl", "tr": "tur_Latn", "vi": "vie_Latn",
    "ko": "kor_Hang", "fa": "pes_Arab", "he": "heb_Hebr", "id": "ind_Latn",
    "zh": "zho_Hans", "ar": "arb_Arab", "bn": "ben_Beng", "ne": "npi_Deva",
    "sw": "swh_Latn", "uz": "uzn_Latn", "zu": "zul_Latn", "hi": "hin_Deva",
    "ur": "urd_Arab", "ta": "tam_Taml", "si": "sin_Sinh", "th": "tha_Thai",
    "ja": "jpn_Jpan", "ps": "pbt_Arab", "ky": "kir_Cyrl", "kk": "kaz_Cyrl",
    "tg": "tgk_Cyrl", "am": "amh_Ethi", "ha": "hau_Latn", "yo": "yor_Latn",
    "ig": "ibo_Latn", "so": "som_Latn", "rw": "kin_Latn", "pl": "pol_Latn",
    "nl": "nld_Latn", "uk": "ukr_Cyrl", "el": "ell_Grek",
}

_NAME_ALIASES = {
    "english": "en", "german": "de", "spanish": "es", "french": "fr",
    "italian": "it", "portuguese": "pt", "russian": "ru", "turkish": "tr",
    "vietnamese": "vi", "arabic": "ar", "chinese": "zh",
}


def norm_lang(raw) -> str:
    s = (str(raw) if raw is not None else "").strip().lower()
    if not s:
        return "en"
    return _NAME_ALIASES.get(s, s)


def content_key(lang: str, title: str, summary: str) -> str:
    payload = "\x1f".join((SIDECAR_MODEL_NAME, lang, title or "", summary or ""))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def translate_set(findings):
    """Index → (lang, title, summary, key) for every finding the real sidecar
    would translate (non-English, FLORES-mapped, non-empty text)."""
    out = {}
    for i, f in enumerate(findings):
        lang = norm_lang(f.get("language"))
        title = f.get("title") or ""
        summary = f.get("summary") or ""
        if lang in ENGLISH_LANGS or lang not in FLORES:
            continue
        if not (title.strip() or summary.strip()):
            continue
        out[i] = (lang, title, summary, content_key(lang, title, summary))
    return out


def load_cache(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, ValueError, OSError):
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def save_cache(entries, path):
    """Atomic write, same payload shape as the real sidecar's save_cache."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"model": SIDECAR_MODEL_NAME, "version": 1, "entries": entries}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


class MadladCT2:
    """CT2-int8 MADLAD translator, deterministic beam decode."""

    def __init__(self, model_dir: str):
        import ctranslate2
        from transformers import AutoTokenizer

        self._translator = ctranslate2.Translator(model_dir, device="cpu")
        self._tok = AutoTokenizer.from_pretrained(MADLAD_HF_ID)

    def translate(self, texts, max_batch_size: int = 64):
        """texts → English. Empty/whitespace inputs come back as ''."""
        idx_map = [i for i, t in enumerate(texts) if (t or "").strip()]
        out = [""] * len(texts)
        if not idx_map:
            return out
        tokenised = [
            self._tok.convert_ids_to_tokens(self._tok.encode("<2en> " + texts[i]))
            for i in idx_map
        ]
        results = self._translator.translate_batch(
            tokenised,
            beam_size=NUM_BEAMS,
            max_decoding_length=MAX_DECODING_LENGTH,
            max_batch_size=max_batch_size,
        )
        for pos, r in zip(idx_map, results):
            ids = self._tok.convert_tokens_to_ids(r.hypotheses[0])
            out[pos] = self._tok.decode(ids, skip_special_tokens=True).strip()
        return out
