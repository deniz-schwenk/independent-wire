#!/usr/bin/env python3
"""Model evaluation — sends the same pipeline input to multiple models and compares results.

Usage:
    # Eval 1: model comparison (no reasoning)
    python scripts/test_models.py --role curator --reuse 2026-04-07

    # Eval 2: reasoning matrix
    python scripts/test_models.py --role researcher_plan --reuse 2026-04-07 --topic 1 \
        --reasoning medium --model "deepseek/deepseek-v3.2" \
        --output-dir output/eval/2026-04-08-reasoning

    # Eval 2: full reasoning matrix for a role
    python scripts/test_models.py --role researcher_plan --reuse 2026-04-07 --topic 1 \
        --reasoning-matrix --output-dir output/eval/2026-04-08-reasoning
"""

import argparse
import asyncio
import json
import logging
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.tools import web_search_tool

# IMPORTANT: The first entry in each list is the Reference Quality model.
# Its eval_model_name MUST be "Reference Quality" — never "Opus", "Claude", or any brand name.

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

# Reasoning matrix: role → list of (model_slug, model_name, reasoning_level)
# Only NEW calls that don't exist as baselines from Eval 1
REASONING_MATRIX = {
    "curator": [
        ("anthropic/claude-opus-4.6", "Reference Quality", "on"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "low"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "medium"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "high"),
        ("z-ai/glm-5-turbo", "GLM 5 Turbo", "off"),
        ("z-ai/glm-5-turbo", "GLM 5 Turbo", "medium"),
    ],
    "researcher_plan": [
        ("anthropic/claude-opus-4.6", "Reference Quality", "on"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "low"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "medium"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "high"),
        ("z-ai/glm-5", "GLM 5", "medium"),
    ],
    "researcher_assemble": [
        ("anthropic/claude-opus-4.6", "Reference Quality", "on"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "low"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "medium"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "high"),
        ("z-ai/glm-5", "GLM 5", "medium"),
    ],
    "writer": [
        ("anthropic/claude-opus-4.6", "Reference Quality", "on"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "low"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "medium"),
        ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "high"),
        ("z-ai/glm-5-turbo", "GLM 5 Turbo", "medium"),
    ],
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
        # Compress same way as pipeline._prepare_curator_input()
        seen_urls: set[str] = set()
        unique = []
        for f in findings:
            url = f.get("source_url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            unique.append(f)
        compressed = []
        for i, f in enumerate(unique):
            title = f.get("title", "").strip()
            if not title:
                continue
            entry: dict = {"id": f"finding-{i}", "title": title, "source_name": f.get("source_name", "")}
            summary = f.get("summary", "").strip()
            if summary and summary.lower() != title.lower() and not title.lower().startswith(summary.lower()[:50]):
                entry["summary"] = summary
            compressed.append(entry)
        return (
            "Review these findings. Cluster related findings into topics. "
            "Score each topic's newsworthiness on a 1-10 scale. "
            "For each topic provide: title, relevance_score, summary, source_ids.",
            {"findings": compressed},
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


def resolve_reasoning_param(
    model_slug: str, reasoning_level: str,
) -> str | bool | None:
    """Map reasoning level to Agent constructor parameter.

    Opus 4.6: effort levels are ignored — only on/off (True/None).
    Other models: pass effort string directly.
    """
    if reasoning_level == "off":
        return None
    if model_slug.startswith("anthropic/claude"):
        # Opus: effort levels ignored, use adaptive thinking
        return True
    return reasoning_level  # "none", "minimal", "low", "medium", "high"


async def run_model(
    model_slug: str,
    model_name: str,
    role: str,
    message: str,
    context: dict,
    reasoning: str | bool | None = None,
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
        reasoning=reasoning,
    )

    result_record: dict = {
        "eval_role": role,
        "eval_model_slug": model_slug,
        "eval_model_name": model_name,
        "eval_reasoning": "off" if reasoning is None else (
            "on" if reasoning is True else reasoning
        ),
        "duration_seconds": 0,
        "tokens_used": 0,
        "reasoning_tokens": 0,
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


def make_output_filename(role: str, model_name: str, reasoning_level: str) -> str:
    """Build output filename: {role}--{model-safe-name}[--r-{level}].json"""
    safe_name = model_name.lower().replace(" ", "-")
    if reasoning_level and reasoning_level != "off":
        return f"{role}--{safe_name}--r-{reasoning_level}.json"
    return f"{role}--{safe_name}.json"


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
    parser.add_argument(
        "--reasoning", default=None,
        choices=["off", "none", "minimal", "low", "medium", "high", "on"],
        help="Reasoning level (single model mode)",
    )
    parser.add_argument(
        "--model", default=None,
        help="Run only this model slug (e.g. 'deepseek/deepseek-v3.2')",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Override output directory (default: output/eval/{reuse})",
    )
    parser.add_argument(
        "--reasoning-matrix", action="store_true",
        help="Run full reasoning matrix for this role",
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

    # Determine eval output directory
    if args.output_dir:
        eval_dir = ROOT / args.output_dir
    else:
        eval_dir = ROOT / "output" / "eval" / args.reuse
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Load input for this role
    logger.info("Loading input for role '%s' from %s", args.role, args.reuse)
    message, context = load_input_for_role(args.role, output_dir, args.topic, args.reuse)

    # Save or copy _input.json
    input_path = eval_dir / f"{args.role}--_input.json"
    eval1_input = ROOT / "output" / "eval" / args.reuse / f"{args.role}--_input.json"
    if eval1_input.exists() and str(eval_dir) != str(eval1_input.parent):
        # Copy from Eval 1
        shutil.copy2(eval1_input, input_path)
        logger.info("Copied input from Eval 1: %s", input_path.name)
    elif not input_path.exists():
        config = ROLE_CONFIG[args.role]
        prompt_path = ROOT / config["prompt"]
        system_prompt_text = prompt_path.read_text(encoding="utf-8")
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
        input_path.write_text(json.dumps(input_record, indent=2, ensure_ascii=False))
        logger.info("Saved input to %s", input_path.name)

    # Build test list: either reasoning matrix, single model+reasoning, or full model list
    test_list: list[tuple[str, str, str]] = []  # (slug, name, reasoning_level)

    if args.reasoning_matrix:
        matrix = REASONING_MATRIX.get(args.role, [])
        if not matrix:
            logger.error("No reasoning matrix defined for role '%s'", args.role)
            sys.exit(1)
        test_list = list(matrix)
        logger.info("Reasoning matrix: %d calls for role '%s'", len(test_list), args.role)

    elif args.reasoning and args.model:
        # Single model + reasoning combo
        model_info = next(
            (m for m in MODELS[args.role] if m["slug"] == args.model), None
        )
        name = model_info["name"] if model_info else args.model.split("/")[-1]
        test_list = [(args.model, name, args.reasoning)]

    elif args.reasoning:
        # Apply reasoning to all models in the role
        for m in MODELS[args.role]:
            test_list.append((m["slug"], m["name"], args.reasoning))

    else:
        # Default: all models, no reasoning (Eval 1 mode)
        for m in MODELS[args.role]:
            test_list.append((m["slug"], m["name"], "off"))

    logger.info("Running %d model calls for role '%s'", len(test_list), args.role)

    # Run sequentially with rate limiting
    results = []
    for i, (slug, name, r_level) in enumerate(test_list):
        if i > 0:
            logger.info("Waiting 15s between models...")
            await asyncio.sleep(15)

        reasoning_param = resolve_reasoning_param(slug, r_level)
        r_label = f" (reasoning={r_level})" if r_level != "off" else ""
        logger.info("Running %s (%s)%s...", name, slug, r_label)

        result = await run_model(slug, name, args.role, message, context, reasoning_param)
        results.append(result)

        # Save individual result
        out_path = eval_dir / make_output_filename(args.role, name, r_level)
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

        status = "OK" if not result["error"] else f"ERROR: {result['error'][:80]}"
        json_ok = "JSON OK" if result["json_parseable"] else "JSON FAIL"
        logger.info(
            "  %s r=%s: %d tokens, %.1fs, %s, %s",
            name, r_level,
            result["tokens_used"],
            result["duration_seconds"],
            json_ok, status,
        )

    # Print summary
    print(f"\n{'='*80}")
    print(f"Model Evaluation: {args.role}")
    print(f"{'='*80}")
    print(f"{'Model':<22s} {'Reason':>6s} {'Tokens':>8s} {'Time':>8s} {'JSON':>6s} {'Length':>8s} {'Status':>8s}")
    print(f"{'-'*22} {'-'*6} {'-'*8} {'-'*8} {'-'*6} {'-'*8} {'-'*8}")

    for r in results:
        status = "OK" if not r["error"] else "ERROR"
        json_ok = "OK" if r["json_parseable"] else "FAIL"
        reasoning_display = r.get("eval_reasoning", "off")
        print(
            f"{r['eval_model_name']:<22s} {reasoning_display:>6s} {r['tokens_used']:>8d} "
            f"{r['duration_seconds']:>7.1f}s {json_ok:>6s} "
            f"{r['content_length']:>8d} {status:>8s}"
        )

    print(f"\nResults saved to: {eval_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
