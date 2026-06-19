# BACKLOG — German render label map (controlled vocabularies)

Status: OPEN
Raised: 2026-06-16
Origin: translation-stage scoping (Q7 decision, extended). See
config/de_exonyms.json + the translation workstream.

## What

A single frozen config file (proposed config/de_render_labels.json)
holding the German rendering of every CONTROLLED VOCABULARY in a Topic
Package — the closed enum sets and fixed structural labels that are
identical across every TP and must never pass through the translation
LLM. The German RENDERER applies this map at HTML-build time.

## Scope (verified against production TPs 2026-06-1x)

- actor/stakeholder types (9): government, civil_society,
  affected_community, military, academia, international_org, industry,
  judiciary, legislature
- divergence types (4): factual, framing, emphasis, omission
- bias language issues (6): evaluative_adjective, loaded_term,
  emotionalizing, hedging, passive_obscuring, intensifier
- position classifiers: stated, reported, mentioned, editorial
  position attributed to
- the source-distribution country tags under the geographic SVG
- the bias dimension names (language, source, framing, selection,
  geographical)
- everything in the expandable "about this label" section
- any other fixed UI/structural label in the render path

## Why separate from the translation stage

These are not prose — they are keys with one correct German label
each. Translating them per-run via the LLM would reintroduce drift and
cost for zero benefit. Deterministic-before-LLM: a fixed map is pure
code. Guarantees day-over-day consistency the translation stage cannot.

## Work

1. Enumerate every controlled vocabulary + the "about this label"
   copy from the current English render path (read render.py + the
   templates).
2. Operator-curated German for each (these are house-voice product
   labels, not mechanical translation — the operator owns the wording).
3. Wire the German renderer to look up labels from this map; English
   render path unchanged.

## Dependency

Lands in the German render path, which is downstream of the
translation stage going to production. Build after the translation
stage is validated and cut over, OR in parallel since it touches
different code. No blocker on the translation tuning loop.
