# WP-PIPELINE — Claude Code Task

## Task
Build the Pipeline orchestration for Independent Wire: a Python class that calls Agents in a defined sequence, passes data between steps, persists state to disk, and continues on individual topic failures instead of crashing.

## Read first
1. `/Users/denizschwenk/Documents/independent-wire/repo-clone/docs/ARCHITECTURE.md` — target architecture, especially the Pipeline section
2. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/agent.py` — existing Agent code
3. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/models.py` — AgentResult
4. `/Users/denizschwenk/Documents/independent-wire/repo-clone/schema/topic-package-v1.json` — the output schema
5. `/Users/denizschwenk/Documents/nanobot-main/nanobot/agent/loop.py` — reference for sequential processing

## Working directory
`/Users/denizschwenk/Documents/independent-wire/repo-clone/`

## Context: What already exists
- `src/agent.py` — Agent class with async `run()`, tool loop, retry logic
- `src/models.py` — AgentResult dataclass
- `src/tools/` — ToolRegistry, web_search, web_fetch, file_ops
- `tests/test_agent.py`, `tests/test_tools.py` — existing tests (all green, 4 skipped)

## What to build

### 1. `src/models.py` — Extend with TopicPackage

Add the TopicPackage class to the existing `models.py`. **Do NOT delete AgentResult!**

```python
@dataclass
class TopicAssignment:
    """A topic assigned by Chefredaktion to be processed."""
    id: str                           # e.g. "tp-2026-03-30-001"
    title: str
    priority: int                     # 1-10
    topic_slug: str
    selection_reason: str
    raw_data: dict = field(default_factory=dict)  # data from Kurator

@dataclass
class TopicPackage:
    """The atomic output unit — a complete topic with all layers."""
    id: str
    metadata: dict
    sources: list[dict] = field(default_factory=list)
    perspectives: list[dict] = field(default_factory=list)
    divergences: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    article: dict = field(default_factory=dict)
    bias_analysis: dict = field(default_factory=dict)
    visualizations: list[dict] = field(default_factory=list)
    transparency: dict = field(default_factory=dict)
    status: str = "draft"             # draft/review/published/rejected/failed
    error: str | None = None          # error message if status=="failed"

    def to_dict(self) -> dict:
        """Serialize to dict matching topic-package-v1.json schema."""
        return {
            "id": self.id,
            "version": "1.0",
            "metadata": self.metadata,
            "sources": self.sources,
            "perspectives": self.perspectives,
            "divergences": self.divergences,
            "gaps": self.gaps,
            "article": self.article,
            "bias_analysis": self.bias_analysis,
            "visualizations": self.visualizations,
            "transparency": self.transparency,
        }

@dataclass
class PipelineState:
    """Checkpoint state for pipeline resumption."""
    run_id: str
    date: str
    current_step: str                 # which step we're at
    completed_steps: list[str] = field(default_factory=list)
    raw_findings: list[dict] = field(default_factory=list)
    curated_topics: list[dict] = field(default_factory=list)
    assignments: list[dict] = field(default_factory=list)
    packages: list[dict] = field(default_factory=list)  # serialized TopicPackages
    started_at: str = ""              # ISO timestamp
    error: str | None = None
```

### 2. `src/pipeline.py` — The Pipeline class

```python
class Pipeline:
    """Orchestrates agents in a defined sequence with data flow and gating."""

    STEPS = ["collect", "curate", "editorial_conference", "produce", "verify"]

    def __init__(
        self,
        name: str,                        # e.g. "daily_report"
        agents: dict[str, Agent],         # agents by role name
        output_dir: str = "./output",     # where Topic Packages are written
        state_dir: str = "./state",       # pipeline checkpoints
        max_topics: int = 7,              # max topics per run
        mode: str = "full",               # "full" / "quick"
        gate_handler: Callable | None = None,  # optional async gate callback
    ):
        ...

    async def run(self, date: str | None = None) -> list[TopicPackage]:
        """Execute the full pipeline. Returns completed TopicPackages."""
        ...
```

#### Pipeline.run() flow:

1. Generate `run_id`: `f"run-{date}-{uuid4().hex[:6]}"`
2. `date` defaults to today (`datetime.now().strftime("%Y-%m-%d")`)
3. Check for incomplete state file (`state_dir/run-{date}-*.json`)
   - If found: load state, resume from the last completed step
   - If not: create new PipelineState
4. Execute steps in order:
   - `collect()` → `raw_findings`
   - `curate(raw_findings)` → `curated_topics`
   - `editorial_conference(curated_topics)` → `assignments` (list[TopicAssignment])
   - Optional: `gate("editorial_conference", assignments)` — only in "full" mode
   - `produce(assignments)` → `packages` (list[TopicPackage])
   - `verify(packages)` → final `packages`
5. After each step: write state to disk
6. At the end: write TopicPackages as JSON to `output_dir`
7. Return: list[TopicPackage]

#### Step methods in detail:

**`collect()`**
- Calls `agents["collector"].run(message)` with an output_schema expecting a JSON array
- Message: "Scan current news sources and return a JSON array of findings. Each finding should have: title, summary, source_url, source_name, language, region."
- Returns `list[dict]`
- On agent failure: log error, return empty list

**`curate(raw_findings)`**
- Calls `agents["kurator"].run(message, context={"findings": raw_findings})`
- Message: "Review these raw findings. Select the most newsworthy topics. For each selected topic provide: title, topic_slug, relevance_score, summary, source_ids."
- Returns `list[dict]`, sorted by relevance_score
- Limited to `max_topics`

**`editorial_conference(curated_topics)`**
- Calls `agents["chefredaktion"].run(message, context={"topics": curated_topics})`
- Message: "Prioritize these topics for today's report. For each: assign priority (1-10), provide selection_reason, assign topic_id."
- Expects structured output (JSON array of TopicAssignment-compatible dicts)
- Returns `list[TopicAssignment]`

**`gate(step_name, data)`**
- Only called in `mode="full"`
- Calls `gate_handler(step_name, data)` if one was provided
- `gate_handler` is an async Callable returning `True` (proceed) or `False` (abort)
- If no `gate_handler`: always returns `True`
- If `False`: pipeline stops, state is saved, raises `PipelineGateRejected`
- This is the hook for WP-TELEGRAM (coming later)

**`produce(assignments)`**
- Iterates over all TopicAssignments **sequentially** (no asyncio.gather — that comes later)
- For each topic: call `_produce_single(assignment)`
- Catch errors in individual topics, set status="failed", continue with the rest
- Returns `list[TopicPackage]` (mix of completed and failed)

**`_produce_single(assignment)`** — the core method per topic:

1. **Perspektiv-Agent** (if present in `agents`):
   - `agents["perspektiv"].run(message, context=assignment_data)`
   - Message: "Research the spectrum of perspectives on this topic."
   - Output: perspectives array

2. **Redakteur**:
   - `agents["redakteur"].run(message, context={assignment + perspectives})`
   - Message: "Write a multi-perspective article on this topic."
   - Output: article dict (headline, body, summary)

3. **Bias-Detektor** (if present):
   - `agents["bias_detektor"].run(message, context={article + sources})`
   - Message: "Analyze this article for bias across all five dimensions."
   - Output: bias_analysis dict

4. **QA/Faktencheck** (if present):
   - `agents["qa"].run(message, context={article + sources})`
   - Message: "Verify all factual claims in this article."
   - Output: updated sources with verification_status

5. Assemble and return TopicPackage

**Important:** Every sub-agent is optional. If `agents.get("perspektiv")` is None, that step is skipped. Only `redakteur` is required in `_produce_single()`. This enables incremental testing: first just Collector+Kurator+Chefredaktion+Redakteur, then add perspektiv and bias later.

**`verify(packages)`**
- Count: `total = len(packages)`
- Count: `completed = len([p for p in packages if p.status != "failed"])`
- Count: `failed = len([p for p in packages if p.status == "failed"])`
- Assert: `completed + failed == total` — if not, log ERROR
- Log summary: "Verify: {completed}/{total} topics completed, {failed} failed"
- Returns packages unchanged (verify is an integrity check, not a correction)

#### State persistence

After each step:
```python
async def _save_state(self):
    """Save current pipeline state to disk."""
    path = Path(self.state_dir) / f"{self.state.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(self.state)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
```

On startup:
```python
def _load_incomplete_state(self, date: str) -> PipelineState | None:
    """Check for incomplete runs from the same date."""
    state_path = Path(self.state_dir)
    if not state_path.exists():
        return None
    for f in state_path.glob(f"run-{date}-*.json"):
        data = json.loads(f.read_text())
        state = PipelineState(**data)
        if state.current_step != "done":
            return state
    return None
```

#### Writing output

At the end of `run()`:
```python
async def _write_output(self, packages: list[TopicPackage]):
    """Write completed TopicPackages as JSON to output_dir."""
    out = Path(self.output_dir) / self.state.date
    out.mkdir(parents=True, exist_ok=True)
    for pkg in packages:
        if pkg.status == "failed":
            continue
        path = out / f"{pkg.id}.json"
        path.write_text(
            json.dumps(pkg.to_dict(), indent=2, ensure_ascii=False)
        )
    # Also write a run summary
    summary_path = out / f"{self.state.run_id}-summary.json"
    summary = {
        "run_id": self.state.run_id,
        "date": self.state.date,
        "total_topics": len(packages),
        "completed": len([p for p in packages if p.status != "failed"]),
        "failed": len([p for p in packages if p.status == "failed"]),
        "packages": [p.id for p in packages],
    }
    summary_path.write_text(json.dumps(summary, indent=2))
```

#### Exceptions

```python
class PipelineError(Exception):
    """Base exception for pipeline errors."""

class PipelineGateRejected(PipelineError):
    """Raised when a gate handler rejects the pipeline."""

class PipelineStepError(PipelineError):
    """Raised when a critical pipeline step fails (collect, curate, etc.)."""
```

### 3. `tests/test_pipeline.py` — Tests

#### Unit tests (no API key needed):

**test_pipeline_state_persistence**
- Create Pipeline with dummy agents (never called)
- Set `state` manually to a known state
- Call `_save_state()`
- Load state from file and compare
- Cleanup: tmp_path

**test_pipeline_load_incomplete_state**
- Write an incomplete state file to tmp_path
- Call `_load_incomplete_state(date)`
- Assert: state is loaded with correct `current_step`

**test_pipeline_load_no_incomplete**
- Empty state_dir
- `_load_incomplete_state()` returns None

**test_topic_package_to_dict**
- Create TopicPackage with known data
- Call `to_dict()`
- Assert: contains all required fields from the schema
- Assert: `version` == "1.0"

**test_verify_counts**
- Create 3 TopicPackages: 2 with status="review", 1 with status="failed"
- Call `verify()`
- Assert: return has 3 packages
- Assert: logging contains "2/3 topics completed, 1 failed"

**test_gate_handler_called**
- Create Pipeline with a mock gate_handler
- Call `gate("test_step", {"data": "test"})`
- Assert: gate_handler was called with the correct arguments

**test_gate_rejected_raises**
- gate_handler returns `False`
- Assert: `PipelineGateRejected` is raised

**test_gate_skipped_in_quick_mode**
- Pipeline with `mode="quick"`
- Gate is not called, always returns True

**test_produce_single_error_isolation**
- Mock agent that raises an exception
- `_produce_single()` catches the error
- Returns TopicPackage with `status="failed"` and `error` set

#### Integration test (requires OPENROUTER_API_KEY):

**test_pipeline_collect_curate** (marked with `@skip_no_key`)
- Create real Agents with cheap models (`openai/gpt-4o-mini`)
- Create simple prompt files in tmp_path:
  - collector prompt: "You are a news collector. Return findings as JSON array."
  - kurator prompt: "You are a news curator. Select the most relevant topics."
- Create Pipeline with only collector and kurator
- Call `collect()`, check that result is a non-empty list
- Call `curate(raw)`, check that result is a list
- This tests the real data flow Collector→Kurator without running the full pipeline

**IMPORTANT:** This test should be cheap. Use `openai/gpt-4o-mini` and keep prompts short. The test proves data flow works, not that the agent prompts are good (that comes in WP-AGENTS).

## Technical rules
- Python 3.11+, type hints everywhere
- `async def` for all methods that do I/O
- Logging via `logging.getLogger(__name__)`, no print()
- No global variables, no singletons
- Pipeline receives Agents as constructor argument — it does not create Agents itself
- State files are JSON, human-readable, in `state_dir`
- Output files are JSON, in `output_dir/{date}/`
- Existing tests (`test_agent.py`, `test_tools.py`) MUST NOT break
- Project imports: `from src.agent import Agent`, `from src.models import ...`

## Architecture principles (from ARCHITECTURE.md)

These are NON-NEGOTIABLE:

1. **Pipeline steps are deterministic Python methods** — no LLM decides "what to do next" (Lesson Learned #11)
2. **Each agent receives only the data it needs** via message+context — no shared filesystem (LL #12)
3. **State is saved after each step** — on crash, resume from last checkpoint (LL #13, #25)
4. **Counting is mandatory**: verify checks completed + failed == total (LL #14)
5. **Signal/control flow comes from Python, not from the agent** (LL #15)
6. **Individual topic failures don't break the entire pipeline** — error isolation

## What NOT to build
- No real agent prompts (AGENTS.md files) — comes in WP-AGENTS
- No Telegram integration — comes in WP-TELEGRAM (gate_handler is the hook)
- No parallelization — produce runs sequentially, asyncio.gather comes later
- No CLI / no run.py — comes in WP-INTEGRATION
- No memory logic — comes in WP-MEMORY
- No visualizations — those come via generate-visuals.py (already exists)

## Acceptance criteria
1. `python -m pytest tests/ -v` passes completely (all tests including existing ones)
2. Pipeline can execute steps sequentially with data flow between steps
3. State is written as JSON to disk after each step
4. Incomplete state is detected and loaded on next start
5. Individual topic failures produce `status="failed"` packages, pipeline continues
6. Gate handler hook works (called/rejected/skipped in quick mode)
7. TopicPackages are written as JSON to output_dir
8. verify() counts correctly and logs summary
9. Code is clean, typed, and documented

## After building
```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
source .venv/bin/activate && source .env && python -m pytest tests/ -v
git add -A
git commit -m "WP-PIPELINE: Pipeline orchestration with state persistence and error isolation

- Pipeline class: sequential agent orchestration with data flow
- TopicPackage and PipelineState dataclasses
- State persistence: JSON checkpoints after each step
- Resume from incomplete runs on restart
- Per-topic error isolation: failed topics don't break the pipeline
- Gate handler hooks for future Telegram integration
- Verify sweep with counting integrity check
- Output: TopicPackage JSON + run summary
- Tests: unit tests for state/gate/verify + integration test"
git push origin main
```
