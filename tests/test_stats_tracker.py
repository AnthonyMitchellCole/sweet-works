"""Tests for :mod:`src.stats.tracker`.

Covers the centralized stats tracker's contract:

* Event subscriptions bump lifetime totals on ``item.produced`` /
  ``item.consumed``.
* Per-second ring buffers roll forward on ``update`` and drive the
  rolling ``total`` / ``rate_per_min`` / ``max_per_min`` / ``min_per_min``
  / ``median_per_min`` / ``net_series`` queries.
* ``building.placed`` / ``building.removed`` feed both per-prefab *and*
  per-class buckets and keep ``active_count`` non-negative.
* Session sampling captures belt-tile + building + items-in-world counts
  from the attached ``World`` once per simulated second.
* ``close()`` unsubscribes so subsequent events are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.events import EventBus
from src.items.registry import ITEMS
from src.stats.tracker import StatsTracker, prefab_display_name


# -- test doubles ----------------------------------------------------------


@dataclass
class _FakeBuilding:
    """Minimal stand-in that supports both sprite- and name-keyed lookups."""

    sprite_base: str | None
    name: str


class _FakeBeltNet:
    def __init__(self, belts: int, items: int) -> None:
        self._belt_by_pos = {i: None for i in range(belts)}
        self._items = items

    def total_items(self) -> int:
        return self._items


@dataclass
class _FakeWorld:
    """World stand-in used for session sampling tests."""

    belt_network: _FakeBeltNet | None = None
    buildings: list[object] = field(default_factory=list)


# -- helpers ---------------------------------------------------------------


def _produce(bus: EventBus, item_id: str, n: int = 1) -> None:
    item = next(i for i in ITEMS.all() if i.id == item_id)
    for _ in range(n):
        bus.emit("item.produced", item_type=item)


def _consume(bus: EventBus, item_id: str, n: int = 1) -> None:
    item = next(i for i in ITEMS.all() if i.id == item_id)
    for _ in range(n):
        bus.emit("item.consumed", item_type=item)


def _advance(tracker: StatsTracker, *, seconds: int, start: float = 0.0) -> float:
    """Step the tracker by whole seconds and return the final world time."""
    t = start
    for _ in range(seconds):
        t += 1.0
        tracker.update(1.0, t)
    return t


# -- lifetime totals & rates ----------------------------------------------


def test_produce_bumps_lifetime_totals() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    try:
        _produce(bus, "cocoa_bean", 5)
        _consume(bus, "cocoa_bean", 2)
        assert tracker.total("cocoa_bean", "produced") == 5
        assert tracker.total("cocoa_bean", "consumed") == 2
        # Untouched items stay at zero without any allocations.
        assert tracker.total("chocolate", "produced") == 0
    finally:
        tracker.close()


def test_rate_per_min_uses_warmup_window_first() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    try:
        # Three produced events before the first update -> still in
        # warm-up, so the /min rate is scaled over the observed window.
        _produce(bus, "cocoa_bean", 3)
        tracker.update(0.5, 0.5)
        rate = tracker.rate_per_min("cocoa_bean", "produced", 60)
        # With ~0.5s observed, 3 events extrapolate to ~360/min.
        assert rate > 100.0
    finally:
        tracker.close()


def test_window_total_rolls_off_after_window() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    try:
        _produce(bus, "cocoa_bean", 4)
        tracker.update(1.0, 1.0)
        assert tracker.total("cocoa_bean", "produced", window_s=10) == 4
        # Step 11 simulated seconds of silence; the 4 events fall off
        # the 10s rolling window but stay in the lifetime total.
        _advance(tracker, seconds=11, start=1.0)
        assert tracker.total("cocoa_bean", "produced", window_s=10) == 0
        assert tracker.total("cocoa_bean", "produced") == 4
    finally:
        tracker.close()


def test_max_min_median_over_window() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    try:
        # Prime the clock so later buckets line up cleanly: the first
        # ``update`` that arrives with a positive world time just latches
        # ``_last_sec`` without closing any buckets.
        tracker.update(1.0, 1.0)
        # Now a real 3-sample history: 1, 3, 5 events in successive
        # simulated seconds, each closed off by an explicit update.
        _produce(bus, "cocoa_bean", 1)
        tracker.update(1.0, 2.0)
        _produce(bus, "cocoa_bean", 3)
        tracker.update(1.0, 3.0)
        _produce(bus, "cocoa_bean", 5)
        tracker.update(1.0, 4.0)
        assert tracker.max_per_min("cocoa_bean", "produced", 10) == 5 * 60
        assert tracker.min_per_min("cocoa_bean", "produced", 10) == 1 * 60
        # Window wide enough (10s) to be dominated by empty buckets, so
        # the median is zero -- i.e. the factory is idle "on average"
        # while still having real production during three busy seconds.
        assert tracker.median_per_min("cocoa_bean", "produced", 10) == 0.0
        # Narrow the window down to the three populated buckets: median
        # is then the middle sample (3/s -> 180/min).
        assert tracker.median_per_min("cocoa_bean", "produced", 3) == 3 * 60
    finally:
        tracker.close()


def test_net_series_returns_window_sized_list() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    try:
        # Prime the clock, then push a 2P/1C burst and close the bucket.
        tracker.update(1.0, 1.0)
        _produce(bus, "cocoa_bean", 2)
        _consume(bus, "cocoa_bean", 1)
        tracker.update(1.0, 2.0)
        series = tracker.net_series("cocoa_bean", window_s=5, smooth=1)
        assert len(series) == 5
        # The only populated bucket sits just behind the current
        # (empty) head second, so index -2 holds the closed sample.
        assert series[-2] == (2 - 1) * 60.0
        assert series[0] == 0.0
    finally:
        tracker.close()


# -- building tracking ----------------------------------------------------


def test_building_place_and_remove_updates_prefab_and_class() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    try:
        # Two extractor miners. ``sprite_base`` drives prefab resolution,
        # ``name`` drives class resolution. The sprite_base mirrors
        # the live BUILDINGS registry so the tracker can map back to
        # the prefab id "extractor_cocoa".
        m1 = _FakeBuilding(sprite_base="structure_extractor_cocoa", name="miner")
        m2 = _FakeBuilding(sprite_base="structure_extractor_cocoa", name="miner")
        bus.emit("building.placed", building=m1)
        bus.emit("building.placed", building=m2)

        assert tracker.active_count("extractor_cocoa") == 2
        assert tracker.placed_total("extractor_cocoa") == 2
        # Class bucket mirrors the aggregate for "any miner" queries.
        assert tracker.active_count("miner") == 2
        assert tracker.placed_total("miner") == 2

        bus.emit("building.removed", building=m1)
        assert tracker.active_count("extractor_cocoa") == 1
        assert tracker.active_count("miner") == 1
        # Removed_total climbs even when active is decremented.
        assert tracker.building_stats()["extractor_cocoa"].removed_total == 1
    finally:
        tracker.close()


def test_active_count_does_not_go_negative_on_unknown_remove() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    try:
        ghost = _FakeBuilding(sprite_base="structure_extractor_cocoa", name="miner")
        bus.emit("building.removed", building=ghost)
        assert tracker.active_count("extractor_cocoa") == 0
        assert tracker.active_count("miner") == 0
    finally:
        tracker.close()


# -- session sampling -----------------------------------------------------


def test_session_samples_belts_and_buildings_each_second() -> None:
    bus = EventBus()
    world = _FakeWorld(
        belt_network=_FakeBeltNet(belts=7, items=42),
        buildings=[object(), object(), object()],
    )
    tracker = StatsTracker(bus, world)
    try:
        # A full simulated second must elapse for ``_close_second`` to run.
        _advance(tracker, seconds=2)
        session = tracker.session()
        assert session.belt_tile_count == 7
        assert session.items_in_world == 42
        assert session.building_count == 3
        assert session.elapsed_s >= 1.0
    finally:
        tracker.close()


def test_global_produced_total_tracks_sum_across_items() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    try:
        _produce(bus, "cocoa_bean", 3)
        _produce(bus, "chocolate", 2)
        _advance(tracker, seconds=2)
        session = tracker.session()
        assert session.total_produced == 5
    finally:
        tracker.close()


# -- lifecycle ------------------------------------------------------------


def test_close_unsubscribes_from_bus() -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    tracker.close()
    # Further events must be ignored; totals stay at zero.
    _produce(bus, "cocoa_bean", 4)
    assert tracker.total("cocoa_bean", "produced") == 0


def test_prefab_display_name_resolves_known_and_falls_back() -> None:
    # Known prefab id comes from the live registry.
    known = prefab_display_name("extractor_cocoa")
    assert isinstance(known, str) and known
    # Unknown id falls back to a title-cased version of itself.
    assert prefab_display_name("totally_fake_prefab") == "Totally Fake Prefab"
