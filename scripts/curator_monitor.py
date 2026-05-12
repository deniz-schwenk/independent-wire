#!/usr/bin/env python3
"""Post-run Curator monitor: compares today's Curator output against the
V1 2026-05-11 pathology baseline and a rolling N-day window.

Stdlib-only, no LLM calls, no new dependencies. Designed for cron use:

    python scripts/curator_monitor.py [--date YYYY-MM-DD] [--report-file PATH]
                                       [--fail-on-pathology] [--window-days N]

Defaults: --date = today (UTC), --report-file = docs/curator-monitor/{date}.md,
--window-days = 7. Without --fail-on-pathology the exit code is always 0;
with the flag, exit 1 on RED verdict.

The on-topic heuristic is **dynamic per cluster**: each daily run derives
its own regex from the top cluster's title+summary (tokenise, drop
multilingual stopwords, ≥4-char tokens). This measures cluster
self-consistency — does the cluster's content match the headline Curator
itself wrote? — not topic correctness against a fixed reference. ~5-10 %
FP/FN rate per the audit experience; directional indicator only.

Outputs:
    docs/curator-monitor/{date}.md           — durable markdown report
    output/curator-monitor/_baseline.json    — cached pathology metrics (gitignored)
    output/curator-monitor/_history/{d}.json — per-day metric cache (gitignored)

Verdict thresholds (calibrated to the pathology baseline):
    RED    today.top_cluster_size >= 500 OR off_topic_pct >= 70
    GREEN  today within window p90 on both axes
    AMBER  exceeds window p90 but stays below pathology/2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

PATHOLOGY_BASELINE_STATE = (
    ROOT / "output" / "2026-05-11-v1-baseline" / "_state"
    / "run-2026-05-11-722571ae" / "run_bus.CuratorStage.json"
)
MONITOR_CACHE_DIR = ROOT / "output" / "curator-monitor"
BASELINE_CACHE = MONITOR_CACHE_DIR / "_baseline.json"
HISTORY_DIR = MONITOR_CACHE_DIR / "_history"
REPORT_DIR = ROOT / "docs" / "curator-monitor"


# ── Multilingual stopword list ───────────────────────────────────────────
# ~420 tokens across EN, DE, ES, FR, IT, PT, TR, KO. Below the 500-token
# "split into sibling module" threshold from the brief; kept inline for
# zero dependencies. Lowercase only — the tokeniser lowercases input first.
STOPWORDS = frozenset({
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


def derive_on_topic_regex(title: str, summary: str) -> tuple[Optional[re.Pattern], list[str]]:
    """Build the dynamic on-topic regex from the top cluster's
    self-description (title + summary).

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
    file. Pure function over the loaded JSON."""
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
    regex, tokens = derive_on_topic_regex(top.get("title") or "", top.get("summary") or "")

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


# ── State discovery + caching ────────────────────────────────────────────
def find_state_for_date(date_str: str) -> Optional[Path]:
    """Locate ``output/{date}/_state/run-*/run_bus.CuratorStage.json``. If
    multiple run directories exist for the date, pick the latest by mtime."""
    base = ROOT / "output" / date_str / "_state"
    if not base.exists():
        return None
    candidates = list(base.glob("run-*/run_bus.CuratorStage.json"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def get_pathology_baseline_metrics() -> dict:
    """Return cached pathology baseline metrics, computing on first call
    or when the source state file is newer than the cache."""
    if not PATHOLOGY_BASELINE_STATE.exists():
        raise FileNotFoundError(
            f"Pathology baseline state not found at {PATHOLOGY_BASELINE_STATE}"
        )
    if (
        BASELINE_CACHE.exists()
        and BASELINE_CACHE.stat().st_mtime
        >= PATHOLOGY_BASELINE_STATE.stat().st_mtime
    ):
        return json.loads(BASELINE_CACHE.read_text(encoding="utf-8"))
    state = json.loads(PATHOLOGY_BASELINE_STATE.read_text(encoding="utf-8"))
    metrics = compute_metrics(state)
    MONITOR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_CACHE.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return metrics


def get_metrics_for_date(date_str: str) -> Optional[dict]:
    """Return cached metrics for the given date, computing and caching on
    miss. Returns ``None`` if no state file exists for the date."""
    cache_path = HISTORY_DIR / f"{date_str}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache_path.unlink(missing_ok=True)
    state_path = find_state_for_date(date_str)
    if state_path is None:
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    metrics = compute_metrics(state)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return metrics


# ── Verdict ──────────────────────────────────────────────────────────────
def compute_verdict(
    today: dict, baseline: dict, window: list[dict],
) -> tuple[str, str]:
    """Return ``(verdict, explanation)``. ``verdict`` ∈ {GREEN, AMBER, RED}.

    Rules per brief:
    - RED if today.top_cluster_size ≥ 500 OR off_topic_pct ≥ 70
    - GREEN if today ≤ window-p90 on BOTH axes
    - AMBER if today exceeds window-p90 on either axis but stays under
      pathology / 2 on both

    Empty window: verdict driven purely by RED thresholds (GREEN otherwise).
    """
    top = today["top_cluster_size"]
    off = today["top_cluster_off_topic_pct"]

    if top >= 500 or off >= 70:
        reasons = []
        if top >= 500:
            reasons.append(f"top_cluster_size={top} ≥ 500")
        if off >= 70:
            reasons.append(f"off_topic_pct={off} ≥ 70")
        return "RED", "; ".join(reasons)

    if not window:
        return "GREEN", "no window history; within RED thresholds"

    p90_top = _percentile([w["top_cluster_size"] for w in window], 0.9)
    p90_off = _percentile([w["top_cluster_off_topic_pct"] for w in window], 0.9)

    if top <= p90_top and off <= p90_off:
        return "GREEN", f"within window p90 (top≤{p90_top:.0f}, off≤{p90_off:.1f}%)"

    half_top = baseline["top_cluster_size"] / 2
    half_off = baseline["top_cluster_off_topic_pct"] / 2
    if top < half_top and off < half_off:
        drifted = []
        if top > p90_top:
            drifted.append(f"top_cluster_size={top} > window p90={p90_top:.0f}")
        if off > p90_off:
            drifted.append(f"off_topic_pct={off} > window p90={p90_off:.1f}%")
        return "AMBER", "; ".join(drifted) or "drifted vs window"

    return "RED", "exceeds pathology/2 on at least one axis"


_EMOJI = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}


# ── Markdown rendering ───────────────────────────────────────────────────
def render_markdown(
    date_str: str,
    today: dict,
    window: list[dict],
    baseline: dict,
    window_days: int,
    verdict: str,
    explanation: str,
) -> str:
    lines: list[str] = []
    lines.append(f"# Curator monitor — {date_str}\n")

    lines.append("## Verdict\n")
    lines.append(f"{_EMOJI.get(verdict, '')} **{verdict}** — {explanation}\n")

    # Today vs window vs baseline
    if window:
        p50_top = _percentile([w["top_cluster_size"] for w in window], 0.5)
        p90_top = _percentile([w["top_cluster_size"] for w in window], 0.9)
        p50_off = _percentile([w["top_cluster_off_topic_pct"] for w in window], 0.5)
        p90_off = _percentile([w["top_cluster_off_topic_pct"] for w in window], 0.9)
        p50_clusters = _percentile([w["n_clusters"] for w in window], 0.5)
        p90_clusters = _percentile([w["n_clusters"] for w in window], 0.9)
        p50_orphan = _percentile([w["orphan_rate"] for w in window], 0.5)
        p90_orphan = _percentile([w["orphan_rate"] for w in window], 0.9)
        p50_cs90 = _percentile([w["cluster_size_p90"] for w in window], 0.5)
        p90_cs90 = _percentile([w["cluster_size_p90"] for w in window], 0.9)
        win_text = lambda p50, p90: f"{p50:.1f} / {p90:.1f}"
    else:
        p50_top = p90_top = p50_off = p90_off = 0
        p50_clusters = p90_clusters = 0
        p50_orphan = p90_orphan = 0
        p50_cs90 = p90_cs90 = 0
        win_text = lambda p50, p90: "n/a (empty window)"

    lines.append("## Today\n")
    lines.append("| Metric | Today | Window p50 / p90 | Pathology baseline |")
    lines.append("|---|---:|---:|---:|")
    lines.append(
        f"| n_findings_total | {today['n_findings_total']} | "
        f"{win_text(_percentile([w['n_findings_total'] for w in window], 0.5), _percentile([w['n_findings_total'] for w in window], 0.9)) if window else 'n/a'} | "
        f"{baseline['n_findings_total']} |"
    )
    lines.append(
        f"| n_clusters | {today['n_clusters']} | "
        f"{win_text(p50_clusters, p90_clusters)} | {baseline['n_clusters']} |"
    )
    lines.append(
        f"| top_cluster_size | {today['top_cluster_size']} | "
        f"{win_text(p50_top, p90_top)} | {baseline['top_cluster_size']} |"
    )
    lines.append(
        f"| top_cluster_off_topic_pct | {today['top_cluster_off_topic_pct']} | "
        f"{win_text(p50_off, p90_off)} | {baseline['top_cluster_off_topic_pct']} |"
    )
    lines.append(
        f"| orphan_rate | {today['orphan_rate']} | "
        f"{win_text(p50_orphan, p90_orphan)} | {baseline['orphan_rate']} |"
    )
    lines.append(
        f"| cluster_size_p90 | {today['cluster_size_p90']} | "
        f"{win_text(p50_cs90, p90_cs90)} | {baseline['cluster_size_p90']} |"
    )
    lines.append("")
    lines.append(f"Top cluster: \"{today['top_cluster_title']}\"")
    tokens = today.get("on_topic_regex_tokens") or []
    if tokens:
        preview = "|".join(tokens[:15])
        suffix = f"  *(and {len(tokens) - 15} more)*" if len(tokens) > 15 else ""
        lines.append(f"On-topic regex (derived, {len(tokens)} tokens): `\\b({preview})\\b`{suffix}")
    else:
        lines.append("On-topic regex (derived): _no usable tokens — every finding flagged off-topic_")
    lines.append("")

    # Window history
    lines.append(f"## Last {window_days} days\n")
    if window:
        lines.append("| Date | n_clusters | top_size | off_topic_% | orphan_rate |")
        lines.append("|---|---:|---:|---:|---:|")
        for w in window:
            lines.append(
                f"| {w['date']} | {w['n_clusters']} | {w['top_cluster_size']} | "
                f"{w['top_cluster_off_topic_pct']} | {w['orphan_rate']} |"
            )
    else:
        lines.append("_No prior days within window had a Curator state file._")
    lines.append("")

    lines.append("## Observations\n")
    if verdict == "RED":
        lines.append(f"- {explanation}")
        lines.append(f"- Pathology baseline reference: top_cluster_size={baseline['top_cluster_size']}, off_topic_pct={baseline['top_cluster_off_topic_pct']} %.")
        lines.append("- **Action**: review Curator output; if RED persists ≥2 days, consider rollback or config change.")
    elif verdict == "AMBER":
        lines.append(f"- {explanation}")
        lines.append("- Single AMBER day is not actionable — temp=1.0 is stochastic. Look for sustained AMBER over multiple days.")
    else:
        if window:
            lines.append(
                f"- Within normal range. Window p90 top_cluster_size={p90_top:.0f}, "
                f"off_topic_pct={p90_off:.1f} %."
            )
        else:
            lines.append("- No window history yet — verdict driven solely by RED thresholds.")
    lines.append("")

    lines.append("## Heuristic notes\n")
    lines.append(
        "The on-topic regex is derived per cluster from Curator's own "
        "self-description (top cluster's `title` + `summary`). It measures "
        "**self-consistency** — does the cluster's content match the headline "
        "Curator wrote? — not topic correctness against an external truth. "
        "~5-10 % FP/FN rate per audit experience (`docs/AUDIT-CURATOR-2026-05-11.md` §4). "
        "Single-day signal only, directional indicator."
    )
    lines.append("")

    lines.append("## Cache\n")
    lines.append(f"Today's metrics cached at `output/curator-monitor/_history/{date_str}.json`.")
    lines.append("")
    return "\n".join(lines)


# ── CLI entrypoint ───────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Post-run Curator monitor; compares today's CuratorStage "
        "output against the V1 2026-05-11 pathology baseline and a rolling "
        "N-day window."
    )
    p.add_argument(
        "--date", default=None,
        help="Run date to monitor (YYYY-MM-DD). Default: today (UTC).",
    )
    p.add_argument(
        "--report-file", default=None,
        help="Output path for the markdown report. "
        "Default: docs/curator-monitor/{date}.md",
    )
    p.add_argument(
        "--fail-on-pathology", action="store_true",
        help="Exit 1 on RED verdict. AMBER and GREEN always exit 0 because "
        "temp=1.0 is stochastic and a single AMBER day is not actionable.",
    )
    p.add_argument(
        "--window-days", type=int, default=7,
        help="Number of prior days to include in the rolling-window comparison.",
    )
    args = p.parse_args(argv)

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    today = get_metrics_for_date(date_str)
    if today is None:
        print(
            f"ERROR: no CuratorStage state for {date_str} under "
            f"output/{date_str}/_state/run-*/run_bus.CuratorStage.json",
            file=sys.stderr,
        )
        return 2

    baseline = get_pathology_baseline_metrics()

    base_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    window: list[dict] = []
    for i in range(1, args.window_days + 1):
        d = base_date - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        m = get_metrics_for_date(d_str)
        if m is not None:
            window.append({**m, "date": d_str})

    verdict, explanation = compute_verdict(today, baseline, window)

    md = render_markdown(
        date_str, today, window, baseline, args.window_days, verdict, explanation,
    )
    report_path = (
        Path(args.report_file) if args.report_file else REPORT_DIR / f"{date_str}.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md, encoding="utf-8")

    print(
        f"{date_str}  curator monitor  {verdict}  "
        f"top={today['top_cluster_size']}  "
        f"off%={today['top_cluster_off_topic_pct']}  "
        f"clusters={today['n_clusters']}"
    )

    if args.fail_on_pathology and verdict == "RED":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
