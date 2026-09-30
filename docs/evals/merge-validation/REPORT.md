# MERGE-VALIDATION — hallucination inventory + guard evidence

Detector `detect.py` → `pairs.json` (3087 rows, every merge on disk).
Per-dossier inventory → `inventory.json`. Guard:
`src/agent_stages.py::merge_signals` / `validate_merges`.

## 1. Headline

**Clean separation is NOT achievable, and per the brief the trade-off returns
to the owner.** The guard is built, wired and tested on
`fix/merge-validation`, and it catches all five required cases — but at the
setting that catches them it would also have rejected roughly **25 legitimate
merges for every 11 hallucinations** in a hand-classified sample. The
legitimate rejections are overwhelmingly cross-language institution merges,
which is the thing an 18-language pipeline exists to do.

My recommendation is therefore **do not enable it as a blanket hard reject**;
section 6 proposes what the data does support.

## 2. The damage is real and it is in the published product

`output/2026-07-27/tp-2026-07-27-003.json` — the PUBLISHED dossier — contains
**exactly one actor entry**:

```
actors: 1
  Iris Spranger | Berlin Senator for the Interior
```

Forty-seven distinct actors went into that stage. Forty-six were merged away,
including Friedrich Merz (German Chancellor), Frank-Walter Steinmeier (Federal
President), the suspect's father, and the defence lawyer — all recorded as
"Iris Spranger". A reader has no way to detect this: the dossier does not look
broken, it looks sparse.

## 3. Inventory

| | |
|---|--:|
| merge pairs on disk (2026-05-27 … 09-15) | 3087 |
| flagged suspect (no tangible signal) | **248 (8.03%)** |
| topics affected | 104 of 308 |
| published dossiers affected | 104 (all resolvable to a `tp-*.json`) |
| many-to-one collapses (≥3 suspect aliases → one canonical) | **9** |

Severity-ranked, worst first (`inventory.json` has all 104 with their pairs):

| dossier | severity | suspect | largest collapse |
|---|---|--:|---|
| `tp-2026-07-27-003` | COLLAPSE | 46 | **46× → 'Iris Spranger'** |
| `tp-2026-09-06-003` | COLLAPSE | 7 | 6× → 'IDF' |
| `tp-2026-09-07-002` | COLLAPSE | 7 | 6× → 'Idf' |
| `tp-2026-09-07-001` | COLLAPSE | 7 | 4× → 'Guardie Rivoluzionarie iraniane' |
| `tp-2026-06-29-003` | COLLAPSE | 5 | 5× → 'Hamdulá Fitrat' |
| `tp-2026-08-10-003` | COLLAPSE | 5 | 3× → 'Yahya Saree' |
| `tp-2026-05-29-001` | COLLAPSE | 4 | 4× → 'Radu Miruță' |
| `tp-2026-07-25-003` | COLLAPSE | 4 | 4× → 'Authorities' |
| `tp-2026-08-03-001` | COLLAPSE | 4 | 4× → 'Iranian military officials' |

Several COLLAPSE rows are **false alarms**: the IDF and IRGC ones are genuine
cross-language merges of the same institution (`Ejército de Israel`,
`israelische Armee`, `Les Gardiens de la Révolution`). The Spranger row is not.
Severity ranking finds the catastrophic case first, but it does not by itself
separate the two.

**Required cases — all five caught**, with no signal at all:

| pair | signals |
|---|---|
| `Marco Rubio → Donald Trump` | `[]` |
| `Kevin Warsh → Jerome Powell` | `[]` |
| `Mark Levine → Thomas DiNapoli` | `[]` |
| `Marcie Frost → Thomas DiNapoli` | `[]` |
| Spranger topic | 46 of 46 `[]` |

### Random or clustered?

**Both, and the split matters.** 38% of suspect merges sit in 10 topics, but
**57 of the 104 affected topics have exactly one**. Rate by month: 7.0 / 13.4 /
9.1 / 5.3 / 7.4 % — no trend. Rate by resolver model build: 8.3 / 6.1 / 7.6 /
6.3 % — **no model is responsible**; the flash alias roll of 2026-09-10 did not
move it. This is a steady background property of the stage, punctuated by rare
catastrophic collapses.

## 4. Why clean separation failed

A 40-pair sample of the rejections (excluding the Spranger 46, which would
swamp it), hand-classified against the actors' names and role text:

| | count |
|---|--:|
| LEGITIMATE — the guard would be wrong | **~25** |
| HALLUCINATION — the guard would be right | **~11** |
| ambiguous | ~4 |

The legitimate rejections are one dominant class — **the same institution named
in two languages**, where the names share no token and the roles are the only
link: `Ejército de Israel → IDF`, `israelische Armee → Idf`,
`Gardiens de la Révolution → Guarda Revolucionária Islâmica`,
`die ukrainische Staatsbahn → Ukrzaliznytsia`,
`US-Regionalkommando → Comando Central das Forças Armadas dos EUA`.

The obvious fix is a **role-similarity signal**, and it was tried and rejected.
It works on those cases — and at any threshold loose enough to help, it also
excuses:

* `Mark Levine` (New York **City** Comptroller) → `Thomas DiNapoli` (New York
  **State** Comptroller) — 3 of 4 role tokens shared, two different offices,
  two different people, and one of the five cases that MUST be caught;
* `Hugh Grant-Chapman` → `Christopher Gundermann`, whose role strings are
  **byte-identical** ("Fellow, Economics Program and Scholl Chair in
  International Business at CSIS") and who are two different CSIS fellows.

Role similarity cannot distinguish "same entity described twice" from "two
people in similar jobs". Adding it dropped Levine→DiNapoli; that disqualified
it under the brief's own must-catch list. The signal is absent from the shipped
detector and the reason is recorded in the code.

## 5. The guard, as built

`validate_merges(alias_pairs, actors_by_id) -> (kept, rejected)`. A merge
survives if it carries any of: `name_shared`, `name_subset`, `name_variant`,
`acronym`, `gloss`, `role_link`, `cross_script`.

Three choices worth naming:

* **Rejection is a drop, never a retry.** Handing a hallucinated merge back to
  the model asks the thing that invented it to grade its own work, and costs a
  call to do it. Tested (`test_rejection_is_a_drop_not_a_retry`).
* **Validation runs BEFORE the union-find.** Union-find is transitive, so one
  un-anchored pair inside a chain drags every member of that chain together —
  that is the mechanism behind 46-into-1. Validating afterwards would already
  have lost them. Tested.
* **`cross_script` is an abstention, not evidence.** A Cyrillic name and a
  Latin one share no characters, so a transliteration merge is
  indistinguishable from an invented one without transliterating. The guard
  never rejects a merge it cannot check.

No Bus slot, no schema change. The count reaches the stage row through a
stage-level `extra_log_fields`, a small extension of the runner's existing
agent-level seam (`merges_rejected`, `merges_rejected_detail`), emitted only
when something was rejected so a clean row keeps its shape.

## 6. Recommendation

**Do not enable as a blanket hard reject.** At 8% it would reject ~2.3
legitimate merges per hallucination caught, and the losses land on exactly the
cross-language merges that justify 18 language streams. Fragmenting
`IDF`/`Ejército de Israel`/`israelische Armee` into three actors is a visible
product regression traded against an invisible one.

What the data does support, in order:

1. **Ship it as a detector first** — log and count `merges_rejected` on every
   run, reject nothing. Zero product risk, and it turns a 4-month blind spot
   into a daily number. The wiring is identical; only the drop would be
   disabled.
2. **Hard-reject the collapse shape only.** The catastrophic damage is
   many-to-one: ≥3 signal-less aliases onto one canonical. That is 9 topics in
   4 months, and it is where a reader loses a dossier's entire actor set. It
   would have caught Spranger. It would also have caught the IDF/IRGC
   false alarms, so this needs its own precision measurement before shipping —
   I did not do it, and I am not claiming it.
3. **Republishing `tp-2026-07-27-003` is an owner decision.** I have not
   touched `site/`. It is the one dossier where the published artefact is
   plainly wrong rather than arguably wrong.

The deeper fix is not a guard: two of the five known hallucinations
(Levine/DiNapoli, Grant-Chapman/Gundermann) are only distinguishable with world
knowledge about which offices and fellowships are distinct. That is a prompt or
model question for the resolver, not a Python question.

---

# ADDENDUM — detector mode + collapse-rule precision (TASK-VALIDATION-DETECTOR-MODE)

Owner decision on record: the guard ships as a **detector**. This section
records what that means in the code and answers the one open measurement.

## 7. Detector semantics

`src/agent_stages.py`: `MERGE_VALIDATION_MODE = MERGE_VALIDATION_DETECTOR`.

Detection is byte-identical in both modes; only the drop differs.

| | `detector` (shipped) | `reject` (wired, unused) |
|---|---|---|
| `kept` | **every pair, unchanged** | flagged pairs removed |
| `rejected` | what reject mode *would* have removed | the same list |
| product effect | **none** | actor lists change |

Four things worth knowing about the implementation:

* **Zero behaviour change is asserted, not assumed.**
  `test_detector_mode_keeps_every_merge_and_still_counts` requires
  `kept == pairs` — same objects, same order.
* **The two modes are tested against each other**, not separately
  (`test_reject_mode_drops_what_detector_mode_counts` asserts
  `flagged_detector == flagged_reject`), so the count cannot drift from the
  behaviour it predicts.
* **Validation still runs BEFORE the union-find**, even though it now drops
  nothing. Union-find is transitive, so running afterwards would inspect the
  collapsed result rather than the pair that caused it — the un-anchored pair
  would have acquired a shared canonical by then and the **count itself** would
  be wrong. Pinned in `test_validation_runs_before_the_union_find`.
* **Field names are unchanged from the reject design** (`merges_rejected`,
  `merges_rejected_detail`), so enabling the drop later does not rename a
  column mid-series. `merge_validation_mode` is added to the row so a future
  flip is legible as a mode change rather than an unexplained step.

The stage log line says `FLAGGED … DETECTOR MODE: counted only, every merge
proceeds`, and points at this report — because a raw count is **not** a
hallucination count, and will be misread as one otherwise.

## 8. Collapse-rule precision — 50%

Rule: **≥3 signal-less aliases onto one canonical**. Nine firings in four
months, every one hand-classified (`collapse_precision.py`, machine-readable in
`collapse_precision.json`).

| verdict | firing | size |
|---|---|--:|
| **TRUE** | `2026-07-27 t2` → 'Iris Spranger' | 46× |
| **TRUE** | `2026-07-25 t2` → 'Authorities' | 4× |
| **TRUE** | `2026-08-03 t1` → 'Iranian military officials' | 4× |
| **TRUE** | `2026-08-10 t2` → 'Yahya Saree' | 3× |
| FALSE | `2026-09-06 t2` → 'IDF' | 6× |
| FALSE | `2026-09-07 t1` → 'Idf' | 6× |
| FALSE | `2026-09-07 t0` → 'Guardie Rivoluzionarie iraniane' | 4× |
| FALSE | `2026-05-29 t0` → 'Radu Miruță' | 4× |
| ambiguous | `2026-06-29 t2` → 'Hamdulá Fitrat' | 5× |

**Precision = 4/8 = 50%** with the ambiguous case excluded; 44% counting it
false, 56% counting it true.

Reasoning for the four TRUE calls, since the number rests on them:

* **Spranger** — 46 unrelated people including Macron, Meloni, von der Leyen, a
  bishop, a drag artist, the suspect's father and the defence lawyer.
* **'Authorities'** — *Greece* merged with the Spanish government, the Spanish
  met agency and the Guardia Civil. Two countries in one actor.
* **'Iranian military officials'** — four transliterations of Abbas Araghchi,
  Iran's **foreign** minister. Merging the four spellings is right; the target
  is wrong.
* **'Yahya Saree'** — the Port Director of al-Makha is a different person from
  the Houthi military spokesperson.

The four FALSE ones are a single recognisable class, exactly as predicted: the
same institution named in four to six languages (`Ejército de Israel`,
`l'armée israélienne`, `israelische Armee`, `ইসরায়েলের সেনাবাহিনী`;
`Les Gardiens de la Révolution`, `die iranische Revolutionsgarde`). The
Romanian one is the institution↔office-holder merge the corpus makes routinely
and which the detector already accepts elsewhere through `role_link`.

### The number to carry forward, and its shape

50% is a coin flip **by count**, which is the honest headline. But the rule's
value is not evenly spread across its firings:

* **Alias-weighted it is 74%** — 57 aliases inside true firings vs 20 inside
  false ones.
* **The single largest firing is TRUE and holds 81% of all true-firing
  aliases.** The rule's entire practical value is that it finds Spranger-class
  events; the 3–6× firings are where it coin-flips.

Two readings follow, and choosing between them is a decision, not a
measurement:

* as a **hard reject**, 50% by count means one legitimate cross-language
  institution fragmented for every real collapse stopped — roughly four bad
  actor lists over four months in exchange for four good ones;
* as an **alerting threshold on top of the detector**, 50% is strong: nine
  alerts in four months, half of them real, one of them catastrophic, each
  resolvable by eye in under a minute from the log line alone.

No recommendation beyond the number, per the brief. No rule was enabled.
