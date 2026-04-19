"""Selected-structure menu: slide-in detail panel on the right.

Opens when the player clicks an existing building. Pulls fresh numbers
from the live simulation every frame (port counts, craft progress) via
``ui.info``, so no events or caching are required.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from .info import PortInfo, StructureInfo, for_belt, for_building
from .widget import Widget

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..belts.belt import ConveyorBelt
    from ..belts.network_soa import BeltNetworkSoA
    from ..buildings.building import Building


_PANEL_W = 320
_PANEL_H = 440
_MARGIN = 24
_PAD = THEME.spacing.lg
_SECTION_GAP = THEME.spacing.md
_ROW_H = 22
_PORT_BAR_H = 10
_CLOSE_SIZE = 24
_SHADOW_ALPHA = 150


class StructureMenu:
    """Right-anchored detail panel, slides in with an ease-out tween."""

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self._building: Building | None = None
        self._belt: ConveyorBelt | None = None
        self._belt_net: BeltNetworkSoA | None = None
        self._info: StructureInfo | None = None
        self._window_size: tuple[int, int] = (0, 0)
        self._final_x: int = 0
        self._offscreen_x: int = 0
        self._y: int = 0
        self._x_tween: Tween = Tween(start=0.0, end=0.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out)
        self._x_tween.done = True
        self._is_open: bool = False
        self._closing: bool = False

        # Smoothed values for numbers + bars.
        self._progress_anim = AnimValue(value=0.0, target=0.0, speed=10.0)
        self._port_anims: dict[int, AnimValue] = {}
        self._time: float = 0.0

        # Close button widget
        self._close_btn = Widget(pygame.Rect(0, 0, _CLOSE_SIZE, _CLOSE_SIZE))

    # -- layout ------------------------------------------------------------

    def layout(self, window_size: tuple[int, int]) -> None:
        self._window_size = window_size
        w, h = window_size
        self._final_x = w - _PANEL_W - _MARGIN
        self._offscreen_x = w + 8
        # Keep the menu vertically centered between the HUD bar and the toolbar.
        hud_bottom = 16 + 48 + 8          # top pad + HUD h + gap
        toolbar_top = h - (64 + 12 * 2 + 16)  # SLOT + PANEL_PAD*2 + bottom gap
        usable_h = max(_PANEL_H, toolbar_top - hud_bottom)
        self._y = hud_bottom + max(0, (usable_h - _PANEL_H) // 2)
        # Re-target in-flight tween if needed.
        if self._is_open and not self._closing:
            self._x_tween = Tween(
                start=self._current_x(),
                end=self._final_x,
                duration=THEME.anim.base,
                ease=THEME.anim.ease_out,
            )

    # -- API ---------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._is_open

    def rect(self) -> pygame.Rect | None:
        if not self._is_open:
            return None
        return pygame.Rect(int(self._current_x()), self._y, _PANEL_W, _PANEL_H)

    def open_building(self, building: Building) -> None:
        self._building = building
        self._belt = None
        self._belt_net = None
        self._begin_open()

    def open_belt(self, belt: ConveyorBelt, net: BeltNetworkSoA | None) -> None:
        self._belt = belt
        self._belt_net = net
        self._building = None
        self._begin_open()

    def close(self) -> None:
        if not self._is_open:
            return
        self._closing = True
        self._x_tween = Tween(
            start=self._current_x(),
            end=float(self._offscreen_x),
            duration=THEME.anim.base,
            ease=THEME.anim.ease_out,
        )

    def _begin_open(self) -> None:
        already_open = self._is_open and not self._closing
        self._is_open = True
        self._closing = False
        self._progress_anim.set(0.0)
        self._port_anims.clear()
        if already_open:
            self._x_tween = Tween(
                start=self._current_x(),
                end=float(self._final_x),
                duration=THEME.anim.base,
                ease=THEME.anim.ease_out,
            )
            # Brief pop on re-open
            self._x_tween.elapsed = 0.0
        else:
            self._x_tween = Tween(
                start=float(self._offscreen_x),
                end=float(self._final_x),
                duration=THEME.anim.slow,
                ease=THEME.anim.ease_out,
            )

    # -- events ------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True when the event was consumed by the menu."""
        if not self._is_open:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return True
        return False

    # -- update ------------------------------------------------------------

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_released: bool,
    ) -> None:
        self._time += dt
        # Slide animation
        x = self._x_tween.update(dt)
        if self._closing and self._x_tween.done:
            self._is_open = False
            self._closing = False
            self._building = None
            self._belt = None
            self._belt_net = None
            self._info = None
            return
        if not self._is_open:
            return

        # Pull fresh info from the live simulation.
        self._info = self._compute_info()

        # Progress bar lerp
        target_progress = self._info.progress if self._info and self._info.progress is not None else 0.0
        self._progress_anim.to(float(target_progress))
        self._progress_anim.update(dt)

        # Per-port fill lerps
        if self._info is not None:
            for i, pinfo in enumerate(self._info.port_rows):
                a = self._port_anims.get(i)
                if a is None:
                    a = AnimValue(value=pinfo.fill, target=pinfo.fill, speed=14.0)
                    self._port_anims[i] = a
                a.to(pinfo.fill)
                a.update(dt)

        # Close button widget (positioned relative to the live panel rect)
        pr = pygame.Rect(int(x), self._y, _PANEL_W, _PANEL_H)
        self._close_btn.rect.topleft = (
            pr.right - _PAD - _CLOSE_SIZE,
            pr.top + _PAD // 2,
        )
        self._close_btn.update(dt, mouse_pos, mouse_down)
        if self._close_btn.clicked(mouse_released):
            self.close()

    def _compute_info(self) -> StructureInfo | None:
        if self._building is not None:
            return for_building(self._building)
        if self._belt is not None:
            return for_belt(self._belt, self._belt_net)
        return None

    def _current_x(self) -> float:
        if self._x_tween.done:
            return float(self._x_tween.end)
        # Re-evaluate tween value without advancing time.
        if self._x_tween.duration <= 0:
            return float(self._x_tween.end)
        t = self._x_tween.ease(
            min(1.0, self._x_tween.elapsed / self._x_tween.duration)
        )
        return self._x_tween.start + (self._x_tween.end - self._x_tween.start) * t

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        if not self._is_open:
            return
        info = self._info
        if info is None:
            return

        x = int(self._current_x())
        rect = pygame.Rect(x, self._y, _PANEL_W, _PANEL_H)

        # Open progress in [0,1] used for an overall reveal alpha.
        span = float(self._offscreen_x - self._final_x)
        reveal = 1.0 if span <= 0 else max(
            0.0,
            min(1.0, 1.0 - (x - self._final_x) / span),
        )
        reveal = max(0.05, reveal)

        # Drop shadow first
        with acquired((rect.w + 12, rect.h + 12)) as shadow:
            shadow.fill(with_alpha(PALETTE.bg_deep, int(_SHADOW_ALPHA * reveal)))
            surface.blit(shadow, (rect.x - 4, rect.y + 6))

        # Panel body
        beveled_panel(surface, rect, fill=PALETTE.bg_base, border=PALETTE.line)

        # Left accent stripe
        stripe = pygame.Rect(rect.x, rect.y + 2, 3, rect.h - 4)
        pygame.draw.rect(surface, info.accent, stripe)

        cursor_y = rect.y + _PAD
        cursor_y = self._render_header(surface, rect, cursor_y, info)
        cursor_y = self._render_divider(surface, rect, cursor_y)

        if info.rate_rows:
            cursor_y = self._render_section_label(surface, rect, cursor_y, "THROUGHPUT")
            cursor_y = self._render_rate_rows(surface, rect, cursor_y, info)
            cursor_y += _SECTION_GAP

        if info.port_rows:
            cursor_y = self._render_divider(surface, rect, cursor_y)
            cursor_y = self._render_section_label(surface, rect, cursor_y, "PORTS")
            cursor_y = self._render_port_rows(surface, rect, cursor_y, info)
            cursor_y += _SECTION_GAP

        if info.progress is not None:
            cursor_y = self._render_divider(surface, rect, cursor_y)
            cursor_y = self._render_section_label(surface, rect, cursor_y, "PROGRESS")
            cursor_y = self._render_progress(surface, rect, cursor_y, info)

        self._render_close_button(surface)

    # -- sections ----------------------------------------------------------

    def _render_header(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        info: StructureInfo,
    ) -> int:
        # Icon box
        icon_box = pygame.Rect(rect.x + _PAD, y, 44, 44)
        beveled_panel(surface, icon_box, fill=darken(PALETTE.bg_raised, 0.15), border=PALETTE.line)
        # Item chip or structure silhouette
        if info.primary_item is not None:
            inner = icon_box.inflate(-14, -14)
            pygame.draw.rect(surface, info.primary_item.color, inner)
            pygame.draw.rect(surface, lighten(info.primary_item.color, 0.25), inner, 1)
        else:
            arrow = [
                (icon_box.centerx - 10, icon_box.centery),
                (icon_box.centerx + 10, icon_box.centery),
            ]
            pygame.draw.line(surface, info.accent, arrow[0], arrow[1], 4)
            pygame.draw.polygon(
                surface,
                info.accent,
                [
                    (arrow[1][0] + 6, icon_box.centery),
                    (arrow[1][0] - 2, icon_box.centery - 6),
                    (arrow[1][0] - 2, icon_box.centery + 6),
                ],
            )

        tx = icon_box.right + THEME.spacing.md
        title = self.assets.render_text(info.title, TYPE.h1, PALETTE.text_strong)
        surface.blit(title, (tx, y - 2))
        subtitle = self.assets.render_text(info.subtitle, TYPE.caption, PALETTE.muted)
        surface.blit(subtitle, (tx, y + title.get_height()))

        return y + icon_box.h + THEME.spacing.md

    def _render_divider(self, surface: pygame.Surface, rect: pygame.Rect, y: int) -> int:
        pygame.draw.line(
            surface,
            PALETTE.line,
            (rect.x + _PAD, y),
            (rect.right - _PAD, y),
        )
        return y + THEME.spacing.sm

    def _render_section_label(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        text: str,
    ) -> int:
        surf = self.assets.render_text(text, TYPE.label, PALETTE.muted)
        surface.blit(surf, (rect.x + _PAD, y))
        return y + surf.get_height() + THEME.spacing.xs

    def _render_rate_rows(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        info: StructureInfo,
    ) -> int:
        for row in info.rate_rows:
            chip_x = rect.x + _PAD
            row_mid_y = y + _ROW_H // 2
            if row.item is not None:
                chip = pygame.Rect(chip_x, row_mid_y - 5, 10, 10)
                pygame.draw.rect(surface, row.item.color, chip)
                pygame.draw.rect(surface, lighten(row.item.color, 0.25), chip, 1)
                label_x = chip_x + 14
            else:
                label_x = chip_x
            label_surf = self.assets.render_text(row.label, TYPE.body, PALETTE.text_body)
            surface.blit(
                label_surf,
                (label_x, row_mid_y - label_surf.get_height() // 2),
            )
            value_color = row.accent if row.accent is not None else PALETTE.text_strong
            value_surf = self.assets.render_text(row.value, TYPE.body, value_color)
            surface.blit(
                value_surf,
                (
                    rect.right - _PAD - value_surf.get_width(),
                    row_mid_y - value_surf.get_height() // 2,
                ),
            )
            y += _ROW_H
        return y

    def _render_port_rows(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        info: StructureInfo,
    ) -> int:
        for i, port in enumerate(info.port_rows):
            y = self._render_port_row(surface, rect, y, port, i)
        return y

    def _render_port_row(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        port: PortInfo,
        index: int,
    ) -> int:
        kind_label = "IN " if port.kind.value == "input" else "OUT"
        kind_color = PALETTE.secondary if port.kind.value == "input" else PALETTE.primary
        kind_surf = self.assets.render_text(kind_label, TYPE.label, kind_color)
        surface.blit(kind_surf, (rect.x + _PAD, y + 2))

        name = port.item.name if port.item is not None else "any"
        name_surf = self.assets.render_text(name, TYPE.caption, PALETTE.text_body)
        surface.blit(name_surf, (rect.x + _PAD + kind_surf.get_width() + 8, y + 2))

        count_text = f"{port.count}/{port.capacity}"
        full = port.is_full
        count_color = PALETTE.warning if full else PALETTE.text_strong
        count_surf = self.assets.render_text(count_text, TYPE.caption, count_color)
        surface.blit(
            count_surf,
            (
                rect.right - _PAD - count_surf.get_width(),
                y + 2,
            ),
        )

        # Bar
        bar_y = y + kind_surf.get_height() + 6
        bar_rect = pygame.Rect(rect.x + _PAD, bar_y, rect.w - _PAD * 2, _PORT_BAR_H)
        pygame.draw.rect(surface, darken(PALETTE.bg_raised, 0.3), bar_rect)
        pygame.draw.rect(surface, PALETTE.line, bar_rect, 1)

        fill = self._port_anims.get(index)
        fill_frac = fill.value if fill is not None else port.fill
        fill_w = int((bar_rect.w - 2) * max(0.0, min(1.0, fill_frac)))
        if fill_w > 0:
            inner = pygame.Rect(bar_rect.x + 1, bar_rect.y + 1, fill_w, bar_rect.h - 2)
            bar_color = port.item.color if port.item is not None else kind_color
            if full:
                pulse = 0.5 + 0.5 * math.sin(self._time * 6.0)
                bar_color = lighten(PALETTE.warning, 0.15 * pulse)
            pygame.draw.rect(surface, bar_color, inner)
            pygame.draw.rect(
                surface,
                lighten(bar_color, 0.3),
                pygame.Rect(inner.x, inner.y, inner.w, 1),
            )

        return bar_y + _PORT_BAR_H + THEME.spacing.sm

    def _render_progress(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        info: StructureInfo,
    ) -> int:
        label = info.progress_label or ""
        label_surf = self.assets.render_text(label, TYPE.caption, PALETTE.text_body)
        surface.blit(label_surf, (rect.x + _PAD, y))

        pct_text = f"{int(self._progress_anim.value * 100)}%"
        pct_surf = self.assets.render_text(pct_text, TYPE.body, PALETTE.text_strong)
        surface.blit(
            pct_surf,
            (
                rect.right - _PAD - pct_surf.get_width(),
                y - 2,
            ),
        )

        bar_y = y + label_surf.get_height() + 6
        bar_rect = pygame.Rect(rect.x + _PAD, bar_y, rect.w - _PAD * 2, 14)
        pygame.draw.rect(surface, darken(PALETTE.bg_raised, 0.35), bar_rect)
        pygame.draw.rect(surface, PALETTE.line, bar_rect, 1)

        frac = max(0.0, min(1.0, self._progress_anim.value))
        fill_w = int((bar_rect.w - 2) * frac)
        if fill_w > 0:
            inner = pygame.Rect(bar_rect.x + 1, bar_rect.y + 1, fill_w, bar_rect.h - 2)
            pygame.draw.rect(surface, PALETTE.primary, inner)
            pygame.draw.rect(
                surface,
                lighten(PALETTE.primary, 0.35),
                pygame.Rect(inner.x, inner.y, inner.w, 2),
            )
            # Scanline accent
            sheen_x = inner.x + int(
                (math.sin(self._time * 3.0) * 0.5 + 0.5) * max(0, inner.w - 6)
            )
            pygame.draw.line(
                surface,
                with_alpha(PALETTE.text_strong, 120),
                (sheen_x, inner.y),
                (sheen_x, inner.bottom - 1),
                2,
            )

        return bar_y + bar_rect.h + THEME.spacing.sm

    # -- close button ------------------------------------------------------

    def _render_close_button(self, surface: pygame.Surface) -> None:
        r = self._close_btn.rect
        hover = self._close_btn.hover_anim.value
        press = self._close_btn.press_anim.value
        bg = lighten(PALETTE.bg_raised, 0.1 * hover) if hover > 0 else PALETTE.bg_raised
        beveled_panel(surface, r, fill=bg, border=PALETTE.line)
        tint = lighten(PALETTE.danger, 0.2 * hover) if hover > 0 else PALETTE.text_body
        inset = 6 + int(press * 2)
        pygame.draw.line(
            surface, tint, (r.x + inset, r.y + inset), (r.right - inset, r.bottom - inset), 2
        )
        pygame.draw.line(
            surface, tint, (r.right - inset, r.y + inset), (r.x + inset, r.bottom - inset), 2
        )
