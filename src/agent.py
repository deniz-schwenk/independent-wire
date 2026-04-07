"""Independent Wire — Agent abstraction.

An Agent is a configured async LLM caller with identity, model, tools, memory,
and temperature. It calls the OpenRouter API (OpenAI-compatible), handles tool
calls in a loop, and returns structured AgentResult objects.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path

from openai import AsyncOpenAI, APIStatusError

from src.models import AgentResult
from src.tools.registry import Tool

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
}


class AgentError(Exception):
    """Base exception for agent errors."""


class AgentAPIError(AgentError):
    """Raised when the LLM API returns a non-retryable error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentTimeoutError(AgentError):
    """Raised when the LLM API call times out."""


class Agent:
    """A configured LLM caller with identity, model, tools, and memory."""

    def __init__(
        self,
        name: str,
        model: str,
        prompt_path: str,
        tools: list[Tool] | None = None,
        memory_path: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 65536,
        provider: str = "openrouter",
        base_url: str | None = None,
        api_key: str | None = None,
        reasoning: str | bool | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.prompt_path = prompt_path
        self.tools = tools or []
        self.memory_path = memory_path
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.provider = provider
        self.reasoning = reasoning

        # Resolve provider defaults
        defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openrouter"])
        self.base_url = base_url or defaults["base_url"]

        # Resolve API key: explicit > env var > provider default > error
        resolved_key = api_key
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
        )

        # Build tool lookup for fast access during tool-call loop
        self._tool_map: dict[str, Tool] = {t.name: t for t in self.tools}

    def _load_system_prompt(self) -> str:
        """Load system prompt from prompt_path file."""
        path = Path(self.prompt_path)
        if not path.exists():
            raise AgentError(
                f"Agent '{self.name}': Prompt file not found: {self.prompt_path}"
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

    def _build_system_prompt(self, output_schema: dict | None = None) -> str:
        """Build the full system prompt with optional memory and schema instructions."""
        prompt = self._load_system_prompt()

        memory = self._load_memory()
        if memory:
            prompt += f"\n\n---\n\n## Memory\n\n{memory}"

        if output_schema:
            schema_str = json.dumps(output_schema, indent=2, ensure_ascii=False)
            prompt += (
                f"\n\n---\n\n## Output Format\n\n"
                f"Respond with JSON matching this schema:\n\n```json\n{schema_str}\n```\n\n"
                f"Return ONLY the JSON object, no additional text."
            )

        return prompt

    def _build_user_message(self, message: str, context: dict | None = None) -> str:
        """Build the user message, optionally embedding context."""
        if not context:
            return message
        context_str = json.dumps(context, indent=2, ensure_ascii=False)
        return f"{message}\n\n---\n\nContext:\n```json\n{context_str}\n```"

    def _get_tool_definitions(self) -> list[dict] | None:
        """Get OpenAI-format tool definitions, or None if no tools."""
        if not self.tools:
            return None
        return [t.to_openai_format() for t in self.tools]

    async def _call_with_retry(
        self, messages: list[dict], tools: list[dict] | None
    ) -> object:
        """Call the LLM API with exponential backoff retry for transient errors."""
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        # Map reasoning parameter to provider-specific extra_body
        extra_body: dict = {}
        if self.reasoning is not None:
            if self.provider == "openrouter":
                if isinstance(self.reasoning, bool):
                    extra_body["reasoning"] = {
                        "effort": "high" if self.reasoning else "minimal"
                    }
                elif isinstance(self.reasoning, str):
                    extra_body["reasoning"] = {"effort": self.reasoning}
            elif self.provider in ("ollama", "ollama_cloud"):
                if isinstance(self.reasoning, bool):
                    extra_body["think"] = self.reasoning
                elif isinstance(self.reasoning, str):
                    extra_body["think"] = self.reasoning
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

    async def _parse_or_retry_structured(
        self,
        messages: list[dict],
        content: str,
        output_schema: dict,
        tool_defs: list[dict] | None,
    ) -> tuple[str, dict | None, int]:
        """Try to parse content as JSON. If it fails, retry with corrective prompt.

        Returns: (final_content, structured_or_none, additional_tokens_used)
        """
        additional_tokens = 0

        parsed = self._parse_json(content)
        if parsed is not None:
            return content, parsed, 0

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

            response = await self._call_with_retry(messages, tools=None)
            choice = response.choices[0]
            content = choice.message.content or ""
            additional_tokens += response.usage.total_tokens if response.usage else 0

            parsed = self._parse_json(content)
            if parsed is not None:
                return content, parsed, additional_tokens

        logger.warning(
            "Agent '%s': structured output parsing failed after %d retries",
            self.name,
            MAX_STRUCTURED_RETRIES,
        )
        return content, None, additional_tokens

    async def run(
        self,
        message: str,
        context: dict | None = None,
        output_schema: dict | None = None,
    ) -> AgentResult:
        """Run the agent: send message to LLM, handle tool calls, return result."""
        start_time = time.monotonic()

        system_prompt = self._build_system_prompt(output_schema)
        user_message = self._build_user_message(message, context)
        tool_defs = self._get_tool_definitions()

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        total_tokens = 0
        all_tool_calls: list[dict] = []

        # Tool-call loop
        for iteration in range(MAX_TOOL_ITERATIONS):
            response = await self._call_with_retry(messages, tool_defs)
            choice = response.choices[0]
            resp_message = choice.message

            total_tokens += response.usage.total_tokens if response.usage else 0

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

        # Parse structured output if schema was requested, with retry
        structured = None
        if output_schema and content:
            content, structured, extra_tokens = await self._parse_or_retry_structured(
                messages, content, output_schema, tool_defs,
            )
            total_tokens += extra_tokens

        logger.info(
            "Agent '%s': completed in %.1fs, %d tokens, %d tool calls",
            self.name,
            duration,
            total_tokens,
            len(all_tool_calls),
        )

        return AgentResult(
            content=content,
            structured=structured,
            tool_calls=all_tool_calls,
            tokens_used=total_tokens,
            cost_usd=0.0,  # cost estimation deferred to config/pricing layer
            model=model_used,
            duration_seconds=round(duration, 2),
        )
