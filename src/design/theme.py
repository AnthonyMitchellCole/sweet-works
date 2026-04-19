"""Design tokens: spacing, radii, animation durations."""

from __future__ import annotations

from dataclasses import dataclass

from . import easing


@dataclass(frozen=True)
class Spacing:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32

    def step(self, n: int) -> int:
        """Return n * 4 px for ad-hoc spacing."""
        return n * 4


@dataclass(frozen=True)
class Radius:
    sm: int = 2
    md: int = 4
    lg: int = 6


@dataclass(frozen=True)
class Anim:
    instant: float = 0.0
    fast: float = 0.12
    base: float = 0.20
    slow: float = 0.40

    ease_out: easing.Easing = easing.out_quart
    ease_in_out: easing.Easing = easing.in_out_cubic
    ease_bounce: easing.Easing = easing.out_back


@dataclass(frozen=True)
class Theme:
    spacing: Spacing = Spacing()
    radius: Radius = Radius()
    anim: Anim = Anim()


THEME = Theme()
