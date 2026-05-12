"""Curator post-run metric computation — shared by the monitor and shadow
scripts. Pure functions, stdlib-only, deterministic.

The metric record is computed from a CuratorStage state dict (or any dict
shaped `{"curator_findings": [...], "curator_topics_unsliced": [...]}`).
The on-topic regex is derived **per cluster** from the top cluster's own
title+summary — it measures self-consistency, not topic correctness.

Originally lived inline in scripts/curator_monitor.py; extracted to this
module so scripts/curator_shadow.py can re-use the same metric definitions
without code duplication.
"""

from __future__ import annotations

import re
from typing import Optional


# ── Multilingual stopword list ───────────────────────────────────────────
# ~420 tokens across EN, DE, ES, FR, IT, PT, TR, KO. Kept inline for zero
# dependencies. Lowercase only — the tokeniser lowercases input first.
STOPWORDS: frozenset[str] = frozenset({
    # ── English ── 65
    "the", "this", "that", "these", "those", "with", "from", "into", "onto",
    "over", "under", "after", "before", "while", "their", "there", "where",
    "when", "what", "which", "whom", "whose", "than", "then", "also", "only",
    "just", "even", "very", "much", "more", "most", "less", "least", "many",
    "such", "some", "each", "every", "both", "either", "neither", "none",
    "between", "among", "during", "since", "until", "again", "still", "however",
    "though", "although", "because", "without", "within", "across", "through",
    "above", "below", "around", "about", "against", "would", "could", "should",
    "shall", "might", "must",
    # ── German ── 50
    "und", "oder", "aber", "der", "die", "das", "den", "dem", "des", "ein",
    "eine", "einen", "einer", "einem", "eines", "mit", "von", "zum", "zur",
    "für", "auf", "aus", "durch", "über", "unter", "vor", "nach", "bei",
    "sind", "war", "waren", "sein", "haben", "hatte", "hatten", "werden",
    "wurde", "wurden", "kann", "könnten", "sollte", "sollten", "müssen",
    "dies", "dieser", "diese", "dieses", "sich", "uns", "ihre", "ihrer",
    "ihres", "noch", "schon", "sehr", "mehr", "nicht", "alle", "alles", "einige",
    "wenn", "weil", "dass", "auch", "dann",
    # ── Spanish ── 55
    "los", "las", "una", "unos", "unas", "del", "por", "para", "con", "sin",
    "sobre", "entre", "hasta", "desde", "hacia", "durante", "antes", "después",
    "mientras", "como", "cuando", "donde", "porque", "que", "qué", "quien",
    "cuál", "cuáles", "cómo", "cuándo", "dónde", "también", "sólo", "solo",
    "aún", "todavía", "menos", "mucho", "poco", "todo", "todos", "toda",
    "todas", "este", "esta", "estos", "estas", "eso", "esa", "esos", "esas",
    "aquel", "aquella", "aquellos", "aquellas",
    # ── French ── 50
    "les", "des", "aux", "dans", "pour", "avec", "sans", "sous", "vers",
    "après", "avant", "pendant", "contre", "chez", "par", "pas", "mais",
    "donc", "car", "que", "qui", "quoi", "dont", "où", "comme", "lorsque",
    "quand", "puisque", "parce", "alors", "déjà", "encore", "toujours",
    "jamais", "plus", "moins", "très", "beaucoup", "peu", "tout", "tous",
    "toute", "toutes", "cette", "cet", "ces", "elle", "elles", "leur", "leurs",
    "nous",
    # ── Italian ── 45
    "lo", "gli", "una", "uno", "uno", "del", "dello", "della", "dei", "degli",
    "delle", "dal", "dallo", "dalla", "dai", "dagli", "dalle", "nel", "nello",
    "nella", "nei", "negli", "nelle", "sul", "sullo", "sulla", "sui", "sugli",
    "sulle", "con", "per", "fra", "tra", "anche", "ancora", "già", "sempre",
    "mai", "più", "meno", "molto", "poco", "tutto", "tutti", "tutta", "tutte",
    "quale", "quali", "questo", "questa", "questi", "queste", "quello", "quella",
    "quelli", "quelle", "essere", "avere",
    # ── Portuguese ── 45
    "uma", "uns", "umas", "dos", "das", "no", "na", "nos", "nas", "pelo",
    "pela", "pelos", "pelas", "para", "sem", "sob", "sobre", "com", "entre",
    "até", "desde", "durante", "antes", "depois", "mas", "porque", "quando",
    "onde", "como", "qual", "quais", "isso", "isto", "aquilo", "este", "esta",
    "esse", "essa", "aquele", "aquela", "estar", "ter", "haver", "fazer",
    # ── Turkish ── 40
    "bir", "bu", "şu", "ne", "kim", "hangi", "neden", "niçin", "nasıl",
    "nerede", "çok", "biraz", "daha", "gibi", "kadar", "için", "ile",
    "veya", "ama", "fakat", "çünkü", "ancak", "eğer", "ben", "sen", "biz",
    "siz", "onlar", "beni", "seni", "bunu", "şunu", "onu", "var", "yok",
    "olan", "oldu", "olur", "olarak", "şey",
    # ── Korean ── 35
    "그리고", "그러나", "그렇게", "이것", "그것", "저것", "이는", "그는",
    "그녀", "그들", "우리", "너희", "매우", "또한", "모든", "어떤", "무엇",
    "누구", "어디", "언제", "어떻게", "이미", "아직", "항상", "결코",
    "또는", "그래서", "하지만", "위해", "위한", "통해", "대해", "관해",
    "위에", "에서",
})


# ── Tokenisation + dynamic regex ─────────────────────────────────────────
def _tokenise(text: str) -> list[str]:
    """Lowercase, split on non-letter chars, return tokens. Unicode-aware
    so non-Latin scripts (Korean, Arabic, etc.) tokenise correctly."""
    if not text:
        return []
    return re.findall(r"[^\W\d_]+", text.lower(), flags=re.UNICODE)


def derive_on_topic_regex(
    title: str, summary: str,
) -> tuple[Optional[re.Pattern], list[str]]:
    """Build the dynamic on-topic regex from a cluster's self-description
    (title + summary).

    Algorithm: lowercase, tokenise, drop stopwords, drop tokens shorter
    than 4 characters, unique, build ``\\b(...)\\b`` case-insensitive
    alternation. Returns ``(compiled_pattern, token_list)``. Returns
    ``(None, [])`` if no usable tokens survived — the caller then treats
    every finding as off-topic (since we can't measure self-consistency
    with an empty vocabulary).
    """
    tokens = _tokenise((title or "") + " " + (summary or ""))
    unique: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if len(t) < 4:
            continue
        if t in STOPWORDS:
            continue
        if t in seen:
            continue
        seen.add(t)
        unique.append(t)
    if not unique:
        return None, []
    pattern = r"\b(" + "|".join(re.escape(t) for t in unique) + r")\b"
    return re.compile(pattern, re.IGNORECASE | re.UNICODE), unique


def _is_on_topic(finding: dict, regex: Optional[re.Pattern]) -> bool:
    if regex is None:
        return False
    text = " ".join([
        finding.get("title") or "",
        finding.get("summary") or "",
        finding.get("description") or "",
    ])
    return regex.search(text) is not None


# ── Metrics ──────────────────────────────────────────────────────────────
def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])


def compute_metrics(curator_state: dict) -> dict:
    """Compute the post-run metric record for a single CuratorStage state
    dict. Pure function over ``{"curator_findings": [...],
    "curator_topics_unsliced": [...]}``.

    Returns a dict with keys: n_findings_total, n_clusters, top_cluster_size,
    top_cluster_title, top_cluster_on_topic_count, top_cluster_off_topic_count,
    top_cluster_off_topic_pct, cluster_size_p50/p90/max/min, orphan_count,
    orphan_rate, on_topic_regex_tokens.
    """
    findings: list[dict] = list(curator_state.get("curator_findings") or [])
    topics: list[dict] = list(curator_state.get("curator_topics_unsliced") or [])

    cluster_sizes = [len(t.get("source_ids") or []) for t in topics]

    if not topics:
        return {
            "n_findings_total": len(findings),
            "n_clusters": 0,
            "top_cluster_size": 0,
            "top_cluster_title": "",
            "top_cluster_on_topic_count": 0,
            "top_cluster_off_topic_count": 0,
            "top_cluster_off_topic_pct": 0.0,
            "cluster_size_p50": 0,
            "cluster_size_p90": 0,
            "cluster_size_max": 0,
            "cluster_size_min": 0,
            "orphan_count": len(findings),
            "orphan_rate": 1.0 if findings else 0.0,
            "on_topic_regex_tokens": [],
        }

    top = max(topics, key=lambda t: len(t.get("source_ids") or []))
    regex, tokens = derive_on_topic_regex(
        top.get("title") or "", top.get("summary") or "",
    )

    on = off = 0
    for sid in top.get("source_ids") or []:
        try:
            idx = int(str(sid).split("finding-")[-1])
        except (ValueError, IndexError):
            continue
        if 0 <= idx < len(findings):
            if _is_on_topic(findings[idx], regex):
                on += 1
            else:
                off += 1
    total = on + off
    off_pct = round(100.0 * off / total, 2) if total else 0.0

    assigned = sum(cluster_sizes)
    orphan = max(0, len(findings) - assigned)

    return {
        "n_findings_total": len(findings),
        "n_clusters": len(topics),
        "top_cluster_size": len(top.get("source_ids") or []),
        "top_cluster_title": (top.get("title") or "")[:120],
        "top_cluster_on_topic_count": on,
        "top_cluster_off_topic_count": off,
        "top_cluster_off_topic_pct": off_pct,
        "cluster_size_p50": int(round(_percentile(cluster_sizes, 0.5))),
        "cluster_size_p90": int(round(_percentile(cluster_sizes, 0.9))),
        "cluster_size_max": max(cluster_sizes),
        "cluster_size_min": min(cluster_sizes),
        "orphan_count": orphan,
        "orphan_rate": round(orphan / len(findings), 4) if findings else 0.0,
        "on_topic_regex_tokens": tokens,
    }
