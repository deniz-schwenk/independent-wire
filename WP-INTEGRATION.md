# WP-INTEGRATION — First End-to-End Pipeline Run

## Goal

Wire everything together for the first real Collector → Curator → Editor → Writer pipeline run with live LLM calls. Produce actual Topic Package JSON output.

This is the "moment of truth" — every component has been tested in isolation, now they run together.

## Context for Claude Code

- **Local clone:** `/Users/denizschwenk/Documents/independent-wire/repo-clone/`
- **Reference codebase (read-only):** `/Users/denizschwenk/Documents/nanobot-main/` — look at `nanobot/agent/loop.py` for patterns on LLM call orchestration
- **Run tests:** `source .venv/bin/activate && source .env && python -m pytest tests/ -v`
- **Run pipeline:** `source .venv/bin/activate && source .env && python scripts/run.py`

## Scope

Three things to build:

1. **`scripts/run.py`** — CLI entry point that instantiates agents + pipeline and runs
2. **Fix `_extract_list` / `_extract_dict`** in `src/pipeline.py` — they don't handle markdown code fences, which LLMs almost always emit
3. **Test it** — run and debug until the pipeline completes (expect 2-3 iterations)

---

## Part 1: `scripts/run.py`

Create a simple async CLI script that:

1. Sets up logging (INFO to stdout, timestamps)
2. Resolves all paths relative to repo root
3. Imports and creates the `web_search_tool` from `src.tools`
4. Creates 4 Agent instances (see config table)
5. Creates a Pipeline and calls `pipeline.run()`
6. Prints a summary: how many topics produced, time elapsed, any failures
7. Handles KeyboardInterrupt gracefully

### Agent Configuration

| Pipeline Key | Model | Provider | Temp | Tools | Prompt |
|-------------|-------|----------|------|-------|--------|
| `collector` | `minimax-m2.7:cloud` | `ollama_cloud` | 0.2 | `[web_search_tool]` | `agents/collector/AGENTS.md` |
| `curator` | `minimax-m2.7:cloud` | `ollama_cloud` | 0.2 | `[]` | `agents/curator/AGENTS.md` |
| `editor` | `glm-5:cloud` | `ollama_cloud` | 0.3 | `[]` | `agents/editor/AGENTS.md` |
| `writer` | `glm-5:cloud` | `ollama_cloud` | 0.3 | `[web_search_tool]` | `agents/writer/AGENTS.md` |

### Pipeline Configuration

```python
pipeline = Pipeline(
    name="daily_report",
    agents=agents,  # dict with keys: collector, curator, editor, writer
    output_dir=str(ROOT / "output"),
    state_dir=str(ROOT / "state"),
    max_topics=3,  # start small for first run!
    mode="quick",  # no gating
)
```

### Critical Details

- **Prompt paths must be absolute.** The Agent class reads `self.prompt_path` as-is via `Path(self.prompt_path)`. Use `str(ROOT / "agents" / "collector" / "AGENTS.md")`.
- **`web_search_tool` is an object**, not a string. Import it: `from src.tools import web_search_tool`. The Agent constructor takes `tools: list[Tool]`.
- **`max_topics=3`** for the first run. We want to see if it works, not burn through API credits.
- **`sys.path` handling**: The script runs from `scripts/`, but imports use `from src...`. Add the repo root to `sys.path` at the top of the script:
  ```python
  ROOT = Path(__file__).resolve().parent.parent
  sys.path.insert(0, str(ROOT))
  ```

### Skeleton

```python
#!/usr/bin/env python3
"""Independent Wire — Run the daily pipeline."""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Repo root for resolving paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.pipeline import Pipeline
from src.tools import web_search_tool


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_agents() -> dict[str, Agent]:
    """Create all pipeline agents with their configurations."""
    # ... see config table above
    pass


async def main():
    setup_logging()
    logger = logging.getLogger("independent_wire")

    logger.info("Starting Independent Wire pipeline...")
    start = time.time()

    agents = create_agents()
    pipeline = Pipeline(
        name="daily_report",
        agents=agents,
        output_dir=str(ROOT / "output"),
        state_dir=str(ROOT / "state"),
        max_topics=3,
        mode="quick",
    )

    try:
        packages = await pipeline.run()
        elapsed = time.time() - start

        # Print summary
        completed = [p for p in packages if p.status != "failed"]
        failed = [p for p in packages if p.status == "failed"]
        logger.info("Pipeline finished in %.1f seconds", elapsed)
        logger.info("  Topics: %d completed, %d failed", len(completed), len(failed))
        for p in completed:
            logger.info("  ✓ %s: %s", p.id, p.metadata.get("title", ""))
        for p in failed:
            logger.info("  ✗ %s: %s", p.id, p.error or "unknown error")

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Part 2: Fix JSON Extraction in `src/pipeline.py`

### The Problem

`_extract_list()` and `_extract_dict()` in `pipeline.py` do a raw `json.loads(result.content)`. But LLMs almost always wrap JSON in markdown code fences:

```
```json
[{"title": "..."}]
```
```

This will cause `json.JSONDecodeError` and every pipeline step that doesn't use `output_schema` will fail silently (returning `None` or `[]`).

### The Fix

Add a helper function `_strip_code_fences()` and use it in both extraction functions. The Agent class already has similar logic in `_parse_json()` — reuse that pattern.

```python
import re

def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    # Match ```json ... ``` or ``` ... ```
    match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _extract_list(result: object) -> list[dict] | None:
    """Extract a list from an AgentResult (structured or content)."""
    if result.structured and isinstance(result.structured, list):
        return result.structured
    try:
        cleaned = _strip_code_fences(result.content)
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        # Some LLMs wrap lists in an object: {"findings": [...]}
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _extract_dict(result: object) -> dict | None:
    """Extract a dict from an AgentResult (structured or content)."""
    if result.structured and isinstance(result.structured, dict):
        return result.structured
    try:
        cleaned = _strip_code_fences(result.content)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return None
```

**Important:** The "unwrap list from dict" fallback in `_extract_list` is critical. Models like minimax and glm often return `{"findings": [...]}` or `{"topics": [...]}` instead of a bare list.

### Where These Functions Are Called

- `collect()` — uses `output_schema`, so structured retry handles it. But `_extract_list` is the fallback. **Keep the fix.**
- `curate()` — calls `_extract_list(result)`. **Will break without the fix.**
- `editorial_conference()` — calls `_extract_list(result)`. **Will break without the fix.**
- `_produce_single()` — calls `_extract_dict(result)` for the article and `_extract_list(result)` for perspectives. **Will break without the fix.**

---

## Part 3: Debug the First Run

After building Parts 1 and 2, run:
```bash
source .venv/bin/activate && source .env && python scripts/run.py
```

### Expected First-Run Issues

**Issue A: Context too large for Curator.** The Collector returns 25-40 findings. When serialized as JSON context for the Curator, this might exceed the model's context window (minimax-m2.7:cloud).

*Fix if needed:* In `curate()`, truncate `raw_findings` to the first 20 items before passing as context. Or summarize each finding to just `{title, summary, source_name}` (drop `source_url` and other fields).

**Issue B: Agent returns prose instead of JSON.** Even with clear instructions, some models may return a mix of prose and JSON. The `_extract_list` fix from Part 2 handles code fences, but not prose-wrapped JSON.

*Fix if needed:* Add a regex fallback in `_extract_list` that searches for the first `[` and last `]` in the content:
```python
# Last resort: find JSON array in prose
start = cleaned.find("[")
end = cleaned.rfind("]")
if start != -1 and end > start:
    try:
        return json.loads(cleaned[start:end+1])
    except json.JSONDecodeError:
        pass
```

**Issue C: Editor assigns IDs that don't match expected format.** The `editorial_conference()` method creates `TopicAssignment` objects and looks for `id`, `title`, `priority`, `topic_slug`, `selection_reason` fields. If the Editor model uses different field names, the assignments will have empty strings.

*Fix if needed:* Add more field name fallbacks in the assignment parsing (already has `a.get("id", a.get("topic_id", ""))`). Extend to cover common variations.

**Issue D: Writer produces article as string, not JSON object.** The Writer might return a plain article text instead of a `{"headline": "...", "body": "..."}` dict. The fallback in `_produce_single` already handles this: `article = _extract_dict(result) or {"headline": assignment.title, "body": result.content}`. This should be fine.

**Issue E: Ollama Cloud rate limits.** If the pipeline fires 4+ LLM calls in quick succession, Ollama Cloud might return 429s. The Agent class has retry logic with exponential backoff — this should handle it. But if it doesn't, add a small delay between pipeline steps.

---

## Part 4: Add Tests

After the first successful run, add a smoke test in `tests/test_integration.py`:

```python
"""Smoke test for the full integration — requires API keys."""

import pytest
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

@pytest.mark.skipif(
    not os.environ.get("OLLAMA_API_KEY"),
    reason="OLLAMA_API_KEY not set"
)
@pytest.mark.asyncio
async def test_pipeline_smoke():
    """Run the pipeline with max_topics=1 and verify output."""
    # Import here to avoid issues when API key is missing
    from scripts.run import create_agents
    from src.pipeline import Pipeline

    agents = create_agents()
    pipeline = Pipeline(
        name="test_run",
        agents=agents,
        output_dir=str(ROOT / "output" / "test"),
        state_dir=str(ROOT / "state" / "test"),
        max_topics=1,
        mode="quick",
    )
    packages = await pipeline.run()
    assert len(packages) >= 1
    # At least one should not be failed
    assert any(p.status != "failed" for p in packages)
```

This test will be skipped in CI (no API key) but can be run locally to verify the integration.

---

## Files Modified/Created

| File | Action |
|------|--------|
| `scripts/run.py` | **Create** — CLI entry point |
| `src/pipeline.py` | **Modify** — fix `_extract_list`, `_extract_dict`, add `_strip_code_fences` |
| `tests/test_integration.py` | **Create** — smoke test (optional, if time permits) |

## Definition of Done

1. `python scripts/run.py` starts the pipeline and produces at least one Topic Package JSON file in `output/YYYY-MM-DD/`
2. The state is saved in `state/` after each step
3. Logging shows the progression through all 5 steps
4. Failed topics are logged but don't crash the pipeline
5. All existing tests still pass

## What NOT to Do

- Don't add `__main__.py` — it's not needed. `scripts/run.py` is the entry point.
- Don't change agent prompts — that's a separate WP if needed.
- Don't add Telegram integration — that's WP-TELEGRAM.
- Don't parallelize — sequential is fine for now.
- Don't optimize token usage — get it working first.
