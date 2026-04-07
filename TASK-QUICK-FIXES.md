# TASK-QUICK-FIXES.md — QF-01, QF-02, QF-03

**Created:** 2026-04-05
**Scope:** Three small fixes, no new agents, no prompt changes.

---

## QF-01: max_tokens Default auf 32768

### Problem
Der Agent-Default `max_tokens=8192` reicht nicht für Single-Response-Agents mit großem JSON-Output. QA-Analyze hat bei 8192 truncated JSON produziert → silent failure.

### Fix
In `src/agent.py`: Default `max_tokens` von 8192 auf **32768** ändern.

Außerdem in `scripts/run.py`: Die expliziten `max_tokens=16384` Overrides für qa_analyze und qa_rewrite entfernen — sie erben jetzt den neuen Default.

---

## QF-02: Token-Tracking persistieren

### Problem
`tokens_used`, `duration_seconds` und `model` aus AgentResult werden nur in die Console geloggt, nicht persistiert. Keine Möglichkeit, Kosten pro Lauf nachzuvollziehen.

### Fix
In `src/pipeline.py`: Nach jedem Agent-Call die Metriken sammeln und am Ende des Laufs als `run-stats.json` in den Output-Ordner schreiben.

Struktur:

```json
{
  "run_id": "run-2026-04-05-abc123",
  "date": "2026-04-05",
  "agents": [
    {
      "agent": "collector",
      "topic": null,
      "tokens_used": 4521,
      "duration_seconds": 45.2,
      "model": "minimax/minimax-m2.7"
    },
    {
      "agent": "qa_analyze",
      "topic": "us-israel-iran-conflict",
      "tokens_used": 21000,
      "duration_seconds": 386.2,
      "model": "z-ai/glm-5"
    }
  ],
  "total_tokens": 85000,
  "total_duration_seconds": 1800.5
}
```

Implementierung: Der einfachste Weg ist eine Liste `self._agent_stats: list[dict]` auf der Pipeline-Instanz. Nach jedem `agent.run()` Call ein dict appenden:

```python
self._agent_stats.append({
    "agent": agent.name,
    "topic": slug or None,
    "tokens_used": result.tokens_used,
    "duration_seconds": result.duration_seconds,
    "model": result.model,
})
```

In `_write_output()` am Ende die Stats schreiben:

```python
stats_path = out / f"{self.state.run_id}-stats.json"
stats = {
    "run_id": self.state.run_id,
    "date": self.state.date,
    "agents": self._agent_stats,
    "total_tokens": sum(s["tokens_used"] for s in self._agent_stats),
    "total_duration_seconds": sum(s["duration_seconds"] for s in self._agent_stats),
}
stats_path.write_text(json.dumps(stats, indent=2))
```

---

## QF-03: Silent-failure Warning für leere QA-Outputs

### Problem
Wenn QA-Analyze ein leeres `{}` liefert (z.B. wegen truncated JSON), meldet die Pipeline trotzdem Erfolg. Der Fehler ist nur in den Debug-Files erkennbar.

### Fix
In `_produce_single()`, nach dem QA-Analyze Call:

```python
if qa_analysis and not qa_analysis.get("verification_card"):
    logger.warning(
        "QA-Analyze for '%s' returned no verification_card — output may be truncated or empty. "
        "Check debug file 06-qa-analyze-*.json.",
        assignment.title,
    )
```

Gleiche Prüfung für QA-Rewrite:

```python
if qa_rewrite_output and not qa_rewrite_output.get("body"):
    logger.warning(
        "QA-Rewrite for '%s' returned no body — output may be truncated. "
        "Check debug file 07-qa-rewrite-*.json.",
        assignment.title,
    )
```

---

## Betroffene Dateien

- `src/agent.py` — max_tokens Default ändern
- `src/pipeline.py` — Token-Stats sammeln + schreiben, QA-Warnings
- `scripts/run.py` — explizite max_tokens Overrides entfernen

## Testing

```bash
source .venv/bin/activate && source .env && python scripts/run.py --from qa_analyze --reuse 2026-04-05 --topic 1
```

Prüfen:
1. `output/{date}/run-*-stats.json` existiert und enthält Token-Zahlen für qa_analyze + qa_rewrite
2. Kein expliziter max_tokens Override mehr in run.py für QA-Agents
3. Bei leerem QA-Output erscheint Warning in Logs

## Claude Code prompt

```
Read TASK-QUICK-FIXES.md and implement all three fixes (QF-01, QF-02, QF-03). Read src/agent.py, src/pipeline.py, and scripts/run.py before starting. Test with: python scripts/run.py --from qa_analyze --reuse 2026-04-05 --topic 1. After the run, verify that output/{date}/run-*-stats.json exists and contains token data.
```