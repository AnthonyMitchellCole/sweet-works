"""Z-ordered render layers."""

from __future__ import annotations

from enum import IntEnum


class Layer(IntEnum):
    FLOOR = 0
    BELT = 1
    BUILDING = 2
    ITEM = 3
    GHOST = 4
    UI = 5
