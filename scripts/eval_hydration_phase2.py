"""Cost-efficiency sweep wave 1, Sweep #2 — hydration_aggregator_phase2 (reducer).

Compares DeepSeek V4 Pro candidates against the Opus 4.6 production baseline
for the HydrationPhase2Stage reducer role. Gemini 3.1 Pro is excluded for
this role per the brief (prior blind eval scored 75-90/120 vs Opus 114/120,
with a structural ceiling at 3-4 divergences/topic regardless of
temp/reasoning).

Substrate: today's V2 hydrated run (run_id `c26864b2`, 3 topics) —
`topic_buses.HydrationPhase1Stage.{0,1,2}.json` carries
`editor_selected_topic` + `hydration_phase1_analyses` +
`hydration_fetch_results` (Phase 2 reducer reads all three).

6 variants × 3 topics = 18 LLM calls. Hard cap: $10.

Outputs:
  - output/eval/hydration_phase2-2026-05-18/{label}-topic{N}.json
  - output/eval/hydration_phase2-2026-05-18/_metrics.json
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
SWEEP_DIR = EVAL_OUTPUT_ROOT / f"{SWEEP_NAME}-2026-05-18"
PREV_STAGE = "HydrationPhase1Stage"
TOPIC_INDICES = (0, 1, 2)

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "hydration_aggregator" / "PHASE2-SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "hydration_aggregator" / "PHASE2-INSTRUCTIONS.md"

# Mirrors `src/agent_stages.py::_PHASE2_USER_MESSAGE`
PHASE2_USER_MESSAGE = (
    "Synthesize cross-article observations from the provided article_analyses "
    "and article_metadata. Return a single JSON object with "
    "preliminary_divergences and coverage_gaps."
)


VARIANTS: list[Variant] = [
    Variant("dskpro-t05-rnone", "deepseek/deepseek-v4-pro", 0.5, "none", streaming=False),
    Variant("dskpro-t05-rmedium", "deepseek/deepseek-v4-pro", 0.5, "medium", streaming=True),
    Variant("dskpro-t05-rhigh", "deepseek/deepseek-v4-pro", 0.5, "high", streaming=True),
    Variant("dskpro-t07-rnone", "deepseek/deepseek-v4-pro", 0.7, "none", streaming=False),
    Variant("dskpro-t07-rmedium", "deepseek/deepseek-v4-pro", 0.7, "medium", streaming=True),
    Variant("dskpro-t07-rhigh", "deepseek/deepseek-v4-pro", 0.7, "high", streaming=True),
]


def _build_topic_message(topic_bus: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Mirrors HydrationPhase2Stage.__call__ + _run_phase2_reducer payload."""
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


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _divs_gaps_from(structured: Any) -> tuple[list[str], list[str]]:
    if not isinstance(structured, dict):
        return [], []
    divs = structured.get("preliminary_divergences") or []
    gaps = structured.get("coverage_gaps") or []
    divs = [d for d in divs if isinstance(d, str)]
    gaps = [g for g in gaps if isinstance(g, str)]
    return divs, gaps


def aggregate_metrics(sweep_dir: Path) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(sweep_dir.glob("*-topic*.json")):
        with path.open() as f:
            rec = json.load(f)
        by_variant.setdefault(rec["label"], []).append(rec)

    rows: list[dict[str, Any]] = []
    for label, recs in sorted(by_variant.items()):
        recs.sort(key=lambda r: r["topic_index"])
        per_topic = []
        for r in recs:
            divs, gaps = _divs_gaps_from(r.get("structured"))
            per_topic.append({
                "topic_index": r["topic_index"],
                "n_preliminary_divergences": len(divs),
                "n_coverage_gaps": len(gaps),
                "div_char_len_median": _median([len(d) for d in divs]) if divs else 0,
                "gap_char_len_median": _median([len(g) for g in gaps]) if gaps else 0,
                "cost_usd": r["cost_usd"],
                "tokens_used": r["tokens_used"],
                "wall_seconds": r["wall_seconds"],
                "schema_valid": r["schema_valid"],
                "provider_served": r.get("provider_served"),
                "error": r.get("error"),
            })
        wall_seconds = [p["wall_seconds"] for p in per_topic if p["wall_seconds"]]
        first = recs[0]
        div_counts = [p["n_preliminary_divergences"] for p in per_topic]
        gap_counts = [p["n_coverage_gaps"] for p in per_topic]
        schema_valid_flags = [p["schema_valid"] for p in per_topic]
        failures = [p["error"] for p in per_topic if p.get("error")]
        rows.append({
            "label": label,
            "model": first["model_requested"],
            "temperature": first["temperature"],
            "reasoning": first["reasoning"],
            "max_tokens": first["max_tokens"],
            "streaming": first["streaming"],
            "n_topics": len(per_topic),
            "n_topics_succeeded": sum(1 for s in schema_valid_flags if s),
            "schema_validity_rate": sum(schema_valid_flags) / max(1, len(schema_valid_flags)),
            "cost_usd_total": sum(p["cost_usd"] for p in per_topic),
            "cost_usd_per_topic_mean": sum(p["cost_usd"] for p in per_topic) / max(1, len(per_topic)),
            "tokens_total": sum(p["tokens_used"] for p in per_topic),
            "wall_seconds_mean": sum(wall_seconds) / len(wall_seconds) if wall_seconds else 0.0,
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
            "stage": "HydrationPhase2Stage",
            "model": "anthropic/claude-opus-4.6",
            "temperature": 0.1,
            "reasoning": "none",
            "max_tokens": 32000,
            "cost_usd_per_topic_mean": 0.0936,
            "cost_usd_total": 0.2808,
            "tokens_per_topic_mean": 14540,
            "tokens_total": 43619,
            "n_preliminary_divergences_per_topic": [9, 10, 6],
            "n_coverage_gaps_per_topic": [9, 10, 8],
        },
        "variants": rows,
    }


def _median(xs: list[int]) -> int:
    if not xs:
        return 0
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) // 2


def write_metrics(metrics: dict[str, Any], sweep_dir: Path) -> Path:
    out = sweep_dir / "_metrics.json"
    with out.open("w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    if not SUBSTRATE_ROOT.exists():
        print(f"FATAL: substrate root missing: {SUBSTRATE_ROOT}", file=sys.stderr)
        return 2

    per_topic_messages: dict[int, list[dict[str, str]]] = {}
    for topic_index in TOPIC_INDICES:
        topic_bus = load_topic_bus(PREV_STAGE, topic_index)
        message, context = _build_topic_message(topic_bus)
        per_topic_messages[topic_index] = build_messages(
            system_prompt_path=SYSTEM_PROMPT_PATH,
            instructions_path=INSTRUCTIONS_PATH,
            message=message,
            context=context,
        )

    provider_order_per_variant = {v.label: _provider_order_for(v) for v in VARIANTS}

    print(f"[{SWEEP_NAME}] starting {len(VARIANTS)} variants × {len(TOPIC_INDICES)} topics "
          f"= {len(VARIANTS) * len(TOPIC_INDICES)} calls (cap $10)")
    print(f"[{SWEEP_NAME}] sweep dir: {SWEEP_DIR}")

    try:
        await run_sweep(
            sweep_name=SWEEP_NAME,
            sweep_dir=SWEEP_DIR,
            variants=VARIANTS,
            per_topic_messages=per_topic_messages,
            response_format_schema=HYDRATION_PHASE2_SCHEMA,
            schema_name="hydration_phase2_output",
            provider_order_per_variant=provider_order_per_variant,
            cap_usd=10.0,
        )
    except SpendingCapExceeded as e:
        print(f"[{SWEEP_NAME}] HALTED: {e}", file=sys.stderr)

    metrics = aggregate_metrics(SWEEP_DIR)
    out = write_metrics(metrics, SWEEP_DIR)
    print(f"[{SWEEP_NAME}] metrics written: {out}")

    print()
    print(f"{'label':25} {'cost':>8} {'tok':>7} {'wall':>7} {'divs':>14} {'gaps':>14} {'valid':>5}")
    for row in metrics["variants"]:
        divs_per = "/".join(str(x) for x in row["n_preliminary_divergences_per_topic"])
        gaps_per = "/".join(str(x) for x in row["n_coverage_gaps_per_topic"])
        print(
            f"{row['label']:25} "
            f"${row['cost_usd_total']:>6.4f} "
            f"{row['tokens_total']:>7d} "
            f"{row['wall_seconds_mean']:>6.1f}s "
            f"{divs_per:>14}  "
            f"{gaps_per:>14}  "
            f"{row['schema_validity_rate']:>4.0%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
