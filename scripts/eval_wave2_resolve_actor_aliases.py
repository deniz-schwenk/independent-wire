"""Wave 2 Sweep #2 — Resolve Actor Aliases (Flash replacement).

Topic-phase stage. Substrate:
`topic_buses.consolidate_actors.{0,1,2}.json` carries `final_actors[]`
(43 / 91 / 39 entries for topics 0/1/2). Production wrapper reads
`final_actors` only.

1 variant × 3 topics. max_tokens=160000.
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
from src.schemas import RESOLVE_ACTOR_ALIASES_SCHEMA  # noqa: E402

SWEEP_NAME = "resolve_actor_aliases"
SWEEP_DIR = EVAL_OUTPUT_ROOT / "wave-2" / SWEEP_NAME
PREV_STAGE = "consolidate_actors"
TOPIC_INDICES = (0, 1, 2)

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "resolve_actor_aliases" / "SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "resolve_actor_aliases" / "INSTRUCTIONS.md"

RESOLVE_USER_MESSAGE = (
    "Identify which actor entries refer to the same real-world entity. "
    "Flag entries whose name is a generic source-class label."
)

VARIANTS: list[Variant] = [
    Variant(
        "dskflash-t05-rnone",
        "deepseek/deepseek-v4-flash",
        0.5,
        "none",
        streaming=False,
        max_tokens=160000,
    ),
]


def _build_topic_message(topic_bus: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return RESOLVE_USER_MESSAGE, {
        "final_actors": list(topic_bus.get("final_actors") or [])
    }


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

    # Build baseline coverage info
    baseline_coverage = {}
    for tid in TOPIC_INDICES:
        baseline = json.load(open(
            f"{SUBSTRATE_ROOT}/topic_buses.ResolveActorAliasesStage.{tid}.json"
        ))
        baseline_coverage[tid] = {
            "n_canonical_actors": len(baseline.get("canonical_actors") or []),
            "n_aliases": len(baseline.get("actor_alias_mapping") or []),
        }

    rows: list[dict[str, Any]] = []
    for label, recs in sorted(by_variant.items()):
        recs.sort(key=lambda r: r["topic_index"])
        per_topic = []
        for r in recs:
            s = r.get("structured")
            aliases = []
            anon = []
            if isinstance(s, dict):
                aliases = [a for a in (s.get("aliases") or []) if isinstance(a, dict)]
                anon = [a for a in (s.get("anonymous_flags") or []) if isinstance(a, str)]
            # Coverage: every input final_actor.id should appear in at least
            # one alias mapping (alias_id or canonical_id) OR remain a
            # canonical (i.e., not appear as alias_id)
            tid = r["topic_index"]
            sub = load_topic_bus(PREV_STAGE, tid)
            input_ids = {a.get("id") for a in (sub.get("final_actors") or []) if isinstance(a, dict)}
            alias_ids = {a.get("alias_id") for a in aliases}
            canonical_ids_from_aliases = {a.get("canonical_id") for a in aliases}
            # canonical_id can be either a separate canonical or another input id
            covered_ids = alias_ids | canonical_ids_from_aliases
            uncovered = input_ids - covered_ids
            # Also count canonical actors implied = input_ids - alias_ids
            implied_canonical = input_ids - alias_ids
            per_topic.append({
                "topic_index": tid,
                "n_aliases": len(aliases),
                "n_anonymous_flags": len(anon),
                "n_input_actors": len(input_ids),
                "n_implied_canonical": len(implied_canonical),
                "n_uncovered_input_ids": len(uncovered),
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
            "max_tokens": first["max_tokens"],
            "streaming": first["streaming"],
            "n_topics": len(per_topic),
            "schema_validity_rate": sum(1 for p in per_topic if p["schema_valid"]) / max(1, len(per_topic)),
            "cost_usd_total": sum(p["cost_usd"] for p in per_topic),
            "cost_usd_per_topic_mean": sum(p["cost_usd"] for p in per_topic) / max(1, len(per_topic)),
            "tokens_total": sum(p["tokens_used"] for p in per_topic),
            "wall_seconds_mean": sum(wall) / len(wall) if wall else 0.0,
            "n_aliases_per_topic": [p["n_aliases"] for p in per_topic],
            "n_anonymous_flags_per_topic": [p["n_anonymous_flags"] for p in per_topic],
            "n_implied_canonical_per_topic": [p["n_implied_canonical"] for p in per_topic],
            "n_uncovered_input_ids_per_topic": [p["n_uncovered_input_ids"] for p in per_topic],
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
            "model": "google/gemini-3-flash-preview",
            "temperature": 1.0,
            "reasoning": "medium",
            "max_tokens": 66000,
            "per_topic": baseline_coverage,
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
    print(f"[{SWEEP_NAME}] starting {len(VARIANTS)} variants × {len(TOPIC_INDICES)} topics")
    print(f"[{SWEEP_NAME}] sweep dir: {SWEEP_DIR}")

    try:
        await run_sweep(
            sweep_name=SWEEP_NAME,
            sweep_dir=SWEEP_DIR,
            variants=VARIANTS,
            per_topic_messages=per_topic_messages,
            response_format_schema=RESOLVE_ACTOR_ALIASES_SCHEMA,
            schema_name="resolve_actor_aliases_output",
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
              f"aliases={row['n_aliases_per_topic']} "
              f"valid={row['schema_validity_rate']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
