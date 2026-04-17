#!/usr/bin/env python3
"""WP-EVAL-GAP — Evaluate 4 unevaluated pipeline agents across 4 models × 2 reasoning levels.

Runs 4 concurrent lanes (one per model), each executing 8 sequential calls
(4 roles × 2 reasoning levels). Total: 32 LLM calls in ~6-8 minutes.

Usage:
    source .env && python scripts/test_eval_gap.py --reuse 2026-04-07
    source .env && python scripts/test_eval_gap.py --reuse 2026-04-07 --model "z-ai/glm-5"
    source .env && python scripts/test_eval_gap.py --reuse 2026-04-07 --role editor
    source .env && python scripts/test_eval_gap.py --reuse 2026-04-07 --model "z-ai/glm-5" --role editor
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent

MODELS = [
    {"slug": "anthropic/claude-opus-4.6", "name": "Opus 4.6"},
    {"slug": "z-ai/glm-5", "name": "GLM 5"},
    {"slug": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash"},
    {"slug": "anthropic/claude-sonnet-4.6", "name": "Sonnet 4.6"},
]

ROLE_CONFIG = {
    "editor": {
        "prompt": "agents/editor/AGENTS.md",
        "temperature": 0.3,
    },
    "perspektiv": {
        "prompt": "agents/perspektiv/AGENTS.md",
        "temperature": 0.1,
    },
    "qa_analyze": {
        "prompt": "agents/qa_analyze/AGENTS.md",
        "temperature": 0.1,
    },
    "bias_language": {
        "prompt": "agents/bias_detector/AGENTS.md",
        "temperature": 0.1,
    },
}

REASONING_LEVELS = ["none", "medium"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_eval_gap")


# ── Input Loading ─────────────────────────────────────────────────────────

def load_inputs(output_dir: Path, reuse_date: str, roles: list[str]) -> dict[str, tuple[str, dict]]:
    """Load inputs for each role from debug output. Returns {role: (message, context)}."""
    assignments = json.loads((output_dir / "03-editor-assignments.json").read_text())
    topic_1 = assignments[0]
    slug = topic_1["topic_slug"]

    # Fallback slug if primary files missing
    slug_2 = assignments[1]["topic_slug"] if len(assignments) > 1 else None

    inputs: dict[str, tuple[str, dict]] = {}

    for role in roles:
        try:
            if role == "editor":
                topics = json.loads((output_dir / "02-curator-topics.json").read_text())
                inputs[role] = (
                    f"Prioritize these topics for today's report. Today's date is {reuse_date}.",
                    {"topics": topics},
                )

            elif role == "perspektiv":
                dossier_path = output_dir / f"04-researcher-{slug}.json"
                if not dossier_path.exists() and slug_2:
                    dossier_path = output_dir / f"04-researcher-{slug_2}.json"
                    topic_1 = assignments[1]
                if not dossier_path.exists():
                    raise FileNotFoundError(f"No researcher dossier for {slug} or {slug_2}")
                dossier = json.loads(dossier_path.read_text())
                inputs[role] = (
                    "Analyze the spectrum of perspectives for this topic.",
                    {"assignment": topic_1, "research_dossier": dossier},
                )

            elif role == "qa_analyze":
                article_path = output_dir / f"05-writer-{slug}.json"
                dossier_path = output_dir / f"04-researcher-{slug}.json"
                if not article_path.exists() and slug_2:
                    article_path = output_dir / f"05-writer-{slug_2}.json"
                    dossier_path = output_dir / f"04-researcher-{slug_2}.json"
                if not article_path.exists() or not dossier_path.exists():
                    raise FileNotFoundError(f"No writer/researcher files for {slug} or {slug_2}")
                article = json.loads(article_path.read_text())
                dossier = json.loads(dossier_path.read_text())
                inputs[role] = (
                    "Check this article against the source material. Find errors and divergences.",
                    {"article": article, "research_dossier": dossier},
                )

            elif role == "bias_language":
                article_path = output_dir / f"05-writer-{slug}.json"
                bias_path = output_dir / f"08-bias-card-{slug}.json"
                if not article_path.exists() and slug_2:
                    article_path = output_dir / f"05-writer-{slug_2}.json"
                    bias_path = output_dir / f"08-bias-card-{slug_2}.json"
                if not article_path.exists() or not bias_path.exists():
                    raise FileNotFoundError(f"No writer/bias-card files for {slug} or {slug_2}")
                article = json.loads(article_path.read_text())
                bias_card = json.loads(bias_path.read_text())
                inputs[role] = (
                    "Analyze this article for linguistic bias and write a reader note.",
                    {"article_body": article, "bias_card": bias_card},
                )

        except FileNotFoundError as e:
            logger.error("Skipping role '%s': %s", role, e)

    return inputs


# ── LLM Call ──────────────────────────────────────────────────────────────

def make_safe_name(model_name: str) -> str:
    return model_name.lower().replace(" ", "-")


async def run_single(
    role: str,
    model_slug: str,
    model_name: str,
    reasoning_level: str,
    message: str,
    context: dict,
) -> dict:
    """Run a single model call and return result record."""
    config = ROLE_CONFIG[role]

    agent = Agent(
        name=f"eval_{role}",
        model=model_slug,
        prompt_path=str(ROOT / config["prompt"]),
        tools=[],
        temperature=config["temperature"],
        max_tokens=16384,
        provider="openrouter",
        reasoning=reasoning_level,
    )

    record: dict = {
        "eval_role": role,
        "eval_model_slug": model_slug,
        "eval_model_name": model_name,
        "eval_reasoning": reasoning_level,
        "duration_seconds": 0,
        "tokens_used": 0,
        "json_parseable": False,
        "content_length": 0,
        "error": None,
        "raw_output": "",
    }

    start = time.monotonic()
    try:
        result = await agent.run(message, context=context)
        duration = time.monotonic() - start

        record["duration_seconds"] = round(duration, 1)
        record["tokens_used"] = result.tokens_used
        record["content_length"] = len(result.content)
        record["raw_output"] = result.content

        parsed = Agent._parse_json(result.content)
        record["json_parseable"] = parsed is not None

    except Exception as e:
        record["error"] = str(e)
        record["duration_seconds"] = round(time.monotonic() - start, 1)

    return record


# ── Lane (one model, all roles × reasoning) ──────────────────────────────

async def run_lane(
    model: dict,
    roles: list[str],
    inputs: dict[str, tuple[str, dict]],
    eval_dir: Path,
) -> tuple[str, float, list[dict]]:
    """Run all calls for one model sequentially. Returns (model_name, lane_duration, results)."""
    lane_start = time.monotonic()
    results = []
    safe = make_safe_name(model["name"])
    first_call = True

    for role in roles:
        if role not in inputs:
            continue
        message, context = inputs[role]

        for reasoning in REASONING_LEVELS:
            if not first_call:
                await asyncio.sleep(10)
            first_call = False

            logger.info("[%s] %s (reasoning=%s)...", model["name"], role, reasoning)

            record = await run_single(
                role, model["slug"], model["name"], reasoning, message, context,
            )
            results.append(record)

            # Save individual result
            out_path = eval_dir / f"{role}--{safe}--r-{reasoning}.json"
            out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

            status = "OK" if not record["error"] else "ERROR"
            json_ok = "JSON OK" if record["json_parseable"] else "JSON FAIL"
            logger.info(
                "[%s] %s r=%s: %d tokens, %.1fs, %s, %s",
                model["name"], role, reasoning,
                record["tokens_used"], record["duration_seconds"],
                json_ok, status,
            )

    lane_duration = time.monotonic() - lane_start
    return model["name"], lane_duration, results


# ── Summary ───────────────────────────────────────────────────────────────

def write_summary(
    eval_dir: Path,
    all_results: list[dict],
    lane_durations: dict[str, float],
    wall_time: float,
):
    """Write and print summary table."""
    # Sort by role then model
    role_order = list(ROLE_CONFIG.keys())
    all_results.sort(key=lambda r: (
        role_order.index(r["eval_role"]) if r["eval_role"] in role_order else 99,
        r["eval_model_name"],
        r["eval_reasoning"],
    ))

    total_calls = len(all_results)
    lines = [
        f"WP-EVAL-GAP Results — {total_calls} calls, "
        f"{len(lane_durations)} models × {len(role_order)} roles × {len(REASONING_LEVELS)} reasoning",
        "=" * 80,
        f"{'Role':<16s} {'Model':<19s} {'Reasoning':>9s} {'Tokens':>8s} {'Time':>8s} {'JSON':>6s} {'Content':>9s}",
        f"{'-'*16} {'-'*19} {'-'*9} {'-'*8} {'-'*8} {'-'*6} {'-'*9}",
    ]

    for r in all_results:
        json_ok = "OK" if r["json_parseable"] else "FAIL"
        if r.get("error"):
            json_ok = "ERR"
        lines.append(
            f"{r['eval_role']:<16s} {r['eval_model_name']:<19s} "
            f"{r['eval_reasoning']:>9s} {r['tokens_used']:>8d} "
            f"{r['duration_seconds']:>7.1f}s {json_ok:>6s} "
            f"{r['content_length']:>9d}"
        )

    lines.append("")
    lines.append("Lane Duration:")
    for name, dur in lane_durations.items():
        m, s = divmod(int(dur), 60)
        lines.append(f"  {name + ':':22s} {m}m {s:02d}s")
    wm, ws = divmod(int(wall_time), 60)
    lines.append(f"  {'Total wall time:':22s} {wm}m {ws:02d}s (concurrent)")

    report = "\n".join(lines)
    summary_path = eval_dir / "_summary.txt"
    summary_path.write_text(report)
    logger.info("Summary saved to %s", summary_path.name)
    print("\n" + report)


# ── Main ──────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="WP-EVAL-GAP: Evaluate 4 pipeline agents")
    parser.add_argument("--reuse", required=True, help="Date for test data (YYYY-MM-DD)")
    parser.add_argument("--model", default=None, help="Run only this model slug")
    parser.add_argument("--role", default=None, choices=list(ROLE_CONFIG.keys()), help="Run only this role")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    args = parser.parse_args()

    output_dir = ROOT / "output" / args.reuse
    if not output_dir.exists():
        logger.error("Output directory not found: %s", output_dir)
        sys.exit(1)

    today = date.today().isoformat()
    if args.output_dir:
        eval_dir = ROOT / args.output_dir
    else:
        eval_dir = ROOT / "output" / "eval" / f"{today}-eval-gap"
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Select models
    if args.model:
        model_list = [m for m in MODELS if m["slug"] == args.model]
        if not model_list:
            logger.error("Model '%s' not found in MODELS list", args.model)
            sys.exit(1)
    else:
        model_list = MODELS

    # Select roles
    roles = [args.role] if args.role else list(ROLE_CONFIG.keys())

    # Load inputs
    inputs = load_inputs(output_dir, args.reuse, roles)
    if not inputs:
        logger.error("No inputs could be loaded")
        sys.exit(1)
    logger.info("Loaded inputs for %d roles: %s", len(inputs), list(inputs.keys()))

    # Run lanes concurrently
    wall_start = time.monotonic()
    lane_tasks = [
        run_lane(m, roles, inputs, eval_dir)
        for m in model_list
    ]
    lane_results = await asyncio.gather(*lane_tasks)
    wall_time = time.monotonic() - wall_start

    # Collect all results and lane durations
    all_results: list[dict] = []
    lane_durations: dict[str, float] = {}
    for model_name, dur, results in lane_results:
        lane_durations[model_name] = dur
        all_results.extend(results)

    # Write summary
    write_summary(eval_dir, all_results, lane_durations, wall_time)
    print(f"\nAll results saved to: {eval_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
