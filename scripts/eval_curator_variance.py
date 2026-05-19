"""Curator topic-discovery variance smoke — 9 variants × 3 reps = 27 calls.

DeepSeek V4 Flash against the 2026-05-18 substrate (`run-2026-05-18-c26864b2`,
`run_bus.pre_cluster_findings.json`). Measures per-variant variance on
three quality dimensions:

* emission count (vs prompt spec 10-30),
* unique-theme count (post 0.85 cosine dedup using the fastembed singleton),
* text-corruption signals (four regex patterns described in `_corruption_signals`).

Each reasoning level (none / medium / high) is dispatched concurrently
via `asyncio.gather` over its 9 (3 temps × 3 reps) calls.

Streaming is mandatory for `reasoning ∈ {medium, high}` — Wave-2 Sweep #5
showed AtlasCloud can synchronously reject war / civilian-casualty content
on high-reasoning streams, and the eval harness already handles the
streaming path in `scripts/eval_common.py::call_openrouter`.

The substrate is loaded once (fastembed compression ~30 s) and the resulting
messages list is shared across all 27 calls.
"""

from __future__ import annotations

import asyncio
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.eval_common import (  # noqa: E402
    SpendingCapExceeded,
    SpendTracker,
    Variant,
    build_client,
    build_messages,
    call_openrouter,
    load_run_bus,
)
from src.agent_stages import (  # noqa: E402
    SAMPLE_TITLES_PER_CLUSTER,
    _compress_pre_clusters_to_llm_input,
    _topic_discovery_finding_text,
)
from src.schemas import CURATOR_TOPIC_DISCOVERY_SCHEMA  # noqa: E402

SWEEP_NAME = "curator_variance"
SWEEP_DIR = REPO_ROOT / "output" / "eval" / "curator-variance-2026-05-19"

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "curator" / "SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "curator" / "INSTRUCTIONS.md"

CURATOR_USER_MESSAGE = (
    "Discover today's topics from the supplied micro-clusters. "
    "Output JSON: {topics: [{title, summary}]}."
)

REPS = 3
TEMPS = [0.5, 0.7, 1.0]
REASONINGS = ["none", "medium", "high"]

DEDUP_THRESHOLD = 0.85
CAP_USD = 5.0


# ── Variant grid ─────────────────────────────────────────────────────────
def _label(temp: float, reasoning: str) -> str:
    temp_tag = f"t{int(round(temp * 10)):02d}"  # 0.5 -> t05, 1.0 -> t10
    r_tag = {"none": "rnone", "medium": "rmedium", "high": "rhigh"}[reasoning]
    return f"dskflash-{temp_tag}-{r_tag}"


def _all_variants() -> list[Variant]:
    out: list[Variant] = []
    for temp in TEMPS:
        for r in REASONINGS:
            out.append(
                Variant(
                    label=_label(temp, r),
                    model="deepseek/deepseek-v4-flash",
                    temperature=temp,
                    reasoning=r,
                    streaming=(r != "none"),
                    max_tokens=160000,
                )
            )
    return out


# ── Regex corruption patterns ────────────────────────────────────────────
REPEATED_WORD = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
"""Adjacent doubles: 'wounding wounding', 'denounced denounced'."""

REPEATED_QUOTED = re.compile(r"'([^']{3,}?)'(\1)")
"""Echoed quoted phrase, e.g. 'clock is ticking'clock is ticking'."""

HYPHEN_ED = re.compile(r"\b\w+-\w+ed\b")
"""Hyphen-mangled past-tense compound. Empty allowlist per brief — every
match is recorded as a signal. Common legitimate compounds (US-brokered,
China-linked) will appear in the count; surface them in the report rather
than silently filter."""

TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z'\-]*\b")


def _non_adjacent_stutter_count(text: str) -> int:
    """Same content word reappearing within 2-5 tokens, where the word is
    ≥ 7 chars and lowercase-initial.

    Catches the brief's `Hezbollah denounced ... were denounced` and the
    `petition against ... petition` cases without firing on legitimate
    proper-noun repetition (place / person names, capitalized entities).
    """
    tokens = TOKEN_RE.findall(text)
    seen: dict[str, int] = {}
    n = 0
    for i, tok in enumerate(tokens):
        if len(tok) < 7 or not tok[0].islower():
            continue
        low = tok.lower()
        if low in seen and 1 < (i - seen[low]) <= 5:
            n += 1
        seen[low] = i
    return n


def _corruption_signals(title: str, summary: str) -> dict[str, int]:
    body = (title or "") + "\n" + (summary or "")
    return {
        "repeated_word": len(REPEATED_WORD.findall(body)),
        "repeated_quoted": len(REPEATED_QUOTED.findall(body)),
        "hyphen_ed": len(HYPHEN_ED.findall(body)),
        "non_adjacent_stutter": _non_adjacent_stutter_count(body),
    }


# ── Cosine dedup of topics within a single call ──────────────────────────
def _unique_theme_count(topics: list[dict], embedder, threshold: float = DEDUP_THRESHOLD) -> int:
    texts = [
        (t.get("title", "") + " " + t.get("summary", "")).strip()
        for t in topics
        if isinstance(t, dict)
    ]
    texts = [t for t in texts if t]
    if not texts:
        return 0
    vecs = embedder.embed_batch(texts)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    vecs = vecs / norms
    sim = vecs @ vecs.T
    n = len(texts)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold:
                union(i, j)

    return len({find(i) for i in range(n)})


# ── Substrate (loaded once) ──────────────────────────────────────────────
def _build_messages_once() -> list[dict[str, str]]:
    sub = load_run_bus("pre_cluster_findings")
    findings = list(sub.get("curator_findings") or [])
    pre_clusters_record = sub.get("curator_pre_clusters") or {}
    pre_clusters = list(pre_clusters_record.get("clusters") or [])
    run_date = sub.get("run_date") or ""

    from src.stages.coherence import _cosine_normalized, _get_default_embedder

    emb = _get_default_embedder()
    finding_texts = [_topic_discovery_finding_text(f) for f in findings]
    finding_matrix = _cosine_normalized(emb.embed_batch(finding_texts))

    micro_clusters_input = _compress_pre_clusters_to_llm_input(
        pre_clusters,
        findings,
        finding_matrix,
        k=SAMPLE_TITLES_PER_CLUSTER,
    )

    context = {
        "run_date": run_date,
        "micro_clusters": micro_clusters_input,
    }
    return build_messages(
        system_prompt_path=SYSTEM_PROMPT_PATH,
        instructions_path=INSTRUCTIONS_PATH,
        message=CURATOR_USER_MESSAGE,
        context=context,
    )


# ── Per-call execution ───────────────────────────────────────────────────
def _output_path(label: str, rep: int) -> Path:
    return SWEEP_DIR / f"{label}-rep{rep}.json"


def _has_usable_cache(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open() as f:
            data = json.load(f)
        if data.get("error"):
            return False
        return data.get("structured") not in (None, {}, [])
    except (json.JSONDecodeError, OSError):
        return False


async def _run_one(
    client,
    variant: Variant,
    rep: int,
    messages: list[dict[str, str]],
    tracker: SpendTracker,
) -> dict[str, Any]:
    out_path = _output_path(variant.label, rep)
    if _has_usable_cache(out_path):
        with out_path.open() as f:
            cached = json.load(f)
        return cached

    try:
        content, structured, telemetry = await call_openrouter(
            client=client,
            variant=variant,
            messages=messages,
            response_format_schema=CURATOR_TOPIC_DISCOVERY_SCHEMA,
            schema_name="curator_topic_discovery_output",
            provider_order=["deepseek"],
        )
        error: str | None = None
    except Exception as e:  # noqa: BLE001 — log and continue
        content = ""
        structured = None
        telemetry = {
            "cost_usd": 0.0,
            "tokens_used": 0,
            "wall_seconds": 0.0,
            "model_served": variant.model,
            "provider_served": "",
            "response_id": "",
            "schema_valid": False,
        }
        error = f"{type(e).__name__}: {e}"

    record = {
        "label": variant.label,
        "rep": rep,
        "model_requested": variant.model,
        "model_served": telemetry["model_served"],
        "provider_served": telemetry["provider_served"],
        "response_id": telemetry["response_id"],
        "temperature": variant.temperature,
        "reasoning": variant.reasoning,
        "streaming": variant.streaming,
        "max_tokens": variant.max_tokens,
        "schema_valid": telemetry["schema_valid"],
        "cost_usd": telemetry["cost_usd"],
        "tokens_used": telemetry["tokens_used"],
        "wall_seconds": telemetry["wall_seconds"],
        "error": error,
        "content": content,
        "structured": structured,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    if error is None:
        try:
            tracker.add(f"{variant.label}-rep{rep}", record["cost_usd"])
        except SpendingCapExceeded:
            # Persist already happened; let the outer caller detect via
            # tracker.cumulative_usd. Don't break the gather.
            pass

    print(
        f"[{SWEEP_NAME}] {variant.label}-rep{rep}: "
        f"${record['cost_usd']:.4f} {record['tokens_used']}tok "
        f"{record['wall_seconds']:.1f}s valid={record['schema_valid']} err={error}"
    )
    return record


# ── Aggregation ──────────────────────────────────────────────────────────
def _stats(values: list[float]) -> dict[str, float]:
    vs = [float(v) for v in values if v is not None]
    if not vs:
        return {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    m = float(statistics.fmean(vs))
    sd = float(statistics.stdev(vs)) if len(vs) > 1 else 0.0
    return {"mean": m, "stdev": sd, "min": float(min(vs)), "max": float(max(vs))}


def _aggregate(variants: list[Variant]) -> tuple[list[dict], list[dict]]:
    from src.stages.coherence import _get_default_embedder

    embedder = _get_default_embedder()

    per_call_rows: list[dict] = []
    for variant in variants:
        for rep in (1, 2, 3):
            path = _output_path(variant.label, rep)
            if not path.exists():
                continue
            with path.open() as f:
                rec = json.load(f)
            s = rec.get("structured")
            topics: list[dict] = []
            if isinstance(s, dict):
                topics = [
                    t
                    for t in (s.get("topics") or [])
                    if isinstance(t, dict) and t.get("title")
                ]

            n_topics = len(topics)
            n_unique = _unique_theme_count(topics, embedder) if topics else 0
            n_dup = n_topics - n_unique

            corr_total = {
                "repeated_word": 0,
                "repeated_quoted": 0,
                "hyphen_ed": 0,
                "non_adjacent_stutter": 0,
            }
            for t in topics:
                sigs = _corruption_signals(t.get("title", ""), t.get("summary", ""))
                for k, v in sigs.items():
                    corr_total[k] += v
            n_corr = sum(corr_total.values())

            per_call_rows.append(
                {
                    "label": variant.label,
                    "rep": rep,
                    "temperature": variant.temperature,
                    "reasoning": variant.reasoning,
                    "streaming": variant.streaming,
                    "schema_valid": rec.get("schema_valid", False),
                    "cost_usd": rec.get("cost_usd", 0.0),
                    "wall_seconds": rec.get("wall_seconds", 0.0),
                    "tokens_used": rec.get("tokens_used", 0),
                    "provider_served": rec.get("provider_served", ""),
                    "error": rec.get("error"),
                    "n_topics": n_topics,
                    "n_unique_themes": n_unique,
                    "n_duplicates": n_dup,
                    "n_text_corruption_signals": n_corr,
                    "corruption_breakdown": corr_total,
                }
            )

    per_variant: list[dict] = []
    for v in variants:
        rows = [r for r in per_call_rows if r["label"] == v.label]
        if not rows:
            continue
        per_variant.append(
            {
                "label": v.label,
                "model": v.model,
                "temperature": v.temperature,
                "reasoning": v.reasoning,
                "streaming": v.streaming,
                "n_reps_completed": len(rows),
                "n_topics": _stats([r["n_topics"] for r in rows]),
                "n_unique_themes": _stats([r["n_unique_themes"] for r in rows]),
                "n_duplicates": _stats([r["n_duplicates"] for r in rows]),
                "n_text_corruption_signals": _stats([r["n_text_corruption_signals"] for r in rows]),
                "schema_validity_rate": sum(1 for r in rows if r["schema_valid"]) / len(rows),
                "cost_usd_total": sum(r["cost_usd"] for r in rows),
                "wall_seconds_mean": statistics.fmean([r["wall_seconds"] for r in rows]),
                "n_errors": sum(1 for r in rows if r["error"]),
            }
        )

    return per_call_rows, per_variant


async def main() -> int:
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{SWEEP_NAME}] building substrate + messages (loads fastembed once)")
    messages = _build_messages_once()
    variants = _all_variants()
    print(
        f"[{SWEEP_NAME}] {len(variants)} variants × {REPS} reps "
        f"= {len(variants) * REPS} calls, cap ${CAP_USD:.2f}"
    )

    tracker = SpendTracker(cap_usd=CAP_USD)
    client = build_client()

    try:
        for reasoning in REASONINGS:
            level_variants = [v for v in variants if v.reasoning == reasoning]
            tasks = [
                _run_one(client, v, rep, messages, tracker)
                for v in level_variants
                for rep in (1, 2, 3)
            ]
            print(f"[{SWEEP_NAME}] launching {len(tasks)} concurrent calls @ reasoning={reasoning}")
            await asyncio.gather(*tasks, return_exceptions=False)
            print(
                f"[{SWEEP_NAME}] reasoning={reasoning} batch done; "
                f"cumulative ${tracker.cumulative_usd:.4f} / cap ${CAP_USD:.2f}"
            )
            if tracker.cumulative_usd >= CAP_USD:
                print(
                    f"[{SWEEP_NAME}] WARN: ${CAP_USD:.2f} cap crossed — halting before next reasoning level",
                    file=sys.stderr,
                )
                break
    finally:
        await client.close()

    per_call_rows, per_variant = _aggregate(variants)
    metrics = {
        "sweep_name": SWEEP_NAME,
        "substrate": {
            "run_id": "c26864b2",
            "date": "2026-05-18",
            "substrate_file": "run_bus.pre_cluster_findings.json",
        },
        "config": {
            "temps": TEMPS,
            "reasonings": REASONINGS,
            "reps": REPS,
            "model": "deepseek/deepseek-v4-flash",
            "max_tokens": 160000,
            "dedup_threshold": DEDUP_THRESHOLD,
            "cap_usd": CAP_USD,
        },
        "cumulative_cost_usd": tracker.cumulative_usd,
        "per_call": per_call_rows,
        "per_variant": per_variant,
    }
    with (SWEEP_DIR / "_metrics.json").open("w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[{SWEEP_NAME}] metrics: {SWEEP_DIR / '_metrics.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
