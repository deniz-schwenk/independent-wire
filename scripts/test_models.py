#!/usr/bin/env python3
"""Model evaluation — sends the same pipeline input to multiple models and compares results.

Usage:
    python scripts/test_models.py --role curator --reuse 2026-04-07
    python scripts/test_models.py --role researcher_assemble --reuse 2026-04-07 --topic 1
    python scripts/test_models.py --role writer --reuse 2026-04-07 --topic 1
    python scripts/test_models.py --role perspektiv_qa_bias --reuse 2026-04-07 --topic 1
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent

# Models to evaluate per role
MODELS = {
    "curator": [
        {"slug": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2"},
        {"slug": "stepfun/step-3.5-flash", "name": "Step 3.5 Flash"},
        {"slug": "minimax/minimax-m2.7", "name": "MiniMax M2.7"},
        {"slug": "moonshotai/kimi-k2.5", "name": "Kimi K2.5"},
        {"slug": "xiaomi/mimo-v2-pro", "name": "MiMo-V2-Pro"},
    ],
    "researcher_assemble": [
        {"slug": "z-ai/glm-5-turbo", "name": "GLM 5 Turbo"},
        {"slug": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2"},
        {"slug": "moonshotai/kimi-k2.5", "name": "Kimi K2.5"},
        {"slug": "xiaomi/mimo-v2-pro", "name": "MiMo-V2-Pro"},
    ],
    "writer": [
        {"slug": "z-ai/glm-5-turbo", "name": "GLM 5 Turbo"},
        {"slug": "moonshotai/kimi-k2.5", "name": "Kimi K2.5"},
        {"slug": "xiaomi/mimo-v2-pro", "name": "MiMo-V2-Pro"},
    ],
    "perspektiv_qa_bias": [
        {"slug": "z-ai/glm-5", "name": "GLM 5"},
        {"slug": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2"},
        {"slug": "z-ai/glm-5.1", "name": "GLM 5.1"},
        {"slug": "moonshotai/kimi-k2.5", "name": "Kimi K2.5"},
        {"slug": "xiaomi/mimo-v2-pro", "name": "MiMo-V2-Pro"},
    ],
}

# Role → (prompt_path, temperature, tools)
ROLE_CONFIG = {
    "curator": {
        "prompt": "agents/curator/AGENTS.md",
        "temperature": 0.2,
    },
    "researcher_assemble": {
        "prompt": "agents/researcher/ASSEMBLE.md",
        "temperature": 0.2,
    },
    "writer": {
        "prompt": "agents/writer/AGENTS.md",
        "temperature": 0.3,
    },
    "perspektiv_qa_bias": {
        "prompt": "agents/perspektiv/AGENTS.md",
        "temperature": 0.1,
    },
}


def find_debug_files(output_dir: Path) -> dict[str, Path]:
    """Index debug output files by prefix pattern."""
    files = {}
    for f in sorted(output_dir.glob("*.json")):
        files[f.name] = f
    return files


def load_topic_slug(output_dir: Path, topic_num: int) -> str | None:
    """Find the slug for topic N from editor assignments."""
    for f in sorted(output_dir.glob("02-editor-*.json")):
        data = json.loads(f.read_text())
        assignments = data if isinstance(data, list) else data.get("assignments", [])
        if topic_num <= len(assignments):
            title = assignments[topic_num - 1].get("title", "")
            # Derive slug from title (same logic as pipeline)
            import re
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
            return slug
    return None


def load_input_for_role(role: str, output_dir: Path, topic_num: int | None) -> tuple[str, dict]:
    """Load the saved input that would be sent to this agent role.

    Returns (message, context) matching what pipeline.py sends.
    """
    if role == "curator":
        # Curator gets RSS findings
        raw_dir = output_dir.parent.parent / "raw" / output_dir.name
        feeds_path = raw_dir / "feeds.json"
        if not feeds_path.exists():
            raise FileNotFoundError(f"No feeds file at {feeds_path}")
        findings = json.loads(feeds_path.read_text())
        return (
            f"Evaluate these {len(findings)} findings and select the top 3 most "
            "significant international news topics for today's report.",
            {"findings": findings},
        )

    if not topic_num:
        raise ValueError(f"--topic required for role '{role}'")

    slug = load_topic_slug(output_dir, topic_num)
    if not slug:
        raise FileNotFoundError(f"Could not find slug for topic {topic_num}")

    if role == "researcher_assemble":
        # Load search results that the assembler would receive
        search_file = next(output_dir.glob(f"03b-search-results-{slug}*.json"), None)
        plan_file = next(output_dir.glob(f"03a-research-plan-{slug}*.json"), None)
        if not search_file:
            raise FileNotFoundError(f"No search results for {slug}")
        search_results = json.loads(search_file.read_text())
        plan = json.loads(plan_file.read_text()) if plan_file else {}
        return (
            "Assemble a comprehensive research dossier from these multilingual search results.",
            {"search_results": search_results, "research_plan": plan},
        )

    if role == "writer":
        dossier_file = next(output_dir.glob(f"04-researcher-{slug}*.json"), None)
        perspektiv_file = next(output_dir.glob(f"04b-perspektiv-{slug}*.json"), None)
        editor_file = next(output_dir.glob("02-editor-*.json"), None)
        if not dossier_file:
            raise FileNotFoundError(f"No dossier for {slug}")
        dossier = json.loads(dossier_file.read_text())
        perspective = json.loads(perspektiv_file.read_text()) if perspektiv_file else {}
        assignment = {}
        if editor_file:
            ed = json.loads(editor_file.read_text())
            assignments = ed if isinstance(ed, list) else ed.get("assignments", [])
            if topic_num <= len(assignments):
                assignment = assignments[topic_num - 1]
        return (
            "Write an article based on the research dossier and perspective analysis.",
            {
                "assignment": assignment,
                "research_dossier": dossier,
                "perspective_analysis": perspective,
            },
        )

    if role == "perspektiv_qa_bias":
        dossier_file = next(output_dir.glob(f"04-researcher-{slug}*.json"), None)
        if not dossier_file:
            raise FileNotFoundError(f"No dossier for {slug}")
        dossier = json.loads(dossier_file.read_text())
        return (
            "Analyze the spectrum of perspectives represented in this research dossier.",
            {"research_dossier": dossier},
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

    agent = Agent(
        name=f"eval_{role}",
        model=model_slug,
        prompt_path=prompt_path,
        tools=[],
        temperature=config["temperature"],
        provider="openrouter",
    )

    result_record = {
        "model_slug": model_slug,
        "model_name": model_name,
        "role": role,
        "tokens_used": 0,
        "duration_seconds": 0,
        "json_parseable": False,
        "content_length": 0,
        "error": None,
    }

    try:
        start = time.monotonic()
        result = await agent.run(message, context=context)
        duration = time.monotonic() - start

        result_record["tokens_used"] = result.tokens_used
        result_record["duration_seconds"] = round(duration, 1)
        result_record["content_length"] = len(result.content)
        result_record["model_reported"] = result.model

        # Check if output is valid JSON
        parsed = Agent._parse_json(result.content)
        result_record["json_parseable"] = parsed is not None
        result_record["content_preview"] = result.content[:500]

    except Exception as e:
        result_record["error"] = str(e)
        result_record["duration_seconds"] = 0

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
    message, context = load_input_for_role(args.role, output_dir, args.topic)

    models = MODELS[args.role]
    logger.info("Evaluating %d models for role '%s'", len(models), args.role)

    # Run models sequentially
    results = []
    for model_info in models:
        logger.info("Running %s (%s)...", model_info["name"], model_info["slug"])
        result = await run_model(
            model_info["slug"],
            model_info["name"],
            args.role,
            message,
            context,
        )
        results.append(result)

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

    # Save results
    eval_dir = ROOT / "output" / "eval" / args.reuse
    eval_dir.mkdir(parents=True, exist_ok=True)

    for result in results:
        safe_name = result["model_name"].lower().replace(" ", "-")
        out_path = eval_dir / f"{args.role}-{safe_name}.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

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
            f"{r['model_name']:<25s} {r['tokens_used']:>8d} "
            f"{r['duration_seconds']:>7.1f}s {json_ok:>8s} "
            f"{r['content_length']:>8d} {status:>10s}"
        )

    print(f"\nResults saved to: {eval_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
