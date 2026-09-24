# ALIAS-GATE-TRIGGER — discriminator design, replay, residual risk

Scripts and data in this directory. Shipped implementation:
`src/agent_stages.py::merge_candidates_present`. Authoritative replay:
`replay.py` (imports the SHIPPED function, not the prototype) →
`replay.json`.

## 1. Headline

**The literal evidence bar is not met.** After removing hand-classified
resolver errors the discriminator misses **1 of 311** topics that had a real
merge (2026-06-29 t0). Against the raw label it misses 6 of 318. The brief says
that returns the trade-off to the owner, so this branch is pushed and NOT
merged, and nothing below claims merge-readiness.

What the work did establish, and what makes the decision a real one rather than
a refusal:

* The motivating case is separated. 2026-09-14 t2 now returns
  `present=False, why=[]` — no retries, no rung-2 spend, no degraded status.
* Recall on genuinely-positive topics is **99.7%** (310/311).
* **5 of the 6 raw misses are the resolver merging unrelated people.** That is
  a finding in its own right and is section 3.

## 2. Confusion matrix (336 topics, 2026-05-27 … 2026-09-15)

Every `topic_buses.consolidate_actors.N.json` on disk with its matching
`ResolveActorAliasesStage.N.json`. Deterministic, zero LLM cost.

Label: *positive* = the resolver emitted at least one alias or anonymous flag.

### Raw label

| | predicted CANDIDATES | predicted NOTHING |
|---|--:|--:|
| outcome non-empty (318) | 312 | **6** ← false negatives |
| outcome empty (18) | 5 | **13** ← true negatives |

Recall 312/318 = **98.1%**. Empty outcomes separated 13/18 = 72.2%.

### Label with the 7 hand-classified resolver-error topics removed (329)

| | predicted CANDIDATES | predicted NOTHING |
|---|--:|--:|
| outcome non-empty (311) | 310 | **1** ← false negative |
| outcome empty (18) | 5 | **13** |

Recall 310/311 = **99.7%**.

The one genuine miss, 2026-06-29 t0: `'Pierre Chanel Tein Tutugoro' ->
'Christian Tein'`. The pair shares the surname token `tein` but nothing else,
and the remaining tokens are not near-variants. A rule that fires on "share any
4-letter token" catches it — and also fires on 2026-09-14 t2, where
Josh/Mike/Evan/Greg/Marc are each shared by exactly two unrelated people. The
two cannot be separated by token sharing alone, which is why this one is
accepted as residual rather than patched.

## 3. The ground truth is contaminated, and that matters for the bar

Reading every merge pair behind the 6 raw misses:

| topic | "merge" | verdict |
|---|---|---|
| 2026-06-15 t0 | `Marco Rubio -> Donald Trump` | wrong |
| 2026-06-23 t1 | `Kevin Warsh -> Jerome Powell` | wrong |
| 2026-06-12 t1 | `Mark Levine`, `Marcie Frost -> Thomas DiNapoli` | wrong |
| 2026-06-08 t2 | `Marie Rosaline Belizaire -> Tedros Adhanom Ghebreyesus` | wrong |
| 2026-06-25 t0 | `Arestovic -> Volodymyr Zelensky` | wrong |
| 2026-06-02 t2 | anon-flagged `Corrigan` (a surname) | wrong |
| **2026-07-27 t2** | **46 distinct German politicians -> `Iris Spranger`** | wrong |
| 2026-06-29 t0 | `Pierre Chanel Tein Tutugoro -> Christian Tein` | plausible |

The bar as written — "on every day with real merges the discriminator must NOT
classify the input as nothing-to-merge" — cannot be met against this label,
because meeting it would require predicting the resolver's hallucinations from
its input. That is not a property any input-side discriminator can have.

**Separate finding, larger than this task.** A corpus-wide deterministic proxy
("both sides are 2-token Latin personal names, share no token, no near-variant,
neither role names the other") counts **81 of 3087 merge pairs (2.6%)** across
**35 of 336 topics**, with 41 of the 81 inside 2026-07-27 t2 alone. The proxy is
noisy in both directions — it catches legitimate cross-language org merges like
`Kuveyt ordusu -> Kuwait's military`, and misses org-shaped errors — so treat
2.6% as an indicative upper bound, not a rate. The point stands regardless:
**the resolver silently merges distinct people into one another, and that
corrupts a dossier's actor set in a way no reader can detect.** It is out of
scope here and should be its own task.

## 4. Cross-script hazard — measured, not asserted

The brief names `Сибіга -> Sybiha`: a Cyrillic name and its Latin
transliteration share no character, so every Latin-side normalisation is blind
to them by construction. Handling is two signals, and the measurement is what
made them their current shape:

**S6 `multi_script`** — two or more *dominant* scripts among the actor names
counts as a candidate on the possibility alone. Fires on 44/336 topics (13%);
`test_cross_script_variants_without_a_latin_handle_do_count` pins
`["Andrii Sybiha", "Radoslaw Sikorski", "Сибіга"] -> True`.

*Dominant*, and excluding self-glossed names, is not decoration. The first
version counted any script present anywhere and fired on 2026-09-14 t2 — from a
single actor, `Simsim – مشاركة مواطنة (Simsim – Citizen Participation
Association)`, whose Arabic is its own name and which already carries its own
Latin gloss. That one name alone destroyed the separation the task exists to
achieve. Names whose parentheses hold a Latin gloss are therefore excluded from
the script count, because S4 compares that gloss directly.

**S4 `paren_gloss`** — a parenthetical gloss overlapping another actor's
tokens. Fires on 78/336 (23%). This is how the corpus's cross-script merges
actually present: `الجيش الإسرائيلي (Israeli military) -> Israeli military`.

Measured limit, stated plainly: a bare Cyrillic name in a topic with **no other
script** and no gloss is invisible to both. No such topic appears in 336
historical cases, but the design does not exclude one.

## 5. Signals and their firing rates (336 topics)

| signal | fires | what it is for |
|---|--:|---|
| `variant_pair` | 88% | subset / ≥2 shared tokens / shared + near-variant |
| `role_names_actor` | 73% | an actor's ROLE text names another actor |
| `generic_label` | 63% | source-class label → anonymous-flag candidate |
| `norm_collision` | 47% | two actors normalise identically |
| `role_as_name` | 43% | the NAME is a role/title |
| `paren_gloss` | 23% | gloss overlapping another actor |
| `acronym` | 18% | acronym ↔ another name's initials |
| `multi_script` | 13% | cross-script variants possible |

Two design notes worth keeping:

* `variant_pair` replaced a bare "share any token" rule, which fired on
  2026-09-14 t2 on **shared given names alone** — Michael/Josh/Mike/Evan/Greg/
  Marc across six unrelated people. A bare token rule measures "two Americans
  have the same first name".
* `role_names_actor` was the single biggest recall win (+14 topics). The
  corpus's legitimate person↔organisation merges carry no name-level signal at
  all: `Matthew Diller` → `New York City Bar Association` share nothing, but
  Diller's role field reads "President, New York City Bar Association".

## 6. Residual risk, stated as exposure and as rate

The new path is taken on **19 of 336 topics (5.7%)** — ~1 topic in 18, about
**one every 6 days** at 3 topics/day. On exactly those topics an empty result is
now accepted without retry, ladder or gate.

* **Exposure**: 19 topics over 112 days that previously escalated and would now
  not. That is the honest number, and it is not small.
* **Expected missed degradations**: exposure × the measured channel-C flash
  empty/invalid rate (0.86–1.14%, forensics A4) ≈ **one missed real degradation
  every ~1.6 years**.
* **Known blind spot**: topics of the 2026-06-29 shape — a shared surname with
  no other signal. 1 in 336 historically.
* **Accepted false positives**: `role_names_actor` matches a geographic phrase
  embedded in a role ("Marco Rubio", role "Secretary of State of the United
  States", beside an actor "United States"). Pinned in tests as a knowing
  choice: a false positive costs at most the retries the stage already made,
  a false negative accepts a real degradation in silence.

## 7. What the owner is deciding

Ship: the gate stops crying wolf on ~1 topic every 6 days, and the motivating
case is fixed. Don't ship: one genuine miss in 311 survives, so the bar as
written is not met, and 19 topics per 112 days lose their escalation path.

My reading is that the trade is favourable — a gate ignored because it fires on
correct output protects nothing, and ~1 missed degradation per 1.6 years is
cheaper than that. But the bar was set as a hard one and it is not met, so the
call is the owner's and the branch stays unmerged.
