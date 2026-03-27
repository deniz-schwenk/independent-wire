"""Tests for the tool system.

Unit tests run without API key. Integration tests require OPENROUTER_API_KEY.
"""

import os

import pytest

from src.tools import (
    Tool,
    ToolRegistry,
    create_default_registry,
    read_file_tool,
    web_fetch_tool,
    web_search_tool,
    write_file_tool,
)
from src.tools.file_ops import read_file_handler, write_file_handler

HAS_API_KEY = bool(os.environ.get("OPENROUTER_API_KEY"))
skip_no_key = pytest.mark.skipif(not HAS_API_KEY, reason="No OPENROUTER_API_KEY")


# ---------------------------------------------------------------------------
# Unit tests — no API key needed
# ---------------------------------------------------------------------------


def test_tool_to_openai_format() -> None:
    """Tool.to_openai_format() returns correct structure."""
    fmt = web_search_tool.to_openai_format()
    assert fmt["type"] == "function"
    assert fmt["function"]["name"] == "web_search"
    assert "query" in fmt["function"]["parameters"]["properties"]


def test_registry_register_and_get() -> None:
    """Registry stores and retrieves tools by name."""
    registry = ToolRegistry()
    registry.register(read_file_tool)
    assert registry.get("read_file") is read_file_tool
    assert registry.get("nonexistent") is None


def test_registry_get_for_agent() -> None:
    """Registry filters tools by allowed names."""
    registry = create_default_registry()
    tools = registry.get_for_agent(["read_file", "write_file"])
    names = [t.name for t in tools]
    assert names == ["read_file", "write_file"]
    assert len(tools) == 2


def test_registry_get_for_agent_ignores_unknown() -> None:
    """Registry silently ignores unknown tool names."""
    registry = create_default_registry()
    tools = registry.get_for_agent(["read_file", "does_not_exist"])
    assert len(tools) == 1
    assert tools[0].name == "read_file"


def test_create_default_registry() -> None:
    """create_default_registry() returns a registry with all 4 tools."""
    registry = create_default_registry()
    assert registry.get("web_search") is not None
    assert registry.get("web_fetch") is not None
    assert registry.get("read_file") is not None
    assert registry.get("write_file") is not None


def test_read_file(tmp_path: str) -> None:
    """read_file reads an existing file."""
    path = tmp_path / "test.txt"
    path.write_text("hello world", encoding="utf-8")
    result = read_file_handler(str(path))
    assert result == "hello world"


def test_read_file_not_found() -> None:
    """read_file returns error for missing file."""
    result = read_file_handler("/nonexistent/file.txt")
    assert result.startswith("Error:")


def test_write_file(tmp_path: str) -> None:
    """write_file writes content to a file."""
    path = tmp_path / "output.txt"
    result = write_file_handler(str(path), "test content")
    assert "Successfully wrote" in result
    assert path.read_text(encoding="utf-8") == "test content"


def test_write_file_creates_directories(tmp_path: str) -> None:
    """write_file creates parent directories if they don't exist."""
    path = tmp_path / "a" / "b" / "c" / "output.txt"
    result = write_file_handler(str(path), "nested content")
    assert "Successfully wrote" in result
    assert path.read_text(encoding="utf-8") == "nested content"


@pytest.mark.asyncio
async def test_web_fetch() -> None:
    """web_fetch retrieves a real web page."""
    from src.tools.web_fetch import web_fetch_handler

    result = await web_fetch_handler("https://httpbin.org/html", max_chars=5000)
    assert "Herman Melville" in result


@pytest.mark.asyncio
async def test_web_fetch_truncation() -> None:
    """web_fetch truncates content at max_chars."""
    from src.tools.web_fetch import web_fetch_handler

    result = await web_fetch_handler("https://httpbin.org/html", max_chars=100)
    assert "[Truncated at 100 characters]" in result


@pytest.mark.asyncio
async def test_web_fetch_bad_url() -> None:
    """web_fetch returns error for unreachable URL."""
    from src.tools.web_fetch import web_fetch_handler

    result = await web_fetch_handler("https://httpbin.org/status/404")
    assert "Error:" in result


@pytest.mark.asyncio
async def test_tool_execute_sync_handler(tmp_path: str) -> None:
    """Tool.execute() works with synchronous handlers via asyncio.to_thread."""
    path = tmp_path / "exec_test.txt"
    path.write_text("via execute", encoding="utf-8")
    result = await read_file_tool.execute(path=str(path))
    assert result == "via execute"


# ---------------------------------------------------------------------------
# Integration tests — require OPENROUTER_API_KEY
# ---------------------------------------------------------------------------


@skip_no_key
@pytest.mark.asyncio
async def test_web_search_returns_results() -> None:
    """web_search returns results for a known query."""
    from src.tools.web_search import web_search_handler

    result = await web_search_handler("Python programming language Wikipedia")
    assert len(result) > 50
    assert "Error:" not in result


@skip_no_key
@pytest.mark.asyncio
async def test_agent_with_web_search_tool() -> None:
    """Agent uses web_search tool to answer a question."""
    from src.agent import Agent

    agent = Agent(
        name="test-search",
        model="openai/gpt-4o-mini",
        prompt_path="agents/test/AGENTS.md",
        tools=[web_search_tool],
    )

    result = await agent.run(
        "Use the web_search tool to find: what year was the Python programming "
        "language first released? Call the tool, then answer."
    )

    assert result.content
    assert len(result.tool_calls) > 0
    assert result.tool_calls[0]["tool"] == "web_search"
