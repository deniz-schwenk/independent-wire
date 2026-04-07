# Independent Wire — Session Handoff (2026-04-05)

## Completed This Session

| Task | Status | Notes |
|------|--------|-------|
| Feed-Fixes | ✅ | 8/21 broken feeds fixed. Google News proxies eliminated in second round. All 21 feeds now direct outlet RSS |
| WP-RESEARCH | ✅ | Research Agent: multilingual deep search between Editor and Writer. Lauf 3: 5-8 languages per topic |
| WP-PARTIAL-RUN | ✅ | `--from`/`--topic`/`--reuse` CLI flags. Writer-only test: 2 min / ~$0.05 instead of 30 min / ~$0.50 |
| CLAUDE.md | ✅ | Project instructions for Claude Code. Cost-awareness rule: ask before full pipeline runs |
| TASKS.md + ROADMAP.md | ✅ | Updated with all completions, Lauf 3 results, new WP tracking |

## Third Pipeline Run (Lauf 3)

| Metric | Lauf 2 (03-31) | Lauf 3 (04-05) |
|--------|----------------|----------------|
| Topics | 3/3 | 3/3 |
| Runtime | 19.5 min | 29.6 min |
| Languages per topic | 1 (en only) | 5-8 (en, ar, fa, he, hu, de, fr, pl, ja, zh-TW) |
| Sources per topic | ~10 | 18-38 |
| Researcher queries | n/a | 12-13 per topic, 76-85% non-English |

The #1 quality problem (100% English sources) is solved.

## Feed Replacements (final state)

| Old | New | Region |
|-----|-----|--------|
| Tehran Times | Press TV | Middle East |
| Xinhua | South China Morning Post | East Asia |
| TASS | Moscow Times | Europe |
| Guardian Nigeria | Premium Times Nigeria | Africa |
| PTI | NDTV | South Asia |
| El Universal | El Financiero | Latin America |
| ReliefWeb | IPS News | International |
| Daily Nation | nation.africa/kenya/rss.xml (same outlet, fixed URL) | Africa |

Principle: No Google News proxy URLs. All feeds point to outlet's own domain.

## Workflow Established This Session

### Three-Role Division

| Role | Responsibility | Tool |
|------|---------------|------|
| **Architect** (this Claude instance) | Planning, task files, WP design, doc updates, prompt review | Claude.ai Project |
| **Prompt Engineer** (separate Claude project) | Writing agent system prompts (AGENTS.md files) | Claude.ai Project |
| **Implementer** (Claude Code) | Code implementation, testing, git commits | Claude Code CLI |

### New Agent Workflow (established with WP-RESEARCH)

1. **Architect** writes a prompt briefing as a **code box** (not as a file in the repo). Contains: agent purpose, model info, input/output format, behavioral requirements, constraints, reference prompts.
2. **Deniz** pastes the briefing into the **Prompt Engineer** Claude project.
3. **Prompt Engineer** writes the prompt following Fabric structure (IDENTITY / STEPS / OUTPUT FORMAT / RULES).
4. **Deniz** uploads the finished prompt to this chat for **Architect review**.
5. **Architect** evaluates against requirements. If approved, writes it to `agents/{name}/AGENTS.md` in the repo.
6. **Claude Code** implements pipeline integration (reads WP-*.md task file). Claude Code does NOT write or rewrite agent prompts.

### Claude Code Instructions

- `CLAUDE.md` in repo root — read automatically by Claude Code on every session start
- Contains: testing cost rules, model protection, prompt protection, key commands
- Key rule: "NEVER run a full pipeline just to test — ask first if a partial run suffices"

### Task File Convention

- Task files go in **repo root** (e.g., `WP-RESEARCH.md`, `TASK-FEED-FIXES.md`)
- Claude Code prompts formatted as **code boxes** for copy-paste
- Task files and prompts in **English**; conversation with Deniz in **German**

## What Comes Next

### Priority order for next WPs

| WP | Impact | Effort | Notes |
|----|--------|--------|-------|
| WP-QA | Fact verification, fills divergences + gaps fields | Medium | New agent + prompt + pipeline slot |
| WP-PERSPEKTIV | Multi-perspective depth per topic | Medium | New agent + prompt + pipeline slot |
| WP-MEMORY | Editor knows past coverage | Small | File-based memory loading |
| WP-BIAS | 5-dimension bias analysis | Medium | New agent + prompt |

All four follow the established three-role workflow (Architect → Prompt Engineer → Claude Code).

## Pipeline Architecture (current)

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
                         │   Researcher (glm-5, multilingual search) ✅ NEW │
                         │   Writer (glm-5, article)     │
                         │  [QA]            (future)     │
                         │  [Bias Detector] (future)     │
                         └───────────────────────────────┘
                                      ↓
                              Topic Package JSON
```

## Key Technical Facts

- **Partial runs:** `python scripts/run.py --from writer --reuse 2026-04-04 --topic 1`
- **Full run:** `python scripts/run.py` (~30 min, ~$0.50-1.00)
- **Feeds:** `python scripts/fetch_feeds.py` (21 sources, 0 failed)
- **Tests:** `python -m pytest tests/ -v`
- **Claude Code:** `source .env && claude` (reads CLAUDE.md automatically)
- **Debug output:** `output/YYYY-MM-DD/01-collector-raw.json` through `05-writer-*.json`
- **Local clone:** `/Users/denizschwenk/Documents/independent-wire/repo-clone/`
