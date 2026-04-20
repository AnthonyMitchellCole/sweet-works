"""Top HUD: resource counters, FPS, tick indicator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..core.events import EventBus
from ..design.palette import PALETTE, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..items.item_type import ItemType
from ..items.registry import ITEMS
from ..rendering.animation import AnimValue
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from ..world.direction import Direction

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


class HUD:
    def __init__(self, assets: AssetLoader, events: EventBus) -> None:
        self.assets = assets
        self.events = events

        self._tracked: tuple[ItemType, ...] = (
            ITEMS.cocoa_bean,
            ITEMS.sugar_crystal,
            ITEMS.milk,
            ITEMS.chocolate,
            ITEMS.caramel,
            ITEMS.candy_bar,
        )
        self._counts: dict[str, int] = {t.id: 0 for t in self._tracked}
        self._pulses: dict[str, AnimValue] = {
            t.id: AnimValue(value=0.0, speed=10.0) for t in self._tracked
        }

        self._off_produced = events.on("item.produced", self._on_produced)

        # Live transform state mirrored from the placement cursor.
        self._rotation: Direction = Direction.E
        self._mirrored: bool = False

    def close(self) -> None:
        self._off_produced()

    # -- events ------------------------------------------------------------

    def _on_produced(self, item_type: ItemType) -> None:
        self._counts[item_type.id] = self._counts.get(item_type.id, 0) + 1
        p = self._pulses.get(item_type.id)
        if p is not None:
            p.value = 1.0
            p.to(0.0)

    # -- update/render -----------------------------------------------------

    def update(self, dt: float) -> None:
        for p in self._pulses.values():
            p.update(dt)

    def set_transform(self, rotation: Direction, mirrored: bool) -> None:
        """Sync the transform indicator with the live placement cursor."""
        self._rotation = rotation
        self._mirrored = bool(mirrored)

    def render(self, surface: pygame.Surface, fps: float) -> None:
        pad = THEME.spacing.lg
        height = 48
        rect = pygame.Rect(pad, pad, surface.get_width() - pad * 2, height)
        beveled_panel(surface, rect, fill=PALETTE.bg_base, border=PALETTE.line)

        title = self.assets.render_text("SWEET WORKS", TYPE.label, PALETTE.primary)
        surface.blit(title, (rect.x + THEME.spacing.md, rect.y + (height - title.get_height()) // 2))

        x = rect.x + THEME.spacing.md + title.get_width() + THEME.spacing.xl
        for t in self._tracked:
            pulse = self._pulses[t.id].value
            x = self._render_resource(surface, rect, x, t, self._counts[t.id], pulse)

        fps_surf = self.assets.render_text(f"{int(fps):>3} FPS", TYPE.mono, PALETTE.muted)
        fps_x = rect.right - fps_surf.get_width() - THEME.spacing.md
        surface.blit(
            fps_surf,
            (fps_x, rect.y + (height - fps_surf.get_height()) // 2),
        )

        # Compact transform indicator lives just left of the FPS counter.
        pip_x = fps_x - THEME.spacing.lg - 24
        pip_y = rect.y + height // 2
        self._render_transform_pip(surface, pip_x, pip_y)

    def _render_resource(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        x: int,
        item_type: ItemType,
        count: int,
        pulse: float,
    ) -> int:
        icon = self.assets.item_icon(item_type.id)
        icon_y = rect.y + (rect.h - icon.get_height()) // 2
        surface.blit(icon, (x, icon_y))

        count_surf = self.assets.render_text(
            f"{count:>3}", TYPE.mono, PALETTE.text_strong
        )
        tx = x + icon.get_width() + THEME.spacing.xs
        ty = rect.y + (rect.h - count_surf.get_height()) // 2
        surface.blit(count_surf, (tx, ty))

        if pulse > 0.02:
            halo_size = (icon.get_width() + 6, icon.get_height() + 6)
            with acquired(halo_size) as halo:
                halo.fill(with_alpha(item_type.color, int(pulse * 140)))
                surface.blit(
                    halo, (x - 3, icon_y - 3), special_flags=pygame.BLEND_PREMULTIPLIED
                )

        return tx + count_surf.get_width() + THEME.spacing.lg

    def _render_transform_pip(
        self, surface: pygame.Surface, cx: int, cy: int
    ) -> None:
        """Compass chevron + optional flip bar at (cx, cy)."""
        dx, dy = self._rotation.vector
        perp = (-dy, dx)
        size = 7
        tip = (cx + dx * size, cy + dy * size)
        back = (cx - dx * size, cy - dy * size)
        left = (back[0] + perp[0] * size, back[1] + perp[1] * size)
        right = (back[0] - perp[0] * size, back[1] - perp[1] * size)
        color = lighten(PALETTE.primary, 0.1)
        pygame.draw.polygon(surface, color, [tip, left, right])
        pygame.draw.polygon(surface, PALETTE.bg_deep, [tip, left, right], 1)
        if self._mirrored:
            mirror_color = with_alpha(PALETTE.secondary, 220)
            with acquired((24, 24)) as layer:
                pygame.draw.line(
                    layer,
                    mirror_color,
                    (12 + perp[0] * 10, 12 + perp[1] * 10),
                    (12 - perp[0] * 10, 12 - perp[1] * 10),
                    2,
                )
                surface.blit(layer, (cx - 12, cy - 12))
