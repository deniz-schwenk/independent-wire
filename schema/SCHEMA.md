# Topic Package v1 — Schema Documentation

The **Topic Package** is the atomic output unit of Independent Wire. It is not an article — it is a structured transparency bundle that contains everything about a single topic.

## Design Principle

The article is one possible *rendering* of the Topic Package — not the Package itself. The same data can produce a website article, a podcast briefing, a newsletter, or an API response. Different formats, same transparent data foundation.

## Structure Overview

| Section | Purpose |
|---------|--------|
| `metadata` | Title, date, status, priority, tags |
| `sources` | Every source used, with full URLs and claims |
| `perspectives` | Spectrum of positions — who says what |
| `divergences` | Where sources contradict each other |
| `gaps` | What's missing from the coverage |
| `article` | The rendered text (one possible output) |
| `bias_analysis` | 5-dimension bias analysis with scores |
| `visualizations` | Mermaid.js diagrams (deterministic) |
| `transparency` | Why this topic, what was discarded, what it cost |

## ID Format

`tp-YYYY-MM-DD-NNN` — e.g., `tp-2026-03-27-001`

## Status Flow

```
draft → review → published
              → rejected
              → failed (pipeline error)
```

## Verification Model (Three-Tier)

Every factual claim in every source is classified:

| Status | Meaning | Rule |
|--------|---------|------|
| `verified` | Confirmed by independent source | Must have corroborating evidence |
| `unverifiable` | Cannot be confirmed or denied | Default for claims without counter-evidence |
| `disputed` | Contradicted by another source | Both sides documented |
| `provably_false` | Demonstrably incorrect | **Only** with counter-evidence, never on absence of evidence |

## Bias Scores

Each bias dimension is scored 0.0–1.0:
- **0.0** — No detected bias in this dimension
- **0.3** — Minor, common patterns
- **0.6** — Notable bias that affects interpretation
- **1.0** — Severe bias that dominates the content

Scores are not judgments — they are measurements. The Bias-Detektor marks; it never rewrites.

## Schema File

The formal JSON Schema is at [`topic-package-v1.json`](topic-package-v1.json).
