# WP-QA — Quality Assurance Agent (Two-Step: Analyze + Rewrite)

**Created:** 2026-04-05
**Depends on:** WP-RESEARCH, WP-PARTIAL-RUN
**Scope:** Add QA-Analyze and QA-Rewrite agents to the pipeline between Writer and Bias Detector. Fix word_count to be computed by Python, not LLM.

---

## Overview

QA runs as two sequential agent calls per topic inside `_produce_single()`:

1. **QA-Analyze** (glm-5, no tools): Verifies every factual claim against Writer sources + Researcher dossier. Produces verification_card, divergences, gaps, corrections list.
2. **QA-Rewrite** (glm-5, no tools): Applies corrections to article text. Produces corrected body + final verification_card + qa_summary.

Pipeline code handles assembly: article_original, sources pass-through, word_count calculation, merging divergences/gaps into TopicPackage.

## Reference Files — Read These First

```
agents/qa_analyze/AGENTS.md      — QA-Analyze system prompt (already written)
agents/qa_rewrite/AGENTS.md      — QA-Rewrite system prompt (already written)
agents/researcher/AGENTS.md      — Reference for how agents integrate
agents/writer/AGENTS.md          — Writer prompt (word_count field removed)
src/pipeline.py                  — Current pipeline with _produce_single()
src/models.py                    — TopicPackage, TopicAssignment models
scripts/run.py                   — Agent creation and CLI
/Users/denizschwenk/Documents/nanobot-main/nanobot/agent/loop.py — Reference for agent loop patterns
```

---

## Task 1: Add QA agents to run.py

In `create_agents()`, add two new agents after "writer":

```python
"qa_analyze": Agent(
    name="qa_analyze",
    model="z-ai/glm-5",
    prompt_path=str(agents_dir / "qa_analyze" / "AGENTS.md"),
    tools=[],
    temperature=0.1,
    provider="openrouter",
),
"qa_rewrite": Agent(
    name="qa_rewrite",
    model="z-ai/glm-5",
    prompt_path=str(agents_dir / "qa_rewrite" / "AGENTS.md"),
    tools=[],
    temperature=0.1,
    provider="openrouter",
),
```

Low temperature (0.1) because QA must be precise and conservative.

---

## Task 2: Modify _produce_single() in pipeline.py
Replace the current QA and Bias Detector sections in `_produce_single()`. The new order inside the method MUST be:

1. Perspektiv-Agent (optional, unchanged)
2. Researcher (unchanged)
3. Writer (unchanged)
4. **QA-Analyze (new)**
5. **QA-Rewrite (new, only if corrections exist)**
6. Bias Detector (optional, unchanged — but moves AFTER QA)

### QA-Analyze call

```python
# 4. QA-Analyze (verify all claims)
qa_analysis: dict = {}
if qa_analyze := self.agents.get("qa_analyze"):
    qa_context = {
        "article": article,           # Writer's output (headline, subheadline, body, summary, sources)
        "research_dossier": research_dossier,  # Researcher's dossier with rsrc-NNN sources
    }
    result = await qa_analyze.run(
        "Verify every factual claim in this article against the available sources.",
        context=qa_context,
    )
    qa_analysis = _extract_dict(result) or {}
    slug = assignment.topic_slug or assignment.id
    self._write_debug_output(f"06-qa-analyze-{slug}.json", qa_analysis)
```

### QA-Rewrite call (conditional)

```python
# 5. QA-Rewrite (apply corrections, only if needed)
corrected_article = article.copy()
qa_rewrite_output: dict = {}
corrections = qa_analysis.get("corrections", [])

if corrections and (qa_rewrite := self.agents.get("qa_rewrite")):
    # 10s delay to avoid rate limits
    await asyncio.sleep(10)

    rewrite_context = {
        "article": article,        # Writer's original
        "qa_analysis": qa_analysis, # QA-Analyze output with corrections list
    }
    result = await qa_rewrite.run(
        "Apply the corrections to the article text and produce the final verification card.",
        context=rewrite_context,
    )
    qa_rewrite_output = _extract_dict(result) or {}
    slug = assignment.topic_slug or assignment.id
    self._write_debug_output(f"07-qa-rewrite-{slug}.json", qa_rewrite_output)

    # Merge: QA-Rewrite body replaces Writer body
    if qa_rewrite_output.get("body"):
        corrected_article["body"] = qa_rewrite_output["body"]
    if qa_rewrite_output.get("headline"):
        corrected_article["headline"] = qa_rewrite_output["headline"]
    if qa_rewrite_output.get("subheadline"):
        corrected_article["subheadline"] = qa_rewrite_output["subheadline"]
    if qa_rewrite_output.get("summary"):
        corrected_article["summary"] = qa_rewrite_output["summary"]
```

### Assembly logic (after QA, before Bias Detector)

```python
# Compute word_count in Python (never trust LLM counting)
body_text = corrected_article.get("body", "")
corrected_article["word_count"] = len(body_text.split())

# Preserve original article text for transparency
article_original = article.get("body", "")
```

---

## Task 3: Update TopicPackage assembly

In the TopicPackage construction at the end of `_produce_single()`, update these fields:

```python
# Use corrected article (falls back to original if no QA ran)
article=corrected_article,

# Sources come from Writer (QA does not modify sources)
sources=corrected_article.get("sources", []),

# Divergences and gaps come from QA-Analyze (or empty)
divergences=qa_analysis.get("divergences", []),
gaps=qa_analysis.get("gaps", []),

# Add to transparency
transparency={
    "selection_reason": assignment.selection_reason,
    "confidence": "medium",
    "pipeline_run": {
        "run_id": self.state.run_id if self.state else "",
        "date": self.state.date if self.state else "",
    },
    "article_original": article_original,
    "verification_card": (
        qa_rewrite_output.get("verification_card")
        or qa_analysis.get("verification_card", [])
    ),
    "qa_summary": (
        qa_rewrite_output.get("qa_summary")
        or qa_analysis.get("qa_summary", {})
    ),
},
```

Note: If no corrections were needed, verification_card comes from QA-Analyze directly.
---

## Task 4: Fix word_count for Writer output

The Writer prompt no longer produces a word_count field. Add Python calculation AFTER the Writer call in `_produce_single()`:

```python
# After writer result is parsed into article dict:
body_text = article.get("body", "")
article["word_count"] = len(body_text.split())
```

This ensures word_count is always accurate regardless of what the LLM returns.

Also: if the Writer still returns a word_count field in its JSON, that's fine — the Python calculation overwrites it.

---

## Task 5: Partial run support

### Update CLI choices in run.py

Add `qa_analyze` and `qa_rewrite` to the `--from` choices:

```python
choices=["collector", "curator", "editor", "researcher", "writer", "qa_analyze", "qa_rewrite"],
```

### Update step_order in run_partial()

```python
step_order = ["collector", "curator", "editor", "researcher", "writer", "qa_analyze", "qa_rewrite"]
```

### Load debug data for partial QA runs

When `--from qa_analyze`: load 03-editor-assignments.json + 04-researcher-{slug}.json + 05-writer-{slug}.json
When `--from qa_rewrite`: load all above + 06-qa-analyze-{slug}.json

The pattern matches what already exists for `--from writer` (loading researcher dossiers). Add equivalent loading for Writer output and QA-Analyze output.

For `--from qa_analyze`:
```python
# Load writer output
writer_outputs: dict[str, dict] = {}
for assignment in assignments:
    slug = assignment.topic_slug or assignment.id
    filename = f"05-writer-{slug}.json"
    writer_data = self._load_debug_output(reuse, filename)
    if writer_data and isinstance(writer_data, dict):
        writer_outputs[slug] = writer_data
```

For `--from qa_rewrite`, additionally load:
```python
# Load QA-Analyze output
qa_analyze_outputs: dict[str, dict] = {}
for assignment in assignments:
    slug = assignment.topic_slug or assignment.id
    filename = f"06-qa-analyze-{slug}.json"
    qa_data = self._load_debug_output(reuse, filename)
    if qa_data and isinstance(qa_data, dict):
        qa_analyze_outputs[slug] = qa_data
```

---

## Task 6: Remove old QA placeholder

In `_produce_single()`, DELETE the existing QA placeholder code:

```python
# DELETE THIS BLOCK:
# 4. QA/Faktencheck (optional)
if qa := self.agents.get("qa"):
    result = await qa.run(
        "Verify all factual claims in this article.",
        context={"article": article, "sources": sources},
    )
    sources = _extract_list(result) or []
```

Also MOVE the Bias Detector block to run AFTER QA-Rewrite, not before it.

---

## Task 7: Testing

### Quick test (partial run, ~2-4 min, ~$0.10)

```bash
source .venv/bin/activate && source .env && python scripts/run.py --from qa_analyze --reuse 2026-04-05 --topic 1
```

This loads the Writer output from Lauf 3 and runs only QA-Analyze + QA-Rewrite on the first topic.

### Verify results

1. Check `output/{date}/06-qa-analyze-{slug}.json` exists and contains:
   - `verification_card` with entries for every claim
   - `divergences` array (may be empty)
   - `gaps` array (may be empty)
   - `corrections` array
   - `qa_summary` with matching counts

2. If corrections were found, check `output/{date}/07-qa-rewrite-{slug}.json`:
   - `body` contains corrected text
   - `verification_card` has updated entries for corrected claims
   - `qa_summary.corrections_applied` matches corrections count

3. Check final TopicPackage JSON:
   - `article.word_count` is a reasonable integer (600-1200)
   - `article.body` matches QA-Rewrite output (or Writer output if no corrections)
   - `transparency.article_original` contains Writer's original body
   - `transparency.verification_card` exists
   - `divergences` and `gaps` are populated (not empty arrays like before)

### Edge case test

If QA-Analyze returns an empty corrections array, QA-Rewrite should be SKIPPED entirely (no API call). Verify this by checking logs — there should be no "qa_rewrite" log entries when corrections are empty.

---

## Important constraints

- **DO NOT modify agent prompts.** The prompts in agents/qa_analyze/AGENTS.md and agents/qa_rewrite/AGENTS.md are finalized. Read them to understand input/output contracts, but do not edit them.
- **DO NOT modify the Writer prompt** (agents/writer/AGENTS.md). The word_count field has already been removed from it. The fix goes in pipeline.py only.
- **Rate limits:** Add 10s delay between QA-Analyze and QA-Rewrite calls (same pattern as researcher→writer delay).
- **Debug output filenames:** Use `06-qa-analyze-{slug}.json` and `07-qa-rewrite-{slug}.json` to maintain the numbered sequence.

---

## Claude Code prompt

```
Read WP-QA.md and implement the work package. Read all referenced files before you start, especially the two QA agent prompts (agents/qa_analyze/AGENTS.md and agents/qa_rewrite/AGENTS.md) and the current pipeline code (src/pipeline.py, scripts/run.py, src/models.py). Do NOT modify any agent prompts. Test with: python scripts/run.py --from qa_analyze --reuse 2026-04-05 --topic 1
```