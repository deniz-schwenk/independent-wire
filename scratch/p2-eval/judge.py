"""Blind judging: 3 fresh Opus-4.8 judges per topic over the 5 anonymized,
order-randomized phase-2 outputs, anchor-free against the phase-1 analyses.

Leak-proof anonymization: each topic gets a deterministic label permutation
(seeded by date#topic, NO wall-clock) mapping arms -> labels A..E; the judge
sees only {label, preliminary_divergences, coverage_gaps} + the ground-truth
analyses. The label->arm key is written to a SEPARATE file the judge never sees.
The parent never judges — each verdict is a fresh Opus-4.8 call.

  uv run python scratch/p2-eval/judge.py probe          # 1 judge call, 1 topic
  uv run python scratch/p2-eval/judge.py run [conc]     # 3 judges x all ready topics
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from src.agent import Agent, AgentError  # noqa: E402
from harness import ARTICLES, ARMS, load_input, raw_path  # noqa: E402

VERD = HERE / "verdicts"
VERD.mkdir(exist_ok=True)
KEYS = HERE / "anon_keys"
KEYS.mkdir(exist_ok=True)
N_JUDGES = 3

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "grounding": {"type": "integer"},
                    "specificity": {"type": "integer"},
                    "cross_group_validity": {"type": "integer"},
                    "gap_quality": {"type": "integer"},
                    "overall": {"type": "integer"},
                    "fabricated_divergences": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "quote": {"type": "string"},
                                "why_unsupported": {"type": "string"},
                            },
                            "required": ["quote", "why_unsupported"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["label", "grounding", "specificity",
                             "cross_group_validity", "gap_quality", "overall",
                             "fabricated_divergences"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["assessments"],
    "additionalProperties": False,
}

JUDGE_MESSAGE = (
    "Score each anonymized candidate's phase-2 output against the article "
    "analyses (your only ground truth), and list every fabricated divergence."
)


def judge_agent(idx: int) -> Agent:
    return Agent(
        name=f"p2_judge{idx}", model="anthropic/claude-opus-4.8",
        system_prompt_path=str(HERE / "JUDGE-SYSTEM.md"),
        instructions_path=str(HERE / "JUDGE-INSTRUCTIONS.md"),
        tools=[], provider="openrouter", temperature=None,
        max_tokens=64000, reasoning={"enabled": True, "effort": "high"},
        output_schema=JUDGE_SCHEMA)


def _perm(date: str, n: int) -> list[int]:
    """Deterministic label permutation from a stable seed (no wall-clock)."""
    h = int(hashlib.sha256(f"{date}#{n}".encode()).hexdigest(), 16)
    order = list(range(len(ARMS)))
    # Fisher–Yates with the hash as the entropy source.
    for i in range(len(order) - 1, 0, -1):
        h, j = divmod(h, i + 1)
        order[i], order[j] = order[j], order[i]
    return order


def topic_ready(date: str, n: int) -> bool:
    for arm in ARMS:
        p = raw_path(arm, date, n)
        if not p.exists():
            return False
        r = json.load(open(p))
        if not r.get("ok"):
            return False
    return True


def build_blind(date: str, n: int) -> tuple[dict, dict]:
    """Return (judge_context, label->arm key). Labels A..E in a permuted order."""
    inp = load_input(date, n)
    letters = [chr(ord("A") + i) for i in range(len(ARMS))]
    perm = _perm(date, n)                       # perm[k] = arm index for slot k
    candidates, key = [], {}
    for slot, arm_i in enumerate(perm):
        arm = ARMS[arm_i]
        st = json.load(open(raw_path(arm, date, n))).get("structured") or {}
        label = letters[slot]
        key[label] = arm
        candidates.append({
            "label": label,
            "preliminary_divergences": list(st.get("preliminary_divergences") or []),
            "coverage_gaps": list(st.get("coverage_gaps") or []),
        })
    ctx = {
        "assignment": inp["assignment"],
        "article_analyses": inp["article_analyses"],
        "article_metadata": inp["article_metadata"],
        "candidates": candidates,
    }
    return ctx, key


async def judge_topic(date: str, n: int) -> None:
    ctx, key = build_blind(date, n)
    json.dump(key, open(KEYS / f"{date}_{n}.json", "w"), indent=1)
    for j in range(N_JUDGES):
        out = VERD / f"{date}_{n}__j{j}.json"
        if out.exists() and json.load(open(out)).get("ok"):
            continue
        agent = judge_agent(j)
        t0 = time.monotonic()
        rec = {"date": date, "topic": n, "judge": j}
        try:
            res = await agent.run(JUDGE_MESSAGE, context=ctx)
            rec.update(ok=True, structured=res.structured,
                       cost_usd=res.cost_usd, tokens=res.tokens_used,
                       duration_s=round(time.monotonic() - t0, 1),
                       provider=res.provider)
        except AgentError as e:
            rec.update(ok=False, error=f"{e.__class__.__name__}: {e}",
                       duration_s=round(time.monotonic() - t0, 1))
        json.dump(rec, open(out, "w"), ensure_ascii=False, indent=1)
        print(f"  [{'OK ' if rec.get('ok') else 'ERR'}] judge {date}#{n} j{j} "
              f"${rec.get('cost_usd',0) or 0:.4f} {rec.get('duration_s','-')}s "
              f"{rec.get('error','')}")


async def cmd_probe():
    date, n = next((d, x) for d, x in ARTICLES if topic_ready(d, x))
    print(f"judge probe on {date}#{n} (1 judge call)\n")
    ctx, key = build_blind(date, n)
    json.dump(key, open(KEYS / f"{date}_{n}.json", "w"), indent=1)
    agent = judge_agent(0)
    t0 = time.monotonic()
    res = await agent.run(JUDGE_MESSAGE, context=ctx)
    out = VERD / f"{date}_{n}__j0.json"
    json.dump({"date": date, "topic": n, "judge": 0, "ok": True,
               "structured": res.structured, "cost_usd": res.cost_usd,
               "tokens": res.tokens_used, "provider": res.provider,
               "duration_s": round(time.monotonic() - t0, 1)},
              open(out, "w"), ensure_ascii=False, indent=1)
    print(f"  judge probe: ${res.cost_usd:.4f}  tok={res.tokens_used}  "
          f"{round(time.monotonic()-t0,1)}s  prov={res.provider}")
    print(f"  -> 63-call projection: ${res.cost_usd*63:.2f} (all 21) / "
          f"${res.cost_usd*45:.2f} (floor 15)")


async def cmd_run(conc: int = 4):
    ready = [(d, n) for d, n in ARTICLES if topic_ready(d, n)]
    print(f"judging {len(ready)} ready topics x {N_JUDGES} judges\n")
    sem = asyncio.Semaphore(conc)

    async def g(d, n):
        async with sem:
            try:
                return await judge_topic(d, n)
            except Exception as e:  # noqa: BLE001
                print(f"  [XXX] {d}#{n} {e.__class__.__name__}: {e}")
    await asyncio.gather(*(g(d, n) for d, n in ready))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe":
        asyncio.run(cmd_probe())
    elif cmd == "run":
        asyncio.run(cmd_run(int(sys.argv[2]) if len(sys.argv) > 2 else 4))
