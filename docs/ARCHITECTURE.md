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

A Pipeline is a sequence of agent calls with data flow, gating, and integrity checks.

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
    async def collect(self) -> list[dict]: ...
    async def curate(self, raw: list[dict]) -> list[dict]: ...
    async def editorial_conference(self, topics: list[dict]) -> list[dict]: ...
    async def gate(self, step_name: str, data: any) -> bool: ...
    async def produce_topic_package(self, assignment: dict) -> TopicPackage: ...
    async def verify(self, packages: list[TopicPackage]) -> list[TopicPackage]: ...
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
]
```

No numpy. No pandas. No langchain. No pytorch. Two core dependencies.

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

## File Structure

```
independent-wire/
├── src/
│   ├── agent.py              # Agent class + AgentResult
│   ├── pipeline.py           # Pipeline class
│   ├── tools/
│   │   ├── registry.py       # ToolRegistry
│   │   ├── web_search.py     # web_search tool
│   │   └── file_ops.py       # read_file, write_file tools
│   ├── telegram.py           # TelegramNotifier (optional)
│   ├── config.py             # Configuration loader
│   └── models.py             # TopicPackage dataclass, AgentResult
├── agents/                   # Agent prompts (public, in repo)
│   ├── collector/AGENTS.md
│   ├── kurator/AGENTS.md
│   ├── chefredaktion/AGENTS.md
│   ├── redakteur/AGENTS.md
│   ├── perspektiv/AGENTS.md
│   ├── bias_detektor/AGENTS.md
│   └── qa/AGENTS.md
├── config/
│   ├── style-guide.md
│   ├── sources.json
│   └── profiles/
├── scripts/
│   └── generate-visuals.py
├── schema/
│   └── topic-package-v1.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   └── VISUALIZATIONS.md
├── .env.example
├── pyproject.toml
└── LICENSE (AGPL-3.0)
```
