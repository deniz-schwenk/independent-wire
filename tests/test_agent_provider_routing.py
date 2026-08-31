"""Provider-routing preference (the DeepSeek fp8 pin) — TASK-DEEPSEEK-FP8-PIN.

Verifies that Agent(provider_routing=...) puts exactly the intended `provider`
block into the request body, that require_parameters is added on top for schema
calls, and that neither the shared provider_routing nor extra_body_override is
mutated across calls (the setdefault aliasing trap, docs/CODE-REVIEW-2026-07-02).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pathlib import Path

import pytest

from src.agent import Agent

MODEL = "deepseek/deepseek-v4-pro"


@pytest.fixture
def prompt_file(tmp_path) -> str:
    path = tmp_path / "AGENTS.md"
    path.write_text("You are a helpful test assistant.")
    return str(path)


TINY_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _mk_agent(prompt_file, **kw) -> Agent:
    return Agent(
        name="t",
        model=MODEL,
        system_prompt_path=prompt_file,
        instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
        **kw,
    )


async def _captured_extra_body(agent: Agent, output_schema=None) -> dict:
    """Drive _call_with_retry once with a mocked client and return the
    extra_body that was sent in the request."""
    agent._client.chat.completions.create = AsyncMock(return_value=MagicMock())
    await agent._call_with_retry(
        messages=[{"role": "user", "content": "x"}],
        tools=None,
        output_schema=output_schema,
    )
    return agent._client.chat.completions.create.call_args.kwargs["extra_body"]


@pytest.mark.asyncio
async def test_provider_routing_produces_exact_block_with_schema(prompt_file):
    routing = {"order": ["baidu/fp8", "wandb/fp8", "parasail/fp8"],
               "allow_fallbacks": False, "quantizations": ["fp8"]}
    agent = _mk_agent(prompt_file, provider_routing=routing, reasoning="none")
    extra_body = await _captured_extra_body(agent, output_schema=TINY_SCHEMA)
    assert extra_body["provider"] == {
        "order": ["baidu/fp8", "wandb/fp8", "parasail/fp8"],
        "allow_fallbacks": False,
        "quantizations": ["fp8"],
        "require_parameters": True,  # added by Agent for schema calls
    }


@pytest.mark.asyncio
async def test_provider_routing_applies_without_schema(prompt_file):
    """The fp8 pin applies to every call, even one without a response_format
    (no require_parameters then — there are no params to require)."""
    routing = {"order": ["baidu/fp8"], "allow_fallbacks": False, "quantizations": ["fp8"]}
    agent = _mk_agent(prompt_file, provider_routing=routing, reasoning="none")
    extra_body = await _captured_extra_body(agent, output_schema=None)
    assert extra_body["provider"] == {
        "order": ["baidu/fp8"], "allow_fallbacks": False, "quantizations": ["fp8"],
    }


@pytest.mark.asyncio
async def test_provider_routing_not_mutated_across_calls(prompt_file):
    """require_parameters must NOT leak back into the shared provider_routing
    dict — the aliasing trap. The instance dict stays pristine across calls."""
    routing = {"order": ["baidu/fp8"], "allow_fallbacks": False, "quantizations": ["fp8"]}
    agent = _mk_agent(prompt_file, provider_routing=routing, reasoning="none")
    await _captured_extra_body(agent, output_schema=TINY_SCHEMA)
    await _captured_extra_body(agent, output_schema=TINY_SCHEMA)
    assert agent._provider_routing == {
        "order": ["baidu/fp8"], "allow_fallbacks": False, "quantizations": ["fp8"],
    }
    assert "require_parameters" not in agent._provider_routing
    # the caller's original dict is likewise untouched
    assert routing == {"order": ["baidu/fp8"], "allow_fallbacks": False, "quantizations": ["fp8"]}


@pytest.mark.asyncio
async def test_extra_body_override_provider_not_mutated(prompt_file):
    """The pre-existing setdefault aliasing trap (CODE-REVIEW agent.py:362):
    a provider block passed via extra_body_override must not accumulate
    require_parameters across calls."""
    agent = _mk_agent(
        prompt_file,
        extra_body_override={"provider": {"only": ["baidu"]}},
        reasoning="none",
    )
    extra_body = await _captured_extra_body(agent, output_schema=TINY_SCHEMA)
    # the request gets require_parameters ...
    assert extra_body["provider"]["require_parameters"] is True
    assert extra_body["provider"]["only"] == ["baidu"]
    # ... but the shared instance dict does NOT
    assert agent._extra_body_override == {"provider": {"only": ["baidu"]}}


@pytest.mark.asyncio
async def test_non_openrouter_ignores_provider_routing(prompt_file):
    """provider_routing is an OpenRouter concept; a non-OpenRouter provider
    must not receive a `provider` block from it."""
    routing = {"order": ["baidu/fp8"], "allow_fallbacks": False, "quantizations": ["fp8"]}
    agent = _mk_agent(prompt_file, provider="ollama", provider_routing=routing,
                      base_url="http://localhost:11434/v1", reasoning="none")
    extra_body = await _captured_extra_body(agent, output_schema=None)
    assert "provider" not in (extra_body or {})


def test_both_deepseek_fp8_pins_are_retired():
    """Neither DeepSeek fp8 routing constant exists any more.

    ``DEEPSEEK_V4_FLASH_FP8_ROUTING`` went on 2026-08-24 (TASK-FLASH-0731-SWAP)
    and ``DEEPSEEK_V4_PRO_FP8_ROUTING`` on 2026-08-31 (TASK-DSV4-SWAPS-BUNDLE),
    each when the last stage referencing it moved to full-precision
    v4-flash-0731 on the two-channel wiring. The pins existed because fp4
    quantization causes fabrications in DeepSeek V4
    (docs/DEEPSEEK-FP8-PIN-2026-07.md); that hazard is unreachable from a route
    that never leaves DeepSeek's own endpoint.

    Asserting the ABSENCE is the point: a reintroduced pin means a swap was
    partially reverted, and that is the state this guard exists to catch.
    """
    import scripts.run as run_mod

    for retired in ("DEEPSEEK_V4_FLASH_FP8_ROUTING", "DEEPSEEK_V4_PRO_FP8_ROUTING"):
        assert not hasattr(run_mod, retired), (
            f"{retired} is retired; see TASK-FLASH-0731-SWAP / "
            f"TASK-DSV4-SWAPS-BUNDLE"
        )
    # ... and no agent may quietly grow one back inline.
    src = (Path(run_mod.__file__)).read_text(encoding="utf-8")
    assert "deepseek/deepseek-v4-pro" not in src, (
        "no stage runs deepseek-v4-pro any more (TASK-DSV4-SWAPS-BUNDLE)"
    )


def test_flash_0731_native_routing_has_no_quantization_filter():
    """Channel A's pin must NOT carry a quantizations filter.

    The DeepSeek endpoint reports quantization "unknown"; any filter excludes
    it and the call 404s with "No endpoints found" (T2b §1.1). Every other pin
    in scripts/run.py filters by construction, so this one reads like an
    omission — it is not, and this guard says so.
    """
    from scripts.run import DEEPSEEK_NATIVE_ROUTING

    assert DEEPSEEK_NATIVE_ROUTING["order"] == ["deepseek"]
    assert DEEPSEEK_NATIVE_ROUTING["allow_fallbacks"] is False
    assert "quantizations" not in DEEPSEEK_NATIVE_ROUTING
