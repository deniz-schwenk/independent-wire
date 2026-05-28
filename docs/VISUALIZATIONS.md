# Independent Wire — Visualization System

## Design Decision

Independent Wire does **not** use AI-generated images. No photorealistic illustrations, no Gemini / DALL·E / Midjourney outputs. This is a deliberate philosophical choice, not a technical limitation.

**Why:** AI-generated images simulate a reality that nobody photographed. A photorealistic header image of "EU Parliament voting" creates the illusion of documentary photography where none exists. That directly contradicts Independent Wire's core principle of transparency.

**Instead:** all visuals are **data-driven diagrams**, generated deterministically from the structured data in each Topic Package. Same input → same output. No hallucination, no cost, no API dependency. Visuals are produced at HTML-render time — they are not stored as a field in the Topic Package JSON.

## Live visualizations

### Source Distribution — "Evidence Terrain"

A deterministic topographic SVG of where a Topic Package's sources come from. Per-country source counts are aggregated into seven World Bank region buckets (`src/region_buckets.py`); each active bucket is drawn as an isolated contour "mountain" whose height and ring count grow with its source count. A left-hand legend lists every region as `N | NAME` (zero-count regions shown dimmed — e.g. Sub-Saharan Africa at 0), horizontal connectors link each legend row to its mountain, and a `{N} TOTAL SOURCES` footer sits beneath the terrain. A colour-coded country-badge grid accompanies it.

How it's drawn: each region samples its own Gaussian on a small grid; marching squares extracts isolines at level sets scaled to that region's peak; polylines are chained and depth-sorted back-to-front (painter's algorithm), then projected obliquely to screen. Pure Python, no plotting library.

- Generator: `scripts/evidence_terrain.py` → `render_evidence_terrain(by_country) -> str` (returns a complete `<svg>`).
- Embedded by: `scripts/render.py` → `build_source_map`, which rebuilds the per-country counts from the **post-prune** source set so the "TOTAL SOURCES" figure matches the report's meta bar.

This is the **Source Map** type from the vision paper, implemented — and it makes geographical bias visible at a glance: who is speaking, and who is silent.

### Source Balance by Language — bar chart

A deterministic HTML/CSS horizontal bar chart in the bias card, showing the number of sources per language (`build_bias_card` in `scripts/render.py`). Part of the bias-transparency surface.

## Technology

Hand-rolled deterministic SVG (marching squares + oblique projection) and HTML/CSS bars — **not** a charting library and **not** Mermaid. The earlier PoC plan to emit Mermaid into a `visualizations` JSON field (`scripts/generate-visuals.py`) is superseded: that script predates the V2 schema and is unwired. Visuals are now rendered straight into the published HTML, deterministically — same data → same diagram, every time, with zero runtime dependency.

## Planned visualization types

The data behind these already exists in every Topic Package and is surfaced today as structured sections (positions, divergences, QA verification status); dedicated *diagram* renderings of them are future work:

- **Perspective Spectrum** — positions held by different actors, by representation strength.
- **Divergence Chart** — explicit source contradictions, by type and resolution status.
- **Fact-Check Diagram** — verification status of factual claims.

## Phase 2+ (future)

- **D3.js** for interactive visualizations on the website.
- **Geographical coverage** as a literal world-map projection (the terrain is region-bucketed, not a geographic map).
- **Timeline** for narrative tracking across days and weeks.
