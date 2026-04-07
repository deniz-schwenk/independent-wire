# TASK: Integrate Perspective Agent into Pipeline (WP-PERSPEKTIV)

Reference codebase for patterns: `/Users/denizschwenk/Documents/nanobot-main/` (read-only, not a dependency).

This task integrates the new Perspective Agent into the pipeline. The agent prompt already exists at `agents/perspektiv/AGENTS.md`. Do NOT modify any agent prompt files — only pipeline code.

---

## Overview of changes

The Perspective Agent sits between Researcher and Writer. It receives the Researcher's dossier (with `actors_quoted` per source), produces a stakeholder map, and feeds it to the Writer.

Pipeline order changes from:
```
Researcher → Writer → QA → [Bias Detector]
```
to:
```
Researcher → Perspective Agent → Writer → QA → [Bias Detector]
```

Additionally, `gaps` ownership moves from QA to the Perspective Agent.

---

## Change 1: Register the Perspective Agent in `scripts/run.py`

In the `create_agents()` function, add the `perspektiv` agent BETWEEN `researcher` and `writer`:

```python
"perspektiv": Agent(
    name="perspektiv",
    model="z-ai/glm-5",
    prompt_path=str(agents_dir / "perspektiv" / "AGENTS.md"),
    tools=[],
    temperature=0.1,
    provider="openrouter",
),
```

Key settings:
- **No tools** — the Perspective Agent works only with the Researcher's dossier
- **temperature=0.1** — analytical task, low creativity needed
- **glm-5** — needs strong reasoning for stakeholder synthesis

Also add `"perspektiv"` to the `--from` choices in `parse_args()`:

```python
choices=["collector", "curator", "editor", "researcher", "perspektiv", "writer", "qa_analyze"],
```

## Change 2: Rewrite the Perspective Agent call in `src/pipeline.py`

In `_produce_single()`, the existing perspektiv block (comment `# 1. Perspektiv-Agent (optional)`) runs BEFORE the researcher and passes `assignment_data` as context. This must change completely.

### Step A: Remove the OLD perspektiv block

Find and DELETE this entire block (approximately lines after `slug = ...`):

```python
# 1. Perspektiv-Agent (optional)
if perspektiv := self.agents.get("perspektiv"):
    result = await perspektiv.run(
        "Research the spectrum of perspectives on this topic.",
        context=assignment_data,
    )
    self._track_agent(result, "perspektiv", slug)
    perspectives = _extract_list(result) or []
```

Also remove the line `perspectives: list[dict] = []` near the top of `_produce_single()`.

### Step B: Add the NEW perspektiv block AFTER the researcher

After the researcher block ends (after the `await asyncio.sleep(10)` that separates researcher and writer), insert this new block:

```python
        # 2b. Perspective Agent (stakeholder mapping, no tools)
        perspective_analysis: dict = {}
        if preloaded_dossier is None and preloaded_article is None:
            if perspektiv := self.agents.get("perspektiv"):
                perspektiv_context = {
                    **assignment_data,
                    "research_dossier": research_dossier,
                }
                result = await perspektiv.run(
                    "Analyze the research dossier. Map all stakeholders, identify missing voices, "
                    "and surface framing divergences between regions and language groups.",
                    context=perspektiv_context,
                )
                perspective_analysis = _extract_dict(result) or {}
                self._track_agent(result, "perspektiv", slug)
                self._write_debug_output(f"04b-perspektiv-{slug}.json", perspective_analysis)

                # 5s delay before writer
                await asyncio.sleep(5)
```

Key details:
- `perspective_analysis` is a **dict** (not list) — the output has `stakeholders`, `missing_voices`, `framing_divergences`
- Skip if `preloaded_dossier` or `preloaded_article` is set (partial runs that skip researcher also skip perspektiv)
- Debug output goes to `04b-perspektiv-{slug}.json` (between 04-researcher and 05-writer)

### Step C: Pass perspective data to the Writer

Find the `writer_context` dict and change it to include `perspective_analysis`:

```python
# BEFORE
writer_context = {
    **assignment_data,
    "perspectives": perspectives,
    "research_dossier": research_dossier,
}

# AFTER
writer_context = {
    **assignment_data,
    "perspective_analysis": perspective_analysis,
    "research_dossier": research_dossier,
}
```

Note: the key changes from `"perspectives"` to `"perspective_analysis"` to match the new data structure.

### Step D: Update TopicPackage assembly

At the bottom of `_produce_single()`, where the TopicPackage is assembled, update the `perspectives` and `gaps` fields:

```python
# BEFORE
return TopicPackage(
    ...
    perspectives=perspectives,
    divergences=qa_analysis.get("divergences", []),
    gaps=qa_analysis.get("gaps", []),
    ...
)

# AFTER
return TopicPackage(
    ...
    perspectives=perspective_analysis.get("stakeholders", []),
    divergences=qa_analysis.get("divergences", []),
    gaps=perspective_analysis.get("missing_voices", []),
    ...
)
```

Changes:
- `perspectives` now comes from `perspective_analysis["stakeholders"]` (was empty list from old perspektiv)
- `gaps` now comes from `perspective_analysis["missing_voices"]` (was from QA)
- `divergences` stays from QA (factual divergences only)

Also add `framing_divergences` to the `transparency` dict:

```python
"framing_divergences": perspective_analysis.get("framing_divergences", []),
```

---

## Change 3: Remove `gaps` from QA-Analyze output handling

In `_produce_single()`, find the warning check for QA output. It currently checks for three fields:

```python
# BEFORE
if not qa_analysis or not any(
    qa_analysis.get(k) is not None for k in ("corrections", "divergences", "gaps")
):

# AFTER
if not qa_analysis or not any(
    qa_analysis.get(k) is not None for k in ("corrections", "divergences")
):
```

Remove `"gaps"` from the tuple — QA no longer produces gaps.

---

## Change 4: Update QA-Analyze prompt — remove `gaps`

In `agents/qa_analyze/AGENTS.md`, remove the `gaps` field from the output schema.

Find and edit the OUTPUT FORMAT section. Remove the entire `"gaps"` field specification:

```
- "gaps": Array of objects. Each has:
  - "type": One of "geographic", "demographic", "temporal", "topical".
  - "description": What is missing.
  - "significance": One of "critical", "notable", "minor".
```

Also remove the sentence: `If no corrections are needed, corrections is an empty array. Same for divergences and gaps. Do not invent problems — but be rigorous enough that genuine problems are never missed.`

Replace with: `If no corrections are needed, corrections is an empty array. Same for divergences. Do not invent problems — but be rigorous enough that genuine problems are never missed.`

Also remove the Example gap entry if one exists.

Update the first paragraph of OUTPUT FORMAT from "The object MUST have exactly these three fields:" to "The object MUST have exactly these two fields:" (corrections and divergences only).

**IMPORTANT:** Do NOT touch the RULES section of QA-Analyze. RULE 5 (Wikipedia) was just added in QF-04/P-07. Leave all rules as they are.

---

## Change 5: Update partial run support in `pipeline.py`

In `run_partial()`, the `step_order` list must include `perspektiv`:

```python
# BEFORE
step_order = ["collector", "curator", "editor", "researcher", "writer", "qa_analyze"]

# AFTER
step_order = ["collector", "curator", "editor", "researcher", "perspektiv", "writer", "qa_analyze"]
```

When `--from perspektiv` is used, the partial run should load the researcher dossier from debug output and run perspektiv + writer + qa from there.

When `--from writer` is used, perspective data is NOT loaded from debug output (it didn't exist in older runs). The writer should still work without it — `perspective_analysis` defaults to `{}`.

---

## Change 6: Update `to_dict()` in `models.py`

Add `framing_divergences` to the `transparency` section of `TopicPackage.to_dict()`. No other changes to models.py needed — the existing `perspectives`, `divergences`, and `gaps` fields already have the right types (`list[dict]`).

---

## Testing

Do NOT run the full pipeline. Write a minimal test that verifies the integration wiring:

```python
# tests/test_perspektiv_integration.py
"""Test that the Perspective Agent is correctly wired into the pipeline."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run import create_agents


def test_perspektiv_agent_registered():
    """Perspektiv agent must be in the agent registry."""
    agents = create_agents()
    assert "perspektiv" in agents


def test_perspektiv_agent_config():
    """Perspektiv agent must have no tools and low temperature."""
    agents = create_agents()
    perspektiv = agents["perspektiv"]
    assert perspektiv.tools == []
    assert perspektiv.temperature == 0.1
    assert "perspektiv" in perspektiv.prompt_path


def test_perspektiv_prompt_exists():
    """Perspektiv agent prompt file must exist."""
    prompt_path = Path(__file__).resolve().parent.parent / "agents" / "perspektiv" / "AGENTS.md"
    assert prompt_path.exists()
    content = prompt_path.read_text()
    assert "stakeholders" in content
    assert "missing_voices" in content
    assert "framing_divergences" in content
```

Run ONLY this test:

```bash
source .venv/bin/activate && source .env && python -m pytest tests/test_perspektiv_integration.py -v
```

---

## Commit and push

Single commit for all changes:

```bash
git add -A && git commit -m "feat: integrate Perspective Agent into pipeline (WP-PERSPEKTIV)

- Register perspektiv agent (glm-5, no tools, temp 0.1)
- Pipeline order: Researcher → Perspektiv → Writer
- Perspektiv receives research dossier, produces stakeholder map
- gaps ownership moved from QA to Perspektiv (missing_voices)
- QA output simplified to corrections + divergences only
- Debug output: 04b-perspektiv-{slug}.json
- Partial run support: --from perspektiv" && git push origin main
```

---

## Summary of files changed

| File | Change |
|------|--------|
| `scripts/run.py` | Add perspektiv agent, update --from choices |
| `src/pipeline.py` | Move perspektiv after researcher, pass dossier, update TopicPackage assembly, update partial run, remove gaps from QA check |
| `agents/qa_analyze/AGENTS.md` | Remove gaps from output schema (corrections + divergences only) |
| `src/models.py` | Minor: add framing_divergences to transparency in to_dict() |
| `tests/test_perspektiv_integration.py` | New: integration wiring test |

Files NOT changed (already done):
- `agents/perspektiv/AGENTS.md` — already exists
- `agents/researcher/AGENTS.md` — already updated (V2 with actors_quoted)
