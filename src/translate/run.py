"""Per-TP translation with one provider — the unit the fallback chain retries.

A faithful refactor of the validated driver_v3.run_tp: 5-block segmentation, one
json_object/strict-tools block call per sub-batch, per-item deterministic guard, and a
temperature-ladder repair of any failing item — but provider-parameterized and reporting
a single per-TP `ok`. The orchestrator (scripts/translate_de.py) tries providers in order
and moves to the next whenever `translate_tp` returns ok=False (a guard miss the ladder
could not clean) or raises TransportError (a whole-TP transport failure). Providers are
never mixed within one TP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import core
from .transport import Provider, TransportError

TEMP_LADDER = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]   # models.json b_probe_ladder
BATCH_SIZE = 8


@dataclass
class TPResult:
    tp_id: str
    provider: str
    ok: bool = False
    reason: str | None = None
    items: list[dict] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    entity_index: dict = field(default_factory=dict)
    calls: int = 0
    repairs: int = 0
    cost_usd: float = 0.0
    wall_s: float = 0.0
    degenerate: list[str] = field(default_factory=list)

    @property
    def src_tokens_expected(self) -> int:
        return sum(it["src_tokens_expected"] for it in self.items)

    @property
    def src_tokens_present(self) -> int:
        return sum(it["src_tokens_present"] for it in self.items)


def _by_key(parsed) -> dict:
    out = {}
    if isinstance(parsed, dict):
        for o in (parsed.get("items") or []):
            if isinstance(o, dict) and o.get("key") is not None:
                out[str(o["key"])] = o
    return out


async def _repair_item(provider: Provider, system, instr, glossary, prior, it):
    """Walk the temperature ladder until the guard passes or the ladder is exhausted.
    Returns (best_final, degenerate, n_calls, latency, cost). May raise TransportError."""
    cands, total_lat, total_cost, n = [], 0.0, 0.0, 0
    for temp in TEMP_LADDER:
        user = core.build_block_user(instr, glossary, prior, [it])
        parsed, meta = await provider.generate(system, user, temp)
        total_lat += meta["latency_s"]
        total_cost += meta.get("cost_usd", 0.0)
        n += 1
        o = _by_key(parsed).get(it["key"], {})
        final = o.get("final") if isinstance(o, dict) else None
        cands.append(final or "")
        ok, _, _ = core.item_ok(it["text"], o)
        if ok:
            return final, False, n, round(total_lat, 2), total_cost
    return core.best_candidate(*cands), True, n, round(total_lat, 2), total_cost


async def _translate_batch(provider, system, instr, glossary, prior, items):
    """One sub-batch: a single block call, then per-item guard + ladder repair."""
    user = core.build_block_user(instr, glossary, prior, items)
    parsed, meta = await provider.generate(system, user, TEMP_LADDER[0])
    by_key = _by_key(parsed)
    calls, repairs, lat, cost = 1, 0, meta["latency_s"], meta.get("cost_usd", 0.0)
    item_recs, clean_finals = [], []
    for it in items:
        o = by_key.get(it["key"], {})
        ok, reason, _ = core.item_ok(it["text"], o)
        final = o.get("final") if isinstance(o, dict) else None
        degenerate, repaired = False, False
        if not ok:
            repaired = True
            final, degenerate, n_try, rlat, rcost = await _repair_item(
                provider, system, instr, glossary, prior, it)
            calls += n_try
            repairs += 1
            lat += rlat
            cost += rcost
        want = core.SRC_TOKEN.findall(it["text"])
        clean = isinstance(final, str) and bool(final.strip()) and not degenerate
        if clean:
            clean_finals.append(final)
        item_recs.append({
            "key": it["key"], "path": it["path"], "src_chars": len(it["text"]),
            "final_chars": len(final or ""), "ok": clean, "degenerate": degenerate,
            "repaired": repaired, "guard_reason": (None if ok else reason),
            "src_tokens_expected": len(want),
            "src_tokens_present": sum(1 for s in want if s in (final or "")),
            "final": final,
        })
    return item_recs, clean_finals, calls, repairs, round(lat, 2), cost


async def translate_tp(provider: Provider, tp: dict, batch_size: int = BATCH_SIZE) -> TPResult:
    """Translate one TP with a single provider. Returns a TPResult; ok=False (with a
    reason) when a guard miss survives the ladder or a transport error aborts the TP."""
    tp_id = tp.get("id", "unknown")
    res = TPResult(tp_id=tp_id, provider=provider.name)
    exonyms, places = core.load_tables()
    index = core.build_entity_index(tp, exonyms, places)
    res.entity_index = {
        "resolved": index["resolved"], "keep_original": sorted(index["keep_orig"]),
        "persons": index["persons"], "generic_passthrough": index["generic"],
        "pending_candidates": index["pending"]}
    blocks = core.build_blocks(tp)
    system, instr = core.load_prompt()
    prior: list[str] = []

    try:
        for blk in blocks:
            btext = "\n\n".join(it["text"] for it in blk["items"])
            gloss = core.glossary_for(btext, index)
            core.append_pending(core.pending_in(btext, index), tp_id, blk["name"])
            b_items, b_calls, b_rep, b_lat, b_cost = [], 0, 0, 0.0, 0.0
            for batch in core.chunk(blk["items"], batch_size):
                recs, cleans, c, r, lat, cost = await _translate_batch(
                    provider, system, instr, gloss, prior, batch)
                for rec in recs:
                    rec["block"] = blk["name"]
                b_items += recs
                prior.extend(cleans)
                b_calls += c; b_rep += r; b_lat += lat; b_cost += cost
            res.items += b_items
            res.calls += b_calls
            res.repairs += b_rep
            res.wall_s += b_lat
            res.cost_usd += b_cost
            res.blocks.append({
                "name": blk["name"], "n_items": len(blk["items"]), "calls": b_calls,
                "repairs": b_rep, "glossary_size": len(gloss),
                "clean_items": sum(1 for r in b_items if r["ok"]),
                "latency_s": round(b_lat, 2), "cost_usd": round(b_cost, 6)})
    except TransportError as e:
        res.ok = False
        res.reason = f"transport: {e}"
        return res

    res.wall_s = round(res.wall_s, 2)
    res.cost_usd = round(res.cost_usd, 6)
    res.degenerate = [it["path"] for it in res.items if it["degenerate"]]
    if res.degenerate:
        res.ok = False
        res.reason = f"guard: {len(res.degenerate)} item(s) degenerate after ladder"
    else:
        res.ok = True
    return res
