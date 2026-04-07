# Independent Wire — Task Tracker

**Erstellt:** 2026-03-30
**Aktualisiert:** 2026-04-06
**Zweck:** Living Document — wird nach jeder Session aktualisiert

---

## Erledigte Arbeitspakete

| WP | Status | Beschreibung |
|----|--------|-------------|
| WP-AGENT | ✅ | Agent class: async LLM calls, tool loop, retry logic |
| WP-TOOLS | ✅ | Tool system: web_search, web_fetch, file_ops, ToolRegistry |
| WP-TOOLS-v2 | ✅ | Multi-provider search: Perplexity, Brave, Grok, DuckDuckGo |
| WP-TOOLS-v3 | ✅ | Ollama integration: local, ollama_cloud, x_search_tool |
| WP-PIPELINE | ✅ | Pipeline: sequential steps, state persistence, error isolation |
| WP-STRUCTURED-RETRY | ✅ | Retry logic for failed JSON parsing |
| WP-AGENTS | ✅ | System prompts for Collector, Curator, Editor, Writer |
| WP-INTEGRATION | ✅ | First end-to-end pipeline run (2/3 topics produced) |
| WP-RSS | ✅ | RSS/API feeds: 21 sources in config/sources.json, fetch_feeds.py, Pipeline merges with Collector output |
| WP-DEBUG-OUTPUT | ✅ | Step-by-step debug JSON per pipeline step (01-collector-raw.json etc.) |
| WP-REASONING | ✅ | Configurable reasoning effort per agent (None/True/False/"low"/"medium"/"high") |
| WP-RESEARCH | ✅ | Research Agent: mehrsprachige Tiefenrecherche zwischen Editor und Writer. Lauf 3: 5-8 Sprachen/Topic statt 100% EN |
| WP-PARTIAL-RUN | ✅ | `--from`/`--topic`/`--reuse` Flags für run.py. Writer-only Test: 2 min statt 30 min |
| WP-QA | ✅ | QA-Analyze (vereinfacht) + Writer-Correction + Python-Verify. Verification Card entfernt, QA-Rewrite eliminiert. Lauf 5: 1 Korrektur, 3 Divergenzen, 4 Gaps. |

## Erledigte Fixes

| Fix | Status | Beschreibung |
|-----|--------|-------------|
| Feed-Fixes | ✅ | 8 kaputte Feeds gefixt. Alle Google News Proxies entfernt. |
| P-01–P-05 | ✅ | Collector: date-awareness, YouTube/Wiki/social ban, best-effort multilingual, no dup URLs. Writer: Wikipedia only for background |
| F-01–F-05 | ✅ | 30s delay, date in Editor msg, code-fence parsing, model correction, language diversity warning |
| P-06 | ✅ | `divergences` und `gaps` werden durch QA-Analyze befüllt |
| QF-01 | ✅ | max_tokens Default auf 32768 (vorher 8192) |
| QF-02 | ✅ | Token-Tracking: run-*-stats.json mit tokens_used, duration_seconds pro Agent |
| QF-03 | ✅ | Warning wenn QA-Analyze leeres Output liefert |
| QA-Simplify | ✅ | Verification Card entfernt, QA-Rewrite eliminiert, Writer-Correction + Python-Verify eingeführt. |

## Bald umsetzen (nächste Session)

| # | Typ | Bereich | Fix | Priorität |
|---|-----|---------|-----|-----------|
| QF-04 | Agent | Alle | max_tokens Default von 32768 auf **65536** erhöhen. Headroom für wachsende Dossiers und komplexere Topics. Einzeiler in `src/agent.py`. | 🔴 Hoch |
| P-07 | Prompt | QA-Analyze | Wikipedia-Regel als RULE 5 ergänzen. Writer verbietet Wikipedia für Claims/Analyse, QA muss dagegen prüfen (Ungarn-Artikel hatte Wikipedia als src-023 für Polling). | 🔴 Hoch |
| P-08 | Pipeline | Writer | Quellen-Anzahl im Meta-Transparenz-Absatz durch Python setzen statt LLM. Systematischer Zählfehler (25 vs 20, 29 vs 24). | 🟡 Mittel |

## Nächste Arbeitspakete (Reihenfolge = Priorität)

| WP | Priorität | Beschreibung | Abhängig von |
|----|-----------|-------------|--------------|
| WP-CACHING | 🟢 Klein | Prompt Caching via OpenRouter für GLM5-turbo und Mimo-V2-Pro. Provider-agnostisch: funktioniert mit und ohne Caching. | — |
| WP-PERSPEKTIV | 🟡 Mittel | Perspektiv-Agent: recherchiert Spektrum der Positionen pro Thema | WP-RESEARCH |
| WP-MEMORY | 🟢 Klein | Agent Memory Loading/Saving (Editor kennt bisherige Berichterstattung) | — |

## Zukünftige Arbeitspakete (H2)

| WP | Beschreibung | Status |
|----|-------------|--------|
| WP-BIAS | Bias-Detektor: analysiert fertigen Text auf 5 Bias-Dimensionen | ⬜ Offen |
| WP-TELEGRAM | Telegram-Notifications + Gating (gate_handler Hook ist ready) | ⬜ Offen |
| WP-VISUALS | generate-visuals.py Integration (Mermaid-Diagramme aus Topic Packages) | ⬜ Offen |
| WP-SOCIAL | Social-Media-Agent: separater Agent zur Quellenanreicherung (X, YouTube, Instagram) vor dem Writer | ⬜ Offen |
| WP-WEBSITE | GitHub Pages für independentwire.org | ⬜ Offen |
| WP-DNS | DNS-Konfiguration Cloudflare + .de/.eu Domains | ⬜ Offen |

## Erkenntnisse aus den Pipeline-Läufen

### Lauf 1 (2026-03-30)
**Daten:** 39 Findings → 3 Topics → 2 produziert, 1 failed (Rate-Limit)
**Laufzeit:** 19 Minuten | **Modelle:** minimax-m2.7 + glm-5 via OpenRouter

### Lauf 2 (2026-03-31)
**Daten:** 38 Collector + 445 RSS = 483 Findings → 3 Topics → 3/3 produziert, 0 failed
**Laufzeit:** 19.5 Minuten

### Lauf 3 (2026-04-05) — mit Research Agent
**Daten:** 3 Topics → 3/3 produziert, 0 failed
**Laufzeit:** 29.6 Minuten
**Researcher-Ergebnisse:** 5-8 Sprachen/Topic, 18-38 Quellen, 76-85% non-English Queries.

### Lauf 4 (2026-04-05) — QA (komplexe Version, vor Vereinfachung)
**Daten:** 1 Topic (Iran-Konflikt), QA-only Partial Run
**Ergebnisse:** 30 Claims geprüft, 2 Korrekturen (Subheadline + Source Count)
**Problem:** QA-Analyze mit Verification Card: 29.170 Tokens, ~8 min. Bei 2/3 Folge-Läufen: leeres `{}` (JSON-Parsing-Fehler wegen zu großem Output).
**Erkenntnis:** Verification Card ist Haupttreiber der Komplexität → vereinfacht in TASK-QA-SIMPLIFY.

### Lauf 5 (2026-04-06) — QA (vereinfachte Version)
**Daten:** 1 Topic (Ungarn-Wahl), QA-only Partial Run gegen unkorrigierten Lauf-3-Output
**Tokens:** QA-Analyze 20.049 (70s) + Writer-Correction 15.836 (32s) = 35.885 gesamt (102s)
**Ergebnisse:**
- 1 Korrektur: "25 sources" → "20 sources" (systematischer Writer-Zählfehler)
- 3 Divergenzen: Kaczyński-Orbán Verbindung fehlt (omission), Diaspora-Framing (framing), EU-Gelder vs. Innenpolitik (emphasis)
- 4 Gaps: rumänische Quellen, slowakisch/tschechisch, Kaczyński-Verbindung, Business-Community
- Python-Verify: 1/1 Korrekturen erfolgreich angewandt

**Vergleich alt vs. neu:** 29K Tokens + 480s + leeres Output → 36K Tokens + 102s + vollständiges Ergebnis.

---

*Dieses Dokument wird nach jeder Session aktualisiert. Änderungen per Git nachvollziehbar.*