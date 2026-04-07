# Independent Wire — Session Handoff (2026-04-06)

## Completed This Session

| Task | Status | Notes |
|------|--------|-------|
| WP-QA (initial) | ✅ then ♻️ | First version with Verification Card + QA-Rewrite. Worked once (Lauf 4: 2 corrections), but QA-Analyze failed 2/3 subsequent runs (truncated JSON → empty `{}`). Root cause: output too large (~5000-7000 tokens for 30-claim Verification Card). |
| QF-01 max_tokens | ✅ | Default 8192 → 32768 for all agents |
| QF-02 token tracking | ✅ | run-*-stats.json with tokens_used, duration_seconds per agent per topic |
| QF-03 silent failure | ✅ | Warning when QA-Analyze returns empty output |
| QA-Simplify | ✅ | Eliminated Verification Card from QA-Analyze output. Eliminated QA-Rewrite agent entirely. Writer handles corrections via second call. Python verifies corrections deterministically. |
| WP-QA (final) | ✅ | Lauf 5: QA-Analyze (20K tokens, 70s) + Writer-Correction (16K tokens, 32s). 1 correction found and applied, 3 divergences, 4 gaps. Reliable. |
| Writer word_count fix | ✅ | Removed word_count from Writer prompt. Pipeline computes it in Python. |

## Architecture Change: QA Simplification

### Before (complex, unreliable)
```
Writer → QA-Analyze (30 claims × Verification Card) → QA-Rewrite → [Bias Detector]
         7 agents, ~29K tokens, ~8 min, 2/3 JSON parse failures
```

### After (simple, reliable)
```
Writer → QA-Analyze (corrections + divergences + gaps only) → Writer-Correction → Python-Verify
         5 agents (+1 conditional), ~36K tokens, ~102s, 0 failures
```

### Key decisions made
- Verification Card removed: 30× "VERIFIED" entries add ~3000-4000 output tokens for near-zero information value. The real value is in corrections, divergences, and gaps.
- QA-Rewrite eliminated: Writer handles its own corrections. Fewer agents = fewer failure points.
- Python-Verify instead of LLM verify: deterministic string check confirms corrections were applied. Zero tokens, zero risk.
- article_original preserved in transparency trail when corrections are applied.

## Current Pipeline Architecture

```
RSS feeds (cron/manual)  →  raw/YYYY-MM-DD/feeds.json
                                      ↓
Collector (web_search, minimax-m2.7)  →  raw findings
                                      ↓
                              Curator (minimax-m2.7, merges RSS + Collector)
                                      ↓
                              Editor (glm-5, assigns topics)
                                      ↓
                         ┌── per topic ──────────────────┐
                         │  [Perspektiv]    (future)     │
                         │   Researcher (glm-5, multilingual search) │
                         │   Writer (glm-5, article)     │
                         │   QA-Analyze (glm-5, no tools) │
                         │   [Writer-Correction if needed] │
                         │   [Python-Verify]             │
                         │  [Bias Detector] (future)     │
                         └───────────────────────────────┘
                                      ↓
                              Topic Package JSON
```

## Debug Output Files (per topic)

```
01-collector-raw.json
02-curator-topics.json
03-editor-assignments.json
04-researcher-{slug}.json
05-writer-{slug}.json
06-qa-analyze-{slug}.json
07-writer-correction-{slug}.json  (only if corrections applied)
run-{id}-stats.json               (token tracking)
run-{id}-summary.json
```

## Known Issues / Open Items — Bald Umsetzen

| # | Type | Description | Priority |
|---|------|-------------|----------|
| QF-04 | Agent | max_tokens Default von 32768 auf **65536** erhöhen. Headroom für wachsende Dossiers. Einzeiler in `src/agent.py`. | 🔴 Nächste Session |
| P-07 | Prompt | QA-Analyze hat keine Wikipedia-Regel. Writer verbietet Wikipedia für Claims/Analyse, QA flaggt es nicht (Ungarn: src-023 war Wikipedia für Polling). RULE 5 ergänzen. | 🔴 Nächste Session |
| P-08 | Pipeline | Writer zählt Quellen systematisch falsch (25 vs 20, 29 vs 24). Python soll die Zahl im Meta-Transparenz-Absatz setzen. | 🟡 Nächste Session |
| — | Architecture | Prompt Caching via OpenRouter (GLM5-turbo, Mimo-V2-Pro). Provider-agnostisch (mit/ohne Caching, OpenRouter + Ollama). | Future |

## What Comes Next

### Priority order for next session

| Task | Impact | Effort | Notes |
|------|--------|--------|-------|
| QF-04: max_tokens 65536 | High | Tiny | Einzeiler in src/agent.py. Verhindert truncated JSON bei komplexen Topics. |
| P-07: QA Wikipedia-Regel | High | Tiny | Eine Zeile im QA-Analyze Prompt ergänzen. |
| P-08: Python source count | High | Small | Eliminates systematic Writer error. String replace in pipeline.py after Writer call. |
| Full pipeline run (Lauf 6) | High | Small | First complete run with simplified QA. All 3 topics, end-to-end. Validates full flow. |
| WP-CACHING | Medium | Medium | Prompt caching for cost reduction. Research GLM5-turbo + Mimo-V2-Pro caching behavior. |
| WP-PERSPEKTIV | Medium | Medium | Evaluate if needed — Researcher + QA divergences may cover 80% of what Perspektiv-Agent would do. |
| WP-MEMORY | Low | Small | Editor memory for coverage continuity across runs. |

### Recommendation
Start next session with QF-04 + P-07 + P-08 (three quick fixes, all high impact) → Lauf 6 (full validation run with all fixes) → then decide on WP-CACHING vs WP-PERSPEKTIV based on Lauf 6 results.

## Workflow Reminders

### Three-Role Division
| Role | Tool |
|------|------|
| **Architect** (this Claude instance) | Planning, task files, prompt review, doc updates |
| **Prompt Engineer** (separate Claude project) | Writing agent system prompts via briefing |
| **Implementer** (Claude Code) | Code implementation, testing, git commits |

### File conventions
- Task files: repo root (e.g. `TASK-QA-SIMPLIFY.md`)
- Agent prompts: `agents/{name}/AGENTS.md` — written by Architect after Prompt Engineer review
- Claude Code prompts: code boxes for copy-paste
- Task files and prompts: English. Conversation with Deniz: German.

### Key commands
- Full run: `python scripts/run.py` (~30 min, ~$0.50-1.00)
- Partial run: `python scripts/run.py --from qa_analyze --reuse 2026-04-04 --topic 2`
- Feeds: `python scripts/fetch_feeds.py`
- Tests: `source .venv/bin/activate && source .env && python -m pytest tests/ -v`
- Claude Code: `source .env && claude`

## Key Technical Facts

- **Provider:** OpenRouter with `minimax/minimax-m2.7` + `z-ai/glm-5`
- **max_tokens:** 32768 (default, pending increase to 65536 via QF-04)
- **QA-Analyze:** glm-5, no tools, temperature 0.1, output: corrections/divergences/gaps
- **Token tracking:** `output/{date}/run-*-stats.json`
- **Caching candidates:** GLM5-turbo + Mimo-V2-Pro via OpenRouter (auto-caching, provider-agnostic design needed)
- **agents/qa_rewrite/:** DELETED — no longer exists
- **Local path:** `/Users/denizschwenk/Documents/independent-wire/repo-clone/`