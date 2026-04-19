"""Placement ghost: tile highlight + oriented preview of the selected prefab."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design import easing
from ..design.palette import PALETTE, with_alpha
from ..rendering.pixel import dashed_rect
from ..rendering.pool import acquired
from ..world.direction import Direction
from .toolbar import ToolSlot

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera


class PlacementCursor:
    """Placement ghost with validity feedback.

    When the target tile(s) are free the cursor shows the tool's accent color
    (blue fill, primary arrow for belts). When any target cell is occupied it
    flips to ``PALETTE.danger`` with a dashed outline and a subtle shake so
    the rejection is obvious without being noisy.
    """

    _TOOL_CHANGE_POP_MS: float = 220.0

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self.tile_pos: tuple[int, int] = (0, 0)
        self.rotation: Direction = Direction.E
        self.tool: ToolSlot | None = None
        self.is_valid: bool = True
        self._time: float = 0.0
        # Re-used to retrigger the "snap to life" scale on tool / rotation swaps.
        self._tool_change_time: float = 0.0
        self._last_tool_id: str | None = None
        self._last_rotation: Direction = Direction.E

    # -- API ---------------------------------------------------------------

    def set_tool(self, slot: ToolSlot) -> None:
        if self.tool is None or slot.id != self.tool.id:
            self._tool_change_time = self._time
        self.tool = slot

    def rotate_cw(self) -> None:
        self.rotation = self.rotation.rotate_cw()
        self._tool_change_time = self._time

    def update(
        self,
        dt: float,
        tile_pos: tuple[int, int],
        is_valid: bool = True,
    ) -> None:
        self.tile_pos = tile_pos
        self.is_valid = is_valid
        self._time += dt

    def footprint(self) -> tuple[int, int]:
        if self.tool is None or self.tool.prefab is None:
            return (1, 1)
        return self.tool.prefab.footprint

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface, camera: Camera) -> None:
        if self.tool is None:
            return
        # In Pointer (inspect) mode, do not draw a placement ghost. Hover
        # feedback comes from the hover-highlight brackets instead.
        if self.tool.id == "pointer":
            return

        size = int(config.TILE * camera.zoom)
        fw, fh = self.footprint()
        x, y = camera.world_to_screen(
            self.tile_pos[0] * config.TILE, self.tile_pos[1] * config.TILE
        )
        rect = pygame.Rect(x, y, size * fw, size * fh)

        # Snap-to-life scale on tool/rotation swap: briefly inset, then settle.
        age = max(0.0, self._time - self._tool_change_time)
        pop_duration = self._TOOL_CHANGE_POP_MS / 1000.0
        if age < pop_duration:
            pop_t = age / pop_duration
            # inset starts small then resolves to zero.
            inset_px = int(round((1.0 - easing.out_quart(pop_t)) * max(2, size // 10)))
        else:
            inset_px = 0
        rect = rect.inflate(-inset_px * 2, -inset_px * 2)

        pulse = 0.5 + 0.5 * math.sin(self._time * 4.0)

        if not self.is_valid:
            self._render_invalid(surface, rect, pulse)
            return

        accent = PALETTE.secondary
        # Pulsing fill
        fill_alpha = int(40 + 40 * pulse)
        with acquired(rect.size) as overlay:
            overlay.fill(with_alpha(accent, fill_alpha))
            surface.blit(overlay, rect.topleft)

        # Crisp outline + pulsing inner outline
        pygame.draw.rect(surface, accent, rect, 2)
        inner = rect.inflate(-4, -4)
        pygame.draw.rect(
            surface, with_alpha(PALETTE.text_strong, int(120 + 80 * pulse)), inner, 1
        )

        if self.tool.id == "belt":
            self._draw_belt_preview(surface, rect)
        else:
            self._draw_port_preview(surface, rect)

    def _render_invalid(
        self, surface: pygame.Surface, rect: pygame.Rect, pulse: float
    ) -> None:
        """Danger-tinted ghost with dashed outline + micro-shake."""
        # 1.5 px shake on the outline for an unmistakable "no" signal.
        shake = math.sin(self._time * 26.0) * 1.5
        shaken = rect.move(int(round(shake)), 0)

        fill_alpha = int(55 + 35 * pulse)
        with acquired(shaken.size) as overlay:
            overlay.fill(with_alpha(PALETTE.danger, fill_alpha))
            surface.blit(overlay, shaken.topleft)

        # Dashed outline (phase animates so it feels hot).
        phase = int((self._time * 24.0) % 5)
        dashed_rect(surface, shaken, PALETTE.danger, dash=3, gap=2, phase=phase)
        inner = shaken.inflate(-4, -4)
        dashed_rect(
            surface,
            inner,
            PALETTE.danger,
            dash=2,
            gap=3,
            phase=(phase + 2) % 5,
        )

        # Muted arrow / port markers beneath the dashed outline so the
        # user still sees the intended orientation.
        if self.tool is None:
            return
        if self.tool.id == "belt":
            self._draw_belt_preview(surface, shaken, color=PALETTE.muted)
        else:
            self._draw_port_preview(surface, shaken, muted=True)

    def _draw_belt_preview(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        color: tuple[int, int, int] | None = None,
    ) -> None:
        dx, dy = self.rotation.vector
        cx, cy = rect.center
        length = min(rect.w, rect.h) // 3
        tip = (cx + dx * length, cy + dy * length)
        tail = (cx - dx * length // 2, cy - dy * length // 2)
        c = color if color is not None else PALETTE.primary
        pygame.draw.line(surface, c, tail, tip, 3)
        self._draw_arrowhead(surface, tip, self.rotation, c)

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

    def _draw_port_preview(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        muted: bool = False,
    ) -> None:
        if self.tool is None or self.tool.prefab is None:
            return
        left_c = PALETTE.muted if muted else PALETTE.secondary
        right_c = PALETTE.muted if muted else PALETTE.primary
        left = pygame.Rect(0, 0, 6, 6)
        left.center = (rect.x + 6, rect.centery)
        pygame.draw.rect(surface, left_c, left)
        right = pygame.Rect(0, 0, 6, 6)
        right.center = (rect.right - 6, rect.centery)
        pygame.draw.rect(surface, right_c, right)
