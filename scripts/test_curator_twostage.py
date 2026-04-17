#!/usr/bin/env python3
"""Curator Two-Stage Eval — clustering + scoring across 9 models.

Modes:
  cluster   — Pass 1 only (LLM clustering)
  score     — Pass 2 only (LLM scoring, requires --cluster-source)
  twostage  — Pass 1 + Python glue + Pass 2 (same model for both)
  hybrid    — Python Jaccard clustering + LLM scoring

Usage:
    source .env && python scripts/test_curator_twostage.py --mode twostage --reuse 2026-04-07
    source .env && python scripts/test_curator_twostage.py --mode cluster --reuse 2026-04-07 --model "z-ai/glm-5"
    source .env && python scripts/test_curator_twostage.py --mode hybrid --reuse 2026-04-07
    source .env && python scripts/test_curator_twostage.py --mode score --reuse 2026-04-07 \
        --cluster-source output/eval/2026-04-09-curator-twostage/cluster--glm-5.json
"""

import argparse
import asyncio
import json
import logging
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent

MODELS = [
    {"slug": "qwen/qwen3.6-plus", "name": "Qwen 3.6 Plus"},
    {"slug": "z-ai/glm-5", "name": "GLM 5"},
    {"slug": "z-ai/glm-5.1", "name": "GLM 5.1"},
    {"slug": "z-ai/glm-5-turbo", "name": "GLM 5 Turbo"},
    {"slug": "anthropic/claude-opus-4.6", "name": "Opus 4.6"},
    {"slug": "anthropic/claude-sonnet-4.6", "name": "Sonnet 4.6"},
    {"slug": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash"},
    {"slug": "google/gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro"},
    {"slug": "openai/gpt-5.4", "name": "GPT 5.4"},
    {"slug": "openai/gpt-5.4-mini", "name": "GPT 5.4 Mini"},
]

CLUSTER_PROMPT = ROOT / "agents" / "curator" / "CLUSTER.md"
SCORE_PROMPT = ROOT / "agents" / "curator" / "SCORE.md"

CLUSTER_MESSAGE = "Cluster these news findings by topic. Every finding must appear in exactly one cluster."
SCORE_MESSAGE = "Evaluate these topic clusters. Score newsworthiness 1-10. Write summaries from source data only."

# --- Jaccard clustering for hybrid mode ---

STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "be", "been", "with", "by", "from", "as",
    "it", "its", "that", "this", "has", "have", "had", "will", "would",
    "could", "should", "may", "can", "do", "does", "did", "not", "but",
    "if", "so", "than", "more", "also", "over", "after", "before", "says",
    "said", "new", "us", "he", "she", "they", "we", "his", "her", "their",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_twostage")


# ── Data Loading ──────────────────────────────────────────────────────────

def load_findings(feeds_path: Path) -> tuple[list[dict], list[dict]]:
    """Load feeds, URL-dedup, return (title_only, full_compressed)."""
    raw = json.loads(feeds_path.read_text(encoding="utf-8"))
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
    full_compressed = []
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
        full_compressed.append(entry)

    logger.info("Loaded %d raw -> %d unique -> %d findings", len(raw), len(unique), len(title_only))
    return title_only, full_compressed


# ── Metrics ───────────────────────────────────────────────────────────────

def compute_cluster_metrics(clusters: list[dict], input_ids: set[str]) -> dict:
    """Compute clustering quality metrics."""
    all_assigned = []
    for c in clusters:
        all_assigned.extend(c.get("finding_ids", []))

    assigned_set = set(all_assigned)
    valid_assigned = assigned_set & input_ids
    invalid_ids = len(assigned_set - input_ids)
    missing = input_ids - assigned_set
    duplicates = len(all_assigned) - len(assigned_set)

    sizes = [len(c.get("finding_ids", [])) for c in clusters]

    return {
        "cluster_count": len(clusters),
        "coverage_pct": round(len(valid_assigned) / len(input_ids) * 100, 1) if input_ids else 0,
        "coverage_count": len(valid_assigned),
        "missing_count": len(missing),
        "duplicate_count": duplicates,
        "largest_cluster": max(sizes) if sizes else 0,
        "singleton_count": sum(1 for s in sizes if s == 1),
        "invalid_ids": invalid_ids,
    }


def compute_score_metrics(topics: list[dict]) -> dict:
    """Compute scoring quality metrics."""
    scores = [t.get("relevance_score", 0) for t in topics if isinstance(t.get("relevance_score"), (int, float))]
    summaries = [t.get("summary", "") for t in topics]
    has_slug = all("topic_slug" in t for t in topics)

    if not scores:
        return {
            "topic_count": len(topics),
            "score_min": 0, "score_max": 0, "score_avg": 0, "score_median": 0,
            "full_range_used": False,
            "avg_summary_length": 0,
            "has_topic_slug": has_slug,
        }

    return {
        "topic_count": len(topics),
        "score_min": min(scores),
        "score_max": max(scores),
        "score_avg": round(statistics.mean(scores), 1),
        "score_median": round(statistics.median(scores), 1),
        "full_range_used": (max(scores) - min(scores)) >= 4,
        "avg_summary_length": round(statistics.mean(len(s) for s in summaries)),
        "has_topic_slug": has_slug,
    }


# ── Python Glue: Build Cluster Summaries ─────────────────────────────────

def build_cluster_summaries(clusters: list[dict], full_compressed: list[dict]) -> list[dict]:
    """Build enriched cluster data for the Scoring pass."""
    findex = {f["id"]: f for f in full_compressed}

    enriched = []
    for cluster in clusters:
        fids = cluster.get("finding_ids", [])
        matched = [findex[fid] for fid in fids if fid in findex]

        # Pick 3-5 findings with the longest summaries (most informative)
        with_summary = [f for f in matched if f.get("summary")]
        with_summary.sort(key=lambda f: len(f.get("summary", "")), reverse=True)
        sample = with_summary[:5]

        # If fewer than 3 have summaries, pad with title-only findings
        if len(sample) < 3:
            no_summary = [f for f in matched if not f.get("summary")]
            for f in no_summary[:3 - len(sample)]:
                sample.append(f)

        sample_findings = [
            {"title": f["title"], "summary": f.get("summary", f["title"])}
            for f in sample
        ]

        sources = sorted(set(f.get("source_name", "") for f in matched))

        enriched.append({
            "cluster_title": cluster["cluster_title"],
            "source_count": len(fids),
            "sources": sources,
            "sample_findings": sample_findings,
        })

    return enriched


# ── Jaccard Clustering (Hybrid Mode) ─────────────────────────────────────

def tokenize(title: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", title.lower()))
    return words - STOPWORDS


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def python_jaccard_clustering(title_only: list[dict]) -> list[dict]:
    """Cluster findings using Jaccard similarity on title word sets."""
    try:
        from sklearn.cluster import AgglomerativeClustering
        import numpy as np
    except ImportError:
        logger.error("scikit-learn is required for hybrid mode. Install with: pip install scikit-learn")
        sys.exit(1)

    logger.info("Python Jaccard clustering on %d findings...", len(title_only))
    start = time.monotonic()

    tokens = [tokenize(f["title"]) for f in title_only]
    n = len(tokens)

    # Build distance matrix (1 - jaccard)
    dist = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = 1.0 - jaccard(tokens[i], tokens[j])
            dist[i][j] = d
            dist[j][i] = d

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=0.65,
        metric="precomputed",
        linkage="average",
    )
    labels = clustering.fit_predict(dist)

    # Group findings by cluster
    clusters_map: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        clusters_map.setdefault(label, []).append(idx)

    clusters = []
    for label in sorted(clusters_map.keys()):
        indices = clusters_map[label]
        finding_ids = [title_only[i]["id"] for i in indices]
        # Use first title as cluster title
        cluster_title = title_only[indices[0]]["title"][:80]
        clusters.append({
            "cluster_title": cluster_title,
            "finding_ids": finding_ids,
        })

    clusters.sort(key=lambda c: len(c["finding_ids"]), reverse=True)
    duration = time.monotonic() - start
    logger.info("Python clustering done: %d clusters in %.1fs", len(clusters), duration)
    return clusters


# ── LLM Calls ─────────────────────────────────────────────────────────────

def make_safe_name(model_name: str) -> str:
    return model_name.lower().replace(" ", "-")


def _provider_extra(model_slug: str) -> dict:
    """Return extra_body_override for provider routing."""
    if model_slug.startswith("z-ai/"):
        return {"provider": {"order": ["DeepInfra"], "allow_fallbacks": True}}
    return {}


async def run_cluster_pass(model_slug: str, model_name: str, title_only: list[dict]) -> dict:
    """Pass 1: LLM clustering."""
    agent = Agent(
        name="curator_cluster",
        model=model_slug,
        prompt_path=str(CLUSTER_PROMPT),
        tools=[],
        temperature=0.2,
        max_tokens=16384,
        provider="openrouter",
        reasoning=None,
        extra_body_override=_provider_extra(model_slug),
    )

    record: dict = {
        "eval_mode": "cluster",
        "eval_model_slug": model_slug,
        "eval_model_name": model_name,
        "eval_pass": "cluster",
        "duration_seconds": 0,
        "tokens_used": 0,
        "json_parseable": False,
        "error": None,
        "metrics": {},
        "raw_output": "",
        "parsed_output": None,
    }

    try:
        start = time.monotonic()
        result = await agent.run(CLUSTER_MESSAGE, context={"findings": title_only})
        duration = time.monotonic() - start

        record["duration_seconds"] = round(duration, 1)
        record["tokens_used"] = result.tokens_used
        record["raw_output"] = result.content

        parsed = Agent._parse_json(result.content)
        if parsed and isinstance(parsed, list):
            record["json_parseable"] = True
            record["parsed_output"] = parsed
            input_ids = {f["id"] for f in title_only}
            record["metrics"] = compute_cluster_metrics(parsed, input_ids)
        else:
            record["error"] = "JSON parse failed or not a list"

    except Exception as e:
        record["error"] = str(e)
        record["duration_seconds"] = round(time.monotonic() - start, 1)

    return record


async def run_score_pass(model_slug: str, model_name: str, enriched_clusters: list[dict]) -> dict:
    """Pass 2: LLM scoring."""
    agent = Agent(
        name="curator_score",
        model=model_slug,
        prompt_path=str(SCORE_PROMPT),
        tools=[],
        temperature=0.3,
        max_tokens=8192,
        provider="openrouter",
        reasoning=None,
        extra_body_override=_provider_extra(model_slug),
    )

    record: dict = {
        "eval_mode": "score",
        "eval_model_slug": model_slug,
        "eval_model_name": model_name,
        "eval_pass": "score",
        "duration_seconds": 0,
        "tokens_used": 0,
        "json_parseable": False,
        "error": None,
        "metrics": {},
        "raw_output": "",
        "parsed_output": None,
    }

    try:
        start = time.monotonic()
        result = await agent.run(SCORE_MESSAGE, context={"clusters": enriched_clusters})
        duration = time.monotonic() - start

        record["duration_seconds"] = round(duration, 1)
        record["tokens_used"] = result.tokens_used
        record["raw_output"] = result.content

        parsed = Agent._parse_json(result.content)
        if parsed and isinstance(parsed, list):
            record["json_parseable"] = True
            record["parsed_output"] = parsed
            record["metrics"] = compute_score_metrics(parsed)
        else:
            record["error"] = "JSON parse failed or not a list"

    except Exception as e:
        record["error"] = str(e)
        record["duration_seconds"] = round(time.monotonic() - start, 1)

    return record


# ── Summary Table ─────────────────────────────────────────────────────────

def write_summary(eval_dir: Path, mode: str, results: list[dict]):
    """Write _summary.txt with comparison tables."""
    today = date.today().isoformat()
    lines = [
        "=" * 80,
        f"  Curator Two-Stage Eval — {mode} mode — {today}",
        "=" * 80,
        "",
    ]

    # Collect cluster results
    cluster_results = [r for r in results if r.get("eval_pass") == "cluster" or r.get("_pass1")]
    score_results = [r for r in results if r.get("eval_pass") == "score" or r.get("_pass2")]

    # For twostage mode, extract from combined records
    if mode == "twostage":
        cluster_results = [r for r in results if "_pass1" in r]
        score_results = [r for r in results if "_pass2" in r]

    if cluster_results or mode in ("cluster", "twostage"):
        lines.append("Pass 1 — Clustering:")
        lines.append(f"{'Model':<22s} {'Clusters':>8s} {'Coverage%':>9s} {'Largest':>7s} {'Singletons':>10s} {'Tokens':>8s} {'Time':>7s} {'JSON':>6s}")
        lines.append(f"{'-'*22} {'-'*8} {'-'*9} {'-'*7} {'-'*10} {'-'*8} {'-'*7} {'-'*6}")
        for r in cluster_results:
            p1 = r.get("_pass1", r)
            m = p1.get("metrics", {})
            name = p1.get("eval_model_name", r.get("eval_model_name", "?"))
            json_ok = "OK" if p1.get("json_parseable") else "FAIL"
            if p1.get("error") and not p1.get("json_parseable"):
                json_ok = "ERR"
            lines.append(
                f"{name:<22s} {m.get('cluster_count', 0):>8d} "
                f"{m.get('coverage_pct', 0):>8.1f}% "
                f"{m.get('largest_cluster', 0):>7d} "
                f"{m.get('singleton_count', 0):>10d} "
                f"{p1.get('tokens_used', 0):>8d} "
                f"{p1.get('duration_seconds', 0):>6.1f}s "
                f"{json_ok:>6s}"
            )
        lines.append("")

    if score_results or mode in ("score", "twostage", "hybrid"):
        label = "Pass 2 — Scoring:" if mode != "hybrid" else "LLM Scoring (on Python clusters):"
        lines.append(label)
        lines.append(f"{'Model':<22s} {'Topics':>6s} {'Score Range':>11s} {'Avg':>5s} {'Slugs':>5s} {'Tokens':>8s} {'Time':>7s} {'JSON':>6s}")
        lines.append(f"{'-'*22} {'-'*6} {'-'*11} {'-'*5} {'-'*5} {'-'*8} {'-'*7} {'-'*6}")
        for r in score_results:
            p2 = r.get("_pass2", r)
            m = p2.get("metrics", {})
            name = p2.get("eval_model_name", r.get("eval_model_name", "?"))
            json_ok = "OK" if p2.get("json_parseable") else "FAIL"
            if p2.get("error") and not p2.get("json_parseable"):
                json_ok = "ERR"
            score_range = f"{m.get('score_min', 0)}-{m.get('score_max', 0)}"
            slugs = "Yes" if m.get("has_topic_slug") else "No"
            lines.append(
                f"{name:<22s} {m.get('topic_count', 0):>6d} "
                f"{score_range:>11s} "
                f"{m.get('score_avg', 0):>5.1f} "
                f"{slugs:>5s} "
                f"{p2.get('tokens_used', 0):>8d} "
                f"{p2.get('duration_seconds', 0):>6.1f}s "
                f"{json_ok:>6s}"
            )
        lines.append("")

    report = "\n".join(lines)
    summary_path = eval_dir / "_summary.txt"
    summary_path.write_text(report)
    logger.info("Summary saved to %s", summary_path.name)
    print("\n" + report)


# ── Main ──────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Curator Two-Stage Eval")
    parser.add_argument("--mode", required=True, choices=["cluster", "score", "twostage", "hybrid"])
    parser.add_argument("--reuse", required=True, help="Date for feed data (YYYY-MM-DD)")
    parser.add_argument("--model", default=None, help="Run only this model slug")
    parser.add_argument("--cluster-source", default=None, help="Path to clustering result JSON (score mode)")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    args = parser.parse_args()

    # Resolve paths
    feeds_path = ROOT / "raw" / args.reuse / "feeds.json"
    if not feeds_path.exists():
        logger.error("Feeds not found: %s", feeds_path)
        sys.exit(1)

    today = date.today().isoformat()
    if args.output_dir:
        eval_dir = ROOT / args.output_dir
    else:
        eval_dir = ROOT / "output" / "eval" / f"{today}-curator-twostage"
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Validate score mode requires cluster-source
    if args.mode == "score" and not args.cluster_source:
        logger.error("--cluster-source is required for score mode")
        sys.exit(1)

    # Select models
    if args.model:
        model_list = [m for m in MODELS if m["slug"] == args.model]
        if not model_list:
            logger.error("Model '%s' not found in MODELS list", args.model)
            sys.exit(1)
    else:
        model_list = MODELS

    # Load data
    title_only, full_compressed = load_findings(feeds_path)
    input_ids = {f["id"] for f in title_only}

    # Save cluster input reference
    input_path = eval_dir / "_cluster-input.json"
    if not input_path.exists():
        input_path.write_text(json.dumps(title_only, indent=2, ensure_ascii=False))
        logger.info("Saved cluster input to %s (%d findings)", input_path.name, len(title_only))

    # ── Mode: cluster ─────────────────────────────────────────────────
    if args.mode == "cluster":
        results = []
        for i, m in enumerate(model_list):
            if i > 0:
                logger.info("Waiting 15s...")
                await asyncio.sleep(15)

            logger.info("Pass 1 (cluster): %s (%s)...", m["name"], m["slug"])
            record = await run_cluster_pass(m["slug"], m["name"], title_only)
            record["_pass1"] = record.copy()
            results.append(record)

            out_path = eval_dir / f"cluster--{make_safe_name(m['name'])}.json"
            out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

            cm = record["metrics"]
            json_ok = "JSON OK" if record["json_parseable"] else "JSON FAIL"
            logger.info(
                "  %s: %d clusters, %.1f%% coverage, %d tokens, %.1fs, %s",
                m["name"], cm.get("cluster_count", 0), cm.get("coverage_pct", 0),
                record["tokens_used"], record["duration_seconds"], json_ok,
            )

        write_summary(eval_dir, "cluster", results)

    # ── Mode: score ───────────────────────────────────────────────────
    elif args.mode == "score":
        # Load cluster source
        cs_path = Path(args.cluster_source)
        if not cs_path.is_absolute():
            cs_path = ROOT / cs_path
        if not cs_path.exists():
            logger.error("Cluster source not found: %s", cs_path)
            sys.exit(1)

        cs_data = json.loads(cs_path.read_text())
        clusters = cs_data.get("parsed_output") or cs_data
        if not isinstance(clusters, list):
            logger.error("Cluster source does not contain a list")
            sys.exit(1)

        enriched = build_cluster_summaries(clusters, full_compressed)
        logger.info("Built %d enriched clusters from %s", len(enriched), cs_path.name)

        results = []
        for i, m in enumerate(model_list):
            if i > 0:
                logger.info("Waiting 15s...")
                await asyncio.sleep(15)

            logger.info("Pass 2 (score): %s (%s)...", m["name"], m["slug"])
            record = await run_score_pass(m["slug"], m["name"], enriched)
            record["_pass2"] = record.copy()
            results.append(record)

            out_path = eval_dir / f"score--{make_safe_name(m['name'])}.json"
            out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

            sm = record["metrics"]
            json_ok = "JSON OK" if record["json_parseable"] else "JSON FAIL"
            logger.info(
                "  %s: %d topics, scores %d-%d, %d tokens, %.1fs, %s",
                m["name"], sm.get("topic_count", 0),
                sm.get("score_min", 0), sm.get("score_max", 0),
                record["tokens_used"], record["duration_seconds"], json_ok,
            )

        write_summary(eval_dir, "score", results)

    # ── Mode: twostage ────────────────────────────────────────────────
    elif args.mode == "twostage":
        results = []
        for i, m in enumerate(model_list):
            if i > 0:
                logger.info("Waiting 15s...")
                await asyncio.sleep(15)

            logger.info("=== Two-Stage: %s (%s) ===", m["name"], m["slug"])
            safe = make_safe_name(m["name"])

            # Pass 1: Clustering
            logger.info("  Pass 1 (cluster)...")
            p1 = await run_cluster_pass(m["slug"], m["name"], title_only)

            # Save cluster result
            cluster_path = eval_dir / f"cluster--{safe}.json"
            cluster_path.write_text(json.dumps(p1, indent=2, ensure_ascii=False))

            cm = p1["metrics"]
            json_ok = "JSON OK" if p1["json_parseable"] else "JSON FAIL"
            logger.info(
                "  Pass 1: %d clusters, %.1f%% coverage, %d tokens, %.1fs, %s",
                cm.get("cluster_count", 0), cm.get("coverage_pct", 0),
                p1["tokens_used"], p1["duration_seconds"], json_ok,
            )

            # Check if Pass 1 succeeded
            if not p1["json_parseable"] or not p1.get("parsed_output"):
                logger.warning("  Pass 1 failed for %s — skipping Pass 2", m["name"])
                combined = {
                    "eval_mode": "twostage",
                    "eval_model_slug": m["slug"],
                    "eval_model_name": m["name"],
                    "eval_pass": "cluster",
                    "error": p1.get("error", "Pass 1 failed"),
                    "pass1_metrics": p1["metrics"],
                    "pass2_metrics": {},
                    "pass1_tokens": p1["tokens_used"],
                    "pass2_tokens": 0,
                    "pass1_duration": p1["duration_seconds"],
                    "pass2_duration": 0,
                    "json_parseable": False,
                    "tokens_used": p1["tokens_used"],
                    "duration_seconds": p1["duration_seconds"],
                    "raw_output": p1["raw_output"],
                    "parsed_output": None,
                    "_pass1": p1,
                }
                results.append(combined)
                ts_path = eval_dir / f"twostage--{safe}.json"
                ts_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False))
                continue

            # Python glue: build enriched clusters
            enriched = build_cluster_summaries(p1["parsed_output"], full_compressed)
            logger.info("  Glue: %d enriched clusters", len(enriched))

            # Pass 2: Scoring
            logger.info("  Pass 2 (score)...")
            await asyncio.sleep(5)  # brief pause between passes
            p2 = await run_score_pass(m["slug"], m["name"], enriched)

            # Save score result
            score_path = eval_dir / f"score--{safe}.json"
            score_path.write_text(json.dumps(p2, indent=2, ensure_ascii=False))

            sm = p2["metrics"]
            json_ok = "JSON OK" if p2["json_parseable"] else "JSON FAIL"
            logger.info(
                "  Pass 2: %d topics, scores %d-%d, %d tokens, %.1fs, %s",
                sm.get("topic_count", 0),
                sm.get("score_min", 0), sm.get("score_max", 0),
                p2["tokens_used"], p2["duration_seconds"], json_ok,
            )

            # Combined twostage record
            combined = {
                "eval_mode": "twostage",
                "eval_model_slug": m["slug"],
                "eval_model_name": m["name"],
                "eval_pass": "twostage",
                "error": p2.get("error"),
                "pass1_metrics": p1["metrics"],
                "pass2_metrics": p2["metrics"],
                "pass1_tokens": p1["tokens_used"],
                "pass2_tokens": p2["tokens_used"],
                "pass1_duration": p1["duration_seconds"],
                "pass2_duration": p2["duration_seconds"],
                "json_parseable": p2["json_parseable"],
                "tokens_used": p1["tokens_used"] + p2["tokens_used"],
                "duration_seconds": round(p1["duration_seconds"] + p2["duration_seconds"], 1),
                "metrics": p2["metrics"],
                "raw_output": p2["raw_output"],
                "parsed_output": p2.get("parsed_output"),
                "_pass1": p1,
                "_pass2": p2,
            }
            results.append(combined)

            ts_path = eval_dir / f"twostage--{safe}.json"
            ts_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False))

        write_summary(eval_dir, "twostage", results)

    # ── Mode: hybrid ──────────────────────────────────────────────────
    elif args.mode == "hybrid":
        # Python clustering
        py_clusters = python_jaccard_clustering(title_only)
        py_path = eval_dir / "_python-jaccard-clusters.json"
        py_path.write_text(json.dumps(py_clusters, indent=2, ensure_ascii=False))
        logger.info("Saved %d Python clusters to %s", len(py_clusters), py_path.name)

        # Build enriched clusters
        enriched = build_cluster_summaries(py_clusters, full_compressed)
        logger.info("Built %d enriched clusters for scoring", len(enriched))

        results = []
        for i, m in enumerate(model_list):
            if i > 0:
                logger.info("Waiting 15s...")
                await asyncio.sleep(15)

            logger.info("Hybrid (score): %s (%s)...", m["name"], m["slug"])
            record = await run_score_pass(m["slug"], m["name"], enriched)
            record["eval_mode"] = "hybrid"
            record["eval_pass"] = "hybrid"
            record["_pass2"] = record.copy()
            results.append(record)

            out_path = eval_dir / f"hybrid--{make_safe_name(m['name'])}.json"
            out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

            sm = record["metrics"]
            json_ok = "JSON OK" if record["json_parseable"] else "JSON FAIL"
            logger.info(
                "  %s: %d topics, scores %d-%d, %d tokens, %.1fs, %s",
                m["name"], sm.get("topic_count", 0),
                sm.get("score_min", 0), sm.get("score_max", 0),
                record["tokens_used"], record["duration_seconds"], json_ok,
            )

        write_summary(eval_dir, "hybrid", results)

    print(f"\nAll results saved to: {eval_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
