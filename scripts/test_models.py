#!/usr/bin/env python3
"""Model evaluation — sends the same pipeline input to multiple models and compares results.

Usage:
    python scripts/test_models.py --role curator --reuse 2026-04-07
    python scripts/test_models.py --role researcher_assemble --reuse 2026-04-07 --topic 1
    python scripts/test_models.py --role researcher_plan --reuse 2026-04-07 --topic 1
    python scripts/test_models.py --role writer --reuse 2026-04-07 --topic 1
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

# IMPORTANT: The first entry in each list is the Reference Quality model.
# Its eval_model_name MUST be "Reference Quality" — never "Opus", "Claude", or any brand name.
# This output serves as the benchmark against which all other models are evaluated.

MODELS = {
    "curator": [
        {"slug": "anthropic/claude-opus-4.6", "name": "Reference Quality"},
        {"slug": "minimax/minimax-m2.7", "name": "MiniMax M2.7"},
        {"slug": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2"},
        {"slug": "moonshotai/kimi-k2.5", "name": "Kimi K2.5"},
        {"slug": "xiaomi/mimo-v2-pro", "name": "MiMo-V2-Pro"},
    ],
    "researcher_assemble": [
        {"slug": "anthropic/claude-opus-4.6", "name": "Reference Quality"},
        {"slug": "z-ai/glm-5", "name": "GLM 5"},
        {"slug": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2"},
        {"slug": "moonshotai/kimi-k2.5", "name": "Kimi K2.5"},
        {"slug": "xiaomi/mimo-v2-pro", "name": "MiMo-V2-Pro"},
    ],
    "researcher_plan": [
        {"slug": "anthropic/claude-opus-4.6", "name": "Reference Quality"},
        {"slug": "z-ai/glm-5", "name": "GLM 5"},
        {"slug": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2"},
        {"slug": "moonshotai/kimi-k2.5", "name": "Kimi K2.5"},
        {"slug": "xiaomi/mimo-v2-pro", "name": "MiMo-V2-Pro"},
    ],
    "writer": [
        {"slug": "anthropic/claude-opus-4.6", "name": "Reference Quality"},
        {"slug": "z-ai/glm-5", "name": "GLM 5"},
        {"slug": "z-ai/glm-5-turbo", "name": "GLM 5 Turbo"},
        {"slug": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2"},
        {"slug": "moonshotai/kimi-k2.5", "name": "Kimi K2.5"},
        {"slug": "xiaomi/mimo-v2-pro", "name": "MiMo-V2-Pro"},
    ],
}

ROLE_CONFIG = {
    "curator": {
        "prompt": "agents/curator/AGENTS.md",
        "temperature": 0.2,
        "tools": False,
    },
    "researcher_assemble": {
        "prompt": "agents/researcher/ASSEMBLE.md",
        "temperature": 0.2,
        "tools": False,
    },
    "researcher_plan": {
        "prompt": "agents/researcher/PLAN.md",
        "temperature": 0.5,
        "tools": False,
    },
    "writer": {
        "prompt": "agents/writer/AGENTS.md",
        "temperature": 0.3,
        "tools": True,
    },
}


def load_assignments(output_dir: Path) -> list[dict]:
    """Load editor assignments from debug output."""
    path = output_dir / "03-editor-assignments.json"
    if not path.exists():
        raise FileNotFoundError(f"No editor assignments at {path}")
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else data.get("assignments", [])


def load_input_for_role(
    role: str, output_dir: Path, topic_num: int | None, reuse_date: str,
) -> tuple[str, dict]:
    """Load the saved input that would be sent to this agent role.

    Messages and context match pipeline.py exactly.
    """
    if role == "curator":
        raw_dir = output_dir.parent.parent / "raw" / output_dir.name
        feeds_path = raw_dir / "feeds.json"
        if not feeds_path.exists():
            raise FileNotFoundError(f"No feeds file at {feeds_path}")
        findings = json.loads(feeds_path.read_text())
        trimmed = [
            {"title": f.get("title", ""), "summary": f.get("summary", ""),
             "source_name": f.get("source_name", "")}
            for f in findings[:40]
        ]
        return (
            "Review these raw findings. Select the most newsworthy topics. "
            "For each selected topic provide: title, topic_slug, relevance_score, "
            "summary, source_ids.",
            {"findings": trimmed},
        )

    if not topic_num:
        raise ValueError(f"--topic required for role '{role}'")

    assignments = load_assignments(output_dir)
    if topic_num > len(assignments):
        raise ValueError(f"Topic {topic_num} not found (only {len(assignments)} assignments)")
    assignment = assignments[topic_num - 1]
    slug = assignment["topic_slug"]

    if role == "researcher_plan":
        return (
            f"Plan multilingual research queries for this topic. Today is {reuse_date}.",
            assignment,
        )

    if role == "researcher_assemble":
        search_file = output_dir / f"04-researcher-search-{slug}.json"
        if not search_file.exists():
            raise FileNotFoundError(f"No search results at {search_file}")
        search_results = json.loads(search_file.read_text())
        return (
            "Build a research dossier from these search results. "
            "Extract sources, actors, divergences, and coverage gaps.",
            {
                "assignment": assignment,
                "search_results": search_results,
            },
        )

    if role == "writer":
        dossier_file = output_dir / f"04-researcher-{slug}.json"
        perspektiv_file = output_dir / f"04b-perspektiv-{slug}.json"
        if not dossier_file.exists():
            raise FileNotFoundError(f"No dossier at {dossier_file}")
        dossier = json.loads(dossier_file.read_text())
        perspective = json.loads(perspektiv_file.read_text()) if perspektiv_file.exists() else {}
        return (
            "Write a multi-perspective article on this topic.",
            {
                **assignment,
                "perspective_analysis": perspective,
                "research_dossier": dossier,
            },
        )

    raise ValueError(f"Unknown role: {role}")


async def run_model(
    model_slug: str,
    model_name: str,
    role: str,
    message: str,
    context: dict,
) -> dict:
    """Run a single model and return results."""
    config = ROLE_CONFIG[role]
    prompt_path = str(ROOT / config["prompt"])

    tools = [web_search_tool] if config.get("tools") else []

    agent = Agent(
        name=f"eval_{role}",
        model=model_slug,
        prompt_path=prompt_path,
        tools=tools,
        temperature=config["temperature"],
        provider="openrouter",
    )

    result_record = {
        "eval_role": role,
        "eval_model_slug": model_slug,
        "eval_model_name": model_name,
        "duration_seconds": 0,
        "tokens_used": 0,
        "json_parseable": False,
        "content_length": 0,
        "error": None,
        "raw_output": "",
    }

    try:
        start = time.monotonic()
        result = await agent.run(message, context=context)
        duration = time.monotonic() - start

        result_record["duration_seconds"] = round(duration, 1)
        result_record["tokens_used"] = result.tokens_used
        result_record["content_length"] = len(result.content)
        result_record["raw_output"] = result.content

        parsed = Agent._parse_json(result.content)
        result_record["json_parseable"] = parsed is not None

    except Exception as e:
        result_record["error"] = str(e)

    return result_record


async def main():
    parser = argparse.ArgumentParser(description="Model evaluation for Independent Wire")
    parser.add_argument(
        "--role", required=True,
        choices=list(MODELS.keys()),
        help="Agent role to evaluate",
    )
    parser.add_argument(
        "--reuse", required=True,
        help="Date to load debug output from (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--topic", type=int, default=None,
        help="Topic number (1-based, required for per-topic roles)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("test_models")

    output_dir = ROOT / "output" / args.reuse
    if not output_dir.exists():
        logger.error("No output directory at %s", output_dir)
        sys.exit(1)

    # Load input for this role
    logger.info("Loading input for role '%s' from %s", args.role, args.reuse)
    message, context = load_input_for_role(args.role, output_dir, args.topic, args.reuse)

    # Save input record
    eval_dir = ROOT / "output" / "eval" / args.reuse
    eval_dir.mkdir(parents=True, exist_ok=True)

    config = ROLE_CONFIG[args.role]
    prompt_path = ROOT / config["prompt"]
    system_prompt_text = prompt_path.read_text(encoding="utf-8")

    # Build full user message same way Agent does
    full_user_message = message
    if context:
        context_str = json.dumps(context, indent=2, ensure_ascii=False)
        full_user_message = f"{message}\n\n---\n\nContext:\n```json\n{context_str}\n```"

    input_record = {
        "eval_role": args.role,
        "system_prompt": system_prompt_text,
        "user_message": full_user_message,
        "message": message,
        "context_keys": list(context.keys()),
        "date": args.reuse,
        "topic": args.topic,
    }
    input_path = eval_dir / f"{args.role}--_input.json"
    input_path.write_text(json.dumps(input_record, indent=2, ensure_ascii=False))
    logger.info("Saved input to %s", input_path.name)

    models = MODELS[args.role]
    logger.info("Evaluating %d models for role '%s'", len(models), args.role)

    # Run models sequentially with rate limiting
    results = []
    for i, model_info in enumerate(models):
        if i > 0:
            logger.info("Waiting 15s between models...")
            await asyncio.sleep(15)

        logger.info("Running %s (%s)...", model_info["name"], model_info["slug"])
        result = await run_model(
            model_info["slug"],
            model_info["name"],
            args.role,
            message,
            context,
        )
        results.append(result)

        # Save individual result
        safe_name = model_info["name"].lower().replace(" ", "-")
        out_path = eval_dir / f"{args.role}--{safe_name}.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

        status = "OK" if not result["error"] else f"ERROR: {result['error'][:80]}"
        json_ok = "JSON OK" if result["json_parseable"] else "JSON FAIL"
        logger.info(
            "  %s: %d tokens, %.1fs, %s, %s",
            model_info["name"],
            result["tokens_used"],
            result["duration_seconds"],
            json_ok,
            status,
        )

    # Print summary
    print(f"\n{'='*70}")
    print(f"Model Evaluation: {args.role}")
    print(f"{'='*70}")
    print(f"{'Model':<25s} {'Tokens':>8s} {'Time':>8s} {'JSON':>8s} {'Length':>8s} {'Status':>10s}")
    print(f"{'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

    for r in results:
        status = "OK" if not r["error"] else "ERROR"
        json_ok = "OK" if r["json_parseable"] else "FAIL"
        print(
            f"{r['eval_model_name']:<25s} {r['tokens_used']:>8d} "
            f"{r['duration_seconds']:>7.1f}s {json_ok:>8s} "
            f"{r['content_length']:>8d} {status:>10s}"
        )

    print(f"\nResults saved to: {eval_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
