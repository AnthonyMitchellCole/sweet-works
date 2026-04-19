"""Chunk-based world background renderer.

Floor tiles and the static (non-animated) belt base are baked into a
``Surface`` per chunk, per zoom bin. Drawing the world background then
reduces to one ``blit`` per visible chunk instead of one blit per tile.

Animated belt chevrons are re-blitted on top per frame (belt sprites are
already pre-rotated and zoom-cached by :class:`ScaledSpriteCache`).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

import pygame

from ..belts.belt import ConveyorBelt
from ..core import config
from ..world.grid import chunk_of
from .sprite_cache import zoom_bin

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera
    from ..world.world import World


_DIR_CODE_TO_STR = {0: "E", 1: "N", 2: "W", 3: "S"}


def _chunk_world_rect(chunk: tuple[int, int]) -> tuple[int, int, int, int]:
    cs = config.CHUNK_SIZE
    wx = chunk[0] * cs * config.TILE
    wy = chunk[1] * cs * config.TILE
    return (wx, wy, cs * config.TILE, cs * config.TILE)


class ChunkRenderer:
    """Bake + blit per-chunk backgrounds with LRU eviction."""

    def __init__(self, max_entries: int = 96) -> None:
        # OrderedDict acts as an LRU: recently used chunks stay at the end.
        self._cache: OrderedDict[tuple[tuple[int, int], int], pygame.Surface] = OrderedDict()
        self._max = max_entries

    def invalidate(self, chunk: tuple[int, int]) -> None:
        for key in list(self._cache.keys()):
            if key[0] == chunk:
                del self._cache[key]

    def invalidate_zoom(self) -> None:
        self._cache.clear()

    def clear(self) -> None:
        self._cache.clear()

    # ---- public API ------------------------------------------------------

    def draw(
        self,
        surface: pygame.Surface,
        world: World,
        camera: Camera,
        assets: AssetLoader,
    ) -> None:
        """Blit all chunks that intersect the camera viewport."""
        self._drain_dirty(world)

        bin_idx = zoom_bin(camera.zoom)
        min_tx, min_ty, max_tx, max_ty = camera.visible_tile_rect()
        cs = config.CHUNK_SIZE
        min_cx = min_tx // cs
        min_cy = min_ty // cs
        max_cx = max_tx // cs
        max_cy = max_ty // cs

        for cy in range(min_cy, max_cy + 1):
            for cx in range(min_cx, max_cx + 1):
                chunk = (cx, cy)
                surf = self._get_chunk_surface(chunk, bin_idx, world, assets, camera.zoom)
                wx, wy, _, _ = _chunk_world_rect(chunk)
                sx, sy = camera.world_to_screen(wx, wy)
                surface.blit(surf, (sx, sy))

    # ---- internals -------------------------------------------------------

    def _drain_dirty(self, world: World) -> None:
        dirty = world.grid.take_dirty_chunks()
        for c in dirty:
            self.invalidate(c)

    def _get_chunk_surface(
        self,
        chunk: tuple[int, int],
        bin_idx: int,
        world: World,
        assets: AssetLoader,
        zoom: float,
    ) -> pygame.Surface:
        key = (chunk, bin_idx)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        surf = self._bake_chunk(chunk, world, assets, zoom)
        self._cache[key] = surf
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return surf

    def _bake_chunk(
        self,
        chunk: tuple[int, int],
        world: World,
        assets: AssetLoader,
        zoom: float,
    ) -> pygame.Surface:
        cs = config.CHUNK_SIZE
        tile_px = max(1, int(round(config.TILE * zoom)))
        size_px = cs * tile_px
        surf = pygame.Surface((size_px, size_px))

        floor = assets.sprite_scaled("floor", zoom)
        for dy in range(cs):
            for dx in range(cs):
                surf.blit(floor, (dx * tile_px, dy * tile_px))

        cx, cy = chunk
        origin_tx = cx * cs
        origin_ty = cy * cs
        grid = world.grid
        for ty in range(origin_ty, origin_ty + cs):
            for tx in range(origin_tx, origin_tx + cs):
                tile = grid.get((tx, ty))
                if isinstance(tile, ConveyorBelt):
                    belt_sprite = assets.belt_scaled(tile.direction.value, 0, zoom)
                    surf.blit(belt_sprite, ((tx - origin_tx) * tile_px, (ty - origin_ty) * tile_px))
        return surf


def chunks_intersecting_rect(
    min_tx: int, min_ty: int, max_tx: int, max_ty: int
) -> list[tuple[int, int]]:
    cs = config.CHUNK_SIZE
    out: list[tuple[int, int]] = []
    for cy in range(min_ty // cs, max_ty // cs + 1):
        for cx in range(min_tx // cs, max_tx // cs + 1):
            out.append((cx, cy))
    return out


__all__ = ["ChunkRenderer", "chunk_of", "chunks_intersecting_rect"]
