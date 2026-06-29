"""Clustering translate-to-English sidecar — NLLB-local, isolated, flagged.

Authoritative reference: TASK-CLUSTER-TRANSLATE-SIDECAR.md.
Empirical basis: scratch/feed-batch1/REPORT-TRANSLATE-EVAL.md
(TASK-CLUSTER-TRANSLATE-EVAL) — embedding an English translation of each
finding closes the genuine embedding-bridge gap (Bengali 0 → 5-6 attach) with
no regression on the working languages (ar/ne hold and sharpen), and a local
NLLB-200 matches reliable translation on attach at zero per-run cost.

What this stage does
--------------------
Runs after ``fetch_findings`` and BEFORE ``pre_cluster_findings``. For every
``curator_finding`` it produces an English-normalised ``{title, summary}`` and
writes a per-finding parallel record to the ``curator_findings_clustering``
RunBus slot. The three embedding consumers — ``pre_cluster_findings``,
``CuratorTopicDiscoveryStage``, ``gravitational_assign`` — read that slot (via
:func:`clustering_findings`) and embed the English text instead of the native
text. The original-language ``curator_findings`` slot is **never mutated**.

Isolation firewall (the contract)
----------------------------------
The English translation is a clustering-internal field only. It lives solely in
``curator_findings_clustering`` (visibility ``internal``) and is consumed ONLY
by the three clustering stages. It never reaches any RunBus/TopicBus slot read
by the synthesis agents (Editor / Perspektiv / Writer / Bias) — their inputs
stay the original-language text, unchanged. ``curator_findings`` passes through
byte-identical.

Flag / default-off
------------------
Disabled by default. Enabled only when ``IW_CLUSTER_TRANSLATE`` is truthy
(``1`` / ``true`` / ``yes``) **and** the stage is wired into the stage list
(``build_production_stages(..., translate_sidecar=True)`` or the same env var).
When disabled the stage is a pure no-op: it writes an empty slot, imports no
translation runtime, and the consumers fall through to today's native-text
behaviour byte-for-byte.

Determinism + cache
-------------------
NLLB runs with a fixed beam (``num_beams=4``, ``do_sample=False``) so output is
reproducible. A persistent JSON cache keyed by a content-hash of
``(model, lang, title, summary)`` means each unique finding is translated once;
repeats across days are free and clustering stays reproducible. Cache path:
``IW_CLUSTER_TRANSLATE_CACHE`` or ``output/_translate_cache/<model>.json``.

Graceful degradation
---------------------
If translation is unavailable (no backend installed) or errors for a finding,
the stage falls back to embedding that finding's native text (today's
behaviour) and logs the fallback. The pipeline never crashes because translation
failed. English findings and findings whose language has no FLORES-200 mapping
also pass through as native (no-op).

Runtime / dependencies
----------------------
The translation backend is an **optional, lazily-imported** dependency — the
default-off path adds nothing to the pinned dependency set. Backend resolution
prefers a lean CTranslate2 NLLB model (``IW_CLUSTER_TRANSLATE_CT2_DIR`` pointing
at a converted model) and falls back to ``transformers`` + ``torch`` (the
runtime the eval used). The pinned fastembed embedder is untouched — the sidecar
only feeds English text INTO it. One backend instance per process (module
singleton) keeps the one-runtime-per-process invariant.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)

# repo root: src/stages/translate_sidecar.py -> parents[2]
_REPO = Path(__file__).resolve().parents[2]

# ── Configuration ─────────────────────────────────────────────────────────
ENABLE_ENV = "IW_CLUSTER_TRANSLATE"
CACHE_ENV = "IW_CLUSTER_TRANSLATE_CACHE"
CT2_DIR_ENV = "IW_CLUSTER_TRANSLATE_CT2_DIR"

MODEL_NAME = "facebook/nllb-200-distilled-600M"
"""NLLB-200 distilled 600M — the model validated in the translate eval. Local,
deterministic, no API key. Pinned here so a model change explicitly invalidates
the content-hash cache (the model name is part of the cache key)."""

TARGET_FLORES = "eng_Latn"
NUM_BEAMS = 4
MAX_LENGTH = 200
TRANSLATE_BATCH = 16
MAX_ATTEMPTS_NOTE = "no retry — deterministic beam; fall back to native on error"

_TRUTHY = {"1", "true", "yes", "on", "y", "t"}

# Languages that are already English — no translation, native passes through.
ENGLISH_LANGS = frozenset({"en", "eng", "english", "en-us", "en-gb", "en_us", "en_gb"})

# ISO-639-1 (and a few full-name aliases) → FLORES-200 source code. Covers the
# production source pool (en/de/es/fr/it/pt/ru/tr/vi + ko/fa/he/id/zh) and the
# batch-1 diversification languages (ar/bn/ne/sw/uz/zu/zh) plus common
# neighbours. A language absent from this map falls back to native (logged once).
FLORES: dict[str, str] = {
    # production pool
    "de": "deu_Latn",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "ru": "rus_Cyrl",
    "tr": "tur_Latn",
    "vi": "vie_Latn",
    "ko": "kor_Hang",
    "fa": "pes_Arab",
    "he": "heb_Hebr",
    "id": "ind_Latn",
    "zh": "zho_Hans",
    # batch-1 diversification + South/Central Asia, MENA, Sub-Saharan Africa
    "ar": "arb_Arab",
    "bn": "ben_Beng",
    "ne": "npi_Deva",
    "sw": "swh_Latn",
    "uz": "uzn_Latn",
    "zu": "zul_Latn",
    "hi": "hin_Deva",
    "ur": "urd_Arab",
    "ta": "tam_Taml",
    "si": "sin_Sinh",
    "th": "tha_Thai",
    "ja": "jpn_Jpan",
    "ps": "pbt_Arab",
    "ky": "kir_Cyrl",
    "kk": "kaz_Cyrl",
    "tg": "tgk_Cyrl",
    "am": "amh_Ethi",
    "ha": "hau_Latn",
    "yo": "yor_Latn",
    "ig": "ibo_Latn",
    "so": "som_Latn",
    "rw": "kin_Latn",
    "pl": "pol_Latn",
    "nl": "nld_Latn",
    "uk": "ukr_Cyrl",
    "el": "ell_Grek",
}

# A few full language-name aliases seen in real feed metadata (e.g. the literal
# value "English" tagged on some sources). Normalised before the FLORES lookup.
_NAME_ALIASES: dict[str, str] = {
    "english": "en",
    "german": "de",
    "spanish": "es",
    "french": "fr",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "turkish": "tr",
    "vietnamese": "vi",
    "arabic": "ar",
    "chinese": "zh",
}


# ── Flag + path helpers (pure) ────────────────────────────────────────────
def is_enabled() -> bool:
    """True iff the sidecar flag env var is truthy. Default off."""
    return os.environ.get(ENABLE_ENV, "").strip().lower() in _TRUTHY


def cache_path() -> Path:
    """Persistent translation-cache path. Override via ``IW_CLUSTER_TRANSLATE_CACHE``."""
    override = os.environ.get(CACHE_ENV, "").strip()
    if override:
        return Path(override)
    safe_model = MODEL_NAME.replace("/", "__")
    return _REPO / "output" / "_translate_cache" / f"{safe_model}.json"


def norm_lang(raw: Any) -> str:
    """Lowercase + strip + resolve a few full-name aliases to ISO-639-1."""
    s = (str(raw) if raw is not None else "").strip().lower()
    if not s:
        return "en"
    if s in _NAME_ALIASES:
        return _NAME_ALIASES[s]
    return s


def content_key(lang: str, title: str, summary: str) -> str:
    """SHA-256 content-hash of ``(model, lang, title, summary)``. The model name
    is part of the key so a model swap invalidates stale translations rather
    than silently serving them."""
    payload = "\x1f".join((MODEL_NAME, lang, title or "", summary or ""))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Cache I/O (pure) ──────────────────────────────────────────────────────
def load_cache(path: Optional[Path] = None) -> dict[str, dict]:
    """Load the ``{key: {title_en, summary_en, src_lang}}`` cache. Missing or
    unreadable cache → empty dict (never raises — a corrupt cache must not
    crash the pipeline; it just re-translates)."""
    p = path or cache_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning("translate_sidecar: cache unreadable at %s (%s); ignoring", p, exc)
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def save_cache(entries: dict[str, dict], path: Optional[Path] = None) -> None:
    """Atomically persist the cache (tmp file + rename). Best-effort — a write
    failure is logged, not raised."""
    p = path or cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"model": MODEL_NAME, "version": 1, "entries": entries}
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError as exc:
        logger.warning("translate_sidecar: could not persist cache to %s (%s)", p, exc)


# ── Effective-finding helper (pure) — consumed by the clustering stages ───
def _effective_finding(native: dict, entry: Optional[dict]) -> dict:
    """Return the finding dict the clustering stages should embed.

    When ``entry`` is a successful translation, substitute the English
    title/summary over the native finding and blank ``description`` (real RSS
    findings carry no description; blanking guards against any native-text leak
    into the embedded string). Otherwise return the native finding unchanged."""
    if entry and entry.get("translated"):
        return {
            **native,
            "title": entry.get("title") or native.get("title") or "",
            "summary": entry.get("summary") or native.get("summary") or "",
            "description": "",
        }
    return native


def clustering_findings(run_bus: Any) -> Optional[list[dict]]:
    """Index-aligned list of effective finding dicts for the clustering stages,
    or ``None`` when the sidecar slot is empty (disabled / no-op) so the caller
    falls through to ``curator_findings`` unchanged.

    The returned list is the same length and order as ``curator_findings`` —
    ``finding-NNN`` source-id alignment is preserved."""
    native = list(getattr(run_bus, "curator_findings", None) or [])
    clt = list(getattr(run_bus, "curator_findings_clustering", None) or [])
    if not clt:
        return None
    out: list[dict] = []
    for i, f in enumerate(native):
        entry = clt[i] if i < len(clt) else None
        out.append(_effective_finding(f, entry))
    return out


# ── Translation backend (optional, lazily imported) ───────────────────────
class _Backend(Protocol):
    name: str

    def translate(self, texts: Sequence[str], src_flores: str) -> list[str]:
        ...


class _CTranslate2NLLB:
    """Lean CTranslate2 NLLB backend — preferred when a converted model dir is
    available (``IW_CLUSTER_TRANSLATE_CT2_DIR``) and ``ctranslate2`` +
    ``transformers`` (tokenizer only) are importable. Lower footprint than full
    torch inference."""

    name = "ctranslate2"

    def __init__(self, model_dir: str) -> None:
        import ctranslate2  # noqa: F401 — availability probe
        from transformers import AutoTokenizer

        self._ct2 = __import__("ctranslate2")
        self._translator = self._ct2.Translator(model_dir, device="cpu")
        self._tok = AutoTokenizer.from_pretrained(MODEL_NAME)

    def translate(self, texts: Sequence[str], src_flores: str) -> list[str]:
        self._tok.src_lang = src_flores
        out: list[str] = []
        for i in range(0, len(texts), TRANSLATE_BATCH):
            chunk = list(texts[i : i + TRANSLATE_BATCH])
            tokenised = [
                self._tok.convert_ids_to_tokens(self._tok.encode(t)) for t in chunk
            ]
            results = self._translator.translate_batch(
                tokenised,
                target_prefix=[[TARGET_FLORES]] * len(tokenised),
                beam_size=NUM_BEAMS,
                max_decoding_length=MAX_LENGTH,
            )
            for r in results:
                toks = r.hypotheses[0]
                if toks and toks[0] == TARGET_FLORES:
                    toks = toks[1:]
                out.append(self._tok.decode(self._tok.convert_tokens_to_ids(toks)).strip())
        return out


class _TransformersNLLB:
    """transformers + torch NLLB backend — the runtime the eval used. Heavier
    than CTranslate2 but already proven. Deterministic (num_beams=4,
    do_sample=False)."""

    name = "transformers"

    def __init__(self) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
        self._model.eval()
        self._bos = self._tok.convert_tokens_to_ids(TARGET_FLORES)

    def translate(self, texts: Sequence[str], src_flores: str) -> list[str]:
        self._tok.src_lang = src_flores
        out: list[str] = []
        for i in range(0, len(texts), TRANSLATE_BATCH):
            chunk = list(texts[i : i + TRANSLATE_BATCH])
            enc = self._tok(
                chunk, return_tensors="pt", padding=True, truncation=True, max_length=128
            )
            with self._torch.no_grad():
                gen = self._model.generate(
                    **enc,
                    forced_bos_token_id=self._bos,
                    num_beams=NUM_BEAMS,
                    do_sample=False,
                    max_length=MAX_LENGTH,
                )
            out.extend(t.strip() for t in self._tok.batch_decode(gen, skip_special_tokens=True))
        return out


# Module-singleton backend (one runtime per process). Sentinel distinguishes
# "not yet probed" from "probed, none available".
_BACKEND: Any = "__unprobed__"


def _resolve_backend() -> Optional[_Backend]:
    """Resolve the translation backend once per process: CTranslate2 (preferred)
    → transformers → None. ``None`` means no runtime is installed; callers must
    fall back to native text. Never raises."""
    global _BACKEND
    if _BACKEND != "__unprobed__":
        return _BACKEND

    ct2_dir = os.environ.get(CT2_DIR_ENV, "").strip()
    if ct2_dir:
        try:
            _BACKEND = _CTranslate2NLLB(ct2_dir)
            logger.info("translate_sidecar: backend=ctranslate2 (%s)", ct2_dir)
            return _BACKEND
        except Exception as exc:  # noqa: BLE001 — any import/load failure → next backend
            logger.warning("translate_sidecar: ctranslate2 backend unavailable (%s)", exc)

    try:
        _BACKEND = _TransformersNLLB()
        logger.info("translate_sidecar: backend=transformers (%s)", MODEL_NAME)
        return _BACKEND
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "translate_sidecar: no translation backend available (%s); "
            "findings will embed native text (graceful degradation)",
            exc,
        )
        _BACKEND = None
        return None


def _reset_backend_for_tests() -> None:
    """Test hook — clear the module-singleton backend probe."""
    global _BACKEND
    _BACKEND = "__unprobed__"


# ── The translation core (env-independent; reused by the validation warmer) ─
def translate_findings(
    findings: list[dict],
    *,
    cache: Optional[dict[str, dict]] = None,
    cache_file: Optional[Path] = None,
    backend: Optional[_Backend] = None,
    persist: bool = True,
) -> tuple[list[dict], dict[str, Any]]:
    """Pure-ish core: translate ``findings`` → per-finding clustering records.

    Returns ``(entries, stats)``. ``entries`` is index-aligned with ``findings``;
    each entry is::

        {"title": <en|native>, "summary": <en|native>,
         "translated": bool, "src_lang": <iso>, "reason": <why-native|None>}

    ``backend`` is injected by tests; production passes ``None`` and the module
    resolves the singleton. Cache hits never touch the backend. Misses are
    grouped by FLORES source-code and translated in one batch per language;
    title and summary are translated as separate segments so the Curator's
    sample-titles get a clean English title. Any backend error degrades that
    language group to native (logged), never raises."""
    path = cache_file or cache_path()
    cache = cache if cache is not None else load_cache(path)

    entries: list[Optional[dict]] = [None] * len(findings)
    # finding_index -> (lang, flores, title, summary, key)
    misses: list[tuple[int, str, str, str, str]] = []
    n_cache_hit = 0
    n_native = 0
    native_reasons: dict[str, int] = {}

    def _native(i: int, lang: str, reason: str) -> None:
        nonlocal n_native
        f = findings[i]
        entries[i] = {
            "title": f.get("title") or "",
            "summary": f.get("summary") or "",
            "translated": False,
            "src_lang": lang,
            "reason": reason,
        }
        n_native += 1
        native_reasons[reason] = native_reasons.get(reason, 0) + 1

    for i, f in enumerate(findings):
        lang = norm_lang(f.get("language"))
        title = f.get("title") or ""
        summary = f.get("summary") or ""
        if lang in ENGLISH_LANGS:
            _native(i, lang, "english")
            continue
        flores = FLORES.get(lang)
        if flores is None:
            _native(i, lang, "no_flores_mapping")
            continue
        if not (title.strip() or summary.strip()):
            _native(i, lang, "empty_text")
            continue
        key = content_key(lang, title, summary)
        hit = cache.get(key)
        if hit is not None:
            entries[i] = {
                "title": hit.get("title_en") or "",
                "summary": hit.get("summary_en") or "",
                "translated": True,
                "src_lang": lang,
                "reason": None,
            }
            n_cache_hit += 1
            continue
        misses.append((i, lang, flores, title, summary))

    n_fresh = 0
    cache_dirty = False
    if misses:
        bk = backend if backend is not None else _resolve_backend()
        if bk is None:
            for i, lang, _flores, _t, _s in misses:
                _native(i, lang, "no_backend")
        else:
            # group misses by FLORES source code (one src_lang per batch)
            by_flores: dict[str, list[tuple[int, str, str, str, str]]] = {}
            for m in misses:
                by_flores.setdefault(m[2], []).append(m)
            for flores, group in by_flores.items():
                seg_texts: list[str] = []
                seg_owner: list[tuple[int, str]] = []  # (finding_index, 't'|'s')
                for i, _lang, _fl, title, summary in group:
                    seg_texts.append(title)
                    seg_owner.append((i, "t"))
                    seg_texts.append(summary)
                    seg_owner.append((i, "s"))
                try:
                    translated = bk.translate(seg_texts, flores)
                    if len(translated) != len(seg_texts):
                        raise ValueError(
                            f"backend returned {len(translated)} segments for "
                            f"{len(seg_texts)} inputs"
                        )
                except Exception as exc:  # noqa: BLE001 — degrade this group to native
                    logger.error(
                        "translate_sidecar: backend error on %s (%d segments): %s "
                        "— falling back to native for this language group",
                        flores, len(seg_texts), exc,
                    )
                    for i, lang, _fl, _t, _s in group:
                        _native(i, lang, "backend_error")
                    continue
                # reassemble per finding
                per_finding: dict[int, dict[str, str]] = {}
                for (i, slot), text in zip(seg_owner, translated):
                    per_finding.setdefault(i, {})[slot] = text
                for i, lang, _fl, title, summary in group:
                    tr = per_finding.get(i, {})
                    title_en = tr.get("t", "").strip()
                    summary_en = tr.get("s", "").strip()
                    entries[i] = {
                        "title": title_en,
                        "summary": summary_en,
                        "translated": True,
                        "src_lang": lang,
                        "reason": None,
                    }
                    cache[content_key(lang, title, summary)] = {
                        "title_en": title_en,
                        "summary_en": summary_en,
                        "src_lang": lang,
                    }
                    cache_dirty = True
                    n_fresh += 1

    # Any still-None (shouldn't happen) → native guard
    for i, e in enumerate(entries):
        if e is None:
            _native(i, norm_lang(findings[i].get("language")), "unfilled")

    if cache_dirty and persist:
        save_cache(cache, path)

    stats = {
        "n_findings": len(findings),
        "n_translated_cache_hit": n_cache_hit,
        "n_translated_fresh": n_fresh,
        "n_native_fallback": n_native,
        "native_reasons": native_reasons,
        "cache_path": str(path),
        "model_name": MODEL_NAME,
    }
    return [e for e in entries], stats  # type: ignore[return-value]


# ── The stage ─────────────────────────────────────────────────────────────
# Imported lazily so this module's pure helpers (used by the validation warmer
# and by the consumer stages) do not require the heavy stage machinery.
from src.bus import RunBus  # noqa: E402
from src.stage import run_stage_def  # noqa: E402


@run_stage_def(
    reads=("curator_findings",),
    writes=("curator_findings_clustering",),
)
async def translate_findings_sidecar(run_bus: RunBus) -> RunBus:
    """Populate ``curator_findings_clustering`` with English-normalised
    title/summary per finding — or an empty slot when disabled.

    Default-off: when ``IW_CLUSTER_TRANSLATE`` is not truthy this is a pure
    no-op (empty slot, no backend import). The slot is ``optional_write=True``
    so the empty case passes the post-condition gate."""
    findings = list(run_bus.curator_findings or [])

    if not is_enabled():
        run_bus.curator_findings_clustering = []
        logger.debug(
            "translate_findings_sidecar: disabled (%s not set) — no-op", ENABLE_ENV
        )
        return run_bus

    if not findings:
        run_bus.curator_findings_clustering = []
        logger.info("translate_findings_sidecar: no findings — empty slot")
        return run_bus

    entries, stats = translate_findings(findings)
    run_bus.curator_findings_clustering = entries
    logger.info(
        "translate_findings_sidecar: %d findings → %d cache-hit, %d fresh, "
        "%d native-fallback %s",
        stats["n_findings"],
        stats["n_translated_cache_hit"],
        stats["n_translated_fresh"],
        stats["n_native_fallback"],
        stats["native_reasons"] or "",
    )
    return run_bus


__all__ = [
    "CACHE_ENV",
    "CT2_DIR_ENV",
    "ENABLE_ENV",
    "FLORES",
    "MODEL_NAME",
    "cache_path",
    "clustering_findings",
    "content_key",
    "is_enabled",
    "load_cache",
    "norm_lang",
    "save_cache",
    "translate_findings",
    "translate_findings_sidecar",
]
