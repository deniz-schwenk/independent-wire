# Independent Wire — Session Handoff (2026-03-30)

## Completed Work Packages

| WP | Status | What it does |
|----|--------|-------------|
| WP-AGENT | ✅ Done | Agent class: async LLM calls via OpenRouter/Ollama, tool loop, retry logic |
| WP-TOOLS | ✅ Done | Tool system: web_search (multi-provider), web_fetch, file_ops, ToolRegistry |
| WP-TOOLS-v2 | ✅ Done | Multi-provider search: Perplexity, Brave, Grok, DuckDuckGo |
| WP-TOOLS-v3 | ✅ Done | Ollama integration: local, ollama_cloud, x_search_tool |
| WP-PIPELINE | ✅ Done | Pipeline orchestration: sequential steps, state persistence, error isolation, gate hooks |
| WP-STRUCTURED-RETRY | ✅ Done | Retry logic for failed JSON parsing (up to 2 retries with corrective prompt) |
| WP-AGENTS | ✅ Done | English agent names + system prompts for Collector, Curator, Editor, Writer |

## Current Test Status
- All tests passing (50+ tests, ~4 skipped for missing API keys)
- Run: `source .venv/bin/activate && source .env && python -m pytest tests/ -v`

## Agent Names (English, finalized)

| Agent | Pipeline Key | Model (dev) | Temperature | Prompt |
|-------|-------------|-------------|-------------|--------|
| Collector | `collector` | minimax-m2.7:cloud | 0.2 | agents/collector/AGENTS.md |
| Curator | `curator` | minimax-m2.7:cloud | 0.2 | agents/curator/AGENTS.md |
| Editor | `editor` | glm-5:cloud | 0.3 | agents/editor/AGENTS.md |
| Writer | `writer` | glm-5:cloud | 0.3 | agents/writer/AGENTS.md |

Provider for all: `ollama_cloud` (https://ollama.com/v1, needs OLLAMA_API_KEY)

## What Comes Next

### Immediate: WP-INTEGRATION
Wire everything together for the first real end-to-end pipeline run:
- CLI entry point (`scripts/run.py` or `python -m independent_wire`)
- Create the 4 Agent instances with correct models, prompts, tools, temperatures
- Create Pipeline with the agents dict
- Run and see what happens

This is the "moment of truth" — first real Collector→Curator→Editor→Writer run.

### After first run works:
- **WP-QA** — QA/Faktencheck agent (optional slot already in pipeline)
- **WP-PERSPEKTIV** — Perspektiv-Agent (optional slot already in pipeline)
- **WP-BIAS** — Bias-Detektor agent (optional slot already in pipeline)
- **WP-TELEGRAM** — Telegram notifications + gating (gate_handler hook ready)
- **WP-MEMORY** — Agent memory loading/saving

### On the horizon (H2):
- GitHub Pages setup for independentwire.org
- DNS configuration (Cloudflare)
- Cloudflare Email Routing (hello@independentwire.org)
- generate-visuals.py integration (Mermaid diagrams from Topic Packages)

## Domains
- independentwire.org ✅ (Cloudflare)
- independentwire.com ✅ (Cloudflare)
- independentwire.de — not yet (Cloudflare doesn't support .de, use Porkbun or INWX)
- independentwire.eu — not yet (same)

## File Structure (current)
```
independent-wire/repo-clone/
├── src/
│   ├── agent.py          # Agent class with structured retry
│   ├── pipeline.py       # Pipeline with English agent keys
│   ├── models.py         # AgentResult, TopicPackage, TopicAssignment, PipelineState
│   └── tools/            # web_search, web_fetch, file_ops, registry
├── agents/
│   ├── collector/AGENTS.md
│   ├── curator/AGENTS.md
│   ├── editor/AGENTS.md
│   └── writer/AGENTS.md
├── tests/
│   ├── test_agent.py
│   ├── test_tools.py
│   └── test_pipeline.py
├── config/style-guide.md
├── schema/topic-package-v1.json
├── docs/ARCHITECTURE.md
└── WP-*.md               # Work package specs (historical)
```

## Key Technical Facts
- All LLM calls via OpenAI-compatible client (works with OpenRouter and Ollama Cloud)
- Dev models: minimax-m2.7:cloud (NOT 2.5), glm-5:cloud — both via ollama_cloud provider
- Tests: `source .venv/bin/activate && source .env && python -m pytest tests/ -v`
- Claude Code: `source .env && claude`
- Git: HTTPS via macOS Keychain, `git push origin main` works without token input
- Local clone: /Users/denizschwenk/Documents/independent-wire/repo-clone/
