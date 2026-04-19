"""Sparse infinite tile grid with dirty-chunk tracking for the chunk renderer."""

from __future__ import annotations

from collections.abc import Iterator

from ..core import config
from .direction import Direction
from .tile import Coord, Tile


def chunk_of(pos: Coord) -> Coord:
    size = config.CHUNK_SIZE
    # Python's floor division matches the chunk tile-range semantics even for
    # negative coordinates (tile -1 belongs to chunk -1, not chunk 0).
    return (pos[0] // size, pos[1] // size)


class Grid:
    def __init__(self) -> None:
        self._tiles: dict[Coord, Tile] = {}
        # Chunks whose cached atlas surface needs re-baking.
        self._dirty_chunks: set[Coord] = set()

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
        self._dirty_chunks.add(chunk_of(tile.pos))

    def remove(self, pos: Coord) -> Tile | None:
        tile = self._tiles.pop(pos, None)
        if tile is not None:
            self._dirty_chunks.add(chunk_of(pos))
        return tile

    def neighbor(self, pos: Coord, d: Direction) -> Tile | None:
        dx, dy = d.vector
        return self._tiles.get((pos[0] + dx, pos[1] + dy))

    def cells_in_rect(
        self, min_x: int, min_y: int, max_x: int, max_y: int
    ) -> Iterator[Tile]:
        for (x, y), t in self._tiles.items():
            if min_x <= x <= max_x and min_y <= y <= max_y:
                yield t

    # ---- dirty chunks ----------------------------------------------------

    def take_dirty_chunks(self) -> set[Coord]:
        out = self._dirty_chunks
        self._dirty_chunks = set()
        return out

    def mark_all_dirty(self) -> None:
        self._dirty_chunks.update(chunk_of(p) for p in self._tiles)
