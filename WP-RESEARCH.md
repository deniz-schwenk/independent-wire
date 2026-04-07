# WP-RESEARCH — Multilingual Research Agent

## Goal

Add a Research Agent to the pipeline between Editor and Writer. The Research Agent receives a topic assignment and performs targeted multilingual web searches to build a research dossier. This dossier becomes input for the Writer, solving the #1 quality problem: all sources are currently 100% English despite international topic coverage.

## Prerequisites

- The agent prompt at `agents/researcher/AGENTS.md` must exist before running this task. It is created separately by the prompt engineer.

## Architecture Decision

The Research Agent is **not** a replacement for the Writer's own web_search capability. The Writer already searches — but it searches in English, from an English prompt, and finds English sources. The Research Agent's job is to **front-load multilingual research** so the Writer receives a rich, diverse source base before it starts writing.

**Pipeline before:**
```
Editor → [per topic] → Writer → Topic Package
```

**Pipeline after:**
```
Editor → [per topic] → Researcher → Writer → Topic Package
```

The Researcher runs once per topic, just like the Writer. It uses the same `web_search` tool the Writer uses, but its prompt instructs it to search in languages relevant to the topic's geographic context.

## What to implement

### 1. Integrate into the pipeline

In `src/pipeline.py`, modify `_produce_single()` to add the Research Agent step between perspektiv and writer:

```python
# In _produce_single(), after the perspektiv block and before the writer block:

# Research Agent (multilingual deep search)
research_dossier: dict = {}
if researcher := self.agents.get("researcher"):
    result = await researcher.run(
        "Research this topic with multilingual web searches. "
        "Find sources in languages relevant to the topic's geographic context.",
        context=assignment_data,
    )
    research_dossier = _extract_dict(result) or {}
```

Then pass the research dossier to the Writer as additional context:

```python
# Update the writer_context to include research dossier
writer_context = {
    **assignment_data,
    "perspectives": perspectives,
    "research_dossier": research_dossier,  # NEW
}
```

### 2. Add the agent to run.py

In `scripts/run.py`, add the researcher agent to `create_agents()`:

```python
"researcher": Agent(
    name="researcher",
    model="z-ai/glm-5",
    prompt_path=str(agents_dir / "researcher" / "AGENTS.md"),
    tools=[web_search_tool],
    temperature=0.2,
    provider="openrouter",
),
```

Use `glm-5` — the research task requires reasoning to construct good non-English queries. Temperature 0.2 (lower than Writer) because research should be precise, not creative.

### 3. Update debug output numbering

In `_produce_single()`, add debug output for the researcher and shift the writer debug number:

```python
# After researcher runs:
if research_dossier:
    slug = assignment.topic_slug or assignment.id
    self._write_debug_output(f"04-researcher-{slug}.json", research_dossier)
```

The existing writer debug output (`04-writer-{slug}`) should be renumbered to `05-writer-{slug}`.

### 4. Update the Writer prompt

Add a section to `agents/writer/AGENTS.md` that tells the Writer how to use the research dossier:

In STEPS, after step 1, add:

```
1b. If a research_dossier is present in the context, it contains pre-researched sources from multiple languages gathered by the Research Agent. USE THESE SOURCES. Re-index them from rsrc-NNN to src-NNN in your sources array. You may still use web_search for additional sources, but the research dossier is your primary multilingual source base.
```

In RULES, update RULE 7 (quotes in original language) to reference the research dossier:

```
RULE 7 — QUOTES IN ORIGINAL LANGUAGE. When citing non-English sources — including those from the research dossier — provide the original-language quote followed by a translation in parentheses.
```

### 5. Add the 10-second delay

Add a small delay (10s) between researcher and writer within the same topic to avoid rate limits:

```python
# In _produce_single(), between researcher and writer:
if research_dossier:
    import asyncio
    logger.info("Waiting 10s between researcher and writer...")
    await asyncio.sleep(10)
```

## What NOT to do

- Do NOT create `agents/researcher/AGENTS.md` — that file is provided by the prompt engineer
- Do NOT modify the Agent class (`src/agent.py`) — no changes needed
- Do NOT modify the Tool system — the researcher uses the existing `web_search` tool
- Do NOT add new dependencies
- Do NOT change the Collector, Curator, or Editor agents
- Do NOT modify the TopicPackage schema — the research dossier is consumed by the Writer and does not appear in the final output

## How to test

```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
source .venv/bin/activate && source .env && python scripts/run.py
```

**Success criteria:**
1. Pipeline completes with 3/3 topics (no regressions)
2. Debug output includes `04-researcher-{slug}.json` for each topic
3. Researcher debug files show `research_queries` with non-English queries
4. Writer debug files show sources from multiple languages (check `sources[].language`)
5. Final Topic Package articles contain non-English source citations

## Expected impact

- Source language diversity: from 100% English to 40-60% English + 40-60% other languages
- Runtime increase: ~2-4 minutes per topic (6-10 additional web searches × ~15s each)
- Cost increase: ~$0.05-0.10 per topic (one additional glm-5 call + Perplexity searches)
- Total pipeline runtime: from ~20 min to ~30 min for 3 topics

## Reference

- Read `/Users/denizschwenk/Documents/nanobot-main/` for architectural patterns (especially `nanobot/agent/loop.py` for the tool-call loop pattern). Reference only, not a dependency.
- Existing agent prompts in `agents/collector/AGENTS.md`, `agents/writer/AGENTS.md` for prompt structure and style conventions.
- `src/pipeline.py` lines 290-350 (`_produce_single()`) for the exact insertion point.
