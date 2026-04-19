"""Placement ghost: tile highlight + oriented preview of the selected prefab."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design.palette import PALETTE, with_alpha
from ..rendering.pool import acquired
from ..world.direction import Direction
from .toolbar import ToolSlot

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera


class PlacementCursor:
    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self.tile_pos: tuple[int, int] = (0, 0)
        self.rotation: Direction = Direction.E
        self.tool: ToolSlot | None = None
        self._time: float = 0.0

    # -- API ---------------------------------------------------------------

    def set_tool(self, slot: ToolSlot) -> None:
        self.tool = slot

    def rotate_cw(self) -> None:
        self.rotation = self.rotation.rotate_cw()

    def update(self, dt: float, tile_pos: tuple[int, int]) -> None:
        self.tile_pos = tile_pos
        self._time += dt

    def footprint(self) -> tuple[int, int]:
        if self.tool is None or self.tool.prefab is None:
            return (1, 1)
        return self.tool.prefab.footprint

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface, camera: Camera) -> None:
        if self.tool is None:
            return

        size = int(config.TILE * camera.zoom)
        fw, fh = self.footprint()
        x, y = camera.world_to_screen(
            self.tile_pos[0] * config.TILE, self.tile_pos[1] * config.TILE
        )
        rect = pygame.Rect(x, y, size * fw, size * fh)

        # Pulsing fill
        pulse = 0.5 + 0.5 * math.sin(self._time * 4.0)
        fill_alpha = int(40 + 40 * pulse)
        with acquired(rect.size) as overlay:
            overlay.fill(with_alpha(PALETTE.secondary, fill_alpha))
            surface.blit(overlay, rect.topleft)

        # Crisp outline + pulsing inner outline
        pygame.draw.rect(surface, PALETTE.secondary, rect, 2)
        inner = rect.inflate(-4, -4)
        pygame.draw.rect(surface, with_alpha(PALETTE.text_strong, int(120 + 80 * pulse)), inner, 1)

        if self.tool.id == "belt":
            self._draw_belt_preview(surface, rect)
        else:
            self._draw_port_preview(surface, rect)

    def _draw_belt_preview(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        dx, dy = self.rotation.vector
        cx, cy = rect.center
        length = min(rect.w, rect.h) // 3
        tip = (cx + dx * length, cy + dy * length)
        tail = (cx - dx * length // 2, cy - dy * length // 2)
        pygame.draw.line(surface, PALETTE.primary, tail, tip, 3)
        self._draw_arrowhead(surface, tip, self.rotation, PALETTE.primary)

    def _draw_arrowhead(
        self,
        surface: pygame.Surface,
        tip: tuple[int, int],
        direction: Direction,
        color,
    ) -> None:
        dx, dy = direction.vector
        perp = (-dy, dx)
        size = 6
        back = (tip[0] - dx * size, tip[1] - dy * size)
        left = (back[0] + perp[0] * size // 2, back[1] + perp[1] * size // 2)
        right = (back[0] - perp[0] * size // 2, back[1] - perp[1] * size // 2)
        pygame.draw.polygon(surface, color, [tip, left, right])

    def _draw_port_preview(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        if self.tool is None or self.tool.prefab is None:
            return
        # Input marker (W) and output marker (E) as a hint.
        left = pygame.Rect(0, 0, 6, 6)
        left.center = (rect.x + 6, rect.centery)
        pygame.draw.rect(surface, PALETTE.secondary, left)
        right = pygame.Rect(0, 0, 6, 6)
        right.center = (rect.right - 6, rect.centery)
        pygame.draw.rect(surface, PALETTE.primary, right)
