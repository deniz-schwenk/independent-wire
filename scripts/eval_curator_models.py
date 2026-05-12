#!/usr/bin/env python3
"""Curator model audit — 2026-05-11.

Twenty variants across Flash + DeepSeek-V4-Pro + DeepSeek-V4-Flash, plus
the V1 baseline (already on disk, not re-run). Determines whether the
over-clustering pathology that produced the 1004-finding "Stalled US-Iran"
cluster in the Flash-temp-0.2 baseline is Flash-specific or persists
across models and reasoning levels.

Mirrors production Curator construction exactly — same SYSTEM.md +
INSTRUCTIONS.md + CURATOR_SCHEMA + _prepare/_rebuild/_enrich helpers —
with per-variant overrides for model / temperature / reasoning effort /
max_tokens / provider routing.

Output:
- output/eval/curator-2026-05-11/{label}.json — per-variant raw output
- output/eval/curator-2026-05-11/{label}.error.json — per-variant failure
- output/eval/curator-2026-05-11/_metrics.json — aggregated metrics

Cost cap: $17 (~€15) hard stop.

Built fresh (not extending scripts/test_multimodel_curator.py) because the
matrix shape — provider routing override, reasoning-by-temperature grid,
schema-strict output, max_tokens-by-reasoning-level, semaphore-gated
parallelism, hard cost cap, separate error files — doesn't match the
prior script's "title-only vs compressed" two-test pattern.

Usage:
    source .venv/bin/activate && source .env && \\
        python scripts/eval_curator_models.py
"""

import asyncio
import json
import logging
import random
import re
import statistics as _stats
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent  # noqa: E402
from src.agent_stages import (  # noqa: E402
    _prepare_curator_input,
    _rebuild_curator_source_ids,
    _enrich_curator_output,
)
from src.schemas import CURATOR_SCHEMA  # noqa: E402

# ── paths ────────────────────────────────────────────────────────────────
BASELINE_STATE = (
    ROOT / "output" / "2026-05-11-v1-baseline" / "_state"
    / "run-2026-05-11-722571ae" / "run_bus.CuratorStage.json"
)
OUTPUT_DIR = ROOT / "output" / "eval" / "curator-2026-05-11"
AGENTS_DIR = ROOT / "agents"

# ── matrix ───────────────────────────────────────────────────────────────
DEEPSEEK_PROVIDER = {"order": ["deepseek"], "allow_fallbacks": True}

REASONING_TO_MAX_TOKENS = {
    # Bumped 2026-05-12 mid-audit after dskpro reasoning=medium variants
    # at 96k returned 0 clusters with 223k total tokens — reasoning
    # consumed the OUTPUT budget on this provider routing. 320k gives
    # the model headroom for both reasoning + the ~15-20k JSON envelope.
    # The brief's original 64k/96k/128k figures are preserved as comments
    # in case we want to revisit the failure mode later.
    "none": 320000,
    "medium": 320000,
    "high": 320000,
}

# (label, model, temperature, reasoning, extra_body_override)
VARIANTS: list[tuple[str, str, float, str, Optional[dict]]] = [
    # Flash — 2 variants (default OpenRouter routing)
    ("flash-t-10-r-none", "google/gemini-3-flash-preview", 1.0, "none", None),
    ("flash-t-10-r-medium", "google/gemini-3-flash-preview", 1.0, "medium", None),
    # DeepSeek-V4-Pro — 9 variants
    ("dskpro-t-05-r-none", "deepseek/deepseek-v4-pro", 0.5, "none",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskpro-t-05-r-medium", "deepseek/deepseek-v4-pro", 0.5, "medium",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskpro-t-05-r-high", "deepseek/deepseek-v4-pro", 0.5, "high",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskpro-t-07-r-none", "deepseek/deepseek-v4-pro", 0.7, "none",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskpro-t-07-r-medium", "deepseek/deepseek-v4-pro", 0.7, "medium",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskpro-t-07-r-high", "deepseek/deepseek-v4-pro", 0.7, "high",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskpro-t-10-r-none", "deepseek/deepseek-v4-pro", 1.0, "none",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskpro-t-10-r-medium", "deepseek/deepseek-v4-pro", 1.0, "medium",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskpro-t-10-r-high", "deepseek/deepseek-v4-pro", 1.0, "high",
     {"provider": DEEPSEEK_PROVIDER}),
    # DeepSeek-V4-Flash — 9 variants
    ("dskflash-t-05-r-none", "deepseek/deepseek-v4-flash", 0.5, "none",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskflash-t-05-r-medium", "deepseek/deepseek-v4-flash", 0.5, "medium",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskflash-t-05-r-high", "deepseek/deepseek-v4-flash", 0.5, "high",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskflash-t-07-r-none", "deepseek/deepseek-v4-flash", 0.7, "none",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskflash-t-07-r-medium", "deepseek/deepseek-v4-flash", 0.7, "medium",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskflash-t-07-r-high", "deepseek/deepseek-v4-flash", 0.7, "high",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskflash-t-10-r-none", "deepseek/deepseek-v4-flash", 1.0, "none",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskflash-t-10-r-medium", "deepseek/deepseek-v4-flash", 1.0, "medium",
     {"provider": DEEPSEEK_PROVIDER}),
    ("dskflash-t-10-r-high", "deepseek/deepseek-v4-flash", 1.0, "high",
     {"provider": DEEPSEEK_PROVIDER}),
]

CONCURRENCY = 5
COST_CAP_USD = 17.0  # ~€15 at current rate
RETRIES_PER_VARIANT = 3

# ── on-topic heuristic (from brief) ──────────────────────────────────────
ON_TOPIC_RE = re.compile(
    r'\b(iran|tehran|trump|peace|negot|nuclear|israel|netanyahu|hezbollah|'
    r'houthi|yemen|hormuz|oil|tanker|red sea|gaza|hamas|war|sanction|missile|'
    r'enrichment|ayatollah|khamenei|pezeshkian|araghchi|witkoff|persia|'
    r'persian|middle east|naher osten|medio oriente|saudi|qatar|lebanon|'
    r'syria|emirates|teheran)\b',
    re.I,
)


def _is_on_topic(finding: dict) -> bool:
    text = " ".join([
        finding.get("title") or "",
        finding.get("summary") or "",
        finding.get("description") or "",
    ])
    return ON_TOPIC_RE.search(text) is not None


# ── logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eval_curator")
# Suppress httpx info chatter — one variant emits >50 lines per call.
logging.getLogger("httpx").setLevel(logging.WARNING)

CURATOR_MESSAGE = (
    "Review these findings. Cluster related findings into topics. "
    "Score each topic's newsworthiness on a 1-10 scale."
)


# ── per-variant runner ───────────────────────────────────────────────────
async def run_one(
    label: str,
    model: str,
    temperature: float,
    reasoning: str,
    extra_body_override: Optional[dict],
    *,
    raw_findings: list[dict],
    prepared: list[dict],
    sem: asyncio.Semaphore,
    cost_tracker: dict,
    lock: asyncio.Lock,
) -> dict:
    # Resume support: if a successful payload already exists on disk
    # from a prior partial run, skip re-paying and return the loaded
    # payload for the metrics aggregator.
    existing_path = OUTPUT_DIR / f"{label}.json"
    if existing_path.exists():
        try:
            cached = json.loads(existing_path.read_text(encoding="utf-8"))
            if cached.get("status") == "ok" and (cached.get("n_topics") or 0) > 0:
                logger.info(
                    "%-22s RESUMED from disk (n_topics=%d, cost=$%.4f)",
                    label, cached.get("n_topics"), cached.get("cost_usd") or 0,
                )
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    async with sem:
        # Cost-cap admission check — atomic via lock.
        async with lock:
            if cost_tracker["total"] >= COST_CAP_USD:
                logger.warning(
                    "%s SKIPPED — cost cap $%.2f reached", label, COST_CAP_USD,
                )
                return {"label": label, "status": "skipped_cost_cap"}

        max_tokens = REASONING_TO_MAX_TOKENS[reasoning]
        agent = Agent(
            name=f"audit_{label}",
            model=model,
            system_prompt_path=str(AGENTS_DIR / "curator" / "SYSTEM.md"),
            instructions_path=str(AGENTS_DIR / "curator" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=temperature,
            provider="openrouter",
            reasoning=reasoning,
            max_tokens=max_tokens,
            output_schema=CURATOR_SCHEMA,
            extra_body_override=extra_body_override,
        )

        last_err: Optional[BaseException] = None
        last_tb: str = ""
        for attempt in range(1, RETRIES_PER_VARIANT + 1):
            try:
                start = time.monotonic()
                result = await agent.run(
                    CURATOR_MESSAGE, context={"findings": prepared}
                )
                wall = time.monotonic() - start

                topics = _rebuild_curator_source_ids(result, raw_findings)
                topics = _enrich_curator_output(
                    topics, raw_findings, sources_json_path=None
                )

                async with lock:
                    cost_tracker["total"] += result.cost_usd or 0.0
                    running_total = cost_tracker["total"]

                # Truncation heuristic: tokens_used hits within ~5% of
                # max_tokens and content didn't carry valid JSON (raw
                # would not be parseable). Conservative.
                approx_max = int(max_tokens * 0.97)
                likely_truncated = (
                    (result.tokens_used or 0) >= approx_max
                    and result.structured is None
                )

                payload = {
                    "label": label,
                    "status": "ok",
                    "model": model,
                    "temperature": temperature,
                    "reasoning": reasoning,
                    "max_tokens": max_tokens,
                    "wall_seconds": round(wall, 2),
                    "tokens_used": result.tokens_used,
                    "cost_usd": result.cost_usd,
                    "provider_served": result.provider,
                    "response_id": result.response_id,
                    "attempt": attempt,
                    "likely_truncated": likely_truncated,
                    "raw_content_len": len(result.content or ""),
                    "n_topics": len(topics),
                    "curator_topics_unsliced": topics,
                }
                (OUTPUT_DIR / f"{label}.json").write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                top_size = max(
                    (len(t.get("source_ids") or []) for t in topics),
                    default=0,
                )
                logger.info(
                    "%-22s OK $%.4f / %.1fs / %d tok / %d clusters / "
                    "top=%d / running=$%.2f / provider=%r",
                    label, result.cost_usd or 0, wall, result.tokens_used or 0,
                    len(topics), top_size, running_total,
                    result.provider or "?",
                )
                return payload

            except Exception as e:
                last_err = e
                last_tb = traceback.format_exc()
                logger.warning(
                    "%s attempt %d/%d failed: %s",
                    label, attempt, RETRIES_PER_VARIANT, e,
                )
                if attempt < RETRIES_PER_VARIANT:
                    await asyncio.sleep(2 ** attempt)

        err_payload = {
            "label": label, "status": "error",
            "model": model, "temperature": temperature, "reasoning": reasoning,
            "error": str(last_err),
            "error_type": type(last_err).__name__ if last_err else "Unknown",
            "traceback": last_tb,
        }
        (OUTPUT_DIR / f"{label}.error.json").write_text(
            json.dumps(err_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.error("%s FAILED after %d attempts", label, RETRIES_PER_VARIANT)
        return err_payload


# ── metrics ──────────────────────────────────────────────────────────────
def compute_metrics_for_variant(
    payload: dict, raw_findings: list[dict], baseline_top_set: set[str],
) -> dict:
    """Compute the metric row for a single variant payload (or error)."""
    label = payload["label"]
    status = payload.get("status", "error")
    if status != "ok":
        return {"label": label, "status": status}

    topics = payload.get("curator_topics_unsliced") or []
    cluster_sizes = [len(t.get("source_ids") or []) for t in topics]
    cluster_sizes_sorted = sorted(cluster_sizes, reverse=True)
    top_size = cluster_sizes_sorted[0] if cluster_sizes_sorted else 0

    # Top cluster off-topic count
    top_cluster = None
    for t in topics:
        if len(t.get("source_ids") or []) == top_size and top_size > 0:
            top_cluster = t
            break

    on_topic_count = 0
    off_topic_count = 0
    off_topic_titles: list[str] = []
    if top_cluster is not None:
        for sid in top_cluster.get("source_ids") or []:
            try:
                idx = int(str(sid).split("finding-")[-1])
            except (ValueError, IndexError):
                continue
            if not (0 <= idx < len(raw_findings)):
                continue
            f = raw_findings[idx]
            if _is_on_topic(f):
                on_topic_count += 1
            else:
                off_topic_count += 1
                off_topic_titles.append(f.get("title") or "")

    off_topic_pct = (
        100.0 * off_topic_count / (on_topic_count + off_topic_count)
        if (on_topic_count + off_topic_count) > 0 else 0.0
    )

    # Cluster-size distribution
    def _pct(p: float) -> float:
        if not cluster_sizes:
            return 0.0
        s = sorted(cluster_sizes)
        k = (len(s) - 1) * p
        f = int(k)
        c = min(f + 1, len(s) - 1)
        return s[f] + (k - f) * (s[c] - s[f])

    dist = {
        "mean": round(_stats.mean(cluster_sizes), 2) if cluster_sizes else 0,
        "median": _stats.median(cluster_sizes) if cluster_sizes else 0,
        "max": max(cluster_sizes) if cluster_sizes else 0,
        "min": min(cluster_sizes) if cluster_sizes else 0,
        "p90": round(_pct(0.9), 2),
    }

    # Orphan rate
    assigned = sum(cluster_sizes)
    orphan_count = max(0, len(raw_findings) - assigned)
    orphan_pct = 100.0 * orphan_count / len(raw_findings) if raw_findings else 0.0

    # Jaccard vs baseline top cluster
    top_set = set(top_cluster.get("source_ids") or []) if top_cluster else set()
    inter = len(top_set & baseline_top_set)
    union = len(top_set | baseline_top_set)
    jaccard = inter / union if union else 0.0

    return {
        "label": label,
        "status": "ok",
        "model": payload.get("model"),
        "temperature": payload.get("temperature"),
        "reasoning": payload.get("reasoning"),
        "max_tokens": payload.get("max_tokens"),
        "wall_seconds": payload.get("wall_seconds"),
        "tokens_used": payload.get("tokens_used"),
        "cost_usd": round(payload.get("cost_usd") or 0.0, 4),
        "provider_served": payload.get("provider_served"),
        "response_id": payload.get("response_id"),
        "likely_truncated": payload.get("likely_truncated"),
        "n_topics": len(topics),
        "top_cluster_size": top_size,
        "top_cluster_title": (top_cluster or {}).get("title", "")[:80],
        "top_cluster_on_topic": on_topic_count,
        "top_cluster_off_topic": off_topic_count,
        "top_cluster_off_topic_pct": round(off_topic_pct, 2),
        "cluster_size_dist": dist,
        "orphan_count": orphan_count,
        "orphan_pct": round(orphan_pct, 2),
        "jaccard_top_vs_baseline": round(jaccard, 4),
        "top_cluster_source_ids": list(top_set),  # for downstream sampling
        "off_topic_titles_in_top_cluster": off_topic_titles,
    }


def compute_baseline_metrics(
    baseline_state_path: Path, raw_findings: list[dict],
) -> dict:
    d = json.loads(baseline_state_path.read_text(encoding="utf-8"))
    topics = d.get("curator_topics_unsliced") or []
    baseline_payload = {
        "label": "baseline-flash-t-02-r-none",
        "status": "ok",
        "model": "google/gemini-3-flash-preview",
        "temperature": 0.2,
        "reasoning": "none",
        "max_tokens": 64000,
        "wall_seconds": None,
        "tokens_used": None,
        "cost_usd": None,
        "provider_served": None,
        "response_id": None,
        "likely_truncated": False,
        "curator_topics_unsliced": topics,
    }
    baseline_top_set: set[str] = set()
    if topics:
        topics_sorted = sorted(
            topics, key=lambda t: len(t.get("source_ids") or []), reverse=True
        )
        baseline_top_set = set(topics_sorted[0].get("source_ids") or [])
    return compute_metrics_for_variant(baseline_payload, raw_findings, baseline_top_set), baseline_top_set


# ── orchestration ────────────────────────────────────────────────────────
async def main() -> int:
    if not BASELINE_STATE.exists():
        logger.error("Baseline state not found: %s", BASELINE_STATE)
        return 1
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    d = json.loads(BASELINE_STATE.read_text(encoding="utf-8"))
    raw_findings = list(d.get("curator_findings") or [])
    logger.info("Loaded %d curator_findings from baseline", len(raw_findings))
    prepared = _prepare_curator_input(raw_findings)

    # Baseline reference metrics — no LLM call, just disk read.
    baseline_metrics, baseline_top_set = compute_baseline_metrics(
        BASELINE_STATE, raw_findings
    )
    logger.info(
        "Baseline reference: top cluster size=%d, off_topic_pct=%.1f%%",
        baseline_metrics["top_cluster_size"],
        baseline_metrics["top_cluster_off_topic_pct"],
    )

    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    cost_tracker = {"total": 0.0}

    start = time.monotonic()
    results = await asyncio.gather(*(
        run_one(*v, raw_findings=raw_findings, prepared=prepared,
                sem=sem, cost_tracker=cost_tracker, lock=lock)
        for v in VARIANTS
    ))
    wall = time.monotonic() - start

    # Per-family failure check
    family_status: dict[str, list[str]] = {"flash": [], "dskpro": [], "dskflash": []}
    for r in results:
        for fam in family_status:
            if r["label"].startswith(fam + "-"):
                family_status[fam].append(r.get("status", "error"))
    for fam, statuses in family_status.items():
        if statuses and all(s != "ok" for s in statuses):
            logger.error(
                "WHOLE FAMILY FAILED: %s — %d variant(s), no successes",
                fam, len(statuses),
            )

    # Aggregate metrics
    metrics = [baseline_metrics] + [
        compute_metrics_for_variant(r, raw_findings, baseline_top_set)
        for r in results
    ]
    aggregate_path = OUTPUT_DIR / "_metrics.json"
    aggregate_path.write_text(
        json.dumps(
            {
                "audit_run_wall_seconds": round(wall, 1),
                "total_cost_usd": round(cost_tracker["total"], 4),
                "cost_cap_usd": COST_CAP_USD,
                "cost_cap_tripped": cost_tracker["total"] >= COST_CAP_USD,
                "baseline_top_cluster_size": len(baseline_top_set),
                "n_variants_requested": len(VARIANTS),
                "n_variants_ok": sum(1 for r in results if r.get("status") == "ok"),
                "n_variants_error": sum(1 for r in results if r.get("status") == "error"),
                "n_variants_skipped": sum(
                    1 for r in results if r.get("status") == "skipped_cost_cap"
                ),
                "metrics": metrics,
            },
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info("Wrote %s", aggregate_path)
    logger.info(
        "DONE: total cost $%.4f, wall %.1fs, OK=%d / err=%d / skipped=%d",
        cost_tracker["total"], wall,
        sum(1 for r in results if r.get("status") == "ok"),
        sum(1 for r in results if r.get("status") == "error"),
        sum(1 for r in results if r.get("status") == "skipped_cost_cap"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
