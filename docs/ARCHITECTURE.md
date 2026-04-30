# Independent Wire — Framework Architecture

## Decision

Independent Wire uses its own minimal Python framework instead of OpenClaw, Hermes Agent, Nanobot, or Paperclip. The framework is purpose-built for a **deterministic multi-agent news pipeline** — not a general-purpose personal AI assistant.

### Why not an existing framework?

All evaluated frameworks (OpenClaw, Hermes, Nanobot, Paperclip) are **chat-oriented personal assistants**: a human sends a message, an agent responds, optionally using tools. Independent Wire needs something fundamentally different: a **pipeline** where specialized agents with different models, different tools, and different prompts process data sequentially, producing structured JSON output.

The three things we actually need from a framework — LLM API calls, tool execution, and Telegram notifications — are each ~50-100 lines of Python. The overhead of adapting a 3,500-line (Nanobot) or 300,000-line (OpenClaw) framework to do something it wasn't designed for exceeds the cost of building exactly what we need.

### Reference implementation

Nanobot's codebase (`agent/loop.py`, `agent/context.py`, `agent/tools/`) serves as architectural reference for how to structure LLM calls, tool registration, and context building. We don't import it — we learn from it.

---

## V2 transition (planned)

This document describes the V1 pipeline architecture as it stands at the end of S15 (commit tagged `v1-final`). A full V2 architectural redesign is documented in `docs/ARCH-V2-BUS-SCHEMA.md` — RunBus + TopicBus, mirror-and-modify pattern, visibility-driven render layer. V2 implementation begins in a subsequent session and replaces the aggregation-based construction this document describes. V1 remains accessible via the `v1-final` git tag as a rollback baseline.

Read `docs/ARCH-V2-BUS-SCHEMA.md` for the V2 architectural contract. The remainder of this document describes V1.

---

## Three Core Abstractions

Everything in the framework is built on three abstractions. If these are right, everything else — memory, parallelization, new tools, Docker deployment — can be added without rewriting.

### 1. Agent

An Agent is a configured LLM caller. It has an identity (name, system prompt), a model assignment, allowed tools, optional memory, and temperature. It takes a message + context and returns a structured response.

```python
class Agent:
    """A configured LLM caller with identity, model, tools, and memory."""

    def __init__(
        self,
        name: str,                    # e.g. "curator", "writer", "bias_language"
        model: str,                   # e.g. "anthropic/claude-opus-4.6"
        system_prompt_path: str,      # path to SYSTEM.md (identity)
        instructions_path: str,       # path to INSTRUCTIONS.md (per-run task spec)
        tools: list[Tool] = None,     # e.g. [web_search_tool] — None = no tools
        memory_path: str = None,      # optional persistent memory file
        temperature: float = 0.3,     # model temperature
        max_tokens: int = 32000,      # max response tokens
        provider: str = "openrouter", # API provider
        reasoning: str | None = None, # 'none', 'minimal', 'high' (provider-specific)
    ):
        ...

    async def run(
        self,
        message: str = "",
        context: dict = None,                   # JSON-encoded into the User-turn <context> block
        output_schema: dict = None,             # JSON Schema enforced as decoder constraint via OpenRouter response_format (strict mode). See src/schemas.py.
        instructions_addendum: str | None = None,  # appended inside the <instructions> block
    ) -> AgentResult:
        """
        Build the system message as <system_prompt>{SYSTEM.md}</system_prompt>.
        Build the User turn from three blocks: <context>, <memory>, <instructions>.
        Handle tool calls in a loop until final response.
        Return structured result.
        """
        ...


@dataclass
class AgentResult:
    """What an agent returns."""
    content: str                      # raw text response
    structured: dict = None           # parsed JSON if output_schema was provided
    tool_calls: list[dict] = None     # log of tool calls made
    tokens_used: int = 0              # total tokens consumed
    cost_usd: float = 0.0            # estimated cost
    model: str = ""                   # model that was actually used
    duration_seconds: float = 0.0     # wall clock time
```

**Key design decisions:**
- Agents are **async** (`async def run`) — enables future parallelization via `asyncio.gather()`
- Each agent has its **own model** — no global default
- **Tool calls handled inside the agent loop** — same pattern as Nanobot's `loop.py`
- **Structured output** via `output_schema`. The schema is wired as `response_format: {type: "json_schema", strict: true, schema: ...}` on the OpenRouter API call. For Anthropic models, OpenRouter applies the `anthropic-beta: structured-outputs-2025-11-13` header automatically. Decoder masks tokens that would violate the schema before sampling — agents are mechanically incapable of emitting fields outside their schema. All eight production agent schemas live in `src/schemas.py` as a single source of truth. Defense-in-depth (`_extract_dict`, `_extract_list`, `_parse_json`, `json_repair`, `_parse_or_retry_structured`) preserved as fallback when the schema fails to compile or a provider falls back.
- **Memory is a file path**, not a framework feature; loaded into the User-turn `<memory>` block when set
- **Two-file prompt convention** (S13): every agent has `agents/{name}/SYSTEM.md` (identity) + `agents/{name}/INSTRUCTIONS.md` (per-run task spec). Researcher and Hydration Aggregator use phase-named pairs (`PLAN-*`, `ASSEMBLE-*`, `PHASE1-*`, `PHASE2-*`)
- **User-turn three-block layout**: `<context>` (JSON-encoded input + optional message), `<memory>` (when present), `<instructions>` (always present; addendum like Writer FOLLOWUP.md appended inside the closing tag). System message contains only `<system_prompt>{SYSTEM.md}</system_prompt>`

### 2. Pipeline

A Pipeline is a sequence of agent calls with data flow, gating, and integrity checks. The current pipeline flow:

1. **Curate** — LLM clusters and scores ~1,400 RSS findings into topics
2. **Edit** — LLM prioritizes topics, selects top 3 with reasoning
3. **Per topic** (sequential):
   - Researcher Plan → Python search execution → Researcher Assemble
   - Perspektiv Agent (stakeholder map, missing voices)
   - Writer (article with web_search tool)
   - QA+Fix (single call: find errors + apply corrections + return corrected article)
   - Python post-processing (word_count, meta-transparency, sanity checks)
   - Python bias aggregation → Bias Language Analyzer
   - → Topic Package JSON

```python
class Pipeline:
    """Orchestrates agents in a defined sequence with data flow and gating."""
    
    def __init__(
        self,
        name: str,
        agents: dict[str, Agent],
        mode: str = "full",
        telegram: TelegramNotifier = None,
    ):
        ...

    async def run(self, date: str = None) -> list[TopicPackage]: ...
    async def curate(self, raw: list[dict]) -> list[dict]: ...
    async def editorial_conference(self, topics: list[dict]) -> list[dict]: ...
    async def _research_two_phase(self, assignment: dict, slug: str) -> dict: ...
    async def _produce_single(self, assignment: TopicAssignment) -> TopicPackage: ...
    # Per-topic flow inside _produce_single:
    #   Researcher Plan → Python search → Researcher Assemble →
    #   Perspektiv → Writer → QA+Fix → Python build_bias_card → Bias Language
    async def verify(self, packages: list[TopicPackage]) -> list[TopicPackage]: ...
    async def gate(self, step_name: str, data: any) -> bool: ...
```

**Key design decisions:**
- Pipeline steps are **explicit methods**, not LLM-orchestrated
- **Gating** is a first-class concept (Telegram confirmation)
- **Verify sweep** is built in (article counting is mandatory)
- Steps are async, enabling future parallelization

### 3. Tool

A Tool is a callable function that agents can use during their LLM loop.

```python
class Tool:
    """A callable function that agents can invoke during LLM interaction."""
    
    def __init__(self, name: str, description: str, parameters: dict, handler: Callable):
        ...

class ToolRegistry:
    """Manages available tools. Each agent gets a filtered subset."""
    
    def register(self, tool: Tool): ...
    def get_for_agent(self, allowed: list[str]) -> list[Tool]: ...
    def to_openai_format(self, allowed: list[str]) -> list[dict]: ...
```

**Key design decisions:**
- Tools are **swappable** — `web_search` can use Brave today and SearXNG tomorrow
- Tool permissions are **per-agent** — strict allow-lists
- Tools use the **OpenAI function-calling format**
- The registry pattern means new tools require no agent code changes

---

## Architectural Principles

Two non-negotiable principles govern how work is divided between Python and LLM agents. They have **direct, measurable impact on both output quality and operating cost** and must be applied without exception.

Violations of these principles are architectural debt, not stylistic preference. Every LLM token spent on work Python could do deterministically is waste — both in money and in the noise it introduces into the model's reasoning. Every piece of data an agent must pass through instead of originate is a risk: the model may reformat it, drop it, or transform it silently. Python-routed data flow eliminates that entire class of failure.

**These principles apply to every agent in the pipeline, without exception.** They apply equally to the agents already in production (which were built before these principles were formalized) and to future agents (including the Hydration Aggregator). The current production agents have not been systematically audited against these principles yet — this is a known open work item, documented as an audit commitment below.

### Principle 1 — Deterministic before LLM

**If a piece of work can be solved deterministically in Python, it must be solved in Python.** LLM calls are reserved for genuinely non-deterministic work (summarization, cross-language comparison, stakeholder identification, bias analysis). Normalization, ID assignment, schema compliance, counting, indexing, language-code formatting — these are Python's job.

Applied in the current pipeline:
- Curator enrichment (`_enrich_curator_output`): computes `geographic_coverage`, `languages`, `source_diversity`, `missing_regions`, `missing_languages` deterministically from raw finding metadata. The Curator LLM only clusters and scores.
- Source URL deduplication (before Curator).
- Word count computation (never trust LLM counting).
- Meta-transparency fixup (language and source counts in article body).
- Date extraction from URLs (`_extract_date_from_url`).
- Bias Card aggregation (`_build_bias_card`): counts sources by language and country, identifies geographic gaps — all Python. Bias Language LLM analyzes only the prose itself.
- Source ID reindexing between pipeline stages (rsrc-NNN → src-NNN).

This principle extends to the Hydration pipeline (Etappe 2, see below): language codes, country lookup, and article titles are normalized in Python before the Aggregator LLM sees them. The Aggregator never faces raw, inconsistent input.

### Principle 2 — Agents produce only originary output

**An agent must only output what it genuinely creates through its own work.** Fields that are simply passed through — URLs, outlet names, language codes, dates, titles — should not appear in the agent's output schema. Python handles the pass-through and merges originary agent output with reference data.

The cost of violating this principle is both tokens (input + output paid twice for no value) and architecture (agents become brittle format-translators instead of reasoning modules).

Applied in the current pipeline:
- Bias Language agent outputs only `language_bias` findings and `reader_note` — it does not re-emit the source list or divergences, which Python aggregates separately.
- QA+Fix returns corrections plus the corrected article body — not the full Topic Package, which Python assembles.

Applied in the Hydration Aggregator (Etappe 2): the agent returns `article_analyses[]` with only `article_index`, `summary`, and `actors_quoted` per article. URL, outlet, language, country, title, estimated_date are pass-through via Python merge, keyed by `article_index`.

### Audit Commitment

The two principles above were formalized during Session 10 (April 2026), after several pipeline iterations. Most production agents were built before that formalization and have not yet been systematically reviewed against the principles. Some obvious applications have been retrofitted (Bias Language, QA+Fix), but a complete audit has not happened.

**A pipeline-wide audit is an open work item.** Every production agent prompt and its input/output contract must be reviewed against these two principles. The audit procedure:

1. For each agent, identify every field in its output schema.
2. Classify each field as either **originary** (the agent genuinely created it through reasoning) or **pass-through** (the field was in the input and the agent just reproduced it).
3. Every pass-through field is a candidate for removal — Python should merge it back in after the LLM call.
4. For each input the agent receives, identify every normalization, enrichment, or pre-processing step.
5. Any normalization currently done by the LLM (language codes, country lookups, date formatting, ID assignment, deduplication) should move to Python before the call.
6. Measure token savings per agent before and after the change. Record in a follow-up session handoff.

Agents to be audited, in priority order by current token volume:

- **Writer** — the largest cost center (40-120K tokens/topic). Highest-value audit target. Specifically: does the Writer re-emit source metadata that Python already has? Does it rewrite the source list schema or pass it through? Each redundant field costs real money at Opus rates.
- **Curator** — processes ~1,400 findings, cheapest model but largest input. Verify that its output contains only cluster decisions (groupings + scores), not repeated finding metadata. Current enrichment (`_enrich_curator_output`) already removed some fields — check if more is possible.
- **Researcher Assembler** — the dossier it produces is consumed by Writer and Perspektiv. Every pass-through field multiplies downstream.
- **Perspektiv** — stakeholder extraction is genuinely originary, but check whether region/country lookups could move to Python using the source metadata already known.
- **QA+Fix** — returns the corrected article. The article body is originary (post-correction) but the sources list in its output may be redundant with what Python has from the Writer.
- **Editor** — smallest input and output, audit for completeness but likely low yield.
- **Bias Language** — already redesigned in Session 9 to output only originary content (`language_bias` + `reader_note`). Confirm baseline.

This audit is not blocking Etappe 2 implementation, but it should happen before any future pipeline extension. The cost and quality gains compound: every token saved at the Writer or Curator is a token we don't pay for, and every pass-through we remove is a class of inconsistency eliminated from the data flow.

### Contract discipline

**Agent output schemas in task briefs are complete specifications.** Unlisted fields are not added silently by implementation; useful telemetry is surfaced as questions for architect review. This rule was formalized after a Session 11 incident where a Claude Code implementation added a `fetch_started_at` field to the hydration output without it being in the brief. The same discipline applies to pipeline helper functions and Topic Package schema: additions are decisions, not drift.

### Field-absence vs null value (Perspektiv-Sync pattern)

**When an agent emits delta output, field absence and null value carry different semantics.** Absence means "do not touch this field"; null means "set this field to null" (e.g. remove a quote). Python checks must use `"field" in delta`, never `delta.get("field") is None`. This applies to any delta-emitting agent added in the future — the convention prevents silent data corruption where a genuinely-removed value is preserved because the absent-field case was conflated with the null-value case.

---

## Error Handling and Retries

Agent-level exponential backoff with jitter for transient API errors (429, 5xx). Auth errors (401/403) and invalid requests (400) are raised immediately. Pipeline continues after individual topic failures — failed topics are logged and reported. State is persisted after each major step for crash recovery.

## Configuration

File-based, environment-overridable, path-agnostic. API keys are **never** in the config file — config references env var names, the loader reads actual values from the environment. Profile system for model overrides (develop/demo).

## Dependencies (Minimal)

```toml
dependencies = [
    "openai>=1.0",          # OpenAI-compatible API client (works with OpenRouter)
    "httpx",                # async HTTP for tool implementations
    "feedparser",           # RSS feed parsing
    "json-repair",          # recovery of malformed LLM JSON output
    "trafilatura",          # article full-text extraction (Hydration pipeline)
    "aiohttp",              # parser-tolerant async HTTP (Hydration pipeline)
]
```

No numpy. No pandas. No langchain. No pytorch. Six dependencies total, all single-purpose. `trafilatura` and `aiohttp` serve the Hydration pipeline (full-text extraction + parser-tolerant async HTTP). Production pipeline uses only the first four.

---

## What This Architecture Enables (Without Rewriting)

| Future Need | How It's Handled |
|-------------|-----------------|
| **Memory** | `Agent.memory_path` loads memory into the User-turn `<memory>` block at runtime |
| **Parallelization** | `asyncio.gather()` — agents are already async |
| **New tools** | `registry.register(new_tool)` |
| **Docker deployment** | All config via env vars or config file |
| **Different providers** | Agent's `provider` field |
| **Structured output** | Agent's `output_schema` parameter; schema enforced at decode time via OpenRouter response_format |
| **Error recovery** | Pipeline resumes from last checkpoint |

## Current Model Assignments (April 2026)

All assignments validated through 90+ eval calls across 14 models, plus the Session-12 Phase-2 blind eval over 5 additional variants. Reasoning=none everywhere. Synthesis agents all run at temperature 0.1; extraction agents at 0.2-0.3.

| Agent | Model | Provider | Role |
|-------|-------|----------|------|
| Curator | google/gemini-3-flash-preview | OpenRouter | Cluster + score + summarize 1,400+ findings |
| Editor | anthropic/claude-opus-4.6 | OpenRouter | Prioritize topics, assign selection_reason |
| Researcher Plan | google/gemini-3-flash-preview | OpenRouter | Generate multilingual search queries |
| Researcher Assemble | google/gemini-3-flash-preview | OpenRouter | Build research dossier from search results |
| Perspektiv | anthropic/claude-opus-4.6 | OpenRouter | Position-cluster map (V2): `position_clusters[]` + `missing_positions[]`. Python adds `pc-NNN`, `actors[]`, `regions[]`, `languages[]`, `representation` |
| Writer | anthropic/claude-opus-4.6 | OpenRouter | Write article with web_search tool access; emits `[rsrc-NNN]` / `[web-N]` citations (Python renumbers to `[src-NNN]` before QA+Fix) |
| QA+Fix | anthropic/claude-sonnet-4.6 | OpenRouter | Find problems, propose corrections, return corrected article. Output: `problems_found[]`, `proposed_corrections[]`, `article`, `divergences[]` |
| Perspektiv-Sync | anthropic/claude-opus-4.6 | OpenRouter | (Hydrated only) Re-align position-cluster map after QA+Fix. V2 emits `position_cluster_updates[]` with optional `position_label` / `position_summary` deltas |
| Bias Language | anthropic/claude-opus-4.6 | OpenRouter | Analyze language bias; reads pre-aggregated `bias_card` (Python) and emits `language_bias` + `reader_note` |
| Hydration Aggregator Phase 1 | google/gemini-3-flash-preview | OpenRouter | Per-chunk article extraction (parallel, chunked). Returns `article_analyses[]` only. |
| Hydration Aggregator Phase 2 | anthropic/claude-opus-4.6 | OpenRouter | Cross-corpus reducer (single call, temp 0.1). Returns `preliminary_divergences[]` + `coverage_gaps[]`. |

**Migration pending:** All `anthropic/claude-opus-4.6` agents above are staged for simultaneous migration to `anthropic/claude-opus-4.7` as a single workstream (WP-OPUS-4.7-MIGRATION). Opus 4.7 removes `temperature`, `top_p`, `top_k` as supported parameters (returns 400 on any non-default value) and replaces discrete reasoning levels with `output_config.effort` (low/medium/high/xhigh/max, always active). This requires `src/agent.py` refactor plus per-agent effort-level evaluation before cutover — not a drop-in swap.

## Hydration Pipeline (Etappe 2 — Integrated, Production-Ready)

The Production pipeline described above treats the Curator's clustered RSS findings as a ranking signal only: after the Editor selects the top 3 topics, the Researcher begins from zero, querying the web independently via search snippets. The RSS-cluster content — 15-25 articles per topic across 5-8 languages — is discarded. The Writer never sees the actual RSS source texts, only Web-Search snippets.

**Etappe 2 adds a parallel pipeline that uses the cluster content.** After the Editor and before the Researcher, a new step fetches the cluster URLs directly via HTTP, extracts article full-text, and passes it through a two-phase chunked Aggregator LLM pipeline that produces a pre-dossier in the same shape as the Researcher Assembler output. The Researcher Assembler then extends this pre-dossier with web-search results covering gaps that the cluster did not. Python merges both dossiers by reindexing `rsrc-NNN` source IDs.

The Hydrated pipeline (`src/pipeline_hydrated.py`) is feature-complete as of Session 11 and operates in parallel to production. Both pipelines share Curator, Editor, Perspektiv, Writer, QA+Fix, and Bias Language. Only the research step differs. T4 compare orchestrator (`scripts/compare_pipelines.py`, Session 12) runs both on shared assignments and produces side-by-side metric reports for qualitative review.

### Why it was decided

Two feasibility spikes established the empirical base:

**Spike 1 — Fetch viability (httpx + trafilatura):** 30/51 URLs from Lauf 19's produced topics extracted to full-text (58.8%). Failures concentrated in two categories: 10 URLs in `connection_error` caused by httpx's strict HTTP parser rejecting Anadolu Agency's non-conformant Transfer-Encoding headers; 11 URLs in `bot_blocked` or `partial` from real outlet policy (FT, Axios, SCMP, Dawn, Meduza, Le Monde paywalls).

**Spike B — Parser tolerance (aiohttp):** Swapping httpx for aiohttp recovered all 6 Anadolu URLs. Success rate rose to 70.6% (36/51). Remaining failures are structural, not tooling: Press TV unreachable from this network (tls_error subtype, likely sanctions-routing), and the bot-protected / paywalled outlets are not recoverable by any respectful-scraping approach.

**Spike C — Aggregator quality (two Gemini models):** The Hydration Aggregator prompt was tested on the 36 Spike-B successes across `google/gemini-3-flash-preview` and `google/gemini-3.1-flash-lite-preview`. Flash-preview: 100% structural compliance (12/12 articles analyzed per topic), avg 36-55 word summaries, 4-5 divergences and 4 gaps per topic. Flash-lite: 11/12 on one topic (Rule 1 violation — a disqualification for production), shallower summaries, fewer divergences. Decision: **`google/gemini-3-flash-preview` as the production Aggregator model.** Cost per topic: ~$0.015, ~17 seconds per call on 10K-17K input tokens. Full-text quality of recovered articles (300-900 words per article with lead, body, and attribution) substantially exceeds what Perplexity snippets provide.

### Scraping ethics position

The Hydration pipeline fetches article full-text from public RSS-listed URLs. This is text-and-data mining for editorial analysis, not content republication. Independent Wire's operating principles for this pipeline:

1. **Only top-3 produced topics are fetched**, not the 1,400+ full feed findings.
2. **Identifiable bot user-agent**: `Independent-Wire-Bot/1.0 +https://independentwire.org` — outlets can see us and contact us.
3. **Per-domain rate limit**: 1 request per second maximum.
4. **Robots.txt respected** — any `Disallow` on the target path means no fetch.
5. **No circumvention** of Cloudflare, CAPTCHA, or paywalls. When an outlet blocks, we skip.
6. **Full-text used only as LLM-context** for paraphrased journalism. Never reproduced verbatim in the published article.
7. **Public documentation** in the repo README: the list of outlets regularly fetched, the user-agent string, purpose, and the Remove-My-Outlet contact.

Under this discipline, Hydration is indistinguishable in moral weight from the Production pipeline's existing reliance on Perplexity (which itself scrapes and caches outlet content). The difference is ownership: we take the responsibility and the transparency burden directly rather than pay a third party to do it with less visibility.

### Aggregator Chunking Architecture (Session 12)

The original Aggregator was a single monolithic call: all N successfully-fetched articles entered one LLM prompt, and the model produced both per-article analyses and cross-corpus divergences/gaps in one response. This worked on small inputs (≤15 articles) but failed systematically on larger inputs: Gemini 3 Flash dropped exactly one article's analysis when N ≥ 17, triggering a Rule 1 validation crash in `_validate_aggregator_output`.

The diagnosis was not that Gemini 3 Flash is unsuitable — it is excellent at per-article extraction — but that attention load on the extraction task grew with N faster than attention budget. The architectural response was to split the Aggregator into two phases and chunk the first phase:

**Phase 1 — Per-article extraction (parallel, chunked):**
- Chunk sizing: `ceil(N / 10)` chunks, distributed evenly so every chunk has between 5 and 10 articles.
- Chunks fire in parallel via `asyncio.gather`. Each chunk's LLM call runs the registered `hydration_aggregator_phase1` agent (loading `agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md`) and returns `article_analyses[]` for only its chunk's articles.
- Intelligent retry per chunk, max 2 attempts. If the response is missing some `article_index` values, the retry sends only the missing articles back as a smaller input. This both reduces the attention load on the retry and eliminates re-work for already-successful extractions in the same chunk.
- Hard crash after 2 retries of a chunk. Silent data loss is worse than pipeline failure.

**Phase 2 — Cross-corpus reducer (single call):**
- After all Phase 1 chunks complete, Python merges `article_analyses[]` into a flat sorted list by `article_index`.
- A single LLM call runs the registered `hydration_aggregator_phase2` agent (loading `agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md`) with the merged analyses plus per-article metadata (language, country, outlet). This produces `preliminary_divergences[]` and `coverage_gaps[]` in one shot.
- Cross-linguistic and cross-regional observations require a global view of the corpus, which Phase 1's chunked extraction cannot produce. The Phase 2 input is compact (summaries, not full-text), so attention load is low regardless of N.
- Phase 2 model is selected for synthesis quality, independent of the extraction model. Phase 1 uses Gemini 3 Flash (excellent structured extraction, cheap); Phase 2 uses Opus 4.6 @ temp 0.1 reasoning=none (selected after 5-variant blind eval — see ROADMAP.md, section H2.2).

**Counting is deterministic in Python, never delegated to LLM.** Prompt engineer correction during PHASE1-INSTRUCTIONS.md review: the prompt does not ask the LLM to verify its output length, count its array entries, or enforce an `expected_count`. The validation happens in `src/hydration_aggregator.py` after each response; missing indices trigger retry. This generalizes Principle 1 ("deterministic before LLM") into prompt-design discipline — the LLM should never be asked to perform a task Python can perform deterministically, even as a self-check.

The chunking architecture scales to arbitrary N without code changes. Lauf evidence: 32-article topic chunks cleanly into [8,8,8,8], 15-article into [7,8], 5-article into [5]; all observed runs since integration have completed Phase 1 with zero retries.

### Pipeline shape

```
Production (unchanged):
  fetch_feeds → Curator → Editor → Researcher Plan → Python Web-Search →
    Researcher Assemble → Perspektiv → Writer → QA+Fix → Python Bias Card →
    Bias Language → Topic Package

Hydrated (Etappe 2, parallel):
  fetch_feeds → Curator → Editor →
    [NEW: Python Feed-Hydration (aiohttp fetch + trafilatura extract, respectful)]
    [NEW: Hydration Aggregator LLM → pre-dossier in Researcher-Assembler shape]
    Researcher Plan (seeded with pre-dossier coverage map) →
    Python Web-Search →
    Researcher Assemble (web-search-only input, unchanged prompt) →
    [NEW: Python merge pre-dossier + web-search dossier → combined dossier]
    Perspektiv → Writer → QA+Fix → Python Bias Card → Bias Language →
    Topic Package (same schema)
```

The downstream agents (Perspektiv, Writer, QA+Fix, Bias Language) see a richer dossier but operate on the same schema. Their prompts require no changes. The only prompt that changes is the Researcher Planner, which must know about the pre-dossier to plan gap-filling queries rather than redundant coverage.

### Files introduced by Etappe 2

- `src/pipeline_hydrated.py` — copy of `pipeline.py` with Feed-Hydration and Aggregator steps inserted. Independent file; no production-code modification.
- `src/hydration_aggregator.py` — chunked two-phase Aggregator implementation. Module-level constants at top: `AGGREGATOR_MODEL` (Phase 1), `PHASE2_MODEL`, `PHASE2_PROMPT_PATH`, `PHASE2_TEMPERATURE`.
- `agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md` — per-article extraction prompt. Each LLM call processes 5-10 articles and returns `article_analyses[]` only.
- `agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md` — cross-corpus reducer prompt. Single LLM call over all merged analyses produces `preliminary_divergences[]` + `coverage_gaps[]`.
- `agents/_archive/hydration_aggregator-AGENTS-2026-04-23.md` — deprecated monolithic prompt, archived 2026-04-23 after multiple green hydrated runs through S13.
- `agents/researcher_hydrated/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md` — a modified planner prompt that uses the pre-dossier as context. The Assembler prompt is unchanged (still processes web-search results only; pre-dossier merging happens in Python after assembly).
- `scripts/compare_pipelines.py` — T4 A/B orchestrator. Shared Curator+Editor run once; Production and Hydrated pipelines both run in parallel on identical assignments; deterministic metric extraction + markdown report.

Production runs continue to use the unchanged flow with `agents/researcher/PLAN-{SYSTEM,INSTRUCTIONS}.md` and `ASSEMBLE-{SYSTEM,INSTRUCTIONS}.md`. The Hydration pipeline is invoked via a separate test script (`scripts/test_hydration_pipeline.py`) that writes to `output/{date}/test_hydration/`, or via `scripts/compare_pipelines.py` for side-by-side evaluation.

## File Structure

```
independent-wire/
├── src/
│   ├── agent.py              # Agent class + AgentResult
│   ├── pipeline.py           # Production Pipeline class (sequential orchestration)
│   ├── pipeline_hydrated.py  # Hydrated Pipeline class (Etappe 2, with feed hydration)
│   ├── hydration_aggregator.py # Chunked two-phase Aggregator (Phase 1 parallel + Phase 2 reducer)
│   ├── models.py             # TopicPackage dataclass, AgentResult
│   ├── config.py             # Configuration loader
│   └── tools/
│       ├── registry.py       # ToolRegistry
│       ├── web_search.py     # web_search tool (Perplexity, Brave, DuckDuckGo)
│       └── file_ops.py       # read_file, write_file tools
├── agents/                   # Agent prompts (public, in repo)
│   ├── curator/{SYSTEM,INSTRUCTIONS}.md
│   ├── editor/{SYSTEM,INSTRUCTIONS}.md
│   ├── researcher/{PLAN,ASSEMBLE}-{SYSTEM,INSTRUCTIONS}.md
│   ├── researcher_hydrated/PLAN-{SYSTEM,INSTRUCTIONS}.md   # Etappe 2 planner variant
│   ├── perspektiv/{SYSTEM,INSTRUCTIONS}.md
│   ├── perspektiv_sync/{SYSTEM,INSTRUCTIONS}.md            # V2 delta-sync (Etappe 2)
│   ├── writer/{SYSTEM,INSTRUCTIONS}.md
│   ├── writer/FOLLOWUP.md                                  # addendum (loaded conditionally)
│   ├── qa_analyze/{SYSTEM,INSTRUCTIONS}.md
│   ├── bias_detector/{SYSTEM,INSTRUCTIONS}.md              # registered as `bias_language`
│   └── hydration_aggregator/
│       ├── PHASE1-{SYSTEM,INSTRUCTIONS}.md    # Per-article extraction (active)
│       └── PHASE2-{SYSTEM,INSTRUCTIONS}.md    # Cross-corpus reducer (active)
├── config/
│   ├── style-guide.md
│   ├── sources.json          # 72 RSS feeds, v0.3
│   └── profiles/
├── scripts/
│   ├── run.py                # Main pipeline entry point (--from/--to/--topic/--reuse)
│   ├── render.py             # Topic Package JSON → self-contained HTML
│   ├── publish.py            # Site generator (index.html, feed.xml, sitemap.xml)
│   ├── fetch_feeds.py        # RSS feed fetcher → raw/YYYY-MM-DD/feeds.json
│   ├── test_models.py        # Multi-model eval
│   ├── test_clustering.py    # Python clustering eval
│   ├── test_curator_twostage.py  # Two-Stage vs One-Pass eval
│   ├── test_eval_gap.py      # Editor/Perspektiv/QA/Bias eval
│   └── test_researcher_writer.py # Researcher/Writer eval
├── raw/                      # Raw feed data per date
│   └── YYYY-MM-DD/feeds.json
├── output/                   # Pipeline output + eval results
│   ├── YYYY-MM-DD/           # Debug output per pipeline step
│   └── eval/                 # Eval results (8 directories)
├── state/                    # Pipeline state files for crash recovery
│   └── run-YYYY-MM-DD-{hash}.json
├── schema/
│   └── topic-package-v1.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   ├── TASKS.md
│   ├── VISUALIZATIONS.md
│   ├── FEED-CATALOG.md
│   ├── archive/              # Completed tasks, WPs, briefings
│   └── handoffs/             # Session handoff files
├── .env.example
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── deploy-site.yml   # GitHub Pages deployment on push to site/
├── site/                     # Publication website (generated by publish.py)
│   ├── index.html            # Homepage with TP cards
│   ├── feed.xml              # RSS 2.0 feed
│   ├── CNAME                 # Custom domain (independentwire.org)
│   └── reports/              # Rendered TP HTML files
└── LICENSE (AGPL-3.0)
```
