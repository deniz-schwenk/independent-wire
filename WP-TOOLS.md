# WP-TOOLS — Claude Code Task

## Auftrag
Baue die konkreten Tools für Independent Wire: `web_search` (via Perplexity auf OpenRouter), `web_fetch` (via httpx), `read_file`, `write_file`. Alle Tools nutzen die bestehende `Tool`-Klasse aus `src/tools/registry.py`.

## Lies zuerst
1. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/tools/registry.py` — die bestehende Tool + ToolRegistry Klasse
2. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/agent.py` — wie der Agent Tools aufruft (Zeile 174-217, 240-275)
3. `/Users/denizschwenk/Documents/independent-wire/repo-clone/docs/ARCHITECTURE.md` — Architektur-Kontext

## Arbeitsverzeichnis
`/Users/denizschwenk/Documents/independent-wire/repo-clone/`

## Was du bauen sollst

### 1. `src/tools/web_search.py` — Web-Suche via Perplexity auf OpenRouter

**Kernidee:** Perplexity-Modelle (`perplexity/sonar-pro`) laufen auf OpenRouter. Statt einer separaten Search-API machen wir einfach einen LLM-Call an ein Perplexity-Modell mit der Suchanfrage. Perplexity durchsucht das Web und gibt eine Antwort mit Quellen zurück. Gleicher API-Key wie für alle anderen Agents — kein zusätzlicher Key nötig.

```python
import os
import json
from openai import AsyncOpenAI

async def web_search_handler(query: str, num_results: int = 5) -> str:
    """Search the web using Perplexity via OpenRouter.
    
    Makes an LLM call to perplexity/sonar-pro which searches the web
    and returns results with citations.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return "Error: OPENROUTER_API_KEY not set"
    
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    
    response = await client.chat.completions.create(
        model="perplexity/sonar-pro",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a web search assistant. Search for the query and return "
                    "structured results. For each result include: title, URL, and a "
                    "brief summary. Return results as a JSON array. Include the source "
                    "URLs. Be factual and concise."
                ),
            },
            {
                "role": "user", 
                "content": f"Search for: {query}\n\nReturn up to {num_results} results.",
            },
        ],
        temperature=0.1,
        max_tokens=4096,
    )
    
    return response.choices[0].message.content or "No results found"


# Tool-Definition für die ToolRegistry
from src.tools.registry import Tool

web_search_tool = Tool(
    name="web_search",
    description="Search the web for current information. Returns results with titles, URLs, and summaries.",
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
    handler=web_search_handler,
)
```

**Wichtig:**
- Erstelle den AsyncOpenAI-Client **nicht** als globale Variable — erstelle ihn in der Handler-Funktion (oder cach ihn)
- Fehlerbehandlung: wenn der API-Call fehlschlägt, gib eine verständliche Fehlermeldung als String zurück (der Agent sieht das als Tool-Ergebnis)
- Logging mit `logging.getLogger(__name__)`

### 2. `src/tools/web_fetch.py` — Webseite abrufen

```python
import httpx

async def web_fetch_handler(url: str, max_chars: int = 10000) -> str:
    """Fetch a web page and return its text content."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(url, headers={"User-Agent": "IndependentWire/0.1"})
        response.raise_for_status()
        text = response.text
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[Truncated at {max_chars} characters]"
        return text
```

**Wichtig:**
- Timeout auf 30 Sekunden
- User-Agent setzen
- HTML zurückgeben (Agenten können HTML lesen)
- Trunkierung bei max_chars mit Hinweis
- Fehlerbehandlung: HTTP-Fehler als verständliche Fehlermeldung
- Optional: Wenn `beautifulsoup4` installiert ist, kann ein simpel-Text-Extraktor den HTML-Ballast entfernen. Aber das ist kein Muss — als Fallback rohen Text liefern.

Tool-Definition:
```python
web_fetch_tool = Tool(
    name="web_fetch",
    description="Fetch the content of a web page. Returns the page text.",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return (default: 10000)",
                "default": 10000,
            },
        },
        "required": ["url"],
    },
    handler=web_fetch_handler,
)
```

### 3. `src/tools/file_ops.py` — Datei-Operationen

Zwei Tools: `read_file` und `write_file`. Einfach, robust, mit Pfad-Validierung.

```python
read_file_tool = Tool(
    name="read_file",
    description="Read contents of a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read"},
        },
        "required": ["path"],
    },
    handler=read_file_handler,
)

write_file_tool = Tool(
    name="write_file",
    description="Write content to a file. Creates directories if needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to write to"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
    handler=write_file_handler,
)
```

**Wichtig:**
- `write_file` erstellt Parent-Directories automatisch (`Path.parent.mkdir(parents=True, exist_ok=True)`)
- `read_file` gibt den Inhalt als String zurück, bei Fehler eine verständliche Meldung
- Keine Pfad-Beschränkung in Phase 1 (kommt später wenn Pipeline läuft)

### 4. `src/tools/__init__.py` — Alles exportieren

```python
from src.tools.registry import Tool, ToolRegistry
from src.tools.web_search import web_search_tool
from src.tools.web_fetch import web_fetch_tool
from src.tools.file_ops import read_file_tool, write_file_tool

# Convenience: pre-built registry with all tools
def create_default_registry() -> ToolRegistry:
    """Create a ToolRegistry with all built-in tools registered."""
    registry = ToolRegistry()
    registry.register(web_search_tool)
    registry.register(web_fetch_tool)
    registry.register(read_file_tool)
    registry.register(write_file_tool)
    return registry

__all__ = [
    "Tool",
    "ToolRegistry",
    "web_search_tool",
    "web_fetch_tool",
    "read_file_tool",
    "write_file_tool",
    "create_default_registry",
]
```

### 5. `tests/test_tools.py` — Tests

**Unit Tests (kein API-Key nötig):**
- `test_tool_to_openai_format` — Tool-Definition korrekt formatiert
- `test_registry_register_and_get` — Registry speichert und findet Tools
- `test_registry_get_for_agent` — Filtern nach erlaubten Tool-Namen
- `test_read_file` — Datei lesen (mit tmp_path)
- `test_write_file` — Datei schreiben (mit tmp_path)
- `test_write_file_creates_directories` — Erstellt Parent-Dirs
- `test_web_fetch` — Fetch gegen httpbin.org oder ähnlichen Test-Endpunkt (oder mocken mit `respx`)

**Integration Tests (brauchen OPENROUTER_API_KEY):**
- `test_web_search_returns_results` — Echtsuche nach einem bekannten Fakt
- `test_agent_with_web_search_tool` — Agent bekommt web_search Tool, wird gefragt etwas zu suchen, nutzt das Tool

Markiere Integration-Tests mit `@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="No API key")`

### 6. `agents/test/AGENTS.md` — Test-Prompt für Integration-Tests

```markdown
# Test Agent

You are a helpful test agent. When asked to search for something, use the web_search tool. When asked to read or write files, use the appropriate file tools. Be concise in your responses.
```

## Technische Regeln
- Python 3.11+, type hints überall
- `async def` für alle Handler die I/O machen
- Logging via `logging.getLogger(__name__)`
- Keine neuen Dependencies nötig — `openai` und `httpx` sind schon in pyproject.toml
- Fehler in Tool-Handlern: NICHT raisen, sondern Fehler-String zurückgeben (der Agent soll die Fehlermeldung sehen und damit umgehen können)

## Was du NICHT bauen sollst
- Keine Änderungen an `src/agent.py` oder `src/models.py` (die sind fertig)
- Keine Pipeline — kommt in WP-PIPELINE
- Keine Config-Datei — Tools lesen API-Key direkt aus Environment
- Kein Brave Search, kein Tavily — nur Perplexity via OpenRouter

## Akzeptanzkriterien
1. `python -m pytest tests/test_tools.py` — Unit Tests laufen ohne API-Key
2. Integration Tests laufen mit OPENROUTER_API_KEY
3. `web_search_tool` macht einen echten Perplexity-Call über OpenRouter
4. `web_fetch_tool` holt eine echte Webseite
5. `read_file_tool` / `write_file_tool` funktionieren
6. `create_default_registry()` gibt eine Registry mit allen 4 Tools zurück
7. Ein Agent mit web_search Tool kann eine Frage beantworten die Web-Recherche erfordert

## Nach dem Bauen
```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
git add -A
git commit -m "WP-TOOLS: Tool system with web_search (Perplexity/OpenRouter), web_fetch, file_ops

- web_search via Perplexity sonar-pro on OpenRouter (no extra API key)
- web_fetch via httpx with timeout and truncation
- read_file / write_file with auto directory creation
- create_default_registry() convenience function
- Unit tests + integration tests with real API calls"
git push origin main
```
