"""Independent Wire — Multi-provider web search tool."""

import logging
import os
from typing import Any

import httpx
from openai import AsyncOpenAI

from src.tools.registry import Tool

logger = logging.getLogger(__name__)

# Default provider, overridable via env var
DEFAULT_PROVIDER = os.environ.get("IW_SEARCH_PROVIDER", "perplexity")


def _format_results(query: str, items: list[dict[str, Any]], n: int) -> str:
    """Format search results into consistent plaintext output."""
    if not items:
        return f"No results for: {query}"
    lines = [f"Results for: {query}\n"]
    for i, item in enumerate(items[:n], 1):
        title = item.get("title", "").strip()
        url = item.get("url", "")
        snippet = item.get("content", "").strip()
        lines.append(f"{i}. {title}\n   {url}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


async def _search_perplexity(query: str, n: int) -> str:
    """Search via Perplexity sonar-pro on OpenRouter. No extra API key needed."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return "Error: OPENROUTER_API_KEY not set"

    client = AsyncOpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    try:
        response = await client.chat.completions.create(
            model="perplexity/sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a web search assistant. Search for the query and return "
                        "structured results. For each result include: title, URL, and a "
                        "brief summary. Return results as a JSON array with objects having "
                        "'title', 'url', and 'content' keys. Be factual and concise."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Search for: {query}\n\nReturn up to {n} results.",
                },
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        return response.choices[0].message.content or "No results found"
    except Exception as e:
        return f"Error: Perplexity search failed: {e}"


async def _search_brave(query: str, n: int) -> str:
    """Search via Brave Search API. Needs BRAVE_API_KEY."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        logger.warning("BRAVE_API_KEY not set, falling back to DuckDuckGo")
        return await _search_duckduckgo(query, n)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": n},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
                timeout=10.0,
            )
            r.raise_for_status()
        items = [
            {
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "content": x.get("description", ""),
            }
            for x in r.json().get("web", {}).get("results", [])
        ]
        return _format_results(query, items, n)
    except Exception as e:
        return f"Error: Brave search failed: {e}"


async def _search_grok_web(query: str, n: int) -> str:
    """Search via xAI Grok web_search. Needs XAI_API_KEY.

    Uses the xAI Responses API with server-side web_search tool.
    Grok searches the web autonomously and returns results with citations.
    """
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        logger.warning("XAI_API_KEY not set, falling back to DuckDuckGo")
        return await _search_duckduckgo(query, n)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.x.ai/v1/responses",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": "grok-3-fast",
                    "input": [
                        {
                            "role": "user",
                            "content": (
                                f"Search the web for: {query}\n\n"
                                f"Return the top {n} results with title, URL, and brief summary for each."
                            ),
                        }
                    ],
                    "tools": [{"type": "web_search"}],
                },
                timeout=30.0,
            )
            r.raise_for_status()

        data = r.json()
        output = data.get("output", [])
        text_parts = []
        for item in output:
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text", ""))

        return "\n".join(text_parts) if text_parts else "No results found"
    except Exception as e:
        return f"Error: Grok web search failed: {e}"


async def _search_grok_x(query: str, n: int) -> str:
    """Search X/Twitter via xAI Grok x_search. Needs XAI_API_KEY.

    Searches posts, users, and threads on X. Useful for finding
    social media perspectives and narratives on a topic.
    """
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return "Error: XAI_API_KEY not set (required for X/Twitter search)"

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.x.ai/v1/responses",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": "grok-3-fast",
                    "input": [
                        {
                            "role": "user",
                            "content": (
                                f"Search X/Twitter for: {query}\n\n"
                                f"Return the top {n} relevant posts with author, content, and any key context."
                            ),
                        }
                    ],
                    "tools": [{"type": "x_search"}],
                },
                timeout=30.0,
            )
            r.raise_for_status()

        data = r.json()
        output = data.get("output", [])
        text_parts = []
        for item in output:
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text", ""))

        return "\n".join(text_parts) if text_parts else "No results found"
    except Exception as e:
        return f"Error: Grok X search failed: {e}"


async def _search_ollama(query: str, n: int) -> str:
    """Search via Ollama Web Search API. Needs OLLAMA_API_KEY."""
    api_key = os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        logger.warning("OLLAMA_API_KEY not set, falling back to DuckDuckGo")
        return await _search_duckduckgo(query, n)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://ollama.com/api/web_search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query},
                timeout=15.0,
            )
            r.raise_for_status()

        items = r.json().get("results", [])
        return _format_results(query, items, n)
    except Exception as e:
        return f"Error: Ollama search failed: {e}"


async def _search_duckduckgo(query: str, n: int) -> str:
    """Search via DuckDuckGo. No API key needed. Fallback provider."""
    try:
        import asyncio

        from ddgs import DDGS

        ddgs = DDGS(timeout=10)
        raw = await asyncio.to_thread(ddgs.text, query, max_results=n)
        if not raw:
            return f"No results for: {query}"
        items = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "content": r.get("body", ""),
            }
            for r in raw
        ]
        return _format_results(query, items, n)
    except ImportError:
        return (
            "Error: DuckDuckGo search requires 'duckduckgo-search' package "
            "(pip install duckduckgo-search)"
        )
    except Exception as e:
        return f"Error: DuckDuckGo search failed: {e}"


# Provider dispatch map
PROVIDERS: dict[str, Any] = {
    "perplexity": _search_perplexity,
    "brave": _search_brave,
    "grok": _search_grok_web,
    "grok_x": _search_grok_x,
    "ollama": _search_ollama,
    "duckduckgo": _search_duckduckgo,
}


async def web_search_handler(
    query: str,
    num_results: int = 5,
    provider: str | None = None,
) -> str:
    """Search the web using the configured or specified provider.

    Providers:
    - perplexity: Via OpenRouter, uses OPENROUTER_API_KEY (default)
    - brave: Brave Search API, uses BRAVE_API_KEY
    - grok: xAI Grok web search, uses XAI_API_KEY
    - grok_x: xAI Grok X/Twitter search, uses XAI_API_KEY
    - ollama: Ollama Web Search API, uses OLLAMA_API_KEY
    - duckduckgo: Free, no API key needed (fallback)
    """
    p = (provider or DEFAULT_PROVIDER).strip().lower()
    n = min(max(num_results, 1), 10)

    search_fn = PROVIDERS.get(p)
    if not search_fn:
        return f"Error: Unknown search provider '{p}'. Available: {', '.join(PROVIDERS.keys())}"

    logger.info("web_search: provider=%s, query=%r, num_results=%d", p, query, n)
    result = await search_fn(query, n)
    logger.info("web_search: got %d chars response", len(result))
    return result


# --- Tool definitions for ToolRegistry ---

web_search_tool = Tool(
    name="web_search",
    description=(
        "Search the web for current information. Returns results with titles, URLs, and summaries. "
        "Supports multiple providers: perplexity (default), brave, grok, ollama, duckduckgo."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5, max: 10)",
                "default": 5,
            },
            "provider": {
                "type": "string",
                "description": (
                    "Search provider: perplexity, brave, grok, grok_x, ollama, duckduckgo "
                    "(default: from IW_SEARCH_PROVIDER env or perplexity)"
                ),
                "enum": ["perplexity", "brave", "grok", "grok_x", "ollama", "duckduckgo"],
            },
        },
        "required": ["query"],
    },
    handler=web_search_handler,
)

# Separate tool for X/Twitter search (agents that need social media analysis)
x_search_tool = Tool(
    name="x_search",
    description=(
        "Search X (Twitter) for posts, users, and threads on a topic. "
        "Useful for finding social media perspectives and narratives. "
        "Requires XAI_API_KEY."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    handler=lambda query, num_results=5: _search_grok_x(query, num_results),
)
