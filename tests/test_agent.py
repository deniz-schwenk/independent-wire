"""Tests for the Agent abstraction.

These tests require a real OPENROUTER_API_KEY in the environment.
They call a cheap model (openai/gpt-4o-mini) via OpenRouter.
"""

import os
import tempfile

import pytest

from src.agent import Agent, AgentError
from src.models import AgentResult
from src.tools.registry import Tool

HAS_API_KEY = bool(os.environ.get("OPENROUTER_API_KEY"))
skip_no_key = pytest.mark.skipif(not HAS_API_KEY, reason="No OPENROUTER_API_KEY")

MODEL = "openai/gpt-4o-mini"


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
            Agent(name="test", model=MODEL, prompt_path=prompt_file, api_key=None)
    finally:
        if env_backup:
            os.environ["OPENROUTER_API_KEY"] = env_backup


def test_agent_missing_prompt_file() -> None:
    """Agent raises AgentError if prompt file doesn't exist."""
    agent = Agent(
        name="test",
        model=MODEL,
        prompt_path="/nonexistent/AGENTS.md",
        api_key="fake-key-for-unit-test",
    )
    with pytest.raises(AgentError, match="Prompt file not found"):
        agent._load_system_prompt()


def test_build_system_prompt_with_memory(prompt_file: str, memory_file: str) -> None:
    """System prompt includes memory content when memory_path is set."""
    agent = Agent(
        name="test",
        model=MODEL,
        prompt_path=prompt_file,
        memory_path=memory_file,
        api_key="fake-key-for-unit-test",
    )
    prompt = agent._build_system_prompt()
    assert "helpful test assistant" in prompt
    assert "favorite color is blue" in prompt


def test_build_system_prompt_with_schema(prompt_file: str) -> None:
    """System prompt includes schema instruction when output_schema is provided."""
    agent = Agent(
        name="test",
        model=MODEL,
        prompt_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    prompt = agent._build_system_prompt(output_schema=schema)
    assert "Output Format" in prompt
    assert '"answer"' in prompt


def test_build_user_message_with_context(prompt_file: str) -> None:
    """User message includes context JSON when provided."""
    agent = Agent(
        name="test",
        model=MODEL,
        prompt_path=prompt_file,
        api_key="fake-key-for-unit-test",
    )
    msg = agent._build_user_message("Hello", context={"key": "value"})
    assert "Hello" in msg
    assert '"key"' in msg
    assert '"value"' in msg


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
    agent = Agent(name="test", model=MODEL, prompt_path=prompt_file)
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
        prompt_path=prompt_file,
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
    }

    agent = Agent(name="test-structured", model=MODEL, prompt_path=prompt_file)
    result = await agent.run(
        "Return a greeting in French.",
        output_schema=schema,
    )

    assert result.structured is not None
    assert "greeting" in result.structured
    assert "language" in result.structured
