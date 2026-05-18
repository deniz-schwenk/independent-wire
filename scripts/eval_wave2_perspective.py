"""Wave 2 Sweep #5 — Perspective (Opus replacement, V4 Pro grid).

Topic-phase stage. Substrate: `topic_buses.normalize_pre_research.{0,1,2}.json`
carries final_sources / canonical_actors_{stated,reported,mentioned} /
merged_preliminary_divergences / merged_coverage_gaps + editor_selected_topic.

6 variants × 3 topics = 18 calls. max_tokens=160000.
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
from src.schemas import PERSPECTIVE_SCHEMA  # noqa: E402

SWEEP_NAME = "perspective"
SWEEP_DIR = EVAL_OUTPUT_ROOT / "wave-2" / SWEEP_NAME
PREV_STAGE = "normalize_pre_research"
TOPIC_INDICES = (0, 1, 2)

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "perspective" / "SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "perspective" / "INSTRUCTIONS.md"

PERSPECTIVE_USER_MESSAGE = (
    "Identify the position clusters in this dossier. Map missing voices "
    "the dossier could not source."
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
    context = {
        "title": assignment["title"],
        "selection_reason": assignment["selection_reason"],
        "sources": list(topic_bus.get("final_sources") or []),
        "canonical_actors_stated": list(topic_bus.get("canonical_actors_stated") or []),
        "canonical_actors_reported": list(topic_bus.get("canonical_actors_reported") or []),
        "canonical_actors_mentioned": list(topic_bus.get("canonical_actors_mentioned") or []),
        "preliminary_divergences": list(topic_bus.get("merged_preliminary_divergences") or []),
        "coverage_gaps": list(topic_bus.get("merged_coverage_gaps") or []),
    }
    return PERSPECTIVE_USER_MESSAGE, context


def _provider_order_for(variant: Variant) -> list[str] | None:
    if variant.model.startswith("deepseek/"):
        return ["deepseek"]
    return None


def _collect_actor_ids(topic_bus: dict) -> set[str]:
    """Union of input canonical_actors_{stated,reported,mentioned} ids."""
    out = set()
    for k in ("canonical_actors_stated", "canonical_actors_reported", "canonical_actors_mentioned"):
        for a in (topic_bus.get(k) or []):
            if isinstance(a, dict):
                aid = a.get("id")
                if isinstance(aid, str):
                    out.add(aid)
    return out


def aggregate_metrics(sweep_dir: Path) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(sweep_dir.glob("*-topic*.json")):
        with path.open() as f:
            rec = json.load(f)
        by_variant.setdefault(rec["label"], []).append(rec)

    # Baseline shape from disk
    baseline_per_topic = {}
    for tid in TOPIC_INDICES:
        b = json.load(open(f"{SUBSTRATE_ROOT}/topic_buses.PerspectiveStage.{tid}.json"))
        baseline_per_topic[tid] = {
            "n_position_clusters": len(b.get("perspective_clusters") or []),
            "n_missing_positions": len(b.get("perspective_missing_positions") or []),
        }

    rows = []
    for label, recs in sorted(by_variant.items()):
        recs.sort(key=lambda r: r["topic_index"])
        per_topic = []
        for r in recs:
            tid = r["topic_index"]
            s = r.get("structured") or {}
            clusters = [c for c in (s.get("position_clusters") or []) if isinstance(c, dict)]
            missing = [m for m in (s.get("missing_positions") or []) if isinstance(m, dict)]
            # Actor coverage
            input_actor_ids = _collect_actor_ids(load_topic_bus(PREV_STAGE, tid))
            cluster_actor_ids = set()
            stated = reported = mentioned = 0
            for c in clusters:
                for tier_name, counter_key in (
                    ("stated", "stated"),
                    ("reported", "reported"),
                    ("mentioned", "mentioned"),
                ):
                    for aid in (c.get(tier_name) or []):
                        if isinstance(aid, str):
                            cluster_actor_ids.add(aid)
                            if tier_name == "stated":
                                stated += 1
                            elif tier_name == "reported":
                                reported += 1
                            else:
                                mentioned += 1
            actors_per_cluster = (
                sum(len(set((c.get("stated") or []) + (c.get("reported") or []) + (c.get("mentioned") or [])))
                    for c in clusters)
                / max(1, len(clusters))
            )
            coverage_rate = (
                len(input_actor_ids & cluster_actor_ids) / max(1, len(input_actor_ids))
            )
            per_topic.append({
                "topic_index": tid,
                "n_position_clusters": len(clusters),
                "n_missing_positions": len(missing),
                "n_actors_per_cluster_mean": actors_per_cluster,
                "actor_coverage_rate": coverage_rate,
                "tier_stated": stated,
                "tier_reported": reported,
                "tier_mentioned": mentioned,
                "n_input_actor_ids": len(input_actor_ids),
                "cost_usd": r["cost_usd"],
                "tokens_used": r["tokens_used"],
                "wall_seconds": r["wall_seconds"],
                "schema_valid": r.get("schema_valid", False),
                "error": r.get("error"),
                "provider_served": r.get("provider_served"),
            })
        wall = [p["wall_seconds"] for p in per_topic if p["wall_seconds"]]
        first = recs[0]
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
            "n_position_clusters_per_topic": [p["n_position_clusters"] for p in per_topic],
            "n_position_clusters_mean": sum(p["n_position_clusters"] for p in per_topic) / max(1, len(per_topic)),
            "n_actors_per_cluster_mean_per_topic": [p["n_actors_per_cluster_mean"] for p in per_topic],
            "actor_coverage_rate_per_topic": [p["actor_coverage_rate"] for p in per_topic],
            "tier_distribution_per_topic": [
                {"stated": p["tier_stated"], "reported": p["tier_reported"], "mentioned": p["tier_mentioned"]}
                for p in per_topic
            ],
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
            "per_topic": baseline_per_topic,
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
    print(f"[{SWEEP_NAME}] starting {len(VARIANTS)} × {len(TOPIC_INDICES)} = {len(VARIANTS)*len(TOPIC_INDICES)} calls (max_tokens=160000)")

    try:
        await run_sweep(
            sweep_name=SWEEP_NAME,
            sweep_dir=SWEEP_DIR,
            variants=VARIANTS,
            per_topic_messages=per_topic_messages,
            response_format_schema=PERSPECTIVE_SCHEMA,
            schema_name="perspective_output",
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
              f"clusters={row['n_position_clusters_per_topic']} "
              f"coverage={[f'{x:.0%}' for x in row['actor_coverage_rate_per_topic']]} "
              f"valid={row['schema_validity_rate']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
