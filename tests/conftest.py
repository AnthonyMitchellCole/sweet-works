"""Pytest configuration: ensure headless SDL and repo root on ``sys.path``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _reset_perf() -> None:
    """Reset the global perf counters between tests to keep snapshots clean."""
    from src.core.perf import PERF

    PERF.reset()
    yield
    PERF.reset()
