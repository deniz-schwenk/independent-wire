"""Wave 2 Sweep #1 — Curator Topic Discovery (Flash replacement).

Run-phase stage: fires once per pipeline run. Substrate:
`run_bus.pre_cluster_findings.json` carries 1,217 findings and 252
agglomerative pre-clusters, which the production wrapper compresses via
top-K-by-centroid (K=8) before handing to the LLM. The compression
itself is deterministic and shared via the fastembed singleton
(`src/stages/coherence.py::_get_default_embedder`) — we re-run that
helper here to obtain the exact `micro_clusters[]` input the production
wrapper builds, then submit to the candidate model.

1 variant × 1 call. max_tokens=160000.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.eval_common import (  # noqa: E402
    EVAL_OUTPUT_ROOT,
    SUBSTRATE_ROOT,
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

SWEEP_NAME = "curator_topic_discovery"
SWEEP_DIR = EVAL_OUTPUT_ROOT / "wave-2" / SWEEP_NAME

SYSTEM_PROMPT_PATH = REPO_ROOT / "agents" / "curator" / "SYSTEM.md"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "curator" / "INSTRUCTIONS.md"

CURATOR_USER_MESSAGE = (
    "Discover today's topics from the supplied micro-clusters. "
    "Output JSON: {topics: [{title, summary}]}."
)

VARIANTS: list[Variant] = [
    Variant(
        "dskflash-t05-rnone",
        "deepseek/deepseek-v4-flash",
        0.5,
        "none",
        streaming=False,
        max_tokens=160000,
    ),
]


def _build_run_message_and_context() -> tuple[str, dict[str, Any]]:
    sub = load_run_bus("pre_cluster_findings")
    findings = list(sub.get("curator_findings") or [])
    pre_clusters_record = sub.get("curator_pre_clusters") or {}
    pre_clusters = list(pre_clusters_record.get("clusters") or [])
    run_date = sub.get("run_date") or ""

    # Compress with fastembed singleton — same path the production
    # wrapper takes. This loads fastembed once.
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
    return CURATOR_USER_MESSAGE, context


def _output_path(label: str) -> Path:
    return SWEEP_DIR / f"{label}.json"


def _has_usable_cache(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open() as f:
            data = json.load(f)
        return data.get("structured") not in (None, {}, []) and not data.get("error")
    except (json.JSONDecodeError, OSError):
        return False


async def main() -> int:
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)

    message, context = _build_run_message_and_context()
    messages = build_messages(
        system_prompt_path=SYSTEM_PROMPT_PATH,
        instructions_path=INSTRUCTIONS_PATH,
        message=message,
        context=context,
    )

    tracker = SpendTracker(cap_usd=15.0)
    client = build_client()
    results = []
    print(f"[{SWEEP_NAME}] starting {len(VARIANTS)} variants × 1 call")
    print(f"[{SWEEP_NAME}] sweep dir: {SWEEP_DIR}")

    try:
        for variant in VARIANTS:
            out_path = _output_path(variant.label)
            if _has_usable_cache(out_path):
                with out_path.open() as f:
                    cached = json.load(f)
                results.append(cached)
                print(f"[{SWEEP_NAME}] {variant.label} (cached)")
                continue

            try:
                content, structured, telemetry = await call_openrouter(
                    client=client,
                    variant=variant,
                    messages=messages,
                    response_format_schema=CURATOR_TOPIC_DISCOVERY_SCHEMA,
                    schema_name="curator_topic_discovery_output",
                    provider_order=["deepseek"],
                )
                error = None
            except Exception as e:  # noqa: BLE001
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
            with out_path.open("w") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            results.append(record)

            if error is None:
                tracker.add(variant.label, record["cost_usd"])
            print(
                f"[{SWEEP_NAME}] {variant.label}: ${record['cost_usd']:.4f} "
                f"{record['tokens_used']} tokens {record['wall_seconds']:.1f}s "
                f"valid={record['schema_valid']} err={error}"
            )
    except SpendingCapExceeded as e:
        print(f"[{SWEEP_NAME}] WARN: per-sweep cap crossed: {e}", file=sys.stderr)
    finally:
        await client.close()

    # Aggregate metrics — fresh re-read so cached entries are included
    rows = []
    for variant in VARIANTS:
        path = _output_path(variant.label)
        if not path.exists():
            continue
        with path.open() as f:
            rec = json.load(f)
        s = rec.get("structured")
        n_topics = 0
        topic_titles: list[str] = []
        if isinstance(s, dict):
            topics = s.get("topics") or []
            n_topics = len([t for t in topics if isinstance(t, dict) and t.get("title")])
            topic_titles = [t.get("title", "") for t in topics if isinstance(t, dict)]
        rows.append({
            "label": rec["label"],
            "model": rec["model_requested"],
            "temperature": rec["temperature"],
            "reasoning": rec["reasoning"],
            "max_tokens": rec["max_tokens"],
            "streaming": rec["streaming"],
            "schema_validity_rate": 1.0 if rec.get("schema_valid") else 0.0,
            "cost_usd": rec["cost_usd"],
            "wall_seconds": rec["wall_seconds"],
            "tokens_used": rec["tokens_used"],
            "n_topics_discovered": n_topics,
            "topic_titles": topic_titles,
            "providers_served": [rec.get("provider_served") or ""],
            "error": rec.get("error"),
        })

    metrics = {
        "sweep_name": SWEEP_NAME,
        "substrate": {
            "run_id": "c26864b2",
            "date": "2026-05-18",
            "substrate_file": "run_bus.pre_cluster_findings.json",
        },
        "baseline": {
            "model": "google/gemini-3-flash-preview",
            "temperature": 1.0,
            "reasoning": "none",
            "max_tokens": 8000,
            "n_topics_discovered": 20,
            "cost_usd": 0.019231,
            "tokens_used": 30607,
        },
        "cumulative_cost_usd": tracker.cumulative_usd,
        "per_sweep_cap_usd": 15.0,
        "variants": rows,
    }
    with (SWEEP_DIR / "_metrics.json").open("w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[{SWEEP_NAME}] metrics: {SWEEP_DIR / '_metrics.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
