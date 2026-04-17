#!/usr/bin/env python3
"""Clustering comparison: Python TF-IDF vs. LLM (GLM 5 Turbo).

Usage:
    source .env && python scripts/test_clustering.py
"""

import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.agent import Agent

FEEDS_PATH = ROOT / "raw" / "2026-04-07" / "feeds.json"
OUTPUT_DIR = ROOT / "output" / "eval" / "2026-04-08-clustering"

LLM_MODEL = "z-ai/glm-5"
LLM_NAME = "GLM 5"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_clustering")


def load_and_compress() -> tuple[list[dict], list[dict]]:
    """Load feeds.json, URL-dedup, compress to {id, title, source_name}."""
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

    compressed = []
    for i, f in enumerate(unique):
        title = f.get("title", "").strip()
        if not title:
            continue
        entry: dict = {
            "id": f"finding-{i}",
            "title": title,
            "source_name": f.get("source_name", ""),
        }
        summary = f.get("summary", "").strip()
        if summary and summary.lower() != title.lower() and not title.lower().startswith(summary.lower()[:50]):
            entry["summary"] = summary
        compressed.append(entry)

    logger.info("Loaded %d raw → %d unique → %d compressed findings", len(raw), len(unique), len(compressed))
    return unique, compressed


def phase_a_tfidf(compressed: list[dict]) -> dict:
    """Phase A: Python TF-IDF clustering on titles."""
    logger.info("Phase A: TF-IDF clustering...")
    start = time.monotonic()

    titles = [f["title"] for f in compressed]
    ids = [f["id"] for f in compressed]

    vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
    tfidf_matrix = vectorizer.fit_transform(titles)

    # Cosine distance = 1 - cosine_similarity
    sim_matrix = cosine_similarity(tfidf_matrix)
    dist_matrix = 1.0 - sim_matrix

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=0.995,
        metric="precomputed",
        linkage="average",
    )
    labels = clustering.fit_predict(dist_matrix)

    # Group findings by cluster
    clusters_map: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        clusters_map.setdefault(label, []).append(idx)

    clusters = []
    for label in sorted(clusters_map.keys()):
        indices = clusters_map[label]
        finding_ids = [ids[i] for i in indices]
        sample_titles = [titles[i] for i in indices[:5]]
        # Use most common title words as cluster title
        cluster_title = sample_titles[0][:80] if sample_titles else f"Cluster {label}"
        clusters.append({
            "cluster_title": cluster_title,
            "finding_ids": finding_ids,
            "finding_count": len(finding_ids),
            "sample_titles": sample_titles,
        })

    clusters.sort(key=lambda c: c["finding_count"], reverse=True)
    duration = time.monotonic() - start

    result = {
        "method": "tfidf",
        "model": None,
        "tokens_used": 0,
        "duration_seconds": round(duration, 1),
        "cluster_count": len(clusters),
        "findings_total": len(compressed),
        "clusters": clusters,
    }

    logger.info("Phase A done: %d clusters in %.1fs", len(clusters), duration)
    return result


async def phase_b_llm(compressed: list[dict]) -> dict:
    """Phase B: LLM clustering with GLM 5 Turbo."""
    logger.info("Phase B: LLM clustering with %s...", LLM_NAME)

    # Title-only input (no summary) to keep tokens lower
    title_only = [{"id": f["id"], "title": f["title"], "source_name": f["source_name"]} for f in compressed]

    message = """Cluster these news findings by topic.
Group findings that cover the same story or event.
Do NOT over-cluster: same actor but different events = separate clusters.
Every finding must appear in exactly one cluster.

Output: JSON array, each element: {"cluster_title": "...", "finding_ids": ["finding-0", ...]}
No markdown, no commentary, only the JSON array."""

    # Create a minimal temp prompt (Agent requires a prompt file)
    temp_prompt = ROOT / "scripts" / "_clustering_prompt.tmp"
    temp_prompt.write_text("You are a news clustering assistant. Follow the user's instructions exactly.")

    agent = Agent(
        name="clustering_llm",
        model=LLM_MODEL,
        prompt_path=str(temp_prompt),
        tools=[],
        temperature=0.2,
        max_tokens=16384,
        provider="openrouter",
    )

    start = time.monotonic()
    try:
        result = await agent.run(message, context={"findings": title_only})
        duration = time.monotonic() - start

        parsed = Agent._parse_json(result.content)
        if not parsed or not isinstance(parsed, list):
            logger.error("LLM returned unparseable JSON (content length: %d)", len(result.content))
            return {
                "method": "llm",
                "model": LLM_MODEL,
                "tokens_used": result.tokens_used,
                "duration_seconds": round(duration, 1),
                "cluster_count": 0,
                "findings_total": len(compressed),
                "clusters": [],
                "error": "JSON parse failed",
                "raw_output": result.content[:2000],
            }

        clusters = []
        for c in parsed:
            fids = c.get("finding_ids", [])
            # Get sample titles from compressed data
            id_to_title = {f["id"]: f["title"] for f in compressed}
            sample_titles = [id_to_title.get(fid, "?") for fid in fids[:5]]
            clusters.append({
                "cluster_title": c.get("cluster_title", "Unknown"),
                "finding_ids": fids,
                "finding_count": len(fids),
                "sample_titles": sample_titles,
            })

        clusters.sort(key=lambda c: c["finding_count"], reverse=True)

        llm_result = {
            "method": "llm",
            "model": LLM_MODEL,
            "tokens_used": result.tokens_used,
            "duration_seconds": round(duration, 1),
            "cluster_count": len(clusters),
            "findings_total": len(compressed),
            "clusters": clusters,
        }
        logger.info("Phase B done: %d clusters, %d tokens, %.1fs", len(clusters), result.tokens_used, duration)
        return llm_result

    except Exception as e:
        duration = time.monotonic() - start
        logger.error("LLM clustering failed: %s", e)
        return {
            "method": "llm",
            "model": LLM_MODEL,
            "tokens_used": 0,
            "duration_seconds": round(duration, 1),
            "cluster_count": 0,
            "findings_total": len(compressed),
            "clusters": [],
            "error": str(e),
        }


def phase_c_comparison(tfidf_result: dict, llm_result: dict) -> str:
    """Phase C: Generate comparison report."""
    logger.info("Phase C: Generating comparison report...")

    def size_stats(clusters: list[dict]) -> dict:
        sizes = [c["finding_count"] for c in clusters]
        if not sizes:
            return {"min": 0, "max": 0, "median": 0, "total": 0}
        return {
            "min": min(sizes),
            "max": max(sizes),
            "median": round(statistics.median(sizes), 1),
            "total": sum(sizes),
        }

    ts = size_stats(tfidf_result["clusters"])
    ls = size_stats(llm_result["clusters"])

    lines = [
        "=== Clustering Comparison ===",
        "",
        f"LLM ({LLM_NAME}):   {llm_result['cluster_count']} clusters, "
        f"{llm_result['tokens_used']}K tokens, {llm_result['duration_seconds']}s",
        f"Python (TF-IDF):  {tfidf_result['cluster_count']} clusters, "
        f"0 tokens, {tfidf_result['duration_seconds']}s",
        "",
        "--- Size Distribution ---",
        f"{'':20s} {'LLM':>10s} {'Python':>10s}",
        f"{'Clusters:':20s} {llm_result['cluster_count']:>10d} {tfidf_result['cluster_count']:>10d}",
        f"{'Min findings:':20s} {ls['min']:>10d} {ts['min']:>10d}",
        f"{'Max findings:':20s} {ls['max']:>10d} {ts['max']:>10d}",
        f"{'Median:':20s} {ls['median']:>10} {ts['median']:>10}",
        f"{'Total assigned:':20s} {ls['total']:>10d} {ts['total']:>10d}",
        "",
    ]

    # Top 5 largest clusters per approach
    lines.append("--- Top 5 Largest Clusters ---")
    lines.append("")
    lines.append("LLM:")
    for c in llm_result["clusters"][:5]:
        lines.append(f"  [{c['finding_count']:3d}] {c['cluster_title'][:70]}")
    lines.append("")
    lines.append("Python:")
    for c in tfidf_result["clusters"][:5]:
        lines.append(f"  [{c['finding_count']:3d}] {c['cluster_title'][:70]}")
    lines.append("")

    # Top 5 smallest clusters
    lines.append("--- Top 5 Smallest Clusters ---")
    lines.append("")
    lines.append("LLM:")
    for c in llm_result["clusters"][-5:]:
        lines.append(f"  [{c['finding_count']:3d}] {c['cluster_title'][:70]}")
    lines.append("")
    lines.append("Python:")
    for c in tfidf_result["clusters"][-5:]:
        lines.append(f"  [{c['finding_count']:3d}] {c['cluster_title'][:70]}")
    lines.append("")

    # Disagreements: pick 3 LLM clusters, check where those findings ended up in TF-IDF
    lines.append("--- Disagreements (3 LLM clusters vs. Python) ---")
    lines.append("")

    # Build reverse index: finding_id → tfidf cluster index
    tfidf_reverse: dict[str, int] = {}
    for ci, c in enumerate(tfidf_result["clusters"]):
        for fid in c["finding_ids"]:
            tfidf_reverse[fid] = ci

    # Pick 3 medium-sized LLM clusters for comparison
    mid_clusters = [c for c in llm_result["clusters"] if 3 <= c["finding_count"] <= 20]
    if len(mid_clusters) < 3:
        mid_clusters = llm_result["clusters"][:3]
    else:
        mid_clusters = mid_clusters[:3]

    for c in mid_clusters:
        lines.append(f"LLM Cluster: \"{c['cluster_title']}\" ({c['finding_count']} findings)")
        # Check which TF-IDF clusters these findings map to
        tfidf_clusters_hit: dict[int, list[str]] = {}
        unassigned = []
        for fid in c["finding_ids"]:
            tci = tfidf_reverse.get(fid)
            if tci is not None:
                tfidf_clusters_hit.setdefault(tci, []).append(fid)
            else:
                unassigned.append(fid)

        if len(tfidf_clusters_hit) == 1:
            tci = list(tfidf_clusters_hit.keys())[0]
            lines.append(f"  → All in Python cluster #{tci}: \"{tfidf_result['clusters'][tci]['cluster_title'][:60]}\"")
        else:
            lines.append(f"  → Split across {len(tfidf_clusters_hit)} Python clusters:")
            for tci, fids in sorted(tfidf_clusters_hit.items(), key=lambda x: -len(x[1])):
                tc = tfidf_result["clusters"][tci]
                lines.append(f"    Python #{tci} ({len(fids)} findings): \"{tc['cluster_title'][:60]}\"")
        if unassigned:
            lines.append(f"  → {len(unassigned)} findings not in any Python cluster")
        lines.append("")

    report = "\n".join(lines)
    logger.info("Comparison report generated (%d lines)", len(lines))
    return report


async def main():
    if not FEEDS_PATH.exists():
        logger.error("Feeds file not found: %s", FEEDS_PATH)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load and compress
    _, compressed = load_and_compress()

    # Phase A: TF-IDF
    tfidf_result = phase_a_tfidf(compressed)
    tfidf_path = OUTPUT_DIR / "python-tfidf-clusters.json"
    tfidf_path.write_text(json.dumps(tfidf_result, indent=2, ensure_ascii=False))
    logger.info("Saved TF-IDF results to %s", tfidf_path.name)

    # Phase B: LLM
    llm_result = await phase_b_llm(compressed)
    llm_path = OUTPUT_DIR / "llm-glm5-clusters.json"
    llm_path.write_text(json.dumps(llm_result, indent=2, ensure_ascii=False))
    logger.info("Saved LLM results to %s", llm_path.name)

    # Phase C: Comparison
    report = phase_c_comparison(tfidf_result, llm_result)
    report_path = OUTPUT_DIR / "comparison-report.txt"
    report_path.write_text(report)
    logger.info("Saved comparison report to %s", report_path.name)

    print("\n" + report)


if __name__ == "__main__":
    asyncio.run(main())
