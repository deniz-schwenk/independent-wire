# Independent Wire — Claude Code Instructions

## Project

Independent Wire is an open-source AI-powered news pipeline that produces transparency-first, multi-perspective journalism. It's a solo developer project — every change must be simple and reversible.

## Repository Structure

- `src/` — Python framework (agent.py, pipeline.py, tools/, models.py)
- `agents/` — Agent system prompts (collector, curator, editor, researcher, writer)
- `scripts/` — Entry points (run.py, fetch_feeds.py, generate-visuals.py)
- `config/` — sources.json, style-guide.md, profiles/
- `output/` — Pipeline debug output and Topic Package JSON per date
- `state/` — Pipeline state checkpoints
- `docs/` — TASKS.md, ROADMAP.md, ARCHITECTURE.md (living documents)
- `schema/` — Topic Package JSON schema

## Testing Rules — READ THIS FIRST

### Pipeline runs cost real money (~$0.50-1.00 per full run)

**NEVER run a full pipeline (`python scripts/run.py`) just to test a change** unless the change affects the Collector, Curator, or the pipeline orchestration itself.

Before running the pipeline, ALWAYS ask: "Should I test with a partial run (`--from writer --topic 1`) to save costs, or do you need a full pipeline run?"

**Use partial runs for testing:**
```bash
# Test writer changes (~$0.05, ~3 min):
python scripts/run.py --from writer --reuse 2026-04-04 --topic 1

# Test researcher changes (~$0.15, ~10 min):
python scripts/run.py --from researcher --reuse 2026-04-04 --topic 1

# Test editor changes (~$0.25, ~15 min):
python scripts/run.py --from editor --reuse 2026-04-04 --topic 1
```

**When a full run IS needed:** Changes to Collector, Curator, pipeline.py orchestration, RSS feed config, or when explicitly requested.

### Unit tests are free — use them
```bash
source .venv/bin/activate && source .env && python -m pytest tests/ -v
```

## Models — Do NOT Change

- **Collector, Curator:** `minimax/minimax-m2.7` via `openrouter`
- **Editor, Researcher, Writer:** `z-ai/glm-5` via `openrouter`
- Do NOT switch to gpt-4o-mini, gpt-3.5, or any other model without explicit instruction.

## Agent Prompts — Do NOT Write

Agent prompts (`agents/*/AGENTS.md`) are written by a separate prompt engineer. If a task requires a new agent prompt:
1. Create the directory (`agents/{name}/`)
2. Note that the prompt needs to be written
3. Do NOT write the prompt yourself

You MAY make small, targeted additions to existing prompts when integrating a new pipeline step (e.g., adding a step "1b" to the writer to consume new context). But do NOT rewrite or restructure existing prompts.

## Code Conventions

- **Python 3.12**, async/await throughout
- **No new dependencies** without explicit approval
- **JSON output from agents** — no markdown, no prose, strict JSON
- **Debug output** per pipeline step: `output/YYYY-MM-DD/NN-agentname-slug.json`
- **State persistence** after each step: `state/run-YYYY-MM-DD-*.json`

## Git

- HTTPS via macOS Keychain — `git push origin main` works without token
- Commit after completing a task, with a clear message

## Key Architectural Rules

- Pipeline steps are **deterministic Python code**, not LLM-orchestrated
- Agents only see the tools in their `tools` list — no shared filesystem access
- Each agent receives only the data it needs via `message` and `context` params
- Tool descriptions must be concise: WHAT it does, never HOW to call it (GLM-5 breaks on code examples in tool descriptions)
- Google News proxy URLs (`news.google.com/rss/search?q=site:...`) are banned in sources.json
- No AI-generated images — only deterministic data visualizations

## Commands

```bash
# Pipeline (full)
source .venv/bin/activate && source .env && python scripts/run.py

# Pipeline (partial — PREFERRED for testing)
source .venv/bin/activate && source .env && python scripts/run.py --from <step> --topic <N> --reuse <date>

# RSS feeds
source .venv/bin/activate && python scripts/fetch_feeds.py

# Tests
source .venv/bin/activate && source .env && python -m pytest tests/ -v

# Claude Code
source .env && claude
```
