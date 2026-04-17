#!/usr/bin/env python3
"""Researcher + Writer Eval — 5 models × 3 roles, concurrent lanes, reasoning=none.

Runs 5 concurrent lanes (one per model), each executing 3 sequential calls
(researcher_plan → researcher_assemble → writer). Total: 15 LLM calls.

Usage:
    source .env && python scripts/test_researcher_writer.py --reuse 2026-04-07
    source .env && python scripts/test_researcher_writer.py --reuse 2026-04-07 --model "z-ai/glm-5"
    source .env && python scripts/test_researcher_writer.py --reuse 2026-04-07 --role writer
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
from src.tools import web_search_tool

MODELS = [
    {"slug": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash"},
    {"slug": "z-ai/glm-5", "name": "GLM 5"},
    {"slug": "anthropic/claude-haiku-4.5", "name": "Haiku 4.5"},
    {"slug": "anthropic/claude-sonnet-4.6", "name": "Sonnet 4.6"},
    {"slug": "anthropic/claude-opus-4.6", "name": "Opus 4.6"},
]

ROLE_CONFIG = {
    "researcher_plan": {
        "prompt": "agents/researcher/PLAN.md",
        "temperature": 0.5,
        "tools": False,
    },
    "researcher_assemble": {
        "prompt": "agents/researcher/ASSEMBLE.md",
        "temperature": 0.2,
        "tools": False,
    },
    "writer": {
        "prompt": "agents/writer/AGENTS.md",
        "temperature": 0.3,
        "tools": True,
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_rw")


# ── Input Loading ─────────────────────────────────────────────────────────

def load_inputs(output_dir: Path, reuse_date: str, roles: list[str]) -> dict[str, tuple[str, dict]]:
    """Load inputs for each role. Returns {role: (message, context)}."""
    assignments = json.loads((output_dir / "03-editor-assignments.json").read_text())
    topic_1 = assignments[0]
    slug = topic_1["topic_slug"]
    slug_2 = assignments[1]["topic_slug"] if len(assignments) > 1 else None

    inputs: dict[str, tuple[str, dict]] = {}

    for role in roles:
        try:
            if role == "researcher_plan":
                inputs[role] = (
                    f"Plan multilingual research queries for this topic. Today is {reuse_date}.",
                    topic_1,
                )

            elif role == "researcher_assemble":
                search_path = output_dir / f"04-researcher-search-{slug}.json"
                if not search_path.exists() and slug_2:
                    search_path = output_dir / f"04-researcher-search-{slug_2}.json"
                    topic_1 = assignments[1]
                if not search_path.exists():
                    raise FileNotFoundError(f"No search results for {slug} or {slug_2}")
                search_results = json.loads(search_path.read_text())
                inputs[role] = (
                    "Build a research dossier from these search results. "
                    "Extract sources, actors, divergences, and coverage gaps.",
                    {"assignment": topic_1, "search_results": search_results},
                )

            elif role == "writer":
                dossier_path = output_dir / f"04-researcher-{slug}.json"
                perspektiv_path = output_dir / f"04b-perspektiv-{slug}.json"
                if not dossier_path.exists() and slug_2:
                    dossier_path = output_dir / f"04-researcher-{slug_2}.json"
                    perspektiv_path = output_dir / f"04b-perspektiv-{slug_2}.json"
                    topic_1 = assignments[1]
                if not dossier_path.exists():
                    raise FileNotFoundError(f"No dossier for {slug} or {slug_2}")
                dossier = json.loads(dossier_path.read_text())
                perspektiv = json.loads(perspektiv_path.read_text()) if perspektiv_path.exists() else {}
                inputs[role] = (
                    "Write a multi-perspective article on this topic.",
                    {**topic_1, "perspective_analysis": perspektiv, "research_dossier": dossier},
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
    message: str,
    context: dict,
) -> dict:
    """Run a single model call and return result record."""
    config = ROLE_CONFIG[role]
    tools = [web_search_tool] if config.get("tools") else []
    max_tokens = 65536 if role == "writer" else 16384

    agent = Agent(
        name=f"eval_{role}",
        model=model_slug,
        prompt_path=str(ROOT / config["prompt"]),
        tools=tools,
        temperature=config["temperature"],
        max_tokens=max_tokens,
        provider="openrouter",
        reasoning="none",
    )

    record: dict = {
        "eval_role": role,
        "eval_model_slug": model_slug,
        "eval_model_name": model_name,
        "eval_reasoning": "none",
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


# ── Lane ──────────────────────────────────────────────────────────────────

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

        if not first_call:
            await asyncio.sleep(10)
        first_call = False

        logger.info("[%s] %s...", model["name"], role)

        record = await run_single(role, model["slug"], model["name"], message, context)
        results.append(record)

        out_path = eval_dir / f"{role}--{safe}.json"
        out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

        status = "OK" if not record["error"] else "ERROR"
        json_ok = "JSON OK" if record["json_parseable"] else "JSON FAIL"
        logger.info(
            "[%s] %s: %d tokens, %.1fs, %s, %s",
            model["name"], role,
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
    role_order = list(ROLE_CONFIG.keys())
    all_results.sort(key=lambda r: (
        role_order.index(r["eval_role"]) if r["eval_role"] in role_order else 99,
        r["eval_model_name"],
    ))

    total_calls = len(all_results)
    lines = [
        f"Researcher + Writer Eval — {total_calls} calls, "
        f"{len(lane_durations)} models × {len(role_order)} roles",
        "=" * 80,
        f"{'Role':<21s} {'Model':<19s} {'Tokens':>8s} {'Time':>8s} {'JSON':>6s} {'Content':>9s}",
        f"{'-'*21} {'-'*19} {'-'*8} {'-'*8} {'-'*6} {'-'*9}",
    ]

    for r in all_results:
        json_ok = "OK" if r["json_parseable"] else "FAIL"
        if r.get("error"):
            json_ok = "ERR"
        lines.append(
            f"{r['eval_role']:<21s} {r['eval_model_name']:<19s} "
            f"{r['tokens_used']:>8d} {r['duration_seconds']:>7.1f}s "
            f"{json_ok:>6s} {r['content_length']:>9d}"
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
    parser = argparse.ArgumentParser(description="Researcher + Writer Model Eval")
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
        eval_dir = ROOT / "output" / "eval" / f"{today}-researcher-writer"
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

    # Save input files once
    if "researcher_plan" in inputs:
        (eval_dir / "_input-researcher-plan.json").write_text(
            json.dumps(inputs["researcher_plan"][1], indent=2, ensure_ascii=False))
    if "researcher_assemble" in inputs:
        (eval_dir / "_input-researcher-assemble.json").write_text(
            json.dumps(inputs["researcher_assemble"][1], indent=2, ensure_ascii=False))
    if "writer" in inputs:
        (eval_dir / "_input-writer.json").write_text(
            json.dumps(inputs["writer"][1], indent=2, ensure_ascii=False))

    # Run lanes concurrently
    wall_start = time.monotonic()
    lane_tasks = [run_lane(m, roles, inputs, eval_dir) for m in model_list]
    lane_results = await asyncio.gather(*lane_tasks)
    wall_time = time.monotonic() - wall_start

    # Collect results
    all_results: list[dict] = []
    lane_durations: dict[str, float] = {}
    for model_name, dur, results in lane_results:
        lane_durations[model_name] = dur
        all_results.extend(results)

    write_summary(eval_dir, all_results, lane_durations, wall_time)
    print(f"\nAll results saved to: {eval_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
