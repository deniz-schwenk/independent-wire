# Independent Wire

**The news you read was chosen for you. This system shows you why — and what's missing.**

Independent Wire is an open-source AI pipeline that doesn't just report the news. It analyzes *how* the news is reported — which perspectives are included, which are absent, where sources contradict each other, and what structural biases shape the coverage you see.

No publisher. No algorithm optimizing for engagement. No hidden editorial line. Every decision the system makes — from topic selection to source weighting — is traceable, auditable, and open.

> 🚧 **Under active development** — Framework operational, first pipeline runs completed. [Read the vision paper →](docs/VISION-independent-wire.pdf)

## The Problem

Every piece of news you read has passed through a chain of human decisions: which topic gets picked up, which angle chosen, which sources cited, which facts emphasized, which omitted. These decisions are invisible to the reader. The result is a system that *feels* like information but is actually a *selection* — shaped by economic pressure, institutional bias, cultural perspective, and editorial hierarchy.

AI news products reproduce this problem. They aggregate, summarize, and optimize — but they don't make the editorial process transparent. They replace one black box with another.

## What Independent Wire Does Differently

Independent Wire produces **Topic Packages** — not articles. A Topic Package is a structured transparency bundle containing:

- **The facts** — what happened, according to whom, in what language, verified against original sources
- **The perspectives** — who says what, how strongly represented, from which region
- **The divergences** — where sources explicitly contradict each other
- **The gaps** — which regions, demographics, or viewpoints no source covers
- **The bias card** — systematic analysis across 5 dimensions: language, source, framing, selection, and geographical bias
- **The transparency trail** — why this topic was selected, what was discarded, what the system cannot see

The article is one possible *rendering* of the Topic Package — not the package itself.

## How It Works

A pipeline of specialized AI agents, orchestrated by deterministic Python code — no LLM decides "what to do next":

**Collector** → scans global sources in multiple languages via RSS and web search
**Curator** → evaluates relevance, creates structured topic proposals
**Editor** → prioritizes topics, maintains editorial memory across runs
**Perspective Agent** → researches the full spectrum of positions per topic
**Writer** → writes source-based, multi-perspective text
**QA / Fact-Check** → three-tier verification: VERIFIED / UNVERIFIABLE / PROVABLY FALSE
**Bias Detector** → analyzes the finished text for bias — marks, never rewrites

Each agent can use a different AI model optimized for its role. The system is designed so that no single model, no single source, and no single perspective dominates.

## What This Is Not

Independent Wire is not a chatbot, not a news app, not a content generator, and not a replacement for investigative journalism. It cannot conduct confidential interviews, meet whistleblowers, or visit a factory. It is not neutral — nothing is. But it is **transparent about how and where it is not neutral**, which is more than most systems offer.

## Project Status

| Phase | Status |
|-------|--------|
| Vision, schema, architecture | ✅ Complete |
| Framework (Agent + Pipeline + Tool) | ✅ Operational |
| First end-to-end pipeline runs | ✅ 2 runs completed |
| Multi-provider search (Perplexity, Brave, DuckDuckGo) | ✅ Done |
| RSS feed ingestion (21 global sources) | ✅ Done |
| Perspective Agent, Bias Detector, QA | 🔜 Next |
| Live demo (15+ sources, 5+ languages) | 🔜 Planned |

[Architecture →](docs/ARCHITECTURE.md) · [Roadmap →](docs/ROADMAP.md) · [Task tracker →](docs/TASKS.md)

## Cost Transparency

Independent Wire runs on commercial AI APIs via OpenRouter. Two pipeline runs have been completed at ~$0.30–0.50 each (3 topics, 19 minutes). No advertising. No subscriptions. No data collection. Just API costs.

## License

**AGPL-3.0** — the strongest copyleft license available. Anyone who hosts Independent Wire must also open-source their modifications, including changed prompts. This is not a restriction. It is the license doing its job.

Who can read the prompts can check the agenda. Who can change the prompts is free.

## Contributing

This project is in its early stages. The best way to contribute right now:

- Read the [architecture](docs/ARCHITECTURE.md) and the [vision paper](docs/VISION-independent-wire.pdf)
- Open issues with questions or suggestions
- Star the repo to signal interest

---

*Independent Wire — Because transparency is not a feature, it is a promise.*

