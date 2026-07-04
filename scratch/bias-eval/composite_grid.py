"""Stability re-measurement of the extract->union->judge composite on the SAME
5-article x 3-cache-cold grid (TASK-BIAS-STAGE-SPLIT decisive gate).

Uses the real production wiring (create_agents()["bias_language"]) so the
measurement is faithful. A FRESH composite is built per call so concurrent calls
never race on the wrapper's instance accumulators. Crash-safe: skips completed
cells.

  uv run python scratch/bias-eval/composite_grid.py run     # fill the grid
  uv run python scratch/bias-eval/composite_grid.py score   # Jbar + PASS/FAIL
"""
from __future__ import annotations

import asyncio
import glob
import itertools
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import load_input, STAGE_MESSAGE, ARTICLES  # noqa: E402
from scripts.run import create_agents  # noqa: E402

RAW = Path(__file__).resolve().parent / "raw_composite"
RAW.mkdir(parents=True, exist_ok=True)


def make_composite():
    return create_agents()["bias_language"]


async def run_one(date: str, n: int, rep: int) -> dict:
    out = RAW / f"{date}_{n}__r{rep}.json"
    if out.exists():
        prev = json.load(open(out))
        if prev.get("ok"):
            return prev
    body, bias_card = load_input(date, n)
    comp = make_composite()
    comp.reset_call_metrics()
    t0 = time.monotonic()
    rec: dict = {"date": date, "topic": n, "rep": rep, "body_chars": len(body)}
    try:
        res = await comp.run(
            STAGE_MESSAGE, context={"article_body": body, "bias_card": bias_card})
        lb = (res.structured or {}).get("language_bias", {})
        findings = lb.get("findings", [])
        borderline = lb.get("borderline", [])
        rec.update(
            ok=True,
            excerpts=[f.get("excerpt", "") for f in findings],
            confidences=[f.get("extraction_confidence") for f in findings],
            borderline_excerpts=[b.get("excerpt", "") for b in borderline],
            # full per-candidate verdict breakdown (confirmed/borderline/cleared
            # + position) — the flip-distance gate reads this.
            judged=list(comp.last_judgments_debug),
            confirmed=len(findings),
            borderline_n=len(borderline),
            reader_note_len=len(res.structured.get("reader_note", "") or ""),
            cost_usd=res.cost_usd, tokens=res.tokens_used,
            duration_s=round(time.monotonic() - t0, 1),
            provider=res.provider,
            metrics=dict(comp.extra_log_fields),
        )
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error=f"{e.__class__.__name__}: {e}",
                   duration_s=round(time.monotonic() - t0, 1))
    json.dump(rec, open(out, "w"), ensure_ascii=False, indent=1)
    m = rec.get("metrics", {})
    print(f"  [{'OK ' if rec.get('ok') else 'ERR'}] {date}#{n} r{rep} "
          f"conf={rec.get('confirmed','-')} bord={rec.get('borderline_n','-')} "
          f"clr={m.get('cleared_count','-')} union={m.get('union_size','-')} "
          f"${rec.get('cost_usd',0):.4f} {rec.get('duration_s','-')}s {rec.get('error','')}")
    return rec


async def cmd_run(conc: int = 5):
    sem = asyncio.Semaphore(conc)
    jobs = [(d, n, r) for (d, n) in ARTICLES for r in (0, 1, 2)]

    async def guarded(job):
        async with sem:
            try:
                return await run_one(*job)
            except Exception as e:  # noqa: BLE001
                print(f"  [XXX] {job} {e.__class__.__name__}: {e}")
                return None
    await asyncio.gather(*(guarded(j) for j in jobs))


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _je(a, b):
    a, b = set(a), set(b)
    return 1.0 if not a and not b else (len(a & b) / len(a | b) if (a | b) else 1.0)


def _js(a, b):
    A = [_norm(x) for x in a if _norm(x)]
    B = [_norm(x) for x in b if _norm(x)]
    if not A and not B:
        return 1.0
    m, used = 0, set()
    for x in A:
        for j, y in enumerate(B):
            if j in used:
                continue
            if x == y or x in y or y in x:
                m += 1
                used.add(j)
                break
    u = len(A) + len(B) - m
    return m / u if u else 1.0


def cmd_score():
    JE, JS, confirmed_all, costs = [], [], [], []
    print("composite stability grid (confirmed-span sets across 3 cache-cold repeats):\n")
    print(f"{'article':22} {'confirmed':16} {'Jexact':>7} {'Jsoft':>6}")
    per = []
    for date, n in ARTICLES:
        reps = []
        for r in (0, 1, 2):
            f = RAW / f"{date}_{n}__r{r}.json"
            if not f.exists():
                print(f"  MISSING {date}#{n} r{r}"); return
            reps.append(json.load(open(f)))
        if not all(x.get("ok") for x in reps):
            print(f"  ERROR cell {date}#{n}: {[x.get('error') for x in reps]}"); return
        sets = [x["excerpts"] for x in reps]
        for x in reps:
            costs.append(x.get("cost_usd", 0) or 0)
        counts = [len(s) for s in sets]
        confirmed_all += counts
        e = 1 - sum(_je(sets[i], sets[j]) for i, j in itertools.combinations(range(3), 2)) / 3
        s = 1 - sum(_js(sets[i], sets[j]) for i, j in itertools.combinations(range(3), 2)) / 3
        JE.append(e); JS.append(s)
        per.append((date, n, counts, e, s))
        print(f"  {date}#{n:<18} {str(counts):16} {e:7.2f} {s:6.2f}")
    jbar_e = sum(JE) / len(JE)
    jbar_s = sum(JS) / len(JS)
    mean_conf = sum(confirmed_all) / len(confirmed_all)
    mean_cost = sum(costs) / (len(ARTICLES) * 3)
    print(f"\n  Jbar_exact = {jbar_e:.3f}   Jbar_soft = {jbar_s:.3f}")
    print(f"  mean confirmed / article = {mean_conf:.2f}")
    print(f"  mean $ / composite run   = ${mean_cost:.4f}   (target <= $0.06)")
    print(f"\n  incumbent bar (single-call Opus-4.6): Jbar_exact 0.510")
    if jbar_e <= 0.35:
        verdict = "PASS (Jbar_exact <= 0.35)"
    elif jbar_e <= 0.51:
        verdict = "STOP+REPORT — in (0.35, 0.51]: beats incumbent but below target"
    else:
        verdict = "FAIL — does not beat incumbent 0.51"
    print(f"  >>> GATE: {verdict}")
    json.dump({"jbar_exact": round(jbar_e, 3), "jbar_soft": round(jbar_s, 3),
               "mean_confirmed": round(mean_conf, 2), "mean_cost": round(mean_cost, 4),
               "verdict": verdict, "per_article": per},
              open(Path(__file__).resolve().parent / "composite_gate.json", "w"), indent=1)


def _overlap(a, b):
    """Two [pos,end) spans overlap (nesting or partial), both resolved."""
    pa, ea = a
    pb, eb = b
    return pa >= 0 and pb >= 0 and pa < eb and pb < ea


def cmd_scorev2():
    """Gate v2 (TASK-BIAS-TIER-MAPPING): two metrics.

    a) PRIMARY  — Jbar_exact over the CONFIRMED set (≤ 0.35 to PASS).
    b) HARD     — zero full flips: no candidate family may be `confirmed`
                  in one rep and `cleared` in another (matched by positional
                  overlap across reps). Adjacent drift (↔ borderline) is
                  reported informationally, not gated.
    Also: borderline set size + churn, mean confirmed, $/article.
    """
    JE, confirmed_all, bord_all, costs = [], [], [], []
    BJE = []  # borderline-set Jbar (informational)
    flips_total = 0
    flip_detail = []
    per = []
    print("gate v2 — confirmed-set stability + full-flip distance:\n")
    print(f"{'article':22} {'confirmed':14} {'Jconf':>6} {'borderline':12} "
          f"{'Jbord':>6} {'flips':>5}")
    for date, n in ARTICLES:
        reps = []
        for r in (0, 1, 2):
            f = RAW / f"{date}_{n}__r{r}.json"
            if not f.exists():
                print(f"  MISSING {date}#{n} r{r}"); return
            reps.append(json.load(open(f)))
        if not all(x.get("ok") for x in reps):
            print(f"  ERROR cell {date}#{n}: {[x.get('error') for x in reps]}"); return

        conf_sets = [x.get("excerpts", []) for x in reps]
        bord_sets = [x.get("borderline_excerpts", []) for x in reps]
        for x in reps:
            costs.append(x.get("cost_usd", 0) or 0)
        confirmed_all += [len(s) for s in conf_sets]
        bord_all += [len(s) for s in bord_sets]

        je = 1 - sum(_je(conf_sets[i], conf_sets[j])
                     for i, j in itertools.combinations(range(3), 2)) / 3
        bje = 1 - sum(_je(bord_sets[i], bord_sets[j])
                      for i, j in itertools.combinations(range(3), 2)) / 3
        JE.append(je); BJE.append(bje)

        # full flips: confirmed span in rep i overlaps a cleared span in rep j.
        judged = [x.get("judged", []) for x in reps]
        conf_spans = [[(d["pos"], d["end"], d["excerpt"]) for d in judged[r]
                       if d.get("verdict") == "confirmed"] for r in range(3)]
        clr_spans = [[(d["pos"], d["end"], d["excerpt"]) for d in judged[r]
                      if d.get("verdict") == "cleared"] for r in range(3)]
        art_flips = set()
        for i in range(3):
            for j in range(3):
                if i == j:
                    continue
                for (pi, ei, exc) in conf_spans[i]:
                    for (pj, ej, cexc) in clr_spans[j]:
                        if _overlap((pi, ei), (pj, ej)):
                            key = tuple(sorted([exc, cexc]))
                            art_flips.add(key)
                            flip_detail.append(
                                f"{date}#{n}: '{exc}' (confirmed r{i}) ↔ "
                                f"'{cexc}' (cleared r{j})")
        flips_total += len(art_flips)
        per.append((date, n, [len(s) for s in conf_sets], je,
                    [len(s) for s in bord_sets], bje, len(art_flips)))
        print(f"  {date}#{n:<18} {str([len(s) for s in conf_sets]):14} {je:6.2f} "
              f"{str([len(s) for s in bord_sets]):12} {bje:6.2f} {len(art_flips):5}")

    jbar_e = sum(JE) / len(JE)
    jbar_bord = sum(BJE) / len(BJE)
    mean_conf = sum(confirmed_all) / len(confirmed_all)
    mean_bord = sum(bord_all) / len(bord_all)
    mean_cost = sum(costs) / (len(ARTICLES) * 3)
    print(f"\n  PRIMARY  Jbar_exact (confirmed set) = {jbar_e:.3f}   (PASS ≤ 0.35)")
    print(f"  HARD     full flips (confirmed↔cleared) = {flips_total}   (PASS = 0)")
    print(f"  ---")
    print(f"  borderline Jbar (informational) = {jbar_bord:.3f}")
    print(f"  mean confirmed / article = {mean_conf:.2f}   "
          f"mean borderline / article = {mean_bord:.2f}")
    print(f"  mean $ / composite run   = ${mean_cost:.4f}   (target ≤ $0.06)")
    if flip_detail:
        print("\n  FLIPPING FAMILIES:")
        for d in flip_detail:
            print(f"    - {d}")
    primary_pass = jbar_e <= 0.35
    hard_pass = flips_total == 0
    if hard_pass and primary_pass:
        verdict = "PASS — Jbar_exact ≤ 0.35 AND zero full flips"
    elif not hard_pass:
        verdict = f"STOP+REPORT — {flips_total} full flip(s) (HARD gate); see families above"
    else:
        verdict = f"STOP+REPORT — Jbar_exact {jbar_e:.3f} in (0.35, ..]; zero flips"
    print(f"\n  >>> GATE v2: {verdict}")
    json.dump({"jbar_confirmed": round(jbar_e, 3), "full_flips": flips_total,
               "jbar_borderline": round(jbar_bord, 3),
               "mean_confirmed": round(mean_conf, 2),
               "mean_borderline": round(mean_bord, 2),
               "mean_cost": round(mean_cost, 4),
               "primary_pass": primary_pass, "hard_pass": hard_pass,
               "verdict": verdict, "flip_detail": flip_detail, "per_article": per},
              open(Path(__file__).resolve().parent / "composite_gate_v2.json", "w"),
              indent=1, ensure_ascii=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        asyncio.run(cmd_run(int(sys.argv[2]) if len(sys.argv) > 2 else 5))
    elif cmd == "score":
        cmd_score()
    elif cmd == "scorev2":
        cmd_scorev2()
