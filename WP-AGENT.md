# WP-AGENT — Claude Code Task

## Auftrag
Baue die Agent-Abstraktion für Independent Wire: eine Python-Klasse die LLM-Calls über OpenRouter macht, System-Prompts aus Dateien lädt, und Tool-Calls in einer Schleife verarbeitet.

## Lies zuerst
1. `/Users/denizschwenk/Documents/nanobot-main/nanobot/agent/loop.py` — so baut man einen LLM-Call mit Tool-Loop
2. `/Users/denizschwenk/Documents/nanobot-main/nanobot/agent/tools/` — so registriert man Tools
3. `/Users/denizschwenk/Documents/independent-wire/repo-clone/docs/ARCHITECTURE.md` — die Zielarchitektur

Nanobot ist Lesematerial, keine Dependency. Importiere nichts daraus.

## Arbeitsverzeichnis
`/Users/denizschwenk/Documents/independent-wire/repo-clone/`

## Was du bauen sollst

### 1. `src/__init__.py`
Leeres init.

### 2. `src/models.py`
```python
from dataclasses import dataclass, field

@dataclass
class AgentResult:
    """What an agent returns."""
    content: str                          # raw text response
    structured: dict | None = None        # parsed JSON if output_schema was provided
    tool_calls: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0
    model: str = ""
    duration_seconds: float = 0.0
```

### 3. `src/agent.py` — Die Kernklasse

```python
class Agent:
    def __init__(
        self,
        name: str,
        model: str,
        prompt_path: str,           # Pfad zu AGENTS.md Datei
        tools: list["Tool"] = None, # Tool-Objekte (nicht Strings) — kommt in WP-TOOLS
        memory_path: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        provider: str = "openrouter",
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str | None = None, # wenn None, aus Env lesen
    ):
        ...

    async def run(
        self,
        message: str,
        context: dict | None = None,
        output_schema: dict | None = None,
    ) -> AgentResult:
        ...
```

#### Agent.run() Ablauf:
1. System-Prompt aus `prompt_path` laden (Datei lesen, plain text)
2. Falls `memory_path` existiert, Memory-Inhalt an System-Prompt anhängen
3. Falls `context` übergeben, als JSON in die User-Message einbauen
4. Falls `output_schema` übergeben, Instruktion an System-Prompt anhängen: "Respond with JSON matching this schema: ..."
5. OpenAI-kompatiblen API-Call machen (openai library, `base_url` auf OpenRouter)
6. **Tool-Loop**: Wenn die Response `tool_calls` enthält:
   - Jedes Tool ausführen
   - Ergebnisse als tool_result Messages anhängen
   - Erneut API-Call machen
   - Wiederholen bis keine tool_calls mehr kommen oder max 10 Iterationen
7. Finale Response in `AgentResult` packen
8. Falls `output_schema`: versuche `content` als JSON zu parsen → `structured`

#### Retry-Logik (in einer separaten Methode `_call_with_retry`):
- Retryable: 429, 500, 502, 503, 529
- Nicht retryable: 401, 403, 400, 413 → sofort raise
- Max 3 Retries, exponential backoff: `2^attempt + random(0,1)` Sekunden
- Logging bei jedem Retry

#### API-Key Handling:
- Wenn `api_key` übergeben: verwenden
- Sonst: `os.environ.get("OPENROUTER_API_KEY")`
- Wenn beides leer: `ValueError` raise

### 4. `src/tools/__init__.py`
Leeres init.

### 5. `src/tools/registry.py` — Minimaler Platzhalter

```python
from dataclasses import dataclass
from typing import Callable, Any

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict          # JSON Schema
    handler: Callable[..., Any]

    async def execute(self, **kwargs) -> str:
        """Execute the tool and return result as string."""
        import asyncio, inspect
        if inspect.iscoroutinefunction(self.handler):
            result = await self.handler(**kwargs)
        else:
            result = await asyncio.to_thread(self.handler, **kwargs)
        return str(result)

    def to_openai_format(self) -> dict:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_for_agent(self, allowed: list[str]) -> list[Tool]:
        return [self._tools[n] for n in allowed if n in self._tools]

    def to_openai_format(self, allowed: list[str]) -> list[dict]:
        return [t.to_openai_format() for t in self.get_for_agent(allowed)]
```

### 6. `tests/test_agent.py` — Minimaler Test

Ein Test der beweist dass der Agent funktioniert:
- Erstelle eine temporäre AGENTS.md Datei mit einem simplen System-Prompt
- Erstelle einen Agent mit einem günstigen Modell (z.B. `"openai/gpt-4o-mini"`)
- Rufe `agent.run("Say hello")` auf
- Assert dass `result.content` nicht leer ist
- Assert dass `result.tokens_used > 0`
- Assert dass `result.model` gesetzt ist

Der Test braucht einen echten API-Key (OPENROUTER_API_KEY in env). Markiere ihn mit `@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="No API key")`.

Ein zweiter Test für die Tool-Loop:
- Registriere ein Dummy-Tool das einfach "42" zurückgibt
- Erstelle einen Agent mit diesem Tool
- Rufe `agent.run("Use the calculator tool to get the answer")` auf
- Assert dass `result.tool_calls` nicht leer ist

### 7. `tests/__init__.py`
Leeres init.

## Technische Regeln
- Python 3.11+, type hints überall
- `async def` für alle Methoden die I/O machen
- `openai` library für API-Calls (ist OpenRouter-kompatibel)
- Logging via `logging.getLogger(__name__)`, kein print()
- Keine globalen Variablen, kein Singleton
- Fehler sauber als eigene Exceptions: `AgentError`, `AgentAPIError`, `AgentTimeoutError`

## Was du NICHT bauen sollst
- Keine konkreten Tools (web_search etc.) — kommt in WP-TOOLS
- Keine Pipeline — kommt in WP-PIPELINE
- Keine Telegram-Integration — kommt in WP-TELEGRAM
- Keine Config-Datei-Loading — Agent bekommt seine Config als Konstruktor-Argumente
- Kein CLI

## Akzeptanzkriterien
1. `python -m pytest tests/test_agent.py` läuft durch (mit API-Key)
2. Agent kann einen LLM-Call machen und AgentResult zurückgeben
3. Agent kann Tools in einer Schleife aufrufen
4. Retry-Logik ist implementiert und geloggt
5. System-Prompt wird aus Datei geladen
6. Code ist sauber, typisiert, und dokumentiert

## Nach dem Bauen
```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
git add -A
git commit -m "WP-AGENT: Agent abstraction with LLM calls, tool loop, and retry logic

- Agent class: async LLM caller via OpenRouter (OpenAI-compatible)
- AgentResult dataclass with structured output support
- Tool and ToolRegistry for per-agent tool permissions
- Exponential backoff retry for transient API errors
- System prompt loading from AGENTS.md files
- Tests with real API calls and dummy tool loop"
git push origin main
```
