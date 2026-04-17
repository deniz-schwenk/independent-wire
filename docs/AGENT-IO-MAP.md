# Independent Wire — Agent IO Map (Ist vs. Soll)

**Created:** 2026-04-09
**Zweck:** Für jeden Agent: Was braucht er? Was erzeugt er? Was reicht er sinnlos durch?

---

## Grundprinzip (Deniz, Session 6)

> Für jeden Agent bestimmen: A) was braucht er, B) was soll er erzeugen.
> Den Rest leiten wir immer mit Python weiter.
> Wenn ein Agent "durchreicht", erzeugt er Tokens ohne Mehrwert.

---

## 1. Curator (Gemini Flash, 1×/Run)

### INPUT (Ist = Soll)
```
~1.400 Findings (title, url, source, published_at, summary)
```

### OUTPUT
| Key | Ist | Soll | Originär? |
|-----|-----|------|-----------|
| topics[].title | ✅ | ✅ | ✅ Ja — LLM clustert |
| topics[].relevance_score | ✅ | ✅ | ✅ Ja — LLM bewertet |
| topics[].summary | ✅ | ✅ | ✅ Ja — LLM fasst zusammen |
| topics[].source_ids | ✅ | ✅ | ✅ Ja — LLM ordnet zu |
| topics[].geographic_coverage | ❌ | ❌ | Python berechnet (bereits so) |
| topics[].topic_slug | ❌ | ❌ | Python berechnet (bereits so) |

**Status: ✅ Schon optimal.** Python-Enrichment läuft bereits via `_enrich_curator_output()`.

---

## 2. Editor (Opus, 1×/Run)

### INPUT (Ist = Soll)
```
Curator topics[] (enriched)
```

### OUTPUT
| Key | Ist | Soll | Originär? |
|-----|-----|------|-----------|
| assignments[].title | ✅ | ✅ | ✅ Ja (kann vom Curator-Titel abweichen) |
| assignments[].topic_slug | ✅ | ✅ | ✅ Ja |
| assignments[].priority | ✅ | ✅ | ✅ Ja — LLM priorisiert |
| assignments[].selection_reason | ✅ | ✅ | ✅ Ja — LLM begründet |
| assignments[].source_ids | ✅ | ✅ | ✅ Ja — LLM wählt aus |

**Status: ✅ Schon optimal.** Kein Durchreichen.

---

## 3. Researcher Plan (Gemini Flash, 3×/Run)

### INPUT (Ist = Soll)
```
Editor assignment (title, topic_slug, source_ids, selection_reason)
```

### OUTPUT
| Key | Ist | Soll | Originär? |
|-----|-----|------|-----------|
| queries[].query | ✅ | ✅ | ✅ Ja — LLM generiert multilingual |
| queries[].language | ✅ | ✅ | ✅ Ja |

**Status: ✅ Schon optimal.**

---

## 4. Researcher Assemble (Gemini Flash, 3×/Run)

### INPUT (Ist = Soll)
```
Assignment + Search results (from Python execution)
```

### OUTPUT
| Key | Ist | Soll | Originär? |
|-----|-----|------|-----------|
| sources[].id, url, title, outlet, language, country | ✅ | ✅ | ✅ Ja — LLM strukturiert |
| sources[].summary | ✅ | ✅ | ✅ Ja — LLM fasst zusammen |
| sources[].actors_quoted[] | ✅ | ✅ | ✅ Ja — LLM extrahiert |
| preliminary_divergences[] | ✅ | ✅ | ✅ Ja — LLM erkennt |
| coverage_gaps[] | ✅ | ✅ | ✅ Ja — LLM erkennt |
| research_queries[] | ✅ | ❓ | Durchgereicht von Plan-Phase |
| languages_searched[] | ✅ | ❌ | Python kann aus queries[] ableiten |

**Einsparung:** `languages_searched` per Python berechnen. Marginal.

---

## 5. Perspektiv (Opus, 3×/Run)

### INPUT (Ist = Soll)
```
Assignment + Research dossier (sources, actors_quoted, preliminary_divergences)
```

### OUTPUT
| Key | Ist | Soll | Originär? |
|-----|-----|------|-----------|
| stakeholders[] | ✅ | ✅ | ✅ Ja — LLM mappt Akteure |
| missing_voices[] | ✅ | ✅ | ✅ Ja — LLM erkennt Lücken |
| framing_divergences[] | ✅ | ✅ | ✅ Ja — LLM analysiert Framing |

**Status: ✅ Schon optimal.** Alles originär.

---

## 6. ⚠️ Writer (Opus, 3×/Run + 9× Corrections = 12 Calls)

### INPUT (Ist)
```json
{
  "assignment": { "title", "topic_slug", "selection_reason", "source_ids" },
  "perspective_analysis": { "stakeholders", "missing_voices", "framing_divergences" },
  "research_dossier": { "sources", "preliminary_divergences", "coverage_gaps" }
}
```

### INPUT (Soll) — unverändert
Writer BRAUCHT perspective_analysis und research_dossier, weil er den Artikel daraus baut.
Hier gibt es nichts zu sparen am Input.

### OUTPUT (Ist) — gemessen aus 05-writer-*.json, Lauf 10
```json
{
  "id": "...",                    // ❌ Durchgereicht (von Assignment)
  "version": "1.0",              // ❌ Konstante
  "status": "review",            // ❌ Konstante
  "metadata": { ... },           // ❌ Durchgereicht (von Assignment)
  "sources": [],                 // ❌ LEER (Writer hat seine sources[] im article Block)
  "perspectives": [ ... ],       // ❌ DURCHGEREICHT von Perspektiv-Agent!
  "divergences": [ ... ],        // ❌ DURCHGEREICHT von Perspektiv-Agent!
  "gaps": [ ... ],               // ❌ DURCHGEREICHT von Perspektiv-Agent!
  "article": {                   // ✅ ORIGINÄR
    "headline": "...",
    "subheadline": "...",
    "body": "...",
    "summary": "...",
    "sources": [ ... ],
    "word_count": 1329
  },
  "bias_analysis": { ... },      // ❌ DURCHGEREICHT + teilweise leer
  "visualizations": [],          // ❌ LEER
  "transparency": { ... }        // ❌ Durchgereicht
}
```

### OUTPUT (Soll) — nur originäre Felder
```json
{
  "headline": "...",
  "subheadline": "...",
  "body": "...",
  "summary": "...",
  "sources": [
    { "id", "url", "title", "outlet", "language", "country" }
  ]
}
```

