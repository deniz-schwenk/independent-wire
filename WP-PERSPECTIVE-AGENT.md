# WP-PERSPECTIVE-AGENT — Pipeline Architecture Decision

**Created:** 2026-04-07
**Source:** Strategy session (Deniz + Strategy Claude)
**Status:** Architecture decision needed before demo
**Blocks:** WP-PERSPEKTIV, WP-BIAS, WP-QA scope, Writer prompt, demo rendering

---

## Context

The architect previously recommended deferring the Perspective Agent until after the demo, coupling it to the rendering/visualization layer. The reasoning was pragmatic: Researcher + QA already cover factual divergences and coverage gaps, the Perspective Agent adds complexity (+1 LLM call, +1 prompt, +1 failure point), and without rendering the structured perspective data stays invisible in the JSON.

**We disagree with the deferral. Here's why.**

## The Strategic Argument

The Perspective Agent is not a feature. It is the core differentiator of Independent Wire.

Without it, Independent Wire is a well-made news aggregator with bias labels. With it, Independent Wire delivers what the Vision Paper promises: a structured map of who says what, why, and which voices are missing entirely.

The README now opens with: *"The news you read was chosen for you. This system shows you why — and what's missing."* The Perspective Agent is the component that delivers the "why" and the "what's missing." A demo without it is a demo of the wrong product.

## The Practical Argument

Inserting the Perspective Agent after the demo means rebuilding half the pipeline later:
- Writer prompt needs a rewrite to use perspective data as structured input
- QA scope needs to be redefined (what stays with QA, what moves to Perspective Agent)
- Visualizations (Perspective Spectrum diagram) need to be designed around the data structure
- New bottlenecks will emerge that could have been caught now

We already experienced this with QA — it was overloaded with too many responsibilities and had to be restructured mid-session. Better to get the architecture right now than to cement a half-pipeline and refactor against a published demo.

## The Pipeline Order Question

Current pipeline:
```
Collector → Curator → Editor → Researcher → Writer → QA → Bias Detector
```

Proposed pipeline with Perspective Agent:
```
Collector → Curator → Editor → Researcher → Perspective Agent → Writer → QA / Fact-Check → Bias Detector
```

**Why this order works:**

The Perspective Agent does NOT need fact-checked data. It needs the **source landscape** — who reports what, which positions exist, which stakeholder groups are represented, which are absent. This is an analysis of the *reporting landscape*, not of the facts themselves.

The Writer then receives perspective data as structured input alongside the research, and uses it to structure the article.

QA / Fact-Check then verifies the *finished article* against sources — checking whether the Writer represented the facts correctly.

The Bias Detector runs last, analyzing the finished text for linguistic and structural bias.

## What the Architect Needs to Decide

### 1. Pipeline position — confirmed or revised?

Is `Researcher → Perspective Agent → Writer` the right order? Or is there a reason to place the Perspective Agent elsewhere?

### 2. Scope boundary between Perspective Agent and QA

Both touch "divergences" and "gaps" — but from different angles:

| Concern | Perspective Agent | QA / Fact-Check |
|---------|------------------|-----------------|
| "Reuters says 4,500 — Xinhua says 3,800" | Maps this as a positional divergence between stakeholders | Verifies which number is factually supported |
| "No sources from Sub-Saharan Africa" | Flags as missing stakeholder group / geographic gap | Not its job |
| "Five stakeholder groups exist, this one is missing" | Core responsibility — structured stakeholder mapping | Not its job |
| "The article misquotes a source" | Not its job | Core responsibility |
| "Coverage of this event is framed differently in Arabic vs. English sources" | Maps this as a framing divergence | Not its job |

The architect must define which `divergences` and `gaps` fields in the Topic Package are populated by which agent. No overlap — each field has exactly one owner.

### 3. Writer prompt extension

The Writer currently receives research data as input. With the Perspective Agent, the Writer additionally receives:
- Stakeholder map (actors, positions, interests)
- Perspective spectrum (range of positions, strength of representation)
- Missing voices (which stakeholder types are absent)

The Writer prompt needs to be extended so that the article is **structured around the perspective data** — not just enhanced by it. This is not a minor tweak; it changes how the article is organized.

### 4. Perspective Agent output schema

What does the Perspective Agent produce? Proposed structure (must align with Topic Package schema):

```json
{
  "stakeholders": [
    {
      "actor": "Russian Foreign Ministry",
      "type": "government",
      "position": "...",
      "interest": "...",
      "representation_strength": "strong",
      "source_count": 12
    }
  ],
  "perspective_spectrum": {
    "positions": [...],
    "dominant_framing": "...",
    "counter_framings": [...]
  },
  "missing_voices": [
    {
      "stakeholder_type": "affected_community",
      "description": "...",
      "reason_missing": "..."
    }
  ]
}
```

This structure must be designed so that:
- The Writer can use it as input
- The Mermaid Perspective Spectrum diagram can render it
- The Topic Package schema accommodates it

### 5. Visualization dependency

The Perspective Spectrum diagram from the Vision Paper must work with whatever data structure the Perspective Agent produces. This means the `generate-visuals.py` script and the Perspective Agent output schema must be designed together — not sequentially.

The architect should define the data contract between Perspective Agent output and visualization input as part of this work package.

## What This Does NOT Change

- Collector, Curator, Editor, Researcher — unchanged
- The existing pipeline mechanics (sequential steps, state persistence, error isolation) — unchanged
- The sources.json structure and source tiering — unchanged

## Summary

**Decision:** The Perspective Agent ships before the demo, not after.
**Reason:** It is the core differentiator. A demo without it demonstrates the wrong product.
**Risk:** Adding pipeline complexity before the demo. Mitigated by doing the architecture work now instead of retrofitting later.
**Action needed:** The architect defines the pipeline order, scope boundaries, Writer prompt extension, output schema, and visualization data contract. Then implementation can proceed as discrete work packages.
