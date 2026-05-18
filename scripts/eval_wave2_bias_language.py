"""Wave 2 Sweep #6 — Bias Language (Opus replacement, V4 Pro grid).

Topic-phase stage. Substrate: `topic_buses.mirror_qa_corrected.{0,1,2}.json`
carries qa_corrected_article + the slots that compose the deterministic
bias_card via `_build_bias_card_for_agent_input`.

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
from src.schemas import BIAS_DETECTOR_SCHEMA  # noqa: E402

SWEEP_NAME = "bias_language"
SWEEP_DIR = EVAL_OUTPUT_ROOT / "wave-2" / SWEEP_NAME
PREV_STAGE = "mirror_qa_corrected"
TOPIC_INDICES = (0, 1, 2)

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "bias_detector" / "SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "bias_detector" / "INSTRUCTIONS.md"

BIAS_USER_MESSAGE = (
    "Analyze this article for linguistic bias. Identify loaded language "
    "and produce a brief reader-note."
)

VARIANTS: list[Variant] = [
    Variant("dskpro-t05-rnone", "deepseek/deepseek-v4-pro", 0.5, "none", streaming=False, max_tokens=160000),
    Variant("dskpro-t05-rmedium", "deepseek/deepseek-v4-pro", 0.5, "medium", streaming=True, max_tokens=160000),
    Variant("dskpro-t05-rhigh", "deepseek/deepseek-v4-pro", 0.5, "high", streaming=True, max_tokens=160000),
    Variant("dskpro-t07-rnone", "deepseek/deepseek-v4-pro", 0.7, "none", streaming=False, max_tokens=160000),
    Variant("dskpro-t07-rmedium", "deepseek/deepseek-v4-pro", 0.7, "medium", streaming=True, max_tokens=160000),
    Variant("dskpro-t07-rhigh", "deepseek/deepseek-v4-pro", 0.7, "high", streaming=True, max_tokens=160000),
]


def _build_topic_message_and_body(topic_bus_dict: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    """Return (message, context, article_body). The bias_card is built
    via the same helper the production wrapper uses, which requires a
    TopicBus pydantic model — we reconstruct just enough by passing the
    raw dict through and dynamically calling the helper."""
    # Use the actual production helper. It needs a TopicBus instance.
    from src.bus import TopicBus
    from src.agent_stages import _build_bias_card_for_agent_input

    tb = TopicBus.model_validate(topic_bus_dict)
    bias_card = _build_bias_card_for_agent_input(tb)
    body = (tb.qa_corrected_article.body if tb.qa_corrected_article else "") or ""
    return BIAS_USER_MESSAGE, {"article_body": body, "bias_card": bias_card}, body


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

    # Baseline shape
    baseline_per_topic = {}
    for tid in TOPIC_INDICES:
        b = json.load(open(f"{SUBSTRATE_ROOT}/topic_buses.BiasLanguageStage.{tid}.json"))
        findings = b.get("bias_language_findings") or []
        baseline_per_topic[tid] = {
            "n_findings": len(findings),
            "reader_note_len": len(b.get("bias_reader_note") or ""),
        }

    # Also need the article bodies for the "quote presence" check
    article_bodies = {}
    for tid in TOPIC_INDICES:
        sub = json.load(open(f"{SUBSTRATE_ROOT}/topic_buses.{PREV_STAGE}.{tid}.json"))
        qca = sub.get("qa_corrected_article") or {}
        body = qca.get("body") if isinstance(qca, dict) else ""
        article_bodies[tid] = body or ""

    rows = []
    for label, recs in sorted(by_variant.items()):
        recs.sort(key=lambda r: r["topic_index"])
        per_topic = []
        for r in recs:
            tid = r["topic_index"]
            s = r.get("structured") or {}
            language_bias = s.get("language_bias") or {}
            findings = []
            if isinstance(language_bias, dict):
                findings = [f for f in (language_bias.get("findings") or []) if isinstance(f, dict)]
            reader_note = s.get("reader_note") or ""

            # Quote-in-body check: share of findings whose `excerpt` appears
            # as a substring in the article body
            body = article_bodies.get(tid, "")
            n_with_quote = sum(
                1 for f in findings
                if isinstance(f.get("excerpt"), str)
                and f.get("excerpt", "").strip()
                and f["excerpt"].strip() in body
            )
            quote_rate = n_with_quote / max(1, len(findings))

            per_topic.append({
                "topic_index": tid,
                "n_findings": len(findings),
                "n_findings_with_quote": n_with_quote,
                "quote_rate": quote_rate,
                "reader_note_len": len(reader_note),
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
            "n_findings_per_topic": [p["n_findings"] for p in per_topic],
            "n_findings_total": sum(p["n_findings"] for p in per_topic),
            "n_findings_with_quote_per_topic": [p["n_findings_with_quote"] for p in per_topic],
            "quote_rate_per_topic": [p["quote_rate"] for p in per_topic],
            "reader_note_len_per_topic": [p["reader_note_len"] for p in per_topic],
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
        message, context, body = _build_topic_message_and_body(topic_bus)
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
            response_format_schema=BIAS_DETECTOR_SCHEMA,
            schema_name="bias_detector_output",
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
              f"findings={row['n_findings_per_topic']} "
              f"quote%={[f'{x:.0%}' for x in row['quote_rate_per_topic']]} "
              f"valid={row['schema_validity_rate']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
