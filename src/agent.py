"""Independent Wire — Agent abstraction.

An Agent is a configured async LLM caller with identity, model, tools, memory,
and temperature. It calls the OpenRouter API (OpenAI-compatible), handles tool
calls in a loop, and returns structured AgentResult objects.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI, APIStatusError

from src.tools.registry import Tool


@dataclass
class AgentResult:
    """What an agent returns."""

    content: str
    structured: dict | None = None
    tool_calls: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0
    model: str = ""
    duration_seconds: float = 0.0
    # Provider routing fingerprint surfaced by OpenRouter on the final
    # response. Empty string when the provider does not report it (e.g.
    # non-OpenRouter providers or older response shapes). Captured from
    # ``response.provider`` on the last chat-completions call in the
    # tool-call loop.
    provider: str = ""
    # OpenRouter / OpenAI response id of the last chat-completions call.
    # Useful for reproducibility — pairing a logged result with a
    # provider-side trace.
    response_id: str = ""

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10
MAX_RETRIES = 3
MAX_STRUCTURED_RETRIES = 2
BASE_DELAY = 2  # seconds
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# Provider defaults for LLM API endpoints
PROVIDER_DEFAULTS: dict[str, dict[str, str | None]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "api_key_env": None,  # Local Ollama needs no key
        "api_key_default": "ollama",  # Dummy for openai library
    },
    "ollama_cloud": {
        "base_url": "https://ollama.com/v1",
        "api_key_env": "OLLAMA_API_KEY",
    },
    # DeepSeek direct API. No env-var default — callers pass an explicit
    # ``api_key`` or ``api_key_file``. Used by scripts/curator_shadow.py
    # to measure native DeepSeek serving (vs OpenRouter-routed). Provider-
    # specific knobs (``thinking.type``, ``reasoning_effort``) are passed
    # via ``extra_body_override``; the OpenRouter-specific ``reasoning``
    # and ``provider.require_parameters`` injections in
    # ``_call_with_retry`` are gated on ``provider == "openrouter"`` so
    # they do not fire here.
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": None,
    },
    # PRODUCTION channel C for the three v4-flash-0731 stages
    # (TASK-FLASH-0731-SWAP). Same host as ``deepseek`` above, but resolves
    # its key from the environment so ``daily_run.sh`` (which sources .env)
    # needs no per-agent key plumbing. Kept as a separate entry rather than
    # adding an env default to ``deepseek``, so curator_shadow.py's
    # explicit-key contract is untouched.
    #
    # The vendor exposes exactly ONE flash id, ``deepseek-v4-flash``, and
    # rejects every dated form with a 400 — it serves the 0731 build by
    # alias, unpinnable (T2d §1.1). The per-call log line below records the
    # server-echoed model id precisely so an alias roll is visible.
    "deepseek_direct": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
}

# Providers whose endpoint offers no strict ``json_schema`` decoding. Sending
# one anyway is not a no-op: on api.deepseek.com the schema block is ignored,
# and on OpenRouter ``require_parameters: true`` filters the DeepSeek endpoint
# out of the route entirely and the call 404s (T2b §1.1, T2d §1.4). These
# providers get ``response_format: {"type": "json_object"}`` instead, and the
# schema is enforced locally by the caller — the parser chain here, then
# FlashStageWithFallback's schema check.
JSON_OBJECT_ONLY_PROVIDERS = frozenset({"deepseek_direct"})

STRUCTURED_OUTPUT_MODES = ("strict_schema", "json_object")

# --- DeepSeek direct-API pricing ---------------------------------------------
# api.deepseek.com returns no ``usage.cost``. Without this table the three
# flash stages would log ``cost_usd=0.0`` on every run and the daily cost
# report would silently lose its primary channel — worse than reporting
# nothing. USD per 1M tokens from api-docs.deepseek.com/quick_start/pricing,
# fetched 2026-08-23. DeepSeek bills a PEAK and an OFF-PEAK rate differing by
# 2x, so the window is part of the price: peak is 01:00-04:00 and 06:00-10:00
# UTC, Monday to Friday; everything else, weekends included, is off-peak.
# Production fires 06:00 local = 04:00 UTC under CEST, i.e. minutes after the
# first peak block closes — an hour of schedule drift doubles this bill.
# Cross-checked against the vendor's own /user/balance to +4.1% over $1.12 of
# traffic (T2d §1.5). A served model id absent from the table is logged loudly
# and reports NO cost rather than a wrong one.
DEEPSEEK_DIRECT_PRICING_VERSION = "api-docs.deepseek.com @ 2026-08-23"
DEEPSEEK_DIRECT_PRICES: dict[str, dict[str, tuple[float, float, float]]] = {
    # model -> window -> (cache_hit_input, cache_miss_input, output)
    "deepseek-v4-flash": {
        "offpeak": (0.007, 0.22, 0.66),
        "peak": (0.014, 0.44, 1.32),
    },
    "deepseek-v4-pro": {
        "offpeak": (0.022, 0.66, 1.98),
        "peak": (0.044, 1.32, 3.96),
    },
}


def deepseek_price_window(now: datetime | None = None) -> str:
    """``"peak"`` or ``"offpeak"`` for a UTC instant (default: now)."""
    t = now or datetime.now(timezone.utc)
    if t.weekday() < 5 and (1 <= t.hour < 4 or 6 <= t.hour < 10):
        return "peak"
    return "offpeak"


def deepseek_direct_cost_usd(
    model: str, usage: Any, now: datetime | None = None
) -> float | None:
    """Cost of one api.deepseek.com call from its own usage counters.

    Returns ``None`` when the model is unpriced or usage is absent, so the
    caller can distinguish "not measurable" from "free".
    """
    rates = DEEPSEEK_DIRECT_PRICES.get((model or "").split(":")[0])
    if rates is None or usage is None:
        return None
    window = rates[deepseek_price_window(now)]
    hit = getattr(usage, "prompt_cache_hit_tokens", None)
    miss = getattr(usage, "prompt_cache_miss_tokens", None)
    if hit is None and miss is None:          # no cache split reported
        miss, hit = getattr(usage, "prompt_tokens", 0) or 0, 0
    out = getattr(usage, "completion_tokens", 0) or 0
    return round(
        ((hit or 0) * window[0] + (miss or 0) * window[1] + out * window[2])
        / 1_000_000,
        8,
    )


class AgentError(Exception):
    """Base exception for agent errors."""


class AgentAPIError(AgentError):
    """Raised when the LLM API returns a non-retryable error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentTimeoutError(AgentError):
    """Raised when the LLM API call times out."""


def _format_tokens_for_log(total_tokens: int, usage_missing_count: int) -> str:
    """Render a tokens-used display string for the agent's completion log.

    OpenRouter occasionally returns responses with ``usage = None`` or with
    ``usage.total_tokens`` absent — observed during the V2-10 smoke on a
    long-running Curator call that produced valid output but logged
    ``0 tokens``. Rather than silently report ``0`` we surface
    ``"unknown"`` (when no usable usage was observed at all) or
    ``"{N}+ (usage missing on K responses)"`` (when partial usage was
    observed but K responses lacked it).
    """
    if usage_missing_count > 0 and total_tokens == 0:
        return "unknown"
    if usage_missing_count > 0:
        return f"{total_tokens}+ (usage missing on {usage_missing_count} responses)"
    return str(total_tokens)


def _extract_response_tokens(response: Any) -> tuple[int, bool]:
    """Return ``(tokens, observed)`` from an OpenAI-style chat-completion.

    ``observed`` is True when the response carried a non-None ``usage``
    object whose ``total_tokens`` field was a positive integer; False
    otherwise (callers can count missing observations to surface the
    log-display caveat).
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, False
    total = getattr(usage, "total_tokens", None)
    if total is None or not isinstance(total, int) or total < 0:
        return 0, False
    return total, True


class Agent:
    """A configured LLM caller with identity, model, tools, and memory."""

    def __init__(
        self,
        name: str,
        model: str,
        system_prompt_path: str,
        instructions_path: str,
        tools: list[Tool] | None = None,
        memory_path: str | None = None,
        temperature: float | None = 0.3,
        max_tokens: int = 32000,
        provider: str = "openrouter",
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_file: str | None = None,
        reasoning: str | bool | dict | None = None,
        extra_body_override: dict | None = None,
        provider_routing: dict | None = None,
        output_schema: dict | None = None,
        structured_output_mode: str = "strict_schema",
    ) -> None:
        self.name = name
        self.model = model
        self.system_prompt_path = system_prompt_path
        self.instructions_path = instructions_path
        self.tools = tools or []
        self.memory_path = memory_path
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.provider = provider
        self.reasoning = reasoning
        self._extra_body_override = extra_body_override or {}
        # OpenRouter `provider` routing preference (e.g. a quantization pin +
        # provider allow-list + fail-loud fallback policy). Merged into
        # extra_body["provider"] per request; see _call_with_retry. Kept
        # separate from extra_body_override so the routing intent is explicit
        # and self-documenting at the call site.
        self._provider_routing = provider_routing or {}
        self.output_schema = output_schema
        # How ``output_schema`` reaches the wire. ``strict_schema`` (the
        # default, and what every OpenRouter stage has always used) sends a
        # strict ``json_schema`` response_format so decoding cannot violate
        # the schema. ``json_object`` sends only ``{"type": "json_object"}``
        # and leaves enforcement to local validation — required on any route
        # whose endpoint lacks ``structured_outputs``, which includes BOTH
        # v4-flash-0731 channels: api.deepseek.com ignores a schema block,
        # and OpenRouter pinned to the DeepSeek provider 404s on it because
        # ``require_parameters: true`` filters that endpoint out (T2b §1.1).
        if structured_output_mode not in STRUCTURED_OUTPUT_MODES:
            raise AgentError(
                f"Agent '{name}': structured_output_mode must be one of "
                f"{STRUCTURED_OUTPUT_MODES}, got {structured_output_mode!r}"
            )
        # Providers that cannot strict-decode are coerced regardless of what
        # the call site asked for — a strict schema there is silently ignored,
        # which is the worst of both worlds.
        if provider in JSON_OBJECT_ONLY_PROVIDERS:
            structured_output_mode = "json_object"
        self.structured_output_mode = structured_output_mode

        for label, path in (
            ("system_prompt_path", system_prompt_path),
            ("instructions_path", instructions_path),
        ):
            if not Path(path).exists():
                raise AgentError(
                    f"Agent '{name}': {label} file not found: {path}"
                )

        # Resolve provider defaults
        defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openrouter"])
        self.base_url = base_url or defaults["base_url"]

        # Resolve API key: explicit > file > env var > provider default > error
        resolved_key = api_key
        if not resolved_key and api_key_file:
            key_path = Path(api_key_file)
            if not key_path.exists():
                raise ValueError(
                    f"Agent '{name}': api_key_file not found: {api_key_file}"
                )
            resolved_key = key_path.read_text(encoding="utf-8").strip()
            if not resolved_key:
                raise ValueError(
                    f"Agent '{name}': api_key_file is empty: {api_key_file}"
                )
        if not resolved_key:
            env_var = defaults.get("api_key_env")
            if env_var:
                resolved_key = os.environ.get(env_var)
        if not resolved_key:
            resolved_key = defaults.get("api_key_default")
        if not resolved_key:
            env_var = defaults.get("api_key_env", "OPENROUTER_API_KEY")
            raise ValueError(
                f"Agent '{name}': No API key provided and {env_var} not set"
            )

        self._client = AsyncOpenAI(
            api_key=resolved_key,
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0),
        )

        # Build tool lookup for fast access during tool-call loop
        self._tool_map: dict[str, Tool] = {t.name: t for t in self.tools}

        # Per-stage cost/token accumulators. Each `run()` call adds its
        # totals here; the runner resets before each stage and reads after,
        # so the values reflect the cost of one stage execution (which may
        # involve multiple `run()` calls — e.g. HydrationPhase1's parallel
        # chunk dispatch). See TASK-RUN-STAGE-LOG-COST.
        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        # Served model + provider of the most recent `run()` call, surfaced into
        # run_stage_log.jsonl by the runner's `_collect_agent_metrics` so EVERY
        # LLM stage records which model/provider actually served it — not just
        # the fallback-wrapped stages (TASK-LLM-STAGE-LOUD-LOGGING). `model_used`
        # is the resolved id from the response (falls back to the requested
        # model); `provider_used` is the response's `provider` metadata (empty
        # until the first call; the runner logs "unknown" if a response omits it).
        self.last_model_used: str = ""
        self.last_provider_used: str = ""

    def reset_call_metrics(self) -> None:
        """Zero the per-stage cost/token accumulators. Called by the runner
        before each stage execution."""
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.last_model_used = ""
        self.last_provider_used = ""

    def _load_system_content(self) -> str:
        """Load the SYSTEM.md (role-only) content for this agent."""
        path = Path(self.system_prompt_path)
        if not path.exists():
            raise AgentError(
                f"Agent '{self.name}': system_prompt_path not found: "
                f"{self.system_prompt_path}"
            )
        return path.read_text(encoding="utf-8")

    def _load_instructions_content(self) -> str:
        """Load the INSTRUCTIONS.md (task description) content for this agent.

        Empty file is allowed (returns empty string) so a transitional
        empty INSTRUCTIONS.md does not crash the pipeline.
        """
        path = Path(self.instructions_path)
        if not path.exists():
            raise AgentError(
                f"Agent '{self.name}': instructions_path not found: "
                f"{self.instructions_path}"
            )
        return path.read_text(encoding="utf-8")

    def _load_memory(self) -> str | None:
        """Load memory from memory_path if it exists."""
        if not self.memory_path:
            return None
        path = Path(self.memory_path)
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8").strip()
        return content if content else None

    def _build_system_prompt(self) -> str:
        """Return ``<system_prompt>{SYSTEM.md}</system_prompt>`` — nothing else.

        Memory, addendums, and output schemas live in the User turn.
        """
        body = self._load_system_content().rstrip()
        return f"<system_prompt>\n{body}\n</system_prompt>"

    def _build_user_message(
        self,
        message: str,
        context: dict | None = None,
        memory: str | None = None,
        instructions_addendum: str | None = None,
    ) -> str:
        """Build the User turn as three sequential blocks.

        Layout, in order, separated by blank lines:

        1. ``<context>{message + JSON-formatted context}</context>`` —
           omitted entirely when both ``message`` and ``context`` are
           empty. Inside, ``message`` (legacy run() parameter) is
           appended to the JSON-encoded ``context`` with a blank-line
           separator.
        2. ``<memory>{memory}</memory>`` — omitted entirely when memory
           is None or empty.
        3. ``<instructions>{INSTRUCTIONS.md}\\n\\n{instructions_addendum}</instructions>``
           — always present. The addendum (when provided) is appended
           inside the closing tag, separated by exactly one blank line.
        """
        blocks: list[str] = []

        context_payload: list[str] = []
        if context:
            context_payload.append(
                json.dumps(context, indent=2, ensure_ascii=False)
            )
        if message:
            context_payload.append(message)
        if context_payload:
            blocks.append(
                "<context>\n" + "\n\n".join(context_payload) + "\n</context>"
            )

        if memory:
            blocks.append(f"<memory>\n{memory.rstrip()}\n</memory>")

        instructions_body = self._load_instructions_content().rstrip("\n")
        if instructions_addendum:
            addendum = instructions_addendum.rstrip("\n")
            if instructions_body:
                instructions_body = f"{instructions_body}\n\n{addendum}"
            else:
                instructions_body = addendum
        blocks.append(f"<instructions>\n{instructions_body}\n</instructions>")

        return "\n\n".join(blocks)

    def _get_tool_definitions(self) -> list[dict] | None:
        """Get OpenAI-format tool definitions, or None if no tools."""
        if not self.tools:
            return None
        return [t.to_openai_format() for t in self.tools]

    async def _call_with_retry(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        output_schema: dict | None = None,
    ) -> object:
        """Call the LLM API with exponential backoff retry for transient errors."""
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
        # ``temperature=None`` means "do not send a temperature at all" — the
        # Claude 4.7/5 family rejects any non-default temperature/top_p (400),
        # so the qa_analyze Sonnet-5 fallback is constructed with
        # ``temperature=None``. Every other agent passes a float and is
        # unaffected.
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = tools

        # Map reasoning parameter to provider-specific extra_body
        extra_body: dict = {}
        if self.reasoning is None and self.provider == "openrouter":
            extra_body["reasoning"] = {"effort": "none"}
        elif self.reasoning is None and self.provider == "deepseek_direct":
            # The direct API's own default is reasoning ON — leaving the
            # parameter off is a silent multi-x cost surprise, so "no
            # reasoning configured" is sent explicitly as none, matching the
            # OpenRouter branch above.
            extra_body["reasoning_effort"] = "none"
        elif self.reasoning is not None:
            if self.provider == "openrouter":
                if isinstance(self.reasoning, bool):
                    extra_body["reasoning"] = {
                        "effort": "high" if self.reasoning else "minimal"
                    }
                elif isinstance(self.reasoning, dict):
                    # Pass an explicit OpenRouter reasoning block straight
                    # through (deep-copied so the shared instance value is
                    # never mutated). Used by the qa_analyze Sonnet-5 fallback
                    # to request adaptive thinking via ``{"enabled": True}``,
                    # which the ``effort`` vocabulary cannot express.
                    extra_body["reasoning"] = copy.deepcopy(self.reasoning)
                elif isinstance(self.reasoning, str):
                    extra_body["reasoning"] = {"effort": self.reasoning}
            elif self.provider in ("ollama", "ollama_cloud"):
                if isinstance(self.reasoning, bool):
                    extra_body["think"] = self.reasoning
                elif isinstance(self.reasoning, str):
                    extra_body["think"] = self.reasoning
            elif self.provider == "deepseek_direct":
                # A plain string parameter, NOT the OpenRouter object. The
                # direct API accepts ``reasoning: {"effort": ...}`` WITHOUT
                # error and ignores it, so sending the wrong shape here fails
                # silently into the default rather than loudly (T2d §1.3).
                if isinstance(self.reasoning, bool):
                    extra_body["reasoning_effort"] = (
                        "high" if self.reasoning else "none"
                    )
                elif isinstance(self.reasoning, str):
                    extra_body["reasoning_effort"] = self.reasoning
                elif isinstance(self.reasoning, dict):
                    raise AgentError(
                        f"Agent '{self.name}': provider 'deepseek_direct' takes "
                        f"a reasoning_effort STRING; the OpenRouter reasoning "
                        f"object is accepted by the API and silently ignored. "
                        f"Got {self.reasoning!r}."
                    )
        # Deep-copy the override so the per-call mutations below (the provider
        # merge and the require_parameters injection) never touch the shared
        # instance dict — closes the setdefault aliasing trap flagged in
        # docs/CODE-REVIEW-2026-07-02.md (Core, low findings: agent.py:362).
        extra_body.update(copy.deepcopy(self._extra_body_override))

        # Provider-routing preference (e.g. the fp8 quantization pin +
        # verified-provider allow-list + fail-loud fallback policy). Merged
        # into the OpenRouter `provider` block; deep-copied for the same
        # aliasing reason. Only meaningful on the OpenRouter route.
        if self.provider == "openrouter" and self._provider_routing:
            provider_block = extra_body.get("provider")
            if not isinstance(provider_block, dict):
                provider_block = {}
            provider_block.update(copy.deepcopy(self._provider_routing))
            extra_body["provider"] = provider_block

        # Structured outputs: pass JSON schema as OpenAI-compatible
        # ``response_format``. OpenRouter translates this to Anthropic's
        # native output_format.format and applies the
        # ``anthropic-beta: structured-outputs-2025-11-13`` header
        # automatically. Strict mode constrains decoding so the model
        # cannot emit tokens that violate the schema. The defensive
        # parser chain (``_extract_dict``, ``_parse_json``,
        # ``_parse_or_retry_structured``) stays in place as belt-and-
        # suspenders for providers that fall back or schemas that fail
        # to compile.
        if output_schema and self.structured_output_mode == "json_object":
            # No strict decoding available on this route. Ask for JSON and
            # nothing more; the schema is enforced after the fact by the
            # parser chain plus the caller's validity check. Deliberately no
            # ``require_parameters`` — on OpenRouter that flag is exactly what
            # removes the schema-less DeepSeek endpoint from the route.
            kwargs["response_format"] = {"type": "json_object"}
        elif output_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": f"{self.name}_output",
                    "strict": True,
                    "schema": output_schema,
                },
            }
            # Force OpenRouter to skip providers that don't support
            # response_format. Without this, an unsupported provider
            # would silently ignore the schema and return free-form
            # output.
            if self.provider == "openrouter":
                provider_pref = extra_body.setdefault("provider", {})
                provider_pref["require_parameters"] = True

        if extra_body:
            kwargs["extra_body"] = extra_body

        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except APIStatusError as e:
                if e.status_code not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES:
                    raise AgentAPIError(
                        f"Agent '{self.name}': API error {e.status_code}: {e.message}",
                        status_code=e.status_code,
                    ) from e
                delay = BASE_DELAY * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "Agent '%s': API error %d, retry %d/%d in %.1fs",
                    self.name,
                    e.status_code,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                import asyncio

                await asyncio.sleep(delay)
            except json.JSONDecodeError as e:
                if attempt == MAX_RETRIES:
                    raise AgentAPIError(
                        f"Agent '{self.name}': Malformed API response after {MAX_RETRIES} retries: {e}",
                    ) from e
                delay = BASE_DELAY * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "Agent '%s': Malformed API response, retry %d/%d in %.1fs: %s",
                    self.name, attempt + 1, MAX_RETRIES, delay, str(e)[:100],
                )
                import asyncio

                await asyncio.sleep(delay)

        # Unreachable, but satisfies type checker
        raise AgentAPIError(f"Agent '{self.name}': Retries exhausted")

    async def _execute_tool_call(self, tool_call: object) -> dict:
        """Execute a single tool call and return the tool result message."""
        fn = tool_call.function
        tool_name = fn.name

        tool = self._tool_map.get(tool_name)
        if not tool:
            error_msg = f"Tool '{tool_name}' not available for agent '{self.name}'"
            logger.error(error_msg)
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": f"Error: {error_msg}",
            }

        try:
            kwargs = json.loads(fn.arguments) if fn.arguments else {}
        except json.JSONDecodeError as e:
            error_msg = f"Invalid tool arguments for '{tool_name}': {e}"
            logger.error(error_msg)
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": f"Error: {error_msg}",
            }

        logger.info("Agent '%s': calling tool '%s' with %s", self.name, tool_name, kwargs)

        try:
            result = await tool.execute(**kwargs)
        except Exception as e:
            error_msg = f"Tool '{tool_name}' execution failed: {e}"
            logger.error(error_msg)
            return {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": f"Error: {error_msg}",
            }

        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result,
        }

    @staticmethod
    def _parse_json(text: str) -> dict | list | None:
        """Try to parse text as JSON, stripping markdown code fences if present.

        Includes repair steps for common malformed JSON from budget LLMs:
        1. Extract JSON from surrounding prose
        2. Remove trailing commas before } or ]
        3. Fix truncated JSON by appending missing closing brackets
        """
        import re as _re

        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines[1:] if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass

        # Repair 1: Extract JSON from surrounding prose
        first_brace = -1
        for i, ch in enumerate(text):
            if ch in "{[":
                first_brace = i
                break
        if first_brace >= 0:
            bracket = "}" if text[first_brace] == "{" else "]"
            last_bracket = text.rfind(bracket)
            if last_bracket > first_brace:
                extracted = text[first_brace : last_bracket + 1]
                try:
                    return json.loads(extracted)
                except (json.JSONDecodeError, ValueError):
                    text = extracted  # use extracted for subsequent repairs

        # Repair 2: Remove trailing commas before } or ]
        cleaned = _re.sub(r",\s*([}\]])", r"\1", text)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass

        # Repair 3: Fix truncated JSON by appending missing closing brackets
        try:
            json.loads(cleaned)
        except json.JSONDecodeError as e:
            if "Expecting" in str(e) or "Unterminated" in str(e) or "end of input" in str(e).lower():
                stack = []
                in_string = False
                escape = False
                for ch in cleaned:
                    if escape:
                        escape = False
                        continue
                    if ch == "\\":
                        escape = True
                        continue
                    if ch == '"' and not escape:
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if ch in "{[":
                        stack.append("}" if ch == "{" else "]")
                    elif ch in "}]":
                        if stack:
                            stack.pop()

                if stack:
                    closing = "".join(reversed(stack))
                    repaired = cleaned + closing
                    try:
                        result = json.loads(repaired)
                        logger.warning(
                            "Agent JSON repair: fixed truncated JSON (added %d closing brackets)",
                            len(stack),
                        )
                        return result
                    except (json.JSONDecodeError, ValueError):
                        pass

        return None

    @staticmethod
    def _extract_cost_usd(response: object) -> float | None:
        """Return OpenRouter's reported cost for this response, or None if absent.

        OpenRouter surfaces cost under ``response.usage.cost`` as a Pydantic
        ``model_extra`` field (accessible by attribute). Returning ``None``
        (rather than ``0.0``) lets the caller distinguish "provider omitted
        the field" from "provider reported zero cost".
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        cost = getattr(usage, "cost", None)
        if cost is None:
            return None
        try:
            return float(cost)
        except (TypeError, ValueError):
            return None

    def _cost_for(self, response: object) -> float | None:
        """Cost of one response, whoever served it.

        OpenRouter reports it directly. api.deepseek.com reports nothing, so
        it is computed from that response's own usage counters against the
        versioned price table — otherwise the primary channel for three
        stages would log 0.0 forever. An unpriced model returns ``None`` and
        says so loudly; the caller keeps ``cost_reported`` false rather than
        recording a fabricated zero.
        """
        reported = self._extract_cost_usd(response)
        if reported is not None:
            return reported
        if self.provider != "deepseek_direct":
            return None
        served = getattr(response, "model", None) or self.model
        cost = deepseek_direct_cost_usd(served, getattr(response, "usage", None))
        if cost is None:
            logger.warning(
                "Agent '%s': deepseek_direct served model %r is absent from the "
                "price table (%s) — cost cannot be computed and is reported as "
                "unmeasured. If the vendor rolled its alias, this is the "
                "tripwire; update DEEPSEEK_DIRECT_PRICES.",
                self.name, served, DEEPSEEK_DIRECT_PRICING_VERSION,
            )
        return cost

    async def _parse_or_retry_structured(
        self,
        messages: list[dict],
        content: str,
        output_schema: dict,
        tool_defs: list[dict] | None,
    ) -> tuple[str, dict | None, int, float, bool]:
        """Try to parse content as JSON. If it fails, retry with corrective prompt.

        With strict-mode ``response_format`` wired in ``_call_with_retry``,
        constrained decoding makes parse failures effectively impossible
        for agents that have a schema configured. This retry path is now
        a defensive fallback — it triggers only when a provider falls
        back, the schema fails to compile, or the agent has no schema.

        On retry, the schema is suppressed (``output_schema=None``) so
        the corrective prompt is not over-constrained: the model needs
        to satisfy the corrective instruction first; the schema would
        fight that.

        Returns: (final_content, structured_or_none, additional_tokens_used,
                  additional_cost_usd, cost_reported_any, additional_usage_missing_count)
        """
        additional_tokens = 0
        additional_cost = 0.0
        cost_reported = False
        usage_missing_count = 0

        parsed = self._parse_json(content)
        if parsed is not None:
            return content, parsed, 0, 0.0, False, 0

        corrective_message = (
            "Your previous response could not be parsed as valid JSON. "
            "Return ONLY a valid JSON object or array matching the requested schema. "
            "No markdown, no code fences, no explanatory text — just the raw JSON."
        )

        for attempt in range(1, MAX_STRUCTURED_RETRIES + 1):
            logger.info(
                "Agent '%s': structured output retry %d/%d",
                self.name,
                attempt,
                MAX_STRUCTURED_RETRIES,
            )

            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": corrective_message})

            response = await self._call_with_retry(
                messages, tools=None, output_schema=None,
            )
            choice = response.choices[0]
            content = choice.message.content or ""
            tokens, observed = _extract_response_tokens(response)
            additional_tokens += tokens
            if not observed:
                usage_missing_count += 1
            cost = self._cost_for(response)
            if cost is not None:
                additional_cost += cost
                cost_reported = True

            parsed = self._parse_json(content)
            if parsed is not None:
                return content, parsed, additional_tokens, additional_cost, cost_reported, usage_missing_count

        logger.warning(
            "Agent '%s': structured output parsing failed after %d retries",
            self.name,
            MAX_STRUCTURED_RETRIES,
        )
        return content, None, additional_tokens, additional_cost, cost_reported, usage_missing_count

    async def run(
        self,
        message: str = "",
        context: dict | None = None,
        output_schema: dict | None = None,
        instructions_addendum: str | None = None,
    ) -> AgentResult:
        """Run the agent: send message to LLM, handle tool calls, return result.

        Schema precedence: an explicit ``output_schema`` kwarg overrides the
        constructor default ``self.output_schema``. Most call sites should
        omit the kwarg and let the agent's configured schema apply.
        """
        start_time = time.monotonic()

        if output_schema is None:
            output_schema = self.output_schema

        system_prompt = self._build_system_prompt()
        memory = self._load_memory()
        user_message = self._build_user_message(
            message=message,
            context=context,
            memory=memory,
            instructions_addendum=instructions_addendum,
        )
        tool_defs = self._get_tool_definitions()

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        total_tokens = 0
        total_cost_usd = 0.0
        cost_reported = False
        usage_missing_count = 0
        all_tool_calls: list[dict] = []

        # Tool-call loop
        for iteration in range(MAX_TOOL_ITERATIONS):
            response = await self._call_with_retry(
                messages, tool_defs, output_schema=output_schema,
            )
            choice = response.choices[0]
            resp_message = choice.message

            tokens, observed = _extract_response_tokens(response)
            total_tokens += tokens
            if not observed:
                usage_missing_count += 1
            cost = self._cost_for(response)
            if cost is not None:
                total_cost_usd += cost
                cost_reported = True

            # No tool calls — we're done
            if not resp_message.tool_calls:
                break

            # Process tool calls
            messages.append(resp_message.model_dump())

            for tc in resp_message.tool_calls:
                all_tool_calls.append({
                    "tool": tc.function.name,
                    "arguments": tc.function.arguments,
                    "id": tc.id,
                })
                tool_result = await self._execute_tool_call(tc)
                messages.append(tool_result)

            logger.info(
                "Agent '%s': tool iteration %d, %d tool calls processed",
                self.name,
                iteration + 1,
                len(resp_message.tool_calls),
            )
        else:
            logger.warning(
                "Agent '%s': hit max tool iterations (%d)",
                self.name,
                MAX_TOOL_ITERATIONS,
            )

        duration = time.monotonic() - start_time
        content = resp_message.content or ""
        model_used = response.model if hasattr(response, "model") else self.model
        # OpenRouter reports which upstream served the call; a direct vendor
        # API has no such field. Fall back to the configured provider so
        # run_stage_log.jsonl always names the CHANNEL — otherwise every
        # deepseek_direct row would read "unknown" and channel C would be
        # indistinguishable from a broken OpenRouter response.
        provider_served = getattr(response, "provider", "") or ""
        if not provider_served and self.provider != "openrouter":
            provider_served = self.provider
        response_id = getattr(response, "id", "") or ""

        # Parse structured output if schema was requested, with retry
        structured = None
        if output_schema and content:
            (
                content,
                structured,
                extra_tokens,
                extra_cost,
                extra_cost_reported,
                extra_usage_missing,
            ) = await self._parse_or_retry_structured(
                messages, content, output_schema, tool_defs,
            )
            total_tokens += extra_tokens
            total_cost_usd += extra_cost
            cost_reported = cost_reported or extra_cost_reported
            usage_missing_count += extra_usage_missing

        if not cost_reported:
            logger.warning(
                "Agent '%s': provider did not report cost for model %s; "
                "cost_usd=0.0",
                self.name,
                model_used,
            )

        if usage_missing_count > 0 and duration > 30.0:
            logger.warning(
                "Agent '%s': provider did not report token usage on %d "
                "response(s) over a %.1fs call; tokens_used reflects only "
                "responses that did report usage. Likely an OpenRouter "
                "response-shape variance — output is otherwise correct.",
                self.name,
                usage_missing_count,
                duration,
            )

        # One line per call carrying everything an audit needs: the CHANNEL,
        # the model id AS ECHOED BY THE SERVER (the alias-drift tripwire — the
        # DeepSeek direct API serves 0731 under an undated alias and there is
        # no other way to notice a roll), the reasoning setting actually
        # configured, tokens, and cost. Standing rule, TASK-FLASH-0731-SWAP §3.
        logger.info(
            "Agent '%s': completed in %.1fs, %s tokens, %d tool calls "
            "| channel=%s served_model=%s reasoning=%r cost_usd=%s",
            self.name,
            duration,
            _format_tokens_for_log(total_tokens, usage_missing_count),
            len(all_tool_calls),
            provider_served or self.provider,
            model_used,
            self.reasoning,
            (f"{total_cost_usd:.6f}" if cost_reported else "unreported"),
        )

        self.last_cost_usd += total_cost_usd
        self.last_tokens += total_tokens
        # Record which model/provider served this call for loud stage logging.
        # For multi-call stages (e.g. HydrationPhase1's parallel chunk dispatch)
        # this reflects the last-completed call; all such calls share one model
        # config and a pinned provider, so the value is stable. `provider_served`
        # is "" when the response omits provider metadata — the runner maps that
        # to "unknown" rather than dropping the field.
        self.last_model_used = model_used
        self.last_provider_used = provider_served

        return AgentResult(
            content=content,
            structured=structured,
            tool_calls=all_tool_calls,
            tokens_used=total_tokens,
            cost_usd=total_cost_usd,
            model=model_used,
            duration_seconds=round(duration, 2),
            provider=provider_served,
            response_id=response_id,
        )
