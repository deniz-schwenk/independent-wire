"""Score the Phase-0 stability grid against the frozen gate criterion.

Reads scratch/bias-eval/raw/*.json, computes per-article variance
(valid-count spread C, valid-span instability J, total-count spread Ctot,
category-distribution instability D) for each arm, aggregates, and applies:

    PASS  <=>  Jbar(m) <= Jbar(inc)  AND  Cmax(m) <= Cmax(inc)

plus the hard precondition that no call was errored / schema-invalid /
empty-emission. Prints the gate table. Writes gate.json.
"""
from __future__ import annotations

import glob
import itertools
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
# opus48 = Opus-4.8 (adaptive thinking, effort high) — the stability CEILING
# reference, scored alongside but not a swap candidate.
ARMS = ["incumbent", "glm", "deepseek", "sonnet5", "opus48"]
ARTICLES = [("2026-06-13", 0), ("2026-06-17", 1), ("2026-06-02", 2),
            ("2026-06-22", 2), ("2026-06-20", 0)]
CATS = ["evaluative_adjective", "emotionalizing", "passive_obscuring",
        "loaded_term", "hedging", "intensifier"]


def load(arm, date, n, rep):
    p = RAW / f"{arm}__{date}_{n}__r{rep}.json"
    if not p.exists():
        return None
    return json.load(open(p))


def findings(rec):
    if not rec or not rec.get("ok"):
        return None
    s = rec.get("structured")
    if not isinstance(s, dict):
        return None
    return (s.get("language_bias") or {}).get("findings") or []


def valid_set(fs):
    return {f.get("excerpt", "") for f in fs if f.get("finding_valid") is not False}


def all_set(fs):
    return {f.get("excerpt", "") for f in fs}


def jaccard(a, b):
    if not a and not b:
        return 1.0
    u = a | b
    return len(a & b) / len(u) if u else 1.0


def cat_hist(fs):
    v = [f for f in fs if f.get("finding_valid") is not False]
    h = [0] * len(CATS)
    for f in v:
        if f.get("issue") in CATS:
            h[CATS.index(f["issue"])] += 1
    tot = sum(h) or 1
    return [x / tot for x in h]


def l1_over2(h1, h2):
    return sum(abs(a - b) for a, b in zip(h1, h2)) / 2.0


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def score_arm(arm):
    per = []
    precondition_fail = []
    served = set()
    cost = 0.0
    dur = []
    toks = []
    for date, n in ARTICLES:
        reps = [load(arm, date, n, r) for r in (0, 1, 2)]
        if any(r is None for r in reps):
            per.append({"date": date, "n": n, "incomplete": True})
            continue
        fss = []
        for r in reps:
            cost += r.get("cost_usd", 0) or 0
            if r.get("duration_s") is not None:
                dur.append(r["duration_s"])
            if r.get("tokens"):
                toks.append(r["tokens"])
            if r.get("served_provider"):
                served.add(r["served_provider"])
            fs = findings(r)
            if fs is None:
                precondition_fail.append(
                    f"{date}#{n} r{reps.index(r)}: "
                    f"{'error:'+r.get('error','') if not r.get('ok') else 'schema-invalid/None'}")
            fss.append(fs)
        if any(fs is None for fs in fss):
            per.append({"date": date, "n": n, "precondition_fail": True})
            continue
        V = [valid_set(fs) for fs in fss]
        A = [all_set(fs) for fs in fss]
        H = [cat_hist(fs) for fs in fss]
        vc = [len(x) for x in V]
        ac = [len(x) for x in A]
        C = max(vc) - min(vc)
        Ctot = max(ac) - min(ac)
        J = 1 - mean([jaccard(V[i], V[j]) for i, j in itertools.combinations(range(3), 2)])
        D = mean([l1_over2(H[i], H[j]) for i, j in itertools.combinations(range(3), 2)])
        per.append({"date": date, "n": n, "valid_counts": vc, "total_counts": ac,
                    "C": C, "Ctot": Ctot, "J": round(J, 3), "D": round(D, 3)})
    good = [p for p in per if "C" in p]
    agg = {
        "Jbar": round(mean([p["J"] for p in good]), 3) if good else None,
        "Jmax": round(max([p["J"] for p in good]), 3) if good else None,
        "Cmax": max([p["C"] for p in good]) if good else None,
        "Cmean": round(mean([p["C"] for p in good]), 2) if good else None,
        "Ctotmax": max([p["Ctot"] for p in good]) if good else None,
        "Dbar": round(mean([p["D"] for p in good]), 3) if good else None,
        "mean_valid": round(mean([c for p in good for c in p["valid_counts"]]), 2) if good else None,
        "mean_total": round(mean([c for p in good for c in p["total_counts"]]), 2) if good else None,
        "cost": round(cost, 4), "mean_dur_s": round(mean(dur), 1) if dur else None,
        "mean_tokens": int(mean(toks)) if toks else None,
        "max_tokens_call": max(toks) if toks else None,
        "total_tokens": sum(toks) if toks else None,
        "served": sorted(served), "precondition_fail": precondition_fail,
        "n_articles_scored": len(good),
    }
    return per, agg


def main():
    results = {}
    for arm in ARMS:
        per, agg = score_arm(arm)
        results[arm] = {"per_article": per, "agg": agg}

    inc = results["incumbent"]["agg"]
    print("\n=== Phase-0 per-arm aggregates ===")
    hdr = f"{'arm':10} {'Jbar':>6} {'Jmax':>6} {'Cmax':>5} {'Cmean':>6} {'Dbar':>6} {'mV':>5} {'mT':>5} {'meanTok':>8} {'maxTok':>7} {'cost$':>7} {'dur':>6} precond"
    print(hdr)
    for arm in ARMS:
        a = results[arm]["agg"]
        pf = "OK" if not a["precondition_fail"] else f"FAIL({len(a['precondition_fail'])})"
        print(f"{arm:10} {str(a['Jbar']):>6} {str(a['Jmax']):>6} {str(a['Cmax']):>5} "
              f"{str(a['Cmean']):>6} {str(a['Dbar']):>6} "
              f"{str(a['mean_valid']):>5} {str(a['mean_total']):>5} {str(a['mean_tokens']):>8} "
              f"{str(a['max_tokens_call']):>7} {str(a['cost']):>7} "
              f"{str(a['mean_dur_s']):>6} {pf}")

    print("\n=== GATE (PASS iff Jbar<=inc AND Cmax<=inc AND no precondition fail) ===")
    print(f"incumbent bar:  Jbar<={inc['Jbar']}  Cmax<={inc['Cmax']}")
    for arm in ARMS:
        if arm == "incumbent":
            continue
        a = results[arm]["agg"]
        if a["precondition_fail"] or a["n_articles_scored"] < len(ARTICLES):
            verdict = "FAIL (precondition/incomplete)"
        else:
            j_ok = a["Jbar"] <= inc["Jbar"]
            c_ok = a["Cmax"] <= inc["Cmax"]
            verdict = "PASS" if (j_ok and c_ok) else f"FAIL (Jbar_ok={j_ok} Cmax_ok={c_ok})"
        print(f"  {arm:10} -> {verdict}")

    print("\n=== served providers (fp4-confound record) ===")
    for arm in ARMS:
        print(f"  {arm:10} {results[arm]['agg']['served']}")

    json.dump(results, open(HERE / "gate.json", "w"), ensure_ascii=False, indent=1)
    print(f"\nwrote {HERE/'gate.json'}")


if __name__ == "__main__":
    main()
