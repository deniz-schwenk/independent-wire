"""De-anonymize + aggregate the 3-judge verdicts into per-arm results.

Fabrication charge counts only at >=2/3 judges citing the SAME divergence
(matched verbatim to a candidate's divergence string). Leak-proof: labels are
mapped back to arms here (post-hoc) via the per-topic anon_keys.

  uv run python scratch/p2-eval/aggregate.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from harness import ARTICLES, ARMS, raw_path  # noqa: E402

VERD = HERE / "verdicts"
KEYS = HERE / "anon_keys"
AXES = ("grounding", "specificity", "cross_group_validity", "gap_quality", "overall")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_topic(date: str, n: int):
    key_p = KEYS / f"{date}_{n}.json"
    if not key_p.exists():
        return None
    key = json.load(open(key_p))                 # label -> arm
    judges = []
    for j in range(3):
        p = VERD / f"{date}_{n}__j{j}.json"
        if p.exists() and json.load(open(p)).get("ok"):
            judges.append(json.load(open(p))["structured"])
    if len(judges) < 2:                          # need a majority basis
        return None
    return key, judges


def main():
    scores = {a: {ax: [] for ax in AXES} for a in ARMS}
    fabrics = defaultdict(int)                    # arm -> confirmed fabrications
    fabric_topics = defaultdict(set)
    judged_topics = 0
    per_topic = []
    for date, n in ARTICLES:
        t = load_topic(date, n)
        if not t:
            continue
        key, judges = t
        judged_topics += 1
        nj = len(judges)
        # candidate divergence strings per arm (for verbatim fabrication match)
        arm_divs = {}
        for arm in ARMS:
            st = json.load(open(raw_path(arm, date, n))).get("structured") or {}
            arm_divs[arm] = [_norm(d) for d in (st.get("preliminary_divergences") or [])]
        # per label: gather each judge's assessment
        by_label = defaultdict(list)
        charges_by_label = defaultdict(list)     # list per judge of set(normalized quotes)
        for jstruct in judges:
            for a in (jstruct or {}).get("assessments", []):
                lab = a.get("label")
                by_label[lab].append(a)
                charges_by_label[lab].append(
                    {_norm(c.get("quote", "")) for c in a.get("fabricated_divergences", [])})
        row = {"topic": f"{date}#{n}"}
        for lab, arm in key.items():
            asmts = by_label.get(lab, [])
            for ax in AXES:
                vals = [a[ax] for a in asmts if isinstance(a.get(ax), int)]
                scores[arm][ax].extend(vals)
            # confirmed fabrication: a candidate divergence flagged by >=2 judges
            charge_sets = charges_by_label.get(lab, [])
            conf = 0
            for d in arm_divs[arm]:
                hits = sum(1 for cs in charge_sets
                           if any(d == q or (q and (q in d or d in q)) for q in cs))
                if hits >= 2:
                    conf += 1
            fabrics[arm] += conf
            if conf:
                fabric_topics[arm].add(f"{date}#{n}")
            row[arm] = conf
        per_topic.append(row)

    print(f"judged topics: {judged_topics}/21   (3-judge panels; >=2/3 = confirmed)\n")
    print(f"{'arm':10} {'ground':>7} {'specif':>7} {'xgroup':>7} {'gapq':>6} "
          f"{'overall':>7} {'FABRIC':>7} {'fab_topics':>10}")
    ranked = sorted(ARMS, key=lambda a: -(sum(scores[a]['overall'])/max(len(scores[a]['overall']),1)))
    summary = {}
    for arm in ranked:
        m = {ax: (sum(scores[arm][ax]) / len(scores[arm][ax]) if scores[arm][ax] else 0)
             for ax in AXES}
        summary[arm] = {**{ax: round(m[ax], 2) for ax in AXES},
                        "confirmed_fabrications": fabrics[arm],
                        "fab_topics": sorted(fabric_topics[arm])}
        print(f"  {arm:10} {m['grounding']:>7.2f} {m['specificity']:>7.2f} "
              f"{m['cross_group_validity']:>7.2f} {m['gap_quality']:>6.2f} "
              f"{m['overall']:>7.2f} {fabrics[arm]:>7} {len(fabric_topics[arm]):>10}")
    json.dump({"judged_topics": judged_topics, "summary": summary,
               "per_topic_fabrications": per_topic},
              open(HERE / "aggregate.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
