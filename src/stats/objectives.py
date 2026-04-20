"""Objectives / quests layer riding on top of :class:`StatsTracker`.

Objectives are pure data (:class:`ObjectiveSpec`) evaluated each frame
by :class:`ObjectivesState` against the tracker's query API. The first
tick a spec reaches its target, ``objective.completed`` is emitted on
the :class:`EventBus` with the spec and the world time at which the
milestone happened. The event is one-shot; completed specs drop into a
``completed`` set and never re-fire.

Supported predicate kinds:

* :attr:`ObjectiveKind.PRODUCE_TOTAL`
* :attr:`ObjectiveKind.CONSUME_TOTAL`
* :attr:`ObjectiveKind.SUSTAIN_RATE` -- the item's rolling rate over
  ``window_s`` must stay at or above ``rate_per_min`` for ``hold_s``
  continuous seconds. The hold timer resets whenever the rate falls
  below target so brief spikes don't tick progress.
* :attr:`ObjectiveKind.PLACE_BUILDING_COUNT` -- ``active_count`` for
  a prefab id *or* a building class name (e.g. ``"miner"``) reaches
  ``amount``.
* :attr:`ObjectiveKind.BELT_TILES` -- session belt tile count reaches
  ``amount`` (sampled once per second by the tracker).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.events import EventBus
    from .tracker import StatsTracker


class ObjectiveKind(Enum):
    PRODUCE_TOTAL = auto()
    CONSUME_TOTAL = auto()
    SUSTAIN_RATE = auto()
    PLACE_BUILDING_COUNT = auto()
    BELT_TILES = auto()


@dataclass(frozen=True)
class ObjectiveSpec:
    """Immutable description of one objective.

    ``tier`` groups specs for ordered presentation (1 = earliest).
    ``prereq_ids`` keeps the spec locked in the UI until every listed id
    is completed; state only begins evaluating when the prereqs are
    met so a player can't "accidentally" complete a late-game goal
    before the setup objectives.
    """

    id: str
    title: str
    description: str
    tier: int
    kind: ObjectiveKind
    item_id: str | None = None
    building_id: str | None = None
    amount: int = 0
    rate_per_min: float = 0.0
    window_s: int = 10
    hold_s: float = 0.0
    icon_item_id: str | None = None
    icon_building_id: str | None = None
    prereq_ids: tuple[str, ...] = ()


@dataclass
class ObjectiveStatus:
    """Snapshot view consumed by the UI each frame."""

    spec: ObjectiveSpec
    progress: float
    target: float
    progress_frac: float
    completed: bool
    locked: bool
    hold_frac: float = 0.0


class ObjectivesState:
    """Tracks objective progress and emits ``objective.completed`` events."""

    def __init__(
        self,
        events: EventBus,
        stats: StatsTracker,
        catalog: tuple[ObjectiveSpec, ...] | None = None,
    ) -> None:
        self._events = events
        self._stats = stats

        if catalog is None:
            from .catalog import OBJECTIVES_CATALOG

            catalog = OBJECTIVES_CATALOG

        self._catalog: tuple[ObjectiveSpec, ...] = catalog
        self._by_id: dict[str, ObjectiveSpec] = {s.id: s for s in catalog}
        self.completed: set[str] = set()
        self.completed_at: dict[str, float] = {}
        self._progress: dict[str, float] = {s.id: 0.0 for s in catalog}
        self._target: dict[str, float] = {s.id: float(_spec_target(s)) for s in catalog}
        self._sustain_hold: dict[str, float] = {s.id: 0.0 for s in catalog}
        self._last_time: float = 0.0

        # Completion listeners (independent of EventBus so tests that
        # skip events still get a deterministic notification hook).
        self._listeners: list[Callable[[ObjectiveSpec, float], None]] = []

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        self._listeners.clear()

    def catalog(self) -> tuple[ObjectiveSpec, ...]:
        return self._catalog

    def on_completed(
        self, cb: Callable[[ObjectiveSpec, float], None]
    ) -> Callable[[], None]:
        self._listeners.append(cb)

        def off() -> None:
            try:
                self._listeners.remove(cb)
            except ValueError:
                pass

        return off

    # -- per-frame --------------------------------------------------------

    def update(self, dt: float, world_time: float) -> None:
        self._last_time = world_time
        for spec in self._catalog:
            if spec.id in self.completed:
                continue
            if self._is_locked(spec):
                # Locked specs don't accumulate progress; once prereqs
                # complete the first tick re-entering the loop will pick
                # up the current stat value.
                continue
            progress, target, completed, hold_progressed = self._evaluate(spec, dt)
            self._progress[spec.id] = progress
            self._target[spec.id] = target
            if completed:
                self.completed.add(spec.id)
                self.completed_at[spec.id] = world_time
                self._events.emit(
                    "objective.completed", spec=spec, at=world_time
                )
                for cb in list(self._listeners):
                    try:
                        cb(spec, world_time)
                    except Exception:  # pragma: no cover - defensive
                        pass

    def reset(self) -> None:
        self.completed.clear()
        self.completed_at.clear()
        for sid in self._progress:
            self._progress[sid] = 0.0
            self._sustain_hold[sid] = 0.0

    # -- queries ----------------------------------------------------------

    def status_for(self, spec_id: str) -> ObjectiveStatus:
        spec = self._by_id[spec_id]
        target = self._target.get(spec_id, float(_spec_target(spec)))
        progress = self._progress.get(spec_id, 0.0)
        if spec_id in self.completed:
            progress = target
        completed = spec_id in self.completed
        locked = (not completed) and self._is_locked(spec)
        hold = 0.0
        if spec.kind is ObjectiveKind.SUSTAIN_RATE and spec.hold_s > 0:
            hold = min(1.0, self._sustain_hold.get(spec_id, 0.0) / spec.hold_s)
        if target <= 0:
            frac = 1.0 if completed else 0.0
        else:
            frac = max(0.0, min(1.0, progress / target))
        return ObjectiveStatus(
            spec=spec,
            progress=progress,
            target=target,
            progress_frac=frac,
            completed=completed,
            locked=locked,
            hold_frac=hold,
        )

    def statuses(self) -> list[ObjectiveStatus]:
        return [self.status_for(s.id) for s in self._catalog]

    # -- internals --------------------------------------------------------

    def _is_locked(self, spec: ObjectiveSpec) -> bool:
        return any(pid not in self.completed for pid in spec.prereq_ids)

    def _evaluate(
        self, spec: ObjectiveSpec, dt: float
    ) -> tuple[float, float, bool, bool]:
        target = float(_spec_target(spec))
        stats = self._stats
        if spec.kind is ObjectiveKind.PRODUCE_TOTAL:
            assert spec.item_id is not None
            progress = float(stats.total(spec.item_id, "produced", 0))
            completed = progress >= target
            return progress, target, completed, False
        if spec.kind is ObjectiveKind.CONSUME_TOTAL:
            assert spec.item_id is not None
            progress = float(stats.total(spec.item_id, "consumed", 0))
            completed = progress >= target
            return progress, target, completed, False
        if spec.kind is ObjectiveKind.SUSTAIN_RATE:
            assert spec.item_id is not None
            rate = stats.rate_per_min(spec.item_id, "produced", spec.window_s)
            hold = self._sustain_hold.get(spec.id, 0.0)
            if rate >= spec.rate_per_min:
                hold = min(spec.hold_s, hold + max(0.0, dt))
                hold_progressed = True
            else:
                hold = 0.0
                hold_progressed = False
            self._sustain_hold[spec.id] = hold
            # Progress = hold seconds. Target = required hold seconds.
            progress = hold
            completed = hold >= spec.hold_s and spec.hold_s > 0
            return progress, float(spec.hold_s), completed, hold_progressed
        if spec.kind is ObjectiveKind.PLACE_BUILDING_COUNT:
            key = spec.building_id or ""
            progress = float(stats.active_count(key))
            completed = progress >= target
            return progress, target, completed, False
        if spec.kind is ObjectiveKind.BELT_TILES:
            progress = float(stats.session().belt_tile_count)
            completed = progress >= target
            return progress, target, completed, False
        return 0.0, target, False, False


def _spec_target(spec: ObjectiveSpec) -> float:
    if spec.kind is ObjectiveKind.SUSTAIN_RATE:
        return float(spec.hold_s)
    return float(spec.amount)


__all__ = [
    "ObjectiveKind",
    "ObjectiveSpec",
    "ObjectiveStatus",
    "ObjectivesState",
]
