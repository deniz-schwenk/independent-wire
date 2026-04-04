# Independent Wire — Task Tracker

**Erstellt:** 2026-03-30
**Aktualisiert:** 2026-04-04
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


## Nächste Arbeitspakete (Reihenfolge = Priorität)

| WP | Priorität | Beschreibung | Abhängig von |
|----|-----------|-------------|--------------|
| WP-RESEARCH | 🟡 Mittel | Research Agent: themengesteuerte Tiefenrecherche in Originalsprachen zwischen Editor und Writer | WP-INTEGRATION |

## Feed-Fixes (aus zweitem Lauf 2026-03-31)

8 von 21 Feeds failed. URLs müssen gefixt oder ersetzt werden.

| Feed | Problem | Status |
|------|---------|--------|
| Tehran Times | Timeout | ⬜ URL prüfen/ersetzen |
| Daily Nation (Kenya) | 403 Forbidden | ⬜ Alternative URL suchen |
| Guardian Nigeria | 403 Forbidden | ⬜ Alternative URL suchen |
| PTI | Invalid XML | ⬜ URL prüfen/ersetzen |
| El Universal (Mexico) | 404 Not Found | ⬜ Alternative URL suchen |
| Xinhua | 0 entries (Feed leer) | ⬜ Feed-URL prüfen |
| TASS | 0 entries (Feed leer) | ⬜ Feed-URL prüfen |
| ReliefWeb | 0 entries (202 Accepted) | ⬜ API statt RSS testen |

## Prompt-Fixes (aus Qualitätsauswertung 2026-03-30)

Diese Fixes betreffen Agent-Prompts, nicht Code. Können einzeln oder gebündelt umgesetzt werden.

| # | Agent | Problem | Fix | Status |
|---|-------|---------|-----|--------|
| P-01 | Collector | Sucht mit veralteten Jahreszahlen ("economy news 2024") | Datum im Pipeline-Message + Prompt: "search for TODAY's news, do NOT use past years" | ✅ Erledigt |
| P-02 | Collector | YouTube als Quelle (4 von 39 Findings) | Explizite Blocklist: YouTube, Wikipedia, Instagram, TikTok, Reddit, X/Twitter, Facebook | ✅ Erledigt |
| P-03 | Collector | Alle 39 Findings ausschließlich auf Englisch | Collector: "best effort" nicht-englische Queries. Echte Lösung: WP-RESEARCH (dedizierter Research Agent) + WP-RSS (mehrsprachige Feeds) | ✅ Angepasst |
| P-04 | Collector | Doppelte URLs (verschiedene Findings, gleiche URL) | Regel: "Each source_url must be unique. Do not extract multiple findings from the same article." | ✅ Erledigt |
| P-05 | Writer | Wikipedia als Primärquelle (Kongo src-001) | Wikipedia nur für Hintergrundfakten (Bevölkerung, Geographie), nicht als Nachrichtenquelle | ✅ Erledigt |
| P-06 | Writer | `divergences` und `gaps` Felder werden nicht befüllt | Verschoben auf WP-QA — QA-Agent befüllt diese Felder nach Artikelprüfung | ↗️ Verschoben |


## Pipeline-Fixes (aus erstem Lauf)

| # | Bereich | Problem | Fix | Status |
|---|---------|---------|-----|--------|
| F-01 | pipeline.py | Rate-Limiting bei 3+ Writer Topics (429 von glm-5) | 30s Delay zwischen Topics in produce() | ✅ Erledigt |
| F-02 | pipeline.py | Topic-IDs mit falschem Datum (2025-01-09 statt 2026-03-30) | Datum explizit im Editor-Message übergeben | ✅ Erledigt |
| F-03 | pipeline.py | _extract_list/_extract_dict: Markdown Code-Fences nicht gehandled | _strip_code_fences() + dict-unwrap Fallback | ✅ Erledigt |
| F-04 | run.py | Claude Code hat eigenmächtig auf gpt-4o-mini umgestellt | Korrigiert: minimax/minimax-m2.7 + z-ai/glm-5 via OpenRouter | ✅ Erledigt |
| F-05 | pipeline.py | Keine Warnung wenn alle Quellen einsprachig sind | Deterministischer Check in verify(): Warnung wenn alle Quellen im Topic Package dieselbe Sprache haben | ✅ Erledigt |

## Zukünftige Arbeitspakete (H2)

| WP | Beschreibung | Status |
|----|-------------|--------|
| WP-QA | QA / Fact-Check Agent: verifiziert Zahlen/Fakten, befüllt divergences + gaps | ⬜ Offen |
| WP-PERSPEKTIV | Perspective Agent: recherchiert Spektrum der Positionen pro Thema | ⬜ Offen |
| WP-BIAS | Bias Detector: analysiert fertigen Text auf 5 Bias-Dimensionen | ⬜ Offen |
| WP-TELEGRAM | Telegram-Notifications + Gating (gate_handler Hook ist ready) | ⬜ Offen |
| WP-MEMORY | Agent Memory Loading/Saving (Editor kennt bisherige Berichterstattung) | ⬜ Offen |
| WP-VISUALS | generate-visuals.py Integration (Mermaid-Diagramme aus Topic Packages) | ⬜ Offen |
| WP-SOCIAL | Social-Media-Agent: separater Agent zur Quellenanreicherung (X, YouTube, Instagram) vor dem Writer | ⬜ Offen |
| WP-WEBSITE | GitHub Pages für independentwire.org | ⬜ Offen |
| WP-DNS | DNS-Konfiguration Cloudflare + .de/.eu Domains | ⬜ Offen |
| WP-SOURCE-TIERING | `sources.json` Schema erweitern: `tier` (1-4), `source_type`, `state_affiliated`, `editorial_independence` Felder. Bestehende Quellen migrieren, World Monitor Feed-Katalog als Recherche-Startpunkt für Erweiterung auf 40+ | ⬜ Offen |
| WP-DEDUP | Collector-Deduplizierung: exakte URL-Dedup + >95% Text-Similarity als Pipeline-Step. Bewusst KEIN Jaccard <95% — Framing-Unterschiede sind analytisch wertvoll | ⬜ Offen |
| WP-OSINT-FEEDS | Verifizieren ob 26 Telegram-OSINT-Kanäle (Aurora Intel, BNO News, Bellingcat, LiveUAMap, NEXTA etc.) kostenfreie RSS/Web-Alternativen haben. Falls ja + Mehrwert: in `sources.json` aufnehmen | ⬜ Offen |

## Zukünftige Arbeitspakete (H3)

| WP | Beschreibung | Status |
|----|-------------|--------|
| WP-ACLED-GDELT | ACLED (Konflikt-/Protestdaten) + GDELT (globale Event-DB mit Tonalitätsanalyse) als ergänzende Signalquellen für den Collector evaluieren. Beide bieten kostenfreien API-Zugang. Potenzial: Topic-Discovery-Trigger, geographische Abdeckungsvalidierung | ⬜ H3 |
| WP-TELEGRAM-OSINT | Direkte Telegram-API-Integration (GramJS/MTProto) für 26+ kuratierte OSINT-Kanäle als Echtzeit-Quellenlayer. Eigene Infrastruktur nötig (MTProto-Client, Message-Polling, Deduplizierung) | ⬜ H3 |


## Erkenntnisse aus dem ersten Pipeline-Lauf (2026-03-30)

**Lauf-Daten:** 39 Findings → 3 Topics → 2 produziert, 1 failed (Rate-Limit)
**Laufzeit:** 19 Minuten (1153 Sekunden)
**Modelle:** minimax/minimax-m2.7 (Collector, Curator) + z-ai/glm-5 (Editor, Writer) via OpenRouter
**Kosten:** ~$0.30-0.50 geschätzt

### Was funktioniert
- Pipeline-Mechanik Collect→Curate→Edit→Write läuft stabil
- Writer recherchiert eigenständig nach (10-11 Tool-Calls pro Topic)
- Multi-Perspektivität ist real: Iran-Position, westliche Reaktion, asiatische Notfallmaßnahmen
- Transparenz-Absätze am Artikelende identifizieren Quellenlücken ehrlich
- Editor-Begründungen ("selection_reason") sind die stärkste Leistung
- Error Isolation funktioniert: Topic 2 failed, Pipeline produzierte Topic 3 trotzdem

### Was nicht funktioniert
- Collector: alle Findings auf Englisch trotz globaler Abdeckung
- Collector: zeitliche Vermischung (2024er-Daten neben 2026er-News)
- Writer: `divergences` und `gaps` Felder bleiben leer
- Writer: Wikipedia als Primärquelle akzeptiert
- Kein Faktencheck: alle Zahlen und Statistiken ungeprüft
- Ollama Cloud: ~30% Ausfallrate, für Produktion nicht geeignet (OpenRouter stattdessen)

### Architektur-Entscheidung
- Artikellänge richtet sich nach Themen-Tiefe, nicht nach Format-Vorgaben
- Sobald Memory existiert (WP-MEMORY), referenziert der Writer frühere Berichterstattung statt Kontext von Null aufzubauen

### Erkenntnisse aus dem zweiten Pipeline-Lauf (2026-03-31)

**Lauf-Daten:** 38 Collector + 445 RSS = 483 Findings → 3 Topics → 3/3 produziert, 0 failed
**Laufzeit:** 19.5 Minuten (1169 Sekunden)
**Verbesserungen gegenüber Lauf 1:** Kein 429-Fehler, korrekte Topic-IDs, RSS-Feeds integriert, Debug-Output vorhanden, aktuellere Suchanfragen

**Offenes Problem — Sprach-Diversität:** Alle Quellen in beiden Läufen sind 100% Englisch. Länder-Diversität ist gut (Somalia, Mosambik, Libanon, Ruanda etc.), aber die Sprache ist durchgehend EN. RSS-Feeds liefern englische Inhalte selbst von nicht-englischen Outlets. Lösung: WP-RESEARCH (dedizierter Research Agent mit gezielten nicht-englischen Suchen pro Topic).

### Erkenntnisse aus World Monitor Wettbewerbs-Analyse (2026-04-04)

**Ergebnis:** Kein Overlap — World Monitor ist ein Echtzeit-OSINT-Dashboard (Situational Awareness), Independent Wire ist eine redaktionelle Pipeline (Perspective Analysis + Bias Transparency). Verschiedene Fragen an dasselbe Problem: World Monitor fragt "Was passiert?", Independent Wire fragt "Wie wird darüber berichtet, und was fehlt?"

**Nutzbar für Independent Wire:**
- Feed-Katalog (435+ RSS-Feeds mit 4-Tier-System) als Recherche-Startpunkt für `sources.json` Erweiterung
- Source-Tiering-Konzept + State-Affiliation-Flags → übernommen als 4-stufige `editorial_independence` Taxonomie
- Liste von 26 Telegram-OSINT-Kanälen als Quellen-Verzeichnis
- Erkenntnis: Collector-Deduplizierung nur bei >95% (nicht 60% Jaccard wie World Monitor), da Framing-Unterschiede analytisch wertvoll

**Nicht nutzbar:** Code (TypeScript, Dashboard-Architektur), Signal-Korrelations-Engine, Market-Entity-Knowledge-Base, Threat-Classification-Pipeline

**Entscheidung — Editorial Independence Taxonomie:**
4-stufige Skala statt binärem Flag: `independent` → `publicly_funded_autonomous` → `state_influenced` → `state_directed`

Wichtiger Caveat (muss auf Transparenz-Karte erscheinen): Das Feld erfasst die sichtbare strukturelle Beziehung zur Staatsmacht. Es erfasst NICHT verdeckte Finanzierung, Eigentümerinteressen, ideologische Ausrichtung oder Werbeabhängigkeit. Ein strukturell unabhängiges Outlet kann trotzdem massiv geframt sein. Ein staatlich gelenktes Outlet kann trotzdem faktenbasiert berichten. Unabhängigkeit/Abhängigkeit sagt nichts direkt über den Wahrheitsgehalt aus.

---

*Dieses Dokument wird nach jeder Session aktualisiert. Änderungen per Git nachvollziehbar.*
