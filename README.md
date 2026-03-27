# Independent Wire

**An independent newsroom in your pocket. Open. Transparent. For everyone.**

Independent Wire is an open-source system for transparent, multi-perspective news production using specialized AI agents. It doesn't produce articles — it produces **Topic Packages**: structured transparency bundles containing facts, perspectives, divergences, gaps, bias analysis, and a full transparency trail.

> 🚧 **Under Construction** — The architecture is defined, the schema is designed, the framework is being built. [Read the vision paper →](docs/VISION.md)

## What This Is

A pipeline of specialized AI agents, each with a clearly defined role:

| Agent | Role |
|-------|------|
| **Collector** | Scans sources globally via RSS and web search |
| **Kurator** | Evaluates relevance, creates structured topic proposals |
| **Chefredaktion** | Prioritizes topics, maintains editorial memory |
| **Perspektiv-Agent** | Researches the spectrum of positions per topic |
| **Redakteur** | Writes source-based, multi-perspective articles |
| **QA / Faktencheck** | Three-tier verification: VERIFIED / UNVERIFIABLE / PROVABLY FALSE |
| **Bias-Detektor** | Analyzes text for bias across 5 dimensions — marks, never rewrites |

The pipeline is **deterministic**: Python code decides which agent runs when. No LLM decides "what to do next."

## What This Is Not

- Not a chatbot
- Not a content generator
- Not a replacement for investigative journalism
- Not neutral (nothing is) — but **transparent about its biases**

## Architecture

Three core abstractions: **Agent** (configured LLM caller), **Pipeline** (deterministic orchestration), **Tool** (external capabilities). Purpose-built Python framework, async from day one.

[Full architecture →](docs/ARCHITECTURE.md) · [Roadmap →](docs/ROADMAP.md) · [Visualizations →](docs/VISUALIZATIONS.md)

## Project Status

| Phase | Status |
|-------|--------|
| Vision & Concept | ✅ Complete |
| Output Schema (Topic Package v1) | ✅ Complete |
| Visualization System | ✅ Complete |
| Editorial Style Guide | ✅ Complete |
| Framework Architecture | ✅ Complete |
| Repository Setup | ✅ Complete |
| Framework Implementation | 🔜 Next |
| Agent Prompts | 🔜 Planned |
| Live Demo | 🔜 Planned |

## Cost Transparency

Independent Wire runs on commercial AI APIs via OpenRouter. Approximate costs per daily report (7 topics):

| Component | Estimated Cost |
|-----------|---------------|
| Collection & Curation | ~$0.10 |
| Editorial + Research | ~$0.50 |
| Writing (7 articles) | ~$1.00 |
| QA + Bias Detection | ~$0.30 |
| Visualizations | $0.00 (deterministic) |
| **Total per day** | **~$2.00** |

No advertising. No subscriptions. No data sales. Just API costs.

## License

**AGPL-3.0** — the strongest copyleft license available. Anyone who hosts Independent Wire must also open-source their modifications, including changed prompts. This is not a restriction. It is the license doing its job.

## Contributing

This project is in its early stages. The best way to contribute right now:

- Read the [architecture](docs/ARCHITECTURE.md) and [vision paper](docs/VISION.md)
- Open issues with questions or suggestions
- Star the repo to signal interest

---

*Independent Wire — Because transparency is not a feature, it is a promise.*
