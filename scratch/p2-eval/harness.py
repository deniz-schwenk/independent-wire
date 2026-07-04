"""Hydration Phase-2 model-eval harness (read-only on production).

Reconstructs the EXACT production phase-2 reducer input from stored
`topic_buses.HydrationPhase1Stage.N.json` snapshots (which carry
editor_selected_topic + hydration_phase1_analyses + hydration_fetch_results)
and runs it through five arms using the production PHASE2 prompts +
HYDRATION_PHASE2_SCHEMA. The incumbent is the STORED output from
`topic_buses.HydrationPhase2Stage.N.json` (+ its run_stage_log cost); the four
challengers are live shadow calls. Every call's raw output + metrics is
persisted immediately so no spend is lost to a crash.

Usage:
  uv run python scratch/p2-eval/harness.py probe            # 1 call/arm, sample topic
  uv run python scratch/p2-eval/harness.py sizes            # input-size census (free)
  uv run python scratch/p2-eval/harness.py run <arm> <date> <N>
  uv run python scratch/p2-eval/harness.py shadow <arm> [conc]
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.agent import Agent, AgentError  # noqa: E402
from src.bus import TopicBus  # noqa: E402
from src.agent_stages import _build_article_metadata, _PHASE2_USER_MESSAGE  # noqa: E402
from src.schemas import HYDRATION_PHASE2_SCHEMA  # noqa: E402

RAW = Path(__file__).resolve().parent / "raw"
RAW.mkdir(parents=True, exist_ok=True)
AGENTS = REPO / "agents" / "hydration_aggregator"
SYS_P = str(AGENTS / "PHASE2-SYSTEM.md")
INS_P = str(AGENTS / "PHASE2-INSTRUCTIONS.md")

# --- Provider pins (verbatim from scripts/run.py verification docs) ----------
GLM_5_2_FP8_ROUTING = {
    "order": ["baidu/fp8", "ambient/fp8", "venice/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}
DEEPSEEK_V4_PRO_FP8_ROUTING = {
    "order": ["baidu/fp8", "wandb/fp8", "parasail/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}

# --- 21 most-recent in-window topics (prompts+schema stable since 2026-04-28;
# hydrated canonical since 2026-05-19). Floor 15. -----------------------------
ARTICLES = [
    (d, n)
    for d in ("2026-06-28", "2026-06-29", "2026-06-30",
              "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04")
    for n in (0, 1, 2)
]

ARMS = ("incumbent", "glm", "deepseek", "sonnet5", "golden")


def build_agent(arm: str) -> Agent:
    common = dict(system_prompt_path=SYS_P, instructions_path=INS_P,
                  tools=[], provider="openrouter",
                  output_schema=HYDRATION_PHASE2_SCHEMA)
    if arm == "glm":
        return Agent(name="p2_glm", model="z-ai/glm-5.2", temperature=0.1,
                     max_tokens=120000, reasoning={"effort": "xhigh"},
                     provider_routing=GLM_5_2_FP8_ROUTING, **common)
    if arm == "deepseek":
        return Agent(name="p2_deepseek", model="deepseek/deepseek-v4-pro",
                     temperature=0.1, max_tokens=120000,
                     reasoning={"effort": "xhigh"},
                     provider_routing=DEEPSEEK_V4_PRO_FP8_ROUTING, **common)
    if arm == "sonnet5":
        return Agent(name="p2_sonnet5", model="anthropic/claude-sonnet-5",
                     temperature=None, max_tokens=64000,
                     reasoning={"enabled": True, "effort": "high"}, **common)
    if arm == "golden":
        return Agent(name="p2_golden", model="anthropic/claude-opus-4.8",
                     temperature=None, max_tokens=64000,
                     reasoning={"enabled": True, "effort": "high"}, **common)
    raise SystemExit(f"unknown/live-less arm {arm}")


def _run_dir(date: str) -> str:
    return glob.glob(f"{REPO}/output/{date}/_state/run-*")[0]


def load_input(date: str, n: int) -> dict:
    """Exact phase-2 reducer input, reconstructed read-only from the
    HydrationPhase1Stage snapshot."""
    run = _run_dir(date)
    tb = TopicBus.model_validate(
        json.load(open(os.path.join(run, f"topic_buses.HydrationPhase1Stage.{n}.json"))))
    successful = [r for r in (tb.hydration_fetch_results or [])
                  if isinstance(r, dict) and r.get("status") == "success"]
    assignment = tb.editor_selected_topic
    return {
        "assignment": {"title": assignment.title,
                       "selection_reason": assignment.selection_reason},
        "article_analyses": list(tb.hydration_phase1_analyses or []),
        "article_metadata": _build_article_metadata(successful),
    }


def load_incumbent(date: str, n: int) -> dict:
    """Stored production phase-2 output + its run_stage_log cost."""
    run = _run_dir(date)
    tb = TopicBus.model_validate(
        json.load(open(os.path.join(run, f"topic_buses.HydrationPhase2Stage.{n}.json"))))
    corpus = tb.hydration_phase2_corpus
    cost = tokens = None
    log = os.path.join(run, "run_stage_log.jsonl")
    if os.path.exists(log):
        for line in open(log):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("stage") == "HydrationPhase2Stage" and row.get("topic_index") == n:
                cost = row.get("cost_usd")
                tokens = row.get("tokens") or row.get("tokens_used")
    return {
        "preliminary_divergences": list(corpus.preliminary_divergences or []),
        "coverage_gaps": list(corpus.coverage_gaps or []),
        "cost_usd": cost, "tokens": tokens,
    }


def raw_path(arm: str, date: str, n: int) -> Path:
    return RAW / f"{arm}__{date}_{n}.json"


async def run_one(arm: str, date: str, n: int) -> dict:
    out = raw_path(arm, date, n)
    if out.exists() and json.load(open(out)).get("ok"):
        return json.load(open(out))
    payload = load_input(date, n)
    n_an = len(payload["article_analyses"])
    rec: dict = {"arm": arm, "date": date, "topic": n, "n_analyses": n_an,
                 "input_chars": len(json.dumps(payload, ensure_ascii=False))}
    if arm == "incumbent":
        inc = load_incumbent(date, n)
        rec.update(ok=True, structured={
            "preliminary_divergences": inc["preliminary_divergences"],
            "coverage_gaps": inc["coverage_gaps"]},
            cost_usd=inc["cost_usd"], tokens=inc["tokens"], stored=True)
        json.dump(rec, open(out, "w"), ensure_ascii=False, indent=1)
        return rec
    agent = build_agent(arm)
    t0 = time.monotonic()
    try:
        res = await agent.run(_PHASE2_USER_MESSAGE, context=payload)
        rec.update(ok=True, structured=res.structured,
                   structured_is_none=res.structured is None,
                   cost_usd=res.cost_usd, tokens=res.tokens_used,
                   duration_s=round(time.monotonic() - t0, 1),
                   served_provider=res.provider, response_id=res.response_id,
                   n_divergences=len((res.structured or {}).get("preliminary_divergences") or []),
                   n_gaps=len((res.structured or {}).get("coverage_gaps") or []))
    except AgentError as e:
        rec.update(ok=False, error=f"{e.__class__.__name__}: {e}",
                   duration_s=round(time.monotonic() - t0, 1))
    json.dump(rec, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"  [{'OK ' if rec.get('ok') else 'ERR'}] {arm:9} {date}#{n} "
          f"an={n_an} div={rec.get('n_divergences','-')} gap={rec.get('n_gaps','-')} "
          f"prov={rec.get('served_provider','-'):16} ${rec.get('cost_usd',0) or 0:.4f} "
          f"{rec.get('duration_s','-')}s {rec.get('error','')}")
    return rec


def cmd_sizes():
    """Free input-size census across the 21 topics (for the projection)."""
    rows = []
    for date, n in ARTICLES:
        p = load_input(date, n)
        inc = load_incumbent(date, n)
        rows.append((date, n, len(p["article_analyses"]),
                     len(json.dumps(p, ensure_ascii=False)),
                     inc["cost_usd"], len(inc["preliminary_divergences"]),
                     len(inc["coverage_gaps"])))
    print(f"{'topic':16} {'n_an':>4} {'in_chars':>9} {'inc_$':>8} {'div':>4} {'gap':>4}")
    tot_chars = tot_cost = 0
    for d, n, na, ch, c, dv, gp in rows:
        tot_chars += ch
        tot_cost += (c or 0)
        print(f"  {d}#{n:<10} {na:>4} {ch:>9} {(c or 0):>8.4f} {dv:>4} {gp:>4}")
    k = len(rows)
    print(f"\n  topics={k}  mean_analyses={sum(r[2] for r in rows)/k:.1f}  "
          f"mean_in_chars={tot_chars//k}  (~{tot_chars//k//4} tok)  "
          f"incumbent mean $/topic={tot_cost/k:.4f}")


async def cmd_probe():
    """One call per live arm on the largest-input topic (worst case for cost)."""
    census = [(d, n, len(load_input(d, n)["article_analyses"])) for d, n in ARTICLES]
    date, n, _ = max(census, key=lambda t: t[2])
    print(f"probe topic = {date}#{n} (largest by analyses count)\n")
    for arm in ("glm", "deepseek", "sonnet5", "golden"):
        await run_one(arm, date, n)


async def cmd_shadow(arm: str, conc: int = 4):
    sem = asyncio.Semaphore(conc)

    async def guarded(d, n):
        async with sem:
            try:
                return await run_one(arm, d, n)
            except Exception as e:  # noqa: BLE001
                print(f"  [XXX] {arm} {d}#{n} {e.__class__.__name__}: {e}")
                return None
    await asyncio.gather(*(guarded(d, n) for d, n in ARTICLES))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sizes"
    if cmd == "sizes":
        cmd_sizes()
    elif cmd == "probe":
        asyncio.run(cmd_probe())
    elif cmd == "run":
        asyncio.run(run_one(sys.argv[2], sys.argv[3], int(sys.argv[4])))
    elif cmd == "shadow":
        asyncio.run(cmd_shadow(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4))
    else:
        raise SystemExit(__doc__)
