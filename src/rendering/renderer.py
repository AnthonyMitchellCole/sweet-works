"""Layered world renderer.

The renderer delegates:
- Static floor + belt backgrounds -> :class:`ChunkRenderer` (cached per chunk per zoom bin).
- Animated belts + items          -> :mod:`belts.belt_renderer` vectorised batch drawing.
- Buildings                       -> `Building.render`, culled against the camera.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..belts.belt_renderer import (
    draw_belts_batch,
    draw_items_batch,
)
from ..core import config
from ..core.perf import PERF
from .chunk_renderer import ChunkRenderer
from .cull import visible_belts_mask, visible_chain_ids
from .sprite_cache import zoom_bin

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera
    from ..world.world import World


class Renderer:
    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self.chunks = ChunkRenderer()
        self._last_zoom_bin: int = 0

    def invalidate_chunks(self) -> None:
        self.chunks.clear()

    def draw_world(
        self,
        surface: pygame.Surface,
        world: World,
        camera: Camera,
        time: float,
        sim_alpha: float,
    ) -> None:
        current_bin = zoom_bin(camera.zoom)
        if current_bin != self._last_zoom_bin:
            self.chunks.invalidate_zoom()
            self._last_zoom_bin = current_bin

        self.chunks.draw(surface, world, camera, self.assets)

        belt_count = 0
        item_count = 0
        chain_count = 0
        if world.belt_network is not None:
            soa = world.belt_network.soa
            if soa.belt_count > 0:
                chain_count = soa.chain_count
                mask = visible_belts_mask(soa, camera)
                if mask.any():
                    import numpy as np
                    vis_belts = np.flatnonzero(mask).astype(np.int32, copy=False)
                    belt_count = draw_belts_batch(
                        surface, soa, vis_belts, camera, self.assets, time
                    )
                vis_chains = visible_chain_ids(soa, camera)
                item_count = draw_items_batch(
                    surface, soa, vis_chains, camera, self.assets, sim_alpha
                )

        self._draw_buildings(surface, world, camera, time, sim_alpha)

        PERF.chain_count = chain_count
        PERF.visible_chains = belt_count
        PERF.visible_items = item_count
        if world.belt_network is not None:
            PERF.item_count = world.belt_network.total_items()

    # -- layers ------------------------------------------------------------

    def _draw_buildings(
        self,
        surface: pygame.Surface,
        world: World,
        camera: Camera,
        time: float,
        sim_alpha: float,
    ) -> None:
        if not world.buildings:
            return
        min_tx, min_ty, max_tx, max_ty = camera.visible_tile_rect()
        for b in world.buildings:
            ox, oy = b.origin
            w, h = b.footprint
            # AABB cull on building footprint.
            if ox + w - 1 < min_tx or oy + h - 1 < min_ty:
                continue
            if ox > max_tx or oy > max_ty:
                continue
            b.render(surface, camera, self.assets, time, sim_alpha)


# Re-export config for tests that import from this module.
_ = config
