# WP-REASONING — Configurable Reasoning Effort per Agent

## Goal

Enable per-agent control over reasoning/thinking effort. Different agents need different reasoning depths: the Collector just lists findings (low), the Editor needs to make nuanced prioritization decisions (high).

## Context

The Agent class uses `AsyncOpenAI` (OpenAI-compatible client) for all LLM calls. Reasoning parameters are **not** part of the standard OpenAI chat completions spec — they must be passed via `extra_body`.

### Provider-Specific Parameters

**OpenRouter** uses a unified `reasoning` object:
```json
{
  "reasoning": {
    "effort": "high"
  }
}
```
Effort levels: `minimal`, `low`, `medium`, `high`, `xhigh`
OpenRouter maps this to each provider's native implementation (Anthropic → `output_config.effort`, OpenAI → `reasoning_effort`, etc.).

**Ollama (local + cloud)** uses a `think` parameter:
```json
{
  "think": true
}
```
Boolean (true/false). Some models (e.g. GPT-OSS) accept levels: `"low"`, `"medium"`, `"high"`.
Note: Via the OpenAI-compatible endpoint (`/v1/chat/completions`), this needs to be passed as extra body.

## What to Build

### 1. Add `reasoning` parameter to Agent constructor

```python
class Agent:
    def __init__(
        self,
        ...
        reasoning: str | bool | None = None,  # None = model default
        ...
    ):
```

Valid values:
- `None` — don't send any reasoning parameter (model default behavior)
- `True` / `False` — enable/disable thinking (maps to Ollama's `think`)
- `"low"`, `"medium"`, `"high"` — effort level (maps to OpenRouter's `reasoning.effort` or Ollama's `think` level)

### 2. Map to provider-specific parameters in `_call_with_retry`

Inside `_call_with_retry`, build `extra_body` based on the provider:

```python
extra_body = {}

if self.reasoning is not None:
    if self.provider == "openrouter":
        if isinstance(self.reasoning, bool):
            extra_body["reasoning"] = {"effort": "high" if self.reasoning else "minimal"}
        elif isinstance(self.reasoning, str):
            extra_body["reasoning"] = {"effort": self.reasoning}
    elif self.provider in ("ollama", "ollama_cloud"):
        if isinstance(self.reasoning, bool):
            extra_body["think"] = self.reasoning
        elif isinstance(self.reasoning, str):
            # Some Ollama models accept level strings
            extra_body["think"] = self.reasoning

if extra_body:
    kwargs["extra_body"] = extra_body
```

### 3. Make it configurable per agent

In `scripts/run.py` and in future config files:
```python
agents = {
    "collector": Agent(
        name="collector",
        model="minimax-m2.7:cloud",
        reasoning=None,         # no thinking needed, just collect
        ...
    ),
    "editor": Agent(
        name="editor",
        model="glm-5:cloud",
        reasoning="high",       # needs careful prioritization
        ...
    ),
}
```

## What NOT to Do

- Don't parse or process the thinking/reasoning output. Just let it happen inside the model and take the final response.
- Don't make this a pipeline-level setting. It's per-agent — each agent has different reasoning needs.
- Don't add `reasoning` to the config file schema yet. First get it working in code, then add config support.

## Dependencies

- WP-INTEGRATION must be done first (need a working pipeline to test reasoning differences)

## Definition of Done

1. Agent constructor accepts `reasoning` parameter
2. Parameter is correctly mapped to provider-specific extra_body in API calls
3. Setting `reasoning="high"` on one agent and `reasoning=None` on another works in the same pipeline run
4. Existing tests still pass (reasoning=None is default, no behavior change)
