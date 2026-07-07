# BACKLOG — TP data leverage (triage of downstream uses)

**Status:** Architect triage of an idea collection (Opus brainstorm session,
provided by Deniz 2026-07-06). Decisions recorded 2026-07-06/07.
**Core insight:** of eleven ideas, two are actionable now, one was more
urgent than the list knew, and five are a single build, not five products.

## NOW — time-critical (tasks already cut)

1. **TP schema versioning** — the only genuinely time-critical item: every
   external use (dataset, benchmark, blind spots, longitudinal work)
   consumes the archive, and the archive is only analyzable if every TP
   carries `schema_version` from now on. → TASK-SCHEMA-VERSION.md
   (feature branch; lands 2026-07-09).
2. **Copyright as an export design constraint** — publish ONLY our own
   annotations (perspective labels, divergences, bias cards, source
   metadata, gaps) plus source references (URLs). Never full texts or long
   quotes from sources in any distributed dataset. This is written down
   NOW, before any export exists, because retrofitting it is how projects
   get this wrong. This paragraph is the standing rule.
3. **Evidence rescue** — the OSS-quality core claim ("open-weight models at
   equal quality") is NOT unproven: blind evals, the 3-arm backtest, and
   the swap-wave reports exist — but lived untracked in scratch/.
   → TASK-EVIDENCE-RESCUE.md (copy to docs/evals/ + INDEX.md).

## PASSIVE — accrues by waiting

4. **Time depth** — the archive is ~2 months old; longitudinal claims get
   meaningful over quarters. No task. The NOW items above exist precisely
   so that waiting produces a clean, versioned, citable archive.

## Q4 2026 — one workstream, multiple renderings

5. **One deterministic aggregation layer** over the versioned TP archive.
   Not five products: Blind Spot Reports, self-bias audit, meta-dashboards,
   feed-curation evidence, and the research dataset are RENDERINGS of the
   same aggregation (exactly like the TP itself: one data foundation, many
   outputs). Building them as separate workstreams would be fourfold
   redundant. Aggregation is deterministic Python (counting is never
   delegated to an LLM).
   - **First rendering: Blind Spot Report** (monthly/quarterly) — unique
     (nobody systematically documents gaps), embodies the thesis, cheap,
     journalistically citable. Feeds from missing-voices data; the
     story-thread view adds "which stories died" from follow-up chains.
   - Self-bias audit: aggregated bias cards across all TPs expose the
     pipeline's own systematic tilts. Credibility + improvement in one.
   - Feed-curation evidence: which sources consistently deliver own
     perspectives, which are redundant. NOTE: partially operational
     already — the registry shadow LEDGER is this instrument for the
     source side.
   - Research dataset export (annotations + URLs only; see constraint 2).
   Realistic first output: Q4 2026 (time depth).

## PARKED — with reasons (do not silently reopen)

6. **Actor/entity database feeding resolve_actor_aliases** — REJECTED as a
   workstream. Two reasons: (a) complexity magnet (entity resolution over
   time, role changes, storage, maintenance); (b) more fundamentally, it is
   a feedback loop in which accumulated past judgments shape future
   judgments — a self-reinforcing prior. For a project whose thesis is
   "make bias visible", a mechanism that gradually hardens its own bias is
   the wrong component. Parked as a research idea only.
7. **Hugging Face dataset + benchmark** — deferred until the TP schema is
   stable and the export constraint (item 2) is implemented. Building a
   benchmark before the schema settles builds the horse from behind.

## NO TASK

8. **Funding/partnership framing** ("open public-interest dataset on news
   transparency") — belongs in pitch documents, not in the repo.

## Dependencies

- Everything in Q4 depends on: schema_version live (07-09), export
  constraint honored, archive time depth.
- Blind Spot Report prototyping may start earlier as a Cowork/Auditor
  monthly task (see COWORK-PLAYBOOK.md) — prototype in Cowork, then, if
  the format proves out, the aggregation moves into deterministic Python
  in the pipeline (deterministic-before-LLM applies again).
