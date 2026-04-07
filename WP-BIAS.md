# WP-BIAS — Bias Transparency Card (Hybrid)

**Created:** 2026-04-07
**Status:** Ready for implementation
**Priority:** 🔴 High — core differentiator per Vision Paper
**Estimated effort:** 1-2 hours with Claude Code

## Design Principle

The Bias Card is NOT a separate analysis that duplicates what Perspektiv and QA 
already do. It is a **synthesis layer** that aggregates existing pipeline data 
into a reader-facing transparency document, plus one genuinely new contribution: 
language analysis of the article text.

Two steps:
1. **Python (deterministic, 0 tokens)** — aggregate source balance, perspectives, 
   divergences, coverage gaps from existing pipeline outputs
2. **Slim LLM call (~5-8K tokens)** — scan the article text for linguistic bias 
   patterns and write a plain-language reader note

## What Already Exists (no re-analysis needed)

| Data | Source | Field |
|------|--------|-------|
| Stakeholder map | Perspektiv Agent | `perspective_analysis.stakeholders` |
| Missing voices | Perspektiv Agent | `perspective_analysis.missing_voices` |
| Framing divergences | Perspektiv Agent | `perspective_analysis.framing_divergences` |
| Factual divergences | QA-Analyze | `qa_analysis.divergences` |
| Coverage gaps | Researcher | `research_dossier.coverage_gaps` |
| Source list | Writer | `article.sources` |

## What Is New (LLM required)

| Data | Why LLM is needed |
|------|-------------------|
| Language bias findings | Pattern-matching in natural language text |
| Reader note | Synthesis into plain-language summary |

## Step 1 — Python: build_bias_card()

New function in `src/pipeline.py`. Takes the existing pipeline data and produces 
the structural half of the Bias Card deterministically.

```python
def _build_bias_card(
    article: dict,
    perspective_analysis: dict,
    qa_analysis: dict,
    research_dossier: dict,
) -> dict:
    """Build the deterministic portion of the Bias Transparency Card."""
    
    writer_sources = article.get("sources", [])
    researcher_sources = research_dossier.get("sources", [])
    stakeholders = perspective_analysis.get("stakeholders", [])
    
    # Source balance — count by language, country, type
    by_language = {}
    by_country = {}
    for s in writer_sources:
        lang = s.get("language", "unknown")
        by_language[lang] = by_language.get(lang, 0) + 1
        country = s.get("country", "unknown")
        by_country[country] = by_country.get(country, 0) + 1
    
    # Geographic coverage — compare writer vs researcher
    writer_countries = {s.get("country", "") for s in writer_sources}
    researcher_countries = {s.get("country", "") for s in researcher_sources}
    missing_countries = sorted(researcher_countries - writer_countries - {""})
    
    # Perspective coverage — how many stakeholders made it into article
    # (check if any rsrc-NNN from stakeholder source_ids maps to a src-NNN)
    
    return {
        "source_balance": {
            "total": len(writer_sources),
            "by_language": by_language,
            "by_country": by_country,
        },
        "geographic_coverage": {
            "represented": sorted(writer_countries - {""}),
            "missing_from_dossier": missing_countries,
        },
        "perspectives": {
            "total_identified": len(stakeholders),
            "missing_voices": perspective_analysis.get("missing_voices", []),
        },
        "framing_divergences": perspective_analysis.get("framing_divergences", []),
        "factual_divergences": qa_analysis.get("divergences", []),
        "coverage_gaps": research_dossier.get("coverage_gaps", []),
    }
```

This produces 0 tokens, runs in milliseconds, and contains no guesswork.


## Step 2 — LLM: Language Analysis + Reader Note

A slim agent (`bias_language`) receives ONLY the article body text and the 
Python-built bias card. It does two things:

1. Scan the article text for linguistic bias patterns (evaluative adjectives, 
   emotionalizing, passive constructions that obscure responsibility, loaded 
   terms, hedging, intensifiers)
2. Write a 2-3 sentence reader_note in plain language that synthesizes 
   everything — the Python-built structural data AND its own language findings

### Agent Configuration
- **Name:** bias_language
- **Model:** z-ai/glm-5
- **Tools:** None
- **Temperature:** 0.1
- **Prompt:** agents/bias_detector/AGENTS.md

### Input
- article body text (string, not the full article object — just the body)
- Python-built bias_card (the output from Step 1)

### Output
```json
{
  "language_bias": {
    "findings": [
      {
        "excerpt": "the devastating attack",
        "issue": "evaluative_adjective",
        "explanation": "'devastating' is editorial characterization, not sourced."
      }
    ],
    "severity": "low"
  },
  "reader_note": "This article draws on 22 sources in 7 languages. Perspectives 
   from affected civilian populations are represented through statistics but not 
   through direct testimony. Gulf Arab states and the European Union are absent. 
   Casualty figures vary significantly across sources and have not been 
   independently verified."
}
```

## Final Bias Card Assembly (Python)

After the LLM returns, Python merges Step 1 + Step 2:

```python
bias_card = _build_bias_card(article, perspective_analysis, qa_analysis, dossier)
# ... LLM call for language analysis ...
bias_card["language_bias"] = llm_result.get("language_bias", {})
bias_card["reader_note"] = llm_result.get("reader_note", "")
```

The merged result goes into `topic_package.bias_analysis`.


## Debug Output

```
08-bias-card-{slug}.json    # The complete merged Bias Card
```

## Token Budget

| Component | Tokens |
|-----------|--------|
| Python build_bias_card | 0 |
| LLM language analysis + reader_note | ~5,000-8,000 |
| **Total per topic** | **~5,000-8,000** |

Compare: a full Bias Detector agent would cost ~20,000-25,000 tokens per topic.

## Claude Code Instruction

```
Read WP-BIAS.md in the repo root. This implements the Bias Transparency Card 
as a hybrid: Python aggregation + slim LLM call.

IMPORTANT: Do NOT write the agent prompt. It will be provided separately 
at agents/bias_detector/AGENTS.md.

Implementation tasks:

1. Create directory agents/bias_detector/

2. scripts/run.py — Add bias_language agent registration:
   "bias_language": Agent(
       name="bias_language",
       model="z-ai/glm-5",
       prompt_path=str(agents_dir / "bias_detector" / "AGENTS.md"),
       tools=[],
       temperature=0.1,
       provider="openrouter",
   )

3. src/pipeline.py — Add _build_bias_card() function:
   A pure Python function that takes article, perspective_analysis, qa_analysis, 
   and research_dossier as inputs and returns a dict with:
   - source_balance (total, by_language, by_country — counted from article.sources)
   - geographic_coverage (represented countries from article, missing countries 
     that are in researcher sources but not in article sources)
   - perspectives (total_identified from stakeholders count, missing_voices 
     from perspective_analysis)
   - framing_divergences (directly from perspective_analysis)
   - factual_divergences (directly from qa_analysis.divergences)
   - coverage_gaps (directly from research_dossier)
   
   This function uses NO LLM calls. It is pure data aggregation.

4. src/pipeline.py — Replace the existing Bias Detector placeholder in 
   _produce_single() with the hybrid approach:
   
   a) Call _build_bias_card() with the existing pipeline data (0 tokens)
   b) If bias_language agent is registered:
      - Call it with the article body text + the Python-built bias_card as context
      - Merge the LLM result (language_bias + reader_note) into the bias_card
   c) Write debug output: 08-bias-card-{slug}.json
   d) Set bias_analysis = merged bias_card
   
   If no bias_language agent is registered, the Python-built card is used as-is 
   (without language_bias and reader_note fields).

5. src/pipeline.py — Add "bias_detector" to the step_order list after 
   "qa_analyze" for --from/--to support. When running --from bias_detector, 
   load the article, perspektiv, qa, and researcher outputs from debug files.

6. Track the LLM call with self._track_agent().

Do NOT implement yet — wait for the prompt file to be created first.
Prepare the code infrastructure so that once the prompt is in place,
a test run works immediately.

Test (after prompt is provided):
  python scripts/run.py --from bias_detector --to bias_detector --reuse 2026-04-07 --topic 1
```
