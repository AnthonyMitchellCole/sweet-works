"""Easing functions, all taking t in [0, 1] and returning a value in [0, 1]."""

from __future__ import annotations

import math
from typing import Callable


Easing = Callable[[float], float]


def linear(t: float) -> float:
    return t


def in_quad(t: float) -> float:
    return t * t


def out_quad(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def in_out_quad(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def out_quart(t: float) -> float:
    return 1 - (1 - t) ** 4


def out_quint(t: float) -> float:
    return 1 - (1 - t) ** 5


def in_out_cubic(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def out_back(t: float, overshoot: float = 1.70158) -> float:
    c1 = overshoot
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def out_elastic(t: float) -> float:
    if t in (0.0, 1.0):
        return t
    c4 = (2 * math.pi) / 3
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * c4) + 1


def in_out_sine(t: float) -> float:
    return -(math.cos(math.pi * t) - 1) / 2
