"""V2 pipeline stages — deterministic stages and the mirror_stage helper.

Run-scoped stages live in `run_stages`; topic-scoped stages will live in
`topic_stages` (TASK-V2-03b). The generic `mirror_stage` helper consumes the
`mirrors_from` schema metadata declared in `src/bus.py` and is reused by the
topic-level mirror stages.
"""

from src.stages.run_stages import (
    MirrorMismatchError,
    RunInitConfig,
    fetch_findings,
    finalize_run,
    init_run,
    make_fetch_findings,
    make_finalize_run,
    make_init_run,
    mirror_stage,
)

__all__ = [
    "MirrorMismatchError",
    "RunInitConfig",
    "fetch_findings",
    "finalize_run",
    "init_run",
    "make_fetch_findings",
    "make_finalize_run",
    "make_init_run",
    "mirror_stage",
]
