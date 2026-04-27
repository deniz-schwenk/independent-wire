# Research Note: OpenRouter Structured Outputs

**Date:** 2026-04-23
**Researcher:** Architect (S13)
**Sources:** OpenRouter docs, Anthropic Claude API docs

**Status:** ✅ Shipped 2026-04-28 (commits 13cc76a, d56ff32, 15ebc81). Strict-mode `response_format` is now wired for: Curator, Editor, Researcher PLAN, Researcher Assemble, Perspektiv, Writer, QA+Fix, Bias Detector. Perspektiv-Sync (hydrated-only) and Hydration Aggregator phases (Phase 5) remain unwired.

---

## TL;DR

**Yes, OpenRouter supports structured outputs.** Two modes are available via the `response_format` parameter on the Chat Completions endpoint:

1. **`{"type": "json_object"}`** — Basic JSON mode. Model returns valid JSON, but no schema enforcement. Simple and broadly supported.
2. **`{"type": "json_schema", "json_schema": {...}}`** — Strict schema mode. Model output is **constrained at decoding time** to match the provided JSON Schema exactly. Mathematical guarantee, no parse failures.

For our pipeline, **mode 2 is the relevant one.** Mode 1 is no better than what we already have (we already prompt for JSON output).

## How it works for Anthropic models on OpenRouter

OpenRouter normalises this across providers. For Anthropic models specifically:

- Anthropic's **native** API uses a different parameter shape: `output_config.format` with a beta header `anthropic-beta: structured-outputs-2025-11-13`.
- **OpenRouter handles the translation automatically.** When we pass `response_format: {type: "json_schema", ...}` to OpenRouter targeting an Anthropic model, OpenRouter applies the beta header and rewrites the parameter to Anthropic's native shape. From our code's perspective, we use the OpenAI-compatible `response_format`. This is documented:

> *"OpenRouter manages some Anthropic beta features automatically: ... Structured outputs for JSON schema response format (response_format.type: 'json_schema') — the header is automatically applied"*
>
> — [OpenRouter Provider Routing docs](https://openrouter.ai/docs/guides/routing/provider-selection)

## Models that support strict schema mode

Per the Anthropic blog (Feb 4, 2026 — General Availability):

- Claude Opus 4.7 ✅
- Claude Opus 4.6 ✅ (our current production model)
- Claude Sonnet 4.6 ✅ (our current QA+Fix model)
- Claude Sonnet 4.5 ✅
- Claude Opus 4.5 ✅
- Claude Haiku 4.5 ✅

For Gemini-3-flash-preview (our Curator/Researcher/Phase1 model): support is provider-dependent; on OpenRouter it is enabled via `response_format.type: "json_schema"` for Google models that support it. Per the OpenRouter Models API, the `supported_parameters` array on each model entry lists `response_format` and `structured_outputs` flags. We can verify per-model at runtime.

## Required request shape

Per [OpenRouter Structured Outputs guide](https://openrouter.ai/docs/guides/features/structured-outputs):

```json
{
  "model": "anthropic/claude-opus-4.6",
  "messages": [...],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "perspektiv_output",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "position_clusters": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "position_label": {"type": "string"},
                "position_summary": {"type": "string"},
                "source_ids": {
                  "type": "array",
                  "items": {"type": "string"}
                }
              },
              "required": ["position_label", "position_summary", "source_ids"],
              "additionalProperties": false
            }
          },
          "missing_positions": {"type": "array", "items": {"type": "object"}}
        },
        "required": ["position_clusters", "missing_positions"],
        "additionalProperties": false
      }
    }
  }
}
```

Required for strict mode:

- `strict: true` — enables constrained decoding
- `additionalProperties: false` on every object — prevents the model from adding fields outside the schema
- `required` lists every property the model must emit — **all properties listed under `properties` must be in `required`** (Anthropic / OpenAI strict-mode convention)
- `name` — a logical name for the schema (used in caching and error messages)

## Provider routing recommendation

For maximum reliability when using strict schema mode, set `provider.require_parameters: true` so OpenRouter only routes to providers that actually support `response_format.json_schema`:

```json
{
  "model": "anthropic/claude-opus-4.6",
  "provider": {
    "require_parameters": true,
    "order": ["anthropic"]
  },
  "response_format": {...}
}
```

This avoids fallback to providers that would silently ignore the schema.

## Streaming compatibility

Strict schema mode works with streaming. The model streams partial JSON tokens that, when complete, form a valid response matching the schema. No special handling needed.

## Caching effect

First request with a new schema: 100–300ms grammar compilation overhead. Cached for 24 hours. Subsequent requests with the same schema: full speed. For our pipeline (3–4 production runs per day, same schemas), the schema is effectively always cached.

## Implications for Independent Wire

**This makes our entire `_extract_dict` / `_extract_list` / `json_repair` / `_log_raw_on_parse_failure` complex stack obsolete for agents that emit JSON objects.** We can replace it with a single trusted parse.

### Affected agents (everything that emits a JSON object)

All thirteen rewritten agents emit JSON objects with defined schemas. Every single one would benefit from strict mode:

| Agent | Output Schema |
|---|---|
| Curator | `{topics, cluster_assignments}` |
| Editor | `[{title, selection_reason, priority, follow_up_to, follow_up_reason}]` (array) |
| Researcher PLAN | `[{query, language}]` (array) |
| Researcher Hydrated PLAN | `[{query, language}]` (array) |
| Researcher ASSEMBLE | `{sources, coverage_gaps}` |
| Hydration Aggregator PHASE 1 | `{article_analyses}` |
| Hydration Aggregator PHASE 2 | `{preliminary_divergences, coverage_gaps}` |
| Perspektiv | `{position_clusters, missing_positions}` |
| Writer | `{headline, subheadline, body, summary, sources}` |
| QA+Fix | `{problems_found, proposed_corrections, article, divergences}` |
| Perspektiv-Sync | `{position_cluster_updates}` |
| Bias Detector | `{language_bias, reader_note}` |

**The Writer is a special case** — its `body` field carries free-form prose. Schema cannot constrain prose content (only field presence and shape). Strict mode would still help: it guarantees the five top-level fields exist and `sources` is an array of the right shape. The body itself remains unconstrained text.

### Risks and considerations

1. **Schema must be exhaustive.** With `additionalProperties: false`, the model cannot emit fields that are not declared. If we miss a field in the schema, the model can't emit it even when it should. Audit the schemas against the actual prompt outputs before activation.

2. **`required` is total in strict mode.** Every property must be listed as required. Optional fields don't exist in strict mode the way they do in regular JSON Schema. Workaround: model the field as `{"type": ["string", "null"]}` and require it; the model emits `null` when the field is not applicable. This applies to e.g. Editor's `follow_up_to` (null when standalone topic).

3. **Schema compilation latency on first call.** 100–300ms one-time overhead per schema, then cached for 24h. Negligible for production runs.

4. **Still a beta header on Anthropic side** — though OpenRouter applies it transparently. Anthropic could change the contract; OpenRouter would need to update its translation layer. Low practical risk given GA status, but a tail risk worth noting.

5. **Tool-using agents are unaffected.** The Writer uses `web_search`. Strict mode works alongside tool calls — schema enforcement applies to the final assistant message, not to tool-call arguments. Tool calls follow their own JSON Schema (tool-input schema), which is separate.

## Recommendation

**Phase this in carefully.** Adding strict mode to all 13 agents at once is risky — if any schema is mis-specified, that agent will fail every call. Recommend:

1. **Pilot with one low-risk agent first.** Researcher PLAN is a good candidate: schema is trivial (`[{query, language}]`), output is short, error mode is well-understood. Add `response_format` to its agent config in `scripts/run.py`, write the schema, observe one full pipeline run.

2. **If the pilot is clean, expand to the synthesis agents.** Perspektiv → QA+Fix → Bias Detector → Perspektiv-Sync. These have the most complex schemas but also the highest payoff (they currently have the most parse failures historically per WP-MEMORY-V1 / Lauf 13 root-cause notes).

3. **Writer last.** The free-form `body` makes it the lowest-payoff candidate (the structural fields rarely fail; the prose is what matters). Add it once everything else is validated.

4. **Keep the `_extract_dict` / `json_repair` fallbacks during rollout.** Strict mode failures should be rare but not impossible — partial schema definitions, beta-header changes, etc. Defense-in-depth.

5. **Schema-as-data.** Don't hand-craft each schema in `scripts/run.py`. Define schemas in one place (e.g. `src/schemas.py` or a new `agents/{name}/SCHEMA.json` per agent), import them where needed. Single source of truth.

## Open questions

- **Per-model verification.** The OpenRouter Models API exposes `supported_parameters[]` per model, which lists `response_format` and `structured_outputs` flags when supported. We should query this once and confirm all current production models pass. Worth adding a startup check in `Agent.__init__`: warn if the configured model's `supported_parameters` does not include `structured_outputs`.

- **Reasoning compatibility.** Anthropic's extended-thinking mode previously had compatibility issues with strict tool use (Sonnet 3.7). Need to verify that `reasoning=none` (our production setting) is fully compatible with strict schema mode. Initial signs say yes — strict mode is GA — but worth confirming on a smoke run.

- **Cost effect.** Strict mode caches the schema on the provider side. Cache reads come at a discount in Anthropic's pricing for prompt-caching scenarios, but it's not clear whether structured-output schema caching follows the same cost model. Worth measuring on the pilot run.

## Action item placement

**This is not part of WP-PROMPT-REWRITE-PYTHON-FOLLOWUPS.** The current code task is large enough already, and structured outputs is a separate workstream that should land after the rewrite stabilises. Track as a new work package: **WP-STRUCTURED-OUTPUTS** (priority Medium, depends on WP-PROMPT-REWRITE-PYTHON-FOLLOWUPS being done).
