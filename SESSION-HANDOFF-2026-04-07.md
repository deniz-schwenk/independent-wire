# Independent Wire — Session Handoff (2026-04-07)

## Completed This Session

| Task | Status | Notes |
|------|--------|-------|
| QF-04 max_tokens | ✅ | Default 32768 → 65536 in agent.py |
| P-07 QA Wikipedia rule | ✅ | RULE 5 added to QA-Analyze prompt |
| P-08 Python source count | ✅ | Regex fixes meta-transparency counts after Writer + after Writer-Correction |
| QF-05 JSON repair | ✅ | `_parse_json` in agent.py now handles: prose around JSON, trailing commas, truncated brackets |
| QF-06 dead binding | ✅ | Removed unused `sources` variable in `_produce_single()` |
| WP-RESEARCHER-V2 | ✅ | Researcher prompt extended with `actors_quoted` per source (name, role, type, position) |
| WP-PERSPEKTIV prompt | ✅ | New agent prompt at `agents/perspektiv/AGENTS.md` |
| WP-PERSPEKTIV integration | ✅ | Pipeline wiring: perspektiv agent registered, pipeline order updated, gaps ownership moved from QA to Perspektiv |
| WP-WRITER-V2 | ✅ | Writer prompt extended to use perspective_analysis (stakeholder map, missing voices, framing divergences) |
| QA-Analyze cleanup | ✅ | Removed gaps from output schema + fixed Step 3 and Identity text |
| Researcher RAW fallback | ✅ | Claude Code fix: always writes debug output, saves raw content on parse failure |
| TopicPackage status fix | ✅ | Claude Code fix: `to_dict()` now includes `status` field |
| Validation run (Stufe 1) | ✅ | Partial run: Researcher V2 → Perspektiv → Writer → QA → Correction. End-to-end success. |

## Architecture Decisions Made

### Perspective Agent — Pipeline Position & Scope

**Decision:** Perspective Agent ships before the demo, not after.

**Pipeline order confirmed:**
```
Collector → Curator → Editor → Researcher → Perspective Agent → Writer → QA-Analyze → [Bias Detector]
```

**Key design choices:**
- Perspektiv Agent has NO tools (no web_search). Works exclusively with the Researcher's dossier.
- Researcher V2 extended with `actors_quoted` field per source to feed the Perspektiv Agent structured actor data.
- `gaps` ownership moved from QA to Perspektiv Agent (`missing_voices`). QA now produces only `corrections` + `divergences`.
- `framing_divergences` (qualitative narrative differences) belong to Perspektiv Agent. `divergences` (factual contradictions) stay with QA.
- Writer V2 structures articles around `perspective_analysis` when present — stakeholder positions, framing divergences explicit, missing voices in meta-transparency paragraph.

### Topic Package Field Ownership

| Field | Owner | Content |
|-------|-------|---------|
| `perspectives` | Perspektiv Agent | `stakeholders` array from perspective_analysis |
| `gaps` | Perspektiv Agent | `missing_voices` array from perspective_analysis |
| `divergences` | QA-Analyze | Factual contradictions between sources |
| `transparency.framing_divergences` | Perspektiv Agent | Qualitative framing differences |
| `corrections` | QA-Analyze | Errors in article needing Writer fix |
| `bias_analysis` | Bias Detector | (future) Linguistic/structural bias |

### Researcher → Perspektiv Agent Data Flow

The Researcher's `actors_quoted` schema per source:
```json
{"name": "string", "role": "string", "type": "enum (10 types)", "position": "one-sentence summary"}
```
No quote field — the Researcher extracts positions, not verbatim quotes. The Perspektiv Agent's `position_quote` is mostly null (extracted from source titles when available). This is a known limitation, not a bug.

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
                         ┌── per topic ──────────────────────────┐
                         │  Researcher (glm-5, multilingual search,    │
                         │              actors_quoted per source)       │
                         │   ↓                                         │
                         │  Perspektiv Agent (glm-5, no tools,         │
                         │              stakeholder map, missing voices,│
                         │              framing divergences)            │
                         │   ↓                                         │
                         │  Writer (glm-5, article structured around   │
                         │              perspective_analysis)           │
                         │   ↓                                         │
                         │  QA-Analyze (glm-5, corrections +           │
                         │              divergences only, no gaps)      │
                         │   ↓                                         │
                         │  [Writer-Correction if needed]              │
                         │  [Python-Verify]                            │
                         │  [Bias Detector] (future)                   │
                         └─────────────────────────────────────────────┘
                                      ↓
                              Topic Package JSON
```

## Debug Output Files (per topic)

```
01-collector-raw.json
02-curator-topics.json
03-editor-assignments.json
04-researcher-{slug}.json          (with actors_quoted)
04-researcher-{slug}-RAW.json      (fallback if JSON parse fails)
04b-perspektiv-{slug}.json         (NEW: stakeholders, missing_voices, framing_divergences)
05-writer-{slug}.json
06-qa-analyze-{slug}.json
07-writer-correction-{slug}.json   (only if corrections applied)
run-{id}-stats.json
run-{id}-summary.json
```

## Validation Run Results (Stufe 1 — Partial Run 39e65d)

Single topic: `us-israel-iran-conflict-second-month`

| Agent | Tokens | Duration | Notes |
|-------|--------|----------|-------|
| Researcher | 94,116 | 4:21 | 19 tool calls, 7 languages (EN, FA, AR, HE, TR, ZH, FR), 23 sources with actors_quoted |
| Perspektiv | 21,530 | 3:43 | 19 stakeholders, 6 missing voices, 6 framing divergences |
| Writer | 60,008 | 1:40 | 6 web searches for additional sourcing |
| QA-Analyze | 21,520 | 1:12 | Found 7 corrections |
| Writer-Correction | 36,219 | 1:14 | All 7 corrections applied |
| **Total** | **233,393** | **12:10** | End-to-end success |

**Quality highlights:**
- Missing voices are specific and reasoned (e.g., "No direct testimonies from Iranian civilians despite 1,400+ documented deaths including 217 children")
- Framing divergences capture real narrative differences (Western vs. Russian/Chinese framing of aggressor role)
- Stakeholder deduplication works (Iran merged from 4 sources → 1 entry, representation: strong)
- `position_quote` mostly null (2/19) — quotes extracted from source titles, not from actors_quoted (no quote field in Researcher schema)

**Cost observation:** 233K tokens for one topic ≈ $0.50-1.00. At 3 topics per run ≈ $1.50-3.00. Acceptable for current stage but relevant for scaling.

## Known Issues / Open Items

| # | Type | Description | Priority |
|---|------|-------------|----------|
| — | GLM-5 | ~30% JSON parse failure rate on complex Researcher output (2/3 topics failed in full run e6688b). JSON repair (QF-05) mitigates but doesn't eliminate. | 🔴 |
| — | Pipeline | Full 3-topic run with Perspektiv Agent not yet validated. Only single-topic partial run succeeded. | 🔴 Next |
| — | Prompt | Writer V2 prompt is updated but untested with perspective_analysis data. Next run validates. | 🟡 |
| — | Schema | Researcher actors_quoted has no `quote` field — only `position` (summary). position_quote in Perspektiv output mostly null. Future improvement, not blocker. | 🟢 |
| — | Code | pipeline.py has minor dead code: `sources: list[dict] = []` removed (QF-06), but QA Step 3 reference to coverage_gaps already cleaned. | ✅ Done |

## What Comes Next

### Priority order for next session

| Task | Impact | Effort | Notes |
|------|--------|--------|-------|
| Full pipeline run (Lauf 7) | High | Small | First complete 3-topic run with Researcher V2 + Perspektiv + Writer V2. Validates full flow. |
| WP-RESEARCHER-EVAL | High | Medium | Compare LLMs for Researcher: GLM-5 vs minimax-m2.7 vs alternatives. Concrete question: which model reliably produces complex JSON with actors_quoted? |
| WP-CACHING | Medium | Medium | Prompt caching via OpenRouter. Research GLM5-turbo + Mimo-V2-Pro caching behavior. Provider-agnostic design. |
| WP-BIAS | Medium | Medium | Bias Detector agent — last pipeline slot. Depends on stable upstream agents. |
| WP-RENDERING | Medium | Large | Topic Packages → website/newsletter/API. Perspective Spectrum diagram from stakeholder data. |
| WP-MEMORY | Low | Small | Editor memory for coverage continuity across runs. |

### Recommendation
Start next session with Lauf 7 (full 3-topic run). If GLM-5 fails on Researcher JSON again, immediately pivot to WP-RESEARCHER-EVAL. If Lauf 7 succeeds, review Writer output for perspective_analysis integration quality, then decide WP-CACHING vs WP-BIAS.

## Prompt Engineer Workflow Reminder

Briefings are given as code blocks in chat (NOT as .md files in repo). Flow:
1. Architect (this Claude) writes briefing as code block
2. Deniz pastes briefing into Prompt Engineer Claude project
3. Prompt Engineer returns finished prompt
4. Deniz shares prompt with Architect for review
5. Architect writes approved prompt to `agents/{name}/AGENTS.md`
6. Claude Code implements pipeline integration — Claude Code MUST NOT write or rewrite agent prompts

## Workflow Reminders

### Three-Role Division
| Role | Tool |
|------|------|
| **Architect** (this Claude instance) | Planning, task files, prompt review, doc updates |
| **Prompt Engineer** (separate Claude project) | Writing agent system prompts via briefing |
| **Implementer** (Claude Code) | Code implementation, testing, git commits |

### File conventions
- Task files: repo root (e.g. `TASK-PERSPEKTIV-INTEGRATION.md`)
- Agent prompts: `agents/{name}/AGENTS.md` — written by Architect after Prompt Engineer review
- Claude Code prompts: code boxes for copy-paste
- Task files and prompts: English. Conversation with Deniz: German.

### Key commands
- Full run: `python scripts/run.py` (~30-40 min, ~$1.50-3.00)
- Partial run: `python scripts/run.py --from perspektiv --reuse 2026-04-07 --topic 1`
- Feeds: `python scripts/fetch_feeds.py`
- Tests: `source .venv/bin/activate && source .env && python -m pytest tests/ -v`
- Claude Code: `source .env && claude`

## Key Technical Facts

- **Provider:** OpenRouter with `minimax/minimax-m2.7` + `z-ai/glm-5`
- **max_tokens:** 65536 (default, updated from 32768 via QF-04)
- **JSON repair:** `_parse_json` in agent.py handles prose-wrapped JSON, trailing commas, truncated brackets
- **Token tracking:** `output/{date}/run-*-stats.json`
- **Local path:** `/Users/denizschwenk/Documents/independent-wire/repo-clone/`

## Agent Inventory

| Agent | Model | Tools | Temp | Prompt |
|-------|-------|-------|------|--------|
| collector | minimax-m2.7 | web_search | 0.2 | agents/collector/AGENTS.md |
| curator | minimax-m2.7 | none | 0.2 | agents/curator/AGENTS.md |
| editor | glm-5 | none | 0.3 | agents/editor/AGENTS.md |
| researcher | glm-5 | web_search | 0.2 | agents/researcher/AGENTS.md (V2: actors_quoted) |
| perspektiv | glm-5 | none | 0.1 | agents/perspektiv/AGENTS.md (NEW) |
| writer | glm-5 | web_search | 0.3 | agents/writer/AGENTS.md (V2: perspective_analysis) |
| qa_analyze | glm-5 | none | 0.1 | agents/qa_analyze/AGENTS.md (corrections + divergences only) |
| bias_detector | — | — | — | Future — not yet implemented |

## Task Files in Repo Root

| File | Status | Notes |
|------|--------|-------|
| TASK-QUICKFIXES-04-07.md | ✅ Done | QF-04, P-07, P-08 |
| TASK-PERSPEKTIV-INTEGRATION.md | ✅ Done | Pipeline integration for Perspektiv Agent |
| WP-PERSPECTIVE-AGENT.md | ✅ Decided | Architecture decision document (Deniz) |
