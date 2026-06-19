"""Transports for the German translation feature — the per-TP fallback chain.

Four providers, tried in order; if one fails a whole TP (transport error, HTTP 5xx, or
the deterministic guard cannot get a clean result after the temperature-ladder retries),
the WHOLE TP restarts on the next provider (never mix providers within one TP).

  1. ollama-cloud      deepseek-v4-pro:cloud via the local daemon (flat-rate, $0 OpenRouter)
  2. deepseek-direct   api.deepseek.com, strict TOOLS transport, thinking disabled
                       (the transport proven for the bias stage; key from env DEEPSEEK_API_KEY)
  3. openrouter:deepseek    provider pinned "deepseek",    json_object + Python guard
  4. openrouter:atlas-cloud provider pinned "atlas-cloud", json_object + Python guard

The billed transport (2-4) is bench_lib.call_llm — which itself "replicates src/agent.py
exactly" — ported here so the live feature stays SEPARATE from the pipeline (it never
imports src/agent.py, src/bus.py, or scripts/run.py) yet runs on the exact transport that
was validated. The only deliberate change from the bench is key sourcing: keys come from
the repo environment (OPENROUTER_API_KEY, DEEPSEEK_API_KEY), not bench-private files.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
import urllib.request

from . import core

# ---- transport tuning (verbatim from the validated driver_v3 / driver_v2) ----
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "deepseek-v4-pro:cloud"
NUM_PREDICT = 32000
NUM_CTX_MAX = 32768
TOP_P = 1.0
RETRYABLE = {429, 500, 502, 503, 529}

# DeepSeek direct API (no usage.cost in responses) — conservative list price for spend
# accounting; OpenRouter normally reports usage.cost directly.
FALLBACK_PRICE_PER_M = {
    "deepseek-v4-pro": (0.435, 0.87),
    "deepseek/deepseek-v4-pro": (0.6, 1.8),
}

# Strict-tools schema (provider 2): constrains decoding to the canonical prompt's
# six-field-per-item contract exactly, so the guard's six-field check passes.
_DE_ITEM = {
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "analyse": {"type": "string"},
        "translation": {"type": "string"},
        "verify": {"type": "string"},
        "pass": {"type": "boolean"},
        "correction": {"type": "string"},
        "final": {"type": "string"},
    },
    "required": ["key", "analyse", "translation", "verify", "pass", "correction", "final"],
    "additionalProperties": False,
}
DE_BLOCK_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": _DE_ITEM}},
    "required": ["items"],
    "additionalProperties": False,
}
# json_object mode (providers 1,3,4): the prompt defines the shape, the guard validates.
DE_JSON_OBJECT = {"type": "object", "properties": {"items": {"type": "array"}},
                  "required": ["items"], "additionalProperties": True}


class TransportError(Exception):
    """A whole-TP-failing transport condition: connection error, HTTP 5xx, missing
    credentials, or an unparseable/empty response. Triggers the next provider."""


# ----------------------------------------------------------- Ollama-Cloud (provider 1)

def _ollama_generate(host, model, system, user, num_ctx, temperature, timeout=600):
    """One json_object call to Ollama-Cloud via the local daemon. (verbatim driver_v3.)"""
    payload = {
        "model": model, "system": system, "prompt": user,
        "stream": False, "think": False, "format": "json",
        "options": {"temperature": temperature, "num_ctx": num_ctx,
                    "num_predict": NUM_PREDICT, "top_p": TOP_P},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(host + "/api/generate", data=data,
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    meta = {"latency_s": round(time.monotonic() - t0, 2),
            "done_reason": resp.get("done_reason"),
            "eval_count": resp.get("eval_count"),
            "prompt_eval_count": resp.get("prompt_eval_count")}
    raw = resp.get("response", "") or ""
    return core.parse_json_loose(raw), meta


# ----------------------------------------------------------- billed transport (providers 2-4)

def _make_client(api: str):
    """OpenAI-compatible async client. Keys come from the repo environment."""
    from openai import AsyncOpenAI
    import httpx
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
    if api == "deepseek_direct":
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise TransportError("DEEPSEEK_API_KEY not set in environment")
        # Main base URL — strict tool enforcement is GA there (the /beta path is not).
        return AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=timeout)
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise TransportError("OPENROUTER_API_KEY not set in environment")
    return AsyncOpenAI(api_key=key, base_url="https://openrouter.ai/api/v1", timeout=timeout)


async def _call_llm(client, model, user, system, temperature, max_tokens, schema,
                    schema_name, strict, tool_mode, disable_thinking, provider_order,
                    max_retries=4):
    """One chat-completions call. (ported from bench_lib.call_llm — call shape
    replicates src/agent.py exactly.) Returns the validated result dict."""
    from openai import APIStatusError
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    kwargs: dict = {"model": model, "messages": messages,
                    "temperature": temperature, "max_tokens": max_tokens}
    extra_body: dict = {}
    if disable_thinking:
        extra_body["thinking"] = {"type": "disabled"}
    if provider_order:
        extra_body["provider"] = {"order": list(provider_order), "allow_fallbacks": False}
    if schema and tool_mode:
        kwargs["tools"] = [{"type": "function", "function": {
            "name": schema_name, "description": "Emit the complete result object.",
            "strict": True, "parameters": schema}}]
        kwargs["tool_choice"] = {"type": "function", "function": {"name": schema_name}}
        if provider_order:
            extra_body.setdefault("provider", {})["require_parameters"] = True
    elif schema and strict:
        kwargs["response_format"] = {"type": "json_schema", "json_schema": {
            "name": schema_name, "strict": True, "schema": schema}}
        extra_body.setdefault("provider", {})["require_parameters"] = True
    elif schema and not strict:
        kwargs["response_format"] = {"type": "json_object"}
    if extra_body:
        kwargs["extra_body"] = extra_body

    start = time.monotonic()
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.chat.completions.create(**kwargs)
            break
        except APIStatusError as e:
            last_err = e
            transient_400 = (e.status_code == 400 and "Provider returned error" in str(e))
            if (e.status_code not in RETRYABLE and not transient_400) or attempt == max_retries:
                raise
            await asyncio.sleep(2 * (2 ** attempt) + random.uniform(0, 1))
    else:  # pragma: no cover
        raise last_err

    duration = time.monotonic() - start
    msg = resp.choices[0].message
    content = msg.content or ""
    via_tool_call = False
    if tool_mode:
        tcs = getattr(msg, "tool_calls", None) or []
        if tcs:
            content = tcs[0].function.arguments or ""
            via_tool_call = True
    usage = getattr(resp, "usage", None)
    p_tok = getattr(usage, "prompt_tokens", 0) or 0
    c_tok = getattr(usage, "completion_tokens", 0) or 0
    total_tok = getattr(usage, "total_tokens", 0) or (p_tok + c_tok)
    cost = getattr(usage, "cost", None) if usage is not None else None
    estimated = False
    if cost is None:
        rates = FALLBACK_PRICE_PER_M.get(model, (5.0, 25.0))
        cost = p_tok / 1e6 * rates[0] + c_tok / 1e6 * rates[1]
        estimated = True
    return {"content": content, "parsed": core.parse_json_loose(content) if content else None,
            "cost_usd": float(cost), "cost_estimated": estimated, "tokens": total_tok,
            "prompt_tokens": p_tok, "completion_tokens": c_tok,
            "duration_s": round(duration, 2),
            "provider": getattr(resp, "provider", "") or "",
            "via_tool_call": via_tool_call}


# ----------------------------------------------------------- provider abstraction

class Provider:
    """Uniform interface: generate(system, user, temperature) -> (parsed_obj|None, meta).
    meta carries latency_s, cost_usd, and served-provider. Raises TransportError on a
    whole-TP-failing condition."""

    name: str
    billed: bool

    async def generate(self, system: str, user: str, temperature: float):
        raise NotImplementedError


class OllamaCloudProvider(Provider):
    name = "ollama-cloud"
    billed = False

    def __init__(self, host=OLLAMA_HOST, model=OLLAMA_MODEL):
        self.host, self.model = host, model

    async def generate(self, system, user, temperature):
        input_tok = (len(system) + len(user)) // 3
        num_ctx = max(8192, min(NUM_CTX_MAX, input_tok * 2 + 1024))
        try:
            parsed, meta = await asyncio.to_thread(
                _ollama_generate, self.host, self.model, system, user, num_ctx, temperature)
        except Exception as e:  # urllib HTTPError/URLError, timeouts, JSON errors
            raise TransportError(f"ollama-cloud: {type(e).__name__}: {e}") from e
        meta["num_ctx"] = num_ctx
        meta["cost_usd"] = 0.0
        meta["served_provider"] = "ollama-cloud"
        return parsed, meta


class BilledProvider(Provider):
    billed = True

    def __init__(self, name, api, model, tool_mode, strict, disable_thinking,
                 provider_order, schema):
        self.name = name
        self.api = api
        self.model = model
        self.tool_mode = tool_mode
        self.strict = strict
        self.disable_thinking = disable_thinking
        self.provider_order = provider_order
        self.schema = schema
        self._client = None

    def _client_or_make(self):
        if self._client is None:
            self._client = _make_client(self.api)  # raises TransportError if no key
        return self._client

    async def generate(self, system, user, temperature):
        # Generous budget for the six-field self-revision (output ~3-4x source); bounded.
        max_tokens = max(2000, min(16000, len(user) // 3 * 4))
        try:
            client = self._client_or_make()
            res = await _call_llm(
                client, self.model, user, system=system, temperature=temperature,
                max_tokens=max_tokens, schema=self.schema, schema_name="block",
                strict=self.strict, tool_mode=self.tool_mode,
                disable_thinking=self.disable_thinking,
                provider_order=self.provider_order)
        except TransportError:
            raise
        except Exception as e:
            raise TransportError(f"{self.name}: {type(e).__name__}: {e}") from e
        meta = {"latency_s": res["duration_s"], "cost_usd": res["cost_usd"],
                "cost_estimated": res["cost_estimated"], "num_ctx": None,
                "served_provider": res["provider"] or self.name,
                "via_tool_call": res["via_tool_call"]}
        return res["parsed"], meta


def build_chain(force_fail=None, dry_billed=False, ollama_host=OLLAMA_HOST):
    """The 4-step fallback chain, in order. force_fail/dry_billed are smoke fault-injection."""
    force_fail = set(force_fail or [])
    chain = [
        OllamaCloudProvider(host=ollama_host),
        BilledProvider("deepseek-direct", "deepseek_direct", "deepseek-v4-pro",
                       tool_mode=True, strict=True, disable_thinking=True,
                       provider_order=None, schema=DE_BLOCK_TOOL_SCHEMA),
        BilledProvider("openrouter:deepseek", "openrouter", "deepseek/deepseek-v4-pro",
                       tool_mode=False, strict=False, disable_thinking=False,
                       provider_order=["deepseek"], schema=DE_JSON_OBJECT),
        BilledProvider("openrouter:atlas-cloud", "openrouter", "deepseek/deepseek-v4-pro",
                       tool_mode=False, strict=False, disable_thinking=False,
                       provider_order=["atlas-cloud"], schema=DE_JSON_OBJECT),
    ]
    return [_maybe_wrap(p, force_fail, dry_billed) for p in chain]


def _maybe_wrap(provider, force_fail, dry_billed):
    """Wrap a provider so the smoke can prove the chain at $0: force a named provider to
    fail, and/or stub all BILLED providers to a synthetic failure (no real network call)."""
    fail = provider.name in force_fail or (dry_billed and provider.billed)
    if not fail:
        return provider
    return _ForcedFailProvider(provider, dry=dry_billed and provider.billed)


class _ForcedFailProvider(Provider):
    def __init__(self, inner, dry):
        self.inner = inner
        self.name = inner.name
        self.billed = inner.billed
        self._dry = dry

    async def generate(self, system, user, temperature):
        tag = "dry-stub" if self._dry else "forced"
        raise TransportError(f"{self.name}: synthetic failure ({tag}, smoke) — no network call")
