"""Cost-efficiency sweep wave 1, Sweep #3 — researcher_assemble (Flash replacement).

Compares DeepSeek V4 Flash variants against the Gemini Flash 3 production
baseline for the ResearcherAssembleStage role. Per the in-flight course
correction (2026-05-18) the V1-era over-clustering pathology cited as a
reason to exclude reasoning≥medium does NOT generalize to V2's extraction
role (researcher_assemble extracts; it does not cluster). All four
reasoning levels for both temperatures are tested. Reasoning∈{medium,
high} variants stream (same Option B wiring as Phase 1/2).

Substrate: today's V2 hydrated run (run_id `c26864b2`, 3 topics) —
`topic_buses.researcher_search.{0,1,2}.json` carries
`editor_selected_topic` + `researcher_search_results`.

6 variants × 3 topics = 18 LLM calls. Hard cap: $10.

Outputs:
  - output/eval/researcher_assemble-2026-05-18/{label}-topic{N}.json
  - output/eval/researcher_assemble-2026-05-18/_metrics.json
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
    load_run_bus,
    load_topic_bus,
    run_sweep,
)
from src.schemas import RESEARCHER_ASSEMBLE_SCHEMA  # noqa: E402

SWEEP_NAME = "researcher_assemble"
SWEEP_DIR = EVAL_OUTPUT_ROOT / f"{SWEEP_NAME}-2026-05-18"
PREV_STAGE = "researcher_search"
TOPIC_INDICES = (0, 1, 2)
RUN_DATE = "2026-05-18"

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "researcher" / "ASSEMBLE-SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "researcher" / "ASSEMBLE-INSTRUCTIONS.md"

# Mirrors ResearcherAssembleStage.__call__ message
ASSEMBLE_USER_MESSAGE = (
    "Build a research dossier from these search results. "
    "Extract sources, actors, divergences, and coverage gaps."
)


VARIANTS: list[Variant] = [
    Variant("dskflash-t05-rnone", "deepseek/deepseek-v4-flash", 0.5, "none", streaming=False),
    Variant("dskflash-t05-rmedium", "deepseek/deepseek-v4-flash", 0.5, "medium", streaming=True),
    Variant("dskflash-t05-rhigh", "deepseek/deepseek-v4-flash", 0.5, "high", streaming=True),
    Variant("dskflash-t07-rnone", "deepseek/deepseek-v4-flash", 0.7, "none", streaming=False),
    Variant("dskflash-t07-rmedium", "deepseek/deepseek-v4-flash", 0.7, "medium", streaming=True),
    Variant("dskflash-t07-rhigh", "deepseek/deepseek-v4-flash", 0.7, "high", streaming=True),
]


def _build_topic_message(topic_bus: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Mirrors ResearcherAssembleStage.__call__ in src/agent_stages.py."""
    assignment = topic_bus["editor_selected_topic"]
    context = {
        "assignment": {
            "title": assignment["title"],
            "selection_reason": assignment["selection_reason"],
        },
        "date": RUN_DATE,
        "search_results": list(topic_bus.get("researcher_search_results") or []),
    }
    return ASSEMBLE_USER_MESSAGE, context


def _provider_order_for(variant: Variant) -> list[str] | None:
    if variant.model.startswith("deepseek/"):
        return ["deepseek"]
    return None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _median(xs: list[int]) -> int:
    if not xs:
        return 0
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) // 2


def _percentile(xs: list[int], p: float) -> int:
    if not xs:
        return 0
    xs = sorted(xs)
    idx = int(p * (len(xs) - 1))
    return xs[idx]


def _extract_metrics(structured: Any) -> dict[str, Any]:
    if not isinstance(structured, dict):
        return {
            "n_sources_extracted": 0,
            "n_preliminary_divergences": 0,
            "n_coverage_gaps": 0,
            "summary_length_p50": 0,
            "summary_length_p90": 0,
            "n_actors_total": 0,
            "n_languages": 0,
        }
    sources = structured.get("sources") or []
    divs = structured.get("preliminary_divergences") or []
    gaps = structured.get("coverage_gaps") or []
    summary_lens = [len(s.get("summary", "")) for s in sources if isinstance(s, dict)]
    actors = sum(len(s.get("actors_quoted") or []) for s in sources if isinstance(s, dict))
    languages = {s.get("language") for s in sources if isinstance(s, dict) and s.get("language")}
    return {
        "n_sources_extracted": len(sources),
        "n_preliminary_divergences": sum(1 for d in divs if isinstance(d, str)),
        "n_coverage_gaps": sum(1 for g in gaps if isinstance(g, str)),
        "summary_length_p50": _percentile(summary_lens, 0.5),
        "summary_length_p90": _percentile(summary_lens, 0.9),
        "n_actors_total": actors,
        "n_languages": len(languages),
    }


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
            mtx = _extract_metrics(r.get("structured"))
            per_topic.append({
                "topic_index": r["topic_index"],
                **mtx,
                "cost_usd": r["cost_usd"],
                "tokens_used": r["tokens_used"],
                "wall_seconds": r["wall_seconds"],
                "schema_valid": r["schema_valid"],
                "provider_served": r.get("provider_served"),
                "error": r.get("error"),
            })
        wall_seconds = [p["wall_seconds"] for p in per_topic if p["wall_seconds"]]
        first = recs[0]
        schema_valid_flags = [p["schema_valid"] for p in per_topic]
        failures = [p["error"] for p in per_topic if p.get("error")]
        sources_per_topic = [p["n_sources_extracted"] for p in per_topic]
        divs_per_topic = [p["n_preliminary_divergences"] for p in per_topic]
        gaps_per_topic = [p["n_coverage_gaps"] for p in per_topic]
        summary_p50s = [p["summary_length_p50"] for p in per_topic]
        summary_p90s = [p["summary_length_p90"] for p in per_topic]
        rows.append({
            "label": label,
            "model": first["model_requested"],
            "temperature": first["temperature"],
            "reasoning": first["reasoning"],
            "max_tokens": first["max_tokens"],
            "streaming": first["streaming"],
            "n_topics": len(per_topic),
            "schema_validity_rate": sum(schema_valid_flags) / max(1, len(schema_valid_flags)),
            "cost_usd_total": sum(p["cost_usd"] for p in per_topic),
            "cost_usd_per_topic_mean": sum(p["cost_usd"] for p in per_topic) / max(1, len(per_topic)),
            "tokens_total": sum(p["tokens_used"] for p in per_topic),
            "wall_seconds_mean": sum(wall_seconds) / len(wall_seconds) if wall_seconds else 0.0,
            "n_sources_extracted_per_topic": sources_per_topic,
            "n_sources_extracted_mean": sum(sources_per_topic) / max(1, len(sources_per_topic)),
            "n_preliminary_divergences_per_topic": divs_per_topic,
            "n_preliminary_divergences_mean": sum(divs_per_topic) / max(1, len(divs_per_topic)),
            "n_coverage_gaps_per_topic": gaps_per_topic,
            "summary_length_p50_per_topic": summary_p50s,
            "summary_length_p90_per_topic": summary_p90s,
            "summary_length_p50_median": _median(summary_p50s),
            "summary_length_p90_median": _median(summary_p90s),
            "n_actors_total_per_topic": [p["n_actors_total"] for p in per_topic],
            "n_languages_per_topic": [p["n_languages"] for p in per_topic],
            "failures": failures,
            "any_failure": bool(failures),
            "providers_served": sorted({p.get("provider_served") or "" for p in per_topic}),
            "per_topic_detail": per_topic,
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
            "stage": "ResearcherAssembleStage",
            "model": "google/gemini-3-flash-preview",
            "temperature": 0.2,
            "reasoning": "none",
            "max_tokens": 8000,  # production default
            "cost_usd_per_topic_mean": 0.02593,
            "cost_usd_total": 0.0778,
            "tokens_per_topic_mean": 35726,
            "tokens_total": 107178,
            "n_sources_extracted_per_topic": [15, 12, 10],
            "n_preliminary_divergences_per_topic": [3, 3, 1],
            "n_coverage_gaps_per_topic": [3, 3, 2],
            "summary_length_p50_per_topic": [156, 137, 127],
            "summary_length_p90_per_topic": [180, 143, 156],
            "input_search_results_per_topic": [23, 23, 23],
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
            response_format_schema=RESEARCHER_ASSEMBLE_SCHEMA,
            schema_name="researcher_assemble_output",
            provider_order_per_variant=provider_order_per_variant,
            cap_usd=10.0,
        )
    except SpendingCapExceeded as e:
        print(f"[{SWEEP_NAME}] HALTED: {e}", file=sys.stderr)

    metrics = aggregate_metrics(SWEEP_DIR)
    out = write_metrics(metrics, SWEEP_DIR)
    print(f"[{SWEEP_NAME}] metrics written: {out}")

    print()
    print(f"{'label':25} {'cost':>8} {'tok':>7} {'wall':>7} {'src':>12} {'divs':>10} {'sum_p50':>10} {'valid':>5}")
    for row in metrics["variants"]:
        src_per = "/".join(str(x) for x in row["n_sources_extracted_per_topic"])
        divs_per = "/".join(str(x) for x in row["n_preliminary_divergences_per_topic"])
        p50_per = "/".join(str(x) for x in row["summary_length_p50_per_topic"])
        print(
            f"{row['label']:25} "
            f"${row['cost_usd_total']:>6.4f} "
            f"{row['tokens_total']:>7d} "
            f"{row['wall_seconds_mean']:>6.1f}s "
            f"{src_per:>11}  "
            f"{divs_per:>9}  "
            f"{p50_per:>9}  "
            f"{row['schema_validity_rate']:>4.0%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
