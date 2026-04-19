"""Tween primitives used by the UI and rendering code."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..design import easing


@dataclass
class Tween:
    start: float
    end: float
    duration: float
    ease: easing.Easing = field(default=easing.out_quart)
    elapsed: float = 0.0
    done: bool = False

    def update(self, dt: float) -> float:
        if self.done:
            return self.end
        self.elapsed += dt
        if self.elapsed >= self.duration or self.duration <= 0:
            self.done = True
            return self.end
        t = self.ease(self.elapsed / self.duration)
        return self.start + (self.end - self.start) * t

    def reset(self, start: float, end: float, duration: float | None = None) -> None:
        self.start = start
        self.end = end
        if duration is not None:
            self.duration = duration
        self.elapsed = 0.0
        self.done = duration == 0.0


@dataclass
class AnimValue:
    """Auto-lerping scalar toward `target`."""

    value: float = 0.0
    target: float = 0.0
    speed: float = 12.0  # higher = snappier

    def set(self, value: float) -> None:
        self.value = value
        self.target = value

    def to(self, target: float) -> None:
        self.target = target

    def update(self, dt: float) -> float:
        import math

        k = 1.0 - math.exp(-self.speed * dt)
        self.value += (self.target - self.value) * k
        return self.value
