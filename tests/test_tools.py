"""Tests for the tool system.

Unit tests run without API key. Integration tests require various API keys.
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
    x_search_tool,
)
from src.tools.file_ops import read_file_handler, write_file_handler
from src.tools.web_search import PROVIDERS, _format_results, web_search_handler

HAS_OPENROUTER_KEY = bool(os.environ.get("OPENROUTER_API_KEY"))
HAS_BRAVE_KEY = bool(os.environ.get("BRAVE_API_KEY"))
HAS_XAI_KEY = bool(os.environ.get("XAI_API_KEY"))
HAS_OLLAMA_KEY = bool(os.environ.get("OLLAMA_API_KEY"))

skip_no_openrouter = pytest.mark.skipif(
    not HAS_OPENROUTER_KEY, reason="No OPENROUTER_API_KEY"
)
skip_no_brave = pytest.mark.skipif(not HAS_BRAVE_KEY, reason="No BRAVE_API_KEY")
skip_no_xai = pytest.mark.skipif(not HAS_XAI_KEY, reason="No XAI_API_KEY")
skip_no_ollama = pytest.mark.skipif(not HAS_OLLAMA_KEY, reason="No OLLAMA_API_KEY")


def _ollama_local_available() -> bool:
    """Check if local Ollama is reachable."""
    import httpx as _httpx

    try:
        r = _httpx.get("http://localhost:11434/api/version", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


skip_no_ollama_local = pytest.mark.skipif(
    not _ollama_local_available(), reason="Local Ollama not running on localhost:11434"
)


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
    """create_default_registry() returns a registry with all 5 tools."""
    registry = create_default_registry()
    assert registry.get("web_search") is not None
    assert registry.get("x_search") is not None
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
# Multi-provider web search — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_search_unknown_provider() -> None:
    """Unknown provider returns error string."""
    result = await web_search_handler("test", provider="nonexistent")
    assert "Error:" in result
    assert "Unknown search provider" in result
    assert "nonexistent" in result


def test_web_search_format_results() -> None:
    """_format_results() formats items correctly."""
    items = [
        {"title": "Title 1", "url": "https://example.com/1", "content": "Summary 1"},
        {"title": "Title 2", "url": "https://example.com/2", "content": "Summary 2"},
    ]
    result = _format_results("test query", items, 5)
    assert "Results for: test query" in result
    assert "1. Title 1" in result
    assert "https://example.com/1" in result
    assert "Summary 1" in result
    assert "2. Title 2" in result


def test_web_search_format_results_empty() -> None:
    """_format_results() handles empty results."""
    result = _format_results("test query", [], 5)
    assert "No results for: test query" in result


def test_web_search_format_results_limits() -> None:
    """_format_results() respects the n limit."""
    items = [
        {"title": f"Title {i}", "url": f"https://example.com/{i}", "content": ""}
        for i in range(10)
    ]
    result = _format_results("query", items, 3)
    assert "3. Title 2" in result
    assert "4." not in result


def test_web_search_default_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """IW_SEARCH_PROVIDER env var is respected at module level."""
    # The DEFAULT_PROVIDER is read at import time, so we test the handler's
    # fallback logic by passing provider=None and checking it doesn't crash
    # (it will use whatever DEFAULT_PROVIDER was set at import time).
    # For a more direct test, we verify the module-level constant exists.
    from src.tools.web_search import DEFAULT_PROVIDER

    assert isinstance(DEFAULT_PROVIDER, str)
    assert DEFAULT_PROVIDER in ("perplexity", "brave", "grok", "grok_x", "ollama", "duckduckgo")


def test_web_search_ollama_provider_in_list() -> None:
    """'ollama' is in the PROVIDERS dict."""
    assert "ollama" in PROVIDERS


def test_agent_provider_defaults_openrouter() -> None:
    """Default provider remains openrouter with correct base_url."""
    from src.agent import Agent, PROVIDER_DEFAULTS

    assert PROVIDER_DEFAULTS["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"

    agent = Agent(
        name="test",
        model="test-model",
        prompt_path="agents/test/AGENTS.md",
        api_key="test-key",
    )
    assert agent.provider == "openrouter"
    assert agent.base_url == "https://openrouter.ai/api/v1"


def test_agent_provider_defaults_ollama() -> None:
    """provider='ollama' sets localhost base_url and dummy key."""
    from src.agent import Agent

    agent = Agent(
        name="test",
        model="qwen3:4b",
        prompt_path="agents/test/AGENTS.md",
        provider="ollama",
    )
    assert agent.base_url == "http://localhost:11434/v1"
    assert agent.provider == "ollama"


def test_agent_provider_defaults_ollama_cloud() -> None:
    """provider='ollama_cloud' sets ollama.com base_url."""
    from src.agent import Agent

    agent = Agent(
        name="test",
        model="gpt-oss:20b-cloud",
        prompt_path="agents/test/AGENTS.md",
        provider="ollama_cloud",
        api_key="test-ollama-key",
    )
    assert agent.base_url == "https://ollama.com/v1"
    assert agent.provider == "ollama_cloud"


def test_x_search_tool_definition() -> None:
    """x_search_tool has correct OpenAI format."""
    fmt = x_search_tool.to_openai_format()
    assert fmt["type"] == "function"
    assert fmt["function"]["name"] == "x_search"
    assert "query" in fmt["function"]["parameters"]["properties"]


def test_web_search_tool_has_provider_param() -> None:
    """web_search_tool includes provider in parameters."""
    props = web_search_tool.to_openai_format()["function"]["parameters"]["properties"]
    assert "provider" in props
    assert "enum" in props["provider"]


# ---------------------------------------------------------------------------
# Integration tests — require respective API keys
# ---------------------------------------------------------------------------


@skip_no_openrouter
@pytest.mark.asyncio
async def test_web_search_returns_results() -> None:
    """web_search returns results for a known query (backward compat)."""
    result = await web_search_handler("Python programming language Wikipedia")
    assert len(result) > 50
    assert "Error:" not in result


@skip_no_openrouter
@pytest.mark.asyncio
async def test_search_perplexity() -> None:
    """Perplexity provider returns results via OpenRouter."""
    result = await web_search_handler(
        "Python programming language", provider="perplexity"
    )
    assert len(result) > 50
    assert "Error:" not in result


@skip_no_brave
@pytest.mark.asyncio
async def test_search_brave() -> None:
    """Brave provider returns formatted results."""
    result = await web_search_handler(
        "Python programming language", provider="brave"
    )
    assert len(result) > 50
    assert "Error:" not in result


@skip_no_xai
@pytest.mark.asyncio
async def test_search_grok_web() -> None:
    """Grok web search returns results."""
    result = await web_search_handler(
        "Python programming language", provider="grok"
    )
    assert len(result) > 50
    assert "Error:" not in result


@skip_no_xai
@pytest.mark.asyncio
async def test_search_grok_x() -> None:
    """Grok X/Twitter search returns results."""
    result = await web_search_handler(
        "Python programming language", provider="grok_x"
    )
    assert len(result) > 20
    assert "Error:" not in result


@pytest.mark.asyncio
async def test_search_duckduckgo() -> None:
    """DuckDuckGo search returns results (or graceful import error)."""
    result = await web_search_handler(
        "Python programming language", provider="duckduckgo"
    )
    # Either returns results or a graceful import error
    assert len(result) > 20
    assert "Error: DuckDuckGo search failed:" not in result


@skip_no_openrouter
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


# ---------------------------------------------------------------------------
# Ollama integration tests — require OLLAMA_API_KEY
# ---------------------------------------------------------------------------


@skip_no_ollama
@pytest.mark.asyncio
async def test_search_ollama() -> None:
    """Ollama Web Search API returns results."""
    result = await web_search_handler(
        "Python programming language", provider="ollama"
    )
    assert len(result) > 50
    assert "Error:" not in result


@skip_no_ollama
@pytest.mark.asyncio
async def test_fetch_via_ollama() -> None:
    """Ollama Web Fetch API returns clean text."""
    from src.tools.web_fetch import _fetch_via_ollama

    result = await _fetch_via_ollama("https://httpbin.org/html")
    assert result is not None
    assert len(result) > 50


@skip_no_ollama
@pytest.mark.asyncio
async def test_agent_ollama_cloud() -> None:
    """Agent with provider='ollama_cloud' can make a simple chat call."""
    from src.agent import Agent

    agent = Agent(
        name="test-ollama-cloud",
        model="gpt-oss:20b-cloud",
        prompt_path="agents/test/AGENTS.md",
        provider="ollama_cloud",
    )

    result = await agent.run("Say hello in one sentence.")
    assert result.content
    assert len(result.content) > 0


# ---------------------------------------------------------------------------
# Local Ollama tests — require running Ollama instance
# ---------------------------------------------------------------------------


@skip_no_ollama_local
@pytest.mark.asyncio
async def test_agent_ollama_local() -> None:
    """Agent with provider='ollama' can call a local model."""
    from src.agent import Agent

    agent = Agent(
        name="test-ollama-local",
        model="qwen3:4b",
        prompt_path="agents/test/AGENTS.md",
        provider="ollama",
    )

    result = await agent.run("Say hello in one sentence.")
    assert result.content
    assert len(result.content) > 0
