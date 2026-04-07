# Independent Wire — Session Handoff (2026-03-31)

## Completed This Session

| WP / Fix | Status | Notes |
|----------|--------|-------|
| WP-INTEGRATION | ✅ | First e2e run: 2/3 topics. Fixed: code-fence parsing, model routing |
| WP-RSS | ✅ | 21 sources, fetch_feeds.py (14/20 RSS + GDELT = 553 entries), Pipeline merges in curate() |
| WP-DEBUG-OUTPUT | ✅ | Debug JSON per step: 01-collector, 02-curator, 03-editor, 04-writer-{slug} |
| WP-REASONING | ✅ | Agent `reasoning` param → OpenRouter `reasoning.effort` / Ollama `think` |
| Prompt P-01–P-05 | ✅ | Collector: date-awareness, YouTube/Wiki/social ban, best-effort multilingual, no dup URLs. Writer: Wikipedia only for background |
| Pipeline F-01–F-05 | ✅ | 30s delay, date in Editor msg, code-fence parsing, model correction, language diversity warning in verify() |

## Two Successful Pipeline Runs

| Metric | Run 1 (2026-03-30) | Run 2 (2026-03-31) |
|--------|--------------------|--------------------|
| Topics produced | 2/3 (1 failed) | **3/3 (0 failed)** |
| Topic IDs | tp-2025-01-09-* (wrong) | **tp-2026-03-31-*** |
| Collector queries | "economy news 2024" | **"March 2026", "today"** |
| RSS feeds merged | 0 | **445 findings** |
| Total Curator input | 39 | **483 (38+445)** |
| Debug files | none | **6 files** |
| Source languages | 100% EN | 100% EN (unchanged) |
| Runtime | 19 min | 19.5 min |


## Key Insight: Language Diversity Unsolved

Both runs produced articles sourced 100% in English despite international country coverage. RSS feeds deliver English content even from non-English outlets. The Collector searches in English. The Writer finds English sources.

**Decision:** Language diversity is NOT a prompt problem — it's a pipeline architecture problem. Solution: WP-RESEARCH (dedicated multilingual research agent per topic, between Editor and Writer). Pipeline.verify() now warns when all sources share one language, making the gap visible until WP-RESEARCH is implemented.

## What Comes Next

### Immediate: Fix broken RSS feeds
8/21 feeds failed (Tehran Times, Daily Nation, Guardian Nigeria, PTI, El Universal, Xinhua, TASS, ReliefWeb). See TASKS.md "Feed-Fixes" table. Can be a Claude Code task:
```
Fix the broken feed URLs in config/sources.json. 8 feeds are failing — see docs/TASKS.md "Feed-Fixes" section for details. For each broken feed, find the correct RSS URL or replace with a working alternative from the same region. Test with: source .venv/bin/activate && python scripts/fetch_feeds.py
```

### Then: Choose next WP based on priority

| WP | Impact | Effort |
|----|--------|--------|
| WP-RESEARCH | Solves the #1 quality gap (language diversity) | Medium — new agent + prompt + pipeline slot |
| WP-QA | Fact verification + fills divergences/gaps fields | Medium — new agent + prompt |
| WP-PERSPEKTIV | Multi-perspective depth per topic | Medium — new agent + prompt |
| WP-MEMORY | Editor knows past coverage, Writer references it | Small — file-based memory loading |


## Pipeline Architecture (current)

```
RSS feeds (cron/manual)  →  raw/YYYY-MM-DD/feeds.json
                                      ↓
Collector (web_search)  →  raw findings
                                      ↓
                              Curator (merges both inputs)
                                      ↓
                              Editor (assigns topics)
                                      ↓
                         ┌── per topic ──────────────┐
                         │  [Research Agent] (future) │
                         │  [Social Media]  (future)  │
                         │  [Perspektiv]    (future)  │
                         │   Writer (article)         │
                         │  [QA]            (future)  │
                         │  [Bias Detector] (future)  │
                         └────────────────────────────┘
                                      ↓
                              Topic Package JSON
```

## Key Technical Facts

- **Models:** minimax/minimax-m2.7 (Collector, Curator) + z-ai/glm-5 (Editor, Writer) via OpenRouter
- **Search:** Perplexity sonar-pro via OpenRouter
- **RSS:** feedparser + httpx for GDELT. 21 sources in config/sources.json (14 working)
- **Tests:** `source .venv/bin/activate && source .env && python -m pytest tests/ -v`
- **Pipeline:** `source .venv/bin/activate && source .env && python scripts/run.py`
- **Feeds:** `source .venv/bin/activate && python scripts/fetch_feeds.py`
- **Claude Code:** `source .env && claude`
- **Git:** HTTPS via macOS Keychain, `git push origin main`
- **Local clone:** /Users/denizschwenk/Documents/independent-wire/repo-clone/
- **Living docs:** docs/TASKS.md (operational), docs/ROADMAP.md (strategic)
