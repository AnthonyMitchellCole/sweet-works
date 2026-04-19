"""Sparse infinite tile grid."""

from __future__ import annotations

from typing import Iterator

from .direction import Direction
from .tile import Coord, Tile


class Grid:
    def __init__(self) -> None:
        self._tiles: dict[Coord, Tile] = {}

    def __contains__(self, pos: Coord) -> bool:
        return pos in self._tiles

    def __iter__(self) -> Iterator[Tile]:
        return iter(self._tiles.values())

    def __len__(self) -> int:
        return len(self._tiles)

    def get(self, pos: Coord) -> Tile | None:
        return self._tiles.get(pos)

    def set(self, tile: Tile) -> None:
        self._tiles[tile.pos] = tile

    def remove(self, pos: Coord) -> Tile | None:
        return self._tiles.pop(pos, None)

    def neighbor(self, pos: Coord, d: Direction) -> Tile | None:
        dx, dy = d.vector
        return self._tiles.get((pos[0] + dx, pos[1] + dy))

    def cells_in_rect(self, min_x: int, min_y: int, max_x: int, max_y: int) -> Iterator[Tile]:
        for (x, y), t in self._tiles.items():
            if min_x <= x <= max_x and min_y <= y <= max_y:
                yield t
