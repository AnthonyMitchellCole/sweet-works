"""Centralized, allocation-aware stats tracker.

One :class:`StatsTracker` instance is constructed per play session and
subscribes once to the four relevant event topics. It owns:

* Per-item ring buffers of 1-second buckets for ``produced`` /
  ``consumed`` events. Buckets span :data:`_SEC_WINDOW` seconds
  (default 1 hour) so every realistic UI query window fits inside.
* Per-prefab and per-building-class placement / removal / active
  counts (mirrored so an objective can ask for "three miners of any
  kind" without caring which extractor variant the player chose).
* A small session record sampled once per simulated second with
  belt-tile / building / items-in-world totals and global throughput
  peaks.

All counter updates happen in subscribed handlers (cheap integer
bumps) and one ``update(dt, world_time)`` call per frame that rolls
the ring buffers forward using the same integer-second idiom as the
legacy ``HUD.RateTracker``.

Public query methods compute aggregates (avg / max / min / median /
total) on demand by scanning the relevant window; the window is at
most :data:`_SEC_WINDOW` entries, so a full readout at UI frame rate
is comfortably sub-millisecond.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from ..items.registry import ITEMS

if TYPE_CHECKING:
    from ..buildings.building import Building
    from ..core.events import EventBus
    from ..items.item_type import ItemType
    from ..world.world import World


# -- module constants ------------------------------------------------------

_SEC_WINDOW: int = 3600
"""Seconds of rolling per-second history kept per item (1 hour)."""

RateWindow = Literal[10, 60, 300, 1800, 0]
"""Allowed rate windows in seconds. ``0`` means "session total"."""

_ALL_WINDOWS: tuple[int, ...] = (10, 60, 300, 1800)


# -- public record dataclasses --------------------------------------------


@dataclass
class ItemStat:
    """Authoritative lifetime + rolling counters for one item type."""

    item_id: str
    produced_total: int = 0
    consumed_total: int = 0
    peak_prod_per_min: float = 0.0
    peak_cons_per_min: float = 0.0
    first_produced_at: float | None = None
    first_consumed_at: float | None = None


@dataclass
class BuildingStat:
    """Per-prefab (or per-class) placement counters."""

    key: str
    placed_total: int = 0
    removed_total: int = 0
    active_count: int = 0


@dataclass
class SessionStat:
    """Global totals sampled once per simulated second."""

    session_start_time: float = 0.0
    elapsed_s: float = 0.0
    total_produced: int = 0
    total_consumed: int = 0
    peak_global_prod_per_min: float = 0.0
    peak_global_cons_per_min: float = 0.0
    belt_tile_count: int = 0
    building_count: int = 0
    items_in_world: int = 0


# -- tracker ---------------------------------------------------------------


class StatsTracker:
    """Event-driven counters + rolling ring buffers for the play scene."""

    def __init__(self, events: EventBus, world: World | None = None) -> None:
        self._events = events
        self._world = world

        # -- per-item state -----------------------------------------------
        item_ids = tuple(t.id for t in ITEMS.all())
        self._item_ids: tuple[str, ...] = item_ids
        self._stats: dict[str, ItemStat] = {
            iid: ItemStat(item_id=iid) for iid in item_ids
        }
        # Ring buffers laid out as ``list[int]`` per item for simple
        # allocation-free bumps from the hot handlers.
        self._prod: dict[str, list[int]] = {
            iid: [0] * _SEC_WINDOW for iid in item_ids
        }
        self._cons: dict[str, list[int]] = {
            iid: [0] * _SEC_WINDOW for iid in item_ids
        }
        self._head: int = 0
        self._last_sec: int = -1
        self._elapsed: float = 0.0
        # The most recent completed-second value per item (fast "last 1 s"
        # readout for the HUD tooltip without scanning the ring).
        self._last_prod: dict[str, int] = {iid: 0 for iid in item_ids}
        self._last_cons: dict[str, int] = {iid: 0 for iid in item_ids}

        # -- building state -----------------------------------------------
        self._buildings_by_prefab: dict[str, BuildingStat] = {}
        self._buildings_by_class: dict[str, BuildingStat] = {}

        # -- session state ------------------------------------------------
        self._session = SessionStat()

        # -- subscriptions ------------------------------------------------
        self._off_produced: Callable[[], None] = events.on(
            "item.produced", self._on_produced
        )
        self._off_consumed: Callable[[], None] = events.on(
            "item.consumed", self._on_consumed
        )
        self._off_placed: Callable[[], None] = events.on(
            "building.placed", self._on_building_placed
        )
        self._off_removed: Callable[[], None] = events.on(
            "building.removed", self._on_building_removed
        )

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        """Unsubscribe all handlers. Safe to call multiple times."""
        for off in (
            self._off_produced,
            self._off_consumed,
            self._off_placed,
            self._off_removed,
        ):
            try:
                off()
            except Exception:  # pragma: no cover - defensive
                pass

    # -- event handlers ---------------------------------------------------

    def _on_produced(self, item_type: ItemType) -> None:
        iid = item_type.id
        stat = self._stats.get(iid)
        if stat is None:
            return
        stat.produced_total += 1
        if stat.first_produced_at is None:
            stat.first_produced_at = self._elapsed
        self._prod[iid][self._head] += 1

    def _on_consumed(self, item_type: ItemType) -> None:
        iid = item_type.id
        stat = self._stats.get(iid)
        if stat is None:
            return
        stat.consumed_total += 1
        if stat.first_consumed_at is None:
            stat.first_consumed_at = self._elapsed
        self._cons[iid][self._head] += 1

    def _on_building_placed(self, building: Building) -> None:
        prefab_id = _prefab_id_for(building)
        class_name = getattr(building, "name", "building") or "building"
        self._bump_placed(self._buildings_by_prefab, prefab_id)
        self._bump_placed(self._buildings_by_class, class_name)

    def _on_building_removed(self, building: Building) -> None:
        prefab_id = _prefab_id_for(building)
        class_name = getattr(building, "name", "building") or "building"
        self._bump_removed(self._buildings_by_prefab, prefab_id)
        self._bump_removed(self._buildings_by_class, class_name)

    @staticmethod
    def _bump_placed(bucket: dict[str, BuildingStat], key: str) -> None:
        stat = bucket.get(key)
        if stat is None:
            stat = BuildingStat(key=key)
            bucket[key] = stat
        stat.placed_total += 1
        stat.active_count += 1

    @staticmethod
    def _bump_removed(bucket: dict[str, BuildingStat], key: str) -> None:
        stat = bucket.get(key)
        if stat is None:
            stat = BuildingStat(key=key)
            bucket[key] = stat
        stat.removed_total += 1
        if stat.active_count > 0:
            stat.active_count -= 1

    # -- per-frame update -------------------------------------------------

    def update(self, dt: float, world_time: float) -> None:
        """Advance the per-second ring buffer and refresh session samples."""
        self._elapsed = max(self._elapsed, world_time)
        if self._last_sec < 0:
            self._last_sec = int(world_time)
            self._session.session_start_time = world_time
        current_sec = int(world_time)
        while self._last_sec < current_sec:
            self._close_second()
            self._last_sec += 1
            self._head = (self._head + 1) % _SEC_WINDOW
            for buf in self._prod.values():
                buf[self._head] = 0
            for buf in self._cons.values():
                buf[self._head] = 0
        self._session.elapsed_s = max(0.0, world_time - self._session.session_start_time)

    def _close_second(self) -> None:
        """Snapshot the second we're about to roll off into peaks/totals."""
        head = self._head
        total_prod = 0
        total_cons = 0
        for iid, stat in self._stats.items():
            p = self._prod[iid][head]
            c = self._cons[iid][head]
            self._last_prod[iid] = p
            self._last_cons[iid] = c
            total_prod += p
            total_cons += c
            # Rolling 60-second peak for this item.
            window_p = self._window_sum(self._prod[iid], 60)
            window_c = self._window_sum(self._cons[iid], 60)
            if window_p > stat.peak_prod_per_min:
                stat.peak_prod_per_min = float(window_p)
            if window_c > stat.peak_cons_per_min:
                stat.peak_cons_per_min = float(window_c)
        # Global totals + peaks.
        self._session.total_produced = sum(s.produced_total for s in self._stats.values())
        self._session.total_consumed = sum(s.consumed_total for s in self._stats.values())
        global_p = 0
        global_c = 0
        for iid in self._item_ids:
            global_p += self._window_sum(self._prod[iid], 60)
            global_c += self._window_sum(self._cons[iid], 60)
        if global_p > self._session.peak_global_prod_per_min:
            self._session.peak_global_prod_per_min = float(global_p)
        if global_c > self._session.peak_global_cons_per_min:
            self._session.peak_global_cons_per_min = float(global_c)

        # Sample world-wide counts once per second so UI always has a
        # fresh, O(1) readout without scanning grids on every frame.
        self._sample_world()

    def _sample_world(self) -> None:
        world = self._world
        if world is None:
            return
        net = getattr(world, "belt_network", None)
        if net is not None:
            belt_map = getattr(net, "_belt_by_pos", None)
            if isinstance(belt_map, dict):
                self._session.belt_tile_count = len(belt_map)
            try:
                self._session.items_in_world = int(net.total_items())
            except Exception:  # pragma: no cover - defensive
                self._session.items_in_world = 0
        self._session.building_count = len(getattr(world, "buildings", ()))

    # -- internal helpers -------------------------------------------------

    def _window_sum(self, buf: list[int], window_s: int) -> int:
        w = max(1, min(_SEC_WINDOW, window_s))
        h = self._head
        total = 0
        for i in range(w):
            total += buf[(h - i) % _SEC_WINDOW]
        return total

    def _window_series(self, buf: list[int], window_s: int) -> list[int]:
        """Return ``window_s`` ints oldest->newest."""
        w = max(1, min(_SEC_WINDOW, window_s))
        h = self._head
        out: list[int] = [0] * w
        for i in range(w):
            out[w - 1 - i] = buf[(h - i) % _SEC_WINDOW]
        return out

    # -- public query API -------------------------------------------------

    def item_ids(self) -> tuple[str, ...]:
        return self._item_ids

    def item_stat(self, item_id: str) -> ItemStat:
        return self._stats[item_id]

    def total(
        self, item_id: str, kind: Literal["produced", "consumed"], window_s: int = 0
    ) -> int:
        """Return the total count for an item over a window.

        ``window_s = 0`` means the lifetime total (matches
        :attr:`ItemStat.produced_total` / :attr:`ItemStat.consumed_total`).
        """
        if window_s <= 0:
            stat = self._stats[item_id]
            return stat.produced_total if kind == "produced" else stat.consumed_total
        buf = self._prod[item_id] if kind == "produced" else self._cons[item_id]
        return self._window_sum(buf, window_s)

    def rate_per_min(
        self,
        item_id: str,
        kind: Literal["produced", "consumed"],
        window_s: int,
    ) -> float:
        """Return the rate over the last ``window_s`` seconds, scaled to /min.

        Matches the legacy ``RateTracker.per_minute_*`` semantics: during
        warm-up (when ``elapsed < window_s``) the rate is computed over
        the observed window so numbers read correctly right after a
        scene starts.
        """
        window_s = max(1, min(_SEC_WINDOW, window_s))
        buf = self._prod[item_id] if kind == "produced" else self._cons[item_id]
        total = self._window_sum(buf, window_s)
        effective = min(float(window_s), max(0.25, self._elapsed))
        return (total / effective) * 60.0

    def avg_per_min(
        self,
        item_id: str,
        kind: Literal["produced", "consumed"],
        window_s: int,
    ) -> float:
        """Mean per-minute rate sampled at 1-second granularity."""
        return self.rate_per_min(item_id, kind, window_s)

    def max_per_min(
        self,
        item_id: str,
        kind: Literal["produced", "consumed"],
        window_s: int,
    ) -> float:
        """Largest 1-second sample in the window, scaled to /min."""
        series = self._window_series(
            self._prod[item_id] if kind == "produced" else self._cons[item_id],
            window_s,
        )
        return float(max(series)) * 60.0 if series else 0.0

    def min_per_min(
        self,
        item_id: str,
        kind: Literal["produced", "consumed"],
        window_s: int,
    ) -> float:
        """Smallest non-zero 1-second sample in the window, scaled to /min.

        Returns ``0`` if every bucket is empty so the UI can format the
        cell as a dash without a special case.
        """
        series = self._window_series(
            self._prod[item_id] if kind == "produced" else self._cons[item_id],
            window_s,
        )
        non_zero = [v for v in series if v > 0]
        if not non_zero:
            return 0.0
        return float(min(non_zero)) * 60.0

    def median_per_min(
        self,
        item_id: str,
        kind: Literal["produced", "consumed"],
        window_s: int,
    ) -> float:
        """Median of the per-second samples in the window, scaled to /min."""
        series = self._window_series(
            self._prod[item_id] if kind == "produced" else self._cons[item_id],
            window_s,
        )
        if not series:
            return 0.0
        srt = sorted(series)
        n = len(srt)
        if n % 2 == 1:
            mid = float(srt[n // 2])
        else:
            mid = (srt[n // 2 - 1] + srt[n // 2]) / 2.0
        return mid * 60.0

    def net_series(
        self,
        item_id: str,
        window_s: int = 60,
        smooth: int = 3,
    ) -> list[float]:
        """Per-second ``produced - consumed`` rate (per minute), oldest first.

        ``smooth`` applies a centred moving average so one-tick spikes
        don't dominate the sparkline, mirroring the legacy helper in
        :class:`src.ui.hud.RateTracker`.
        """
        window_s = max(1, min(_SEC_WINDOW, window_s))
        smooth = max(1, int(smooth))
        prod = self._window_series(self._prod[item_id], window_s)
        cons = self._window_series(self._cons[item_id], window_s)
        raw = [float(prod[i] - cons[i]) * 60.0 for i in range(window_s)]
        if smooth <= 1:
            return raw
        half = smooth // 2
        out: list[float] = [0.0] * window_s
        for i in range(window_s):
            lo = max(0, i - half)
            hi = min(window_s, i + half + 1)
            s = 0.0
            for j in range(lo, hi):
                s += raw[j]
            out[i] = s / (hi - lo)
        return out

    # -- building queries -------------------------------------------------

    def building_stats(self) -> dict[str, BuildingStat]:
        """Per-prefab stats keyed by prefab id."""
        return self._buildings_by_prefab

    def building_stats_by_class(self) -> dict[str, BuildingStat]:
        """Per-class stats keyed by building class name (``"miner"``, ...)."""
        return self._buildings_by_class

    def active_count(self, key: str) -> int:
        """Resolve ``key`` against prefab *and* class buckets, returning 0 if unseen."""
        stat = self._buildings_by_prefab.get(key)
        if stat is not None:
            return stat.active_count
        stat = self._buildings_by_class.get(key)
        if stat is not None:
            return stat.active_count
        return 0

    def placed_total(self, key: str) -> int:
        stat = self._buildings_by_prefab.get(key)
        if stat is not None:
            return stat.placed_total
        stat = self._buildings_by_class.get(key)
        if stat is not None:
            return stat.placed_total
        return 0

    # -- session queries --------------------------------------------------

    def session(self) -> SessionStat:
        return self._session

    def all_windows(self) -> tuple[int, ...]:
        return _ALL_WINDOWS


# -- helpers ---------------------------------------------------------------


_PREFAB_BY_SPRITE: dict[str, str] = {}
_PREFAB_NAMES: dict[str, str] = {}


def _prefab_id_for(building: Building) -> str:
    """Resolve a live building back to its :class:`BuildingPrefab` id.

    We cache the sprite_base->prefab_id map from the registry on first
    use so the lookup is O(1) after startup and doesn't introduce an
    import cycle on module load.
    """
    global _PREFAB_BY_SPRITE, _PREFAB_NAMES
    if not _PREFAB_BY_SPRITE:
        from ..buildings.registry import BUILDINGS

        _PREFAB_BY_SPRITE = {p.sprite_base: p.id for p in BUILDINGS.all()}
        _PREFAB_NAMES = {p.id: p.name for p in BUILDINGS.all()}
    sprite_base = getattr(building, "sprite_base", None)
    if sprite_base is not None:
        found = _PREFAB_BY_SPRITE.get(sprite_base)
        if found is not None:
            return found
    return getattr(building, "name", "building") or "building"


def prefab_display_name(prefab_id: str) -> str:
    """Resolve a prefab id to its human-readable registry name."""
    global _PREFAB_NAMES
    if not _PREFAB_NAMES:
        from ..buildings.registry import BUILDINGS

        _PREFAB_NAMES = {p.id: p.name for p in BUILDINGS.all()}
    return _PREFAB_NAMES.get(prefab_id, prefab_id.replace("_", " ").title())


__all__ = [
    "BuildingStat",
    "ItemStat",
    "RateWindow",
    "SessionStat",
    "StatsTracker",
    "prefab_display_name",
]
