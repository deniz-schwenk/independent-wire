# WP-RESEARCHER-SPLIT — Two-Phase Agent Architecture

**Created:** 2026-04-07
**Status:** Ready for implementation
**Priority:** 🔴 Critical — unblocks pipeline reliability
**Estimated effort:** 2-3 hours with Claude Code

## Problem

Agents with `web_search` tools (Researcher, Collector) use a tool-call loop where each iteration re-sends the entire conversation history to the LLM. Context accumulates with every search result:

```
Call 1: [system_prompt + assignment]                    → 5K tokens
Call 2: [system_prompt + assignment + result_1]         → 8K tokens
Call 3: [system_prompt + assignment + result_1 + result_2] → 12K tokens
...
Call N: [everything accumulated]                        → explosion
```

The Researcher for Hormuz (Lauf 7) consumed 85,160 tokens across ~14 search iterations. The final call — where GLM-5 must produce one massive JSON blob with 20+ sources and `actors_quoted` — failed with a JSON parse error. This is the primary cause of the ~30% failure rate.

The Collector has the same pattern (40,828 tokens, 12+ searches) but hasn't failed yet because its output schema is simpler.

## Solution: Plan → Search → Assemble

Split every tool-using agent into three phases:

```
Phase 1 — PLAN (1 LLM call, no tools)
  Input:  Topic assignment (~2K tokens)
  Output: Array of search queries with languages (~1K tokens)
  Cost:   ~3-5K tokens

Phase 2 — SEARCH (Python only, no LLM)
  Execute web_search_tool.execute() directly from Python
  Can run in parallel via asyncio.gather()
  Cost:   0 LLM tokens

Phase 3 — ASSEMBLE (1 LLM call, no tools)
  Input:  Assignment + ALL search results at once (~15-20K tokens)
  Output: Structured JSON dossier (~10-15K tokens)
  Cost:   ~25-35K tokens
```

**Total: 2 LLM calls instead of N. No accumulating context. ~30-35K tokens instead of ~85K.**

## Architecture

### Current flow (agent.py tool loop)
```
researcher.run(message, context) → internal tool loop (N iterations) → JSON output
```

### New flow (pipeline.py orchestrated)
```
researcher_plan.run(message, context)     → query list
Python: web_search_tool.execute() × N     → search results
researcher_assemble.run(message, context) → JSON dossier
```

No changes to `agent.py`. The Agent class stays as-is. All changes are in `pipeline.py` (orchestration) and `run.py` (agent registration).


## Files to Create

### 1. `agents/researcher/PLAN.md` — Research Planner prompt

This prompt receives a topic assignment and outputs ONLY a JSON array of search queries. No searching, no summaries, no dossier assembly.

**Key requirements for the prompt:**
- Input: topic assignment with title, selection_reason, raw_data
- Output: JSON array of `{"query": "...", "language": "iso_code"}` objects
- Must follow the same language selection logic as the current Researcher (Step 2 of current AGENTS.md)
- Must produce natural queries (not literal translations) — same as current RULE 2
- Must output 8-12 queries total, at least 50% non-English
- MUST NOT search, summarize, or produce any other output

**Output schema:**
```json
[
  {"query": "Trump Strait of Hormuz passage fees 2026", "language": "en"},
  {"query": "مضيق هرمز رسوم العبور ترامب", "language": "ar"},
  {"query": "تنگه هرمز عوارض عبور ترامپ", "language": "fa"}
]
```

### 2. `agents/researcher/ASSEMBLE.md` — Research Assembler prompt

This prompt receives the topic assignment AND all raw search results, then produces the research dossier JSON. No searching — all data is already provided.

**Key requirements for the prompt:**
- Input: assignment + array of `{query, language, results}` objects (raw search output)
- Output: the same dossier schema as current AGENTS.md (topic_id, research_queries, sources with actors_quoted, preliminary_divergences, etc.)
- Must extract sources, actors_quoted, divergences, coverage_gaps from the provided results
- Must apply all current RULEs (source ID prefix rsrc-, no YouTube/Wikipedia, full URLs, etc.)
- MUST NOT call any tools
- Maximum 15 sources (if more found, keep the 15 most diverse by language/region/perspective)

### 3. `agents/collector/PLAN.md` — Collector Planner prompt

Same pattern for the Collector. Receives today's date, outputs search queries.

**Key requirements:**
- Input: today's date
- Output: JSON array of `{"query": "...", "region": "...", "topic_area": "..."}` objects
- Must cover at least 5/6 topic areas and 4/6 world regions (same as current AGENTS.md Step 1)
- Must produce 12-16 queries total
- Queries MUST target current news (use "today", "this week", current date)

### 4. `agents/collector/ASSEMBLE.md` — Collector Assembler prompt

Receives all raw search results, outputs the findings array.

**Key requirements:**
- Input: array of `{query, region, topic_area, results}` objects
- Output: JSON array of findings (same schema as current AGENTS.md)
- Must deduplicate by URL
- Must produce 20-40 findings
- All current RULEs apply (no social media, no bare domains, neutral summaries)


## Code Changes

### 5. `run.py` — Register new agents

Add four new agent registrations. The planners can use a cheaper model (minimax-m2.7) since query planning is a simple task. The assemblers use GLM-5 (or whatever model we're evaluating).

```python
# New agents for two-phase pattern
"researcher_plan": Agent(
    name="researcher_plan",
    model="minimax/minimax-m2.7",       # simple task, cheap model
    prompt_path=str(agents_dir / "researcher" / "PLAN.md"),
    tools=[],                            # NO tools
    temperature=0.2,
    provider="openrouter",
),
"researcher_assemble": Agent(
    name="researcher_assemble",
    model="z-ai/glm-5",                 # complex JSON output
    prompt_path=str(agents_dir / "researcher" / "ASSEMBLE.md"),
    tools=[],                            # NO tools
    temperature=0.2,
    provider="openrouter",
),
"collector_plan": Agent(
    name="collector_plan",
    model="minimax/minimax-m2.7",
    prompt_path=str(agents_dir / "collector" / "PLAN.md"),
    tools=[],
    temperature=0.2,
    provider="openrouter",
),
"collector_assemble": Agent(
    name="collector_assemble",
    model="minimax/minimax-m2.7",        # collector output is simpler
    prompt_path=str(agents_dir / "collector" / "ASSEMBLE.md"),
    tools=[],
    temperature=0.2,
    provider="openrouter",
),
```

**Keep the old `researcher` and `collector` registrations** — they are still used as fallback and for the `--from` partial run support. Mark them with a comment `# legacy: single-call with tool loop`.

### 6. `pipeline.py` — Two-phase research in `_produce_single()`

Replace the single `researcher.run()` call with three phases. Below is the target logic (not copy-paste code — Claude Code must adapt to the existing code structure):

```python
async def _research_two_phase(self, assignment_data: dict, slug: str) -> dict:
    """Two-phase research: plan queries, execute in Python, assemble dossier."""
    import asyncio

    # Phase 1: Plan
    planner = self.agents.get("researcher_plan")
    if not planner:
        # Fallback to legacy single-call researcher
        return await self._research_legacy(assignment_data, slug)

    plan_result = await planner.run(
        f"Plan multilingual research queries for this topic. Today is {self.state.date}.",
        context=assignment_data,
        output_schema={"type": "array", "items": {"type": "object"}},
    )
    self._track_agent(plan_result, "researcher_plan", slug)

    queries = plan_result.structured
    if not queries or not isinstance(queries, list):
        logger.warning("Researcher planner returned no queries, falling back to legacy")
        return await self._research_legacy(assignment_data, slug)

    logger.info("Researcher plan: %d queries across %d languages",
                len(queries),
                len({q.get("language", "en") for q in queries}))

    # Phase 2: Execute searches in Python (no LLM)
    from src.tools import web_search_tool

    search_results = []
    for q in queries:
        query_str = q.get("query", "")
        if not query_str:
            continue
        try:
            result = await web_search_tool.execute(query=query_str)
            search_results.append({
                "query": query_str,
                "language": q.get("language", "en"),
                "results": result,
            })
        except Exception as e:
            logger.warning("Search failed for '%s': %s", query_str, e)
            search_results.append({
                "query": query_str,
                "language": q.get("language", "en"),
                "results": f"Error: {e}",
            })

    logger.info("Researcher search: %d/%d queries returned results",
                len([r for r in search_results if not r["results"].startswith("Error")]),
                len(search_results))

    # Phase 3: Assemble dossier (one LLM call, no tools)
    assembler = self.agents.get("researcher_assemble")
    if not assembler:
        return await self._research_legacy(assignment_data, slug)

    assemble_result = await assembler.run(
        "Build a research dossier from these search results. "
        "Extract sources, actors, divergences, and coverage gaps.",
        context={
            "assignment": assignment_data,
            "search_results": search_results,
        },
    )
    self._track_agent(assemble_result, "researcher_assemble", slug)

    dossier = _extract_dict(assemble_result) or {}
    return dossier
```

### 7. `pipeline.py` — Two-phase collection in `collect()`

Same pattern for the Collector:

```python
async def collect(self) -> list[dict]:
    """Two-phase collection: plan queries, execute in Python, assemble findings."""
    planner = self.agents.get("collector_plan")
    assembler = self.agents.get("collector_assemble")

    if not planner or not assembler:
        # Fallback to legacy single-call collector
        return await self._collect_legacy()

    # Phase 1: Plan
    plan_result = await planner.run(
        f"Plan search queries for today's global news scan. Today is {self.state.date}.",
        output_schema={"type": "array", "items": {"type": "object"}},
    )
    self._track_agent(plan_result, "collector_plan")
    queries = plan_result.structured or []

    # Phase 2: Execute searches
    from src.tools import web_search_tool
    search_results = []
    for q in queries:
        result = await web_search_tool.execute(query=q.get("query", ""))
        search_results.append({"query": q, "results": result})

    # Phase 3: Assemble findings
    assemble_result = await assembler.run(
        "Compile these search results into a JSON array of news findings.",
        context={"search_results": search_results},
    )
    self._track_agent(assemble_result, "collector_assemble")
    return _extract_list(assemble_result) or []
```

**Important:** Move the current `collect()` logic into `_collect_legacy()` for fallback.


## Debug Output

The two-phase approach generates additional debug files:

```
04-researcher-plan-{slug}.json        # Query plan from Phase 1
04-researcher-search-{slug}.json      # Raw search results from Phase 2
04-researcher-{slug}.json             # Final assembled dossier (same as before)
04-researcher-{slug}-RAW.json         # Only if Phase 3 JSON parse fails
```

For the Collector:
```
01-collector-plan.json                # Query plan
01-collector-search.json              # Raw search results
01-collector-raw.json                 # Final assembled findings (same as before)
```

## Testing Strategy

### Test 1: Researcher only (partial run)
```bash
python scripts/run.py --from researcher --reuse 2026-04-07 --topic 1
```
Compare tokens and output quality against Lauf 7 results for the same topic.

### Test 2: Full pipeline (Lauf 8)
```bash
python scripts/run.py
```
All 3 topics must complete. Total tokens should be significantly lower than Lauf 7's 476K.

### Expected token savings

| Agent | Lauf 7 (old) | Expected (new) | Savings |
|-------|-------------|----------------|---------|
| Researcher (Topic 1, 40K) | 40,607 | ~20,000 | ~50% |
| Researcher (Topic 2, 85K) | 85,160 | ~30,000 | ~65% |
| Researcher (Topic 3, 68K) | 68,451 | ~25,000 | ~63% |
| Collector | 40,828 | ~15,000 | ~63% |
| **Pipeline total** | **476,915** | **~300,000** | **~37%** |

## Implementation Order

1. Create prompt files (PLAN.md and ASSEMBLE.md for both agents) — **Prompt Engineer workflow**
2. Register new agents in `run.py`
3. Implement `_research_two_phase()` in `pipeline.py`, keep legacy as fallback
4. Implement two-phase `collect()`, keep legacy as fallback
5. Add debug output for plan and search phases
6. Test with partial run (researcher only, 1 topic)
7. Test with full pipeline run (Lauf 8)

## Prompt Engineer Briefings

The four prompts (researcher/PLAN.md, researcher/ASSEMBLE.md, collector/PLAN.md, collector/ASSEMBLE.md) follow the Prompt Engineer workflow:
1. Architect (this Claude) writes briefings as code blocks
2. Deniz passes briefings to Prompt Engineer Claude project
3. Prompt Engineer returns finished prompts
4. Architect reviews and writes approved prompts to `agents/{name}/`

**Briefings will be provided separately in chat, not in this file.**

## Future: Parallel Search Execution

Phase 2 currently runs searches sequentially. A future optimization is parallel execution:

```python
# Future: parallel search
tasks = [web_search_tool.execute(query=q["query"]) for q in queries]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

Not included in this WP to keep scope minimal. Rate limits may require throttling.

## Future: Model Flexibility for Phase 3

With the two-phase split, WP-RESEARCHER-EVAL becomes much simpler. Instead of testing 8 models across the entire tool-loop, we only need to test which model produces the best JSON output in Phase 3 (Assembler). The input is identical, the output schema is identical — a clean A/B test.

Candidate models for Phase 3 (from Deniz's list):
Kimi K2.5 | MiMo-V2-Pro | GLM 5V Turbo | Qwen3.6 Plus | MiniMax M2.7 | GLM 5 | DeepSeek V3.2 | Step 3.5 Flash

## Caching Implications

The two-phase split also improves caching potential:
- Phase 1 (Planner): System prompt is identical across all topics → cacheable
- Phase 3 (Assembler): System prompt is identical across all topics → cacheable
- The variable part (search results) is always at the END of the context → maximizes cache prefix hits

This directly addresses Deniz's caching question from the session discussion.

---

## Claude Code Instruction

```
Read WP-RESEARCHER-SPLIT.md in the repo root. This implements a two-phase architecture
for the Researcher and Collector agents to eliminate accumulating context in tool loops.

IMPORTANT: Do NOT write the agent prompts (PLAN.md, ASSEMBLE.md). Those will be provided
separately via the Prompt Engineer workflow. Only implement the code changes:

1. Register the 4 new agents in scripts/run.py (researcher_plan, researcher_assemble,
   collector_plan, collector_assemble). Keep old registrations with "# legacy" comment.

2. Add _research_two_phase() method to Pipeline class in src/pipeline.py.
   Call it from _produce_single() where researcher.run() currently is.
   Move the current researcher logic into _research_legacy() as fallback.
   If "researcher_plan" agent is not registered, fall back to legacy automatically.

3. Add two-phase logic to collect() in pipeline.py.
   Move current collect() logic into _collect_legacy() as fallback.
   If "collector_plan" agent is not registered, fall back to legacy automatically.

4. Write debug output for plan and search phases (04-researcher-plan-{slug}.json,
   04-researcher-search-{slug}.json, 01-collector-plan.json, 01-collector-search.json).

5. Track all agent calls with self._track_agent() for token stats.

Reference /Users/denizschwenk/Documents/nanobot-main/ for patterns, especially
nanobot/agent/loop.py and nanobot/agent/subagent.py for how tool execution
and sub-agent patterns are structured. Use as reading material only, not as dependency.

Test: python scripts/run.py --from researcher --reuse 2026-04-07 --topic 1
(Will fail until prompts are provided — that's expected. Code structure is the goal.)
```

## Search Result Deduplication (Phase 2)

Between Phase 2 (search execution) and Phase 3 (assembly), Python deduplicates search results by URL. This prevents the Assembler from receiving the same article multiple times from different queries.

**Deduplication logic:**

```python
def _deduplicate_search_results(search_results: list[dict]) -> list[dict]:
    """Deduplicate search results by URL, merging query sources.
    
    If the same URL appears in results from multiple queries, keep one entry
    but record all queries that found it in a 'found_by_queries' array.
    
    Input: [{"query": "...", "language": "en", "results": "raw text with URLs"}]
    Output: same structure but with duplicates merged
    """
    # Parse URLs from raw result text
    # Group by URL
    # For each unique URL: keep the richest snippet, list all queries that found it
    # Return deduplicated results
```

**Important:** The raw search results from `web_search_tool.execute()` are plain text, not structured JSON. The deduplication function must parse URLs from the text output. The format from `_format_results()` in `web_search.py` is:

```
Results for: {query}

1. {title}
   {url}
   {snippet}
2. {title}
   {url}
   {snippet}
```

Claude Code should implement the URL extraction and deduplication based on this format.

When two results share the same URL but came from different queries, merge them:
- Keep the longest/richest snippet
- Add a `found_by` field listing all queries that surfaced this URL
- This gives the Assembler signal about which sources are broadly relevant (found by many queries) vs. niche (found by one specific language query)


## Updated Design Decisions (from prompt review)

### No upper limit on query count
The planner must NOT have a hard upper limit on queries. Simple local topics may need 8 queries, complex geopolitical topics with 6+ affected regions may need 18+. The prompt sets a MINIMUM (at least 8, at least 50% non-English) but the upper bound is determined by topic complexity.

### Planner temperature: 0.5 (not 0.2)
The planner benefits from higher variance to produce creatively diverse search queries. Temperature 0.2 would produce conservative, predictable queries. Temperature 0.5 gives enough variance for diverse angles without losing coherence. Update the agent registration in run.py accordingly:
- `researcher_plan`: temperature=0.5
- `collector_plan`: temperature=0.5

### Query distinctiveness rule (prompt level)
The planner prompt must include a rule against marginal query variants. Queries that differ only by one word ("Iran conflict 2026" vs "Iran crisis 2026") waste search calls and produce duplicate results. Each query should target a distinct angle, region, or information need.


## Future Optimization: Python Collector Assembler

The Collector Assembler (LLM) could be replaced by a Python function that parses 
the plaintext search results deterministically: extract URLs, titles, snippets, 
map domains to outlet names, assign regions. This would save ~10-15K tokens per run.

The interface stays the same (JSON array in, JSON array out), so this is a clean 
swap when needed. Not in scope for this WP — revisit when optimizing run costs.


## Model Assignment (updated after test run)

### Planner: GLM-5 (not minimax-m2.7)
The test run revealed that minimax-m2.7 produces encoding errors in multilingual 
queries (mixed Arabic/Chinese script) and incorrect calendar systems (Persian year 
۱۳۸۵ instead of ۱۴۰۵). These are not prompt-fixable edge cases — they require 
genuine multilingual competence. GLM-5 handles non-Latin scripts and cultural 
context reliably.

- `researcher_plan`: model z-ai/glm-5, temperature 0.5
- `collector_plan`: model z-ai/glm-5, temperature 0.5

### Assembler: Test minimax-m2.7, fallback to GLM-5
The assembler role (extract, structure, compare) may be simple enough for minimax. 
Test with one run. If minimax produces clean JSON with correct source extraction 
and meaningful divergences, keep it. If not, switch to GLM-5.

- `researcher_assemble`: start with minimax/minimax-m2.7, evaluate output quality
- `collector_assemble`: start with minimax/minimax-m2.7 (simple schema, should work)

