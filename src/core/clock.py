"""Fixed-timestep clock with render interpolation alpha."""

from __future__ import annotations

import pygame

from . import config


class Clock:
    def __init__(self, tick_hz: int = config.TICK_HZ, fps: int = config.FPS) -> None:
        self._pg = pygame.time.Clock()
        self._fps_cap = max(0, fps)
        self._tick_dt = 1.0 / tick_hz
        self._accumulator: float = 0.0
        self.dt: float = 0.0       # last frame delta (seconds)
        self.time: float = 0.0     # total elapsed seconds
        self.sim_alpha: float = 0.0  # 0..1 interpolation between sim ticks

    def set_fps_cap(self, fps: int) -> None:
        """0 = uncapped; positive integer caps the render loop."""
        self._fps_cap = max(0, fps)

    def set_tick_hz(self, hz: int) -> None:
        """Reconfigure the fixed-timestep simulation rate (Hz)."""
        self._tick_dt = 1.0 / max(1, int(hz))
        # Drop any accumulated debt that was measured against the old dt so
        # we never replay a burst of ticks at the new rate.
        self._accumulator = 0.0

    def tick(self) -> int:
        """Advance the frame timer and return pending sim ticks to run."""
        ms = self._pg.tick(self._fps_cap)
        self.dt = min(ms / 1000.0, 0.1)  # clamp so a stall doesn't snowball
        self.time += self.dt
        self._accumulator += self.dt
        pending = 0
        while self._accumulator >= self._tick_dt:
            self._accumulator -= self._tick_dt
            pending += 1
        self.sim_alpha = self._accumulator / self._tick_dt
        return pending

    @property
    def fps(self) -> float:
        return self._pg.get_fps()

    @property
    def tick_dt(self) -> float:
        return self._tick_dt
