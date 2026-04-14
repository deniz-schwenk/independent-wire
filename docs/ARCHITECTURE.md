# Independent Wire — Framework Architecture

## Decision

Independent Wire uses its own minimal Python framework instead of OpenClaw, Hermes Agent, Nanobot, or Paperclip. The framework is purpose-built for a **deterministic multi-agent news pipeline** — not a general-purpose personal AI assistant.

### Why not an existing framework?

All evaluated frameworks (OpenClaw, Hermes, Nanobot, Paperclip) are **chat-oriented personal assistants**: a human sends a message, an agent responds, optionally using tools. Independent Wire needs something fundamentally different: a **pipeline** where specialized agents with different models, different tools, and different prompts process data sequentially, producing structured JSON output.

The three things we actually need from a framework — LLM API calls, tool execution, and Telegram notifications — are each ~50-100 lines of Python. The overhead of adapting a 3,500-line (Nanobot) or 300,000-line (OpenClaw) framework to do something it wasn't designed for exceeds the cost of building exactly what we need.

### Reference implementation

Nanobot's codebase (`agent/loop.py`, `agent/context.py`, `agent/tools/`) serves as architectural reference for how to structure LLM calls, tool registration, and context building. We don't import it — we learn from it.

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
        name: str,                    # e.g. "collector", "redakteur", "bias_detektor"
        model: str,                   # e.g. "claude-opus-4.6", "kimi-k2.5", "glm-5"
        prompt_path: str,             # path to AGENTS.md system prompt
        tools: list[str] = None,      # e.g. ["web_search"] — None = no tools
        memory_path: str = None,      # optional persistent memory file
        temperature: float = 0.3,     # model temperature
        max_tokens: int = 8192,       # max response tokens
        provider: str = "openrouter", # API provider
    ):
        ...

    async def run(
        self,
        message: str,                 # the task/instruction
        context: dict = None,         # additional context (previous agent output, etc.)
        output_schema: dict = None,   # optional JSON schema for structured output
    ) -> AgentResult:
        """
        Call the LLM with system prompt + message + context.
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
- **Structured output** via `output_schema`
- **Memory is a file path**, not a framework feature

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
    async def research(self, assignment: dict) -> dict: ...
    async def perspektiv(self, assignment: dict, research: dict) -> dict: ...
    async def write(self, assignment: dict, research: dict, perspectives: dict) -> dict: ...
    async def qa_fix(self, article: dict, dossier_sources: list, divergences: list) -> dict: ...
    async def build_bias_card(self, package: dict) -> dict: ...
    async def gate(self, step_name: str, data: any) -> bool: ...
    async def produce_topic_package(self, assignment: dict) -> TopicPackage: ...
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
]
```

No numpy. No pandas. No langchain. No pytorch. Three core dependencies.

---

## What This Architecture Enables (Without Rewriting)

| Future Need | How It's Handled |
|-------------|-----------------|
| **Memory** | Agent loads `memory_path` into context |
| **Parallelization** | `asyncio.gather()` — agents are already async |
| **New tools** | `registry.register(new_tool)` |
| **Docker deployment** | All config via env vars or config file |
| **Different providers** | Agent's `provider` field |
| **Structured output** | Agent's `output_schema` parameter |
| **Error recovery** | Pipeline resumes from last checkpoint |

## Current Model Assignments (April 2026)

All assignments validated through 90+ eval calls across 14 models. Three production models, reasoning=none everywhere.

| Agent | Model | Provider | Role |
|-------|-------|----------|------|
| Curator | google/gemini-3-flash-preview | OpenRouter | Cluster + score + summarize 1,400+ findings |
| Editor | anthropic/claude-opus-4.6 | OpenRouter | Prioritize topics, assign selection_reason |
| Researcher Plan | google/gemini-3-flash-preview | OpenRouter | Generate multilingual search queries |
| Researcher Assemble | google/gemini-3-flash-preview | OpenRouter | Build research dossier from search results |
| Perspektiv | anthropic/claude-opus-4.6 | OpenRouter | Stakeholder map, missing voices, framing divergences |
| Writer | anthropic/claude-opus-4.6 | OpenRouter | Write article with web_search tool access |
| QA+Fix | anthropic/claude-sonnet-4.6 | OpenRouter | Find errors, apply corrections, return corrected article |
| Bias Language | anthropic/claude-opus-4.6 | OpenRouter | Analyze language bias in finished article |

## File Structure

```
independent-wire/
├── src/
│   ├── agent.py              # Agent class + AgentResult
│   ├── pipeline.py           # Pipeline class (sequential orchestration)
│   ├── models.py             # TopicPackage dataclass, AgentResult
│   ├── config.py             # Configuration loader
│   └── tools/
│       ├── registry.py       # ToolRegistry
│       ├── web_search.py     # web_search tool (Perplexity, Brave, DuckDuckGo)
│       └── file_ops.py       # read_file, write_file tools
├── agents/                   # Agent prompts (public, in repo)
│   ├── curator/AGENTS.md, CLUSTER.md, SCORE.md
│   ├── editor/AGENTS.md
│   ├── researcher/PLAN.md, ASSEMBLE.md
│   ├── perspektiv/AGENTS.md
│   ├── writer/AGENTS.md
│   ├── qa_analyze/AGENTS.md
│   └── bias_detector/AGENTS.md
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
