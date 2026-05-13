"""Reproducible sampler for the V1-2026-05-11 Iran-cluster manual-label
brief (TASK-COHERENCE-MANUAL-LABELS-V1).

Loads the V1 CuratorStage state, finds the largest cluster (Iran), seeds
the standard library RNG with ``42``, and emits 50 finding IDs in
``random.sample`` order. The seed and ordering are load-bearing — they
ensure the CSV labels can be matched back to the same 50 findings
forever.

Usage:

    python scripts/sample_iran_findings.py            # print IDs, one per line
    python scripts/sample_iran_findings.py --json     # print as JSON array
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


DEFAULT_STATE = (
    "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/"
    "run_bus.CuratorStage.json"
)
SEED = 42
SAMPLE_SIZE = 50


def sample_iran_finding_ids(state_path: Path) -> list[str]:
    """Deterministic sample of 50 finding IDs from the V1 Iran cluster.

    The Iran cluster is the largest cluster by ``source_count`` in
    ``curator_topics_unsliced``. Sampling is ``random.sample`` with
    ``random.seed(42)`` against the cluster's ``source_ids`` list.
    """
    state = json.loads(state_path.read_text(encoding="utf-8"))
    topics = state.get("curator_topics_unsliced") or []
    if not topics:
        raise SystemExit("no curator_topics_unsliced in state file")
    iran = max(topics, key=lambda t: len(t.get("source_ids") or []))
    source_ids = list(iran.get("source_ids") or [])
    if len(source_ids) < SAMPLE_SIZE:
        raise SystemExit(
            f"Iran cluster has only {len(source_ids)} findings; "
            f"cannot sample {SAMPLE_SIZE}"
        )
    rng = random.Random(SEED)
    return rng.sample(source_ids, SAMPLE_SIZE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--json", action="store_true", help="print as JSON array")
    args = parser.parse_args()

    ids = sample_iran_finding_ids(Path(args.state))
    if args.json:
        print(json.dumps(ids))
    else:
        for sid in ids:
            print(sid)


if __name__ == "__main__":
    main()
