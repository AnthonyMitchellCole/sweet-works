"""Bottom toolbar: prefab slots with hover tweens and a slide-in animation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import pygame

from ..buildings.registry import BUILDINGS, BuildingPrefab
from ..core import config
from ..design.palette import PALETTE, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import Tween
from ..rendering.pixel import beveled_panel
from .widget import Widget

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


SLOT_SIZE: int = 64
SLOT_GAP: int = 8
PANEL_PAD: int = 12


@dataclass(frozen=True)
class ToolSlot:
    id: str
    label: str
    hotkey: int
    prefab: BuildingPrefab | None = None  # None means belt tool


def default_slots() -> tuple[ToolSlot, ...]:
    return (
        ToolSlot(id="belt", label="Conveyor", hotkey=pygame.K_1, prefab=None),
        ToolSlot(id="miner_iron", label="Iron Miner", hotkey=pygame.K_2, prefab=BUILDINGS.miner_iron),
        ToolSlot(id="miner_copper", label="Copper Miner", hotkey=pygame.K_3, prefab=BUILDINGS.miner_copper),
        ToolSlot(id="assembler_plate", label="Plate Assembler", hotkey=pygame.K_4, prefab=BUILDINGS.assembler_plate),
        ToolSlot(id="assembler_gear", label="Gear Assembler", hotkey=pygame.K_5, prefab=BUILDINGS.assembler_gear),
    )


class Toolbar:
    def __init__(
        self,
        assets: "AssetLoader",
        slots: tuple[ToolSlot, ...] | None = None,
        on_select: Callable[[ToolSlot], None] | None = None,
        window_size: tuple[int, int] = (config.WINDOW_W, config.WINDOW_H),
    ) -> None:
        self.assets = assets
        self.slots = slots or default_slots()
        self.on_select = on_select or (lambda _: None)
        self.selected_index: int = 0

        n = len(self.slots)
        total_w = n * SLOT_SIZE + (n - 1) * SLOT_GAP
        self._panel_w = total_w + PANEL_PAD * 2
        self._panel_h = SLOT_SIZE + PANEL_PAD * 2

        self._widgets: list[Widget] = [
            Widget(pygame.Rect(0, 0, SLOT_SIZE, SLOT_SIZE)) for _ in self.slots
        ]
        self._widgets[self.selected_index].selected = True

        self._panel_x: int = 0
        self._panel_final_y: int = 0
        self._panel_start_y: int = 0
        self._slide = Tween(start=0.0, end=0.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out)

        self.layout(window_size, animate_in=True)

    # -- layout ------------------------------------------------------------

    def layout(self, window_size: tuple[int, int], *, animate_in: bool = False) -> None:
        w, h = window_size
        self._panel_x = (w - self._panel_w) // 2
        self._panel_final_y = h - self._panel_h - 16
        self._panel_start_y = h + 8

        current_y = self._panel_final_y
        if animate_in:
            self._slide = Tween(
                start=self._panel_start_y,
                end=self._panel_final_y,
                duration=THEME.anim.slow,
                ease=THEME.anim.ease_out,
            )
            current_y = self._panel_start_y
        else:
            # preserve any in-flight slide offset, just remap to new end
            progress = 0.0
            if self._slide.duration > 0:
                progress = self._slide.elapsed / self._slide.duration
            self._slide = Tween(
                start=self._panel_start_y,
                end=self._panel_final_y,
                duration=THEME.anim.slow,
                ease=THEME.anim.ease_out,
            )
            self._slide.elapsed = progress * self._slide.duration
            self._slide.done = progress >= 1.0
            current_y = self._panel_final_y if self._slide.done else int(
                self._slide.start
                + (self._slide.end - self._slide.start)
                * (self._slide.ease(progress) if 0.0 < progress < 1.0 else progress)
            )

        for i, widget in enumerate(self._widgets):
            x = self._panel_x + PANEL_PAD + i * (SLOT_SIZE + SLOT_GAP)
            widget.rect.topleft = (x, current_y + PANEL_PAD)

    # -- API ---------------------------------------------------------------

    def selected_slot(self) -> ToolSlot:
        return self.slots[self.selected_index]

    def select(self, index: int) -> None:
        index = max(0, min(len(self.slots) - 1, index))
        if index == self.selected_index:
            return
        self._widgets[self.selected_index].selected = False
        self.selected_index = index
        self._widgets[self.selected_index].selected = True
        self.on_select(self.selected_slot())

    def handle_hotkey(self, key: int) -> bool:
        for i, slot in enumerate(self.slots):
            if slot.hotkey == key:
                self.select(i)
                return True
        return False

    # -- update/render -----------------------------------------------------

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_released: bool,
    ) -> None:
        panel_y = self._slide.update(dt)
        dy = int(panel_y - self._panel_final_y)
        for i, w in enumerate(self._widgets):
            x = self._panel_x + PANEL_PAD + i * (SLOT_SIZE + SLOT_GAP)
            w.rect.topleft = (x, self._panel_final_y + PANEL_PAD + dy)
            w.update(dt, mouse_pos, mouse_down)
            if w.clicked(mouse_released):
                self.select(i)

    def render(self, surface: pygame.Surface) -> None:
        panel_y = self._slide.end - (self._slide.end - self._widgets[0].rect.y + PANEL_PAD)
        actual_panel_y = self._widgets[0].rect.y - PANEL_PAD
        panel_rect = pygame.Rect(
            self._panel_x, actual_panel_y, self._panel_w, self._panel_h
        )
        beveled_panel(surface, panel_rect, fill=PALETTE.bg_base, border=PALETTE.line)

        for i, (slot, w) in enumerate(zip(self.slots, self._widgets)):
            self._render_slot(surface, slot, w, i)

        self._render_tooltip(surface)
        _ = panel_y

    def _render_slot(
        self,
        surface: pygame.Surface,
        slot: ToolSlot,
        widget: Widget,
        index: int,
    ) -> None:
        rect = widget.rect
        hover = widget.hover_anim.value
        press = widget.press_anim.value
        scale = 1.0 + hover * 0.04 - press * 0.05

        bg = PALETTE.bg_raised if not widget.selected else lighten(PALETTE.bg_raised, 0.08)
        beveled_panel(surface, rect, fill=bg, border=PALETTE.line)

        if widget.selected:
            glow = pygame.Surface(rect.size, pygame.SRCALPHA)
            glow.fill(with_alpha(PALETTE.primary, int(40 + 40 * hover)))
            surface.blit(glow, rect.topleft)
            pygame.draw.rect(surface, PALETTE.primary, rect, 2)
        elif hover > 0.02:
            pygame.draw.rect(surface, lighten(PALETTE.line, 0.2), rect, 1)

        # Icon
        icon = self._icon_for(slot)
        if icon is not None:
            ix = rect.centerx - int(icon.get_width() * scale) // 2
            iy = rect.centery - int(icon.get_height() * scale) // 2 - 4
            if scale != 1.0:
                size = (
                    max(1, int(icon.get_width() * scale)),
                    max(1, int(icon.get_height() * scale)),
                )
                icon = pygame.transform.scale(icon, size)
            surface.blit(icon, (ix, iy))

        # Hotkey label
        label = str(index + 1)
        surf = self.assets.render_text(label, TYPE.label, PALETTE.muted)
        surface.blit(surf, (rect.x + 4, rect.y + 4))

    def _icon_for(self, slot: ToolSlot) -> pygame.Surface | None:
        if slot.id == "belt":
            return self.assets.belt("E", 0)
        return self.assets.sprite("building_base")

    def _render_tooltip(self, surface: pygame.Surface) -> None:
        for w, slot in zip(self._widgets, self.slots):
            if w.hovered:
                self._draw_tooltip(surface, slot, w.rect)
                break

    def _draw_tooltip(
        self, surface: pygame.Surface, slot: ToolSlot, anchor: pygame.Rect
    ) -> None:
        text = self.assets.render_text(slot.label, TYPE.caption, PALETTE.text_strong)
        pad = THEME.spacing.sm
        rect = pygame.Rect(
            anchor.centerx - text.get_width() // 2 - pad,
            anchor.y - text.get_height() - pad * 2 - 4,
            text.get_width() + pad * 2,
            text.get_height() + pad,
        )
        beveled_panel(surface, rect, fill=PALETTE.bg_deep, border=PALETTE.line)
        surface.blit(text, (rect.x + pad, rect.y + pad // 2))
