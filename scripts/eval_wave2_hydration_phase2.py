"""Wave 2 Sweep #4 — Hydration Phase 2 re-run at max_tokens=160000.

Same grid as Wave 1 Sweep #2, same substrate, same prompts — only difference
is max_tokens (Wave 1 used 64000; this wave uses 160000) to test whether
the 36 % divergence-count shortfall vs Opus baseline was reasoning-budget-
bound or model-capacity-bound.

6 variants × 3 topics = 18 calls.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.eval_common import (  # noqa: E402
    EVAL_OUTPUT_ROOT,
    SUBSTRATE_ROOT,
    SpendingCapExceeded,
    Variant,
    build_messages,
    load_topic_bus,
    run_sweep,
)
from src.agent_stages import _build_article_metadata  # noqa: E402
from src.schemas import HYDRATION_PHASE2_SCHEMA  # noqa: E402

SWEEP_NAME = "hydration_phase2"
SWEEP_DIR = EVAL_OUTPUT_ROOT / "wave-2" / SWEEP_NAME
PREV_STAGE = "HydrationPhase1Stage"
TOPIC_INDICES = (0, 1, 2)

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "hydration_aggregator" / "PHASE2-SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "hydration_aggregator" / "PHASE2-INSTRUCTIONS.md"

PHASE2_USER_MESSAGE = (
    "Synthesize cross-article observations from the provided article_analyses "
    "and article_metadata. Return a single JSON object with "
    "preliminary_divergences and coverage_gaps."
)

VARIANTS: list[Variant] = [
    Variant("dskpro-t05-rnone", "deepseek/deepseek-v4-pro", 0.5, "none", streaming=False, max_tokens=160000),
    Variant("dskpro-t05-rmedium", "deepseek/deepseek-v4-pro", 0.5, "medium", streaming=True, max_tokens=160000),
    Variant("dskpro-t05-rhigh", "deepseek/deepseek-v4-pro", 0.5, "high", streaming=True, max_tokens=160000),
    Variant("dskpro-t07-rnone", "deepseek/deepseek-v4-pro", 0.7, "none", streaming=False, max_tokens=160000),
    Variant("dskpro-t07-rmedium", "deepseek/deepseek-v4-pro", 0.7, "medium", streaming=True, max_tokens=160000),
    Variant("dskpro-t07-rhigh", "deepseek/deepseek-v4-pro", 0.7, "high", streaming=True, max_tokens=160000),
]


def _build_topic_message(topic_bus: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    assignment = topic_bus["editor_selected_topic"]
    fetch_results = topic_bus.get("hydration_fetch_results") or []
    successful = [
        r for r in fetch_results if isinstance(r, dict) and r.get("status") == "success"
    ]
    metadata = _build_article_metadata(successful)
    all_analyses = list(topic_bus.get("hydration_phase1_analyses") or [])
    context = {
        "assignment": {
            "title": assignment["title"],
            "selection_reason": assignment["selection_reason"],
        },
        "article_analyses": all_analyses,
        "article_metadata": metadata,
    }
    return PHASE2_USER_MESSAGE, context


def _provider_order_for(variant: Variant) -> list[str] | None:
    if variant.model.startswith("deepseek/"):
        return ["deepseek"]
    return None


def aggregate_metrics(sweep_dir: Path) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(sweep_dir.glob("*-topic*.json")):
        with path.open() as f:
            rec = json.load(f)
        by_variant.setdefault(rec["label"], []).append(rec)

    rows = []
    for label, recs in sorted(by_variant.items()):
        recs.sort(key=lambda r: r["topic_index"])
        per_topic = []
        for r in recs:
            s = r.get("structured") or {}
            divs = [d for d in (s.get("preliminary_divergences") or []) if isinstance(d, str)]
            gaps = [g for g in (s.get("coverage_gaps") or []) if isinstance(g, str)]
            per_topic.append({
                "topic_index": r["topic_index"],
                "n_preliminary_divergences": len(divs),
                "n_coverage_gaps": len(gaps),
                "cost_usd": r["cost_usd"],
                "tokens_used": r["tokens_used"],
                "wall_seconds": r["wall_seconds"],
                "schema_valid": r.get("schema_valid", False),
                "error": r.get("error"),
                "provider_served": r.get("provider_served"),
            })
        wall = [p["wall_seconds"] for p in per_topic if p["wall_seconds"]]
        first = recs[0]
        div_counts = [p["n_preliminary_divergences"] for p in per_topic]
        gap_counts = [p["n_coverage_gaps"] for p in per_topic]
        failures = [p["error"] for p in per_topic if p.get("error")]
        rows.append({
            "label": label,
            "model": first["model_requested"],
            "temperature": first["temperature"],
            "reasoning": first["reasoning"],
            "streaming": first["streaming"],
            "max_tokens": first["max_tokens"],
            "n_topics": len(per_topic),
            "schema_validity_rate": sum(1 for p in per_topic if p["schema_valid"]) / max(1, len(per_topic)),
            "cost_usd_total": sum(p["cost_usd"] for p in per_topic),
            "cost_usd_per_topic_mean": sum(p["cost_usd"] for p in per_topic) / max(1, len(per_topic)),
            "tokens_total": sum(p["tokens_used"] for p in per_topic),
            "wall_seconds_mean": sum(wall) / len(wall) if wall else 0.0,
            "n_preliminary_divergences_per_topic": div_counts,
            "n_preliminary_divergences_mean": sum(div_counts) / max(1, len(div_counts)),
            "n_coverage_gaps_per_topic": gap_counts,
            "n_coverage_gaps_mean": sum(gap_counts) / max(1, len(gap_counts)),
            "failures": failures,
            "any_failure": bool(failures),
            "providers_served": sorted({p.get("provider_served") or "" for p in per_topic}),
            "per_topic_detail": per_topic,
        })

    return {
        "sweep_name": SWEEP_NAME,
        "substrate": {
            "run_id": "c26864b2",
            "date": "2026-05-18",
            "prev_stage": PREV_STAGE,
            "topic_indices": list(TOPIC_INDICES),
        },
        "baseline": {
            "model": "anthropic/claude-opus-4.6",
            "temperature": 0.1,
            "reasoning": "none",
            "max_tokens": 32000,
            "n_preliminary_divergences_per_topic": [9, 10, 6],
            "n_coverage_gaps_per_topic": [9, 10, 8],
            "cost_usd_per_topic_mean": 0.0936,
        },
        "wave1_reference": {
            "best_variant": "dskpro-t07-rhigh",
            "max_tokens_used": 64000,
            "n_preliminary_divergences_per_topic": [7, 5, 4],
            "mean": 5.3,
        },
        "per_sweep_cap_usd": 15.0,
        "variants": rows,
    }


async def main() -> int:
    per_topic_messages: dict[int, list[dict[str, str]]] = {}
    for tid in TOPIC_INDICES:
        topic_bus = load_topic_bus(PREV_STAGE, tid)
        message, context = _build_topic_message(topic_bus)
        per_topic_messages[tid] = build_messages(
            system_prompt_path=SYSTEM_PROMPT_PATH,
            instructions_path=INSTRUCTIONS_PATH,
            message=message,
            context=context,
        )
    provider_order_per_variant = {v.label: _provider_order_for(v) for v in VARIANTS}
    print(f"[{SWEEP_NAME}] starting {len(VARIANTS)} variants × {len(TOPIC_INDICES)} topics = {len(VARIANTS)*len(TOPIC_INDICES)} calls (max_tokens=160000)")

    try:
        await run_sweep(
            sweep_name=SWEEP_NAME,
            sweep_dir=SWEEP_DIR,
            variants=VARIANTS,
            per_topic_messages=per_topic_messages,
            response_format_schema=HYDRATION_PHASE2_SCHEMA,
            schema_name="hydration_phase2_output",
            provider_order_per_variant=provider_order_per_variant,
            cap_usd=15.0,
        )
    except SpendingCapExceeded as e:
        print(f"[{SWEEP_NAME}] WARN: per-sweep cap crossed: {e}", file=sys.stderr)

    metrics = aggregate_metrics(SWEEP_DIR)
    with (SWEEP_DIR / "_metrics.json").open("w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[{SWEEP_NAME}] metrics: {SWEEP_DIR / '_metrics.json'}")
    for row in metrics["variants"]:
        print(f"  {row['label']:25} cost=${row['cost_usd_total']:.4f} "
              f"divs={row['n_preliminary_divergences_per_topic']} "
              f"valid={row['schema_validity_rate']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
