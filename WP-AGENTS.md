# WP-AGENTS — Claude Code Task

## Task
Rename all German agent keys in the pipeline to English and wire up the new agent prompts. This is a rename + integration task, not a prompt-writing task. The prompts already exist.

## Read first
1. `/Users/denizschwenk/Documents/independent-wire/repo-clone/src/pipeline.py` — current code uses German keys
2. `/Users/denizschwenk/Documents/independent-wire/repo-clone/tests/test_pipeline.py` — tests reference agent keys
3. `/Users/denizschwenk/Documents/independent-wire/repo-clone/agents/` — the four new AGENTS.md files

## Working directory
`/Users/denizschwenk/Documents/independent-wire/repo-clone/`

## What to do

### 1. Rename agent keys in `src/pipeline.py`

Replace all occurrences:
- `"kurator"` → `"curator"`
- `"chefredaktion"` → `"editor"`
- `"redakteur"` → `"writer"`
- `"perspektiv"` → `"perspektiv"` (keep as-is for now — this agent doesn't exist yet)
- `"bias_detektor"` → `"bias_detector"`
- `"collector"` stays `"collector"`
- `"qa"` stays `"qa"`

This affects: `collect()`, `curate()`, `editorial_conference()`, `produce()`, `_produce_single()`, and any log messages that reference these names.

### 2. Update `tests/test_pipeline.py`

Update any test that references agent keys to use the new English names. The integration test `test_pipeline_collect_curate` creates agents with keys — these must match the new names.

### 3. Delete old test agent directory

Remove `agents/test/` if it exists — it was a placeholder from earlier work packages.

### 4. Verify prompt files exist

Add a simple check: assert that these files exist:
- `agents/collector/AGENTS.md`
- `agents/curator/AGENTS.md`
- `agents/editor/AGENTS.md`
- `agents/writer/AGENTS.md`

You can add this as a test in `tests/test_pipeline.py` or as a standalone check.

## Rules
- Do NOT modify the AGENTS.md prompt files — they are already written
- Do NOT change any logic in pipeline.py — only rename the string keys
- All existing tests MUST pass after the rename
- Imports and class structure stay the same

## Acceptance criteria
1. `python -m pytest tests/ -v` passes completely
2. All agent keys in pipeline.py use English names
3. No references to "kurator", "chefredaktion", or "redakteur" remain in pipeline.py or tests
4. The four AGENTS.md files exist in agents/{collector,curator,editor,writer}/

## After building
```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
source .venv/bin/activate && source .env && python -m pytest tests/ -v
git add -A
git commit -m "WP-AGENTS: English agent names + system prompts for 4 core agents

- Rename pipeline keys: kurator→curator, chefredaktion→editor, redakteur→writer, bias_detektor→bias_detector
- Agent prompts: Collector, Curator, Editor, Writer (agents/*/AGENTS.md)
- All prompts follow IDENTITY/STEPS/OUTPUT FORMAT/RULES structure
- Optimized for GLM-5 and MiniMax-M2.7 via Ollama Cloud"
git push origin main
```
