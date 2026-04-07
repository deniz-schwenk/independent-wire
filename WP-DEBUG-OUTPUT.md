# WP-DEBUG-OUTPUT — Step-by-Step Debug Output per Pipeline Step

## Goal

After each pipeline step, write the intermediate output as a separate JSON file so that each agent's contribution can be inspected individually. Currently everything lands in one large state file — debugging requires scrolling through 800+ lines.

## Context for Claude Code

- **Local clone:** `/Users/denizschwenk/Documents/independent-wire/repo-clone/`
- **Run tests:** `source .venv/bin/activate && source .env && python -m pytest tests/ -v`
- **Run pipeline:** `source .venv/bin/activate && source .env && python scripts/run.py`

## What to Build

Modify `Pipeline.run()` in `src/pipeline.py` to write debug output after each major step.

### Output Structure

```
output/YYYY-MM-DD/
├── 01-collector-raw.json          ← raw_findings from Collector
├── 02-curator-topics.json         ← curated_topics from Curator
├── 03-editor-assignments.json     ← assignments from Editor
├── 04-writer-tp-001.json          ← finished TopicPackage 1
├── 04-writer-tp-002.json          ← finished TopicPackage 2
├── 04-writer-tp-003.json          ← finished TopicPackage 3
├── run-summary.json               ← already exists (keep as-is)
└── tp-*.json                      ← final packages (already exist, keep as-is)
```

### Implementation

After each step in `Pipeline.run()`, write the step output to the output directory:


1. After `collect()` → write `01-collector-raw.json` (the raw_findings list)
2. After `curate()` → write `02-curator-topics.json` (the curated_topics list)
3. After `editorial_conference()` → write `03-editor-assignments.json` (the assignments list)
4. After each `_produce_single()` → write `04-writer-{topic_slug}.json` (the TopicPackage)

Use a helper method `_write_debug_output(self, filename: str, data)` that:
- Creates `output/{date}/` if needed
- Writes JSON with `indent=2, ensure_ascii=False`
- Logs: "Debug output: {filename}"

### What NOT to change

- The existing `_write_output()` method stays as-is (final packages + summary)
- The state file in `state/` stays as-is (full pipeline state for resume)
- Debug output is additive — it does not replace anything

## Files Modified

| File | Action |
|------|--------|
| `src/pipeline.py` | **Modify** — add `_write_debug_output()` helper, call it after each step |

## Definition of Done

1. After a pipeline run, `output/YYYY-MM-DD/` contains `01-collector-raw.json`, `02-curator-topics.json`, `03-editor-assignments.json`, and one `04-writer-*.json` per topic
2. Each file is valid JSON and can be inspected independently
3. All existing tests still pass
