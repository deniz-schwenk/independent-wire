"""V2 pipeline runner — stage-list-driven orchestration.

Entry point: :class:`src.runner.runner.PipelineRunner`. Stage lists are
built by :func:`src.runner.stage_lists.build_production_stages` and
:func:`src.runner.stage_lists.build_hydrated_stages`. Snapshot helpers
live in :mod:`src.runner.state`.
"""

from src.runner.runner import (
    FinalizeRunStage,
    PipelineRunner,
    RenderStage,
)
from src.runner.stage_lists import (
    build_hydrated_stages,
    build_production_stages,
)

__all__ = [
    "FinalizeRunStage",
    "PipelineRunner",
    "RenderStage",
    "build_hydrated_stages",
    "build_production_stages",
]
