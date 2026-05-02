"""Tests for the Agent abstraction.

These tests require a real OPENROUTER_API_KEY in the environment.
They call a cheap model (openai/gpt-4o-mini) via OpenRouter.
"""

import os
import tempfile

import pytest

from src.agent import Agent, AgentError, AgentResult
from src.tools.registry import Tool

HAS_API_KEY = bool(os.environ.get("OPENROUTER_API_KEY"))
skip_no_key = pytest.mark.skipif(not HAS_API_KEY, reason="No OPENROUTER_API_KEY")

MODEL = "google/gemini-3-flash-preview"


@pytest.fixture
def prompt_file(tmp_path: str) -> str:
    """Create a temporary AGENTS.md with a simple system prompt."""
    path = tmp_path / "AGENTS.md"
    path.write_text("You are a helpful test assistant. Be concise.")
    return str(path)


@pytest.fixture
def memory_file(tmp_path: str) -> str:
    """Create a temporary memory file."""
    path = tmp_path / "memory.md"
    path.write_text("The user's favorite color is blue.")
    return str(path)


def test_agent_requires_api_key(prompt_file: str) -> None:
    """Agent raises ValueError if no API key is provided or in env."""
    env_backup = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        with pytest.raises(ValueError, match="No API key"):
            Agent(name="test", model=MODEL, system_prompt_path=prompt_file, instructions_path=prompt_file, api_key=None)
    finally:
        if env_backup:
            os.environ["OPENROUTER_API_KEY"] = env_backup


def test_agent_missing_prompt_file(prompt_file: str) -> None:
    """Agent raises AgentError when a prompt file doesn't exist."""
    with pytest.raises(AgentError, match="not found"):
        Agent(
            name="test",
            model=MODEL,
            system_prompt_path="/nonexistent/SYSTEM.md",
            instructions_path=prompt_file,
            api_key="fake-key-for-unit-test",
        )


def test_build_system_prompt_only_system_md(prompt_file: str) -> None:
    """System message wraps SYSTEM.md only — no memory, no addendum, no schema."""
    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )
    prompt = agent._build_system_prompt()
    assert prompt.startswith("<system_prompt>")
    assert prompt.rstrip().endswith("</system_prompt>")
    assert "helpful test assistant" in prompt


def test_memory_appears_in_user_turn(prompt_file: str, memory_file: str) -> None:
    """Memory lives in the User-turn <memory> block, not the System turn."""
    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        memory_path=memory_file,
        api_key="fake-key-for-unit-test",
    )
    system_msg = agent._build_system_prompt()
    assert "favorite color is blue" not in system_msg

    memory = agent._load_memory()
    user_msg = agent._build_user_message(
        message="", context={"k": "v"}, memory=memory,
    )
    assert "<memory>" in user_msg and "</memory>" in user_msg
    assert "favorite color is blue" in user_msg


def test_build_user_message_three_blocks(prompt_file: str) -> None:
    """User message emits <context>, <memory> (when present), <instructions>."""
    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )
    msg = agent._build_user_message("Hello", context={"key": "value"})
    assert "<context>" in msg and "</context>" in msg
    assert "Hello" in msg
    assert '"key"' in msg
    assert '"value"' in msg
    assert "<instructions>" in msg and "</instructions>" in msg
    assert "<memory>" not in msg

    msg_with_mem = agent._build_user_message(
        "", context=None, memory="some memory",
    )
    assert "<context>" not in msg_with_mem
    assert "<memory>" in msg_with_mem
    assert "some memory" in msg_with_mem
    assert "<instructions>" in msg_with_mem


def test_build_user_message_with_addendum(prompt_file: str, tmp_path) -> None:
    """instructions_addendum is appended inside the <instructions> block."""
    instr = tmp_path / "INSTR.md"
    instr.write_text("Primary instruction body.")
    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=str(instr),
        api_key="fake-key-for-unit-test",
    )
    msg = agent._build_user_message(
        "", context=None, instructions_addendum="Follow-up addendum.",
    )
    body = msg.split("<instructions>")[1].split("</instructions>")[0]
    assert "Primary instruction body." in body
    assert "Follow-up addendum." in body
    # Addendum follows the primary content with a blank-line separator
    assert body.index("Primary") < body.index("Follow-up")


def test_tool_openai_format() -> None:
    """Tool.to_openai_format() returns correct structure."""
    tool = Tool(
        name="calc",
        description="A calculator",
        parameters={"type": "object", "properties": {"x": {"type": "number"}}},
        handler=lambda x: x * 2,
    )
    fmt = tool.to_openai_format()
    assert fmt["type"] == "function"
    assert fmt["function"]["name"] == "calc"
    assert fmt["function"]["description"] == "A calculator"


@skip_no_key
@pytest.mark.asyncio
async def test_agent_basic_call(prompt_file: str) -> None:
    """Agent can make a real LLM call and return an AgentResult."""
    agent = Agent(name="test", model=MODEL, system_prompt_path=prompt_file, instructions_path=prompt_file)
    result = await agent.run("Say hello in exactly one word.")

    assert isinstance(result, AgentResult)
    assert result.content
    assert result.tokens_used > 0
    assert result.model
    assert result.duration_seconds > 0


@skip_no_key
@pytest.mark.asyncio
async def test_agent_tool_loop(prompt_file: str) -> None:
    """Agent calls a tool in a loop and includes tool results."""

    def calculator(expression: str) -> str:
        return "42"

    calc_tool = Tool(
        name="calculator",
        description="Evaluates a math expression and returns the result.",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The math expression to evaluate",
                }
            },
            "required": ["expression"],
        },
        handler=calculator,
    )

    agent = Agent(
        name="test-tools",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        tools=[calc_tool],
    )

    result = await agent.run(
        "Use the calculator tool to compute 6 * 7. "
        "Call the tool, then tell me the result."
    )

    assert isinstance(result, AgentResult)
    assert result.content
    assert len(result.tool_calls) > 0
    assert result.tool_calls[0]["tool"] == "calculator"


def test_parse_structured_strips_fences(prompt_file: str) -> None:
    """JSON parsing correctly strips markdown code fences."""
    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )
    content = '```json\n{"city": "Paris", "country": "France"}\n```'
    result = agent._parse_json(content)
    assert result == {"city": "Paris", "country": "France"}


def test_parse_structured_handles_plain_json(prompt_file: str) -> None:
    """JSON parsing handles plain JSON without fences."""
    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )
    content = '{"city": "Paris", "country": "France"}'
    result = agent._parse_json(content)
    assert result == {"city": "Paris", "country": "France"}

    # Also works with arrays
    content_arr = '[{"a": 1}, {"b": 2}]'
    result_arr = agent._parse_json(content_arr)
    assert result_arr == [{"a": 1}, {"b": 2}]


@skip_no_key
@pytest.mark.asyncio
async def test_structured_retry_recovers(prompt_file: str) -> None:
    """Agent returns structured output under strict-mode schema.

    With strict-mode response_format wired in ``_call_with_retry``, parse
    failures are effectively impossible — constrained decoding cannot emit
    non-conforming JSON. The ``_parse_or_retry_structured`` fallback
    remains for providers that silently ignore the schema, but does not
    fire on the happy path. This test verifies the happy path under
    strict mode.
    """
    schema = {
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "country": {"type": "string"},
            "population": {"type": "string"},
        },
        "required": ["city", "country", "population"],
        "additionalProperties": False,
    }

    agent = Agent(name="test-retry", model=MODEL, system_prompt_path=prompt_file, instructions_path=prompt_file)
    result = await agent.run(
        "Tell me about Paris and also return your answer as JSON "
        "with keys: city, country, population.",
        output_schema=schema,
    )

    assert result.structured is not None
    assert "city" in result.structured


@skip_no_key
@pytest.mark.asyncio
async def test_agent_structured_output(prompt_file: str) -> None:
    """Agent can return structured JSON output when given a schema."""
    schema = {
        "type": "object",
        "properties": {
            "greeting": {"type": "string"},
            "language": {"type": "string"},
        },
        "required": ["greeting", "language"],
        "additionalProperties": False,
    }

    agent = Agent(name="test-structured", model=MODEL, system_prompt_path=prompt_file, instructions_path=prompt_file)
    result = await agent.run(
        'Return a greeting in French as JSON with two string fields: '
        '"greeting" (the salutation) and "language" (the language code "fr").',
        output_schema=schema,
    )

    assert result.structured is not None
    assert "greeting" in result.structured
    assert "language" in result.structured


# ---------------------------------------------------------------------------
# JSONDecodeError retry tests (no API key needed)
# ---------------------------------------------------------------------------

import json
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_agent_retries_on_json_decode_error(prompt_file: str) -> None:
    """Agent retries transient JSONDecodeError from the OpenAI client."""
    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"
    mock_response.choices[0].message.tool_calls = None
    mock_response.usage.total_tokens = 10
    mock_response.model = MODEL

    json_err = json.JSONDecodeError("Expecting value", doc="", pos=0)
    agent._client.chat.completions.create = AsyncMock(
        side_effect=[json_err, json_err, mock_response]
    )

    result = await agent.run("test message")
    assert result.content == "ok"
    assert agent._client.chat.completions.create.call_count == 3


@pytest.mark.asyncio
async def test_agent_raises_after_max_json_decode_retries(prompt_file: str) -> None:
    """Agent raises AgentAPIError after MAX_RETRIES JSONDecodeErrors."""
    from src.agent import AgentAPIError

    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )

    json_err = json.JSONDecodeError("Expecting value", doc="", pos=0)
    agent._client.chat.completions.create = AsyncMock(side_effect=json_err)

    with pytest.raises(AgentAPIError, match="Malformed API response"):
        await agent.run("test message")


# ---------------------------------------------------------------------------
# Bug-4 — token-usage logging when the provider omits `usage`
# ---------------------------------------------------------------------------


def test_format_tokens_for_log_unknown_when_zero_and_missing():
    from src.agent import _format_tokens_for_log
    assert _format_tokens_for_log(0, 1) == "unknown"
    assert _format_tokens_for_log(0, 5) == "unknown"


def test_format_tokens_for_log_partial_when_some_observed_some_missing():
    from src.agent import _format_tokens_for_log
    out = _format_tokens_for_log(1234, 2)
    assert "1234+" in out
    assert "missing on 2" in out


def test_format_tokens_for_log_clean_count_when_all_observed():
    from src.agent import _format_tokens_for_log
    assert _format_tokens_for_log(1234, 0) == "1234"
    assert _format_tokens_for_log(0, 0) == "0"


def test_extract_response_tokens_counts_observed_usage():
    from src.agent import _extract_response_tokens
    response = MagicMock()
    response.usage.total_tokens = 4321
    tokens, observed = _extract_response_tokens(response)
    assert tokens == 4321
    assert observed is True


def test_extract_response_tokens_handles_missing_usage_object():
    from src.agent import _extract_response_tokens
    response = MagicMock()
    response.usage = None
    tokens, observed = _extract_response_tokens(response)
    assert tokens == 0
    assert observed is False


def test_extract_response_tokens_handles_missing_total_tokens_field():
    from src.agent import _extract_response_tokens
    response = MagicMock()
    response.usage.total_tokens = None
    tokens, observed = _extract_response_tokens(response)
    assert tokens == 0
    assert observed is False


@pytest.mark.asyncio
async def test_agent_run_logs_unknown_when_response_usage_is_none(
    prompt_file: str, caplog
) -> None:
    """Bug-4 regression: provider returns response with usage=None.
    Agent must log 'unknown' for tokens AND emit a WARNING when the call
    duration is non-trivial. Output is otherwise correct."""
    import logging
    agent = Agent(
        name="test",
        model=MODEL,
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"
    mock_response.choices[0].message.tool_calls = None
    mock_response.usage = None  # <-- the bug-4 case
    mock_response.model = MODEL

    agent._client.chat.completions.create = AsyncMock(return_value=mock_response)

    with caplog.at_level(logging.INFO):
        result = await agent.run("test message")

    # Output is correct
    assert result.content == "ok"
    # tokens_used in AgentResult stays 0 (downstream API stable)
    assert result.tokens_used == 0
    # But the log line surfaces "unknown" rather than silently reporting 0
    completed_lines = [r.message for r in caplog.records if "completed in" in r.message]
    assert completed_lines, "agent must emit a 'completed in' log line"
    assert "unknown" in completed_lines[-1], (
        f"expected 'unknown' in log when usage=None; got {completed_lines[-1]!r}"
    )
