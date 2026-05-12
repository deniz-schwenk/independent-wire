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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.curator_metrics import (  # noqa: E402
    STOPWORDS,
    _percentile,
    compute_metrics,
    derive_on_topic_regex,
)

# Re-export under the original public names so any external tooling that
# imported these from curator_monitor keeps working.
__all__ = [
    "STOPWORDS",
    "compute_metrics",
    "derive_on_topic_regex",
    "find_state_for_date",
    "get_pathology_baseline_metrics",
    "get_metrics_for_date",
    "compute_verdict",
    "render_markdown",
    "main",
]

PATHOLOGY_BASELINE_STATE = (
    ROOT / "output" / "2026-05-11-v1-baseline" / "_state"
    / "run-2026-05-11-722571ae" / "run_bus.CuratorStage.json"
)
MONITOR_CACHE_DIR = ROOT / "output" / "curator-monitor"
BASELINE_CACHE = MONITOR_CACHE_DIR / "_baseline.json"
HISTORY_DIR = MONITOR_CACHE_DIR / "_history"
REPORT_DIR = ROOT / "docs" / "curator-monitor"


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
