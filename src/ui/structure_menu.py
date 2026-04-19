"""Selected-structure menu: slide-in detail panel on the right.

Opens when the player clicks an existing building. Pulls fresh numbers
from the live simulation every frame (port counts, craft progress) via
``ui.info``, so no events or caching are required.

The menu is organised around a top-down **hero diagram** of the
building. Ports are rendered spatially on the correct side of the
correct cell, with callout cards flanking the diagram on the edges
that host ports. Hovering a port marker emits a
:class:`StructureMenu.WorldHighlight` the play scene renders as
coloured corner brackets over the actual world cell.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from ..world.direction import Direction
from ..world.tile import Coord
from .info import InfoRow, PortInfo, StructureInfo, for_belt, for_building
from .structure_diagram import (
    PORT_MARKER,
    PortHit,
    diagram_size,
    draw_diagram,
    layout_diagram,
)
from .widget import Widget

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..belts.belt import ConveyorBelt
    from ..belts.network_soa import BeltNetworkSoA
    from ..buildings.building import Building


_PANEL_W = 600
_MIN_PANEL_H = 320
_MARGIN = 160
_MIN_MARGIN = 16
_PAD = THEME.spacing.lg
_SECTION_GAP = THEME.spacing.md

_HEADER_H = 52
_CALLOUT_W = 136
_CALLOUT_H = 56
_CALLOUT_GAP = THEME.spacing.sm
_RATE_ROW_H = 24
_PROGRESS_ROW_H = 44
_CLOSE_SIZE = 24
_SHADOW_ALPHA = 150


@dataclass(frozen=True)
class WorldHighlight:
    """Highlight a single world cell (usually originated by port hover)."""

    cell: Coord
    footprint: tuple[int, int]
    accent: tuple[int, int, int]


# Per-section reveal phases (start, end) within ``self._reveal_anim.value``.
_PHASES: dict[str, tuple[float, float]] = {
    "header": (0.00, 0.30),
    "diagram": (0.15, 0.55),
    "callouts": (0.25, 0.65),
    "throughput": (0.40, 0.80),
    "progress": (0.55, 1.00),
}


def _phase_progress(reveal: float, key: str) -> float:
    start, end = _PHASES[key]
    if end <= start:
        return 1.0
    return max(0.0, min(1.0, (reveal - start) / (end - start)))


class StructureMenu:
    """Right-anchored detail panel, slides in with an ease-out tween."""

    WorldHighlight = WorldHighlight  # re-expose for consumers

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self._building: Building | None = None
        self._belt: ConveyorBelt | None = None
        self._belt_net: BeltNetworkSoA | None = None
        self._info: StructureInfo | None = None
        self._window_size: tuple[int, int] = (0, 0)
        self._final_x: int = 0
        self._offscreen_x: int = 0
        self._x_tween: Tween = Tween(
            start=0.0, end=0.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out
        )
        self._x_tween.done = True
        self._is_open: bool = False
        self._closing: bool = False

        self._panel_h_anim = AnimValue(
            value=float(_MIN_PANEL_H), target=float(_MIN_PANEL_H), speed=14.0
        )
        self._y_anim = AnimValue(value=0.0, target=0.0, speed=14.0)
        self._reveal_anim = AnimValue(value=0.0, target=0.0, speed=6.5)

        self._progress_anim = AnimValue(value=0.0, target=0.0, speed=10.0)
        self._port_anims: dict[int, AnimValue] = {}
        self._time: float = 0.0

        self._port_hits: tuple[PortHit, ...] = ()
        self._hovered_port_index: int | None = None
        self._world_highlight: WorldHighlight | None = None

        self._close_btn = Widget(pygame.Rect(0, 0, _CLOSE_SIZE, _CLOSE_SIZE))

    # -- layout ------------------------------------------------------------

    def layout(self, window_size: tuple[int, int]) -> None:
        self._window_size = window_size
        w, _h = window_size
        margin = min(_MARGIN, max(_MIN_MARGIN, (w - _PANEL_W) // 2))
        self._final_x = max(_MIN_MARGIN, w - _PANEL_W - margin)
        self._offscreen_x = w + 8
        self._retarget_y()
        if self._is_open and not self._closing:
            self._x_tween = Tween(
                start=self._current_x(),
                end=float(self._final_x),
                duration=THEME.anim.base,
                ease=THEME.anim.ease_out,
            )

    def _retarget_y(self) -> None:
        _, wh = self._window_size
        if wh <= 0:
            return
        hud_bottom = 16 + 48 + 8
        toolbar_top = wh - (64 + 12 * 2 + 16)
        panel_h = self._panel_h_anim.target
        usable_h = max(panel_h, toolbar_top - hud_bottom)
        target_y = hud_bottom + max(0, (usable_h - panel_h) / 2)
        self._y_anim.to(float(target_y))

    # -- API ---------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._is_open

    def rect(self) -> pygame.Rect | None:
        if not self._is_open:
            return None
        return pygame.Rect(
            int(self._current_x()),
            int(self._y_anim.value),
            _PANEL_W,
            int(self._panel_h_anim.value),
        )

    def world_highlight(self) -> WorldHighlight | None:
        if not self._is_open:
            return None
        return self._world_highlight

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
        self._reveal_anim.to(0.0)
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
        self._port_hits = ()
        self._hovered_port_index = None
        self._world_highlight = None
        self._reveal_anim.set(0.0)
        self._reveal_anim.to(1.0)
        if already_open:
            self._x_tween = Tween(
                start=self._current_x(),
                end=float(self._final_x),
                duration=THEME.anim.base,
                ease=THEME.anim.ease_out,
            )
        else:
            self._x_tween = Tween(
                start=float(self._offscreen_x),
                end=float(self._final_x),
                duration=THEME.anim.slow,
                ease=THEME.anim.ease_out,
            )

    # -- events ------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
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
        self._x_tween.update(dt)
        self._reveal_anim.update(dt)

        if self._closing and self._x_tween.done:
            self._is_open = False
            self._closing = False
            self._building = None
            self._belt = None
            self._belt_net = None
            self._info = None
            self._port_hits = ()
            self._hovered_port_index = None
            self._world_highlight = None
            return
        if not self._is_open:
            return

        self._info = self._compute_info()

        # Target height from content; tween toward it so re-selects morph.
        target_h = float(self._measure_panel_height(self._info))
        self._panel_h_anim.to(target_h)
        self._panel_h_anim.update(dt)
        self._retarget_y()
        self._y_anim.update(dt)

        target_progress = (
            self._info.progress
            if self._info is not None and self._info.progress is not None
            else 0.0
        )
        self._progress_anim.to(float(target_progress))
        self._progress_anim.update(dt)

        if self._info is not None:
            for pinfo in self._info.port_rows:
                a = self._port_anims.get(pinfo.index)
                if a is None:
                    a = AnimValue(value=pinfo.fill, target=pinfo.fill, speed=14.0)
                    self._port_anims[pinfo.index] = a
                a.to(pinfo.fill)
                a.update(dt)

        panel_rect = self.rect()
        if panel_rect is None or self._info is None:
            self._hovered_port_index = None
            self._world_highlight = None
            return

        # Compute diagram hit rects from current layout (pure math,
        # no drawing).
        diag_center = self._diagram_center(panel_rect, self._info)
        _, self._port_hits = layout_diagram(diag_center, self._info)

        # Port hover hit-test (uses the inflated hit_rect so hovering
        # the marker is forgiving even though the visual stays crisp).
        self._hovered_port_index = None
        for hit in self._port_hits:
            if hit.hit_rect.collidepoint(mouse_pos):
                self._hovered_port_index = hit.index
                break

        self._world_highlight = self._compute_world_highlight()

        # Close button position.
        self._close_btn.rect.topleft = (
            panel_rect.right - _PAD - _CLOSE_SIZE,
            panel_rect.top + (_HEADER_H - _CLOSE_SIZE) // 2 + 4,
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

    def _compute_world_highlight(self) -> WorldHighlight | None:
        idx = self._hovered_port_index
        if idx is None or self._info is None or self._building is None:
            return None
        port = next(
            (p for p in self._info.port_rows if p.index == idx), None
        )
        if port is None:
            return None
        ox, oy = self._building.origin
        cx, cy = port.cell_offset
        accent = port.item.color if port.item is not None else self._info.accent
        return WorldHighlight(cell=(ox + cx, oy + cy), footprint=(1, 1), accent=accent)

    def _current_x(self) -> float:
        if self._x_tween.done:
            return float(self._x_tween.end)
        if self._x_tween.duration <= 0:
            return float(self._x_tween.end)
        t = self._x_tween.ease(
            min(1.0, self._x_tween.elapsed / self._x_tween.duration)
        )
        return self._x_tween.start + (self._x_tween.end - self._x_tween.start) * t

    # -- measurement -------------------------------------------------------

    def _measure_panel_height(self, info: StructureInfo | None) -> int:
        if info is None:
            return _MIN_PANEL_H
        h = _PAD
        h += _HEADER_H
        h += THEME.spacing.sm  # divider + gap
        h += self._hero_band_height(info)
        h += THEME.spacing.sm

        if info.rate_rows:
            h += self._section_label_h() + THEME.spacing.xs
            h += _RATE_ROW_H * len(info.rate_rows)
            h += _SECTION_GAP
            h += THEME.spacing.sm  # divider

        if info.progress is not None:
            h += self._section_label_h() + THEME.spacing.xs
            h += _PROGRESS_ROW_H
            h += _SECTION_GAP

        h += _PAD
        return max(_MIN_PANEL_H, h)

    def _section_label_h(self) -> int:
        surf = self.assets.render_text("A", TYPE.label, PALETTE.muted)
        return surf.get_height()

    def _hero_band_height(self, info: StructureInfo) -> int:
        _diag_w, diag_h = diagram_size(info)
        col_h = self._callout_column_height(info)
        return max(diag_h, col_h) + THEME.spacing.sm

    def _callout_column_height(self, info: StructureInfo) -> int:
        left = sum(1 for p in info.port_rows if p.side is Direction.W)
        right = sum(1 for p in info.port_rows if p.side is Direction.E)
        top = sum(1 for p in info.port_rows if p.side is Direction.N)
        bottom = sum(1 for p in info.port_rows if p.side is Direction.S)
        vertical_max = max(left, right)
        h_main = vertical_max * (_CALLOUT_H + _CALLOUT_GAP) - _CALLOUT_GAP if vertical_max > 0 else 0
        if top > 0 or bottom > 0:
            h_main += (_CALLOUT_H + _CALLOUT_GAP)
        return max(h_main, 0)

    def _diagram_center(
        self, panel_rect: pygame.Rect, info: StructureInfo
    ) -> tuple[int, int]:
        band_top = panel_rect.top + _PAD + _HEADER_H + THEME.spacing.sm
        band_h = self._hero_band_height(info)
        return (panel_rect.centerx, band_top + band_h // 2)

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        if not self._is_open:
            return
        info = self._info
        if info is None:
            return

        x = int(self._current_x())
        y = int(self._y_anim.value)
        panel_h = int(self._panel_h_anim.value)
        rect = pygame.Rect(x, y, _PANEL_W, panel_h)

        span = float(self._offscreen_x - self._final_x)
        slide_reveal = 1.0 if span <= 0 else max(
            0.0,
            min(1.0, 1.0 - (x - self._final_x) / span),
        )
        slide_reveal = max(0.05, slide_reveal)

        with acquired((rect.w + 12, rect.h + 12)) as shadow:
            shadow.fill(with_alpha(PALETTE.bg_deep, int(_SHADOW_ALPHA * slide_reveal)))
            surface.blit(shadow, (rect.x - 4, rect.y + 6))

        beveled_panel(surface, rect, fill=PALETTE.bg_base, border=PALETTE.line)

        stripe = pygame.Rect(rect.x, rect.y + 2, 3, rect.h - 4)
        pygame.draw.rect(surface, info.accent, stripe)

        reveal = max(0.0, min(1.0, self._reveal_anim.value))

        cursor_y = rect.y + _PAD
        cursor_y = self._render_header(surface, rect, cursor_y, info, reveal)
        cursor_y = self._render_divider(surface, rect, cursor_y)
        cursor_y = self._render_hero_band(surface, rect, cursor_y, info, reveal)
        cursor_y += THEME.spacing.sm

        if info.rate_rows:
            cursor_y = self._render_divider(surface, rect, cursor_y)
            cursor_y = self._render_rate_section(surface, rect, cursor_y, info, reveal)

        if info.progress is not None:
            cursor_y = self._render_divider(surface, rect, cursor_y)
            cursor_y = self._render_progress_section(
                surface, rect, cursor_y, info, reveal
            )

        self._render_close_button(surface, reveal)

    # -- sections ----------------------------------------------------------

    def _blit_with_reveal(
        self,
        surface: pygame.Surface,
        src: pygame.Surface,
        pos: tuple[int, int],
        phase: float,
    ) -> None:
        if phase <= 0.005:
            return
        offset = int((1.0 - phase) * 6)
        if phase >= 0.995:
            surface.blit(src, (pos[0], pos[1] + offset))
            return
        with acquired(src.get_size()) as staged:
            staged.blit(src, (0, 0))
            staged.set_alpha(int(255 * phase))
            surface.blit(staged, (pos[0], pos[1] + offset))

    def _render_header(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        info: StructureInfo,
        reveal: float,
    ) -> int:
        phase = _phase_progress(reveal, "header")
        icon_box = pygame.Rect(rect.x + _PAD, y, 44, 44)
        beveled_panel(
            surface,
            icon_box,
            fill=darken(PALETTE.bg_raised, 0.15),
            border=PALETTE.line,
        )

        icon_sprite = self._safe_item_sprite(info.primary_item.id if info.primary_item else None)
        if icon_sprite is not None:
            inner = icon_box.inflate(-10, -10)
            scaled = pygame.transform.smoothscale(icon_sprite, (inner.w, inner.h))
            surface.blit(scaled, inner.topleft)
        elif info.primary_item is not None:
            inner = icon_box.inflate(-14, -14)
            pygame.draw.rect(surface, info.primary_item.color, inner)
            pygame.draw.rect(surface, lighten(info.primary_item.color, 0.25), inner, 1)
        else:
            arrow_y = icon_box.centery
            pygame.draw.line(
                surface,
                info.accent,
                (icon_box.centerx - 10, arrow_y),
                (icon_box.centerx + 10, arrow_y),
                4,
            )
            pygame.draw.polygon(
                surface,
                info.accent,
                [
                    (icon_box.centerx + 16, arrow_y),
                    (icon_box.centerx + 8, arrow_y - 6),
                    (icon_box.centerx + 8, arrow_y + 6),
                ],
            )

        tx = icon_box.right + THEME.spacing.md
        title_max_w = max(64, rect.right - _PAD - _CLOSE_SIZE - THEME.spacing.sm - tx)
        title_full = self.assets.render_text(info.title, TYPE.h1, PALETTE.text_strong)
        title = (
            title_full.subsurface(
                pygame.Rect(0, 0, min(title_full.get_width(), title_max_w), title_full.get_height())
            )
            if title_full.get_width() > title_max_w
            else title_full
        )
        subtitle = self.assets.render_text(info.subtitle, TYPE.caption, PALETTE.muted)
        self._blit_with_reveal(surface, title, (tx, y - 2), phase)
        self._blit_with_reveal(
            surface, subtitle, (tx, y + title.get_height()), phase
        )

        return y + _HEADER_H - _PAD  # header band height minus the outer pad

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
        phase: float,
    ) -> int:
        surf = self.assets.render_text(text, TYPE.label, PALETTE.muted)
        self._blit_with_reveal(surface, surf, (rect.x + _PAD, y), phase)
        return y + surf.get_height() + THEME.spacing.xs

    # -- hero band ---------------------------------------------------------

    def _render_hero_band(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        info: StructureInfo,
        reveal: float,
    ) -> int:
        band_h = self._hero_band_height(info)
        band_phase = _phase_progress(reveal, "diagram")
        callout_phase = _phase_progress(reveal, "callouts")

        diag_center = (rect.centerx, y + band_h // 2)
        port_fill = {idx: a.value for idx, a in self._port_anims.items()}

        # Render the diagram off-screen first so we can fade it.
        diag_w, diag_h = diagram_size(info)
        with acquired((diag_w + 4, diag_h + 4)) as diag_layer:
            inner_center = (diag_w // 2 + 2, diag_h // 2 + 2)
            draw_diagram(
                diag_layer,
                inner_center,
                info,
                self.assets,
                time=self._time,
                port_fill=port_fill,
                hovered_index=self._hovered_port_index,
            )
            diag_layer.set_alpha(int(255 * band_phase))
            diag_pos = (
                diag_center[0] - (diag_w // 2 + 2),
                diag_center[1] - (diag_h // 2 + 2),
            )
            offset = int((1.0 - band_phase) * 6)
            surface.blit(diag_layer, (diag_pos[0], diag_pos[1] + offset))

        # Recompute hit rects (should match what layout_diagram uses).
        _, hits = layout_diagram(diag_center, info)
        hits_by_index = {h.index: h for h in hits}

        # Layout callout columns.
        left_ports = [p for p in info.port_rows if p.side is Direction.W]
        right_ports = [p for p in info.port_rows if p.side is Direction.E]
        top_ports = [p for p in info.port_rows if p.side is Direction.N]
        bottom_ports = [p for p in info.port_rows if p.side is Direction.S]

        col_h_left = (
            len(left_ports) * (_CALLOUT_H + _CALLOUT_GAP) - _CALLOUT_GAP
            if left_ports else 0
        )
        col_h_right = (
            len(right_ports) * (_CALLOUT_H + _CALLOUT_GAP) - _CALLOUT_GAP
            if right_ports else 0
        )

        left_x = rect.x + _PAD
        right_x = rect.right - _PAD - _CALLOUT_W

        left_y0 = y + (band_h - col_h_left) // 2
        right_y0 = y + (band_h - col_h_right) // 2

        for i, port in enumerate(left_ports):
            cy = left_y0 + i * (_CALLOUT_H + _CALLOUT_GAP)
            callout_rect = pygame.Rect(left_x, cy, _CALLOUT_W, _CALLOUT_H)
            self._render_callout(
                surface, callout_rect, port, anchor_side="right",
                hit=hits_by_index.get(port.index), phase=callout_phase,
            )

        for i, port in enumerate(right_ports):
            cy = right_y0 + i * (_CALLOUT_H + _CALLOUT_GAP)
            callout_rect = pygame.Rect(right_x, cy, _CALLOUT_W, _CALLOUT_H)
            self._render_callout(
                surface, callout_rect, port, anchor_side="left",
                hit=hits_by_index.get(port.index), phase=callout_phase,
            )

        # Top/bottom ports use a wider horizontal pill to avoid covering
        # the diagram and are stacked centrally above/below.
        for i, port in enumerate(top_ports):
            cw = min(_CALLOUT_W * 2, rect.w - _PAD * 2)
            cx = rect.centerx - cw // 2
            cy = y + i * (_CALLOUT_H + _CALLOUT_GAP)
            callout_rect = pygame.Rect(cx, cy, cw, _CALLOUT_H)
            self._render_callout(
                surface, callout_rect, port, anchor_side="bottom",
                hit=hits_by_index.get(port.index), phase=callout_phase,
            )
        for i, port in enumerate(bottom_ports):
            cw = min(_CALLOUT_W * 2, rect.w - _PAD * 2)
            cx = rect.centerx - cw // 2
            cy = y + band_h - _CALLOUT_H - i * (_CALLOUT_H + _CALLOUT_GAP)
            callout_rect = pygame.Rect(cx, cy, cw, _CALLOUT_H)
            self._render_callout(
                surface, callout_rect, port, anchor_side="top",
                hit=hits_by_index.get(port.index), phase=callout_phase,
            )

        return y + band_h + THEME.spacing.sm

    def _render_callout(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        port: PortInfo,
        *,
        anchor_side: str,
        hit: PortHit | None,
        phase: float,
    ) -> None:
        if phase <= 0.01:
            return
        item_color = port.item.color if port.item is not None else (
            PALETTE.secondary if port.kind.value == "input" else PALETTE.primary
        )

        # Connector line from the callout edge to the port marker.
        if hit is not None:
            self._draw_connector(surface, rect, hit, anchor_side, item_color, phase)

        with acquired(rect.size) as panel:
            inner = pygame.Rect(0, 0, rect.w, rect.h)
            beveled_panel(
                panel, inner,
                fill=darken(PALETTE.bg_raised, 0.1),
                border=PALETTE.line,
            )
            # Accent stripe: left for right-anchored, right for left-anchored.
            stripe_color = PALETTE.secondary if port.kind.value == "input" else PALETTE.primary
            if anchor_side == "left":
                stripe = pygame.Rect(0, 2, 3, rect.h - 4)
            elif anchor_side == "right":
                stripe = pygame.Rect(rect.w - 3, 2, 3, rect.h - 4)
            elif anchor_side == "top":
                stripe = pygame.Rect(2, 0, rect.w - 4, 3)
            else:
                stripe = pygame.Rect(2, rect.h - 3, rect.w - 4, 3)
            pygame.draw.rect(panel, stripe_color, stripe)

            # Top row: sprite + name
            px = THEME.spacing.sm + (3 if anchor_side == "right" else 0)
            py = 4
            sprite_surf = self._safe_item_sprite(port.item.id if port.item else None)
            if sprite_surf is not None:
                icon_size = 16
                scaled = pygame.transform.smoothscale(
                    sprite_surf, (icon_size, icon_size)
                )
                panel.blit(scaled, (px, py))
                px += icon_size + 4
            elif port.item is not None:
                chip = pygame.Rect(px, py + 2, 12, 12)
                pygame.draw.rect(panel, item_color, chip)
                pygame.draw.rect(panel, lighten(item_color, 0.25), chip, 1)
                px += 16

            name = port.item.name if port.item is not None else "any"
            name_surf = self.assets.render_text(
                name, TYPE.caption, PALETTE.text_strong
            )
            # Clip if needed
            max_name_w = rect.w - px - THEME.spacing.sm
            if name_surf.get_width() > max_name_w > 0:
                name_surf = name_surf.subsurface(
                    pygame.Rect(0, 0, max_name_w, name_surf.get_height())
                )
            panel.blit(name_surf, (px, py + 1))

            # Bottom row: count / capacity + fill bar
            count_text = f"{port.count}/{port.capacity}"
            count_color = PALETTE.warning if port.is_full else PALETTE.text_body
            count_surf = self.assets.render_text(
                count_text, TYPE.body, count_color
            )
            count_x = rect.w - THEME.spacing.sm - count_surf.get_width()
            count_y = py + name_surf.get_height() + 4
            panel.blit(count_surf, (count_x, count_y))

            kind_label = "IN" if port.kind.value == "input" else "OUT"
            kind_surf = self.assets.render_text(
                kind_label, TYPE.label, PALETTE.muted
            )
            panel.blit(kind_surf, (THEME.spacing.sm + (3 if anchor_side == "right" else 0), count_y + 3))

            # Fill bar spanning the card width.
            bar_h = 3
            bar_rect = pygame.Rect(
                THEME.spacing.sm,
                rect.h - bar_h - 3,
                rect.w - THEME.spacing.sm * 2,
                bar_h,
            )
            pygame.draw.rect(panel, darken(PALETTE.bg_raised, 0.3), bar_rect)
            anim = self._port_anims.get(port.index)
            fill_frac = anim.value if anim is not None else port.fill
            fill_w = int((bar_rect.w - 2) * max(0.0, min(1.0, fill_frac)))
            if fill_w > 0:
                inner_bar = pygame.Rect(
                    bar_rect.x + 1, bar_rect.y + 1, fill_w, bar_rect.h - 2
                )
                bar_color = item_color
                if port.is_full:
                    pulse = 0.5 + 0.5 * math.sin(self._time * 6.0)
                    bar_color = lighten(PALETTE.warning, 0.15 * pulse)
                pygame.draw.rect(panel, bar_color, inner_bar)

            offset_y = int((1.0 - phase) * 6)
            panel.set_alpha(int(255 * phase))
            surface.blit(panel, (rect.x, rect.y + offset_y))

    def _draw_connector(
        self,
        surface: pygame.Surface,
        callout: pygame.Rect,
        hit: PortHit,
        anchor_side: str,
        color: tuple[int, int, int],
        phase: float,
    ) -> None:
        if phase <= 0.1:
            return
        if anchor_side == "left":
            start = (callout.left, callout.centery)
        elif anchor_side == "right":
            start = (callout.right, callout.centery)
        elif anchor_side == "top":
            start = (callout.centerx, callout.top)
        else:
            start = (callout.centerx, callout.bottom)
        end = (
            hit.rect.centerx + (-PORT_MARKER // 2 if anchor_side == "left" else
                                PORT_MARKER // 2 if anchor_side == "right" else 0),
            hit.rect.centery + (-PORT_MARKER // 2 if anchor_side == "top" else
                                PORT_MARKER // 2 if anchor_side == "bottom" else 0),
        )

        alpha = int(150 * phase)
        line_c = with_alpha(color, alpha)
        mid = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
        if anchor_side in ("left", "right"):
            mid = (mid[0], start[1])
        else:
            mid = (start[0], mid[1])
        # two-segment polyline
        seg_surface_size = (
            max(abs(start[0] - end[0]), 2) + 8,
            max(abs(start[1] - end[1]), 2) + 8,
        )
        if seg_surface_size[0] <= 0 or seg_surface_size[1] <= 0:
            return
        with acquired(seg_surface_size) as layer:
            ox = min(start[0], end[0]) - 4
            oy = min(start[1], end[1]) - 4
            s = (start[0] - ox, start[1] - oy)
            m = (mid[0] - ox, mid[1] - oy)
            e = (end[0] - ox, end[1] - oy)
            pygame.draw.aaline(layer, line_c, s, m)
            pygame.draw.aaline(layer, line_c, m, e)
            surface.blit(layer, (ox, oy))

    # -- rate rows ---------------------------------------------------------

    def _render_rate_section(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        info: StructureInfo,
        reveal: float,
    ) -> int:
        phase = _phase_progress(reveal, "throughput")
        y = self._render_section_label(surface, rect, y, "THROUGHPUT", phase)
        for row in info.rate_rows:
            y = self._render_rate_row(surface, rect, y, row, phase)
        return y + _SECTION_GAP

    def _render_rate_row(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        row: InfoRow,
        phase: float,
    ) -> int:
        row_mid_y = y + _RATE_ROW_H // 2
        chip_x = rect.x + _PAD
        sprite_surf = self._safe_item_sprite(row.item.id if row.item else None)
        if sprite_surf is not None:
            icon = 16
            scaled = pygame.transform.smoothscale(sprite_surf, (icon, icon))
            self._blit_with_reveal(
                surface, scaled, (chip_x, row_mid_y - icon // 2), phase
            )
            label_x = chip_x + icon + 6
        elif row.item is not None:
            chip = pygame.Rect(chip_x, row_mid_y - 5, 10, 10)
            pygame.draw.rect(surface, row.item.color, chip)
            pygame.draw.rect(surface, lighten(row.item.color, 0.25), chip, 1)
            label_x = chip_x + 14
        else:
            label_x = chip_x

        label_surf = self.assets.render_text(row.label, TYPE.body, PALETTE.text_body)
        self._blit_with_reveal(
            surface,
            label_surf,
            (label_x, row_mid_y - label_surf.get_height() // 2),
            phase,
        )
        value_color = row.accent if row.accent is not None else PALETTE.text_strong
        value_surf = self.assets.render_text(row.value, TYPE.body, value_color)
        self._blit_with_reveal(
            surface,
            value_surf,
            (
                rect.right - _PAD - value_surf.get_width(),
                row_mid_y - value_surf.get_height() // 2,
            ),
            phase,
        )
        return y + _RATE_ROW_H

    # -- progress ----------------------------------------------------------

    def _render_progress_section(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        info: StructureInfo,
        reveal: float,
    ) -> int:
        phase = _phase_progress(reveal, "progress")
        y = self._render_section_label(surface, rect, y, "PROGRESS", phase)

        label = info.progress_label or ""
        label_surf = self.assets.render_text(label, TYPE.caption, PALETTE.text_body)
        self._blit_with_reveal(surface, label_surf, (rect.x + _PAD, y), phase)

        pct_text = f"{int(self._progress_anim.value * 100)}%"
        pct_surf = self.assets.render_text(pct_text, TYPE.body, PALETTE.text_strong)
        self._blit_with_reveal(
            surface,
            pct_surf,
            (rect.right - _PAD - pct_surf.get_width(), y - 2),
            phase,
        )

        bar_y = y + label_surf.get_height() + 6
        bar_rect = pygame.Rect(rect.x + _PAD, bar_y, rect.w - _PAD * 2, 12)
        pygame.draw.rect(surface, darken(PALETTE.bg_raised, 0.35), bar_rect)
        pygame.draw.rect(surface, PALETTE.line, bar_rect, 1)
        frac = max(0.0, min(1.0, self._progress_anim.value))
        fill_w = int((bar_rect.w - 2) * frac * phase)
        if fill_w > 0:
            inner = pygame.Rect(bar_rect.x + 1, bar_rect.y + 1, fill_w, bar_rect.h - 2)
            pygame.draw.rect(surface, PALETTE.primary, inner)
            pygame.draw.rect(
                surface,
                lighten(PALETTE.primary, 0.35),
                pygame.Rect(inner.x, inner.y, inner.w, 2),
            )
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
        return bar_y + bar_rect.h + _SECTION_GAP

    # -- close button ------------------------------------------------------

    def _render_close_button(self, surface: pygame.Surface, reveal: float) -> None:
        phase = _phase_progress(reveal, "header")
        if phase <= 0.01:
            return
        r = self._close_btn.rect
        hover = self._close_btn.hover_anim.value
        press = self._close_btn.press_anim.value
        bg = lighten(PALETTE.bg_raised, 0.1 * hover) if hover > 0 else PALETTE.bg_raised
        with acquired(r.size) as layer:
            lr = pygame.Rect(0, 0, r.w, r.h)
            beveled_panel(layer, lr, fill=bg, border=PALETTE.line)
            tint = (
                lighten(PALETTE.danger, 0.2 * hover)
                if hover > 0
                else PALETTE.text_body
            )
            inset = 6 + int(press * 2)
            pygame.draw.line(
                layer, tint, (inset, inset), (r.w - inset, r.h - inset), 2
            )
            pygame.draw.line(
                layer, tint, (r.w - inset, inset), (inset, r.h - inset), 2
            )
            layer.set_alpha(int(255 * phase))
            surface.blit(layer, r.topleft)

    # -- helpers -----------------------------------------------------------

    def _safe_item_sprite(self, item_id: str | None) -> pygame.Surface | None:
        if item_id is None:
            return None
        try:
            return self.assets.item_icon(item_id)
        except (FileNotFoundError, pygame.error):
            return None
