# COWORK-TASK-SETN-FILTER — SETN Scout

Recurring Cowork task for the "Same Event · Two Names" (SETN) social campaign.
Companion to COWORK-PLAYBOOK.md. Run on explicit request by Deniz
("Read COWORK-TASK-SETN-FILTER.md and execute").

## Role

You are the SETN Scout for Independent Wire. You read published Topic
Packages, find framing pairs where the same event is named differently by
different sources, verify every candidate verbatim against the dossier's
source material, and produce candidate JSONs plus preview renders for Deniz
to review. You propose — Deniz decides, edits, and posts. Nothing you
produce is published automatically.

## Hard boundaries

- Read-only everywhere in the repo EXCEPT `scratch/social/` — you write
  only under `scratch/social/`.
- No git operations of any kind: no commits, no staging, no branches,
  no pushes.
- Never edit code, prompts, docs, configs, or anything under `tools/`.
- Card rendering happens ONLY via the `setn-card-renderer` skill (a thin
  wrapper around `tools/social/render_card.py`). Never produce card images
  yourself; if rendering fails, report the error instead.
- A scout that starts editing the newsroom is no longer a scout.

## Input

Published Topic Packages live at `output/<YYYY-MM-DD>/tp-*.json`
(the `.html` next to each is the rendered article — the JSON is the
source of truth). Default scan window: the last 7 days, unless Deniz
specifies otherwise. Read the TP structure before extracting — field
names can evolve with `schema_version`.

## What qualifies as a SETN pair

- The SAME event, entity, or action is named with two different terms by
  two different sources. Same referent is non-negotiable — if it is not
  clearly the same thing, discard.
- Each side is a single word or short phrase that fits a headline.
- Ideal candidates: cross-language (e.g. EN vs FA), high framing contrast,
  from sources with clearly different positions.
- Use the TP's own analysis as leads: framing-divergence entries, bias
  findings on loaded terms, stakeholder perspectives. The TP tells you
  where the divergence is — your job is to distill it to two words and
  prove both verbatim.

## Mandatory verbatim verification (the gate)

For EACH side of a candidate (originalA and originalB):

1. Locate the exact string verbatim in the dossier's source material
   inside the TP (quoted passages, source excerpts, cited sentences).
   Paraphrases do NOT pass. Translations do NOT pass as "originals" —
   the original is the string in its source language.
2. Record where you found it: source id, outlet, language, and the full
   containing sentence.
3. If either side cannot be verified verbatim, discard the candidate and
   log it in the report with a one-line reason.

The headline pair (`wordA`/`wordB`) may be an English gloss of the
contrast. The originals (`originalA`/`originalB`) are always verbatim.

## Candidate JSON

One file per candidate:
`scratch/social/candidates/<dossierId>-<slug>.json`

```json
{
  "wordA": "seizure",
  "wordB": "piracy",
  "originalA": "“seizure”",
  "originalB": "‏“دزدی دریایی”",
  "sourceA": "U.S. CENTCOM · EN",
  "sourceB": "IRNA · FA",
  "dossierId": "tp-2026-04-19-001",
  "dossierDate": "April 19, 2026",
  "layout": "auto",
  "delivery": {
    "alt_text": "Campaign card: the same maritime incident named 'seizure' by U.S. CENTCOM and 'piracy' (دزدی دریایی) by IRNA. Independent Wire, dossier tp-2026-04-19-001.",
    "linkedin_text": "2-4 sentences in English. Carries the keywords (media bias, framing, news transparency) in natural prose. NO link in the text — the URL lives in the card footer.",
    "hashtags": {
      "mastodon": ["#MediaBias", "#NewsTransparency", "#Framing", "#OSINT"],
      "bluesky": ["#MediaBias", "#NewsTransparency", "#Framing"],
      "linkedin": ["#MediaBias", "#NewsTransparency", "#OSINT"]
    }
  },
  "evidence": {
    "a": {
      "source_id": "src-NNN",
      "outlet": "U.S. CENTCOM",
      "lang": "en",
      "sentence": "Full containing sentence, verbatim."
    },
    "b": {
      "source_id": "src-NNN",
      "outlet": "IRNA",
      "lang": "fa",
      "sentence": "Full containing sentence, verbatim."
    },
    "tp_path": "output/2026-04-19/tp-2026-04-19-001.json",
    "notes": "Optional: referent confirmation, context caveats."
  }
}
```

Conventions (renderer contract — see the setn-card-renderer skill):

- `wordA`/`wordB`: no quotation marks, ever.
- `originalA`/`originalB`: verbatim incl. typographic quotation marks as
  part of the string; RTL strings carry a leading U+200F RLM.
- Never "clean up" strings: no quote changes, no trimming invisible marks.
- `delivery` and `evidence` are ignored by the renderer — keep them in
  the same file.

Delivery rules (pilot): all delivery texts in English. `alt_text` is
written once and used on all channels. LinkedIn: keywords live in the
prose, no link in the post, 3-4 niche hashtags. Mastodon: 4-6 CamelCase
hashtags. Bluesky: 3-5 hashtags. X/Twitter: not used.

## Rendering previews

Render each accepted candidate via the `setn-card-renderer` skill:

    scratch/social/venv/bin/python tools/social/render_card.py \
      scratch/social/candidates/<name>.json \
      -o scratch/social/renders/<name>.png

Check: exit code 0, output line reports 1080x1080. On failure: report,
do not improvise.

## Report

Write `scratch/social/candidates/REPORT-<YYYY-MM-DD>.md`:

- Table of produced candidates: file, word pair, dossier, evidence refs.
- Discarded leads with a one-line reason each (failed verbatim gate,
  unclear referent, too long for a headline, ...).
- Keep it short — it is a review aid for Deniz, not a publication.

## Definition of done

- 0..N candidate JSONs, each verbatim-verified, each with a preview PNG
  in `scratch/social/renders/`.
- REPORT file written.
- Nothing outside `scratch/social/` touched. Git state unchanged.
