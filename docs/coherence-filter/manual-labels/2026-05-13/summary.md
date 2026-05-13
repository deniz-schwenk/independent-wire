# Manual labels — 2026-05-13 top-3 clusters

Per TASK-EMBEDDING-MODEL-EVAL. CC hand-labelled 50 random findings from the largest cluster (sampled with `random.seed(42)`) and all findings from the next two largest clusters (size < 50). Source state: `output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json`. Cluster selection: top-3 by `source_count` in `curator_topics_unsliced`.

Labelling rubric: each finding compared against its cluster's `title + summary` headline only. Conservative borderline rule: in doubt, label off-topic. Same rubric and CSV schema as the prior 2026-05-11 briefs.

## Aggregate

| Cluster | Size | Sampled n | Off-topic % | Cluster headline (truncated) |
|---|---:|---:|---:|---|
| 1 | 180 | 50 | 64.0% | US-Israel War with Iran and Global Energy Crisis |
| 0 | 45 | 45 | 75.6% | Trump-Xi Summit in Beijing |
| 11 | 40 | 40 | 92.5% | Security Dislodgements and Unrest in Sudan |

Total findings labelled across the three clusters: 135. Total on-topic: 32 (23.7%). Total off-topic: 103 (76.3%).

## Cluster 1 — US-Israel War with Iran and Global Energy Crisis

- **Index in `curator_topics_unsliced`:** 1
- **Full headline:** US-Israel War with Iran and Global Energy Crisis
- **Cluster size:** 180 findings
- **Sampled n:** 50
- **Off-topic:** 32 (64.0%)
- **On-topic:** 18 (36.0%)

### Off-topic examples

- `finding-188` — *'I chose to be a single mum': Is this the new face of parenting?* (unrelated parenting feature)
- `finding-650` — *UK PM Starmer fights for political survival as calls for his resignation grow* (UK domestic politics; cluster names UK as Hormuz coalition member, but finding is about Starmer resignation)
- `finding-694` — *Neue ukrainische Kriegstaktik "Deep strikes" setzt Russland schwer zu* (Russia-Ukraine war, not Iran)

### On-topic examples

- `finding-27` — *Iran, Oman discuss sovereign rights over Strait of Hormuz*
- `finding-339` — *$29 Billion In 60 Days: Iran War Cost 16% More Than US Estimate*
- `finding-373` — *Japan crisp packs to go colourless due to Iran war crunch* (petrochemical-supply spillover, named in summary)

### Observation

A moderate-pathology cluster — 36% on-topic against the tight US-Israel-Iran-energy headline. The on-topic core concentrates on three semantic sub-strands: Hormuz coalition movements (Australia/UK/France/Korea), Iran war cost reporting ($29B / mounting estimates), and Iran-US/Iran-Oman ceasefire diplomacy. The off-topic share is dominated by hot-topic bleed: Mexican domestic politics, Russian internal news, and German consumer stories that the Curator pulled into the cluster on the basis of geopolitical-keyword proximity rather than semantic fit. Two borderline calls were Israel-Lebanon strikes (`finding-53`, `finding-58`) — labelled off-topic per the conservative rule because the cluster headline is specifically the US-Iran war, not the broader Middle East violence footprint.

## Cluster 0 — Trump-Xi Summit in Beijing

- **Index in `curator_topics_unsliced`:** 0
- **Full headline:** Trump-Xi Summit in Beijing
- **Cluster size:** 45 findings
- **Sampled n:** 45 (full cluster — N<50)
- **Off-topic:** 34 (75.6%)
- **On-topic:** 11 (24.4%)

### Off-topic examples

- `finding-343` — *Saudi Arabia Launched Covert Attacks On Iran Amid Middle East War: Report* (Iran-war news; summit agenda mentions Iran but this is the war itself, not summit content)
- `finding-721` — *Умер Владимир Молчанов — телеведущий и автор программы «До и после полуночи»* (Russian TV presenter obituary, unrelated)
- `finding-481` — *Eagles defeat Heroes for 3rd straight win in KBO* (Korean baseball)

### On-topic examples

- `finding-2` — *Trump and Xi to meet in Beijing: The key issues shaping the China summit*
- `finding-92` — *Nvidia's Jensen Huang joins Trump's trip to China at last minute* (Jensen Huang named in summary)
- `finding-659` — *Marktbericht: Anleger setzen auf China als möglicher Vermittler* (German market: investors bet on China as mediator — direct summit-reaction reporting)

### Observation

A pathological mid-size cluster — only 24% on-topic against a tight, well-defined cluster headline (named participants, named venue, named agenda items). The on-topic findings split into two strands: direct preview/explainer reporting (Beijing prep, Trump's delegation, Jensen Huang joining) and trade-talk lead-up (US-China talks in Seoul/Korea). The 34 off-topic findings show a broader pattern than cluster 1 — the Curator pulled in unrelated Mexican, Russian, Pakistani, and Korean stories alongside genuinely-summit-relevant pieces. Border calls on adjacent topics (Saudi-Iran strikes, Taiwan-Paraguay-Beijing, Iran-war Mideast risk) were labelled off-topic when the cluster headline did not specifically scope them.

## Cluster 11 — Security Dislodgements and Unrest in Sudan

- **Index in `curator_topics_unsliced`:** 11
- **Full headline:** Security Dislodgements and Unrest in Sudan
- **Cluster size:** 40 findings
- **Sampled n:** 40 (full cluster — N<50)
- **Off-topic:** 37 (92.5%)
- **On-topic:** 3 (7.5%)

### Off-topic examples

- `finding-156` — *Kenya: MPs Probe Missing 27,000 Tonnes of Imported Sugar* (Kenya domestic)
- `finding-209` — *NPFL: Abia Warriors suspend Amapakabo, Bethel Oji as Shorunmu takes temporary charge* (Nigerian football coaching)
- `finding-684` — *Israel beschließt Sondertribunal für Hamas-Überfall vom 7. Oktober 2023* (Israel-Hamas Oct-7 tribunal)

### On-topic examples

- `finding-7` — *Fighting in Sudan's Blue Nile State displaces thousands* (direct, Blue Nile named in summary)
- `finding-158` — *Sudan: UN Warns Sudan War Entering 'Deadlier Phase' As Drone Strikes Kill Hundreds*
- `finding-181` — *Sudan: Between Khartoum and Nyala — Humanitarian Aid Stuck Amid Legitimacy Conflict* (humanitarian aid + legitimacy conflict — both named in summary)

### Observation

The most severely pathological cluster of the three — 92.5% off-topic. Only 3 findings out of 40 are genuinely about Sudan. The cluster pulled together a regional-Africa noise floor (Nigerian sports, Kenyan corruption probes, Lagos transit, Somali protests, Nigerian court news) on the basis of "African geography" cosine proximity. Additional off-topic pollution came from Brazilian regulation, Mexican politics, Korean Samsung labor, Indian markets, and German market/labor stories — a true mega-pollution pattern. The cluster's tight, well-defined headline (Blue Nile, RSF/SAF, drone strikes, displacement) is structurally incompatible with the breadth of findings the Curator absorbed.
