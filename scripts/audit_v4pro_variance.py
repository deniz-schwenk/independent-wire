"""TASK-AUDIT-CURATOR-V4PRO-VARIANCE.

Variance audit of DeepSeek-V4-Pro as Curator: 3 dates × 3 temperatures ×
3 repetitions = 27 calls, all via DeepSeek-direct (api.deepseek.com).
``thinking={"type":"disabled"}`` across the matrix — the previous audit
established that V4-Pro with reasoning≥medium has a structural
0-output failure mode at our payload sizes.

The headline question this answers: when V4-Pro is given identical
input three times at the same temperature, do the three cluster
shapes look like each other (high inter-rep Jaccard = reproducible)
or like three independent draws from a stochastic regime?

Reuses the shadow infrastructure (``scripts/curator_shadow.py``):
streaming SSE client (DeepSeek-direct closes non-streaming connections
at ~60 s), the curator prompt-construction helpers, and the metric
function from ``src/curator_metrics.py``. Pricing is overridden because
the shadow's constants are V4-Flash; V4-Pro is on a different rate card
(75 %-discount line through 2026-05-31).

Usage:

    python scripts/audit_v4pro_variance.py

Cost cap $5 cumulative — the audit halts and surfaces immediately on
breach. Failure cap 9 of 27 — the audit halts on serving-side breakage,
treating it as not a model question.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent, AgentResult  # noqa: E402
from src.agent_stages import (  # noqa: E402
    _enrich_curator_output,
    _prepare_curator_input,
    _rebuild_curator_source_ids,
)
from src.curator_metrics import compute_metrics  # noqa: E402
from scripts.curator_shadow import (  # noqa: E402
    AGENTS_DIR,
    CURATOR_MESSAGE,
    DEEPSEEK_BASE_URL,
    _stream_chat,
    load_deepseek_api_key,
)


# ── Configuration ────────────────────────────────────────────────────────
V4PRO_MODEL = "deepseek-v4-pro"
# max_tokens raised from the brief's 64000 to 320000 mid-run after
# 9 calls on 2026-05-08 saw mid-stream peer-closes around chunk 20000
# (~20k output tokens). The 9 already-saved reps at max_tokens=64000
# are preserved; from here on the matrix uses 320000.
MAX_TOKENS = 320000
EXTRA_BODY = {"thinking": {"type": "disabled"}}

DATES = ("2026-05-08", "2026-05-11", "2026-05-13")
CONFIGS: dict[str, dict] = {
    "dskpro-t05-r-none": {"temperature": 0.5},
    "dskpro-t07-r-none": {"temperature": 0.7},
    "dskpro-t10-r-none": {"temperature": 1.0},
}
REPS = 3

# V4-Pro pricing per DeepSeek docs as of 2026-05-13 (75% discount
# active until 2026-05-31). Documented in the report; this audit's
# computed cost figures live or die by these constants.
V4PRO_PRICE_INPUT_MISS_PER_M = 0.435
V4PRO_PRICE_INPUT_CACHED_PER_M = 0.003625
V4PRO_PRICE_OUTPUT_PER_M = 0.87

COST_CAP_USD = 5.0
MAX_FAILED_CALLS = 9
RETRY_COUNT = 3
RETRY_BACKOFF_SECONDS = (2.0, 4.0)  # waits before retry 2 and retry 3

OUTPUT_DIR = ROOT / "output" / "eval" / "curator-v4pro-variance-2026-05-13"
REPORT_PATH = ROOT / "docs" / "AUDIT-CURATOR-V4PRO-VARIANCE-2026-05-13.md"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("audit_v4pro")


# ── State-file resolution ────────────────────────────────────────────────
def find_state_for_date(date: str) -> Optional[Path]:
    """Return the path to ``run_bus.CuratorStage.json`` for a date.

    2026-05-11 is pinned to the v1-baseline snapshot per the brief.
    Other dates take the newest run directory."""
    if date == "2026-05-11":
        p = (
            ROOT
            / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json"
        )
        return p if p.exists() else None
    state_dir = ROOT / "output" / date / "_state"
    if not state_dir.exists():
        return None
    candidates = list(state_dir.glob("run-*/run_bus.CuratorStage.json"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


# ── Cost helper ──────────────────────────────────────────────────────────
def estimate_cost_v4pro(uncached: int, cached: int, output: int) -> float:
    """V4-Pro effective rate (75% discount). DeepSeek-direct does not
    return ``usage.cost``, so this is computed from the token counts in
    the trailing SSE usage event."""
    return (
        uncached * V4PRO_PRICE_INPUT_MISS_PER_M
        + cached * V4PRO_PRICE_INPUT_CACHED_PER_M
        + output * V4PRO_PRICE_OUTPUT_PER_M
    ) / 1_000_000


# ── Single call ──────────────────────────────────────────────────────────
async def _single_call(
    api_key: str,
    findings: list[dict],
    temperature: float,
    label: str,
) -> dict:
    """One V4-Pro call. Raises on transport/parse error so the caller
    can retry."""
    agent = Agent(
        name=f"audit_v4pro_{label}",
        model=V4PRO_MODEL,
        system_prompt_path=str(AGENTS_DIR / "curator" / "SYSTEM.md"),
        instructions_path=str(AGENTS_DIR / "curator" / "INSTRUCTIONS.md"),
        tools=[],
        temperature=temperature,
        provider="deepseek",
        api_key=api_key,
        max_tokens=MAX_TOKENS,
        extra_body_override=EXTRA_BODY,
    )
    prepared = _prepare_curator_input(findings)
    body = {
        "model": V4PRO_MODEL,
        "messages": [
            {"role": "system", "content": agent._build_system_prompt()},
            {
                "role": "user",
                "content": agent._build_user_message(
                    message=CURATOR_MESSAGE,
                    context={"findings": prepared},
                ),
            },
        ],
        "temperature": temperature,
        "max_tokens": MAX_TOKENS,
        **EXTRA_BODY,
    }
    t0 = time.monotonic()
    stream = await _stream_chat(api_key, body, log_label=label)
    wall = time.monotonic() - t0

    uncached = max(0, stream.prompt_tokens - stream.cached_tokens)
    cost = estimate_cost_v4pro(uncached, stream.cached_tokens, stream.completion_tokens)

    result = AgentResult(
        content=stream.content,
        structured=None,
        tool_calls=[],
        tokens_used=stream.prompt_tokens + stream.completion_tokens,
        cost_usd=cost,
        model=V4PRO_MODEL,
        duration_seconds=round(wall, 2),
        provider="deepseek-direct",
        response_id=stream.response_id,
    )
    topics = _rebuild_curator_source_ids(result, findings)
    topics = _enrich_curator_output(topics, findings, sources_json_path=None)

    return {
        "topics": topics,
        "wall_seconds": round(wall, 2),
        "cost_usd": cost,
        "prompt_tokens": stream.prompt_tokens,
        "completion_tokens": stream.completion_tokens,
        "cached_input_tokens": stream.cached_tokens,
        "response_id": stream.response_id,
        "finish_reason": stream.finish_reason,
        "raw_content_len": len(stream.content or ""),
    }


async def _call_with_retry(
    api_key: str, findings: list[dict], temperature: float, label: str,
) -> dict:
    """Wrap ``_single_call`` with exponential-backoff retry. Surface the
    last exception to the caller after RETRY_COUNT attempts."""
    last_exc: Optional[BaseException] = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            return await _single_call(api_key, findings, temperature, label)
        except Exception as exc:  # noqa: BLE001 — record any failure
            last_exc = exc
            if attempt >= RETRY_COUNT:
                break
            wait = RETRY_BACKOFF_SECONDS[attempt - 1]
            logger.warning(
                "%s attempt %d failed (%s: %s); retrying in %.0fs",
                label, attempt, type(exc).__name__, str(exc)[:200], wait,
            )
            await asyncio.sleep(wait)
    assert last_exc is not None
    raise last_exc


# ── Aggregation helpers ──────────────────────────────────────────────────
def _top_cluster_ids(topics: list[dict]) -> set[str]:
    if not topics:
        return set()
    top = max(topics, key=lambda t: len(t.get("source_ids") or []))
    return set(top.get("source_ids") or [])


def _jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _pairwise_inter_rep_jaccard(rep_top_ids: list[set]) -> dict:
    """Pairwise Jaccard IoU for top-cluster source_ids across reps.

    Returns ``{pairs: [j12, j13, j23], mean, min}``. The mean is the
    headline variance signal; min flags the worst pair."""
    js: list[float] = []
    n = len(rep_top_ids)
    for i in range(n):
        for j in range(i + 1, n):
            js.append(_jaccard(rep_top_ids[i], rep_top_ids[j]))
    if not js:
        return {"pairs": [], "mean": 0.0, "min": 0.0}
    return {
        "pairs": [round(j, 4) for j in js],
        "mean": round(statistics.mean(js), 4),
        "min": round(min(js), 4),
    }


def _summarise_cell(reps: list[dict]) -> dict:
    """Mean / stddev / range across the reps for the key metrics."""
    succeeded = [r for r in reps if r.get("status") == "ok"]
    fields = (
        "top_cluster_size",
        "top_cluster_off_topic_pct",
        "n_clusters",
        "orphan_rate",
        "cluster_size_p50",
        "cluster_size_p90",
    )
    out: dict = {}
    for f in fields:
        vals = [r["metrics"][f] for r in succeeded]
        out[f] = {
            "mean": round(statistics.mean(vals), 4) if vals else None,
            "stddev": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
            "min": round(min(vals), 4) if vals else None,
            "max": round(max(vals), 4) if vals else None,
        }
    out["cost_usd_mean"] = round(
        statistics.mean([r["cost_usd"] for r in succeeded]), 5
    ) if succeeded else 0.0
    out["wall_seconds_mean"] = round(
        statistics.mean([r["wall_seconds"] for r in succeeded]), 2
    ) if succeeded else 0.0
    out["n_succeeded"] = len(succeeded)
    out["n_failed"] = len(reps) - len(succeeded)
    return out


# ── Disk-resume helpers ──────────────────────────────────────────────────
def _load_rep_from_disk(date: str, config_label: str, rep: int) -> Optional[dict]:
    """Load an existing rep-N.json as an in-memory call_record. Returns
    None if the file is missing, corrupt, or status != ok."""
    rep_path = OUTPUT_DIR / date / config_label / f"rep-{rep}.json"
    if not rep_path.exists():
        return None
    try:
        data = json.loads(rep_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("status") != "ok":
        return None
    return {
        "date": data["date"],
        "config": data["config"],
        "temperature": data["temperature"],
        "rep": data["rep"],
        "status": "ok",
        "wall_seconds": data.get("wall_seconds", 0.0),
        "cost_usd": data.get("cost_usd", 0.0),
        "prompt_tokens": data.get("prompt_tokens", 0),
        "completion_tokens": data.get("completion_tokens", 0),
        "cached_input_tokens": data.get("cached_input_tokens", 0),
        "response_id": data.get("response_id"),
        "finish_reason": data.get("finish_reason"),
        "metrics": data["metrics"],
        "jaccard_top_vs_production": data.get("jaccard_top_vs_production", 0.0),
        "_top_ids_set": set(data.get("top_cluster_source_ids") or []),
        "_resumed_from_disk": True,
    }


async def _run_one_rep(
    api_key: str,
    findings: list[dict],
    production_top: set[str],
    date: str,
    config_label: str,
    rep: int,
) -> dict:
    """Run a single rep end-to-end (retry → metrics → disk-write). Returns
    a call_record dict. Never raises — failures land in the record."""
    label = f"{date}/{config_label}/rep-{rep}"
    cfg = CONFIGS[config_label]
    logger.info("[%s] start", label)
    try:
        result = await _call_with_retry(api_key, findings, cfg["temperature"], label)
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s] FAILED after retries: %s", label, exc)
        return {
            "date": date,
            "config": config_label,
            "temperature": cfg["temperature"],
            "rep": rep,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    state_like = {
        "curator_findings": findings,
        "curator_topics_unsliced": result["topics"],
    }
    metrics = compute_metrics(state_like)
    rep_top_ids = _top_cluster_ids(result["topics"])
    jaccard_vs_prod = _jaccard(rep_top_ids, production_top)

    cell_dir = OUTPUT_DIR / date / config_label
    cell_dir.mkdir(parents=True, exist_ok=True)
    (cell_dir / f"rep-{rep}.json").write_text(
        json.dumps({
            "date": date,
            "config": config_label,
            "temperature": cfg["temperature"],
            "rep": rep,
            "model": V4PRO_MODEL,
            "extra_body": EXTRA_BODY,
            "status": "ok",
            "wall_seconds": result["wall_seconds"],
            "cost_usd": result["cost_usd"],
            "cost_source": "computed-from-tokens (V4-Pro 75% discount rate)",
            "prompt_tokens": result["prompt_tokens"],
            "completion_tokens": result["completion_tokens"],
            "cached_input_tokens": result["cached_input_tokens"],
            "response_id": result["response_id"],
            "finish_reason": result["finish_reason"],
            "raw_content_len": result["raw_content_len"],
            "metrics": metrics,
            "jaccard_top_vs_production": round(jaccard_vs_prod, 4),
            "top_cluster_source_ids": sorted(rep_top_ids),
            "curator_topics_unsliced": result["topics"],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "[%s] ok wall=%.0fs cost=$%.4f top=%d off%%=%.2f clusters=%d",
        label,
        result["wall_seconds"],
        result["cost_usd"],
        metrics["top_cluster_size"],
        metrics["top_cluster_off_topic_pct"],
        metrics["n_clusters"],
    )
    return {
        "date": date,
        "config": config_label,
        "temperature": cfg["temperature"],
        "rep": rep,
        "status": "ok",
        "wall_seconds": result["wall_seconds"],
        "cost_usd": result["cost_usd"],
        "prompt_tokens": result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "cached_input_tokens": result["cached_input_tokens"],
        "response_id": result["response_id"],
        "finish_reason": result["finish_reason"],
        "metrics": metrics,
        "jaccard_top_vs_production": round(jaccard_vs_prod, 4),
        "_top_ids_set": rep_top_ids,
    }


# ── Matrix runner ────────────────────────────────────────────────────────
async def run_matrix() -> tuple[list[dict], dict, str]:
    """Run the full 27-call matrix with within-cell parallelism and
    skip-completed resume. Returns ``(call_records, run_meta, halt_reason)``."""

    # State + production-top-cluster baselines
    state_paths: dict[str, Path] = {}
    for date in DATES:
        p = find_state_for_date(date)
        if p is None:
            raise SystemExit(
                f"FATAL: no CuratorStage state for {date}. Can't fabricate input."
            )
        state_paths[date] = p

    findings_by_date: dict[str, list[dict]] = {}
    production_top_by_date: dict[str, set[str]] = {}
    production_metrics_by_date: dict[str, dict] = {}
    for date, path in state_paths.items():
        state = json.loads(path.read_text(encoding="utf-8"))
        findings_by_date[date] = state.get("curator_findings") or []
        topics = state.get("curator_topics_unsliced") or []
        production_top_by_date[date] = _top_cluster_ids(topics)
        production_metrics_by_date[date] = compute_metrics({
            "curator_findings": findings_by_date[date],
            "curator_topics_unsliced": topics,
        })
        logger.info(
            "input %s: %d findings, %d clusters; production top=%d",
            date,
            len(findings_by_date[date]),
            len(topics),
            production_metrics_by_date[date]["top_cluster_size"],
        )

    api_key = load_deepseek_api_key()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    call_records: list[dict] = []
    cumulative_cost = 0.0
    n_failed = 0
    halt_reason = "complete"
    t_start = time.monotonic()

    def _halt_payload() -> dict:
        return {
            "cumulative_cost": cumulative_cost,
            "n_failed": n_failed,
            "production_metrics": production_metrics_by_date,
            "production_top_ids": {
                d: sorted(list(ids)) for d, ids in production_top_by_date.items()
            },
            "wall_seconds_total": round(time.monotonic() - t_start, 1),
        }

    for date in DATES:
        for config_label in CONFIGS:
            if cumulative_cost >= COST_CAP_USD:
                halt_reason = f"cost_cap_reached_${cumulative_cost:.4f}"
                logger.error("HALT: %s", halt_reason)
                return call_records, _halt_payload(), halt_reason
            if n_failed > MAX_FAILED_CALLS:
                halt_reason = f"failure_cap_reached_{n_failed}"
                logger.error("HALT: %s", halt_reason)
                return call_records, _halt_payload(), halt_reason

            # Step 1: load any completed reps from disk
            cell_records: list[dict] = []
            missing_reps: list[int] = []
            for rep in range(1, REPS + 1):
                disk_record = _load_rep_from_disk(date, config_label, rep)
                if disk_record is not None:
                    cell_records.append(disk_record)
                    logger.info(
                        "[%s/%s/rep-%d] RESUMED from disk (cost $%.4f, top=%d)",
                        date, config_label, rep,
                        disk_record["cost_usd"],
                        disk_record["metrics"]["top_cluster_size"],
                    )
                else:
                    missing_reps.append(rep)

            # Step 2: gather missing reps in parallel (within-cell)
            if missing_reps:
                logger.info(
                    "[%s/%s] launching %d reps in parallel: %s",
                    date, config_label, len(missing_reps), missing_reps,
                )
                tasks = [
                    _run_one_rep(
                        api_key,
                        findings_by_date[date],
                        production_top_by_date[date],
                        date,
                        config_label,
                        rep,
                    )
                    for rep in missing_reps
                ]
                fresh_records = await asyncio.gather(*tasks)
                cell_records.extend(fresh_records)

            # Step 3: tally costs and failures across the cell
            for r in cell_records:
                if r.get("_resumed_from_disk"):
                    continue  # don't double-count cumulative cost for resumed reps
                if r.get("status") == "ok":
                    cumulative_cost += r.get("cost_usd", 0.0)
                else:
                    n_failed += 1
            call_records.extend(cell_records)
            logger.info(
                "[%s/%s] cell complete: ok=%d failed=%d (cum=$%.4f failed=%d/27)",
                date, config_label,
                sum(1 for r in cell_records if r.get("status") == "ok"),
                sum(1 for r in cell_records if r.get("status") != "ok"),
                cumulative_cost, n_failed,
            )

    run_meta = {
        "cumulative_cost": round(cumulative_cost, 5),
        "n_failed": n_failed,
        "production_metrics": production_metrics_by_date,
        "production_top_ids": {
            d: sorted(list(ids)) for d, ids in production_top_by_date.items()
        },
        "wall_seconds_total": round(time.monotonic() - t_start, 1),
    }
    return call_records, run_meta, halt_reason


# ── Aggregate computation ────────────────────────────────────────────────
def build_aggregate(call_records: list[dict], run_meta: dict) -> dict:
    """Per-cell stats over the 3 reps, including the headline inter-rep
    Jaccard mean."""
    cells: dict[str, dict] = {}
    for date in DATES:
        for config_label in CONFIGS:
            cell_key = f"{date}/{config_label}"
            cell_reps = [
                r for r in call_records
                if r["date"] == date and r["config"] == config_label
            ]
            rep_top_ids = [r["_top_ids_set"] for r in cell_reps if r.get("status") == "ok"]
            cells[cell_key] = {
                "date": date,
                "config": config_label,
                "temperature": CONFIGS[config_label]["temperature"],
                "reps": [
                    {
                        "rep": r["rep"],
                        "status": r["status"],
                        **(
                            {
                                "wall_seconds": r.get("wall_seconds"),
                                "cost_usd": r.get("cost_usd"),
                                "metrics": r.get("metrics"),
                                "jaccard_top_vs_production": r.get("jaccard_top_vs_production"),
                            }
                            if r.get("status") == "ok"
                            else {"error": r.get("error")}
                        ),
                    }
                    for r in cell_reps
                ],
                "summary": _summarise_cell(cell_reps),
                "inter_rep_jaccard": _pairwise_inter_rep_jaccard(rep_top_ids),
            }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matrix_shape": {"dates": list(DATES), "configs": list(CONFIGS), "reps": REPS},
        "totals": {
            "attempted": len(call_records),
            "succeeded": sum(1 for r in call_records if r.get("status") == "ok"),
            "failed": run_meta["n_failed"],
            "cumulative_cost_usd": run_meta["cumulative_cost"],
            "wall_seconds_total": run_meta["wall_seconds_total"],
            "cost_cap_usd": COST_CAP_USD,
            "failure_cap": MAX_FAILED_CALLS,
        },
        "production_baselines": {
            date: {
                "n_clusters": run_meta["production_metrics"][date]["n_clusters"],
                "top_cluster_size": run_meta["production_metrics"][date]["top_cluster_size"],
                "top_cluster_off_topic_pct": run_meta["production_metrics"][date][
                    "top_cluster_off_topic_pct"
                ],
                "orphan_rate": run_meta["production_metrics"][date]["orphan_rate"],
            }
            for date in DATES
        },
        "cells": cells,
        "pricing": {
            "model": V4PRO_MODEL,
            "input_miss_per_M": V4PRO_PRICE_INPUT_MISS_PER_M,
            "input_cached_per_M": V4PRO_PRICE_INPUT_CACHED_PER_M,
            "output_per_M": V4PRO_PRICE_OUTPUT_PER_M,
            "note": "DeepSeek V4-Pro 75% discount rate (valid until 2026-05-31).",
        },
    }


# ── Report writing ───────────────────────────────────────────────────────
def _fmt_pm(mean, stddev) -> str:
    if mean is None:
        return "—"
    return f"{mean:.2f} ± {stddev:.2f}"


def _fmt_range(min_, max_) -> str:
    if min_ is None:
        return "—"
    return f"[{min_:.2f} … {max_:.2f}]"


def write_report(aggregate: dict, halt_reason: str) -> None:
    """Render the 8-section audit report."""
    totals = aggregate["totals"]
    cells = aggregate["cells"]
    prod = aggregate["production_baselines"]

    L: list[str] = []
    L.append("# Audit — DeepSeek-V4-Pro Curator variance (3-day × 3-temp × 3-rep)\n")
    L.append(f"- **Generated:** {aggregate['generated_at']}")
    L.append(f"- **Model:** `{aggregate['pricing']['model']}` · `extra_body={EXTRA_BODY}` · max_tokens={MAX_TOKENS}")
    L.append(
        f"- **Pricing applied:** miss ${aggregate['pricing']['input_miss_per_M']}/M · "
        f"cached ${aggregate['pricing']['input_cached_per_M']}/M · "
        f"output ${aggregate['pricing']['output_per_M']}/M ({aggregate['pricing']['note']})"
    )
    L.append("")

    # 1. Setup
    L.append("## 1. Setup")
    L.append("")
    L.append(f"- Dates: {', '.join(DATES)}")
    L.append(f"- Configs: " + ", ".join(
        f"`{lab}` (t={cfg['temperature']})" for lab, cfg in CONFIGS.items()
    ))
    L.append(f"- Reps per (date, config): {REPS}")
    L.append(f"- Total runs attempted: {totals['attempted']}")
    L.append(f"- Total succeeded: {totals['succeeded']}")
    L.append(f"- Total failed: {totals['failed']}")
    L.append(
        f"- Total cost: **${totals['cumulative_cost_usd']:.4f}** "
        f"(cap ${totals['cost_cap_usd']:.2f})"
    )
    L.append(f"- Total wall: {totals['wall_seconds_total']:.0f} s")
    L.append(f"- Halt reason: `{halt_reason}`")
    L.append("")

    # 2. Per-cell variance table
    L.append("## 2. Per-cell variance table")
    L.append("")
    L.append(
        "| Cell | top_cluster_size | top_off%_regex | n_clusters | "
        "orphan_rate | inter-rep Jaccard (mean / min) | n_ok |"
    )
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for cell_key, cell in cells.items():
        s = cell["summary"]
        irj = cell["inter_rep_jaccard"]
        L.append(
            f"| {cell_key} | "
            f"{_fmt_pm(s['top_cluster_size']['mean'], s['top_cluster_size']['stddev'])} "
            f"{_fmt_range(s['top_cluster_size']['min'], s['top_cluster_size']['max'])} | "
            f"{_fmt_pm(s['top_cluster_off_topic_pct']['mean'], s['top_cluster_off_topic_pct']['stddev'])} | "
            f"{_fmt_pm(s['n_clusters']['mean'], s['n_clusters']['stddev'])} "
            f"{_fmt_range(s['n_clusters']['min'], s['n_clusters']['max'])} | "
            f"{_fmt_pm(s['orphan_rate']['mean'], s['orphan_rate']['stddev'])} | "
            f"{irj['mean']:.3f} / {irj['min']:.3f} | "
            f"{s['n_succeeded']}/3 |"
        )
    L.append("")
    L.append(
        "**Inter-rep Jaccard** = mean of pairwise IoU on the three reps' "
        "top-cluster `source_ids`. Higher = more reproducible. 1.00 = "
        "identical top clusters across reps; 0.00 = three disjoint top clusters."
    )
    L.append("")

    # 3. Per-date cross-config comparison
    L.append("## 3. Per-date cross-config comparison")
    L.append("")
    for date in DATES:
        L.append(f"### {date}")
        L.append("")
        L.append(
            "| temperature | top_cluster_size (mean ± sd) | top_off% | n_clusters | inter-rep Jaccard |"
        )
        L.append("|---:|---:|---:|---:|---:|")
        for config_label in CONFIGS:
            cell = cells[f"{date}/{config_label}"]
            s = cell["summary"]
            irj = cell["inter_rep_jaccard"]
            L.append(
                f"| {cell['temperature']:.1f} | "
                f"{_fmt_pm(s['top_cluster_size']['mean'], s['top_cluster_size']['stddev'])} | "
                f"{_fmt_pm(s['top_cluster_off_topic_pct']['mean'], s['top_cluster_off_topic_pct']['stddev'])} | "
                f"{_fmt_pm(s['n_clusters']['mean'], s['n_clusters']['stddev'])} | "
                f"{irj['mean']:.3f} |"
            )
        L.append("")

    # 4. Per-config cross-date comparison
    L.append("## 4. Per-config cross-date comparison")
    L.append("")
    for config_label in CONFIGS:
        L.append(f"### {config_label} (t={CONFIGS[config_label]['temperature']})")
        L.append("")
        L.append(
            "| date | top_cluster_size (mean ± sd) | top_off% | n_clusters | inter-rep Jaccard |"
        )
        L.append("|---|---:|---:|---:|---:|")
        for date in DATES:
            cell = cells[f"{date}/{config_label}"]
            s = cell["summary"]
            irj = cell["inter_rep_jaccard"]
            L.append(
                f"| {date} | "
                f"{_fmt_pm(s['top_cluster_size']['mean'], s['top_cluster_size']['stddev'])} | "
                f"{_fmt_pm(s['top_cluster_off_topic_pct']['mean'], s['top_cluster_off_topic_pct']['stddev'])} | "
                f"{_fmt_pm(s['n_clusters']['mean'], s['n_clusters']['stddev'])} | "
                f"{irj['mean']:.3f} |"
            )
        L.append("")

    # 5. Cross-comparison vs production Gemini-temp=1.0
    L.append("## 5. Cross-comparison vs production Gemini-temp=1.0")
    L.append("")
    L.append(
        "| date | prod top | prod off% | V4-Pro best t / top mean | V4-Pro best t / off% mean | best t (by lowest off%) |"
    )
    L.append("|---|---:|---:|---:|---:|---:|")
    for date in DATES:
        p = prod[date]
        # Find the temperature whose mean off% is lowest on this date
        best_label = None
        best_off = None
        best_top = None
        for config_label in CONFIGS:
            s = cells[f"{date}/{config_label}"]["summary"]
            off = s["top_cluster_off_topic_pct"]["mean"]
            if off is None:
                continue
            if best_off is None or off < best_off:
                best_off = off
                best_label = config_label
                best_top = s["top_cluster_size"]["mean"]
        L.append(
            f"| {date} | {p['top_cluster_size']} | {p['top_cluster_off_topic_pct']:.2f}% | "
            f"{best_top:.1f} | {best_off:.2f}% | "
            f"t={CONFIGS[best_label]['temperature']} |"
        )
    L.append("")

    # 6. Observation (computed)
    L.append("## 6. Observation")
    L.append("")
    irj_means: list[float] = [
        c["inter_rep_jaccard"]["mean"] for c in cells.values()
    ]
    irj_pathology_means = [
        cells[f"2026-05-11/{cfg}"]["inter_rep_jaccard"]["mean"] for cfg in CONFIGS
    ]
    irj_clean_means = [
        cells[f"2026-05-08/{cfg}"]["inter_rep_jaccard"]["mean"] for cfg in CONFIGS
    ]
    L.append(
        f"Mean inter-rep Jaccard across all 9 cells: **{statistics.mean(irj_means):.3f}**. "
        f"Range: {min(irj_means):.3f} – {max(irj_means):.3f}. "
        f"On the severe-pathology day (2026-05-11) the inter-rep Jaccard "
        f"averages **{statistics.mean(irj_pathology_means):.3f}** across temperatures; "
        f"on the clean day (2026-05-08) it averages "
        f"**{statistics.mean(irj_clean_means):.3f}**. "
        f"The temperature axis is reported per cell in §3 — see the "
        f"per-date tables for whether moving from t=0.5 to t=1.0 changes "
        f"top-cluster size or off-topic % at the means."
    )
    L.append("")

    # 7. Open items
    L.append("## 7. Open items")
    L.append("")
    failed_cells = []
    for cell_key, cell in cells.items():
        for r in cell["reps"]:
            if r.get("status") != "ok":
                failed_cells.append(f"- `{cell_key}/rep-{r['rep']}`: {r.get('error')}")
    if failed_cells:
        L.append("**Failed calls:**")
        L.extend(failed_cells)
    else:
        L.append("- No failed calls.")
    truncation = []
    for cell in cells.values():
        for r in cell["reps"]:
            if r.get("status") != "ok":
                continue
            # We can't see finish_reason here without re-reading rep files;
            # surface only the no-cluster cases captured in the metric.
            if r["metrics"]["n_clusters"] == 0:
                truncation.append(
                    f"- `{cell['date']}/{cell['config']}/rep-{r['rep']}`: 0 clusters produced "
                    f"(possible truncation or empty content)"
                )
    if truncation:
        L.append("")
        L.append("**Empty-output / truncation events:**")
        L.extend(truncation)
    L.append("")

    # 8. Recommendation
    L.append("## 8. Recommendation")
    L.append("")
    rec = _build_recommendation(cells, prod)
    L.append(rec["text"])
    L.append("")
    L.append(f"**Verdict tag (for commit-message subject):** `{rec['tag']}`")
    L.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(L), encoding="utf-8")
    logger.info("Report written: %s", REPORT_PATH)


def _build_recommendation(cells: dict, prod: dict) -> dict:
    """Decision-grade recommendation. Compares V4-Pro means against
    production-Gemini per date and inter-rep Jaccard against a
    reproducibility threshold."""
    # Reproducibility threshold: 0.40 inter-rep Jaccard mean is "comparable"
    # at temperature ≥ 0.7 (stochastic regimes never hit 1.0).
    REPRO_OK = 0.40

    cell_irj = {k: c["inter_rep_jaccard"]["mean"] for k, c in cells.items()}
    overall_irj = statistics.mean(cell_irj.values())

    # Per-temp: average across the three dates
    per_temp_irj: dict[str, float] = {}
    per_temp_off: dict[str, float] = {}
    per_temp_top: dict[str, float] = {}
    for config_label in CONFIGS:
        irjs = [cells[f"{d}/{config_label}"]["inter_rep_jaccard"]["mean"] for d in DATES]
        offs = [
            cells[f"{d}/{config_label}"]["summary"]["top_cluster_off_topic_pct"]["mean"]
            for d in DATES
        ]
        tops = [
            cells[f"{d}/{config_label}"]["summary"]["top_cluster_size"]["mean"]
            for d in DATES
        ]
        per_temp_irj[config_label] = statistics.mean(irjs)
        per_temp_off[config_label] = statistics.mean(o for o in offs if o is not None)
        per_temp_top[config_label] = statistics.mean(t for t in tops if t is not None)

    best_temp_label = min(per_temp_off, key=per_temp_off.get)
    best_temp = CONFIGS[best_temp_label]["temperature"]
    best_irj = per_temp_irj[best_temp_label]
    best_off = per_temp_off[best_temp_label]
    best_top = per_temp_top[best_temp_label]

    # Production reference: mean off% across the 3 dates
    prod_off_mean = statistics.mean(prod[d]["top_cluster_off_topic_pct"] for d in DATES)
    prod_top_mean = statistics.mean(prod[d]["top_cluster_size"] for d in DATES)

    pieces: list[str] = []
    if overall_irj < REPRO_OK:
        pieces.append(
            f"V4-Pro inter-rep Jaccard averages **{overall_irj:.3f}** "
            f"across cells — below the reproducibility floor of "
            f"{REPRO_OK:.2f}. Three identical runs at the same temperature "
            f"produce visibly different top clusters."
        )
        verdict = "INCONCLUSIVE"
        tag = "inconclusive — V4-Pro not reproducible enough to recommend a swap"
        decision_line = (
            "**Recommendation:** Keep production Gemini-temp=1.0. The "
            "variance signal disqualifies V4-Pro as a drop-in replacement "
            "at this audit's matrix sizing."
        )
    elif best_off < prod_off_mean - 5.0:
        verdict = "SWAP"
        tag = f"swap to V4-Pro-temp-{best_temp}"
        decision_line = (
            f"**Recommendation:** Swap production Curator to "
            f"`deepseek-v4-pro` at temperature **{best_temp}** "
            f"(`{best_temp_label}`). Inter-rep Jaccard mean "
            f"{best_irj:.3f}; top off% mean {best_off:.2f}% vs production "
            f"Gemini-temp=1.0's {prod_off_mean:.2f}% across the three dates. "
            f"Run a 3-day production swap with the existing curator monitor "
            f"watching GREEN/AMBER/RED before considering the swap permanent."
        )
    else:
        verdict = "KEEP"
        tag = "keep production Gemini-temp-1.0"
        decision_line = (
            "**Recommendation:** Keep production Gemini-temp=1.0. V4-Pro "
            "is reproducible enough but does not improve top off% by a "
            "margin that justifies the swap, given the production stack's "
            "operational maturity."
        )
    pieces.append(
        f"Best V4-Pro temperature by mean off%: **t={best_temp}** — "
        f"top {best_top:.0f}, off {best_off:.2f}%, inter-rep Jaccard "
        f"{best_irj:.3f}. Production-Gemini-temp=1.0 mean across the same "
        f"three dates: top {prod_top_mean:.0f}, off {prod_off_mean:.2f}%."
    )
    pieces.append(decision_line)
    return {"text": " ".join(pieces), "tag": tag, "verdict": verdict}


# ── CLI entry ────────────────────────────────────────────────────────────
async def amain() -> int:
    call_records, run_meta, halt_reason = await run_matrix()
    aggregate = build_aggregate(call_records, run_meta)

    agg_path = OUTPUT_DIR / "_aggregate.json"
    agg_path.write_text(
        json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Aggregate written: %s", agg_path)

    write_report(aggregate, halt_reason)

    succeeded = aggregate["totals"]["succeeded"]
    logger.info(
        "DONE: %d/27 succeeded, cost $%.4f, halt=%s",
        succeeded, aggregate["totals"]["cumulative_cost_usd"], halt_reason,
    )
    return 0 if halt_reason == "complete" else 1


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
