"""Cost-efficiency sweep wave 1, Sweep #1 — researcher_hydrated_plan.

Compares DeepSeek V4 Pro and Gemini 3.1 Pro Preview candidates against the
Opus 4.6 production baseline for the ResearcherHydratedPlanStage role.

Substrate: today's V2 hydrated run (run_id `c26864b2`, 3 topics) — the
`topic_buses.assemble_hydration_dossier.{0,1,2}.json` snapshots, which
carry `editor_selected_topic` + `hydration_pre_dossier` (the Bus slots
the production wrapper reads).

8 variants × 3 topics = 24 LLM calls.  Hard cap: $10.

Outputs:
  - output/eval/researcher_plan-2026-05-18/{label}-topic{N}.json
  - output/eval/researcher_plan-2026-05-18/_metrics.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
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
from src.agent_stages import _build_coverage_summary  # noqa: E402
from src.schemas import RESEARCHER_PLAN_SCHEMA  # noqa: E402

SWEEP_NAME = "researcher_plan"
SWEEP_DIR = EVAL_OUTPUT_ROOT / f"{SWEEP_NAME}-2026-05-18"
PREV_STAGE = "assemble_hydration_dossier"
TOPIC_INDICES = (0, 1, 2)
RUN_DATE = "2026-05-18"

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "researcher_hydrated" / "PLAN-SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "researcher_hydrated" / "PLAN-INSTRUCTIONS.md"


VARIANTS: list[Variant] = [
    Variant("dskpro-t05-rnone", "deepseek/deepseek-v4-pro", 0.5, "none", streaming=False),
    Variant("dskpro-t05-rmedium", "deepseek/deepseek-v4-pro", 0.5, "medium", streaming=True),
    Variant("dskpro-t05-rhigh", "deepseek/deepseek-v4-pro", 0.5, "high", streaming=True),
    Variant("dskpro-t07-rnone", "deepseek/deepseek-v4-pro", 0.7, "none", streaming=False),
    Variant("dskpro-t07-rmedium", "deepseek/deepseek-v4-pro", 0.7, "medium", streaming=True),
    Variant("dskpro-t07-rhigh", "deepseek/deepseek-v4-pro", 0.7, "high", streaming=True),
    Variant("gpro-rlow", "google/gemini-3.1-pro-preview", 1.0, "low", streaming=False),
    Variant("gpro-rhigh", "google/gemini-3.1-pro-preview", 1.0, "high", streaming=False),
]


def _build_topic_message(topic_bus: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Mirrors ResearcherHydratedPlanStage.__call__ in src/agent_stages.py."""
    assignment = topic_bus["editor_selected_topic"]
    pre_dossier = topic_bus["hydration_pre_dossier"]
    coverage_summary = _build_coverage_summary(pre_dossier)
    message = (
        "Plan multilingual queries to gap-fill the existing pre-dossier. "
        f"Today is {RUN_DATE}."
    )
    context = {
        "title": assignment["title"],
        "selection_reason": assignment["selection_reason"],
        "raw_data": dict(assignment.get("raw_data") or {}),
        "coverage_summary": coverage_summary,
        "today": RUN_DATE,
    }
    return message, context


def _provider_order_for(variant: Variant) -> list[str] | None:
    if variant.model.startswith("deepseek/"):
        return ["deepseek"]
    return None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _queries_from(structured: Any) -> list[dict[str, Any]]:
    if isinstance(structured, dict):
        q = structured.get("queries")
        if isinstance(q, list):
            return [x for x in q if isinstance(x, dict)]
    if isinstance(structured, list):
        return [x for x in structured if isinstance(x, dict)]
    return []


def aggregate_metrics(sweep_dir: Path) -> dict[str, Any]:
    """Aggregate per-variant metrics across the three topics."""
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(sweep_dir.glob("*-topic*.json")):
        with path.open() as f:
            rec = json.load(f)
        by_variant.setdefault(rec["label"], []).append(rec)

    rows: list[dict[str, Any]] = []
    for label, recs in sorted(by_variant.items()):
        recs.sort(key=lambda r: r["topic_index"])
        wall_seconds = [r["wall_seconds"] for r in recs if r.get("wall_seconds")]
        costs = [r["cost_usd"] for r in recs]
        tokens = [r["tokens_used"] for r in recs]
        per_topic_queries = [_queries_from(r.get("structured")) for r in recs]
        per_topic_query_count = [len(q) for q in per_topic_queries]
        per_topic_unique_langs = [len({q.get("language") for q in qs}) for qs in per_topic_queries]

        # story_shape_compliance: share of (across all variants, all topics)
        # queries that carry a non-null "story_shape" field. Note: the
        # production strict schema disallows additionalProperties, so a
        # well-behaved schema-honouring model will NEVER emit this field
        # — the metric is structurally pinned to 0. Recorded anyway in
        # case a variant slips it past strict-mode (which would itself
        # be telemetry).
        all_q = [q for qs in per_topic_queries for q in qs]
        story_shape_count = sum(
            1 for q in all_q if q.get("story_shape") not in (None, "")
        )
        story_shape_compliance = (
            story_shape_count / len(all_q) if all_q else 0.0
        )

        schema_valid_flags = [r.get("schema_valid", False) for r in recs]
        failure_reasons = [r.get("error") for r in recs if r.get("error")]
        any_failure = bool(failure_reasons)

        # Reasoning vs prompt requirement: prompt says minimum 10 queries,
        # at least half non-English.
        queries_min_compliance = sum(
            1 for cnt in per_topic_query_count if cnt >= 10
        ) / max(1, len(per_topic_query_count))
        non_en_share_per_topic = [
            sum(1 for q in qs if q.get("language") != "en") / max(1, len(qs))
            for qs in per_topic_queries
        ]
        non_en_share_mean = (
            sum(non_en_share_per_topic) / len(non_en_share_per_topic)
            if non_en_share_per_topic else 0.0
        )
        non_en_compliance = sum(
            1 for s in non_en_share_per_topic if s >= 0.5
        ) / max(1, len(non_en_share_per_topic))

        # Language histogram across the three topics combined
        lang_counter: Counter[str] = Counter()
        for q in all_q:
            lang = q.get("language")
            if lang:
                lang_counter[lang] += 1

        # representative variant metadata
        first = recs[0]
        rows.append({
            "label": label,
            "model": first["model_requested"],
            "temperature": first["temperature"],
            "reasoning": first["reasoning"],
            "max_tokens": first["max_tokens"],
            "streaming": first["streaming"],
            "n_topics": len(recs),
            "n_topics_succeeded": sum(1 for r in recs if r.get("schema_valid")),
            "schema_validity_rate": sum(schema_valid_flags) / max(1, len(schema_valid_flags)),
            "cost_usd_total": sum(costs),
            "cost_usd_per_topic_mean": sum(costs) / max(1, len(costs)),
            "tokens_total": sum(tokens),
            "tokens_per_topic_mean": sum(tokens) / max(1, len(tokens)),
            "wall_seconds_mean": (sum(wall_seconds) / len(wall_seconds)) if wall_seconds else 0.0,
            "queries_count_per_topic": per_topic_query_count,
            "queries_count_mean": (
                sum(per_topic_query_count) / max(1, len(per_topic_query_count))
            ),
            "unique_languages_per_topic": per_topic_unique_langs,
            "unique_languages_mean": (
                sum(per_topic_unique_langs) / max(1, len(per_topic_unique_langs))
            ),
            "language_histogram": dict(sorted(lang_counter.items(), key=lambda kv: (-kv[1], kv[0]))),
            "min_query_count_compliance": queries_min_compliance,
            "non_english_share_mean": non_en_share_mean,
            "non_english_share_compliance": non_en_compliance,
            "story_shape_compliance": story_shape_compliance,
            "story_shape_compliance_note": (
                "Strict-mode response_format on RESEARCHER_PLAN_SCHEMA disallows "
                "additionalProperties; story_shape field is structurally absent."
            ),
            "failures": failure_reasons,
            "any_failure": any_failure,
            "providers_served": sorted({r.get("provider_served") or "" for r in recs}),
        })

    return {
        "sweep_name": SWEEP_NAME,
        "substrate": {
            "run_id": "c26864b2",
            "date": RUN_DATE,
            "prev_stage": PREV_STAGE,
            "topic_indices": list(TOPIC_INDICES),
        },
        "baseline": {
            "stage": "ResearcherHydratedPlanStage",
            "model": "anthropic/claude-opus-4.6",
            "temperature": 0.5,
            "reasoning": "none",
            "max_tokens": 16384,
            "cost_usd_per_topic_mean": 0.05404,
            "cost_usd_total": 0.16212,
            "tokens_per_topic_mean": 7471,
            "tokens_total": 22413,
            "queries_count_per_topic": [23, None, None],  # only topic 0 inspected at substrate time; report enriches
        },
        "variants": rows,
    }


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

    provider_order_per_variant = {
        v.label: _provider_order_for(v) for v in VARIANTS
    }

    print(f"[{SWEEP_NAME}] starting {len(VARIANTS)} variants × {len(TOPIC_INDICES)} topics "
          f"= {len(VARIANTS) * len(TOPIC_INDICES)} calls (cap $10)")
    print(f"[{SWEEP_NAME}] sweep dir: {SWEEP_DIR}")

    try:
        await run_sweep(
            sweep_name=SWEEP_NAME,
            sweep_dir=SWEEP_DIR,
            variants=VARIANTS,
            per_topic_messages=per_topic_messages,
            response_format_schema=RESEARCHER_PLAN_SCHEMA,
            schema_name="researcher_plan_output",
            provider_order_per_variant=provider_order_per_variant,
            cap_usd=10.0,
        )
    except SpendingCapExceeded as e:
        print(f"[{SWEEP_NAME}] HALTED: {e}", file=sys.stderr)

    metrics = aggregate_metrics(SWEEP_DIR)
    out = write_metrics(metrics, SWEEP_DIR)
    print(f"[{SWEEP_NAME}] metrics written: {out}")

    # Print a compact summary
    print()
    print(f"{'label':25} {'cost':>8} {'tok':>7} {'wall':>6} {'queries':>8} {'langs':>5} {'valid':>5}")
    for row in metrics["variants"]:
        print(
            f"{row['label']:25} "
            f"${row['cost_usd_total']:>6.4f} "
            f"{row['tokens_total']:>7d} "
            f"{row['wall_seconds_mean']:>5.1f}s "
            f"{row['queries_count_mean']:>7.1f}  "
            f"{row['unique_languages_mean']:>4.1f}  "
            f"{row['schema_validity_rate']:>4.0%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
