# Independent Wire — Visualization System

**Status:** Design specification — **not yet implemented in V2.** The V2 render layer (`src/render.py`) currently omits visualizations; this document is the design for that workstream when it activates. The "no AI images" decision below, however, is already in force across the whole project.

## Design Decision

Independent Wire does **not** use AI-generated images. No photorealistic illustrations, no Gemini / DALL·E / Midjourney outputs. This is a deliberate philosophical choice, not a technical limitation.

**Why:** AI-generated images simulate a reality that nobody photographed. A photorealistic header image of "EU Parliament voting" creates the illusion of documentary photography where none exists. That directly contradicts Independent Wire's core principle of transparency.

**Instead:** all visuals will be **data-driven diagrams** generated deterministically from the structured data in each Topic Package. Same input → same output. No hallucination, no cost, no API dependency.

## Planned visualization types

| Type | Derived from | Shows |
|---|---|---|
| **Perspective Spectrum** | position clusters | Who says what, how strongly represented |
| **Source Map** | source geography + balance | Geographic distribution, missing regions |
| **Divergence Chart** | documented divergences | Where sources contradict each other |
| **Fact-Check Diagram** | QA verification status | How solid the factual basis is |

### Perspective Spectrum
Positions held by different actors on a topic, colour-coded by representation strength (dominant → emerging). Answers: "What are the different takes, and who holds them?"

### Source Map
Which countries/regions are represented in the source material and — critically — which are missing. Makes geographical bias visible at a glance. Answers: "Who is speaking, and who is silent?"

### Divergence Chart
Explicit contradictions between sources, categorized by type (factual, framing, omission, emphasis) and resolution status. Answers: "Where do sources disagree, and do we know who's right?"

### Fact-Check Diagram
Verification status of factual claims, colour-coded: verified / unverifiable / disputed / contradicted. Answers: "How solid is the factual basis of this report?"

## Technology

**Mermaid.js** — text-based diagram syntax that:
- fits directly into the Topic Package JSON,
- renders natively on GitHub, GitHub Pages, and most Markdown viewers,
- is deterministic: same data → same diagram, every time,
- has zero runtime dependencies for generation,
- stays human-readable as raw text.

## Implementation status

The V2 render layer omits visualizations by design — there is no visualization bus slot yet, and `src/render.py` documents it as a future workstream. A PoC-era generator (`scripts/generate-visuals.py`) survives from V1 as reference, but it predates the V2 schema and is not wired into the pipeline; treat it as a sketch, not a working component. When this workstream activates, the generator will be rebuilt deterministically against the V2 Topic Package schema and injected as a dedicated, visibility-marked bus slot.

## Phase 2+ (future)

- **D3.js** for interactive visualizations on the website.
- **SVG templates** for more complex infographics.
- **Geographical coverage** as a world-map visualization.
- **Timeline** for narrative tracking across days and weeks.
