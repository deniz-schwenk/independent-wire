# Independent Wire — Visualization System

## Design Decision

Independent Wire does **not** use AI-generated images. No photorealistic illustrations, no Gemini/DALL-E/Midjourney outputs. This is a deliberate philosophical choice, not a technical limitation.

**Why:** AI-generated images simulate a reality that nobody photographed. A photorealistic header image of "EU Parliament voting" creates the illusion of documentary photography where none exists. This directly contradicts Independent Wire's core principle of transparency.

**Instead:** All visuals are **data-driven diagrams** generated deterministically from the structured data in each Topic Package. Same input → same output. No hallucination, no cost, no API dependency.

## Visualization Types

| Type | Derives From | Shows |
|------|-------------|-------|
| **Perspective Spectrum** | `perspectives` | Who says what, how strongly represented |
| **Source Map** | `sources` + `bias_analysis.geographical_bias` | Geographic distribution, missing regions |
| **Divergence Chart** | `divergences` | Where sources contradict each other |
| **Fact Check Diagram** | `sources.claims` | Verification status of all claims |

### Perspective Spectrum
Visualizes positions held by different actors on a topic. Color-coded by representation strength (dominant → emerging). Answers: "What are the different takes on this, and who holds them?"

### Source Map
Shows which countries/regions are represented in the source material and — critically — which are missing. Makes geographical bias visible at a glance. Answers: "Who is speaking, and who is silent?"

### Divergence Chart
Displays explicit contradictions between sources, categorized by type (factual, framing, omission, emphasis) and resolution status. Answers: "Where do sources disagree, and do we know who's right?"

### Fact Check Diagram
Shows verification status of every factual claim. Color-coded: green (verified), yellow (unverifiable), orange (disputed), red (contradicted). Answers: "How solid is the factual basis of this report?"

## Technology

**Mermaid.js** — text-based diagram syntax that:
- Fits directly into JSON (the `visualizations.content` field)
- Renders natively on GitHub, GitHub Pages, and most Markdown viewers
- Is deterministic: same data → same diagram, every time
- Has zero runtime dependencies for generation
- Is human-readable even as raw text

## Implementation

`scripts/generate-visuals.py` replaces the PoC's Designer Agent (LLM) with a deterministic Python script.

```bash
# Generate all visualizations
python3 scripts/generate-visuals.py path/to/topic-package.json

# Generate only one type
python3 scripts/generate-visuals.py path/to/topic-package.json --type perspective_spectrum

# Inject back into the topic package JSON
python3 scripts/generate-visuals.py path/to/topic-package.json --inject
```

## Phase 2+ (Future)

- **D3.js** for interactive visualizations on the website
- **SVG templates** for more complex infographics
- **Geographical Coverage** as a world map visualization
- **Timeline** for narrative tracking across days/weeks
