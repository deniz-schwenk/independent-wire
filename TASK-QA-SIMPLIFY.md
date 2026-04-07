# TASK-QA-SIMPLIFY.md — Vereinfachung QA-Pipeline

**Created:** 2026-04-06
**Scope:** QA-Rewrite eliminieren, QA-Analyze vereinfacht (schon erledigt), Writer-Correction-Call + Python-Verify einbauen.

**WICHTIG: Dieses Task ersetzt Teile von WP-QA. Der QA-Analyze Prompt wurde bereits vereinfacht (agents/qa_analyze/AGENTS.md). Lies ihn zuerst.**

---

## Überblick: Neuer QA-Flow

```
Writer → QA-Analyze → [wenn corrections nicht leer] → Writer-Correction → Python-Verify
```

Vorher: 2 eigene QA-Agents (QA-Analyze + QA-Rewrite)
Nachher: 1 QA-Agent (QA-Analyze) + 1 zusätzlicher Writer-Call + Python-Check

---

## Task 1: QA-Rewrite Agent entfernen

In `scripts/run.py`:
- Die `"qa_rewrite"` Agent-Definition aus `create_agents()` entfernen.

In `scripts/run.py` CLI:
- `"qa_rewrite"` aus den `--from` choices entfernen. `"qa_analyze"` bleibt.

---

## Task 2: _produce_single() in pipeline.py umbauen

Die aktuelle QA-Logik (QA-Analyze → conditional QA-Rewrite) wird ersetzt durch:

### Schritt 1: QA-Analyze (vereinfacht)

```python
# 4. QA-Analyze (find errors, divergences, gaps)
qa_analysis: dict = {}
if qa_analyze := self.agents.get("qa_analyze"):
    qa_context = {
        "article": article,
        "research_dossier": research_dossier,
    }
    result = await qa_analyze.run(
        "Review this article against the available sources. Find factual errors, "
        "source divergences the article doesn't reflect, and coverage gaps.",
        context=qa_context,
    )
    qa_analysis = _extract_dict(result) or {}
    slug = assignment.topic_slug or assignment.id
    self._write_debug_output(f"06-qa-analyze-{slug}.json", qa_analysis)

    # QF-03: Warning if QA-Analyze returned empty
    if qa_analysis and not qa_analysis.get("corrections") and not qa_analysis.get("divergences"):
        logger.warning(
            "QA-Analyze for '%s' returned no corrections and no divergences — "
            "output may be truncated. Check debug file.",
            assignment.title,
        )
```

### Schritt 2: Writer-Correction (conditional)

Wenn QA-Analyze Korrekturen gefunden hat, bekommt der **existierende Writer-Agent** einen zweiten Call:

```python
# 5. Writer-Correction (nur wenn Korrekturen nötig)
corrections = qa_analysis.get("corrections", [])
article_original = article.get("body", "")

if corrections and (writer := self.agents.get("writer")):
    await asyncio.sleep(10)  # Rate limit

    correction_context = {
        "task": "correction",
        "original_article": article,
        "corrections": corrections,
    }
    result = await writer.run(
        "You wrote this article. QA found factual errors that need correction. "
        "Apply ONLY the listed corrections to the article. Return the complete "
        "article JSON (headline, subheadline, body, summary, sources) with the "
        "corrections applied. Do not change anything else.",
        context=correction_context,
    )
    corrected = _extract_dict(result) or {}
    slug = assignment.topic_slug or assignment.id
    self._write_debug_output(f"07-writer-correction-{slug}.json", corrected)

    # Merge corrected fields into article
    if corrected.get("body"):
        article["body"] = corrected["body"]
    if corrected.get("headline"):
        article["headline"] = corrected["headline"]
    if corrected.get("subheadline"):
        article["subheadline"] = corrected["subheadline"]
    if corrected.get("summary"):
        article["summary"] = corrected["summary"]
```

### Schritt 3: Python-Verify (deterministisch)

```python
    # 6. Deterministic verification — check corrections were applied
    applied = 0
    not_applied = []
    for correction in corrections:
        excerpt = correction.get("article_excerpt", "")
        if excerpt and excerpt not in article.get("body", ""):
            applied += 1
        elif excerpt:
            not_applied.append(excerpt[:80])

    if not_applied:
        logger.warning(
            "Writer-Correction for '%s': %d/%d corrections NOT applied: %s",
            assignment.title,
            len(not_applied),
            len(corrections),
            not_applied,
        )
    else:
        logger.info(
            "Writer-Correction for '%s': all %d corrections applied.",
            assignment.title,
            len(corrections),
        )
```

### Schritt 4: word_count in Python

```python
# Compute word_count in Python (never trust LLM counting)
article["word_count"] = len(article.get("body", "").split())
```

---

## Task 3: TopicPackage Assembly updaten

```python
# Assemble TopicPackage
return TopicPackage(
    id=assignment.id,
    metadata={...},  # unchanged
    sources=article.get("sources", []),
    perspectives=perspectives,
    divergences=qa_analysis.get("divergences", []),
    gaps=qa_analysis.get("gaps", []),
    article=article,
    bias_analysis=bias_analysis,
    transparency={
        "selection_reason": assignment.selection_reason,
        "confidence": "medium",
        "pipeline_run": {
            "run_id": self.state.run_id if self.state else "",
            "date": self.state.date if self.state else "",
        },
        "article_original": article_original if corrections else None,
        "qa_corrections": corrections,
        "qa_corrections_applied": applied if corrections else 0,
    },
    status="review",
)
```

Keine verification_card mehr. Keine qa_summary mehr. Stattdessen:
- `article_original`: nur gesetzt wenn Korrekturen angewandt wurden
- `qa_corrections`: die Korrekturliste von QA-Analyze
- `qa_corrections_applied`: wie viele Korrekturen umgesetzt wurden

---

## Task 4: Partial-Run-Support anpassen

In `run_partial()`:
- `"qa_rewrite"` aus `step_order` entfernen
- Für `--from qa_analyze`: Writer-Output laden (wie bisher)
- Die Logik für `--from qa_rewrite` komplett entfernen

Neuer step_order:
```python
step_order = ["collector", "curator", "editor", "researcher", "writer", "qa_analyze"]
```

---

## Task 5: Aufräumen

- `agents/qa_rewrite/` Verzeichnis löschen (der Agent existiert nicht mehr)
- In pipeline.py: alle Referenzen auf `qa_rewrite`, `qa_rewrite_output`, `preloaded_qa_analysis` entfernen

---

## Betroffene Dateien

- `agents/qa_analyze/AGENTS.md` — BEREITS AKTUALISIERT, NICHT ÄNDERN
- `agents/qa_rewrite/` — LÖSCHEN
- `src/pipeline.py` — QA-Logik umbauen
- `scripts/run.py` — qa_rewrite Agent entfernen, CLI choices anpassen

## Testing

```bash
source .venv/bin/activate && source .env && python scripts/run.py --from qa_analyze --reuse 2026-04-05 --topic 1
```

Prüfen:
1. `06-qa-analyze-*.json` enthält corrections, divergences, gaps (KEINE verification_card)
2. Wenn Korrekturen gefunden: `07-writer-correction-*.json` existiert
3. Logs zeigen "all N corrections applied" oder Warning wenn nicht
4. `agents/qa_rewrite/` existiert nicht mehr
5. `run-*-stats.json` zeigt Token-Verbrauch für qa_analyze und ggf. writer (correction)

## Claude Code prompt

```
Read TASK-QA-SIMPLIFY.md and implement the changes. Read agents/qa_analyze/AGENTS.md first to understand the new simplified output format. Do NOT modify agents/qa_analyze/AGENTS.md — it is already updated. Delete agents/qa_rewrite/ directory. Test with: python scripts/run.py --from qa_analyze --reuse 2026-04-05 --topic 1
```