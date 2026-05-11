#!/usr/bin/env python3
"""Curator-only diagnostic smoke against 2026-05-11 baseline findings.

Mirrors the production Curator construction from scripts/run.py — same model,
prompts, temperature, reasoning, max_tokens, schema — and the production
pre/post-processing helpers from src/agent_stages.py. Reads curator_findings
from the existing baseline run_bus state file; writes NO state under
output/2026-05-11/. A debug snapshot of the call output is written to
output/eval/2026-05-11/curator_smoke/ (gitignored).

Question answered: does Curator structurally produce >100-assignment clusters
for hot topics (REPRODUCES the 2026-05-11 Iran blowup), or was that a one-off
(DOES NOT REPRODUCE), or is it ambiguous (60-100, more samples needed).

Usage: source .venv/bin/activate && source .env && python scripts/smoke_curator.py
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.agent_stages import (
    _prepare_curator_input,
    _rebuild_curator_source_ids,
    _enrich_curator_output,
)
from src.schemas import CURATOR_SCHEMA

BASELINE_STATE = (
    ROOT / "output" / "2026-05-11" / "_state" / "run-2026-05-11-722571ae"
    / "run_bus.fetch_findings.json"
)
BASELINE_CURATOR_STATE = (
    ROOT / "output" / "2026-05-11" / "_state" / "run-2026-05-11-722571ae"
    / "run_bus.CuratorStage.json"
)
EVAL_DIR = ROOT / "output" / "eval" / "2026-05-11" / "curator_smoke"
REPORT_PATH = ROOT / "docs" / "handoffs" / "CURATOR-SMOKE-2026-05-11.md"

AGENTS_DIR = ROOT / "agents"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("smoke_curator")


def build_curator_agent() -> Agent:
    """Mirror scripts/run.py:81-98 exactly."""
    return Agent(
        name="curator",
        model="google/gemini-3-flash-preview",
        system_prompt_path=str(AGENTS_DIR / "curator" / "SYSTEM.md"),
        instructions_path=str(AGENTS_DIR / "curator" / "INSTRUCTIONS.md"),
        tools=[],
        temperature=0.2,
        provider="openrouter",
        reasoning="none",
        max_tokens=64000,
        output_schema=CURATOR_SCHEMA,
    )


def baseline_topic_summary() -> dict:
    """Load baseline CuratorStage output for side-by-side comparison."""
    if not BASELINE_CURATOR_STATE.exists():
        return {}
    d = json.loads(BASELINE_CURATOR_STATE.read_text(encoding="utf-8"))
    topics = d.get("curator_topics_unsliced") or []
    sizes = sorted(
        ((len(t.get("source_ids") or []), t.get("title", "")[:80]) for t in topics),
        reverse=True,
    )
    total_assigned = sum(s for s, _ in sizes)
    return {
        "n_topics": len(topics),
        "top5": sizes[:5],
        "total_assigned": total_assigned,
    }


def render_report(
    *,
    cost: float,
    wall_seconds: float,
    tokens: int,
    topics: list[dict],
    n_findings_in: int,
    baseline: dict,
    diagnosis: str,
    recommendation: str,
) -> str:
    sizes = [(len(t.get("source_ids") or []), t.get("title", ""), t.get("relevance_score")) for t in topics]
    sizes_sorted = sorted(sizes, key=lambda x: x[0], reverse=True)
    total_assigned = sum(n for n, _, _ in sizes)
    orphan = max(0, n_findings_in - total_assigned)
    orphan_pct = (orphan / n_findings_in * 100) if n_findings_in else 0.0

    def trunc(s: str, n: int = 80) -> str:
        s = (s or "").replace("|", "/").replace("\n", " ").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    lines = []
    lines.append("# CURATOR-SMOKE-2026-05-11\n")
    lines.append("## Run metadata")
    lines.append(f"- Cost: ${cost:.4f}")
    lines.append(f"- Wall-clock: {wall_seconds:.1f} s")
    lines.append(f"- Tokens: {tokens}")
    lines.append("- Model: google/gemini-3-flash-preview, temp=0.2, reasoning=none, max_tokens=64000")
    lines.append("- Input: 1201 curator_findings from run-2026-05-11-722571ae")
    lines.append("")

    lines.append("## Top-5 by assignment count")
    lines.append("| Rank | Assignments | Relevance | Title |")
    lines.append("|---|---|---|---|")
    for i, (n, title, rel) in enumerate(sizes_sorted[:5], 1):
        lines.append(f"| {i} | {n} | {rel} | {trunc(title)} |")
    lines.append("")

    lines.append("## Full cluster-size distribution")
    lines.append("| # | Title | Assignments | Relevance |")
    lines.append("|---|---|---|---|")
    # Stable order: sort by relevance desc then size desc (mirrors production sort)
    ordered = sorted(topics, key=lambda t: (t.get("relevance_score", 0), len(t.get("source_ids") or [])), reverse=True)
    for i, t in enumerate(ordered, 1):
        n = len(t.get("source_ids") or [])
        lines.append(f"| {i} | {trunc(t.get('title', ''))} | {n} | {t.get('relevance_score')} |")
    lines.append("")

    lines.append("## Totals")
    lines.append(f"- Total clusters: {len(topics)}")
    lines.append(f"- Total findings in input: {n_findings_in}")
    lines.append(f"- Total assigned: {total_assigned}")
    lines.append(f"- Orphan findings: {orphan} ({orphan_pct:.1f}%)")
    lines.append("")

    lines.append("## Comparison vs baseline (run-2026-05-11-722571ae)")
    if baseline:
        lines.append("| Metric | Baseline | Smoke |")
        lines.append("|---|---|---|")
        lines.append(f"| Cluster count | {baseline['n_topics']} | {len(topics)} |")
        for i in range(5):
            b = baseline["top5"][i] if i < len(baseline["top5"]) else (0, "")
            s = sizes_sorted[i] if i < len(sizes_sorted) else (0, "", None)
            lines.append(f"| Top-{i+1} assignments | {b[0]} ({trunc(b[1], 40)}) | {s[0]} ({trunc(s[1], 40)}) |")
        lines.append(f"| Total assigned | {baseline['total_assigned']} | {total_assigned} |")
    else:
        lines.append("(baseline CuratorStage state not found)")
    lines.append("")

    lines.append("## Diagnosis")
    lines.append(diagnosis)
    lines.append("")
    lines.append("## Recommendation")
    lines.append(recommendation)
    lines.append("")
    return "\n".join(lines)


def diagnose(topics: list[dict]) -> tuple[str, str]:
    sizes = sorted((len(t.get("source_ids") or []) for t in topics), reverse=True)
    top = sizes[0] if sizes else 0
    if top > 100:
        diag = f"**REPRODUCES** — top cluster has {top} assignments (>100 threshold). The 2026-05-11 baseline pattern is structural Curator behaviour on hot topics, not a one-off."
        rec = (
            "Source-cap workpaket is the next architectural priority. Evaluate cap layer:\n"
            "- Curator-output: cap `cluster_assignments` per cluster (cheapest, earliest in pipeline).\n"
            "- `attach_hydration_urls`: cap URLs per editor-assignment (lets Curator keep the wide cluster, narrows what Phase-1 sees).\n"
            "- `merge_sources`: cap final source count after Researcher merge (latest, preserves upstream context).\n"
            "Architect to decide cap layer based on downstream cost-vs-coverage tradeoff."
        )
    elif top <= 60:
        diag = f"**DOES NOT REPRODUCE** — max cluster size is {top} (≤60 threshold). The 2026-05-11 blowup was a one-shot anomaly, not Curator's normal behaviour."
        rec = (
            "Investigate what was different about the 2026-05-11 run — possibly transient Curator behaviour, "
            "feed-set composition on that day, or a particular input pattern. Source-cap workpaket is NOT the "
            "right mitigation; look upstream/sideways instead."
        )
    else:
        diag = f"**AMBIGUOUS** — top cluster has {top} assignments (60-100 grey zone). Curator is temp=0.2 so slight stochasticity is expected. One sample is not enough."
        rec = (
            "Re-run this smoke 2 more times (3 samples total). If any sample exceeds 100, treat as REPRODUCES; "
            "if all samples stay ≤60, treat as DOES NOT REPRODUCE; if all samples fall in 60-100, source-cap is "
            "still worth pursuing for the upper tail."
        )
    return diag, rec


async def main() -> int:
    if not BASELINE_STATE.exists():
        logger.error("Baseline state not found: %s", BASELINE_STATE)
        return 1

    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    raw = json.loads(BASELINE_STATE.read_text(encoding="utf-8"))
    raw_findings = list(raw.get("curator_findings") or [])
    logger.info("Loaded %d raw findings from baseline", len(raw_findings))

    prepared = _prepare_curator_input(raw_findings)
    logger.info("Prepared %d findings after compression", len(prepared))

    agent = build_curator_agent()
    message = (
        "Review these findings. Cluster related findings into topics. "
        "Score each topic's newsworthiness on a 1-10 scale."
    )

    start = time.monotonic()
    result = await agent.run(message, context={"findings": prepared})
    wall = time.monotonic() - start

    cost = result.cost_usd or 0.0
    tokens = result.tokens_used or 0
    logger.info("Curator call: %.1fs, %d tokens, $%.4f", wall, tokens, cost)

    if cost > 0.50:
        logger.error("Cost exceeded $0.50 ceiling — aborting before producing report")
        return 2

    topics = _rebuild_curator_source_ids(result, raw_findings)
    topics = _enrich_curator_output(topics, raw_findings, sources_json_path=None)
    topics.sort(key=lambda t: t.get("relevance_score", 0), reverse=True)
    logger.info("Curator produced %d topics", len(topics))

    (EVAL_DIR / "topics_snapshot.json").write_text(
        json.dumps(topics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (EVAL_DIR / "agent_raw.json").write_text(
        json.dumps(
            {
                "content": result.content,
                "tokens_used": tokens,
                "cost_usd": cost,
                "wall_seconds": wall,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    baseline = baseline_topic_summary()
    diag, rec = diagnose(topics)

    report = render_report(
        cost=cost,
        wall_seconds=wall,
        tokens=tokens,
        topics=topics,
        n_findings_in=len(raw_findings),
        baseline=baseline,
        diagnosis=diag,
        recommendation=rec,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    logger.info("Wrote report: %s", REPORT_PATH)

    sizes = sorted((len(t.get("source_ids") or []) for t in topics), reverse=True)
    print()
    print("=" * 72)
    print(f"  smoke_curator: {len(topics)} clusters, top sizes = {sizes[:5]}")
    print(f"  cost=${cost:.4f}  wall={wall:.1f}s  tokens={tokens}")
    print(f"  diagnosis: {diag.splitlines()[0]}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
