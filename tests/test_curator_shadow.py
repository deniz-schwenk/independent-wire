"""Tests for the Curator shadow harness + the src/agent.py extension.

Covers four contract pieces from TASK-CURATOR-SHADOW-DEEPSEEK.md §Tests:

1. API-key loading — happy path + missing-file + empty-file errors
2. Agent extension backwards compatibility — existing OpenRouter path
   unchanged (base_url, api_key resolution, extra_body for reasoning)
3. Metric-function reuse — curator_shadow and curator_monitor import
   the same callable from src.curator_metrics (no code duplication)
4. Variant-B config — extra_body has ``thinking.type == "disabled"``,
   not ``"enabled"``

No live API calls. Agent constructions use placeholder api_key strings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent  # noqa: E402
from src.curator_metrics import compute_metrics as shared_compute_metrics  # noqa: E402


@pytest.fixture
def prompt_file(tmp_path: Path) -> str:
    p = tmp_path / "AGENTS.md"
    p.write_text("You are a test assistant.", encoding="utf-8")
    return str(p)


# ─────────────────────────────────────────────────────────────────────────
# §1. API-key loading
# ─────────────────────────────────────────────────────────────────────────


def test_load_deepseek_api_key_strips_whitespace(tmp_path: Path) -> None:
    """Happy path: file with whitespace around the key returns the
    stripped key."""
    from scripts.curator_shadow import load_deepseek_api_key

    key_path = tmp_path / "deepseek_api.txt"
    key_path.write_text("  sk-fakekey-12345\n  ", encoding="utf-8")
    assert load_deepseek_api_key(key_path) == "sk-fakekey-12345"


def test_load_deepseek_api_key_missing_file(tmp_path: Path) -> None:
    """Missing file: clear FileNotFoundError with the path in the message."""
    from scripts.curator_shadow import load_deepseek_api_key

    missing = tmp_path / "does-not-exist.txt"
    with pytest.raises(FileNotFoundError, match="DeepSeek API key file not found"):
        load_deepseek_api_key(missing)


def test_load_deepseek_api_key_empty_file(tmp_path: Path) -> None:
    """Empty file (or whitespace-only): ValueError, not a silent
    empty-string return."""
    from scripts.curator_shadow import load_deepseek_api_key

    p = tmp_path / "empty.txt"
    p.write_text("   \n\t  ", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_deepseek_api_key(p)


# ─────────────────────────────────────────────────────────────────────────
# §2. Agent extension backwards compatibility
# ─────────────────────────────────────────────────────────────────────────


def test_agent_default_routes_to_openrouter(prompt_file: str) -> None:
    """Construct Agent without base_url / api_key_file → uses OpenRouter
    base URL and the explicit api_key kwarg. Existing prod agents that
    don't touch the new knobs are unaffected."""
    agent = Agent(
        name="default",
        model="google/gemini-3-flash-preview",
        system_prompt_path=prompt_file,
        instructions_path=prompt_file,
        api_key="fake-openrouter-key",
    )
    assert agent.base_url == "https://openrouter.ai/api/v1"
    assert agent.provider == "openrouter"
    # OpenAI client constructed with the OpenRouter base
    assert str(agent._client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"
    # api_key resolution: explicit kwarg won
    assert agent._client.api_key == "fake-openrouter-key"


def test_agent_api_key_file_resolution(prompt_file: str, tmp_path: Path) -> None:
    """api_key_file is read at construction and trimmed; explicit api_key
    still wins over api_key_file."""
    key_path = tmp_path / "key.txt"
    key_path.write_text("  sk-from-file  \n", encoding="utf-8")

    agent = Agent(
        name="from-file",
        model="deepseek-v4-flash",
        system_prompt_path=prompt_file,
        instructions_path=prompt_file,
        provider="deepseek",
        api_key_file=str(key_path),
    )
    assert agent._client.api_key == "sk-from-file"
    assert agent.base_url == "https://api.deepseek.com"

    # Explicit api_key still beats api_key_file
    agent2 = Agent(
        name="explicit-wins",
        model="deepseek-v4-flash",
        system_prompt_path=prompt_file,
        instructions_path=prompt_file,
        provider="deepseek",
        api_key="explicit-key",
        api_key_file=str(key_path),
    )
    assert agent2._client.api_key == "explicit-key"


def test_agent_api_key_file_missing_raises(prompt_file: str, tmp_path: Path) -> None:
    """Missing api_key_file → ValueError with the path in the message."""
    with pytest.raises(ValueError, match="api_key_file not found"):
        Agent(
            name="missing-file",
            model="deepseek-v4-flash",
            system_prompt_path=prompt_file,
            instructions_path=prompt_file,
            provider="deepseek",
            api_key_file=str(tmp_path / "nope.txt"),
        )


def test_agent_provider_deepseek_skips_openrouter_reasoning(prompt_file: str) -> None:
    """For provider="deepseek", the agent must NOT auto-inject
    OpenRouter's ``reasoning: {"effort": "none"}`` extra_body. Provider-
    specific knobs come exclusively via extra_body_override."""
    agent = Agent(
        name="ds",
        model="deepseek-v4-flash",
        system_prompt_path=prompt_file,
        instructions_path=prompt_file,
        provider="deepseek",
        api_key="fake-ds-key",
        extra_body_override={
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        },
    )
    # Re-construct the body the same way _call_with_retry does, so we
    # avoid touching the network. The first two branches at lines
    # ~322-338 are gated on provider==openrouter / ollama; for
    # "deepseek" neither fires.
    extra_body: dict = {}
    if agent.reasoning is None and agent.provider == "openrouter":
        extra_body["reasoning"] = {"effort": "none"}
    extra_body.update(agent._extra_body_override)

    assert "reasoning" not in extra_body, (
        "provider=deepseek must not auto-inject OpenRouter reasoning block"
    )
    assert extra_body["thinking"] == {"type": "enabled"}
    assert extra_body["reasoning_effort"] == "high"


# ─────────────────────────────────────────────────────────────────────────
# §3. Metric-function reuse — same callable across scripts
# ─────────────────────────────────────────────────────────────────────────


def test_metric_function_shared_across_monitor_and_shadow() -> None:
    """curator_monitor and curator_shadow both import compute_metrics
    from src.curator_metrics — exact same callable, no shadow copy."""
    from scripts import curator_monitor, curator_shadow
    from src import curator_metrics

    assert curator_monitor.compute_metrics is curator_metrics.compute_metrics
    assert curator_shadow.compute_metrics is curator_metrics.compute_metrics
    assert shared_compute_metrics is curator_metrics.compute_metrics


def test_metric_function_type_stable_against_minimal_state() -> None:
    """The shared compute_metrics returns the documented metric keys for
    a minimal hand-crafted state — guards against silent contract drift
    when one script monkey-patches behaviour."""
    state = {
        "curator_findings": [
            {"title": "Iran peace talks resume in Geneva"},
            {"title": "Crops fail in Spain heatwave"},
        ],
        "curator_topics_unsliced": [
            {
                "title": "US-Iran nuclear negotiations",
                "summary": "Negotiations between Tehran and Washington over uranium enrichment.",
                "source_ids": ["finding-0"],
            },
        ],
    }
    m = shared_compute_metrics(state)
    for key in (
        "n_findings_total",
        "n_clusters",
        "top_cluster_size",
        "top_cluster_off_topic_pct",
        "orphan_count",
        "orphan_rate",
        "on_topic_regex_tokens",
        "cluster_size_p90",
    ):
        assert key in m
    assert m["n_findings_total"] == 2
    assert m["n_clusters"] == 1
    assert m["top_cluster_size"] == 1
    assert m["orphan_count"] == 1


# ─────────────────────────────────────────────────────────────────────────
# §4. Variant-B config — non-thinking, no reasoning_effort
# ─────────────────────────────────────────────────────────────────────────


def test_variant_b_config_disables_thinking_no_reasoning_effort() -> None:
    """Variant B mirrors the audit's dskflash-t-05-r-none. Its
    extra_body must set thinking.type=disabled and must NOT include
    reasoning_effort. response_format=json_object is also expected (the
    JSON-mode hint DeepSeek-direct documents support for)."""
    from scripts.curator_shadow import VARIANTS

    cfg = VARIANTS["B"]
    assert cfg["temperature"] == 0.5
    assert cfg["max_tokens"] == 32000
    eb = cfg["extra_body"]
    assert eb["thinking"]["type"] == "disabled"
    assert "reasoning_effort" not in eb
    assert eb["response_format"] == {"type": "json_object"}


def test_variant_a_config_enables_thinking_high_reasoning() -> None:
    """Variant A — symmetric assertion on the thinking-enabled config."""
    from scripts.curator_shadow import VARIANTS

    cfg = VARIANTS["A"]
    assert cfg["temperature"] == 0.7
    assert cfg["max_tokens"] == 64000
    eb = cfg["extra_body"]
    assert eb["thinking"]["type"] == "enabled"
    assert eb["reasoning_effort"] == "high"
    assert eb["response_format"] == {"type": "json_object"}


# ─────────────────────────────────────────────────────────────────────────
# Day-3 decision short-circuit when <3 days available
# ─────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────
# Streaming SSE accumulator — mock httpx to assert chunk parsing
# ─────────────────────────────────────────────────────────────────────────


class _FakeStreamResponse:
    """Pretend ``httpx.Response`` returned by ``client.stream(...)``.
    Exposes ``status_code`` and ``aiter_lines`` (async iterator) so the
    streaming consumer can walk SSE events."""

    def __init__(self, status_code: int, lines: list[str], request=None) -> None:
        self.status_code = status_code
        self._lines = lines
        self.request = request

    async def aread(self) -> bytes:
        return b"\n".join(line.encode("utf-8") for line in self._lines)

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeAsyncClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, **kwargs):  # noqa: ARG002
        return self._response


@pytest.mark.asyncio
async def test_stream_chat_accumulates_content_and_reasoning(monkeypatch) -> None:
    """``_stream_chat`` parses SSE ``data: {...}`` lines and concatenates
    delta.content + delta.reasoning_content across chunks. Usage tokens
    are picked up from the trailing event."""
    from scripts import curator_shadow

    lines = [
        'data: {"id":"r-1","choices":[{"delta":{"reasoning_content":"think A"}}]}',
        'data: {"id":"r-1","choices":[{"delta":{"reasoning_content":" think B"}}]}',
        'data: {"id":"r-1","choices":[{"delta":{"content":"{\\"topics\\":["}}]}',
        'data: {"id":"r-1","choices":[{"delta":{"content":"]}"}, "finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":200,"completion_tokens":12,'
        '"completion_tokens_details":{"reasoning_tokens":8},'
        '"prompt_cache_hit_tokens":50}}',
        "data: [DONE]",
    ]
    fake_response = _FakeStreamResponse(status_code=200, lines=lines)
    fake_client = _FakeAsyncClient(fake_response)

    monkeypatch.setattr(
        curator_shadow.httpx,
        "AsyncClient",
        lambda **kwargs: fake_client,
    )

    result = await curator_shadow._stream_chat(
        api_key="fake", body={"model": "deepseek-v4-flash", "messages": []},
        log_label="test",
    )

    assert result.content == '{"topics":[]}'
    assert result.reasoning_content == "think A think B"
    assert result.finish_reason == "stop"
    assert result.response_id == "r-1"
    assert result.prompt_tokens == 200
    assert result.completion_tokens == 12
    assert result.reasoning_tokens == 8
    assert result.cached_tokens == 50
    # 150 uncached input * $0.07/M + 50 cached * $0.014/M + 12 output * $0.56/M
    expected = round(
        (150 * 0.07 + 50 * 0.014 + 12 * 0.56) / 1_000_000.0, 6,
    )
    assert result.cost_usd == expected


@pytest.mark.asyncio
async def test_stream_chat_raises_on_non_200(monkeypatch) -> None:
    """A non-200 HTTP status surfaces a ``HTTPStatusError`` with the
    body in the message — the variant runner catches and marks status=error."""
    from scripts import curator_shadow

    fake_response = _FakeStreamResponse(
        status_code=400,
        lines=['{"error":{"message":"missing word json"}}'],
        request=None,
    )
    fake_client = _FakeAsyncClient(fake_response)
    monkeypatch.setattr(
        curator_shadow.httpx,
        "AsyncClient",
        lambda **kwargs: fake_client,
    )

    with pytest.raises(curator_shadow.httpx.HTTPStatusError, match="HTTP 400"):
        await curator_shadow._stream_chat(
            api_key="fake", body={"model": "deepseek-v4-flash", "messages": []},
            log_label="test",
        )


def test_three_day_decision_returns_none_when_fewer_than_three_days(
    tmp_path: Path, monkeypatch,
) -> None:
    """aggregate_three_day_decision returns None if fewer than 3 dated
    sub-directories exist under output/curator-shadow/."""
    from scripts import curator_shadow

    # Redirect SHADOW_DIR to a temp location with only 1 day populated
    shadow_dir = tmp_path / "curator-shadow"
    shadow_dir.mkdir(parents=True)
    (shadow_dir / "2026-05-12").mkdir()
    (shadow_dir / "2026-05-12" / "A.json").write_text(
        json.dumps({"status": "ok", "metrics": {}}), encoding="utf-8",
    )
    (shadow_dir / "2026-05-12" / "B.json").write_text(
        json.dumps({"status": "ok", "metrics": {}}), encoding="utf-8",
    )
    monkeypatch.setattr(curator_shadow, "SHADOW_DIR", shadow_dir)

    assert curator_shadow.aggregate_three_day_decision() is None
