"""Suite-wide fixtures."""

from __future__ import annotations

import os

import pytest

_REJECTED_ENV = "IW_REJECTED_RESPONSES_DIR"


@pytest.fixture(autouse=True)
def _rejected_responses_to_tmp(tmp_path):
    """Agent persists rejected API responses (TASK-SILENT-TOPIC-DEATH-FIX O5)
    under scratch/rejected-responses/ by default. Tests that drive the
    malformed-response paths must never write into the working tree.

    Sets/restores the variable by hand rather than through ``monkeypatch``:
    an autouse fixture that requests ``monkeypatch`` moves its teardown after
    every module fixture, and test_propagate_outlet_metadata's cache-reset
    fixture relies on its monkeypatches being undone first."""
    previous = os.environ.get(_REJECTED_ENV)
    os.environ[_REJECTED_ENV] = str(tmp_path / "rejected-responses")
    yield
    if previous is None:
        os.environ.pop(_REJECTED_ENV, None)
    else:
        os.environ[_REJECTED_ENV] = previous
