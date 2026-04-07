# Independent Wire — Session Handoff (2026-04-07, Session 2)

## Completed This Session

| Task | Status | Notes |
|------|--------|-------|
| Lauf 7 (full 3-topic run) | ✅ | 2/3 topics, 1 failed (Hormuz — 85K token Researcher crash). Triggered architecture rework. |
| WP-RESEARCHER-SPLIT | ✅ | Two-phase architecture: Plan → Python search → Assemble |
| 4 new agent prompts | ✅ | researcher/PLAN.md, researcher/ASSEMBLE.md, collector/PLAN.md, collector/ASSEMBLE.md |
| Planner model swap | ✅ | minimax-m2.7 → GLM-5 (fixed script mixing + calendar errors) |
| Writer RULE 8 | ✅ | Corrections must REPLACE flagged text, not add alongside |
| Writer-Correction retry loop | ✅ | Max 3 attempts, only unapplied corrections re-sent |
| Collector disabled | ✅ | RSS feeds (624 findings/day) sufficient. Code preserved for future pre-filter role. |
| --to CLI flag | ✅ | Pipeline slice testing: --from X --to Y runs only that range |
| WP-BIAS | ✅ | Hybrid Bias Card: Python aggregation + slim LLM language analysis |
| Bias Detector prompt | ✅ | agents/bias_detector/AGENTS.md (Language Bias Analyzer) |
| Lauf 9 (full 3-topic run) | ✅ | **3/3 topics, 0 failures, 391K tokens, 48 min.** First complete run with all new architecture. |
| QF-08 | ✅ | output_schema added to QA-Analyze call, enables structured retry on JSON failures |
| ROADMAP.md updated | ✅ | All WPs, agents, decisions current |

## Lauf 9 Results (first complete run with new architecture)

**3/3 topics completed, 0 failures. 391,224 tokens, 47.7 minutes.**

| Metric | Lauf 7 (old) | Lauf 9 (new) | Delta |
|--------|-------------|-------------|-------|
| Topics completed | 2/3 | 3/3 | +50% |
| Total tokens | 476,915 | 391,224 | -18% |
| JSON crashes | 1 | 0 | fixed |
| Pipeline agents | 7 | 10 (incl. Bias) | +3 |
| Duration | 54.5 min | 47.7 min | -12% |

**Per-topic token breakdown (Lauf 9):**
- Topic 1 (US-Israel-Iran Escalation): 134K — QA returned empty `{}` (15K tokens lost, fixed by QF-08)
- Topic 2 (Humanitarian Crisis Gaza): 127K — 4 corrections, all applied first attempt
- Topic 3 (Iranian Retaliation): 119K — 2 corrections, all applied first attempt

**Bias Cards:** All 3 rated severity "low" with 0 language bias findings. Reader notes correctly synthesize missing voices (Israeli government, displaced families, Iranian government).

**Writer-Correction:** All 6 corrections applied on first attempt. Retry loop not exercised but operational.

## Architecture Decisions Made

### Two-Phase Agent Architecture (WP-RESEARCHER-SPLIT)
**Problem:** Agents with web_search in a tool loop accumulate context with each iteration. The Researcher's Hormuz topic consumed 85K tokens across 14 iterations, with the final JSON output crashing.

**Solution:** Split into Plan → Python search → Assemble. Two clean LLM calls, Python executes searches in between. No accumulating context.

**Impact:** Researcher tokens dropped from 85K to ~30K. JSON parse failures eliminated.

### Bias Card as Hybrid (WP-BIAS)
**Problem:** A full Bias Detector agent would duplicate 80% of what Perspektiv and QA already produce.

**Solution:** Python aggregates existing pipeline data (0 tokens). Slim LLM call (~8-11K tokens) adds language analysis + reader note. No re-analysis.

### Collector Disabled
RSS feeds deliver 624 findings/day from 60 outlets. Collector added ~38 findings (8%). Code preserved for future pre-filter role when scaling to 200+ feeds.

### QF-08: QA Structured Retry
QA-Analyze was called without output_schema — no structured retry on JSON failures. Topic 1 lost 15K tokens of QA work. Fixed by adding output_schema with corrections/divergences required fields.

## Current Pipeline Architecture

```
RSS feeds (cron/manual)  →  raw/YYYY-MM-DD/feeds.json
         ↓
[Collector DISABLED — RSS sufficient]
         ↓
Curator (minimax-m2.7, merges RSS feeds)
         ↓
Editor (glm-5, assigns topics)
         ↓
┌── per topic ────────────────────────────────────────────┐
│  Researcher Planner (glm-5, no tools)                   │
│  Python Search Execution (0 tokens)                     │
│  Python Deduplication (0 tokens)                        │
│  Researcher Assembler (glm-5, no tools)                 │
│   ↓                                                     │
│  Perspektiv Agent (glm-5, no tools)                     │
│   ↓                                                     │
│  Writer (glm-5, web_search)                             │
│   ↓                                                     │
│  QA-Analyze (glm-5, no tools, output_schema)            │
│   ↓                                                     │
│  Writer-Correction (retry loop, max 3)                  │
│  Python-Verify (deterministic)                          │
│   ↓                                                     │
│  Python: build_bias_card (0 tokens)                     │
│  Bias Language Analyzer (glm-5, no tools)               │
│   ↓                                                     │
│  Topic Package JSON                                     │
└─────────────────────────────────────────────────────────┘
```

## Agent Inventory

| Agent | Model | Tools | Temp | Prompt |
|-------|-------|-------|------|--------|
| collector_plan | glm-5 | none | 0.5 | agents/collector/PLAN.md (DISABLED) |
| collector_assemble | minimax-m2.7 | none | 0.2 | agents/collector/ASSEMBLE.md (DISABLED) |
| curator | minimax-m2.7 | none | 0.2 | agents/curator/AGENTS.md |
| editor | glm-5 | none | 0.3 | agents/editor/AGENTS.md |
| researcher_plan | glm-5 | none | 0.5 | agents/researcher/PLAN.md |
| researcher_assemble | glm-5 | none | 0.2 | agents/researcher/ASSEMBLE.md |
| perspektiv | glm-5 | none | 0.1 | agents/perspektiv/AGENTS.md |
| writer | glm-5 | web_search | 0.3 | agents/writer/AGENTS.md |
| qa_analyze | glm-5 | none | 0.1 | agents/qa_analyze/AGENTS.md |
| bias_language | glm-5 | none | 0.1 | agents/bias_detector/AGENTS.md |

## Known Issues / Open Items

| # | Type | Description | Priority |
|---|------|-------------|----------|
| — | Repo | Decide where to move internal files (TASKS.md, WP-*.md, SESSION-HANDOFF-*.md) to keep public repo clean. Options: separate private repo, local folder outside repo, or .gitignore. | 🟡 |
| — | Assembler | minimax-m2.7 as Researcher Assembler not yet tested. Currently GLM-5 for both plan and assemble. Test minimax for assembler if token cost reduction needed. | 🟢 |
| — | Bias | Language bias findings empty (severity "low") on all 3 topics in Lauf 9. May indicate GLM-5 too lenient, or Writer genuinely clean. Manual spot-check recommended. | 🟡 |
| — | Writer | Topic 1 writer used 70K tokens (vs 35-49K for Topics 2-3). High variance. May correlate with topic complexity or web_search count. | 🟢 |

## What Comes Next

### Immediate (next session)
1. **WP-RENDERING** — Topic Packages → visible output. Minimal HTML template rendering article + Bias Card. Required for demo.
2. **Repo cleanup** — decide where internal planning files go (private repo, local folder, or .gitignore). Keep public repo professional.

### Near term
3. **WP-MEMORY** — Editor memory for coverage continuity across runs
4. **WP-CACHING** — Prompt caching via OpenRouter. Two-phase split improves caching (system prompts are stable prefixes)
5. **RSS feed expansion** — Scale from 21 to 40+ feeds using World Monitor catalog. At 200+, reactivate Collector as pre-filter.

### Demo readiness checklist
- [x] Full pipeline run passes (3/3 topics, 0 crashes) ✅ Lauf 9
- [ ] WP-RENDERING (Topic Package → readable HTML with Bias Card)
- [ ] README with quick-start guide
- [ ] At least one published Topic Package on independentwire.org

## Prompt Engineer Workflow

Briefings as code blocks in chat (NOT as .md files in repo). Flow:
1. Architect (this Claude) writes briefing
2. Deniz pastes briefing into Prompt Engineer Claude project
3. Prompt Engineer returns finished prompt
4. Architect reviews and writes to `agents/{name}/*.md`
5. Claude Code implements pipeline integration — MUST NOT write or rewrite agent prompts

## Key Commands

```bash
# Full run
python scripts/fetch_feeds.py && python scripts/run.py

# Pipeline slice testing
python scripts/run.py --from researcher --to perspektiv --reuse 2026-04-07 --topic 1
python scripts/run.py --from bias_detector --to bias_detector --reuse 2026-04-07 --topic 1

# Single step
python scripts/run.py --from qa_analyze --to qa_analyze --reuse 2026-04-07 --topic 1

# Claude Code
source .env && claude
```

## Key Technical Facts

- **Provider:** OpenRouter — `z-ai/glm-5` (all complex tasks) + `minimax/minimax-m2.7` (curator only)
- **max_tokens:** 65536
- **Two-phase agents:** Plan (LLM) → Search (Python) → Assemble (LLM). Eliminates context accumulation.
- **Bias Card:** Python aggregation (0 tokens) + slim LLM language analysis (~8-11K tokens)
- **Writer-Correction:** Retry loop max 3, only unapplied corrections re-sent
- **QA-Analyze:** Now uses output_schema for structured retry (QF-08)
- **Collector:** DISABLED — RSS feeds sufficient. Code preserved for 200+ feed pre-filter.
- **Local path:** `/Users/denizschwenk/Documents/independent-wire/repo-clone/`
