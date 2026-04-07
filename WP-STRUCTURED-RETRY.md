# WP-STRUCTURED-RETRY — Claude Code Task

## Task
Add retry logic for failed structured output parsing in the Agent class. Currently, when `output_schema` is provided but the LLM returns unparseable text instead of valid JSON, the agent silently sets `structured=None` and moves on. This is not acceptable for pipeline reliability — especially with models like GLM-5 and MiniMax that are less consistent with JSON output than GPT-4o or Claude.

## Read first
1. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/agent.py` — the existing Agent code (focus on the `run()` method, specifically the structured output parsing at the end)
2. `/Users/denizschwenk/Documents/independent-wire/repo-clone/tests/test_agent.py` — existing tests

## Working directory
`/Users/denizschwenk/Documents/independent-wire/repo-clone/`

## What to build

### Modify `src/agent.py` — Add structured output retry

When `output_schema` is provided and the LLM response cannot be parsed as valid JSON, the agent should retry the call with a corrective message. Here is the logic:

#### Retry flow (inside `run()`, after the tool-call loop completes):

1. If `output_schema` is set, attempt to parse `content` as JSON (this already exists)
2. If parsing fails: **retry up to 2 more times** with a corrective follow-up message
3. The corrective message is appended to the existing conversation (not a fresh call), so the model sees its own failed attempt
4. Corrective message content: `"Your previous response could not be parsed as valid JSON. Return ONLY a valid JSON object or array matching the requested schema. No markdown, no code fences, no explanatory text — just the raw JSON."`
5. After each retry, attempt to parse again
6. If all retries fail: log a WARNING, set `structured=None`, and return the result as-is (do NOT raise — the pipeline handles None gracefully)

#### Implementation approach:

Add a new constant:
```python
MAX_STRUCTURED_RETRIES = 2
```

Add a new private method:
```python
async def _parse_or_retry_structured(
    self,
    messages: list[dict],
    content: str,
    output_schema: dict,
    tool_defs: list[dict] | None,
) -> tuple[str, dict | None, int]:
    """
    Try to parse content as JSON. If it fails, retry with corrective prompt.
    
    Returns: (final_content, structured_or_none, additional_tokens_used)
    """
```

This method:
- First tries to parse `content` using the existing fence-stripping logic
- If parsing succeeds: return immediately
- If parsing fails: append the assistant's response + corrective user message to `messages`, call `_call_with_retry()` again, try to parse the new response
- Repeat up to MAX_STRUCTURED_RETRIES times
- Log each retry attempt: `"Agent '%s': structured output retry %d/%d"`
- Return the final content, parsed structured data (or None), and total additional tokens used

Then refactor `run()` to call `_parse_or_retry_structured()` instead of doing inline parsing. Replace the existing parsing block (the `if output_schema and content:` section near the end of `run()`) with a call to this new method.

#### Important constraints:
- Do NOT change the retry logic for HTTP errors (`_call_with_retry`) — that stays as-is
- Do NOT change the tool-call loop — that stays as-is
- The corrective retry uses the SAME conversation history (append to `messages`), not a fresh call
- Tool definitions should NOT be passed in the retry calls (set tools=None) — we want a plain text response, not more tool calls
- The additional tokens from retries must be added to `total_tokens` in the AgentResult

### Add tests to `tests/test_agent.py`

#### Unit test (no API key needed):

**test_parse_structured_strips_fences**
- Create an agent with a fake key
- Call the JSON parsing logic with content wrapped in ```json ... ``` fences
- Assert it correctly extracts the JSON

**test_parse_structured_handles_plain_json**
- Same but with plain JSON (no fences)
- Assert correct extraction

#### Integration tests (require OPENROUTER_API_KEY):

**test_structured_retry_recovers** (marked with `@skip_no_key`)
- Create an Agent with a model that sometimes returns text with JSON
- Use a prompt that's likely to produce mixed output on first try, e.g.: "Tell me about Paris and also return your answer as JSON with keys: city, country, population"
- Provide output_schema
- Assert that `result.structured` is not None (retry should recover)
- This test is allowed to be flaky — it tests a probabilistic behavior

**IMPORTANT:** All existing tests MUST continue to pass unchanged.

## Technical rules
- Python 3.11+, type hints everywhere
- Logging via `logging.getLogger(__name__)`, no print()
- Existing tests MUST NOT break
- Keep the change minimal — only touch the structured output parsing path
- No new dependencies

## Acceptance criteria
1. `python -m pytest tests/ -v` passes completely (all tests including existing ones)
2. When `output_schema` is set and first parse fails, agent retries up to 2 times with corrective message
3. Retries use the same conversation context (appended messages, not fresh calls)
4. Additional tokens from retries are counted in AgentResult.tokens_used
5. If all retries fail, `structured=None` is returned (no exception raised)
6. Each retry is logged with attempt number

## After building
```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
source .venv/bin/activate && source .env && python -m pytest tests/ -v
git add -A
git commit -m "WP-STRUCTURED-RETRY: Retry logic for failed structured output parsing

- Agent retries up to 2 times when JSON parsing fails with output_schema
- Corrective message appended to conversation context for retry
- Additional tokens from retries tracked in AgentResult
- Graceful fallback: structured=None if all retries fail
- Tests for fence stripping and retry recovery"
git push origin main
```
