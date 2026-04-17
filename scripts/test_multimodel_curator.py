#!/usr/bin/env python3
"""Multi-model curator test: clustering (Test A) + full curator (Test B) across 7 models.

Usage:
    source .env && python scripts/test_multimodel_curator.py
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent

FEEDS_PATH = ROOT / "raw" / "2026-04-07" / "feeds.json"
OUTPUT_DIR = ROOT / "output" / "eval" / "2026-04-08-multimodel"
CURATOR_PROMPT = ROOT / "agents" / "curator" / "AGENTS.md"

MODELS = [
    {"slug": "anthropic/claude-opus-4.6", "name": "Reference Quality"},
    {"slug": "anthropic/claude-sonnet-4.6", "name": "Sonnet 4.6"},
    {"slug": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash"},
    {"slug": "google/gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro"},
    {"slug": "openai/gpt-5.4", "name": "GPT-5.4"},
    {"slug": "openai/gpt-5.4-mini", "name": "GPT-5.4 Mini"},
    {"slug": "qwen/qwen3.6-plus", "name": "Qwen 3.6 Plus"},
]

CLUSTERING_MESSAGE = """Cluster these news findings by topic.
Group findings that cover the same story or event.
Do NOT over-cluster: same actor but different events = separate clusters.
Every finding must appear in exactly one cluster.

Output: JSON array, each element: {"cluster_title": "...", "finding_ids": ["finding-0", ...]}
No markdown, no commentary, only the JSON array."""

CURATOR_MESSAGE = (
    "Review these findings. Cluster related findings into topics. "
    "Score each topic's newsworthiness on a 1-10 scale. "
    "For each topic provide: title, relevance_score, summary, source_ids."
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_multimodel")


def load_findings() -> tuple[list[dict], list[dict]]:
    """Load feeds, URL-dedup, return (title_only, compressed_with_summary)."""
    raw = json.loads(FEEDS_PATH.read_text(encoding="utf-8"))
    seen_urls: set[str] = set()
    unique = []
    for f in raw:
        url = f.get("source_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique.append(f)

    title_only = []
    compressed = []
    for i, f in enumerate(unique):
        title = f.get("title", "").strip()
        if not title:
            continue
        fid = f"finding-{i}"
        source = f.get("source_name", "")

        title_only.append({"id": fid, "title": title, "source_name": source})

        entry: dict = {"id": fid, "title": title, "source_name": source}
        summary = f.get("summary", "").strip()
        if summary and summary.lower() != title.lower() and not title.lower().startswith(summary.lower()[:50]):
            entry["summary"] = summary
        compressed.append(entry)

    logger.info("Loaded %d raw -> %d unique -> %d findings", len(raw), len(unique), len(title_only))
    return title_only, compressed


def make_filename(test: str, model_name: str) -> str:
    safe = model_name.lower().replace(" ", "-")
    return f"{test}--{safe}.json"


async def run_single(
    model_slug: str,
    model_name: str,
    prompt_path: str,
    message: str,
    context: dict,
    test_label: str,
) -> dict:
    """Run a single model call and return result record."""
    agent = Agent(
        name=f"eval_{test_label}",
        model=model_slug,
        prompt_path=prompt_path,
        tools=[],
        temperature=0.2,
        max_tokens=16384,
        provider="openrouter",
    )

    record: dict = {
        "eval_role": test_label,
        "eval_model_slug": model_slug,
        "eval_model_name": model_name,
        "eval_reasoning": "off",
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


def print_summary(test_name: str, results: list[dict]):
    print(f"\n{'='*80}")
    print(f"  {test_name}")
    print(f"{'='*80}")
    print(f"{'Model':<22s} {'Tokens':>8s} {'Time':>8s} {'JSON':>6s} {'Content':>9s} {'Status':>8s}")
    print(f"{'-'*22} {'-'*8} {'-'*8} {'-'*6} {'-'*9} {'-'*8}")
    for r in results:
        status = "OK" if not r["error"] else "ERROR"
        json_ok = "OK" if r["json_parseable"] else "FAIL"
        print(
            f"{r['eval_model_name']:<22s} {r['tokens_used']:>8d} "
            f"{r['duration_seconds']:>7.1f}s {json_ok:>6s} "
            f"{r['content_length']:>9d} {status:>8s}"
        )


async def main():
    if not FEEDS_PATH.exists():
        logger.error("Feeds not found: %s", FEEDS_PATH)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Prepare minimal system prompt for clustering
    clustering_prompt_path = ROOT / "scripts" / "_clustering_prompt.tmp"
    clustering_prompt_path.write_text(
        "You are a news clustering assistant. Follow the user's instructions exactly."
    )

    # Load data
    title_only, compressed = load_findings()

    # ── Test A: Clustering ──────────────────────────────────────────────
    logger.info("=== TEST A: Clustering (%d models) ===", len(MODELS))
    results_a = []
    for i, m in enumerate(MODELS):
        if i > 0:
            logger.info("Waiting 15s...")
            await asyncio.sleep(15)

        logger.info("Test A: %s (%s)...", m["name"], m["slug"])
        result = await run_single(
            m["slug"], m["name"],
            str(clustering_prompt_path),
            CLUSTERING_MESSAGE,
            {"findings": title_only},
            "clustering",
        )
        results_a.append(result)

        out_path = OUTPUT_DIR / make_filename("clustering", m["name"])
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

        json_ok = "JSON OK" if result["json_parseable"] else "JSON FAIL"
        logger.info(
            "  %s: %d tokens, %.1fs, %s, %d chars",
            m["name"], result["tokens_used"], result["duration_seconds"],
            json_ok, result["content_length"],
        )

    print_summary("Test A: LLM Clustering (title-only, ~88K tokens)", results_a)

    # ── Test B: Full Curator ────────────────────────────────────────────
    logger.info("Waiting 30s before Test B...")
    await asyncio.sleep(30)

    logger.info("=== TEST B: Full Curator (%d models) ===", len(MODELS))
    results_b = []
    for i, m in enumerate(MODELS):
        if i > 0:
            logger.info("Waiting 15s...")
            await asyncio.sleep(15)

        logger.info("Test B: %s (%s)...", m["name"], m["slug"])
        result = await run_single(
            m["slug"], m["name"],
            str(CURATOR_PROMPT),
            CURATOR_MESSAGE,
            {"findings": compressed},
            "curator",
        )
        results_b.append(result)

        out_path = OUTPUT_DIR / make_filename("curator", m["name"])
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

        json_ok = "JSON OK" if result["json_parseable"] else "JSON FAIL"
        logger.info(
            "  %s: %d tokens, %.1fs, %s, %d chars",
            m["name"], result["tokens_used"], result["duration_seconds"],
            json_ok, result["content_length"],
        )

    print_summary("Test B: Full Curator (with summaries, ~158K tokens)", results_b)

    # Cleanup temp file
    clustering_prompt_path.unlink(missing_ok=True)

    print(f"\nAll results saved to: {OUTPUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
