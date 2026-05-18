"""Wave 2 Sweep #3 — Editor (Opus replacement, V4 Pro grid).

Run-phase stage: fires once per pipeline run. Substrate:
`run_bus.assemble_curator_topics.json` carries `curator_topics[]` (10
candidates) and `previous_coverage[]`.

6 variants × 1 call. max_tokens=160000.
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
    SpendTracker,
    Variant,
    build_client,
    build_messages,
    call_openrouter,
    load_run_bus,
)
from src.schemas import EDITOR_SCHEMA  # noqa: E402

SWEEP_NAME = "editor"
SWEEP_DIR = EVAL_OUTPUT_ROOT / "wave-2" / SWEEP_NAME

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "editor" / "SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "editor" / "INSTRUCTIONS.md"

VARIANTS: list[Variant] = [
    Variant("dskpro-t05-rnone", "deepseek/deepseek-v4-pro", 0.5, "none", streaming=False, max_tokens=160000),
    Variant("dskpro-t05-rmedium", "deepseek/deepseek-v4-pro", 0.5, "medium", streaming=True, max_tokens=160000),
    Variant("dskpro-t05-rhigh", "deepseek/deepseek-v4-pro", 0.5, "high", streaming=True, max_tokens=160000),
    Variant("dskpro-t07-rnone", "deepseek/deepseek-v4-pro", 0.7, "none", streaming=False, max_tokens=160000),
    Variant("dskpro-t07-rmedium", "deepseek/deepseek-v4-pro", 0.7, "medium", streaming=True, max_tokens=160000),
    Variant("dskpro-t07-rhigh", "deepseek/deepseek-v4-pro", 0.7, "high", streaming=True, max_tokens=160000),
]


def _build_run_message_and_context() -> tuple[str, dict[str, Any]]:
    sub = load_run_bus("assemble_curator_topics")
    curated = list(sub.get("curator_topics") or [])
    previous = list(sub.get("previous_coverage") or [])
    run_date = sub.get("run_date") or ""
    message = (
        "Prioritize these topics for today's report. For each, assign a "
        "priority (1-10) and a selection_reason. Today's date is "
        f"{run_date}."
    )
    return message, {"topics": curated, "previous_coverage": previous}


def _output_path(label: str) -> Path:
    return SWEEP_DIR / f"{label}.json"


def _has_usable_cache(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open() as f:
            data = json.load(f)
        return data.get("structured") not in (None, {}, []) and not data.get("error")
    except (json.JSONDecodeError, OSError):
        return False


async def main() -> int:
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)

    message, context = _build_run_message_and_context()
    messages = build_messages(
        system_prompt_path=SYSTEM_PROMPT_PATH,
        instructions_path=INSTRUCTIONS_PATH,
        message=message,
        context=context,
    )

    tracker = SpendTracker(cap_usd=15.0)
    client = build_client()
    print(f"[{SWEEP_NAME}] starting {len(VARIANTS)} variants × 1 run-phase call")
    print(f"[{SWEEP_NAME}] sweep dir: {SWEEP_DIR}")

    try:
        # Run variants sequentially — cap enforced after each
        for variant in VARIANTS:
            out_path = _output_path(variant.label)
            if _has_usable_cache(out_path):
                print(f"[{SWEEP_NAME}] {variant.label} (cached)")
                continue

            try:
                content, structured, telemetry = await call_openrouter(
                    client=client,
                    variant=variant,
                    messages=messages,
                    response_format_schema=EDITOR_SCHEMA,
                    schema_name="editor_output",
                    provider_order=["deepseek"],
                )
                error = None
            except Exception as e:  # noqa: BLE001
                content = ""
                structured = None
                telemetry = {
                    "cost_usd": 0.0,
                    "tokens_used": 0,
                    "wall_seconds": 0.0,
                    "model_served": variant.model,
                    "provider_served": "",
                    "response_id": "",
                    "schema_valid": False,
                }
                error = f"{type(e).__name__}: {e}"

            record = {
                "label": variant.label,
                "model_requested": variant.model,
                "model_served": telemetry["model_served"],
                "provider_served": telemetry["provider_served"],
                "response_id": telemetry["response_id"],
                "temperature": variant.temperature,
                "reasoning": variant.reasoning,
                "streaming": variant.streaming,
                "max_tokens": variant.max_tokens,
                "schema_valid": telemetry["schema_valid"],
                "cost_usd": telemetry["cost_usd"],
                "tokens_used": telemetry["tokens_used"],
                "wall_seconds": telemetry["wall_seconds"],
                "error": error,
                "content": content,
                "structured": structured,
            }
            with out_path.open("w") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            print(
                f"[{SWEEP_NAME}] {variant.label}: ${record['cost_usd']:.4f} "
                f"{record['tokens_used']} tok {record['wall_seconds']:.1f}s "
                f"valid={record['schema_valid']} err={error}"
            )
            if error is None:
                tracker.add(variant.label, record["cost_usd"])
    except SpendingCapExceeded as e:
        print(f"[{SWEEP_NAME}] WARN: per-sweep cap crossed: {e}", file=sys.stderr)
    finally:
        await client.close()

    # Aggregate
    baseline = json.load(open(f"{SUBSTRATE_ROOT}/run_bus.EditorStage.json"))
    baseline_assignments = baseline.get("editor_assignments") or []
    baseline_titles = [
        a.get("title", "")
        for a in baseline_assignments
        if a.get("id")  # only kept (assigned ID) topics
    ][:3]  # top-3
    baseline_titles_all = [a.get("title", "") for a in baseline_assignments]

    rows = []
    for variant in VARIANTS:
        path = _output_path(variant.label)
        if not path.exists():
            continue
        with path.open() as f:
            rec = json.load(f)
        s = rec.get("structured") or {}
        assignments = []
        if isinstance(s, dict):
            assignments = [a for a in (s.get("assignments") or []) if isinstance(a, dict)]
        titles = [a.get("title", "") for a in assignments]
        decision_log_len = sum(
            len(a.get("selection_reason", "") or "") for a in assignments
        )
        overlap_top3 = sum(1 for t in titles[:3] if t in baseline_titles)
        overlap_any = sum(1 for t in titles if t in baseline_titles_all)
        rows.append({
            "label": rec["label"],
            "model": rec["model_requested"],
            "temperature": rec["temperature"],
            "reasoning": rec["reasoning"],
            "streaming": rec["streaming"],
            "max_tokens": rec["max_tokens"],
            "schema_validity_rate": 1.0 if rec.get("schema_valid") else 0.0,
            "cost_usd": rec["cost_usd"],
            "wall_seconds": rec["wall_seconds"],
            "tokens_used": rec["tokens_used"],
            "n_topics_selected": len(assignments),
            "editorial_decision_log_length": decision_log_len,
            "same_topic_top3_overlap_vs_baseline": overlap_top3,
            "same_topic_any_overlap_vs_baseline": overlap_any,
            "titles_selected": titles,
            "providers_served": [rec.get("provider_served") or ""],
            "error": rec.get("error"),
        })

    metrics = {
        "sweep_name": SWEEP_NAME,
        "substrate": {
            "run_id": "c26864b2",
            "date": "2026-05-18",
            "substrate_file": "run_bus.assemble_curator_topics.json",
        },
        "baseline": {
            "model": "anthropic/claude-opus-4.6",
            "temperature": 0.3,
            "reasoning": "none",
            "n_topics_selected": len(baseline_assignments),
            "top3_baseline_titles": baseline_titles,
            "all_baseline_titles": baseline_titles_all,
        },
        "cumulative_cost_usd": tracker.cumulative_usd,
        "per_sweep_cap_usd": 15.0,
        "variants": rows,
    }
    with (SWEEP_DIR / "_metrics.json").open("w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[{SWEEP_NAME}] metrics: {SWEEP_DIR / '_metrics.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
