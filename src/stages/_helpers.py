"""Pure helpers shared across topic-stages.

V1 references for ports:
- _normalise_country     src/pipeline.py:342-362
- _normalise_language    src/pipeline.py:370-386
- LANGUAGE_NAMES         src/pipeline.py:309-319
- COUNTRY_ALIASES        src/pipeline.py:325-339
- _LANGUAGE_ALIASES      src/pipeline.py:991-996
- _COUNTRY_ALIASES_GAP   src/pipeline.py:998-1002 (subset, used by gap-validation only)
- _GAP_STOPWORDS         src/pipeline.py:1004-1011
- _gap_tokens            src/pipeline.py:1014-1016
- _validate_coverage_gaps src/pipeline.py:1019-1109
- _STALE_QUANTIFIER_PATTERNS src/pipeline.py:1112-1134
- _strip_stale_quantifiers src/pipeline.py:1137-1194

Logic preserved verbatim where possible; function signatures simplified
(no `self`, no class-method calls, no logger-on-`self`).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language / country normalisation tables (V1 src/pipeline.py:309-339)
# ---------------------------------------------------------------------------

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish",
    "no": "Norwegian", "da": "Danish", "fi": "Finnish", "el": "Greek",
    "tr": "Turkish", "ru": "Russian", "uk": "Ukrainian", "pl": "Polish",
    "cs": "Czech", "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian",
    "sr": "Serbian", "hr": "Croatian", "ar": "Arabic", "fa": "Persian",
    "he": "Hebrew", "ur": "Urdu", "hi": "Hindi", "bn": "Bengali",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese",
    "th": "Thai", "id": "Indonesian", "ms": "Malay", "sw": "Swahili",
}

COUNTRY_ALIASES: dict[str, str] = {
    "us": "United States", "usa": "United States",
    "u.s.": "United States", "u.s.a.": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom",
    "great britain": "United Kingdom", "britain": "United Kingdom",
    "uae": "United Arab Emirates", "u.a.e.": "United Arab Emirates",
    "prc": "China", "people's republic of china": "China",
    "roc": "Taiwan", "rok": "South Korea",
    "dprk": "North Korea",
    "russia": "Russia", "russian federation": "Russia",
    "drc": "Democratic Republic of the Congo",
    "dr congo": "Democratic Republic of the Congo",
    "czechia": "Czech Republic",
}

_LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    name.lower(): code for code, name in LANGUAGE_NAMES.items()
}


def normalise_country(name: Optional[str]) -> str:
    """V1: src/pipeline.py:342-362. Multi-country markers (`/`, `,`, `&`,
    `and`, `und`) yield empty — guessing is worse than missing."""
    if not name or not isinstance(name, str):
        return ""
    stripped = name.strip()
    if not stripped:
        return ""
    if re.search(r"[/,&]|\band\b|\bund\b", stripped, re.IGNORECASE):
        return ""
    lower = stripped.lower()
    for candidate in (lower, lower.rstrip("."), lower.replace(".", "")):
        if candidate in COUNTRY_ALIASES:
            return COUNTRY_ALIASES[candidate]
    return stripped


def normalise_language(value: Optional[str]) -> str:
    """V1: src/pipeline.py:370-386. Returns ISO 639-1 lowercase code, or the
    stripped-lowercased input if not in the canonical table (preserves
    legitimate custom tags like `zh-Hant`)."""
    if not value or not isinstance(value, str):
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    if v in LANGUAGE_NAMES:
        return v
    return _LANGUAGE_NAME_TO_CODE.get(v, v)


# ---------------------------------------------------------------------------
# Coverage-gap validation (V1 src/pipeline.py:991-1109)
# ---------------------------------------------------------------------------

_LANGUAGE_ALIASES: dict[str, str] = {
    "english": "en", "french": "fr", "german": "de", "spanish": "es",
    "persian": "fa", "farsi": "fa", "russian": "ru", "turkish": "tr",
    "italian": "it", "arabic": "ar", "chinese": "zh", "hebrew": "he",
    "ukrainian": "uk", "portuguese": "pt", "japanese": "ja", "korean": "ko",
}

_COUNTRY_ALIASES_GAP: dict[str, str] = {
    "uk": "United Kingdom", "u.k.": "United Kingdom",
    "us": "United States", "u.s.": "United States",
    "usa": "United States", "u.s.a.": "United States",
}

_GAP_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "no", "and", "or", "to", "for",
    "as", "is", "by", "at", "with", "from", "are", "was", "were", "be",
    "but", "not", "this", "that", "any", "all", "its", "it", "has",
    "have", "had", "been", "being", "will", "shall", "do", "does", "did",
    "than", "then", "so", "such", "more", "most", "less", "least",
    "some", "many", "few",
})


def _gap_tokens(text: str) -> set[str]:
    """V1: src/pipeline.py:1014-1016."""
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in _GAP_STOPWORDS}


def validate_coverage_gaps(
    gaps: list[str], source_balance: dict
) -> tuple[list[str], list[str]]:
    """V1: src/pipeline.py:1019-1109. Returns (kept, dropped).

    Drops gaps falsified by source_balance.by_language / by_country, plus
    Jaccard-near-duplicates. Genuinely qualitative gaps survive.
    """
    by_language = {
        (k or "").lower(): v
        for k, v in (source_balance or {}).get("by_language", {}).items()
        if v
    }
    by_country = {
        (k or "").lower(): v
        for k, v in (source_balance or {}).get("by_country", {}).items()
        if v
    }

    kept: list[str] = []
    dropped: list[str] = []
    kept_token_sets: list[set[str]] = []

    no_pattern = re.compile(
        r"\b(no|missing|lack(?:ing)?|absence of|absent|without)\b",
        re.IGNORECASE,
    )

    for gap in gaps or []:
        if not isinstance(gap, str) or not gap.strip():
            continue
        gap_lower = gap.lower()

        falsified = False

        if no_pattern.search(gap):
            for alias, code in _LANGUAGE_ALIASES.items():
                if re.search(rf"\b{alias}\b", gap_lower):
                    if by_language.get(code, 0) > 0 or by_language.get(alias, 0) > 0:
                        falsified = True
                        break
            if not falsified:
                for alias, canonical in _COUNTRY_ALIASES_GAP.items():
                    if re.search(rf"\b{re.escape(alias)}\b", gap_lower):
                        if by_country.get(canonical.lower(), 0) > 0:
                            falsified = True
                            break
            if not falsified:
                for country, count in by_country.items():
                    if count > 0 and re.search(rf"\b{re.escape(country)}\b", gap_lower):
                        falsified = True
                        break

        if falsified:
            dropped.append(gap)
            continue

        tokens = _gap_tokens(gap)
        is_dup = False
        for prev in kept_token_sets:
            if not tokens or not prev:
                continue
            jaccard = len(tokens & prev) / len(tokens | prev)
            if jaccard > 0.7:
                is_dup = True
                break
        if is_dup:
            dropped.append(gap)
            continue

        kept.append(gap)
        kept_token_sets.append(tokens)

    return kept, dropped


# ---------------------------------------------------------------------------
# Stale-quantifier strip (V1 src/pipeline.py:1112-1194)
# ---------------------------------------------------------------------------

_STALE_QUANTIFIER_PATTERNS = [
    re.compile(
        r"\bonly\s+\w+\s+(outlet|outlets|source|sources|region|regions|country|countries)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfew\s+(outlet|outlets|source|sources|region|regions)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\blimited\s+(coverage|reach|outlets|sources|reporting)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(two|three|four|five|six)\s+(outlet|outlets|source|sources|region|regions|country|countries)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d+\s+(outlet|outlets|source|sources|region|regions|country|countries)\b",
    ),
    re.compile(r"\bsingle[-\s]source\b", re.IGNORECASE),
    re.compile(r"\bnarrow\s+(coverage|geography|reach)\b", re.IGNORECASE),
]


def strip_stale_quantifiers(selection_reason: str) -> str:
    """V1: src/pipeline.py:1137-1194. Remove sentences quantifying source
    coverage; if every sentence ends up dropped, return the original."""
    if not selection_reason or not isinstance(selection_reason, str):
        return selection_reason or ""

    sentence_split = re.split(r"(?<=[.!?])\s+", selection_reason.strip())
    if not sentence_split:
        return selection_reason

    kept_sentences: list[str] = []
    stripped_any = False
    for sentence in sentence_split:
        if not sentence.strip():
            continue
        cleaned = sentence
        matched = False
        for pat in _STALE_QUANTIFIER_PATTERNS:
            if pat.search(cleaned):
                matched = True
                cleaned = pat.sub("", cleaned)
        if not matched:
            kept_sentences.append(sentence)
            continue

        stripped_any = True
        residual = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;:")
        words = [w for w in re.findall(r"[A-Za-z]+", residual) if len(w) >= 3]
        if len(words) >= 3:
            kept_sentences.append(re.sub(r"\s+", " ", cleaned).strip())

    if stripped_any:
        if not kept_sentences:
            logger.warning(
                "Selection-reason fully stale; keeping original: %r",
                selection_reason,
            )
            return selection_reason
        logger.warning(
            "Selection-reason stale-quantifier strip: %r -> %r",
            selection_reason, " ".join(kept_sentences),
        )
        return " ".join(kept_sentences)
    return selection_reason


__all__ = [
    "COUNTRY_ALIASES",
    "LANGUAGE_NAMES",
    "normalise_country",
    "normalise_language",
    "strip_stale_quantifiers",
    "validate_coverage_gaps",
]
