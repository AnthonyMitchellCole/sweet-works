"""Cardinal direction with helpers.

The :class:`Direction` enum is the canonical orientation type for the
whole codebase -- belts, buildings, placement cursor, and UI diagrams
all consume it directly or indirectly. The pure helpers at the bottom
(:func:`rotate_side`, :func:`rotate_offset`, :func:`mirror_side`,
:func:`mirror_offset`) turn a building's **local port layout** (authored
as if the building faces :attr:`Direction.E`, un-mirrored) into its
world-space side/cell under a live ``rotation`` + ``mirrored`` pair.
The transforms are 90-degree-quantised and keep all coordinates
integer, so they compose cleanly with the grid-based world model.
"""

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


# ---------------------------------------------------------------------------
# Rotation / mirror transforms for building port layouts.
#
# Convention: a building's local layout is authored as if it faces
# ``Direction.E`` and is un-mirrored. ``rotation_steps_cw`` below is the
# number of 90-degree clockwise rotations to apply to go from that
# canonical frame to the live ``rotation``.
# ---------------------------------------------------------------------------


def rotation_steps_cw(rotation: Direction) -> int:
    """Number of 90-degree CW steps from ``Direction.E`` to ``rotation``."""
    order = (Direction.E, Direction.S, Direction.W, Direction.N)
    return order.index(rotation)


def rotate_side(side_local: Direction, rotation: Direction) -> Direction:
    """Rotate a local side into world space under ``rotation``."""
    return side_local.rotate_cw(rotation_steps_cw(rotation))


def rotate_offset(
    offset: tuple[int, int],
    rotation: Direction,
    footprint: tuple[int, int],
) -> tuple[int, int]:
    """Rotate a local cell offset within its footprint.

    Applies ``rotation_steps_cw(rotation)`` 90-degree clockwise steps in
    y-down screen coordinates. Each step maps ``(x, y)`` within an
    ``(fw, fh)`` footprint to ``(fh - 1 - y, x)`` in an ``(fh, fw)``
    footprint (the footprint swaps each step).
    """
    x, y = int(offset[0]), int(offset[1])
    fw, fh = int(footprint[0]), int(footprint[1])
    for _ in range(rotation_steps_cw(rotation)):
        x, y = fh - 1 - y, x
        fw, fh = fh, fw
    return (x, y)


def mirror_side(side_local: Direction, rotation: Direction) -> Direction:
    """Reflect ``side_local`` across the facing axis (axis along ``rotation``).

    In the local (E-facing) frame, the facing axis is horizontal, so a
    mirror flips ``N`` <-> ``S`` and leaves ``E`` / ``W`` alone. The
    ``rotation`` argument is accepted for symmetry with
    :func:`rotate_side` but the result is rotation-independent because
    mirror is applied before rotation.
    """
    del rotation
    if side_local is Direction.N:
        return Direction.S
    if side_local is Direction.S:
        return Direction.N
    return side_local


def mirror_offset(
    offset: tuple[int, int],
    rotation: Direction,
    footprint: tuple[int, int],
) -> tuple[int, int]:
    """Reflect a local cell offset across the facing axis.

    In the local (E-facing) frame the facing axis is horizontal, so the
    mirror flips ``y`` within the local footprint. ``rotation`` is
    accepted for symmetry; the transform is applied in local space
    before rotation.
    """
    del rotation
    x, y = int(offset[0]), int(offset[1])
    fh = int(footprint[1])
    return (x, fh - 1 - y)


def resolve_local_port(
    side_local: Direction,
    cell_offset_local: tuple[int, int],
    rotation: Direction,
    mirrored: bool,
    footprint: tuple[int, int],
) -> tuple[Direction, tuple[int, int]]:
    """Fully resolve a local port declaration into world (side, cell offset).

    Applied in order: **mirror (local) -> rotation**. This composes
    cleanly because both transforms are rigid and the mirror lives in
    the same local frame the ports are authored in.
    """
    side = side_local
    cell = (int(cell_offset_local[0]), int(cell_offset_local[1]))
    if mirrored:
        side = mirror_side(side, rotation)
        cell = mirror_offset(cell, rotation, footprint)
    side = rotate_side(side, rotation)
    cell = rotate_offset(cell, rotation, footprint)
    return side, cell


def rotated_footprint(
    footprint: tuple[int, int], rotation: Direction
) -> tuple[int, int]:
    """Footprint after applying ``rotation`` (swaps on 90/270 deg)."""
    fw, fh = int(footprint[0]), int(footprint[1])
    if rotation_steps_cw(rotation) % 2 == 1:
        return (fh, fw)
    return (fw, fh)


__all__ = [
    "Direction",
    "rotation_steps_cw",
    "rotate_side",
    "rotate_offset",
    "mirror_side",
    "mirror_offset",
    "resolve_local_port",
    "rotated_footprint",
]
