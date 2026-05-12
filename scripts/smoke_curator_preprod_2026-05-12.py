#!/usr/bin/env python3
"""Pre-flight smoke for the Curator temp=0.2 → temp=1.0 production swap.

Runs Curator with the candidate config (gemini-3-flash-preview, temp=1.0,
reasoning=none, max_tokens=64000) against the 2026-05-11 V1 baseline
curator_findings (1201 entries) and gates the swap against four
acceptance thresholds defined in TASK-CURATOR-PROD-SWAP-FLASH-T10.md §
"Pre-flight smoke":

    top_cluster_size    ∈ [103, 171]   (audit value 137 ± 25 %)
    off_topic_pct       ∈ [45.3, 61.3] (audit value 53.3 ± 8 pp)
    n_clusters          ∈ [8, 16]      (audit value 12 ± 4)
    Jaccard vs audit    ≥ 0.40         (loose — temp=1.0 is stochastic)

Exit codes:
    0 — all four thresholds passed, swap is safe to proceed
    1 — at least one threshold failed, surface to Architect; do not swap
    2 — infrastructure / IO error (no acceptance verdict)

Output: output/eval/curator-2026-05-12-preprod/flash-t-10-r-none.json
(gitignored). One-shot disposable script — sibling to scripts/smoke_curator.py
from the prior diagnostic smoke task.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent  # noqa: E402
from src.agent_stages import (  # noqa: E402
    _prepare_curator_input,
    _rebuild_curator_source_ids,
    _enrich_curator_output,
)
from src.schemas import CURATOR_SCHEMA  # noqa: E402

BASELINE_STATE = (
    ROOT / "output" / "2026-05-11-v1-baseline" / "_state"
    / "run-2026-05-11-722571ae" / "run_bus.CuratorStage.json"
)
AUDIT_REFERENCE = (
    ROOT / "output" / "eval" / "curator-2026-05-11" / "flash-t-10-r-none.json"
)
OUTPUT_DIR = ROOT / "output" / "eval" / "curator-2026-05-12-preprod"
OUTPUT_PATH = OUTPUT_DIR / "flash-t-10-r-none.json"
AGENTS_DIR = ROOT / "agents"

CURATOR_MESSAGE = (
    "Review these findings. Cluster related findings into topics. "
    "Score each topic's newsworthiness on a 1-10 scale."
)

ON_TOPIC_RE = re.compile(
    r'\b(iran|tehran|trump|peace|negot|nuclear|israel|netanyahu|hezbollah|'
    r'houthi|yemen|hormuz|oil|tanker|red sea|gaza|hamas|war|sanction|missile|'
    r'enrichment|ayatollah|khamenei|pezeshkian|araghchi|witkoff|persia|'
    r'persian|middle east|naher osten|medio oriente|saudi|qatar|lebanon|'
    r'syria|emirates|teheran)\b',
    re.I,
)


def _is_on_topic(f: dict) -> bool:
    text = " ".join([
        f.get("title") or "",
        f.get("summary") or "",
        f.get("description") or "",
    ])
    return ON_TOPIC_RE.search(text) is not None


def _top_cluster_metrics(topics: list[dict], raw_findings: list[dict]) -> dict:
    if not topics:
        return {
            "n_clusters": 0, "top_cluster_size": 0,
            "top_on_topic": 0, "top_off_topic": 0,
            "off_topic_pct": 0.0, "top_source_ids": [],
        }
    topics_sorted = sorted(
        topics, key=lambda t: len(t.get("source_ids") or []), reverse=True
    )
    top = topics_sorted[0]
    src_ids = top.get("source_ids") or []
    on = off = 0
    for sid in src_ids:
        try:
            idx = int(str(sid).split("finding-")[-1])
        except (ValueError, IndexError):
            continue
        if 0 <= idx < len(raw_findings):
            if _is_on_topic(raw_findings[idx]):
                on += 1
            else:
                off += 1
    total = on + off
    return {
        "n_clusters": len(topics),
        "top_cluster_size": len(src_ids),
        "top_on_topic": on,
        "top_off_topic": off,
        "off_topic_pct": round(100.0 * off / total, 2) if total else 0.0,
        "top_source_ids": list(src_ids),
        "top_title": top.get("title", "")[:80],
    }


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a or b) else 0.0


async def main() -> int:
    if not BASELINE_STATE.exists():
        print(f"ERROR: baseline state not found: {BASELINE_STATE}", file=sys.stderr)
        return 2
    if not AUDIT_REFERENCE.exists():
        print(f"ERROR: audit reference not found: {AUDIT_REFERENCE}", file=sys.stderr)
        return 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    raw = json.loads(BASELINE_STATE.read_text(encoding="utf-8"))
    raw_findings = list(raw.get("curator_findings") or [])
    prepared = _prepare_curator_input(raw_findings)
    print(f"Loaded {len(raw_findings)} curator_findings → {len(prepared)} after prep")

    # Mirror the production-swap-candidate Curator config exactly.
    agent = Agent(
        name="smoke_curator_preprod",
        model="google/gemini-3-flash-preview",
        system_prompt_path=str(AGENTS_DIR / "curator" / "SYSTEM.md"),
        instructions_path=str(AGENTS_DIR / "curator" / "INSTRUCTIONS.md"),
        tools=[],
        temperature=1.0,
        provider="openrouter",
        reasoning="none",
        max_tokens=64000,
        output_schema=CURATOR_SCHEMA,
    )

    start = time.monotonic()
    result = await agent.run(CURATOR_MESSAGE, context={"findings": prepared})
    wall = time.monotonic() - start

    topics = _rebuild_curator_source_ids(result, raw_findings)
    topics = _enrich_curator_output(topics, raw_findings, sources_json_path=None)

    metrics = _top_cluster_metrics(topics, raw_findings)
    print(
        f"Smoke result: {metrics['n_clusters']} clusters, "
        f"top={metrics['top_cluster_size']} (off {metrics['off_topic_pct']}%), "
        f"cost=${result.cost_usd or 0:.4f}, wall={wall:.1f}s"
    )

    # Jaccard vs audit top cluster
    audit = json.loads(AUDIT_REFERENCE.read_text(encoding="utf-8"))
    audit_topics = audit.get("curator_topics_unsliced") or []
    audit_top_sorted = sorted(
        audit_topics, key=lambda t: len(t.get("source_ids") or []), reverse=True
    )
    audit_top_set = (
        set(audit_top_sorted[0].get("source_ids") or [])
        if audit_top_sorted else set()
    )
    smoke_top_set = set(metrics["top_source_ids"])
    jaccard = _jaccard(smoke_top_set, audit_top_set)
    print(
        f"Audit reference: top_cluster_size={len(audit_top_set)} "
        f"(audit was 137, off 53.3%)"
    )
    print(f"Jaccard(smoke top, audit top) = {jaccard:.3f}")

    payload = {
        "label": "flash-t-10-r-none",
        "context": "preprod-smoke-2026-05-12",
        "model": "google/gemini-3-flash-preview",
        "temperature": 1.0,
        "reasoning": "none",
        "max_tokens": 64000,
        "wall_seconds": round(wall, 2),
        "cost_usd": result.cost_usd or 0.0,
        "tokens_used": result.tokens_used or 0,
        "provider_served": result.provider,
        "response_id": result.response_id,
        "n_clusters": metrics["n_clusters"],
        "top_cluster_size": metrics["top_cluster_size"],
        "top_cluster_title": metrics.get("top_title", ""),
        "top_cluster_on_topic": metrics["top_on_topic"],
        "top_cluster_off_topic": metrics["top_off_topic"],
        "top_cluster_off_topic_pct": metrics["off_topic_pct"],
        "jaccard_vs_audit_top": round(jaccard, 4),
        "curator_topics_unsliced": topics,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {OUTPUT_PATH}")

    # Acceptance thresholds (from brief)
    checks = [
        ("top_cluster_size", metrics["top_cluster_size"], 103, 171),
        ("off_topic_pct", metrics["off_topic_pct"], 45.3, 61.3),
        ("n_clusters", metrics["n_clusters"], 8, 16),
    ]
    print()
    print("─── Acceptance check ───")
    all_pass = True
    for name, val, lo, hi in checks:
        ok = lo <= val <= hi
        all_pass = all_pass and ok
        print(f"  [{('PASS' if ok else 'FAIL')}] {name}: {val}  (require {lo} ≤ x ≤ {hi})")
    jac_ok = jaccard >= 0.40
    all_pass = all_pass and jac_ok
    print(f"  [{('PASS' if jac_ok else 'FAIL')}] jaccard_vs_audit: {jaccard:.3f}  (require ≥ 0.40)")
    print()
    if all_pass:
        print("✓ ALL THRESHOLDS PASS — safe to proceed with the swap")
        return 0
    print("✗ AT LEAST ONE THRESHOLD FAILED — do NOT swap; surface to Architect")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
