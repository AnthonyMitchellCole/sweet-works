"""Cardinal direction with helpers."""

from __future__ import annotations

from enum import Enum


class Direction(Enum):
    N = "N"
    E = "E"
    S = "S"
    W = "W"

    @property
    def vector(self) -> tuple[int, int]:
        return _VECTORS[self]

    @property
    def opposite(self) -> Direction:
        return _OPPOSITE[self]

    def rotate_cw(self, times: int = 1) -> Direction:
        order = (Direction.N, Direction.E, Direction.S, Direction.W)
        return order[(order.index(self) + times) % 4]

    def rotate_ccw(self, times: int = 1) -> Direction:
        return self.rotate_cw(-times)

    @property
    def angle_deg(self) -> int:
        """0 for East, 90 for North, 180 for West, 270 for South."""
        return _ANGLE[self]


_VECTORS: dict[Direction, tuple[int, int]] = {
    Direction.N: (0, -1),
    Direction.E: (1, 0),
    Direction.S: (0, 1),
    Direction.W: (-1, 0),
}

_OPPOSITE: dict[Direction, Direction] = {
    Direction.N: Direction.S,
    Direction.E: Direction.W,
    Direction.S: Direction.N,
    Direction.W: Direction.E,
}

_ANGLE: dict[Direction, int] = {
    Direction.E: 0,
    Direction.N: 90,
    Direction.W: 180,
    Direction.S: 270,
}
