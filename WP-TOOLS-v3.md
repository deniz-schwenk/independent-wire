# WP-TOOLS-v3 — Claude Code Task

## Auftrag
Erweitere das Tool-System um Ollama-Support — sowohl als **Search-Provider** (Ollama Web Search API) als auch als **LLM-Provider** (lokale + Cloud-Modelle). Ollama-Modelle können per Config als Alternative zu OpenRouter für Agent-Calls genutzt werden.

## Lies zuerst
1. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/tools/web_search.py` — aktueller Multi-Provider Search
2. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/agent.py` — Agent-Klasse (LLM-Calls)
3. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/tools/web_fetch.py` — aktueller web_fetch

Referenz-Dokumentation (lies per web_fetch oder beachte die Infos unten):
- Ollama Web Search API: https://docs.ollama.com/capabilities/web-search
- Ollama Cloud Models: https://ollama.com/blog/cloud-models
- Ollama hat eine OpenAI-kompatible API

## Arbeitsverzeichnis
`/Users/denizschwenk/Documents/independent-wire/repo-clone/`

## Hintergrund: Ollama bietet drei Dinge

### A) Web Search API
REST-Endpoint auf `https://ollama.com/api/web_search`. Braucht `OLLAMA_API_KEY`.
Liefert strukturierte Ergebnisse: `{"results": [{"title": "...", "url": "...", "content": "..."}]}`.
Großzügiger Free Tier. Gleiche Struktur wie Brave Search.

```bash
curl https://ollama.com/api/web_search \
  -H "Authorization: Bearer $OLLAMA_API_KEY" \
  -d '{"query": "what is ollama?"}'
```

### B) Web Fetch API
REST-Endpoint auf `https://ollama.com/api/web_fetch`. Braucht `OLLAMA_API_KEY`.
Holt Webseiten und gibt sauberen Text zurück mit title, content, links.

```bash
curl -X POST https://ollama.com/api/web_fetch \
  -H "Authorization: Bearer $OLLAMA_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://ollama.com"}'
```

Response: `{"title": "Ollama", "content": "...", "links": ["..."]}`

### C) LLM-Modelle (lokal + cloud)
Ollama hat eine OpenAI-kompatible API auf `http://localhost:11434/v1` (lokal) oder `https://ollama.com/v1` (cloud).
Cloud-Modelle haben `:cloud` Tag, z.B. `qwen3-coder:480b-cloud`, `gpt-oss:120b-cloud`, `deepseek-v3.1:671b-cloud`.
Cloud-API braucht `OLLAMA_API_KEY` als Bearer Token.

## Was du bauen sollst

### 1. `src/tools/web_search.py` — Ollama Search Provider hinzufügen

Füge `_search_ollama` als neuen Provider hinzu. Registriere ihn im PROVIDERS dict:

```python
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
```

Füge `"ollama"` zum `PROVIDERS` dict und zum `provider` enum in der Tool-Definition hinzu.

### 2. `src/tools/web_fetch.py` — Ollama Web Fetch als Alternative hinzufügen

Füge eine optionale Funktion `_fetch_via_ollama` hinzu die statt direktem httpx-Fetch den Ollama Web Fetch API nutzt (gibt sauberen Text zurück statt rohem HTML). Nutze dies als optionalen Fallback oder wenn explizit angefordert.

```python
async def _fetch_via_ollama(url: str) -> str:
    """Fetch web page via Ollama's web_fetch API. Returns clean text."""
    api_key = os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        return None  # Fallback to direct fetch
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://ollama.com/api/web_fetch",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": url},
                timeout=30.0,
            )
            r.raise_for_status()
        
        data = r.json()
        title = data.get("title", "")
        content = data.get("content", "")
        if title:
            content = f"# {title}\n\n{content}"
        return content
    except Exception:
        return None  # Fallback to direct fetch
```

Ändere den bestehenden `web_fetch_handler` so dass er **zuerst** Ollama Web Fetch versucht (wenn OLLAMA_API_KEY gesetzt), und bei Fehler auf den direkten httpx-Fetch zurückfällt. Das gibt sauberen Text statt rohem HTML.

### 3. `src/agent.py` — Ollama als LLM-Provider unterstützen

Der Agent muss mit Ollama-Modellen arbeiten können — sowohl lokal als auch Cloud. Die `openai` Library funktioniert mit Ollamas OpenAI-kompatibler API direkt.

Ändere den `__init__` des Agents:

```python
def __init__(
    self,
    name: str,
    model: str,
    prompt_path: str,
    tools: list[Tool] | None = None,
    memory_path: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 8192,
    provider: str = "openrouter",        # "openrouter", "ollama", "ollama_cloud"
    base_url: str | None = None,         # None = auto-detect from provider
    api_key: str | None = None,
) -> None:
```

Provider-Logik:
- `provider="openrouter"` → `base_url="https://openrouter.ai/api/v1"`, key aus `OPENROUTER_API_KEY`
- `provider="ollama"` → `base_url="http://localhost:11434/v1"`, key ist `"ollama"` (Ollama lokal braucht keinen echten Key, aber die openai library will einen nicht-leeren String)
- `provider="ollama_cloud"` → `base_url="https://ollama.com/v1"`, key aus `OLLAMA_API_KEY`
- Wenn `base_url` explizit gesetzt ist, überschreibt es den Provider-Default

```python
# Provider defaults
PROVIDER_DEFAULTS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "api_key_env": None,  # Lokal kein Key nötig
        "api_key_default": "ollama",  # Dummy für openai library
    },
    "ollama_cloud": {
        "base_url": "https://ollama.com/v1",
        "api_key_env": "OLLAMA_API_KEY",
    },
}
```

**Wichtig:** Die bestehende Logik darf nicht brechen. `provider="openrouter"` ist weiterhin der Default und verhält sich exakt wie vorher.

### 4. `.env.example` — Erweitern

```
# OpenRouter (primary — for LLM calls AND Perplexity search)
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Ollama (optional — for Ollama search, web fetch, and cloud models)
# Get your key at https://ollama.com/settings/keys
OLLAMA_API_KEY=your-ollama-key-here

# Brave Search (optional)
# BRAVE_API_KEY=your-brave-key-here

# xAI / Grok (optional — for web search and X/Twitter search)
# XAI_API_KEY=your-xai-key-here

# Default search provider (perplexity, brave, grok, ollama, duckduckgo)
# IW_SEARCH_PROVIDER=perplexity
```

### 5. `tests/test_tools.py` — Tests erweitern

**Unit Tests (kein Key):**
- `test_web_search_ollama_provider_in_list` — "ollama" ist im PROVIDERS dict
- `test_agent_provider_defaults_openrouter` — Default provider bleibt openrouter
- `test_agent_provider_defaults_ollama` — provider="ollama" setzt localhost base_url
- `test_agent_provider_defaults_ollama_cloud` — provider="ollama_cloud" setzt ollama.com base_url

**Integration Tests (brauchen OLLAMA_API_KEY):**
- `test_search_ollama` — Ollama Web Search mit echtem API-Call
- `test_fetch_via_ollama` — Ollama Web Fetch mit echtem API-Call
- `test_agent_ollama_cloud` — Agent mit provider="ollama_cloud" und einem Cloud-Modell (z.B. `gpt-oss:20b-cloud`), einfacher Chat-Call

Markiere mit `@pytest.mark.skipif(not os.environ.get("OLLAMA_API_KEY"), reason="No Ollama API key")`

**Lokale Ollama-Tests** (brauchen laufende Ollama-Instanz):
- `test_agent_ollama_local` — Agent mit provider="ollama" und einem lokalen Modell. Markiere mit `@pytest.mark.skipif` der prüft ob `http://localhost:11434` erreichbar ist.

### 6. Bestehende Tests nicht brechen

Alle bisherigen Tests müssen weiterhin durchlaufen. Die Agent-Klasse ist abwärtskompatibel — `provider="openrouter"` ist weiterhin Default.

## Technische Regeln
- Python 3.11+, type hints überall
- Logging via `logging.getLogger(__name__)`
- Keine neuen Dependencies — `openai` und `httpx` reichen für alles
- Fehler in Providern: NICHT raisen, String-Fehlermeldung zurückgeben
- Ollama lokal: `api_key="ollama"` als Dummy-String (openai library verlangt non-empty string)
- Ollama Cloud-API ist OpenAI-kompatibel: `base_url="https://ollama.com/v1"` + Bearer Token

## Was du NICHT bauen sollst
- Kein Ollama SDK/Library installieren — alles über httpx und openai library
- Keine Pipeline-Änderungen
- Kein Config-File-Loading — alles über Environment-Variablen und Konstruktor-Argumente

## Akzeptanzkriterien
1. Bestehende Tests laufen weiterhin
2. `web_search_handler("test", provider="ollama")` nutzt Ollama Web Search API
3. `web_fetch_handler("https://ollama.com")` versucht zuerst Ollama Web Fetch (wenn Key da), dann Fallback
4. `Agent(name="test", model="gpt-oss:20b-cloud", prompt_path="...", provider="ollama_cloud")` funktioniert
5. `Agent(name="test", model="qwen3:4b", prompt_path="...", provider="ollama")` funktioniert mit lokalem Ollama
6. `Agent(name="test", model="...", prompt_path="...", provider="openrouter")` verhält sich exakt wie vorher

## Nach dem Bauen
```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
source .env
python -m pytest tests/ -v
git add -A
git commit -m "WP-TOOLS-v3: Ollama support — search, web fetch, local + cloud LLM provider

- Ollama Web Search API as search provider (OLLAMA_API_KEY)
- Ollama Web Fetch API for clean text extraction (fallback to direct httpx)
- Agent supports provider='ollama' for local models (localhost:11434)
- Agent supports provider='ollama_cloud' for cloud models (ollama.com/v1)
- PROVIDER_DEFAULTS dict for clean provider configuration
- Backward compatible: provider='openrouter' remains default
- Tests for all new providers with appropriate skipif markers"
git push origin main
```
