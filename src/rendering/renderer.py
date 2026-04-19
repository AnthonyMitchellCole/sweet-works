"""Layered world renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..belts.belt import ConveyorBelt
from ..belts.belt_renderer import draw_belt, draw_belt_items
from ..core import config

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera
    from ..world.world import World


class Renderer:
    def __init__(self, assets: "AssetLoader") -> None:
        self.assets = assets

    def draw_world(
        self,
        surface: pygame.Surface,
        world: "World",
        camera: "Camera",
        time: float,
        sim_alpha: float,
    ) -> None:
        self._draw_floor(surface, camera)
        self._draw_belts(surface, world, camera, time)
        self._draw_buildings(surface, world, camera, time, sim_alpha)
        self._draw_belt_items(surface, world, camera, sim_alpha)

    # -- layers ------------------------------------------------------------

    def _draw_floor(self, surface: pygame.Surface, camera: "Camera") -> None:
        floor = self.assets.sprite("floor")
        size = int(config.TILE * camera.zoom)
        if camera.zoom != 1.0:
            floor = pygame.transform.scale(floor, (size, size))
        min_x, min_y, max_x, max_y = camera.visible_tile_rect()
        for ty in range(min_y, max_y + 1):
            for tx in range(min_x, max_x + 1):
                x, y = camera.world_to_screen(tx * config.TILE, ty * config.TILE)
                surface.blit(floor, (x, y))

    def _draw_belts(
        self,
        surface: pygame.Surface,
        world: "World",
        camera: "Camera",
        time: float,
    ) -> None:
        for tile in world.grid:
            if isinstance(tile, ConveyorBelt):
                draw_belt(tile, surface, camera, self.assets, time)

    def _draw_buildings(
        self,
        surface: pygame.Surface,
        world: "World",
        camera: "Camera",
        time: float,
        sim_alpha: float,
    ) -> None:
        for b in world.buildings:
            b.render(surface, camera, self.assets, time, sim_alpha)

    def _draw_belt_items(
        self,
        surface: pygame.Surface,
        world: "World",
        camera: "Camera",
        sim_alpha: float,
    ) -> None:
        for tile in world.grid:
            if isinstance(tile, ConveyorBelt):
                draw_belt_items(tile, surface, camera, self.assets, sim_alpha)
