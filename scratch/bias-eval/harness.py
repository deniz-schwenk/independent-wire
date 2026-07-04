"""Bias-stage model-eval harness (read-only on production).

Reconstructs the EXACT production bias_language input from stored
`topic_buses.BiasLanguageStage.N.json` snapshots and runs it through four
candidate arms using the production prompts + BIAS_DETECTOR_SCHEMA. Every
call's raw output + metrics (cost, tokens, latency, served provider,
response id) is persisted immediately to scratch/bias-eval/raw/ so no
spend is ever lost to a crash.

Usage:
  uv run python scratch/bias-eval/harness.py probe            # 1 call/arm on article 1
  uv run python scratch/bias-eval/harness.py phase0           # full 4x5x3 grid (skips done)
  uv run python scratch/bias-eval/harness.py run <arm> <date> <N> <rep>
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
from src.agent_stages import _build_bias_card_for_agent_input  # noqa: E402
from src.schemas import BIAS_DETECTOR_SCHEMA  # noqa: E402

RAW = Path(__file__).resolve().parent / "raw"
RAW.mkdir(parents=True, exist_ok=True)
AGENTS_DIR = REPO / "agents"
SYS_P = str(AGENTS_DIR / "bias_detector" / "SYSTEM.md")
INS_P = str(AGENTS_DIR / "bias_detector" / "INSTRUCTIONS.md")

# The fixed stage message (verbatim from BiasLanguageStage.__call__).
STAGE_MESSAGE = (
    "Analyze this article for linguistic bias. Identify loaded "
    "language and produce a brief reader-note."
)

# --- Provider pins (copied verbatim from scripts/run.py) ---------------------
DEEPSEEK_V4_PRO_FP8_ROUTING = {
    "order": ["baidu/fp8", "wandb/fp8", "parasail/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}
GLM_5_2_FP8_ROUTING = {
    "order": ["baidu/fp8", "ambient/fp8", "venice/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}

# --- Phase-0 article manifest -----------------------------------------------
ARTICLES = [
    ("2026-06-13", 0),
    ("2026-06-17", 1),
    ("2026-06-02", 2),
    ("2026-06-22", 2),
    ("2026-06-20", 0),
]

# --- Phase-1 quality set: the 21 most-recent in-window topics ---------------
# (06-28 -> 07-04, three topics each; disjoint from the Phase-0 five.)
PHASE1_ARTICLES = [
    (d, n)
    for d in ("2026-06-28", "2026-06-29", "2026-06-30",
              "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04")
    for n in (0, 1, 2)
]
RAW_P1 = Path(__file__).resolve().parent / "raw_p1"
RAW_P1.mkdir(parents=True, exist_ok=True)

# --- Arm builders. Each returns a freshly-constructed Agent. ----------------
# temperature held at incumbent's 0.1 across arms that accept it; Sonnet-5
# omits it (5-family rejects non-default temp). deepseek_temp is toggled by
# the probe if V4-Pro@xhigh rejects a non-default temperature.
DEEPSEEK_TEMP: float | None = 0.1


def build_agent(arm: str) -> Agent:
    common = dict(
        system_prompt_path=SYS_P,
        instructions_path=INS_P,
        tools=[],
        provider="openrouter",
        output_schema=BIAS_DETECTOR_SCHEMA,
    )
    if arm == "incumbent":
        return Agent(
            name="bias_incumbent",
            model="anthropic/claude-opus-4.6",
            temperature=0.1,
            reasoning="none",
            **common,  # max_tokens default 32000 = production
        )
    if arm == "glm":
        return Agent(
            name="bias_glm",
            model="z-ai/glm-5.2",
            temperature=0.1,
            max_tokens=120000,
            reasoning={"effort": "xhigh"},
            provider_routing=GLM_5_2_FP8_ROUTING,
            **common,
        )
    if arm == "deepseek":
        return Agent(
            name="bias_deepseek",
            model="deepseek/deepseek-v4-pro",
            temperature=DEEPSEEK_TEMP,
            max_tokens=120000,
            reasoning={"effort": "xhigh"},
            provider_routing=DEEPSEEK_V4_PRO_FP8_ROUTING,
            **common,
        )
    if arm == "sonnet5":
        return Agent(
            name="bias_sonnet5",
            model="anthropic/claude-sonnet-5",
            temperature=None,
            max_tokens=64000,
            reasoning={"enabled": True, "effort": "high"},
            **common,
        )
    if arm in ("golden", "opus48"):
        # Opus-4.8, adaptive thinking enabled + effort high, via the identical
        # prompt/schema/input path. 4.x-reasoning family rejects non-default
        # temperature, so temp is omitted and effort set explicitly (same
        # shape as sonnet5). Doubles as the Phase-0 stability ceiling ('opus48')
        # and the (unentered) Phase-1 golden reference ('golden').
        return Agent(
            name=f"bias_{arm}",
            model="anthropic/claude-opus-4.8",
            temperature=None,
            max_tokens=64000,
            reasoning={"enabled": True, "effort": "high"},
            **common,
        )
    raise SystemExit(f"unknown arm {arm}")


def load_input(date: str, n: int) -> tuple[str, dict]:
    run = glob.glob(f"{REPO}/output/{date}/_state/run-*")[0]
    f = os.path.join(run, f"topic_buses.BiasLanguageStage.{n}.json")
    d = json.load(open(f))
    tb = TopicBus.model_validate(d)
    bias_card = _build_bias_card_for_agent_input(tb)
    return tb.qa_corrected_article.body, bias_card


def raw_path(arm: str, date: str, n: int, rep: int) -> Path:
    return RAW / f"{arm}__{date}_{n}__r{rep}.json"


async def run_one(arm: str, date: str, n: int, rep: int) -> dict:
    out = raw_path(arm, date, n, rep)
    if out.exists():
        prev = json.load(open(out))
        if prev.get("ok"):
            return prev  # only skip successful calls; retry errored ones
    body, bias_card = load_input(date, n)
    agent = build_agent(arm)
    t0 = time.monotonic()
    rec: dict = {
        "arm": arm, "date": date, "topic": n, "rep": rep,
        "model": agent.model, "body_chars": len(body),
    }
    try:
        res = await agent.run(
            STAGE_MESSAGE,
            context={"article_body": body, "bias_card": bias_card},
        )
        rec.update(
            ok=True,
            structured=res.structured,
            structured_is_none=res.structured is None,
            cost_usd=res.cost_usd,
            tokens=res.tokens_used,
            duration_s=round(time.monotonic() - t0, 1),
            served_provider=res.provider,
            response_id=res.response_id,
            content_len=len(res.content or ""),
        )
    except AgentError as e:
        rec.update(
            ok=False, error=f"{e.__class__.__name__}: {e}",
            duration_s=round(time.monotonic() - t0, 1),
        )
    json.dump(rec, open(out, "w"), ensure_ascii=False, indent=1)
    tag = "OK " if rec.get("ok") else "ERR"
    nf = len((rec.get("structured") or {}).get("language_bias", {}).get("findings", [])) if rec.get("ok") else "-"
    print(f"  [{tag}] {arm:9} {date}#{n} r{rep}  nf={nf} "
          f"prov={rec.get('served_provider','-'):18} "
          f"${rec.get('cost_usd',0):.4f} {rec.get('duration_s','-')}s "
          f"{rec.get('error','')}")
    return rec


async def cmd_probe():
    date, n = ARTICLES[0]
    for arm in ("incumbent", "glm", "deepseek", "sonnet5"):
        await run_one(arm, date, n, 0)


async def cmd_phase0():
    for arm in ("incumbent", "glm", "deepseek", "sonnet5"):
        print(f"== arm {arm} ==")
        for date, n in ARTICLES:
            for rep in (0, 1, 2):
                await run_one(arm, date, n, rep)


async def run_one_p1(arm: str, date: str, n: int) -> dict:
    """One Phase-1 quality call (single pass, no repeats). Writes raw_p1/."""
    out = RAW_P1 / f"{arm}__{date}_{n}.json"
    if out.exists():
        prev = json.load(open(out))
        if prev.get("ok"):
            return prev
    body, bias_card = load_input(date, n)
    agent = build_agent(arm)
    t0 = time.monotonic()
    rec: dict = {"arm": arm, "date": date, "topic": n, "model": agent.model,
                 "body_chars": len(body)}
    try:
        res = await agent.run(STAGE_MESSAGE,
                              context={"article_body": body, "bias_card": bias_card})
        rec.update(ok=True, structured=res.structured,
                   structured_is_none=res.structured is None,
                   cost_usd=res.cost_usd, tokens=res.tokens_used,
                   duration_s=round(time.monotonic() - t0, 1),
                   served_provider=res.provider, response_id=res.response_id,
                   content_len=len(res.content or ""))
    except AgentError as e:
        rec.update(ok=False, error=f"{e.__class__.__name__}: {e}",
                   duration_s=round(time.monotonic() - t0, 1))
    json.dump(rec, open(out, "w"), ensure_ascii=False, indent=1)
    nf = len((rec.get("structured") or {}).get("language_bias", {}).get("findings", [])) if rec.get("ok") else "-"
    print(f"  [{'OK ' if rec.get('ok') else 'ERR'}] {arm:9} {date}#{n} nf={nf} "
          f"prov={rec.get('served_provider','-'):12} ${rec.get('cost_usd',0):.4f} "
          f"{rec.get('duration_s','-')}s {rec.get('error','')}")
    return rec


async def cmd_phase1(arm: str, conc: int = 6):
    sem = asyncio.Semaphore(conc)

    async def guarded(date, n):
        async with sem:
            try:
                return await run_one_p1(arm, date, n)
            except Exception as e:
                print(f"  [XXX] {arm} {date}#{n} {e.__class__.__name__}: {e}")
                return None
    await asyncio.gather(*(guarded(d, n) for d, n in PHASE1_ARTICLES))


async def cmd_phase0par(conc: int = 6, arms=None):
    """Run the full grid concurrently (semaphore-bounded). Crash-safe:
    run_one skips any (arm,date,n,rep) whose raw file already exists."""
    arms = arms or ["incumbent", "glm", "deepseek", "sonnet5"]
    sem = asyncio.Semaphore(conc)
    jobs = [(arm, date, n, rep)
            for arm in arms for (date, n) in ARTICLES for rep in (0, 1, 2)]

    async def guarded(job):
        async with sem:
            try:
                return await run_one(*job)
            except Exception as e:  # never let one call sink the grid
                print(f"  [XXX] {job} unexpected {e.__class__.__name__}: {e}")
                return None
    await asyncio.gather(*(guarded(j) for j in jobs))


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "probe":
        asyncio.run(cmd_probe())
    elif cmd == "phase0":
        asyncio.run(cmd_phase0())
    elif cmd == "phase0par":
        conc = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        arms = sys.argv[3].split(",") if len(sys.argv) > 3 else None
        asyncio.run(cmd_phase0par(conc, arms))
    elif cmd == "phase1":
        asyncio.run(cmd_phase1(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6))
    elif cmd == "run":
        arm, date, n, rep = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
        asyncio.run(run_one(arm, date, n, rep))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
