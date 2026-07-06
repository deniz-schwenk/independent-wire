# BACKLOG — Ollama-cloud workstream (translate xhigh, quantization verification, GLM migration) + DeepSeek xhigh sweep

Status: SCOPED (Deniz + Architect, 2026-07-05). Not activated. Sequencing: after the
2026-07-06 landing queue, the MADLAD verdict, and the registry Phase-A kickoff
(BACKLOG-RESEARCHER-REGISTRY.md). Evals are offline and may interleave once the queue is clear.

## Ground truth (Architect diagnosis, read-only, 2026-07-05)
- translate_de runs **deepseek-v4-pro:cloud** via the local Ollama daemon (flat-rate sub,
  $0 marginal). `src/translate/transport.py`: `think: False` (reasoning OFF today),
  `format: "json"` (Ollama JSON mode — valid-JSON constraint only, NOT schema enforcement),
  `NUM_PREDICT = 32000`.
- Structured output on the Ollama path is guaranteed by **JSON mode + downstream Python
  verification** (per-block schema fields analyse/translation/verify/pass/correction/final,
  bracket-fix guard, src-token preservation check — visible in daily logs as
  "src-tokens 100.0%"). The fallback chain hardens it: deepseek-direct uses strict TOOLS
  schema; openrouter uses json_object + Python guard. So: weaker decode-constraint than
  OpenRouter strict json_schema, compensated by verification. This answers "how was
  structured output ensured" — by design, already robust.
- **Quantization on ollama-cloud is opaque** — no fp8 pin, no provider metadata. This is
  exactly the fp4 risk class (DeepSeek fp4 artifact caused a disqualifying fabrication).
  Empirical verification is mandatory before any production traffic moves.
- Ollama subscription = commercial dependency, currently UNDOCUMENTED → add to the
  documented list (Bias-Judges, Perspective, +Ollama flat-rate for de-translation)
  regardless of what else happens.

## Work packages (each its own gate; caps in code per standing rule)

### WP-OLLAMA-1 — Quantization/quality probe (GATE for everything ollama)
Empirically verify ollama-cloud `glm-5.2` and `deepseek-v4-pro:cloud` against our
OpenRouter fp8 baselines (Baidu pin) on identical real stage inputs. Blind, anonymized,
Opus-4.8 subagent judges (NEVER API), anchor-free; plus artifact screen for the known
quant failure modes (fabricated actors, numeric corruption, repetition). Parity required.
In-code spend cap; API only for candidate arms.

### WP-OLLAMA-2 — translate_de: reasoning ("xhigh") A/B + NUM_PREDICT
Flip `think` on with effort control where the model supports it; raise NUM_PREDICT to keep
output budget (reasoning eats it — Deniz's point). A/B on N real TPs: fidelity judged by
subagents, src-token preservation must stay 100%, wall-clock measured (today 487s/day;
translate runs chained post-publish, latency tolerant but not unbounded). Keep only if
fidelity gain is real; translation rarely benefits from reasoning — honest null result is
a valid outcome.

### WP-OLLAMA-3 — GLM stage migration OpenRouter -> ollama-cloud (cost play)
Only after WP-OLLAMA-1 parity. Stage-by-stage (writer, qa_analyze, editor, hydration_p2):
shadow N days on same inputs, blind judged vs the OpenRouter output; flip one stage per
06:00 window with loud logging (`provider_used: "ollama-cloud"`) and OpenRouter-Baidu-fp8
as declared fallback. Expected saving: the GLM stages' ~$0.7-1.0/day -> $0 marginal.
Rate-limit/throughput of the subscription under the 06:00 burst must be checked in shadow.

### WP-DS-XHIGH — DeepSeek V4 Pro/Flash stages: reasoning-xhigh sweep (quality play)
Inventory the DS stages + operating points from scripts/run.py; per-stage A/B current vs
xhigh, subagent judged, small N. Existing data point: DS V4 Pro @ xhigh scored 3.54 in the
P2 eval — xhigh is no magic bullet. NOTE: this WP RAISES cost (more tokens) — opposite
motivation to WP-3; sequence it last, and pair any adoption with the WP-3 savings.

## Order & dependencies
WP-OLLAMA-1 first (cheap, gates 2+3). WP-2 independent after 1 (translate path is
already ollama). WP-3 only on parity, one stage per window. WP-DS-XHIGH last.
Cross-cutting first commit (can ride any window): document the Ollama dependency in
ARCHITECTURE.md's dependency list.

## UPDATE 2026-07-05 (Abend) — WP-OLLAMA-1 + 1b abgeschlossen: Gate OFFEN für beide Modelle

- **Verdikt:** PARITY/PROCEED für GLM-5.2 und DeepSeek-V4-Pro. Null Quant-Artefakte auf
  allen Ollama-Armen über beide Läufe; alle geflaggten Artefakte der gesamten Probe lagen
  auf den eigenen fp8/xhigh-Baselines. Artefakte: scratch/ollama-probe/ (REPORT.md +
  REPORT-MAX.md, 60 Verdicts, leak-geprüft, $0 Spend).
- **Der Run-1-Vorbehalt ("xhigh unabbildbar") war ein Benennungsfehler (Deniz-Korrektur):**
  Ollamas akzeptierte think-Stufen für glm-5.2:cloud sind {low, medium, high, max, true,
  false} — per nativer Validator-Fehlermeldung belegt. Top-Tier = **max**.
  Dreier-Vergleich: openrouter@xhigh 4.35 · ollama@high 4.40 (2/7/1) · **ollama@max 4.45
  (2/8/0, 0 Artefakte)**. Tier-Mapping für die Migration: production reasoning="xhigh"
  -> ollama think:"max".
- **Neue harte Auflage für WP-OLLAMA-3 (aus der Probe gelernt):** Ollamas /v1-Endpunkt
  akzeptiert UNGÜLTIGE think-Werte stillschweigend (nahm "xhigh" an ohne Fehler) — das ist
  die Silent-Fallback-Verwandtschaft. Jeder Migrations-Task MUSS den konfigurierten
  Tier-Wert beim Start gegen die native Validierung asserten (fail loud, nie still).
- **WP-OLLAMA-3 ist damit vom Operating-Point-Wechsel zum reinen Provider-Tausch
  herabgestuft.** Leichterer Pfad als ursprünglich geplant: pro GLM-Stage (writer,
  qa_analyze, editor, hydration_p2) eine Mini-Probe nach dem etablierten Muster
  (~10 Items, Produktions-Snapshots als Baseline wiederverwendet, Subagent-Richter, $0)
  statt mehrtägiger Shadows — dann Flip je EINE Stage pro 06:00-Fenster mit lautem
  Logging (provider_used:"ollama-cloud") und OpenRouter-Baidu-fp8 als deklariertem
  Fallback. Ratelimit-Frage bleibt: volle Tageslast erst beim ersten Flip real beobachtet
  (Probe sah 0 Limits bei ~6 concurrent, n klein).
- Ebenen-Abgrenzung zur Sequenzierung: Ollama = Model-Serving-Ebene, Registry/MADLAD =
  Quellen-/Cluster-Ebene. Mini-Probes sind offline/read-only und dürfen parallel zur
  Registry-Phase-A laufen; FLIPS bleiben im Ein-Änderung-pro-Lauf-Takt hinter Batch-2 +
  Observability-Commits eingereiht.

## UPDATE 2026-07-05 (Nacht) — WP-OLLAMA-2 abgeschlossen: KEEP think:false
Blind-Probe (6 TPs, 180 geseedete Segmente, 12 Subagent-Verdicts, $0): think:"max" ist auf
allen drei Achsen leicht schlechter (4.939/4.930/4.830 vs 4.958/4.967/4.892; 23W/128T/29L)
bei ~4-5x Latenz (~8 -> ~30 min/Tag). Fehlerbild: Reasoning verleitet zu Ausschmückung —
additions 6 vs 2, wrong_language 11 vs 3, unbelegte Spezifität. Mechanische Garantien
hielten (100% src-tokens, 0 leer). Messbefund /api/generate: num_predict deckelt
thinking+answer GEMEINSAM (Kandidat brauchte 64000). deepseek-v4-pro:cloud akzeptierte
Stufen: {low, medium, high, max, true, false} (nativ belegt). Beleg:
scratch/translate-max-probe/REPORT.md. WP-OLLAMA-2 damit GESCHLOSSEN, Produktion unverändert.

## UPDATE 2026-07-06 (früh) — WP-DS-XHIGH abgeschlossen: KEEP none auf allen V4-Pro-Stages
Probe n=8/Stage, 48 Subagent-Verdicts, $1.35 von $5 Cap. consolidator: Parität (+0.06).
hydration_phase1: schlechter (−0.10) UND Fabrikationen verdoppelt (4→8) bei 3.7x Kosten.
bias_extractor: echter Gewinn (Recall +0.62, 6W/0T/2L), aber 8x Kosten/31x Latenz +
2/8 degenerierte Pässe + Sampling-Confound → KEEP, mit benanntem Folge-Kontrolltest:
none-4/5-Pass-Union am selben Set isoliert Sampling vs Reasoning; bestätigt er sich,
ist ein zusätzlicher none-Pass der billige Produktions-Recall-Hebel (~$0.05/Thema).
Engineering-Befund (wertvoll für jede künftige DS-Reasoning-Adoption): die
"xhigh structured=None"-Pathologie (run.py:492) ist Budget-Starvation — 15-16k
Reasoning-Tokens sprengen max_tokens=32000; bei 64000 überlebt Structured Output
vollständig. V4-Flash-Stages: für Folgewelle gemeldet, nicht geprobt.
Damit ist die gesamte Ollama/DS-Welle vom 07-05 GESCHLOSSEN: WP-1/1b PARITY,
WP-2 KEEP think:false, WP-3a Flip-Plan (editor→writer→qa hold), WP-DS-XHIGH KEEP none.
Offen nur: Flip-Kalender, optionaler bias-none-N-Pass-Kontrolltest, optionale Flash-Welle.
