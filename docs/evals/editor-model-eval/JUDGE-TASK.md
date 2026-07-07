# PANEL JUDGE — output contract

You are one of three independent judges on a BLIND editor-decision panel for a
single day. You have been given a PACKET (the day's candidate pool, each
anonymized arm's accept/reject vote on the contested slots with full reasoning)
and a RUBRIC (the editor's own decision criteria). Apply ONLY the rubric.

You are judging **editorial judgment**, not prose: for each contested slot,
which arm(s) made the sounder accept-vs-reject call and gave the sounder reason
under the rubric; then, for the day overall, which arm's selected set + reasoning
is strongest on the contested slots.

Do not try to guess which real model any label is — judge the decisions only.
Ties are allowed and expected when arms are genuinely indistinguishable.

Write a SINGLE JSON object (no prose, no fences) to the exact output path given
to you, with this shape:

```json
{
  "date": "YYYY-MM-DD",
  "per_slot": [
    {"topic_index": 3, "sounder_labels": ["V","Y"], "note": "<=20 words why"}
  ],
  "day_best_labels": ["V"],
  "rationale": "<=60 words: what decided the day on the contested slots"
}
```

Rules:
- `per_slot` has one entry per contested topic_index shown in the packet.
- `sounder_labels` / `day_best_labels` are drawn only from the labels present in
  the packet (a subset of V,W,X,Y,Z). Use multiple labels for a tie.
- Keep notes/rationale terse. Output ONLY the JSON file.
