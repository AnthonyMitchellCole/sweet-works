"""Lightweight perf counters used by the HUD, benchmark, and test gates.

Everything here is hot-path-safe: no allocations after construction, no
numpy deps, and O(1) inserts. Percentiles are computed on demand from a
pre-allocated ring buffer.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import config


class PerfCounter:
    """Ring buffer of the most recent N float samples (seconds or ms)."""

    __slots__ = ("_buf", "_capacity", "_filled", "_i", "name")

    def __init__(self, name: str, capacity: int = config.PERF_SAMPLES) -> None:
        self.name = name
        self._capacity = max(1, capacity)
        self._buf: list[float] = [0.0] * self._capacity
        self._i: int = 0
        self._filled: int = 0

    def add(self, value: float) -> None:
        self._buf[self._i] = value
        self._i = (self._i + 1) % self._capacity
        if self._filled < self._capacity:
            self._filled += 1

    def clear(self) -> None:
        self._i = 0
        self._filled = 0

    def __len__(self) -> int:
        return self._filled

    def samples(self) -> list[float]:
        if self._filled < self._capacity:
            return self._buf[: self._filled]
        # Ordered oldest-first.
        return self._buf[self._i :] + self._buf[: self._i]

    def last(self) -> float:
        if self._filled == 0:
            return 0.0
        idx = (self._i - 1) % self._capacity
        return self._buf[idx]

    def mean(self) -> float:
        if self._filled == 0:
            return 0.0
        total = 0.0
        for i in range(self._filled):
            total += self._buf[i]
        return total / self._filled

    def max(self) -> float:
        if self._filled == 0:
            return 0.0
        m = self._buf[0]
        for i in range(1, self._filled):
            v = self._buf[i]
            if v > m:
                m = v
        return m

    def min(self) -> float:
        if self._filled == 0:
            return 0.0
        m = self._buf[0]
        for i in range(1, self._filled):
            v = self._buf[i]
            if v < m:
                m = v
        return m

    def percentile(self, p: float) -> float:
        """p in [0, 1]. Uses a one-off sorted copy; keep off hot paths."""
        if self._filled == 0:
            return 0.0
        p = max(0.0, min(1.0, p))
        snap = sorted(self.samples())
        k = int(round(p * (len(snap) - 1)))
        return snap[k]


@dataclass
class PerfSnapshot:
    """Immutable snapshot of the current perf state, safe to pass to the HUD."""

    fps: float = 0.0
    frame_ms_p95: float = 0.0
    frame_ms_mean: float = 0.0
    update_ms_p95: float = 0.0
    tick_ms_p95: float = 0.0
    tick_ms_max: float = 0.0
    tick_ms_mean: float = 0.0
    render_ms_p95: float = 0.0
    render_ms_mean: float = 0.0
    item_count: int = 0
    chain_count: int = 0
    visible_items: int = 0
    visible_chains: int = 0

    samples_frame: list[float] = field(default_factory=list)
    samples_tick: list[float] = field(default_factory=list)
    samples_render: list[float] = field(default_factory=list)


class Perf:
    """A small bundle of PerfCounters plus simple scope timers."""

    def __init__(self) -> None:
        self.frame = PerfCounter("frame_ms")
        self.update = PerfCounter("update_ms")
        self.tick = PerfCounter("tick_ms")
        self.render = PerfCounter("render_ms")

        self.item_count: int = 0
        self.chain_count: int = 0
        self.visible_items: int = 0
        self.visible_chains: int = 0

        self._scope_start: float = 0.0

    def reset(self) -> None:
        self.frame.clear()
        self.update.clear()
        self.tick.clear()
        self.render.clear()

    @contextmanager
    def scope(self, counter: PerfCounter) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            counter.add((time.perf_counter() - start) * 1000.0)

    def snapshot(self, fps: float = 0.0) -> PerfSnapshot:
        return PerfSnapshot(
            fps=fps,
            frame_ms_p95=self.frame.percentile(0.95),
            frame_ms_mean=self.frame.mean(),
            update_ms_p95=self.update.percentile(0.95),
            tick_ms_p95=self.tick.percentile(0.95),
            tick_ms_max=self.tick.max(),
            tick_ms_mean=self.tick.mean(),
            render_ms_p95=self.render.percentile(0.95),
            render_ms_mean=self.render.mean(),
            item_count=self.item_count,
            chain_count=self.chain_count,
            visible_items=self.visible_items,
            visible_chains=self.visible_chains,
            samples_frame=self.frame.samples(),
            samples_tick=self.tick.samples(),
            samples_render=self.render.samples(),
        )


# A single process-wide Perf bundle. Scenes are free to create their own.
PERF = Perf()


@contextmanager
def timed(counter: PerfCounter) -> Iterator[None]:
    """Stand-alone context manager equivalent to Perf.scope."""
    start = time.perf_counter()
    try:
        yield
    finally:
        counter.add((time.perf_counter() - start) * 1000.0)
