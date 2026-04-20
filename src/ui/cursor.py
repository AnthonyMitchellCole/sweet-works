"""Placement ghost: tile highlight + oriented preview of the selected prefab.

Tracks both ``rotation`` and ``mirrored`` so the ghost mirrors the live
state a placed building would land in. Three layered animations sell
changes:

- A scale "pop" on tool switch and on rotate/mirror.
- A chevron "sweep" trail on rotate (from the previous facing to the new
  one) that fades over 200 ms.
- A horizontal flip pulse on mirror, along the axis perpendicular to
  facing, that briefly squashes + expands the ghost.
"""

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
    """Placement ghost with validity + transform feedback.

    When the target tile(s) are free the cursor shows the tool's accent color
    (blue fill, primary arrow for belts). When any target cell is occupied it
    flips to ``PALETTE.danger`` with a dashed outline and a subtle shake so
    the rejection is obvious without being noisy.
    """

    _TOOL_CHANGE_POP_MS: float = 220.0
    _ROTATE_SWEEP_MS: float = 260.0
    _MIRROR_FLIP_MS: float = 220.0

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self.tile_pos: tuple[int, int] = (0, 0)
        self.rotation: Direction = Direction.E
        self.mirrored: bool = False
        self.tool: ToolSlot | None = None
        self.is_valid: bool = True
        self._time: float = 0.0
        # Re-used to retrigger the "snap to life" scale on tool / rotation swaps.
        self._tool_change_time: float = 0.0
        # Dedicated channels for the micro-animations so one cannot cut
        # the other short.
        self._rotate_time: float = -10.0
        self._mirror_time: float = -10.0
        self._rotate_from: Direction = Direction.E
        self._last_tool_id: str | None = None

    # -- API ---------------------------------------------------------------

    def set_tool(self, slot: ToolSlot) -> None:
        if self.tool is None or slot.id != self.tool.id:
            self._tool_change_time = self._time
        self.tool = slot

    def rotate_cw(self) -> None:
        self._rotate_from = self.rotation
        self.rotation = self.rotation.rotate_cw()
        self._tool_change_time = self._time
        self._rotate_time = self._time

    def mirror(self) -> None:
        self.mirrored = not self.mirrored
        self._tool_change_time = self._time
        self._mirror_time = self._time

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

        # Mirror flip: horizontal squash along the perpendicular-to-facing axis.
        mirror_age = max(0.0, self._time - self._mirror_time)
        flip_duration = self._MIRROR_FLIP_MS / 1000.0
        if mirror_age < flip_duration:
            ft = mirror_age / flip_duration
            # Scale goes 0.82 -> 1.0 along the flip axis.
            scale = 0.82 + easing.out_quart(ft) * 0.18
            if self.rotation in (Direction.E, Direction.W):
                # Flip axis = vertical → squash vertically.
                squash_px = int(round((1.0 - scale) * rect.h / 2))
                rect = rect.inflate(0, -squash_px * 2)
            else:
                squash_px = int(round((1.0 - scale) * rect.w / 2))
                rect = rect.inflate(-squash_px * 2, 0)

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

        # Structure sprite ghost underneath the outline (belt tool keeps
        # the arrow preview since belts don't have a structure sprite).
        if self.tool.id != "belt":
            self._draw_structure_ghost(surface, rect, camera)

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

        self._draw_rotate_sweep(surface, rect)
        self._draw_mirror_indicator(surface, rect)

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

    def _draw_structure_ghost(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        camera: Camera,
    ) -> None:
        """Blit the tool's actual structure sprite as a reduced-alpha ghost."""
        if self.tool is None or self.tool.prefab is None:
            return
        key = f"{self.tool.prefab.sprite_base}_idle_f0"
        try:
            sprite = self.assets.structure_sprite_oriented(
                key, self.rotation, self.mirrored, camera.zoom
            )
        except (FileNotFoundError, pygame.error):
            return
        if sprite.get_width() != rect.w or sprite.get_height() != rect.h:
            sprite = pygame.transform.smoothscale(sprite, (rect.w, rect.h))
        else:
            sprite = sprite.copy()
        sprite.set_alpha(130)
        surface.blit(sprite, rect.topleft)

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
        """Port-marker preview derived from the live rotation + mirror.

        Walks the prefab's port hints (encoded as local-frame positions
        on its wrapped Building) by briefly constructing an instance at
        the placement origin. This keeps the ghost's markers pixel-exact
        with the building that will be placed.
        """
        if self.tool is None or self.tool.prefab is None:
            return

        try:
            preview = self.tool.prefab.factory(
                self.tile_pos, self.rotation, self.mirrored
            )
        except TypeError:
            # Older factories that don't accept the mirrored arg.
            preview = self.tool.prefab.factory(self.tile_pos, self.rotation)

        fw, fh = preview.footprint
        cell_w = max(1, rect.w // max(1, fw))
        cell_h = max(1, rect.h // max(1, fh))

        def marker(cx: int, cy: int, side: Direction, color) -> None:
            px = rect.x + cx * cell_w + cell_w // 2
            py = rect.y + cy * cell_h + cell_h // 2
            dx, dy = side.vector
            half_w = cell_w // 2
            half_h = cell_h // 2
            px += int(dx * (half_w - 4))
            py += int(dy * (half_h - 4))
            dot = pygame.Rect(0, 0, 6, 6)
            dot.center = (px, py)
            pygame.draw.rect(surface, color, dot)

        in_color = PALETTE.muted if muted else PALETTE.secondary
        out_color = PALETTE.muted if muted else PALETTE.primary
        ox, oy = preview.origin
        for port in preview.inputs:
            marker(port.cell[0] - ox, port.cell[1] - oy, port.side, in_color)
        for port in preview.outputs:
            marker(port.cell[0] - ox, port.cell[1] - oy, port.side, out_color)

    # -- micro-animations --------------------------------------------------

    def _draw_rotate_sweep(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        """Brief curved chevron arc from the previous facing to the new one."""
        age = self._time - self._rotate_time
        dur = self._ROTATE_SWEEP_MS / 1000.0
        if age < 0 or age >= dur:
            return
        t = age / dur
        alpha = int(255 * (1.0 - easing.out_quart(t)))
        if alpha <= 4 or self._rotate_from is self.rotation:
            return
        # Interpolated direction (we fake a smooth arc by stepping through
        # the intermediate angle). We approximate with an eased mix
        # between prev and next facing angles.
        prev = self._rotate_from.angle_deg
        nxt = self.rotation.angle_deg
        # Shortest CW arc (rotation is always CW).
        delta = (prev - nxt) % 360  # CW delta in degrees
        if delta == 0:
            return
        swept = prev - delta * easing.out_quart(t)
        rad = math.radians(swept)
        cx, cy = rect.center
        r = min(rect.w, rect.h) // 2 - 4
        # Pygame y-axis points down → negate sin.
        tip = (cx + math.cos(rad) * r, cy - math.sin(rad) * r)
        # Arrow points along current sweep tangent (perpendicular, CW).
        tan_rad = rad - math.pi / 2
        tdx = math.cos(tan_rad)
        tdy = -math.sin(tan_rad)
        back = (tip[0] - tdx * 10, tip[1] - tdy * 10)
        perp = (-tdy, tdx)
        left = (back[0] + perp[0] * 5, back[1] + perp[1] * 5)
        right = (back[0] - perp[0] * 5, back[1] - perp[1] * 5)
        color = with_alpha(PALETTE.primary, alpha)
        with acquired(rect.size) as overlay:
            local_pts = [
                (int(tip[0] - rect.x), int(tip[1] - rect.y)),
                (int(left[0] - rect.x), int(left[1] - rect.y)),
                (int(right[0] - rect.x), int(right[1] - rect.y)),
            ]
            pygame.draw.polygon(overlay, color, local_pts)
            surface.blit(overlay, rect.topleft)

    def _draw_mirror_indicator(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        """Subtle flip-line along the facing axis when mirrored is on."""
        if not self.mirrored:
            return
        # Pulsing axis line down the centre of the ghost.
        pulse = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._time * 5.0))
        color = with_alpha(PALETTE.secondary, int(150 * pulse))
        if self.rotation in (Direction.E, Direction.W):
            # Facing horizontal → flip axis horizontal.
            y = rect.centery
            pygame.draw.line(surface, color, (rect.left + 4, y), (rect.right - 4, y), 2)
        else:
            x = rect.centerx
            pygame.draw.line(surface, color, (x, rect.top + 4), (x, rect.bottom - 4), 2)
