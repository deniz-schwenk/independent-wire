"""Silent topic death — TASK-SILENT-TOPIC-DEATH-FIX (O1 + O2 + O3 + O5).

2026-10-15 lost tp-001 without a trace in the text log: DeepSeek answered the
planner's primary call with HTTP 200 and JSON WITHOUT ``choices``; the SDK
builds such a response unvalidated, ``response.choices[0]`` raised TypeError
below every fallback ladder (they catch AgentError only), and the runner
logged one reason-less WARNING (scratch/audit/topic0-failure/REPORT.md).

Pinned here, offline (httpx.MockTransport behind the real AsyncOpenAI client,
no network, $0):

* O3 — a 200 with choices missing / null / empty is an AgentError at BOTH
  read sites (the tool loop and the structured-output retry), and every real
  production ladder from ``create_agents_hydrated()`` then engages its next
  rung — the planner's rung 2 serves the plan.
* O5 — the rejected body is persisted (also a non-JSON body), its path is
  logged, and the store is capped per day and pruned by day.
* O1 — the runner's topic-failure path logs ERROR with stage name, reason
  and traceback, and writes a per-stage failed row next to the topic row.
* O2 — a lost topic fires a publish-time ERROR gate, and the run summary
  counts it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI

from src.agent import (
    REJECTED_KEEP_DAYS,
    REJECTED_MAX_PER_DAY,
    Agent,
    AgentError,
    AgentMalformedResponseError,
    persist_rejected_response,
)
from src.bus import RunBus, RunBusReadOnly, TopicBus, WriterArticle
from src.runner.runner import (
    PipelineRunner,
    fire_lost_topic_gate,
    lost_topic_rows,
)
from src.stage import run_stage_def, topic_stage_def

REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- fixtures

# The 2026-10-15 shape: keep-alive newlines, then a JSON object that is not a
# chat completion. Which JSON DeepSeek actually sent was never persisted; an
# error object is the representative case (the report's §A probe).
BODY_ERROR_OBJECT = b"\n\n\n" + json.dumps(
    {"error": {"message": "server closed the request", "type": "timeout"}}
).encode()
BODY_CHOICES_NULL = json.dumps(
    {"id": "resp-null", "object": "chat.completion", "created": 0,
     "model": "m", "choices": None}
).encode()
BODY_CHOICES_EMPTY = json.dumps(
    {"id": "resp-empty", "object": "chat.completion", "created": 0,
     "model": "m", "choices": []}
).encode()
BODY_NOT_JSON = b"\n\n\n<html>gateway</html>"

CHOICELESS = {
    "choices_missing": BODY_ERROR_OBJECT,
    "choices_null": BODY_CHOICES_NULL,
    "choices_empty": BODY_CHOICES_EMPTY,
}


def _completion(content: str, model: str = "served-model") -> bytes:
    return json.dumps({
        "id": "resp-ok", "object": "chat.completion", "created": 0,
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }).encode()


class _Transport:
    """Serves a fixed sequence of bodies (the last one repeats) and counts
    requests — one per agent, so a test can see which rungs were called."""

    def __init__(self, *bodies: bytes) -> None:
        self.bodies = list(bodies)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = self.bodies[min(self.calls, len(self.bodies) - 1)]
        self.calls += 1
        return httpx.Response(
            200, content=body, headers={"content-type": "application/json"}
        )


def _wire(agent: Agent, transport: _Transport) -> _Transport:
    agent._client = AsyncOpenAI(
        api_key="test-key",
        base_url=agent.base_url,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        max_retries=0,
    )
    return transport


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch, tmp_path):
    # Production agents need key NAMES present to construct; no request ever
    # leaves the MockTransport. Rejected bodies go to a tmp store.
    for key in ("OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "OLLAMA_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.setenv("IW_REJECTED_RESPONSES_DIR", str(tmp_path / "rejected"))
    monkeypatch.setattr("src.agent.BASE_DELAY", 0)


def _plain_agent(**kw) -> Agent:
    return Agent(
        name="probe_agent",
        model="probe-model",
        system_prompt_path=str(REPO / "agents/researcher/PLAN-SYSTEM.md"),
        instructions_path=str(REPO / "agents/researcher/PLAN-INSTRUCTIONS.md"),
        temperature=None,
        **kw,
    )


def _rejected_files(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "rejected").rglob("*.json"))


# ------------------------------------------------------------- O3 at agent


@pytest.mark.parametrize("shape", sorted(CHOICELESS))
def test_choiceless_200_is_an_agent_error_at_the_tool_loop_site(shape, tmp_path, caplog):
    agent = _plain_agent()
    t = _wire(agent, _Transport(CHOICELESS[shape]))
    with caplog.at_level(logging.ERROR, logger="src.agent"):
        with pytest.raises(AgentMalformedResponseError) as ei:
            asyncio.run(agent.run("plan this"))
    assert isinstance(ei.value, AgentError)          # every ladder catches this
    assert t.calls == 1                              # no same-channel retry
    assert "without usable choices" in str(ei.value)
    assert any("fallback ladder engages" in r.getMessage() for r in caplog.records)


def test_choiceless_200_is_an_agent_error_at_the_structured_retry_site():
    """Second read site: the first answer is not JSON, so the agent asks again
    (``_parse_or_retry_structured``) — and THAT answer has no choices."""
    agent = _plain_agent(output_schema={"type": "object"},
                         structured_output_mode="json_object")
    t = _wire(agent, _Transport(_completion("this is not json"), BODY_ERROR_OBJECT))
    with pytest.raises(AgentMalformedResponseError):
        asyncio.run(agent.run("plan this"))
    assert t.calls == 2


def test_a_normal_completion_is_untouched():
    agent = _plain_agent()
    _wire(agent, _Transport(_completion('{"ok": true}')))
    result = asyncio.run(agent.run("plan this"))
    assert result.content == '{"ok": true}'


# --------------------------------------------- O3 through the real ladders


def _production_agents():
    from scripts.run import create_agents_hydrated

    return create_agents_hydrated()


def _first_and_later_rungs(wrapper) -> tuple[Agent, list[Agent]]:
    first = getattr(wrapper, "primary", None) or getattr(wrapper, "draft")
    later = [
        v for k, v in vars(wrapper).items()
        if isinstance(v, Agent) and v is not first and k != "verify"
    ]
    return first, later


LADDERS = [
    "curator_topic_discovery", "editor", "researcher_assemble",
    "resolve_actor_aliases", "perspective", "writer", "qa_analyze",
    "consolidator", "researcher_hydrated_plan",
    "hydration_aggregator_phase1", "hydration_aggregator_phase2",
]


def test_every_production_ladder_is_covered_here():
    agents = _production_agents()
    wrapped = {k for k, v in agents.items()
               if not isinstance(v, Agent)
               and isinstance(getattr(v, "primary", None) or getattr(v, "draft", None), Agent)}
    assert wrapped == set(LADDERS)


@pytest.mark.parametrize("stage", LADDERS)
def test_a_choiceless_primary_engages_the_next_rung_on_every_production_ladder(stage):
    """The forced-failure pattern on the REAL wrappers: the first rung gets
    the 10-15 body, every later rung gets it too. Before the fix the first
    rung raised TypeError and no later rung was ever called; now each ladder
    descends, and what finally surfaces (if anything) is an AgentError."""
    wrapper = _production_agents()[stage]
    first, later = _first_and_later_rungs(wrapper)
    first_t = _wire(first, _Transport(BODY_ERROR_OBJECT))
    later_ts = [_wire(a, _Transport(BODY_ERROR_OBJECT)) for a in later]
    try:
        asyncio.run(wrapper.run("probe message", context={}))
    except AgentError:
        pass                                       # loud terminal failure is fine
    assert first_t.calls >= 1
    assert sum(t.calls for t in later_ts) >= 1, f"{stage}: no later rung was tried"


def test_planner_rung_two_serves_after_a_choiceless_primary(caplog):
    """The 2026-10-15 case end to end: channel C sends the choice-less body,
    rung 2 (dated OpenRouter id) returns a well-formed plan and serves it."""
    ladder = _production_agents()["researcher_hydrated_plan"]
    plan = json.dumps([{"query": "Iran US trade threats", "language": "en"}])
    c = _wire(ladder.primary, _Transport(BODY_ERROR_OBJECT))
    a = _wire(ladder.fallback_dated, _Transport(_completion(plan)))
    i = _wire(ladder.fallback_incumbent, _Transport(_completion(plan)))
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(ladder.run("probe message", context={}))
    assert (c.calls, a.calls, i.calls) == (1, 1, 0)
    assert ladder.last_rung == "fallback_dated_openrouter"
    assert result.structured
    assert any("FALLBACK rung 2" in r.getMessage()
               and "without usable choices" in r.getMessage()
               for r in caplog.records)


# ------------------------------------------------------------------- O5


def test_choiceless_body_is_persisted_and_its_path_logged(tmp_path, caplog):
    agent = _plain_agent()
    _wire(agent, _Transport(BODY_ERROR_OBJECT))
    with caplog.at_level(logging.ERROR, logger="src.agent"):
        with pytest.raises(AgentMalformedResponseError) as ei:
            asyncio.run(agent.run("plan this"))
    files = _rejected_files(tmp_path)
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["agent"] == "probe_agent"
    assert "choices missing or null" in saved["reason"]
    assert "server closed the request" in saved["body"]   # the provider's own words
    assert str(files[0]) in str(ei.value)
    assert any(str(files[0]) in r.getMessage() for r in caplog.records)


def test_non_json_body_is_persisted_on_every_retry(tmp_path, caplog):
    agent = _plain_agent()
    _wire(agent, _Transport(BODY_NOT_JSON))
    with caplog.at_level(logging.WARNING, logger="src.agent"):
        with pytest.raises(AgentError):
            asyncio.run(agent.run("plan this"))
    files = _rejected_files(tmp_path)
    assert len(files) == 4                                 # 1 + MAX_RETRIES
    assert "<html>gateway</html>" in json.loads(files[0].read_text())["body"]
    assert any("raw body →" in r.getMessage() for r in caplog.records)


def test_rejected_store_is_capped_per_day_and_pruned_by_day(tmp_path, monkeypatch):
    root = tmp_path / "rejected"
    for n in range(REJECTED_KEEP_DAYS + 3):
        (root / f"2026-01-{n + 1:02d}").mkdir(parents=True)
    paths = [
        persist_rejected_response(agent_name="a", model="m", provider="p",
                                  reason="r", body={"n": n})
        for n in range(REJECTED_MAX_PER_DAY + 2)
    ]
    assert sum(p is not None for p in paths) == REJECTED_MAX_PER_DAY
    assert paths[-1] is None                               # the cap holds
    day_dirs = [d for d in root.iterdir() if d.is_dir()]
    assert len(day_dirs) == REJECTED_KEEP_DAYS             # oldest pruned
    assert not (root / "2026-01-01").exists()


def test_persisting_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("IW_REJECTED_RESPONSES_DIR", str(blocker))
    assert persist_rejected_response(agent_name="a", model="m", provider="p",
                                     reason="r", body="b") is None


# ------------------------------------------------------- O1 + O2 at runner


@run_stage_def(reads=(), writes=("run_id", "run_date"))
async def _init(run_bus: RunBus) -> RunBus:
    run_bus.run_id = "run-2026-10-15-test"
    run_bus.run_date = "2026-10-15"
    return run_bus


@run_stage_def(reads=("run_id",), writes=("editor_assignments", "selected_assignments"))
async def _three_topics(run_bus: RunBus) -> RunBus:
    rows = [
        {"id": f"tp-2026-10-15-00{i}", "topic_slug": f"slug-{i}", "title": f"T{i}",
         "priority": 5, "selection_reason": "x", "raw_data": {}}
        for i in (1, 2, 3)
    ]
    run_bus.editor_assignments = rows
    run_bus.selected_assignments = list(rows)
    return run_bus


@topic_stage_def(reads=("editor_selected_topic",), writes=("writer_article",))
async def ResearcherHydratedPlanStage(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus:
    if topic_bus.editor_selected_topic.id.endswith("001"):
        raise AgentMalformedResponseError(
            "Agent 'researcher_hydrated_plan': HTTP 200 without usable choices"
        )
    return topic_bus.model_copy(update={
        "writer_article": WriterArticle(headline="h", summary="s", body="b"),
    })


def _two_of_three(tmp_path: Path) -> tuple[PipelineRunner, RunBus]:
    runner = PipelineRunner(
        run_stages=[_init, _three_topics],
        topic_stages=[ResearcherHydratedPlanStage],
        output_dir=tmp_path,
    )
    return runner, asyncio.run(runner.run())


def test_runner_failure_line_names_stage_reason_and_traceback(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="src.runner.runner"):
        runner, _ = _two_of_three(tmp_path)
    assert runner._topic_status == ["failed", "success", "success"]
    fail = [r for r in caplog.records if "FAILED at stage" in r.getMessage()]
    assert len(fail) == 1 and fail[0].levelno == logging.ERROR
    msg = fail[0].getMessage()
    assert "topic 0 (slug-1)" in msg
    assert "ResearcherHydratedPlanStage" in msg
    assert "AgentMalformedResponseError" in msg and "without usable choices" in msg
    assert "Traceback (most recent call last)" in msg
    assert not any("failed at stage;" in r.getMessage() for r in caplog.records)


def test_runner_writes_a_per_stage_row_and_a_topic_row(tmp_path):
    _, rb = _two_of_three(tmp_path)
    log = Path(tmp_path, "2026-10-15", "_state", "run-2026-10-15-test",
               "run_stage_log.jsonl")
    disk = [json.loads(line) for line in log.read_text().splitlines()]
    for rows in (disk, rb.run_stage_log):                 # jsonl == Bus slot
        failed = [r for r in rows if r["status"] == "failed"]
        assert [r["stage"] for r in failed] == ["ResearcherHydratedPlanStage", "topic-0"]
        stage_row, topic_row = failed
        assert stage_row["topic_index"] == 0
        assert stage_row["error_type"] == "AgentMalformedResponseError"
        assert topic_row["failed_stage"] == "ResearcherHydratedPlanStage"
        assert "Traceback" in topic_row["traceback"]


def test_lost_topic_gate_fires_at_publish_time(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="src.runner.runner"):
        _, rb = _two_of_three(tmp_path)
    gate = [r for r in caplog.records if "LOST TOPIC GATE" in r.getMessage()]
    assert len(gate) == 1 and "1 topic(s)" in gate[0].getMessage()
    lost = [r.getMessage() for r in caplog.records if "  LOST: topic 0" in r.getMessage()]
    assert lost and "ResearcherHydratedPlanStage" in lost[0]
    # the two completed topics still ship — publishing policy unchanged
    assert sorted(p.name for p in Path(tmp_path, "2026-10-15").glob("tp-*.json")) == [
        "tp-2026-10-15-002.json", "tp-2026-10-15-003.json",
    ]
    assert len(lost_topic_rows(rb)) == 1


def test_no_lost_topic_no_gate(caplog):
    with caplog.at_level(logging.ERROR, logger="src.runner.runner"):
        assert fire_lost_topic_gate(RunBus()) == []
    assert not caplog.records


def test_run_summary_counts_lost_topics(tmp_path, monkeypatch, caplog):
    """run.py's own summary block, fed a real 2-of-3 RunBus (the runner and
    the stage-list build are stubbed; nothing else in main() runs)."""
    import argparse

    import scripts.run as run_mod

    _, rb = _two_of_three(tmp_path)

    class _Runner:
        def __init__(self, *a, **k):
            pass

        async def run(self):
            return rb

    args = argparse.Namespace(
        help_stages=False, fetch=False, hydrated=True, max_produce=3,
        from_step=None, to_step=None, reuse=None, force=False, topic=None,
        publish=False,
    )
    monkeypatch.setattr(run_mod, "parse_args", lambda: args)
    monkeypatch.setattr(run_mod, "setup_logging", lambda: None)
    monkeypatch.setattr(run_mod, "create_agents_hydrated", lambda: {})
    monkeypatch.setattr(run_mod, "build_hydrated_stages", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(run_mod, "PipelineRunner", _Runner)
    with caplog.at_level(logging.INFO):
        asyncio.run(run_mod.main())
    msgs = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert (logging.INFO, "  Topics: 2 completed, 0 skipped, 1 failed") in msgs
    errors = [m for lvl, m in msgs if lvl == logging.ERROR]
    assert "  Lost topics: 1 — this run is NOT clean" in errors
    assert any("topic 0 (slug-1) at ResearcherHydratedPlanStage: "
               "AgentMalformedResponseError" in m for m in errors)
