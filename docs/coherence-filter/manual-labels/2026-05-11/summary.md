# Manual labels — 2026-05-11 TP clusters

Per TASK-MANUAL-LABELS-TP-CLUSTERS. CC hand-labelled 50 random findings per cluster (or all findings when N<50), one cluster per Topic Package. Source state: `output/2026-05-11/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json`. Cluster selection cross-checked against `output/2026-05-11/tp-2026-05-11-{001,002,003}.json`.

Labelling rubric: each finding compared against its cluster's `title + summary` headline only. Conservative borderline rule: in doubt, label off-topic.

## Aggregate

| Cluster | Size | Sampled n | Off-topic % | Cluster headline (truncated) |
|---|---:|---:|---:|---|
| 0 (tp-001) | 1004 | 50 | 92.0% | Stalled US-Iran peace negotiations and escalating regional tensions |
| 3 (tp-002) | 31 | 31 | 45.2% | Russia-Ukraine Victory Day ceasefire violations and peace talk proposals |
| 1 (tp-003) | 8 | 8 | 62.5% | Global hantavirus outbreak linked to MV Hondius cruise ship |

Total findings labelled across the three clusters: 89.

## Cluster 0 — Stalled US-Iran peace negotiations

- **Index in `curator_topics_unsliced`:** 0
- **Full headline:** Stalled US-Iran peace negotiations and escalating regional tensions
- **Cluster size:** 1004 findings
- **Sampled n:** 50
- **Off-topic:** 46 (92.0%)
- **On-topic:** 4 (8.0%)

### Off-topic examples

- `finding-851` — *Zema mantém embate e publica mais um capítulo da série que irritou Gilmar* (Brazilian politics, no Iran)
- `finding-447` — *Hantavirus cruise ship passengers enter isolation facility after evacuation to UK* (separate cluster's content)
- `finding-545` — *Ukrainische Infanterie: 130 Tage in der Todeszone* (Russia-Ukraine front, no Iran)

### On-topic examples

- `finding-420` — *Oil prices jump after Trump dismisses Iran proposal to end war*
- `finding-26` — *Macron: France 'never considered' military deployment uncoordinated with Iran*
- `finding-360` — *Defense ministry signals providing 'necessary support' for Hormuz ship probe*

### Observation

The Iran cluster's pathology persists at temperature=1.0 — only 8% of the sample is genuinely on-topic against the cluster's tight headline. The hot-topic effect (Iran-war news bleeding into every adjacent geopolitical story) drives most of the noise. The four on-topic findings concentrate on Hormuz/Trump-statement content, the cluster's narrowest semantic core. (Identical sample as TASK-COHERENCE-MANUAL-LABELS-V1 by construction — same seed, same source_ids, same state file.)

## Cluster 3 — Russia-Ukraine Victory Day ceasefire

- **Index in `curator_topics_unsliced`:** 3
- **Full headline:** Russia-Ukraine Victory Day ceasefire violations and peace talk proposals
- **Cluster size:** 31 findings
- **Sampled n:** 31 (full cluster — N<50)
- **Off-topic:** 14 (45.2%)
- **On-topic:** 17 (54.8%)

### Off-topic examples

- `finding-156` — *Temperatures up to +22°C, rain expected across Ukraine on Monday* (weather forecast)
- `finding-141` — *Germany seeks to expand joint deep strike weapons production with Ukraine – Pistorius* (borderline: weapons co-production, not ceasefire/peace)
- `finding-160` — *Occupiers want to 'nationalize' 150 commercial properties in Luhansk – RMA* (occupation admin, not ceasefire/peace)

### On-topic examples

- `finding-21` — *Russia and Ukraine accuse the other of ceasefire violations*
- `finding-131` — *Ukraine and Russia accuse each other of breaking US-brokered ceasefire*
- `finding-47` — *Zelenskyy says Ukraine pushed Putin 'a little' toward a potential meeting*

### Observation

A much cleaner cluster — 55% on-topic vs the Iran cluster's 8%. The off-topic share is dominated by Ukrinform's everyday operational reporting (weather, military command inspections, vehicle deliveries, electrical-grid status, EU loan/sanction news) that the Curator pulled into the cluster on the basis of "Ukraine" alone. The 17 on-topic findings split cleanly into combat-during-truce (ceasefire violations) and negotiator-selection / peace-talk diplomacy (the Schröder thread).

## Cluster 1 — Global hantavirus outbreak MV Hondius

- **Index in `curator_topics_unsliced`:** 1
- **Full headline:** Global hantavirus outbreak linked to MV Hondius cruise ship
- **Cluster size:** 8 findings
- **Sampled n:** 8 (full cluster — N<50)
- **Off-topic:** 5 (62.5%)
- **On-topic:** 3 (37.5%)

### Off-topic examples

- `finding-105` — *China eatery owner closes shop briefly to donate stem cells to toddler* (unrelated human-interest)
- `finding-317` — *How Kansas City, of all places, became a World Cup hotspot* (sports)
- `finding-101` — *Hong Kong lawmakers urge rethink of housing development policy for elderly* (Hong Kong housing)

### On-topic examples

- `finding-35` — *Last evacuation flights for passengers of hantavirus-hit cruise ship to depart Monday*
- `finding-4` — *Two more cruise ship passengers test positive for hantavirus*
- `finding-38` — *French passenger develops symptoms after evacuation from hantavirus-stricken cruise ship*

### Observation

Tiny cluster (8 findings) with a high relative off-topic rate. The three off-topic findings (China, Kansas City, Hong Kong) share no thematic link to hantavirus — they're noise the Curator's cosine-grouping at temperature=1.0 pulled in. One borderline call (`finding-162`, Ukraine's annual hantavirus baseline) was labelled off-topic per the conservative rule because the cluster is specifically the MV Hondius outbreak, not endemic hantavirus epidemiology elsewhere.
