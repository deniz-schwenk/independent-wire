# TASK: Quick-Fixes QF-04, P-07, P-08

Three small, independent fixes. Each is self-contained. Commit each separately.

Reference codebase for patterns: `/Users/denizschwenk/Documents/nanobot-main/` (read-only, not a dependency).

---

## Fix 1: QF-04 — max_tokens default 32768 → 65536

**File:** `src/agent.py`

**What:** Change the default value of `max_tokens` in the `Agent.__init__` signature from `32768` to `65536`.

**Where:** Line with `max_tokens: int = 32768` in the `__init__` parameter list.

**Change:**
```python
# Before
max_tokens: int = 32768,

# After
max_tokens: int = 65536,
```

**Why:** Complex topics (30+ claims, large dossiers) can produce output near the 32K limit. 65536 gives headroom without changing behavior — models still stop when done.

**Test:** `grep -n "max_tokens" src/agent.py` should show `65536`.

**Commit message:** `fix: increase default max_tokens from 32768 to 65536 (QF-04)`

---

## Fix 2: P-07 — QA-Analyze Wikipedia rule

**File:** `agents/qa_analyze/AGENTS.md`

**What:** Add RULE 5 that tells QA-Analyze to flag Wikipedia citations used for current events, claims, or analysis.

**Where:** After `RULE 4 — OUTPUT ONLY JSON.` at the end of the `# RULES` section, add:

```
RULE 5 — FLAG WIKIPEDIA MISUSE. If the article cites Wikipedia (or any wiki) as a source for current events, claims, statistics, or analysis, flag it as a correction with problem type "unsupported_claim". Wikipedia is acceptable ONLY for verifiable background facts (population figures, geography, historical dates). For anything else, it must be flagged. This mirrors the Writer's editorial policy — your job is to catch cases where the Writer violated it.
```

**Why:** In Lauf 5, QA-Analyze did not flag a Wikipedia source (src-023) used for current polling data on Hungary. The Writer has this rule (see `agents/writer/AGENTS.md`, last paragraph), but QA-Analyze has no corresponding check.

**Test:** `grep -c "Wikipedia" agents/qa_analyze/AGENTS.md` should return at least 1.

**Commit message:** `fix: add Wikipedia misuse rule to QA-Analyze prompt (P-07)`

---

## Fix 3: P-08 — Python source count in meta-transparency

**File:** `src/pipeline.py`

**What:** After the Writer produces an article, Python should fix the meta-transparency paragraph's source count and language count. The Writer systematically miscounts (e.g. writes "25 sources" when there are 20).

**Where:** In `_produce_single()`, immediately AFTER the line:

```python
article["word_count"] = len(body_text.split())
```

(the FIRST occurrence, right after the Writer call — NOT the second one after Writer-Correction)

**Add this code:**

```python
# Fix meta-transparency source/language counts (Writer miscounts systematically)
body = article.get("body", "")
writer_sources = article.get("sources", [])
if body and writer_sources:
    actual_count = len(writer_sources)
    langs = {s.get("language", "") for s in writer_sources if s.get("language")}
    actual_langs = len(langs)

    # Pattern: "This report draws on N sources in M languages"
    # Also matches variants like "This article draws on..."
    import re as _re
    pattern = _re.compile(
        r"(This (?:report|article|analysis) draws on )\d+( sources in )\d+( languages?)"
    )
    new_body = pattern.sub(
        rf"\g<1>{actual_count}\g<2>{actual_langs}\3",
        body,
    )
    if new_body != body:
        article["body"] = new_body
        logger.info(
            "Fixed meta-transparency: %d sources in %d languages for '%s'",
            actual_count,
            actual_langs,
            assignment.title,
        )
```

**Important:** The `import re` is already at the top of `pipeline.py` — use `re` directly instead of `_re`. I wrote `_re` above to avoid shadowing. Since `re` is already imported at module level, the code should be:

```python
meta_pattern = re.compile(
    r"(This (?:report|article|analysis) draws on )\d+( sources in )\d+( languages?)"
)
new_body = meta_pattern.sub(
    rf"\g<1>{actual_count}\g<2>{actual_langs}\3",
    body,
)
```

**Also:** Apply the same fix AGAIN after the Writer-Correction block (after the second `article["word_count"] = ...` line), because corrections may re-introduce wrong counts. Same logic, same pattern.

**Why:** The Writer consistently reports wrong source counts in the meta-transparency paragraph. Python knows the exact count from `article["sources"]`. This is deterministic — zero LLM tokens, zero risk.

**Test:** Run `python -c "import re; pattern = re.compile(r'(This (?:report|article|analysis) draws on )\d+( sources in )\d+( languages?)'); result = pattern.sub(r'\g<1>20\g<2>3\3', 'This report draws on 25 sources in 4 languages'); print(result)"` — should output `This report draws on 20 sources in 3 languages`.

**Commit message:** `fix: Python fixes meta-transparency source count after Writer (P-08)`

---

## After all three fixes

Write a small test file `tests/test_meta_transparency_fix.py` that verifies P-08's regex logic works. No pipeline run, no API calls — pure string logic.

```python
"""Test the meta-transparency source count fix (P-08)."""
import re


META_PATTERN = re.compile(
    r"(This (?:report|article|analysis) draws on )\d+( sources in )\d+( languages?)"
)


def _fix_meta_counts(body: str, actual_count: int, actual_langs: int) -> str:
    return META_PATTERN.sub(
        rf"\g<1>{actual_count}\g<2>{actual_langs}\3",
        body,
    )


def test_basic_replacement():
    body = "Some text. This report draws on 25 sources in 4 languages. More text."
    result = _fix_meta_counts(body, 20, 3)
    assert "This report draws on 20 sources in 3 languages" in result


def test_article_variant():
    body = "This article draws on 29 sources in 5 languages."
    result = _fix_meta_counts(body, 24, 3)
    assert "This article draws on 24 sources in 3 languages" in result


def test_analysis_variant():
    body = "This analysis draws on 12 sources in 2 languages."
    result = _fix_meta_counts(body, 12, 2)
    assert "This analysis draws on 12 sources in 2 languages" in result


def test_no_match_unchanged():
    body = "This paragraph has no meta-transparency statement."
    result = _fix_meta_counts(body, 5, 2)
    assert result == body


def test_singular_language():
    body = "This report draws on 8 sources in 1 language."
    result = _fix_meta_counts(body, 6, 1)
    assert "This report draws on 6 sources in 1 language" in result
```

Run ONLY this test:

```bash
source .venv/bin/activate && python -m pytest tests/test_meta_transparency_fix.py -v
```

Do NOT run the full test suite or any pipeline tests. Then push:

```bash
git add -A && git push origin main
```
