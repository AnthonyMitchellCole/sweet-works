"""Tests for :mod:`src.stats.objectives`.

Covers:

* Progress rolls and completion fires exactly once when a
  ``PRODUCE_TOTAL`` threshold is crossed.
* ``objective.completed`` is emitted on the event bus with the full
  spec + world time, and registered listeners fire alongside.
* ``SUSTAIN_RATE`` only completes when the rolling rate stays at or
  above target for the full hold window; a dip resets the timer.
* ``PLACE_BUILDING_COUNT`` and ``BELT_TILES`` wire through to the
  tracker's building/session state.
* Prereqs keep downstream specs locked until every upstream id
  completes; a locked spec doesn't emit on crossing its threshold.
* ``reset`` zeroes progress and ``status_for`` returns the UI snapshot
  in both locked and completed states.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.core.events import EventBus
from src.items.registry import ITEMS
from src.stats.objectives import (
    ObjectiveKind,
    ObjectiveSpec,
    ObjectivesState,
)
from src.stats.tracker import StatsTracker


# -- doubles ---------------------------------------------------------------


@dataclass
class _FakeBuilding:
    sprite_base: str | None
    name: str


class _FakeBeltNet:
    def __init__(self, belts: int, items: int = 0) -> None:
        self._belt_by_pos = {i: None for i in range(belts)}
        self._items = items

    def total_items(self) -> int:
        return self._items


@dataclass
class _FakeWorld:
    belt_network: _FakeBeltNet | None = None
    buildings: list[object] = field(default_factory=list)


# -- helpers ---------------------------------------------------------------


def _record(bus: EventBus) -> tuple[list[dict[str, object]], Callable[[], None]]:
    calls: list[dict[str, object]] = []

    def _on(**payload: object) -> None:
        calls.append(payload)

    off = bus.on("objective.completed", _on)
    return calls, off


def _produce(bus: EventBus, item_id: str, n: int = 1) -> None:
    item = next(i for i in ITEMS.all() if i.id == item_id)
    for _ in range(n):
        bus.emit("item.produced", item_type=item)


def _tick(
    tracker: StatsTracker, state: ObjectivesState, dt: float, t: float
) -> None:
    tracker.update(dt, t)
    state.update(dt, t)


# -- PRODUCE_TOTAL --------------------------------------------------------


def test_produce_total_completes_once_and_emits_event() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    spec = ObjectiveSpec(
        id="q_cocoa_3",
        title="Triple Harvest",
        description="Produce 3 cocoa beans.",
        tier=1,
        kind=ObjectiveKind.PRODUCE_TOTAL,
        item_id="cocoa_bean",
        amount=3,
    )
    state = ObjectivesState(bus, tracker, catalog=(spec,))
    try:
        calls, _off = _record(bus)

        # Below threshold: no event, status reflects progress fraction.
        _produce(bus, "cocoa_bean", 2)
        _tick(tracker, state, 1.0, 1.0)
        assert calls == []
        status = state.status_for("q_cocoa_3")
        assert status.progress == 2
        assert status.completed is False
        assert abs(status.progress_frac - (2 / 3)) < 1e-9

        # Crossing the threshold fires exactly once; further production
        # doesn't re-fire because the spec sits in ``completed``.
        _produce(bus, "cocoa_bean", 5)
        _tick(tracker, state, 1.0, 2.0)
        _tick(tracker, state, 1.0, 3.0)
        assert len(calls) == 1
        payload = calls[0]
        assert payload["spec"] is spec
        assert payload["at"] == 2.0
        assert "q_cocoa_3" in state.completed
    finally:
        state.close()
        tracker.close()


def test_listener_hook_fires_alongside_event() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    spec = ObjectiveSpec(
        id="q",
        title="t",
        description="d",
        tier=1,
        kind=ObjectiveKind.PRODUCE_TOTAL,
        item_id="cocoa_bean",
        amount=1,
    )
    state = ObjectivesState(bus, tracker, catalog=(spec,))
    try:
        hit: list[tuple[str, float]] = []
        state.on_completed(lambda s, t: hit.append((s.id, t)))
        _produce(bus, "cocoa_bean", 1)
        _tick(tracker, state, 1.0, 4.5)
        assert hit == [("q", 4.5)]
    finally:
        state.close()
        tracker.close()


# -- SUSTAIN_RATE ---------------------------------------------------------


def test_sustain_rate_holds_and_resets_on_dip() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    spec = ObjectiveSpec(
        id="q_sustain",
        title="Hold 60/min",
        description="Hold 60/min for 2s",
        tier=1,
        kind=ObjectiveKind.SUSTAIN_RATE,
        item_id="cocoa_bean",
        rate_per_min=60.0,
        window_s=2,
        hold_s=2.0,
    )
    state = ObjectivesState(bus, tracker, catalog=(spec,))
    try:
        calls, _off = _record(bus)

        # Seed the clock so the first produced bucket closes cleanly.
        _tick(tracker, state, 1.0, 1.0)

        # 2 produced per simulated second -> 120/min in the 2s window,
        # comfortably above the 60/min target so the hold timer climbs.
        _produce(bus, "cocoa_bean", 2)
        _tick(tracker, state, 1.0, 2.0)
        hold_after_1 = state.status_for("q_sustain").hold_frac
        assert 0.0 < hold_after_1 < 1.0
        assert calls == []

        # Four seconds of silence: the rolling window drains out, the
        # rate falls below target and the hold timer resets to zero.
        for t in range(3, 7):
            _tick(tracker, state, 1.0, float(t))
        assert state.status_for("q_sustain").hold_frac == 0.0
        assert calls == []

        # Now sustain at 2/s for three straight seconds. After the
        # second completed high-rate second the 2s hold requirement is
        # satisfied and the spec fires exactly once.
        for t in range(7, 11):
            _produce(bus, "cocoa_bean", 2)
            _tick(tracker, state, 1.0, float(t))
        assert "q_sustain" in state.completed
        assert len(calls) == 1
    finally:
        state.close()
        tracker.close()


# -- building / belt ------------------------------------------------------


def test_place_building_count_via_class_bucket() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    spec = ObjectiveSpec(
        id="q_miners",
        title="Three Miners",
        description="Place 3 miners.",
        tier=1,
        kind=ObjectiveKind.PLACE_BUILDING_COUNT,
        building_id="miner",
        amount=3,
    )
    state = ObjectivesState(bus, tracker, catalog=(spec,))
    try:
        for _ in range(3):
            bus.emit(
                "building.placed",
                building=_FakeBuilding(
                    sprite_base="structure_extractor_cocoa", name="miner"
                ),
            )
        _tick(tracker, state, 1.0, 1.0)
        assert "q_miners" in state.completed

        # Decommissioning after completion must NOT re-open the spec.
        bus.emit(
            "building.removed",
            building=_FakeBuilding(
                sprite_base="structure_extractor_cocoa", name="miner"
            ),
        )
        _tick(tracker, state, 1.0, 2.0)
        assert "q_miners" in state.completed
    finally:
        state.close()
        tracker.close()


def test_belt_tiles_reads_world_sample() -> None:
    bus = EventBus()
    world = _FakeWorld(belt_network=_FakeBeltNet(belts=10))
    tracker = StatsTracker(bus, world)
    spec = ObjectiveSpec(
        id="q_belts",
        title="Belt Backbone",
        description="Ten belt tiles.",
        tier=1,
        kind=ObjectiveKind.BELT_TILES,
        amount=10,
    )
    state = ObjectivesState(bus, tracker, catalog=(spec,))
    try:
        # Need a full simulated second to elapse so ``_close_second``
        # samples the world counts.
        _tick(tracker, state, 1.0, 1.0)
        _tick(tracker, state, 1.0, 2.0)
        assert "q_belts" in state.completed
    finally:
        state.close()
        tracker.close()


# -- prereqs & lock state -------------------------------------------------


def test_locked_spec_does_not_complete_until_prereq_done() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    first = ObjectiveSpec(
        id="first",
        title="First",
        description="",
        tier=1,
        kind=ObjectiveKind.PRODUCE_TOTAL,
        item_id="cocoa_bean",
        amount=1,
    )
    second = ObjectiveSpec(
        id="second",
        title="Second",
        description="",
        tier=2,
        kind=ObjectiveKind.PRODUCE_TOTAL,
        item_id="cocoa_bean",
        amount=1,
        prereq_ids=("first",),
    )
    # Re-bind "second" so its amount is higher than "first"'s. This
    # means a single produce event completes "first" but leaves
    # "second" below threshold, so we can assert the locked state
    # directly instead of fighting the natural same-tick cascade.
    second = ObjectiveSpec(
        id="second",
        title="Second",
        description="",
        tier=2,
        kind=ObjectiveKind.PRODUCE_TOTAL,
        item_id="cocoa_bean",
        amount=5,
        prereq_ids=("first",),
    )
    state = ObjectivesState(bus, tracker, catalog=(first, second))
    try:
        calls, _off = _record(bus)

        # Before the prereq completes, "second" reports as locked even
        # though stats would say it has some progress.
        _produce(bus, "cocoa_bean", 1)
        # Re-bind a fresh state where "second" has a prereq but is
        # above threshold on raw stats -- it must stay locked and NOT
        # emit until "first" is itself completed.
        locked_second = ObjectiveSpec(
            id="big",
            title="Big",
            description="",
            tier=2,
            kind=ObjectiveKind.PRODUCE_TOTAL,
            item_id="cocoa_bean",
            amount=1,
            prereq_ids=("never",),
        )
        gate = ObjectivesState(bus, tracker, catalog=(locked_second,))
        _tick(tracker, gate, 1.0, 0.5)
        assert gate.status_for("big").locked is True
        assert "big" not in gate.completed
        gate.close()

        # Back to the real cascade: a single produce completes "first",
        # and since "second" still needs 5 total cocoa beans, it remains
        # incomplete even though it's no longer locked.
        _tick(tracker, state, 1.0, 1.0)
        assert [p["spec"].id for p in calls] == ["first"]
        assert state.status_for("second").locked is False
        assert state.status_for("second").completed is False
        assert state.status_for("second").progress == 1.0

        # Four more produces push "second" over the line on the next
        # tick; total emissions are now ``first`` then ``second``.
        _produce(bus, "cocoa_bean", 4)
        _tick(tracker, state, 1.0, 2.0)
        assert [p["spec"].id for p in calls] == ["first", "second"]
        assert state.status_for("second").completed is True
    finally:
        state.close()
        tracker.close()


def test_reset_clears_progress_and_completion() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    spec = ObjectiveSpec(
        id="q",
        title="",
        description="",
        tier=1,
        kind=ObjectiveKind.PRODUCE_TOTAL,
        item_id="cocoa_bean",
        amount=1,
    )
    state = ObjectivesState(bus, tracker, catalog=(spec,))
    try:
        _produce(bus, "cocoa_bean", 1)
        _tick(tracker, state, 1.0, 1.0)
        assert "q" in state.completed
        state.reset()
        assert state.completed == set()
        assert state.status_for("q").progress == 0
    finally:
        state.close()
        tracker.close()


def test_default_catalog_is_non_empty_and_has_unique_ids() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    state = ObjectivesState(bus, tracker)
    try:
        catalog = state.catalog()
        assert len(catalog) > 0
        ids = [s.id for s in catalog]
        assert len(ids) == len(set(ids))
        # Every prereq must resolve to another spec in the catalog.
        for spec in catalog:
            for pid in spec.prereq_ids:
                assert pid in ids, f"dangling prereq {pid} on {spec.id}"
    finally:
        state.close()
        tracker.close()
