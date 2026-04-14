# Independent Wire

**The news you read was chosen for you. This system shows you why — and what's missing.**

**[→ Read the latest dossiers at independentwire.org](https://independentwire.org)**

Independent Wire is an open-source AI pipeline that produces multi-perspective news dossiers with full source transparency. It scans 72 sources in 20+ languages, identifies where coverage diverges, documents which voices are missing, and publishes everything — including its own biases and limitations.

No publisher. No engagement algorithm. No hidden editorial line. Every decision the system makes is traceable, auditable, and open.

## What It Produces

Independent Wire does not produce articles. It produces **Topic Packages** — structured transparency bundles containing:

- **The article** — source-based, multi-perspective, with every claim traced to a cited source in its original language
- **The perspectives** — who says what, how strongly represented, from which region
- **The divergences** — where sources contradict each other in fact, framing, or emphasis
- **The gaps** — which regions, demographics, or viewpoints no source covers
- **The bias card** — analysis of the article's own language bias, source balance, and geographic coverage
- **The reader note** — an honest self-assessment, placed *before* the article, not after
- **The transparency trail** — why this topic was selected, what was corrected by QA, what the system cannot see

The article is one rendering of the Topic Package. The same data could produce a podcast briefing, a newsletter, or an API response.

## How It Works

A pipeline of specialized AI agents, orchestrated by deterministic Python code. No LLM decides "what to do next."

```
RSS Feeds (72 sources, 20+ languages)
  → Curator — clusters and scores ~1,400 findings
  → Editor — prioritizes topics, selects top 3 with reasoning
     → Researcher — plans multilingual search queries, executes via Python, assembles dossier
     → Perspective Agent — maps stakeholders, identifies missing voices, documents framing divergences
     → Writer — produces source-attributed article from dossier + perspective analysis
     → QA+Fix — finds errors, applies corrections, documents changes
     → Bias Detector — Python aggregation + LLM language analysis → bias transparency card
  → Topic Package JSON → HTML rendering → Publication
```

Each agent uses a different model optimized for its role. Three production models: Gemini 3 Flash (research tasks), Claude Opus 4.6 (editorial and analytical tasks), Claude Sonnet 4.6 (QA). All prompts are in the repo under `agents/`.

## What This Is Not

Independent Wire is not a chatbot, not a news aggregator with a nice UI, and not a replacement for investigative journalism. It cannot conduct confidential interviews, meet whistleblowers, or visit a factory.

It is not neutral — nothing is. But it is transparent about how and where it is not neutral. That is more than most systems offer.

## Project Status

The pipeline is operational and publishing dossiers at [independentwire.org](https://independentwire.org).

| Component | Status |
|-----------|--------|
| Pipeline (8 agents, 3 models) | ✅ Operational — 13+ runs completed |
| Source base (72 feeds, 20+ languages) | ✅ Live |
| Topic Package rendering (HTML, self-contained) | ✅ Live |
| Publication website | ✅ Live at [independentwire.org](https://independentwire.org) |
| RSS feed | ✅ Available at [independentwire.org/feed.xml](https://independentwire.org/feed.xml) |
| Editor memory (coverage continuity) | ✅ Implemented |
| Prompt caching | 🔜 Planned |
| MCP server (query TPs from Claude/ChatGPT) | 🔜 Planned |
| Source expansion (100+ feeds) | 🔜 Planned |

## Cost Transparency

A single pipeline run (3 topics) costs approximately €3.27 and takes 25 minutes. The system runs on commercial AI APIs via OpenRouter. No advertising. No subscriptions. No data collection. Operating cost = AI API cost.

All cost data, including per-agent token breakdowns, is documented in [COST-OPTIMIZATION-ANALYSIS.md](docs/COST-OPTIMIZATION-ANALYSIS.md).

## Architecture

Three abstractions: **Agent** (configured LLM caller), **Pipeline** (deterministic orchestration), **Tool** (swappable external capability). Async from day one. Three dependencies: `openai`, `httpx`, `feedparser`.

Details: [ARCHITECTURE.md](docs/ARCHITECTURE.md) · [ROADMAP.md](docs/ROADMAP.md) · [TASKS.md](docs/TASKS.md)

## License

**AGPL-3.0** — the strongest copyleft license available. Anyone who hosts Independent Wire must also open-source their modifications, including changed prompts. This is not a restriction. It is the license doing its job.

Who can read the prompts can check the agenda. Who can change the prompts is free.

## Contributing

The project is in active development by a single developer. The best ways to contribute right now:

- **Read a dossier** at [independentwire.org](https://independentwire.org) and open an issue with feedback
- **Review the prompts** in `agents/` — editorial improvements are as valuable as code
- **Expand the source base** — suggest feeds from underrepresented regions in `config/sources.json`
- Star the repo to signal interest

Read the [vision paper](docs/VISION-independent-wire.pdf) for the full rationale behind the project.

---

*Independent Wire — Because transparency is not a feature, it is a promise.*
