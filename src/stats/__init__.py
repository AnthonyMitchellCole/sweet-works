"""Centralized gameplay statistics + objectives/quests system.

The :class:`StatsTracker` owns every production / consumption / building
population counter in the game. It subscribes once to the event bus
(``item.produced``, ``item.consumed``, ``building.placed``,
``building.removed``) and exposes a read-only query API the HUD and
``ObjectivesWindow`` consume -- rolling rates, peaks, averages,
medians, maxima, minima, and sparkline series over configurable time
windows.

:class:`ObjectivesState` is a thin reactive layer on top of the tracker
that evaluates a catalog of :class:`ObjectiveSpec` predicates each
frame and emits ``objective.completed`` the first tick a spec crosses
its goal threshold. The catalog in :mod:`~src.stats.catalog` ships the
base sweet-works progression.
"""

from __future__ import annotations

from .catalog import OBJECTIVES_CATALOG
from .objectives import (
    ObjectiveKind,
    ObjectiveSpec,
    ObjectivesState,
    ObjectiveStatus,
)
from .tracker import (
    BuildingStat,
    ItemStat,
    RateWindow,
    SessionStat,
    StatsTracker,
)

__all__ = [
    "OBJECTIVES_CATALOG",
    "BuildingStat",
    "ItemStat",
    "ObjectiveKind",
    "ObjectiveSpec",
    "ObjectiveStatus",
    "ObjectivesState",
    "RateWindow",
    "SessionStat",
    "StatsTracker",
]
