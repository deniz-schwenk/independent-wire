# WP-TOOLS-v2 — Claude Code Task

## Auftrag
Erweitere das Tool-System um einen Multi-Provider Web-Search. Statt nur Perplexity soll `web_search` über Config zwischen mehreren Providern wechseln können: Perplexity (OpenRouter), Brave Search, Grok/xAI (Web + X/Twitter), und DuckDuckGo als Fallback.

## Lies zuerst
1. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/tools/web_search.py` — aktueller Stand (nur Perplexity)
2. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/tools/registry.py` — Tool-Klasse
3. `/Users/denizschwenk/Documents/nanobot-main/nanobot/agent/tools/web.py` — Nanobot's Multi-Provider-Pattern (Referenz, nicht importieren)

## Arbeitsverzeichnis
`/Users/denizschwenk/Documents/independent-wire/repo-clone/`

## Was du bauen sollst

### 1. `src/tools/web_search.py` — Komplett ersetzen

Refactore zu einem Multi-Provider-Pattern nach dem Vorbild von Nanobot. Ein `web_search_handler` der je nach `provider` Parameter an verschiedene Search-Backends dispatcht.

#### Architektur:

```python
"""Independent Wire — Multi-provider web search tool."""

import logging
import os
import json
from typing import Any

import httpx
from openai import AsyncOpenAI, APIStatusError

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
                {"role": "user", "content": f"Search for: {query}\n\nReturn up to {n} results."},
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
        # xAI Responses API is OpenAI-compatible
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
                            "content": f"Search the web for: {query}\n\nReturn the top {n} results with title, URL, and brief summary for each.",
                        }
                    ],
                    "tools": [{"type": "web_search"}],
                },
                timeout=30.0,
            )
            r.raise_for_status()
        
        data = r.json()
        # Extract text from response output
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
                            "content": f"Search X/Twitter for: {query}\n\nReturn the top {n} relevant posts with author, content, and any key context.",
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
        return "Error: DuckDuckGo search requires 'duckduckgo-search' package (pip install duckduckgo-search)"
    except Exception as e:
        return f"Error: DuckDuckGo search failed: {e}"


# Provider dispatch map
PROVIDERS = {
    "perplexity": _search_perplexity,
    "brave": _search_brave,
    "grok": _search_grok_web,
    "grok_x": _search_grok_x,
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
        "Supports multiple providers: perplexity (default), brave, grok, duckduckgo."
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
                "description": "Search provider: perplexity, brave, grok, grok_x, duckduckgo (default: from IW_SEARCH_PROVIDER env or perplexity)",
                "enum": ["perplexity", "brave", "grok", "grok_x", "duckduckgo"],
            },
        },
        "required": ["query"],
    },
    handler=web_search_handler,
)

# Separate tool definition for X/Twitter search (agents that need social media analysis)
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
```

**Wichtige Design-Entscheidungen:**
- `provider` Parameter im Tool ermöglicht dem LLM die Provider-Wahl pro Aufruf
- `IW_SEARCH_PROVIDER` Environment-Variable für den Default-Provider
- Jeder Provider hat seine eigene `_search_*` Funktion — sauber getrennt, leicht testbar
- `_format_results()` für konsistentes Output-Format (Brave, DuckDuckGo)
- Perplexity und Grok geben Freitext zurück (LLM-generiert, inkl. Quellen)
- `x_search_tool` als separates Tool — nicht jeder Agent braucht Twitter-Zugang
- DuckDuckGo als Fallback wenn kein API-Key gesetzt ist
- `ddgs` (duckduckgo-search) ist optional — graceful Import-Error

### 2. `src/tools/__init__.py` — Erweitern

Füge `x_search_tool` zum Export hinzu und zur `create_default_registry()`:

```python
from src.tools.web_search import web_search_tool, x_search_tool

def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(web_search_tool)
    registry.register(x_search_tool)
    registry.register(web_fetch_tool)
    registry.register(read_file_tool)
    registry.register(write_file_tool)
    return registry
```

### 3. `pyproject.toml` — Optionale Dependencies erweitern

Füge hinzu:
```toml
[project.optional-dependencies]
telegram = ["python-telegram-bot>=20.0"]
search-brave = []              # Brave nutzt nur httpx (schon core dep)
search-duckduckgo = ["duckduckgo-search"]
```

Entferne `search-brave = ["brave-search"]` und `search-tavily = ["tavily-python"]` — wir brauchen keine separaten SDKs. Brave läuft über httpx, Tavily wird nicht unterstützt.

### 4. `.env.example` — Erweitern

```
# === Search Provider ===
# Default search provider (perplexity, brave, grok, duckduckgo)
# IW_SEARCH_PROVIDER=perplexity

# === API Keys ===

# OpenRouter (required — for LLM calls AND Perplexity search)
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Brave Search (optional — for brave search provider)
# BRAVE_API_KEY=your-brave-key-here

# xAI / Grok (optional — for grok web search and X/Twitter search)
# XAI_API_KEY=your-xai-key-here

# === Telegram (optional) ===
TELEGRAM_BOT_TOKEN=your-bot-token-here
TELEGRAM_CHAT_ID=your-chat-id-here
```

### 5. `tests/test_tools.py` — Tests erweitern

Erweitere die bestehenden Tests, lösche keine:

**Unit Tests (kein API-Key):**
- `test_web_search_unknown_provider` — unbekannter Provider gibt Fehler zurück
- `test_web_search_format_results` — `_format_results()` formatiert korrekt
- `test_web_search_format_results_empty` — leere Ergebnisse
- `test_web_search_default_provider_from_env` — IW_SEARCH_PROVIDER wird gelesen
- `test_x_search_tool_definition` — x_search_tool hat korrekte OpenAI-Format

**Integration Tests (brauchen jeweiligen API-Key):**
- `test_search_perplexity` — Perplexity via OpenRouter (braucht OPENROUTER_API_KEY)
- `test_search_brave` — Brave Search (braucht BRAVE_API_KEY, skip wenn nicht gesetzt)
- `test_search_grok_web` — Grok Web Search (braucht XAI_API_KEY, skip wenn nicht gesetzt)
- `test_search_grok_x` — Grok X Search (braucht XAI_API_KEY, skip wenn nicht gesetzt)
- `test_search_duckduckgo` — DuckDuckGo (skip wenn ddgs nicht installiert)

Markiere jeden Integration-Test mit dem passenden `skipif`.

### 6. Bestehende Tests nicht brechen

Die bestehenden Tests in `tests/test_tools.py` müssen weiterhin durchlaufen. Die `web_search_handler` Signatur ist abwärtskompatibel — `provider` ist optional.

## Technische Regeln
- Python 3.11+, type hints überall
- Logging via `logging.getLogger(__name__)`
- Keine neuen Core-Dependencies — `openai` und `httpx` reichen. `duckduckgo-search` ist optional.
- Fehler in Providern: NICHT raisen, String-Fehlermeldung zurückgeben
- Wenn ein Provider-Key fehlt und es nicht der explizit angeforderte Provider ist: Fallback auf DuckDuckGo mit Logger-Warning
- Grok API: direkt httpx nutzen (kein xai_sdk), da die Responses API ein einfacher POST ist

## Was du NICHT bauen sollst
- Keine Tavily-Unterstützung (nicht nötig)
- Keine Jina-Unterstützung (nicht nötig)
- Keine SearXNG-Unterstützung (nicht nötig)
- Keine Änderungen an `src/agent.py` oder `src/models.py`
- Kein Config-File-Loading — alles über Environment-Variablen

## Akzeptanzkriterien
1. `python -m pytest tests/test_tools.py` — alle bisherigen Tests laufen weiterhin
2. `web_search_handler("test", provider="perplexity")` funktioniert (mit Key)
3. `web_search_handler("test", provider="brave")` funktioniert (mit Key) oder fällt auf DuckDuckGo zurück
4. `web_search_handler("test", provider="grok")` funktioniert (mit Key) oder fällt auf DuckDuckGo zurück
5. `web_search_handler("test", provider="duckduckgo")` funktioniert (ohne Key)
6. `x_search_tool` ist als separates Tool registriert
7. Provider ist per-Aufruf wählbar UND per Environment-Variable konfigurierbar
8. `IW_SEARCH_PROVIDER=brave python -m pytest` nutzt Brave als Default

## Nach dem Bauen
```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
git add -A
git commit -m "WP-TOOLS-v2: Multi-provider web search — Perplexity, Brave, Grok, DuckDuckGo

- Provider pattern: dispatch by provider name (perplexity, brave, grok, grok_x, duckduckgo)
- Perplexity via OpenRouter (default, no extra key)
- Brave Search via direct API (BRAVE_API_KEY)
- Grok/xAI web search + X/Twitter search (XAI_API_KEY)
- DuckDuckGo as zero-cost fallback
- x_search_tool for social media perspective analysis
- IW_SEARCH_PROVIDER env var for default provider
- Per-call provider override via parameter
- Backward compatible with existing tests"
git push origin main
```
