# WP-PARTIAL-RUN — Skip Early Pipeline Steps for Faster Development

## Goal

Add CLI flags to `scripts/run.py` that let the pipeline start from any step, reusing debug output from a previous run. This avoids re-running Collector, Curator, and Editor when only testing Researcher or Writer changes — saving ~10 minutes and ~$0.20 per iteration.

## The Problem

Every pipeline test currently runs all 5 steps (collect → curate → edit → research → write), even when the change only affects the Researcher or Writer prompt. A full run takes ~30 minutes and costs ~$0.50-1.00. During prompt development, you might iterate 5-10 times — that's 2.5-5 hours and $2.50-10.00 for changes that only need the last 1-2 steps.

## Design

### CLI Interface

```bash
# Full run (default, unchanged behavior)
python scripts/run.py

# Start from researcher — loads collector/curator/editor output from last run
python scripts/run.py --from researcher

# Start from writer — loads everything up to and including researcher
python scripts/run.py --from writer

# Only process one topic (by index: 1, 2, or 3)
python scripts/run.py --from researcher --topic 1

# Use debug output from a specific date (default: latest available)
python scripts/run.py --from researcher --reuse 2026-04-04

# Combine: test only the writer on topic 2, using yesterday's data
python scripts/run.py --from writer --topic 2 --reuse 2026-04-04
```

### Valid `--from` values

| Value | Skips | Loads from debug | Runs |
|-------|-------|-----------------|------|
| `collector` | nothing | nothing | collect → curate → edit → research → write |
| `curator` | collect | `01-collector-raw.json` | curate → edit → research → write |
| `editor` | collect, curate | `01-collector-raw.json`, `02-curator-topics.json` | edit → research → write |
| `researcher` | collect, curate, edit | `03-editor-assignments.json` | research → write |
| `writer` | collect, curate, edit, research | `03-editor-assignments.json` + `04-researcher-*.json` | write only |

### How it works

The debug output files already exist in `output/YYYY-MM-DD/`. They contain the exact data each step produced. To skip steps:

1. Find the latest (or specified) output directory
2. Load the debug JSON files for all steps before `--from`
3. Inject them into the pipeline state as if those steps ran
4. Execute only the remaining steps

## What to implement

### 1. Add argparse to `scripts/run.py`

```python
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Independent Wire pipeline")
    parser.add_argument(
        "--from", dest="from_step", default=None,
        choices=["collector", "curator", "editor", "researcher", "writer"],
        help="Start from this step, loading earlier steps from debug output"
    )
    parser.add_argument(
        "--topic", type=int, default=None,
        help="Only process this topic number (1-based index)"
    )
    parser.add_argument(
        "--reuse", type=str, default=None,
        help="Date to load debug output from (YYYY-MM-DD). Default: latest available"
    )
    return parser.parse_args()
```

### 2. Add a data-loading helper to Pipeline

Add a method to Pipeline that loads debug output from a previous run:

```python
def _load_debug_output(self, date: str, filename: str) -> dict | list | None:
    """Load a debug output file from a previous run."""
    path = Path(self.output_dir) / date / filename
    if not path.exists():
        logger.error("Debug file not found: %s", path)
        return None
    return json.loads(path.read_text(encoding="utf-8"))
```

### 3. Add `run_partial()` to Pipeline

Add a new method that handles partial runs:

```python
async def run_partial(
    self,
    from_step: str,
    date: str | None = None,
    topic_filter: int | None = None,
    reuse_date: str | None = None,
) -> list[TopicPackage]:
    """Run pipeline from a specific step, loading earlier data from debug output."""
```

Key logic:
- Determine `reuse_date`: use `--reuse` value, or find the latest directory in `output/`
- Based on `from_step`, load the required debug files
- For `--from researcher`: load `03-editor-assignments.json`, create assignments
- For `--from writer`: load `03-editor-assignments.json` + all `04-researcher-*.json` files
- If `--topic N` is set: filter assignments to only the Nth entry (1-based)
- Run only the remaining pipeline steps
- Still write debug output and final topic packages as normal

### 4. Loading researcher output for `--from writer`

This is the trickiest part. The researcher output is per-topic, with slug in the filename. The loading logic needs to:

1. Load `03-editor-assignments.json` to get the topic list
2. For each assignment, find the matching `04-researcher-{slug}.json`
3. Pass each researcher dossier as context to the writer

The slug matching can use the `topic_slug` field from the assignment, which should match the filename pattern.

### 5. Wire it up in `main()`

```python
async def main():
    args = parse_args()
    # ... setup ...
    
    if args.from_step:
        packages = await pipeline.run_partial(
            from_step=args.from_step,
            topic_filter=args.topic,
            reuse_date=args.reuse,
        )
    else:
        packages = await pipeline.run()
```

### 6. Find latest output directory helper

```python
def _find_latest_output_date(self) -> str | None:
    """Find the most recent date directory in output/."""
    out = Path(self.output_dir)
    if not out.exists():
        return None
    dates = sorted([d.name for d in out.iterdir() if d.is_dir() and d.name[:4].isdigit()])
    return dates[-1] if dates else None
```

## What NOT to do

- Do NOT change the full `pipeline.run()` method — partial run is a separate code path
- Do NOT change debug output format or filenames
- Do NOT change agent prompts
- Do NOT add new dependencies
- Do NOT modify the Agent class

## How to test

### Test 1: `--from researcher` should skip collect/curate/edit
```bash
cd /Users/denizschwenk/Documents/independent-wire/repo-clone
source .venv/bin/activate && source .env
python scripts/run.py --from researcher --reuse 2026-04-04 --topic 1
```
Expected: Pipeline loads editor assignments from 2026-04-04, runs researcher + writer for topic 1 only. Should take ~10 min instead of 30.

### Test 2: `--from writer` should skip everything before writer
```bash
python scripts/run.py --from writer --reuse 2026-04-04 --topic 1
```
Expected: Loads assignments + researcher dossier, runs only writer. Should take ~3-5 min.

### Test 3: `--help` shows all options
```bash
python scripts/run.py --help
```

### Test 4: full run is NOT broken (verify by reading code only)
Do NOT run a full pipeline to test this. Verify by code review that `run.py` without flags still calls `pipeline.run()` unchanged. A full run costs ~$0.50 and is not needed to validate this change.

## Expected impact

| Scenario | Before | After |
|----------|--------|-------|
| Test researcher prompt change | 30 min, ~$0.50 | 15 min, ~$0.25 |
| Test writer prompt change | 30 min, ~$0.50 | 5 min, ~$0.10 |
| Test writer on single topic | 30 min, ~$0.50 | 3 min, ~$0.05 |
| Full pipeline run | 30 min | 30 min (unchanged) |

## Reference

- Debug output files: `output/YYYY-MM-DD/01-collector-raw.json` through `05-writer-*.json`
- Pipeline state: `state/run-YYYY-MM-DD-*.json`
- Current `run.py`: `scripts/run.py` (~120 lines)
- Current `pipeline.py`: `src/pipeline.py` (~550 lines, `_produce_single()` at line ~290)
