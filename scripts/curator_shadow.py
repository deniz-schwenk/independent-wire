#!/usr/bin/env python3
"""DeepSeek-V4-Flash direct-API shadow runs for Curator validation.

Reads today's production ``curator_findings`` from disk, re-runs the
Curator stage with two DeepSeek-V4-Flash variants (A: temperature=0.7
+ thinking-mode high, B: temperature=0.5 non-thinking), and writes a
side-by-side comparison report against the production Gemini run and
the V1 2026-05-11 pathology baseline.

Connections go **direct to https://api.deepseek.com** (not through
OpenRouter). The audit's DeepSeek variants ran through OpenRouter and
were routed to Parasail/AtlasCloud; this shadow measures the
production-target endpoint.

CLI::

    python scripts/curator_shadow.py [--date YYYY-MM-DD]

Defaults: ``--date`` = today (UTC).

Outputs:
    output/curator-shadow/{date}/A.json + B.json   (gitignored)
    output/curator-shadow/_cumulative.json         (gitignored)
    docs/curator-shadow/{date}.md                  (committed)
    docs/curator-shadow/_decision.md               (committed, after 3 days)

Cost budget: hard cap $1.00 cumulative across the 3-day study. If a
single variant exceeds $0.15, a warning is logged. If the cumulative
cap is reached, the script halts before launching the next variant.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent, AgentResult  # noqa: E402
from src.agent_stages import (  # noqa: E402
    _enrich_curator_output,
    _prepare_curator_input,
    _rebuild_curator_source_ids,
)
from src.curator_metrics import compute_metrics  # noqa: E402

logger = logging.getLogger("curator_shadow")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

AGENTS_DIR = ROOT / "agents"
DEEPSEEK_KEY_PATH = Path("/Users/denizschwenk/Desktop/deepseek_api.txt")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
SHADOW_DIR = ROOT / "output" / "curator-shadow"
REPORT_DIR = ROOT / "docs" / "curator-shadow"
CUMULATIVE_PATH = SHADOW_DIR / "_cumulative.json"
AUDIT_DIR = ROOT / "output" / "eval" / "curator-2026-05-11"

COST_CAP_USD = 1.00
PER_VARIANT_WARN_USD = 0.15

# DeepSeek-V4-Flash pricing (per DeepSeek's pricing page, January 2026).
# Used to compute cost_usd locally because the direct API's `usage` payload
# does not include a cost field (OpenRouter does; DeepSeek-direct does not).
# Treat the numbers as approximations — surface them in the report so the
# Architect knows they are computed, not provider-reported.
DEEPSEEK_PRICE_INPUT_MISS_PER_M = 0.07
DEEPSEEK_PRICE_INPUT_CACHED_PER_M = 0.014
DEEPSEEK_PRICE_OUTPUT_PER_M = 0.56  # incl reasoning tokens (thinking mode)

# Variant configs — mirror audit's dskflash-t-07-r-high and
# dskflash-t-05-r-none, translated to DeepSeek-direct native syntax.
# Provider-specific knobs (thinking.type, reasoning_effort) ride on
# extra_body_override; agent code does not auto-inject reasoning for
# provider="deepseek".
VARIANTS = {
    "A": {
        "label": "dskflash-t07-thinking-high",
        "audit_ref": "dskflash-t-07-r-high",
        "model": "deepseek-v4-flash",
        "temperature": 0.7,
        "max_tokens": 64000,
        "extra_body": {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "response_format": {"type": "json_object"},
        },
    },
    "B": {
        "label": "dskflash-t05-non-thinking",
        "audit_ref": "dskflash-t-05-r-none",
        "model": "deepseek-v4-flash",
        "temperature": 0.5,
        "max_tokens": 32000,
        "extra_body": {
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        },
    },
}

CURATOR_MESSAGE = (
    "Review these findings. Cluster related findings into topics. "
    "Score each topic's newsworthiness on a 1-10 scale."
)


# ── API-key + paths ──────────────────────────────────────────────────────
def load_deepseek_api_key(path: Path = DEEPSEEK_KEY_PATH) -> str:
    """Load and strip the DeepSeek API key. Fails loudly if the file is
    missing or empty."""
    if not path.exists():
        raise FileNotFoundError(f"DeepSeek API key file not found: {path}")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError(f"DeepSeek API key file is empty: {path}")
    return key


def find_state_for_date(date_str: str) -> Optional[Path]:
    """Locate ``output/{date}/_state/run-*/run_bus.CuratorStage.json``."""
    base = ROOT / "output" / date_str / "_state"
    if not base.exists():
        return None
    candidates = list(base.glob("run-*/run_bus.CuratorStage.json"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


# ── Cumulative cost tracker ──────────────────────────────────────────────
def load_cumulative() -> dict:
    if CUMULATIVE_PATH.exists():
        try:
            return json.loads(CUMULATIVE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"total_cost_usd": 0.0, "per_day": {}, "per_variant_per_day": {}}


def save_cumulative(cum: dict) -> None:
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    CUMULATIVE_PATH.write_text(
        json.dumps(cum, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Streaming DeepSeek-direct path ───────────────────────────────────────
# Non-streaming POST to /chat/completions is closed by DeepSeek's server
# at ~60s on payloads that take longer to fully generate (observed wall
# 61.7s with RemoteProtocolError on Curator's 1201-finding payload).
# Streaming SSE keeps the connection alive as chunks arrive incrementally.
# See https://api-docs.deepseek.com/guides/json_mode "API may occasionally
# return empty content" — same root issue surfaces as both retry-storms and
# the connection-cut behaviour. Brief allowed a self-contained
# DeepSeekDirectClient path inside the shadow script as an escape hatch
# when src/agent.py extension would grow too large; this is that path.


@dataclass
class _StreamResult:
    content: str
    reasoning_content: str
    finish_reason: str
    response_id: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    cost_usd: float
    chunks_seen: int


def _estimate_cost(prompt_uncached: int, prompt_cached: int, output: int) -> float:
    return round(
        (
            prompt_uncached * DEEPSEEK_PRICE_INPUT_MISS_PER_M
            + prompt_cached * DEEPSEEK_PRICE_INPUT_CACHED_PER_M
            + output * DEEPSEEK_PRICE_OUTPUT_PER_M
        ) / 1_000_000.0,
        6,
    )


async def _stream_chat(
    api_key: str,
    body: dict,
    log_label: str,
    http_read_timeout_seconds: float = 1800.0,
) -> _StreamResult:
    """POST to DeepSeek's chat-completions endpoint with stream=True,
    accumulate content/reasoning chunks, return a _StreamResult.

    Empty content is a known DeepSeek failure mode under json_object
    mode; an empty content_buffer at [DONE] does NOT raise — the
    caller surfaces it as zero-cluster output through the same
    parser path it would for a malformed response. Returns the usage
    block when one is sent in the trailing SSE event."""
    body = {**body, "stream": True}
    content_buf: list[str] = []
    reasoning_buf: list[str] = []
    usage: dict = {}
    finish: str = ""
    response_id: str = ""
    n_chunks = 0
    t0 = time.monotonic()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=30.0, read=http_read_timeout_seconds, write=60.0, pool=60.0,
        )
    ) as client:
        async with client.stream(
            "POST",
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as response:
            if response.status_code != 200:
                err_body = await response.aread()
                raise httpx.HTTPStatusError(
                    f"DeepSeek-direct returned HTTP {response.status_code}: "
                    f"{err_body[:500]!r}",
                    request=response.request, response=response,
                )
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                n_chunks += 1
                if chunk.get("id") and not response_id:
                    response_id = chunk["id"]
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choice = (chunk.get("choices") or [{}])[0]
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}
                if isinstance(delta.get("content"), str) and delta["content"]:
                    content_buf.append(delta["content"])
                if (
                    isinstance(delta.get("reasoning_content"), str)
                    and delta["reasoning_content"]
                ):
                    reasoning_buf.append(delta["reasoning_content"])
                if n_chunks % 2000 == 0:
                    elapsed = time.monotonic() - t0
                    logger.info(
                        "%s stream: chunk=%d wall=%.0fs content=%d reasoning=%d",
                        log_label, n_chunks, elapsed,
                        sum(len(c) for c in content_buf),
                        sum(len(c) for c in reasoning_buf),
                    )

    content = "".join(content_buf)
    reasoning = "".join(reasoning_buf)
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    reasoning_tokens = (
        (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
    )
    cached = usage.get("prompt_cache_hit_tokens", 0) or 0
    uncached = max(0, prompt_tokens - cached)
    return _StreamResult(
        content=content,
        reasoning_content=reasoning,
        finish_reason=finish or "stop",
        response_id=response_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_tokens=cached,
        cost_usd=_estimate_cost(uncached, cached, completion_tokens),
        chunks_seen=n_chunks,
    )


# ── Variant runner ───────────────────────────────────────────────────────
async def run_variant(
    variant_key: str,
    raw_findings: list[dict],
    api_key: str,
) -> dict:
    """Run a single shadow variant via DeepSeek-direct streaming and
    return a payload dict (variant_key + metrics + cost + tokens +
    provider metadata).

    Errors are caught and surfaced in ``status``/``error`` fields; the
    caller continues to the next variant.

    Uses the Agent class only to build the SYSTEM and User messages —
    the HTTP call goes through ``_stream_chat`` (streaming SSE) rather
    than ``agent.run()`` because DeepSeek's server closes non-streaming
    connections at ~60s for long-running thinking-mode completions.
    """
    cfg = VARIANTS[variant_key]
    label = cfg["label"]

    # Build message + system prompt via the Agent helpers so the shadow
    # uses the exact same prompt shape as production. The Agent itself
    # is never asked to call .run() — its API key is unused; pass a
    # placeholder so the constructor doesn't reject us.
    agent = Agent(
        name=f"curator_shadow_{variant_key.lower()}",
        model=cfg["model"],
        system_prompt_path=str(AGENTS_DIR / "curator" / "SYSTEM.md"),
        instructions_path=str(AGENTS_DIR / "curator" / "INSTRUCTIONS.md"),
        tools=[],
        temperature=cfg["temperature"],
        provider="deepseek",
        api_key=api_key,
        max_tokens=cfg["max_tokens"],
        extra_body_override=cfg["extra_body"],
    )

    prepared = _prepare_curator_input(raw_findings)
    system_prompt = agent._build_system_prompt()
    user_message = agent._build_user_message(
        message=CURATOR_MESSAGE, context={"findings": prepared},
    )
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
        **cfg["extra_body"],
    }

    start = time.monotonic()
    try:
        stream = await _stream_chat(api_key, body, log_label=f"variant {variant_key}")
    except Exception as exc:  # noqa: BLE001 — surface anything DeepSeek raises
        wall = time.monotonic() - start
        logger.exception("variant %s failed: %s", variant_key, exc)
        return {
            "variant": variant_key,
            "label": label,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "wall_seconds": round(wall, 2),
            "cost_usd": 0.0,
            "tokens_used": 0,
        }
    wall = time.monotonic() - start

    # Build an AgentResult-shaped object so _rebuild_curator_source_ids
    # works unchanged (it reads .content and falls back to JSON parse).
    result = AgentResult(
        content=stream.content,
        structured=None,
        tool_calls=[],
        tokens_used=stream.prompt_tokens + stream.completion_tokens,
        cost_usd=stream.cost_usd,
        model=cfg["model"],
        duration_seconds=round(wall, 2),
        provider="deepseek-direct",
        response_id=stream.response_id,
    )

    topics = _rebuild_curator_source_ids(result, raw_findings)
    topics = _enrich_curator_output(topics, raw_findings, sources_json_path=None)

    state_like = {
        "curator_findings": raw_findings,
        "curator_topics_unsliced": topics,
    }
    metrics = compute_metrics(state_like)
    off_topic_titles = _sample_off_topic_titles_from_top_cluster(
        topics, raw_findings, metrics,
    )

    payload = {
        "variant": variant_key,
        "label": label,
        "status": "ok",
        "model": cfg["model"],
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
        "extra_body": cfg["extra_body"],
        "wall_seconds": round(wall, 2),
        "tokens_used": result.tokens_used,
        "completion_tokens": stream.completion_tokens,
        "reasoning_tokens": stream.reasoning_tokens,
        "cached_input_tokens": stream.cached_tokens,
        "cost_usd_estimated": stream.cost_usd,
        "cost_usd": stream.cost_usd,
        "cost_source": "computed-from-tokens (DeepSeek-direct does not return usage.cost)",
        "provider_served": result.provider,
        "response_id": result.response_id,
        "finish_reason": stream.finish_reason,
        "chunks_seen": stream.chunks_seen,
        "raw_content_len": len(result.content or ""),
        "raw_reasoning_len": len(stream.reasoning_content or ""),
        "metrics": metrics,
        "off_topic_sample_titles": off_topic_titles,
        "curator_topics_unsliced": topics,
        "audit_ref": cfg["audit_ref"],
    }
    if stream.cost_usd > PER_VARIANT_WARN_USD:
        logger.warning(
            "variant %s cost $%.4f exceeds per-variant warn threshold $%.2f",
            variant_key, stream.cost_usd, PER_VARIANT_WARN_USD,
        )
    return payload


# ── Audit reference loader ───────────────────────────────────────────────
def load_audit_reference(variant_key: str) -> Optional[dict]:
    """Return audit metrics for the variant's audit_ref label, or None
    if the file is missing. Audit metrics come from
    ``output/eval/curator-2026-05-11/_metrics.json``."""
    ref_label = VARIANTS[variant_key]["audit_ref"]
    metrics_path = AUDIT_DIR / "_metrics.json"
    if not metrics_path.exists():
        return None
    try:
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    for m in data.get("metrics", []):
        if m.get("label") == ref_label and m.get("status") == "ok":
            return m
    return None


# ── Markdown report ──────────────────────────────────────────────────────
def _fmt_pct(v) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "n/a"


def render_markdown(
    date_str: str,
    prod_metrics: dict,
    variant_payloads: dict[str, dict],
    pathology: dict,
    raw_findings: Optional[list[dict]] = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# Curator shadow — {date_str}\n")
    lines.append(
        "Direct-API DeepSeek-V4-Flash shadow runs for the production-target\n"
        "endpoint comparison. Re-runs today's production `curator_findings`\n"
        "through two DeepSeek-direct variants and compares against the\n"
        "Gemini production run + the V1 pathology baseline.\n"
    )

    lines.append("## Side-by-side metric table\n")
    lines.append(
        "| Metric | Production (Gemini t=1.0) | Variant A "
        "(t=0.7 thinking high) | Variant B (t=0.5 non-thinking) | "
        "Pathology baseline |"
    )
    lines.append("|---|---:|---:|---:|---:|")

    def _row(name: str, key: str, fmt=lambda v: str(v) if v is not None else "n/a") -> str:
        prod = prod_metrics.get(key)
        a = variant_payloads.get("A", {}).get("metrics", {}).get(key)
        b = variant_payloads.get("B", {}).get("metrics", {}).get(key)
        bl = pathology.get(key)
        return (
            f"| {name} | {fmt(prod)} | "
            f"{fmt(a) if variant_payloads.get('A', {}).get('status') == 'ok' else 'ERROR'} | "
            f"{fmt(b) if variant_payloads.get('B', {}).get('status') == 'ok' else 'ERROR'} | "
            f"{fmt(bl)} |"
        )

    lines.append(_row("n_findings_total", "n_findings_total"))
    lines.append(_row("n_clusters", "n_clusters"))
    lines.append(_row("top_cluster_size", "top_cluster_size"))
    lines.append(_row("top_cluster_off_topic_pct", "top_cluster_off_topic_pct", _fmt_pct))
    lines.append(_row("orphan_rate", "orphan_rate", _fmt_pct))
    lines.append(_row("cluster_size_p90", "cluster_size_p90"))
    lines.append("")

    # Cost line
    cost_a = variant_payloads.get("A", {}).get("cost_usd") or 0.0
    cost_b = variant_payloads.get("B", {}).get("cost_usd") or 0.0
    wall_a = variant_payloads.get("A", {}).get("wall_seconds") or 0
    wall_b = variant_payloads.get("B", {}).get("wall_seconds") or 0
    lines.append("## Cost + wall\n")
    lines.append(
        f"- Variant A: ${cost_a:.4f}, wall {wall_a:.1f}s, "
        f"provider={variant_payloads.get('A', {}).get('provider_served') or '?'}"
    )
    lines.append(
        f"- Variant B: ${cost_b:.4f}, wall {wall_b:.1f}s, "
        f"provider={variant_payloads.get('B', {}).get('provider_served') or '?'}"
    )
    lines.append(f"- Total today: ${cost_a + cost_b:.4f}")
    lines.append("")

    # Observation
    lines.append("## Observation\n")
    obs = _compose_observation(prod_metrics, variant_payloads, pathology)
    for o in obs:
        lines.append(f"- {o}")
    lines.append("")

    # Per-variant detail
    for vkey in ("A", "B"):
        p = variant_payloads.get(vkey, {})
        cfg = VARIANTS[vkey]
        lines.append(f"## Variant {vkey} — {cfg['label']}\n")
        if p.get("status") != "ok":
            lines.append(f"_Status: {p.get('status', 'missing')}_  ")
            err = p.get("error")
            if err:
                lines.append(f"_Error: `{err}`_  ")
            lines.append("")
            continue
        m = p.get("metrics") or {}
        lines.append(f"- Top cluster title: \"{m.get('top_cluster_title', '')}\"")
        tokens = m.get("on_topic_regex_tokens") or []
        if tokens:
            preview = "|".join(tokens[:15])
            suffix = f"  *(and {len(tokens) - 15} more)*" if len(tokens) > 15 else ""
            lines.append(
                f"- On-topic regex (derived, {len(tokens)} tokens): "
                f"`\\b({preview})\\b`{suffix}"
            )
        else:
            lines.append("- On-topic regex: _no usable tokens_")
        samples = _sample_off_topic_titles(p)
        if not samples and raw_findings is not None:
            # Backfill on the fly for payloads written before we cached
            # off-topic samples in the variant JSON (day-1 gap).
            samples = _sample_off_topic_titles_from_top_cluster(
                p.get("curator_topics_unsliced") or [], raw_findings,
                p.get("metrics") or {},
            )
        if samples:
            lines.append("- 5 random off-topic-flagged titles:")
            for s in samples:
                lines.append(f"  - {s}")
        # Audit reference for variance check
        ref = load_audit_reference(vkey)
        if ref:
            lines.append(
                f"- Audit reference (OpenRouter via {ref.get('provider_served') or '?'}): "
                f"top={ref.get('top_cluster_size')}, off%={ref.get('top_cluster_off_topic_pct')}, "
                f"clusters={ref.get('n_topics')}"
            )
        lines.append("")

    # Temperature-honoured note (day 1: single-day signal only)
    lines.append("## Temperature-honoured smoke\n")
    lines.append(_temperature_note(variant_payloads, date_str))
    lines.append("")

    lines.append("## Heuristic notes\n")
    lines.append(
        "On-topic regex is derived per variant from that variant's own top-"
        "cluster title+summary — each variant gets self-consistency measured "
        "against its own headline. ~5-10 % FP/FN rate. Single-day signal only."
    )
    lines.append("")

    lines.append("## Cache\n")
    lines.append(
        f"- Per-variant payloads: `output/curator-shadow/{date_str}/A.json`, `B.json`"
    )
    lines.append(f"- Cumulative cost: `output/curator-shadow/_cumulative.json`")
    lines.append("")
    return "\n".join(lines)


def _sample_off_topic_titles_from_top_cluster(
    topics: list[dict],
    raw_findings: list[dict],
    metrics: dict,
    n: int = 5,
) -> list[str]:
    """Pick up to ``n`` titles from the top cluster's source_ids whose
    text does NOT match the cluster's own dynamic regex. Returns [] when
    there are no topics, no findings, or no off-topic survivors."""
    import random
    from src.curator_metrics import _is_on_topic, derive_on_topic_regex

    if not topics or not raw_findings:
        return []
    top = max(topics, key=lambda t: len(t.get("source_ids") or []))
    regex, _ = derive_on_topic_regex(
        top.get("title") or "", top.get("summary") or "",
    )
    if regex is None:
        return []
    src_ids = top.get("source_ids") or []
    off: list[str] = []
    for sid in src_ids:
        try:
            idx = int(str(sid).split("finding-")[-1])
        except (ValueError, IndexError):
            continue
        if not (0 <= idx < len(raw_findings)):
            continue
        f = raw_findings[idx]
        if not _is_on_topic(f, regex):
            t = f.get("title")
            if t:
                off.append(t)
    if not off:
        return []
    if len(off) <= n:
        return off
    random.seed(42)
    return random.sample(off, n)


def _sample_off_topic_titles(payload: dict, n: int = 5) -> list[str]:
    """Pre-computed sample stored on the payload by run_variant. Falls
    back to empty list when status != ok or the field is missing."""
    if payload.get("status") != "ok":
        return []
    return list(payload.get("off_topic_sample_titles") or [])[:n]


def _compose_observation(
    prod: dict, variants: dict[str, dict], pathology: dict,
) -> list[str]:
    """One-paragraph-equivalent bullet list summarising which variant
    looked best on this day, on which dimensions."""
    notes: list[str] = []
    pa = variants.get("A", {})
    pb = variants.get("B", {})

    if pa.get("status") != "ok" and pb.get("status") != "ok":
        notes.append(
            "Both shadow variants errored; production Gemini is the only "
            "comparable data point today. See per-variant error rows."
        )
        return notes
    if pa.get("status") != "ok":
        notes.append(f"Variant A errored: `{pa.get('error', '?')}`")
    if pb.get("status") != "ok":
        notes.append(f"Variant B errored: `{pb.get('error', '?')}`")

    candidates = []
    for k, v in (("A", pa), ("B", pb)):
        if v.get("status") == "ok":
            m = v.get("metrics") or {}
            candidates.append((k, m.get("top_cluster_off_topic_pct", 100.0), m))
    if candidates:
        candidates.sort(key=lambda x: x[1])
        best_key, best_off, best_m = candidates[0]
        notes.append(
            f"Best off-topic %: variant {best_key} at {best_off:.2f} % "
            f"(top_cluster_size={best_m.get('top_cluster_size')}, "
            f"n_clusters={best_m.get('n_clusters')})"
        )

    prod_top = prod.get("top_cluster_size") or 0
    if prod_top >= 500:
        notes.append(
            f"Production Gemini run shows pathology shape today "
            f"(top_cluster_size={prod_top}) — both shadow variants for direct "
            f"comparison."
        )
    elif prod_top:
        notes.append(
            f"Production Gemini run looks normal (top_cluster_size={prod_top}, "
            f"off%={prod.get('top_cluster_off_topic_pct')})."
        )
    return notes


def _temperature_note(variant_payloads: dict[str, dict], date_str: str) -> str:
    """Note on whether variant-A temperature appears to be honoured. The
    full variance check needs ≥2 days of data; on day 1 we cite the
    audit reference."""
    pa = variant_payloads.get("A", {})
    ref = load_audit_reference("A")
    if pa.get("status") != "ok":
        return (
            "Variant A errored; cannot assess temperature-honoured signal "
            "from this day."
        )
    today_m = pa.get("metrics") or {}
    today_top = today_m.get("top_cluster_size") or 0
    today_off = today_m.get("top_cluster_off_topic_pct") or 0.0
    if not ref:
        return (
            f"Single-day shadow at temp=0.7 thinking-mode-high: "
            f"top={today_top}, off%={today_off:.2f}. No audit reference "
            "available for comparison; surface variance after ≥2 days."
        )
    ref_top = ref.get("top_cluster_size") or 0
    ref_off = ref.get("top_cluster_off_topic_pct") or 0
    delta_top = today_top - ref_top
    delta_off = today_off - ref_off
    return (
        f"Single-day shadow at temp=0.7 thinking-mode-high: "
        f"top={today_top} (audit={ref_top}, Δ={delta_top:+d}), "
        f"off%={today_off:.2f} (audit={ref_off:.2f}, Δ={delta_off:+.2f}). "
        f"Day-to-day variance check requires ≥2 days; if A's numbers "
        f"are essentially identical across all 3 days, that would "
        f"suggest temperature is NOT being honoured (the legacy "
        f"`/guides/thinking_mode` note would then still apply)."
    )


# ── Decision summary (day 3) ─────────────────────────────────────────────
def aggregate_three_day_decision() -> Optional[str]:
    """If 3 dated reports exist under docs/curator-shadow/{date}.md
    with corresponding output/curator-shadow/{date}/{A,B}.json, produce
    a decision summary and return its markdown body. Otherwise return
    None.

    The decision recommends one of: keep production / swap to A / swap
    to B / inconclusive. Decision rule: variant wins if it beats
    production on top_cluster_off_topic_pct on ≥2 of 3 days AND its
    median top_cluster_size is < production's top_cluster_size median.
    Otherwise the recommendation is to keep production (or 'inconclusive'
    if the data is too noisy).
    """
    if not SHADOW_DIR.exists():
        return None
    day_dirs = sorted(
        [d for d in SHADOW_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")]
    )
    if len(day_dirs) < 3:
        return None

    rows: list[dict] = []
    for d in day_dirs[:3]:
        date_str = d.name
        prod_state = find_state_for_date(date_str)
        if prod_state is None:
            continue
        prod_metrics = compute_metrics(json.loads(prod_state.read_text(encoding="utf-8")))
        a_path = d / "A.json"
        b_path = d / "B.json"
        if not a_path.exists() or not b_path.exists():
            continue
        a = json.loads(a_path.read_text(encoding="utf-8"))
        b = json.loads(b_path.read_text(encoding="utf-8"))
        rows.append({
            "date": date_str,
            "prod": prod_metrics,
            "A": a,
            "B": b,
        })
    if len(rows) < 3:
        return None

    def med(xs: list[float]) -> float:
        if not xs:
            return float("nan")
        s = sorted(xs)
        return s[len(s) // 2]

    prod_off = [r["prod"]["top_cluster_off_topic_pct"] for r in rows]
    prod_top = [r["prod"]["top_cluster_size"] for r in rows]

    def variant_summary(key: str) -> tuple[list[float], list[float], int]:
        offs, tops, wins = [], [], 0
        for r in rows:
            v = r[key]
            if v.get("status") != "ok":
                offs.append(float("nan"))
                tops.append(float("nan"))
                continue
            m = v.get("metrics") or {}
            o = m.get("top_cluster_off_topic_pct") or 0.0
            t = m.get("top_cluster_size") or 0
            offs.append(o)
            tops.append(t)
            if o < r["prod"]["top_cluster_off_topic_pct"]:
                wins += 1
        return offs, tops, wins

    a_off, a_top, a_wins = variant_summary("A")
    b_off, b_top, b_wins = variant_summary("B")

    # Decision rule
    def beats(off_wins: int, top_med: float) -> bool:
        return off_wins >= 2 and top_med < med(prod_top)

    def safe_med(xs):
        cleaned = [x for x in xs if isinstance(x, (int, float)) and x == x]  # drop NaN
        return med(cleaned)

    a_passes = beats(a_wins, safe_med(a_top))
    b_passes = beats(b_wins, safe_med(b_top))

    if a_passes and not b_passes:
        verdict = "swap-to-A"
        rationale = (
            f"Variant A beat production on off_topic_% on {a_wins}/3 days "
            f"with median top_cluster_size={safe_med(a_top):.0f} vs "
            f"production median {med(prod_top):.0f}."
        )
    elif b_passes and not a_passes:
        verdict = "swap-to-B"
        rationale = (
            f"Variant B beat production on off_topic_% on {b_wins}/3 days "
            f"with median top_cluster_size={safe_med(b_top):.0f} vs "
            f"production median {med(prod_top):.0f}."
        )
    elif a_passes and b_passes:
        # Tiebreak: pick the lower off_topic_pct median
        a_med = safe_med(a_off)
        b_med = safe_med(b_off)
        if a_med < b_med:
            verdict = "swap-to-A"
            rationale = (
                f"Both A and B beat production; A has lower off_topic_% median "
                f"({a_med:.2f} vs {b_med:.2f})."
            )
        else:
            verdict = "swap-to-B"
            rationale = (
                f"Both A and B beat production; B has lower off_topic_% median "
                f"({b_med:.2f} vs {a_med:.2f})."
            )
    else:
        # Neither beat. If production is at pathology, recommend inconclusive
        # (data isn't strong enough to swap, but production may need fixing).
        # Otherwise: keep production.
        if all(p >= 500 for p in prod_top):
            verdict = "inconclusive"
            rationale = (
                "Production is in pathology shape across all 3 days but "
                "neither variant cleanly beats it on the decision rule. "
                "Need a different intervention (different variant, prompt "
                "change, or upstream filter)."
            )
        else:
            verdict = "keep-Gemini-temp-1.0"
            rationale = (
                f"Neither variant cleanly beats production on the decision "
                f"rule (A wins {a_wins}/3 days, B wins {b_wins}/3 days). "
                f"Production median top_cluster_size={med(prod_top):.0f}, "
                f"off%_median={med(prod_off):.2f}."
            )

    lines: list[str] = []
    lines.append("# Curator shadow — 3-day decision\n")
    lines.append(f"**Recommendation: `{verdict}`**\n")
    lines.append(f"_Rationale: {rationale}_\n")
    lines.append("## 3-day aggregate table\n")
    lines.append("| Date | Production (off% / top) | Variant A | Variant B |")
    lines.append("|---|---:|---:|---:|")
    for r in rows:
        prod_o = r["prod"]["top_cluster_off_topic_pct"]
        prod_t = r["prod"]["top_cluster_size"]
        a_v = r["A"]
        b_v = r["B"]
        a_cell = (
            f"{a_v['metrics']['top_cluster_off_topic_pct']:.2f} / "
            f"{a_v['metrics']['top_cluster_size']}"
            if a_v.get("status") == "ok"
            else "ERROR"
        )
        b_cell = (
            f"{b_v['metrics']['top_cluster_off_topic_pct']:.2f} / "
            f"{b_v['metrics']['top_cluster_size']}"
            if b_v.get("status") == "ok"
            else "ERROR"
        )
        lines.append(f"| {r['date']} | {prod_o:.2f} / {prod_t} | {a_cell} | {b_cell} |")
    lines.append("")

    # Temperature-honoured cross-day analysis
    a_top_obs = [x for x in a_top if x == x]  # drop NaN
    if len(a_top_obs) >= 2:
        spread = max(a_top_obs) - min(a_top_obs)
        lines.append("## Temperature-honoured cross-day check\n")
        if spread <= 2:
            lines.append(
                f"- Variant A top_cluster_size is essentially constant "
                f"across days (spread={spread:.0f}). This is suggestive that "
                f"temperature may NOT be honoured at DeepSeek-direct in "
                f"thinking mode for `deepseek-v4-flash` — the legacy "
                f"`/guides/thinking_mode` note may still apply."
            )
        else:
            lines.append(
                f"- Variant A top_cluster_size varies across days "
                f"(spread={spread:.0f}). Temperature appears to be honoured."
            )
        lines.append("")

    lines.append("## Cumulative cost\n")
    cum = load_cumulative()
    lines.append(f"- Total across all shadow runs: ${cum.get('total_cost_usd', 0):.4f}")
    lines.append(f"- Cap: ${COST_CAP_USD:.2f}")
    lines.append("")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────
async def amain(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="DeepSeek-V4-Flash direct-API shadow runs for Curator validation."
    )
    p.add_argument("--date", default=None,
                   help="Run date (YYYY-MM-DD). Default: today (UTC).")
    args = p.parse_args(argv)

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Cost cap admission
    cum = load_cumulative()
    if cum.get("total_cost_usd", 0) >= COST_CAP_USD:
        logger.error(
            "cumulative cap $%.2f already reached (running total $%.4f); halting",
            COST_CAP_USD, cum["total_cost_usd"],
        )
        return 2

    # Locate production state
    prod_state_path = find_state_for_date(date_str)
    if prod_state_path is None:
        logger.error(
            "no CuratorStage state for %s under output/%s/_state/run-*/run_bus.CuratorStage.json",
            date_str, date_str,
        )
        return 2
    logger.info("loaded production state: %s", prod_state_path)

    state = json.loads(prod_state_path.read_text(encoding="utf-8"))
    raw_findings = list(state.get("curator_findings") or [])
    if not raw_findings:
        logger.error("production state has empty curator_findings; nothing to shadow")
        return 2

    prod_metrics = compute_metrics(state)
    logger.info(
        "production today: top=%d off%%=%s clusters=%d findings=%d",
        prod_metrics["top_cluster_size"],
        prod_metrics["top_cluster_off_topic_pct"],
        prod_metrics["n_clusters"],
        prod_metrics["n_findings_total"],
    )

    api_key = load_deepseek_api_key()
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    day_dir = SHADOW_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    # Pathology baseline metrics
    pathology_state = ROOT / "output" / "2026-05-11-v1-baseline" / "_state" / \
        "run-2026-05-11-722571ae" / "run_bus.CuratorStage.json"
    if pathology_state.exists():
        pathology = compute_metrics(json.loads(pathology_state.read_text(encoding="utf-8")))
    else:
        pathology = {}

    variant_payloads: dict[str, dict] = {}
    for vkey in ("A", "B"):
        # Per-day skip-resume: if a payload exists from a prior run, reuse it.
        out_path = day_dir / f"{vkey}.json"
        if out_path.exists():
            try:
                cached = json.loads(out_path.read_text(encoding="utf-8"))
                if cached.get("status") == "ok":
                    logger.info("variant %s resumed from disk", vkey)
                    variant_payloads[vkey] = cached
                    continue
            except json.JSONDecodeError:
                pass
        # Cost cap admission per-variant
        if cum.get("total_cost_usd", 0) >= COST_CAP_USD:
            logger.error("cap reached before variant %s; halting", vkey)
            break
        logger.info("running variant %s …", vkey)
        payload = await run_variant(vkey, raw_findings, api_key)
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        variant_payloads[vkey] = payload
        if payload.get("status") == "ok":
            cum["total_cost_usd"] = round(
                cum.get("total_cost_usd", 0) + (payload.get("cost_usd") or 0), 6,
            )
            cum.setdefault("per_day", {})[date_str] = round(
                cum["per_day"].get(date_str, 0) + (payload.get("cost_usd") or 0), 6,
            )
            cum.setdefault("per_variant_per_day", {}).setdefault(date_str, {})[vkey] = \
                payload.get("cost_usd") or 0
            save_cumulative(cum)

    # Render report
    md = render_markdown(
        date_str, prod_metrics, variant_payloads, pathology,
        raw_findings=raw_findings,
    )
    report_path = REPORT_DIR / f"{date_str}.md"
    report_path.write_text(md, encoding="utf-8")
    logger.info("report written: %s", report_path)

    # Stdout one-liner
    a_ok = variant_payloads.get("A", {}).get("status") == "ok"
    b_ok = variant_payloads.get("B", {}).get("status") == "ok"
    a_top = variant_payloads.get("A", {}).get("metrics", {}).get("top_cluster_size", "?")
    b_top = variant_payloads.get("B", {}).get("metrics", {}).get("top_cluster_size", "?")
    a_off = variant_payloads.get("A", {}).get("metrics", {}).get("top_cluster_off_topic_pct", "?")
    b_off = variant_payloads.get("B", {}).get("metrics", {}).get("top_cluster_off_topic_pct", "?")
    print(
        f"{date_str}  curator shadow  prod_top={prod_metrics['top_cluster_size']} "
        f"prod_off%={prod_metrics['top_cluster_off_topic_pct']}  "
        f"A={'OK' if a_ok else 'ERR'}(top={a_top}, off%={a_off})  "
        f"B={'OK' if b_ok else 'ERR'}(top={b_top}, off%={b_off})  "
        f"cum=${cum.get('total_cost_usd', 0):.4f}"
    )

    # Day-3 decision if available
    decision_md = aggregate_three_day_decision()
    if decision_md is not None:
        (REPORT_DIR / "_decision.md").write_text(decision_md, encoding="utf-8")
        logger.info("3-day decision written: %s", REPORT_DIR / "_decision.md")

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    return asyncio.run(amain(argv))


if __name__ == "__main__":
    sys.exit(main())
