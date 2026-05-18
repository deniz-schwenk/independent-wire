"""Cost-efficiency sweep — shared harness.

This module is the harness layer for `scripts/eval_researcher_plan.py`,
`scripts/eval_hydration_phase2.py`, and `scripts/eval_researcher_assemble.py`
(TASK-COST-EFFICIENCY-SWEEP-WAVE-1). It bypasses `Agent.run()` and calls the
OpenRouter `/chat/completions` endpoint directly through `AsyncOpenAI`. This
is Option B from the brief — chosen because DeepSeek V4 Pro with
`reasoning ∈ {medium, high}` requires `stream=True` to avoid the 230-350k
internal-reasoning-token buffer-then-silence failure documented in
`docs/AUDIT-CURATOR-2026-05-11.md`, and the streaming path is a non-trivial
addition that should not land in `src/agent.py` for an eval-only smoke.

The harness builds messages with the same three-block layout as
`Agent._build_user_message`:

    <context>{json(context)}\n\n{message}</context>
    <instructions>{INSTRUCTIONS.md}</instructions>

so the agent's prompt receives exactly the input the production wrapper
would produce.

Production code in `src/`, `agents/`, `scripts/run.py`, `src/schemas.py`
is not touched by this harness.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBSTRATE_ROOT = REPO_ROOT / "output" / "2026-05-18" / "_state" / "run-2026-05-18-c26864b2"
EVAL_OUTPUT_ROOT = REPO_ROOT / "output" / "eval"


# ---------------------------------------------------------------------------
# Spending cap
# ---------------------------------------------------------------------------


class SpendingCapExceeded(RuntimeError):
    """Raised when cumulative cost for a sweep crosses the cap."""


@dataclass
class SpendTracker:
    cap_usd: float
    cumulative_usd: float = 0.0
    per_label_usd: dict[str, float] = field(default_factory=dict)

    def add(self, label: str, cost_usd: float) -> None:
        self.per_label_usd[label] = self.per_label_usd.get(label, 0.0) + cost_usd
        self.cumulative_usd += cost_usd
        if self.cumulative_usd >= self.cap_usd:
            raise SpendingCapExceeded(
                f"Spending cap ${self.cap_usd:.2f} reached/crossed: "
                f"cumulative ${self.cumulative_usd:.4f}. Last addition: "
                f"{label} += ${cost_usd:.4f}."
            )


# ---------------------------------------------------------------------------
# Substrate loader
# ---------------------------------------------------------------------------


def load_topic_bus(prev_stage: str, topic_index: int) -> dict[str, Any]:
    path = SUBSTRATE_ROOT / f"topic_buses.{prev_stage}.{topic_index}.json"
    if not path.exists():
        raise FileNotFoundError(f"Substrate missing: {path}")
    with path.open() as f:
        return json.load(f)


def load_run_bus(stage: str = "finalize_run") -> dict[str, Any]:
    path = SUBSTRATE_ROOT / f"run_bus.{stage}.json"
    if not path.exists():
        raise FileNotFoundError(f"Run bus missing: {path}")
    with path.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Prompt assembly (mirrors Agent._build_user_message exactly)
# ---------------------------------------------------------------------------


def build_messages(
    system_prompt_path: Path,
    instructions_path: Path,
    message: str,
    context: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Three-block User turn:  <context> + <instructions>.  No <memory>
    block (eval harness never carries memory)."""
    system_body = system_prompt_path.read_text(encoding="utf-8").rstrip()
    instructions_body = instructions_path.read_text(encoding="utf-8").rstrip("\n")

    blocks: list[str] = []
    context_payload: list[str] = []
    if context:
        context_payload.append(json.dumps(context, indent=2, ensure_ascii=False))
    if message:
        context_payload.append(message)
    if context_payload:
        blocks.append("<context>\n" + "\n\n".join(context_payload) + "\n</context>")

    blocks.append(f"<instructions>\n{instructions_body}\n</instructions>")

    return [
        {"role": "system", "content": f"<system_prompt>\n{system_body}\n</system_prompt>"},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


# ---------------------------------------------------------------------------
# Variant spec + result
# ---------------------------------------------------------------------------


@dataclass
class Variant:
    label: str
    model: str
    temperature: float
    reasoning: str | None  # 'none', 'low', 'medium', 'high', or None to omit
    streaming: bool
    max_tokens: int = 64000


@dataclass
class CallResult:
    label: str
    topic_index: int
    model_requested: str
    model_served: str
    provider_served: str
    response_id: str
    temperature: float
    reasoning: str | None
    streaming: bool
    max_tokens: int
    content: str
    structured: dict | list | None
    schema_valid: bool
    cost_usd: float
    tokens_used: int
    wall_seconds: float
    error: str | None = None


# ---------------------------------------------------------------------------
# OpenRouter call (Option B — bypasses Agent.run)
# ---------------------------------------------------------------------------


def _build_extra_body(
    variant: Variant,
    schema: dict,
    provider_order: list[str] | None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if variant.reasoning is not None:
        extra["reasoning"] = {"effort": variant.reasoning}
    # response_format will be added at request-kwarg level; here we add
    # the provider-routing block.
    provider_block: dict[str, Any] = {"require_parameters": True}
    if provider_order:
        provider_block["order"] = provider_order
        provider_block["allow_fallbacks"] = True
    extra["provider"] = provider_block
    return extra


def _validate_against_schema(payload: Any, schema: dict) -> bool:
    """Strict-mode schema validation — enough to detect structural drift.

    We do not pull in `jsonschema`. The strict_mode response_format above
    already constrains decoding, so this is a sanity check (shape + keys
    + types at the top level) rather than a full validator.
    """
    if not isinstance(payload, dict):
        return False
    required = schema.get("required") or []
    for key in required:
        if key not in payload:
            return False
    # If top-level "queries" / "assignments" / "sources" / etc. is an array,
    # at least confirm it is a list.
    for key, prop in (schema.get("properties") or {}).items():
        if key in payload and prop.get("type") == "array":
            if not isinstance(payload[key], list):
                return False
    return True


async def call_openrouter(
    client: AsyncOpenAI,
    variant: Variant,
    messages: list[dict[str, str]],
    response_format_schema: dict,
    schema_name: str,
    provider_order: list[str] | None,
) -> tuple[str, dict | list | None, dict[str, Any]]:
    """Single LLM call.  Returns (content, structured, telemetry).

    `telemetry` carries:  cost_usd, tokens_used, wall_seconds,
    model_served, provider_served, response_id, schema_valid.

    Raises on transport / API errors — the caller wraps the call to
    record the failure cleanly.
    """
    kwargs: dict[str, Any] = {
        "model": variant.model,
        "messages": messages,
        "temperature": variant.temperature,
        "max_tokens": variant.max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": response_format_schema,
            },
        },
        "extra_body": _build_extra_body(variant, response_format_schema, provider_order),
    }

    start = time.monotonic()

    if variant.streaming:
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        content_chunks: list[str] = []
        usage: Any = None
        model_served = variant.model
        provider_served = ""
        response_id = ""
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if getattr(chunk, "id", None):
                    response_id = chunk.id
                if getattr(chunk, "model", None):
                    model_served = chunk.model
                if getattr(chunk, "provider", None):
                    provider_served = chunk.provider or provider_served
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    if delta is not None and getattr(delta, "content", None):
                        content_chunks.append(delta.content)
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage
        finally:
            wall = time.monotonic() - start
        content = "".join(content_chunks)
    else:
        response = await client.chat.completions.create(**kwargs)
        wall = time.monotonic() - start
        choice = response.choices[0]
        content = choice.message.content or ""
        usage = getattr(response, "usage", None)
        model_served = getattr(response, "model", variant.model) or variant.model
        provider_served = getattr(response, "provider", "") or ""
        response_id = getattr(response, "id", "") or ""

    # Parse JSON output
    structured: dict | list | None
    try:
        structured = json.loads(content) if content.strip() else None
    except (json.JSONDecodeError, ValueError):
        structured = None

    schema_valid = bool(structured) and _validate_against_schema(structured, response_format_schema)

    # Cost + tokens from usage block
    cost_usd = 0.0
    tokens_used = 0
    if usage is not None:
        cost_val = getattr(usage, "cost", None)
        if cost_val is None and isinstance(usage, dict):
            cost_val = usage.get("cost")
        if cost_val is not None:
            try:
                cost_usd = float(cost_val)
            except (TypeError, ValueError):
                pass
        toks = getattr(usage, "total_tokens", None)
        if toks is None and isinstance(usage, dict):
            toks = usage.get("total_tokens")
        if toks is not None:
            try:
                tokens_used = int(toks)
            except (TypeError, ValueError):
                pass

    return content, structured, {
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
        "wall_seconds": wall,
        "model_served": model_served,
        "provider_served": provider_served,
        "response_id": response_id,
        "schema_valid": schema_valid,
    }


# ---------------------------------------------------------------------------
# Per-variant call wrapper with skip-resume + failure capture
# ---------------------------------------------------------------------------


def _output_path(sweep_dir: Path, label: str, topic_index: int) -> Path:
    return sweep_dir / f"{label}-topic{topic_index}.json"


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


async def run_variant_on_topic(
    client: AsyncOpenAI,
    sweep_dir: Path,
    variant: Variant,
    topic_index: int,
    messages: list[dict[str, str]],
    response_format_schema: dict,
    schema_name: str,
    provider_order: list[str] | None,
    tracker: SpendTracker,
) -> CallResult:
    out_path = _output_path(sweep_dir, variant.label, topic_index)

    if _has_usable_cache(out_path):
        with out_path.open() as f:
            cached = json.load(f)
        return CallResult(
            label=variant.label,
            topic_index=topic_index,
            model_requested=variant.model,
            model_served=cached.get("model_served", variant.model),
            provider_served=cached.get("provider_served", ""),
            response_id=cached.get("response_id", ""),
            temperature=variant.temperature,
            reasoning=variant.reasoning,
            streaming=variant.streaming,
            max_tokens=variant.max_tokens,
            content=cached.get("content", ""),
            structured=cached.get("structured"),
            schema_valid=cached.get("schema_valid", False),
            cost_usd=cached.get("cost_usd", 0.0),
            tokens_used=cached.get("tokens_used", 0),
            wall_seconds=cached.get("wall_seconds", 0.0),
            error=None,
        )

    try:
        content, structured, telemetry = await call_openrouter(
            client=client,
            variant=variant,
            messages=messages,
            response_format_schema=response_format_schema,
            schema_name=schema_name,
            provider_order=provider_order,
        )
        error: str | None = None
    except Exception as e:  # noqa: BLE001 — eval harness logs and continues
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

    result = CallResult(
        label=variant.label,
        topic_index=topic_index,
        model_requested=variant.model,
        model_served=telemetry["model_served"],
        provider_served=telemetry["provider_served"],
        response_id=telemetry["response_id"],
        temperature=variant.temperature,
        reasoning=variant.reasoning,
        streaming=variant.streaming,
        max_tokens=variant.max_tokens,
        content=content,
        structured=structured,
        schema_valid=telemetry["schema_valid"],
        cost_usd=telemetry["cost_usd"],
        tokens_used=telemetry["tokens_used"],
        wall_seconds=telemetry["wall_seconds"],
        error=error,
    )

    # Persist before cap check — even if cap throws on this addition, we
    # do not lose the call's output.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(_dump_result(result), f, indent=2, ensure_ascii=False)

    # Cap enforcement happens after persistence
    if error is None:
        tracker.add(f"{variant.label}-topic{topic_index}", result.cost_usd)

    return result


def _dump_result(result: CallResult) -> dict[str, Any]:
    return {
        "label": result.label,
        "topic_index": result.topic_index,
        "model_requested": result.model_requested,
        "model_served": result.model_served,
        "provider_served": result.provider_served,
        "response_id": result.response_id,
        "temperature": result.temperature,
        "reasoning": result.reasoning,
        "streaming": result.streaming,
        "max_tokens": result.max_tokens,
        "schema_valid": result.schema_valid,
        "cost_usd": result.cost_usd,
        "tokens_used": result.tokens_used,
        "wall_seconds": result.wall_seconds,
        "error": result.error,
        "content": result.content,
        "structured": result.structured,
    }


# ---------------------------------------------------------------------------
# OpenAI client factory
# ---------------------------------------------------------------------------


def build_client() -> AsyncOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set in environment")
    return AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        # Reasoning + streaming can run long; allow 10 min reads to be safe.
        timeout=httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0),
    )


# ---------------------------------------------------------------------------
# Sweep-level driver
# ---------------------------------------------------------------------------


async def run_sweep(
    sweep_name: str,
    sweep_dir: Path,
    variants: list[Variant],
    per_topic_messages: dict[int, list[dict[str, str]]],
    response_format_schema: dict,
    schema_name: str,
    provider_order_per_variant: dict[str, list[str] | None],
    cap_usd: float = 10.0,
) -> tuple[list[CallResult], SpendTracker]:
    """Run all (variant, topic) pairs sequentially per variant; 3 topics
    are dispatched in parallel within each variant.

    The cap is enforced per variant — i.e. after every variant we check
    `tracker.cumulative_usd` against `cap_usd`. Within a variant the
    three parallel calls may overshoot the cap by a fraction; this is
    acceptable because each individual call is bounded by `max_tokens`.
    """
    sweep_dir.mkdir(parents=True, exist_ok=True)
    client = build_client()
    tracker = SpendTracker(cap_usd=cap_usd)
    results: list[CallResult] = []

    try:
        for variant in variants:
            provider_order = provider_order_per_variant.get(variant.label)
            tasks = [
                run_variant_on_topic(
                    client=client,
                    sweep_dir=sweep_dir,
                    variant=variant,
                    topic_index=topic_index,
                    messages=messages,
                    response_format_schema=response_format_schema,
                    schema_name=schema_name,
                    provider_order=provider_order,
                    tracker=tracker,
                )
                for topic_index, messages in per_topic_messages.items()
            ]
            try:
                batch = await asyncio.gather(*tasks)
                results.extend(batch)
            except SpendingCapExceeded:
                # gather may have completed some — persist what we have
                # and rebreak.
                raise

            print(
                f"[{sweep_name}] variant {variant.label}: "
                f"cumulative ${tracker.cumulative_usd:.4f} / cap ${cap_usd:.2f}"
            )
            if tracker.cumulative_usd >= cap_usd:
                raise SpendingCapExceeded(
                    f"Cap ${cap_usd:.2f} reached after variant {variant.label}; "
                    f"cumulative ${tracker.cumulative_usd:.4f}."
                )
    finally:
        await client.close()

    return results, tracker
