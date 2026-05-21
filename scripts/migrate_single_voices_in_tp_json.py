#!/usr/bin/env python3
"""One-shot migration: rebuild `perspectives.mentioned_actors` on existing TP
JSON files from `actors[]` + `perspectives.position_clusters[]` + `sources[]`.

Used after the 2026-05-21 rename `single_voices → mentioned_actors` to bring
pre-rename TP JSON files (which carry only the legacy `single_voices` slot
with the ≥ 2-source orphan set) up to the new schema (every non-cluster
actor included, regardless of source count).

Invokes the live `derive_mentioned_actors` topic-stage on a TopicBus
synthesized from the JSON so the migration result is identical to what
the production pipeline would emit if replayed from before the bracket
stage. Removes the stale `single_voices` key.

Idempotent: re-runs on already-migrated JSON files write the same content.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.bus import RunBus, TopicBus
from src.stages.topic_stages import derive_mentioned_actors


def _migrate_one(path: Path) -> tuple[bool, int]:
    tp = json.loads(path.read_text(encoding="utf-8"))
    persp = tp.get("perspectives") or {}

    tb = TopicBus()
    tb.canonical_actors = list(tp.get("actors") or [])
    tb.perspective_clusters_synced = list(persp.get("position_clusters") or [])
    tb.final_sources = list(tp.get("sources") or [])

    rb_ro = RunBus().as_readonly()
    tb_after = asyncio.run(derive_mentioned_actors(tb, rb_ro))
    new_bracket = dict(tb_after.mentioned_actors or {})

    persp.pop("single_voices", None)
    persp["mentioned_actors"] = new_bracket
    tp["perspectives"] = persp

    new_text = json.dumps(tp, ensure_ascii=False, indent=2) + "\n"
    if path.read_text(encoding="utf-8") == new_text:
        return False, int(new_bracket.get("counts", {}).get("actors", 0) or 0)
    path.write_text(new_text, encoding="utf-8")
    return True, int(new_bracket.get("counts", {}).get("actors", 0) or 0)


def main() -> int:
    targets = sorted(
        ROOT.glob("output/2026-05-*/tp-2026-05-*.json")
    )
    if not targets:
        print("No TP JSON files found.", file=sys.stderr)
        return 1
    for path in targets:
        changed, n_actors = _migrate_one(path)
        flag = "wrote" if changed else "unchanged"
        rel = path.relative_to(ROOT)
        print(f"  {flag:9}  {rel}  mentioned_actors.counts.actors={n_actors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
