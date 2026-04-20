"""Bottom toolbar: prefab slots with hover tweens and a slide-in animation."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from ..audio.sfx import SFX
from ..buildings.registry import BUILDINGS, BuildingPrefab
from ..core import config
from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import Tween
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from ..world.direction import Direction
from .widget import Widget

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..core.events import EventBus
    from ..research.state import ResearchState


SLOT_SIZE: int = 64
SLOT_GAP: int = 8
PANEL_PAD: int = 12


@dataclass(frozen=True)
class ToolSlot:
    id: str
    label: str
    hotkey: int
    prefab: BuildingPrefab | None = None  # None means belt tool or pointer


def default_slots() -> tuple[ToolSlot, ...]:
    return (
        ToolSlot(id="pointer", label="Inspect", hotkey=pygame.K_q, prefab=None),
        ToolSlot(id="belt", label="Conveyor", hotkey=pygame.K_1, prefab=None),
        ToolSlot(
            id="extractor_cocoa",
            label="Cocoa Extractor",
            hotkey=pygame.K_2,
            prefab=BUILDINGS.extractor_cocoa,
        ),
        ToolSlot(
            id="extractor_sugar",
            label="Sugar Extractor",
            hotkey=pygame.K_3,
            prefab=BUILDINGS.extractor_sugar,
        ),
        ToolSlot(
            id="well_milk",
            label="Milk Well",
            hotkey=pygame.K_4,
            prefab=BUILDINGS.well_milk,
        ),
        ToolSlot(
            id="mixer_chocolate",
            label="Chocolate Mixer",
            hotkey=pygame.K_5,
            prefab=BUILDINGS.mixer_chocolate,
        ),
        ToolSlot(
            id="pot_caramel",
            label="Caramel Pot",
            hotkey=pygame.K_6,
            prefab=BUILDINGS.pot_caramel,
        ),
        ToolSlot(
            id="wrapper_candy",
            label="Candy Wrapper",
            hotkey=pygame.K_7,
            prefab=BUILDINGS.wrapper_candy,
        ),
    )


class Toolbar:
    def __init__(
        self,
        assets: AssetLoader,
        slots: tuple[ToolSlot, ...] | None = None,
        on_select: Callable[[ToolSlot], None] | None = None,
        window_size: tuple[int, int] = (config.WINDOW_W, config.WINDOW_H),
        research: ResearchState | None = None,
        events: EventBus | None = None,
    ) -> None:
        self.assets = assets
        self.slots = slots or default_slots()
        self.on_select = on_select or (lambda _: None)
        self.selected_index: int = 0
        self.research: ResearchState | None = research
        # Lock pulse phase (driven by update dt) for the dashed halo.
        self._lock_phase: float = 0.0
        self._events = events
        self._unsub_research = None
        if events is not None:
            self._unsub_research = events.on(
                "research.changed", lambda **_: self._on_research_changed()
            )

        # Live placement-transform state mirrored from the cursor so the
        # selected slot can render a rotation + mirror pip. Defaults keep
        # the toolbar usable in isolation (tests, menu preview).
        self._transform_rotation: Direction = Direction.E
        self._transform_mirrored: bool = False

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

        # Procedural icon cache (e.g. pointer cursor glyph).
        self._icon_cache: dict[str, pygame.Surface] = {}

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

    def is_slot_unlocked(self, slot: ToolSlot) -> bool:
        if self.research is None:
            return True
        if slot.prefab is not None:
            return self.research.is_unlocked(slot.prefab.id)
        # Non-prefab slots (pointer, belt) are always available.
        return self.research.is_unlocked(slot.id)

    def select(self, index: int) -> None:
        index = max(0, min(len(self.slots) - 1, index))
        if index == self.selected_index:
            return
        slot = self.slots[index]
        if not self.is_slot_unlocked(slot):
            SFX.play("ui.error")
            # Nudge the lock pulse so the halo flashes on rejection.
            self._lock_phase += 2.0
            return
        self._widgets[self.selected_index].selected = False
        self.selected_index = index
        self._widgets[self.selected_index].selected = True
        self.on_select(self.selected_slot())

    def _on_research_changed(self) -> None:
        """If the live selection becomes somehow invalid, fall back to pointer.

        Normally research only *unlocks* things, but this keeps the
        invariant "selected slot is always unlocked" airtight.
        """
        slot = self.selected_slot()
        if self.is_slot_unlocked(slot):
            return
        for i, s in enumerate(self.slots):
            if self.is_slot_unlocked(s):
                self._widgets[self.selected_index].selected = False
                self.selected_index = i
                self._widgets[i].selected = True
                self.on_select(s)
                return

    def close(self) -> None:
        if self._unsub_research is not None:
            self._unsub_research()
            self._unsub_research = None

    def set_transform(self, rotation: Direction, mirrored: bool) -> None:
        """Sync the rotation + mirror pip with the live placement cursor."""
        self._transform_rotation = rotation
        self._transform_mirrored = bool(mirrored)

    def handle_hotkey(self, key: int) -> bool:
        for i, slot in enumerate(self.slots):
            if slot.hotkey == key:
                if not self.is_slot_unlocked(slot):
                    SFX.play("ui.error")
                    self._lock_phase += 2.0
                    return True
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
        self._lock_phase = (self._lock_phase + dt * 1.8) % 1000.0
        for i, w in enumerate(self._widgets):
            x = self._panel_x + PANEL_PAD + i * (SLOT_SIZE + SLOT_GAP)
            w.rect.topleft = (x, self._panel_final_y + PANEL_PAD + dy)
            w.update(dt, mouse_pos, mouse_down)
            if w.clicked(mouse_released):
                self.select(i)

    def render(self, surface: pygame.Surface) -> None:
        actual_panel_y = self._widgets[0].rect.y - PANEL_PAD
        panel_rect = pygame.Rect(
            self._panel_x, actual_panel_y, self._panel_w, self._panel_h
        )
        beveled_panel(surface, panel_rect, fill=PALETTE.bg_base, border=PALETTE.line)

        for i, (slot, w) in enumerate(zip(self.slots, self._widgets)):
            self._render_slot(surface, slot, w, i)

        self._render_tooltip(surface)

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
        locked = not self.is_slot_unlocked(slot)

        if locked:
            bg = darken(PALETTE.bg_raised, 0.25)
        else:
            bg = PALETTE.bg_raised if not widget.selected else lighten(PALETTE.bg_raised, 0.08)
        beveled_panel(surface, rect, fill=bg, border=PALETTE.line)

        if widget.selected and not locked:
            with acquired(rect.size) as glow:
                glow.fill(with_alpha(PALETTE.primary, int(40 + 40 * hover)))
                surface.blit(glow, rect.topleft)
            pygame.draw.rect(surface, PALETTE.primary, rect, 2)
        elif hover > 0.02 and not locked:
            pygame.draw.rect(surface, lighten(PALETTE.line, 0.2), rect, 1)

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
            if locked:
                # Desaturate: blend icon with grey via a darkened overlay.
                tinted = icon.copy()
                veil = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
                veil.fill(with_alpha(PALETTE.bg_deep, 170))
                tinted.blit(veil, (0, 0))
                surface.blit(tinted, (ix, iy))
            else:
                surface.blit(icon, (ix, iy))

        if locked:
            self._draw_lock_glyph(surface, rect, hover)

        label = pygame.key.name(slot.hotkey).upper()
        label_color = PALETTE.line if locked else PALETTE.muted
        surf = self.assets.render_text(label, TYPE.label, label_color)
        surface.blit(surf, (rect.x + 4, rect.y + 4))

        if widget.selected and slot.prefab is not None and not locked:
            self._draw_transform_pip(surface, rect)

    def _draw_lock_glyph(
        self, surface: pygame.Surface, rect: pygame.Rect, hover: float
    ) -> None:
        """Small padlock icon + soft pulsing halo in the slot's top-right."""
        pulse = 0.5 + 0.5 * math.sin(self._lock_phase * math.tau)
        halo_alpha = int(60 + 60 * pulse + hover * 60)
        with acquired(rect.size) as glow:
            pygame.draw.rect(
                glow,
                with_alpha(PALETTE.warning, max(0, min(255, halo_alpha))),
                glow.get_rect(),
                2,
            )
            surface.blit(glow, rect.topleft)

        gx = rect.right - 12
        gy = rect.top + 10
        body = pygame.Rect(gx - 5, gy, 10, 8)
        pygame.draw.rect(surface, PALETTE.warning, body)
        pygame.draw.rect(surface, PALETTE.bg_deep, body, 1)
        shackle = pygame.Rect(gx - 3, gy - 5, 6, 6)
        pygame.draw.arc(
            surface,
            PALETTE.warning,
            shackle,
            math.pi * 0.1,
            math.pi * 0.9,
            2,
        )
        keyhole = pygame.Rect(gx - 1, gy + 2, 2, 4)
        pygame.draw.rect(surface, PALETTE.bg_deep, keyhole)

    def _draw_transform_pip(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        """Tiny rotation chevron (plus mirror tick) in the slot's top-right."""
        cx = rect.right - 10
        cy = rect.top + 10
        dx, dy = self._transform_rotation.vector
        size = 5
        perp = (-dy, dx)
        tip = (cx + dx * size, cy + dy * size)
        back = (cx - dx * size, cy - dy * size)
        left = (back[0] + perp[0] * size, back[1] + perp[1] * size)
        right = (back[0] - perp[0] * size, back[1] - perp[1] * size)
        pygame.draw.polygon(surface, PALETTE.primary, [tip, left, right])
        pygame.draw.polygon(surface, PALETTE.bg_deep, [tip, left, right], 1)
        if self._transform_mirrored:
            # Small dash on the perpendicular axis = "flipped".
            pygame.draw.line(
                surface,
                PALETTE.secondary,
                (cx + perp[0] * 7, cy + perp[1] * 7),
                (cx - perp[0] * 7, cy - perp[1] * 7),
                2,
            )

    def _icon_for(self, slot: ToolSlot) -> pygame.Surface | None:
        if slot.id == "pointer":
            return self._pointer_icon()
        if slot.id == "belt":
            return self.assets.belt("E", 0)
        if slot.prefab is not None and slot.prefab.sprite_base != "building_base":
            key = f"{slot.prefab.sprite_base}_idle_f0"
            try:
                icon = self.assets.sprite(key)
            except FileNotFoundError:
                return self.assets.sprite("building_base")
            # Scale 2x2 structure sprites down to fit a single toolbar slot.
            target = SLOT_SIZE - 12
            if icon.get_width() != target:
                cache_key = f"toolbar:{key}"
                cached = self._icon_cache.get(cache_key)
                if cached is None:
                    cached = pygame.transform.smoothscale(icon, (target, target))
                    self._icon_cache[cache_key] = cached
                return cached
            return icon
        return self.assets.sprite("building_base")

    def _pointer_icon(self) -> pygame.Surface:
        """Procedural arrow cursor glyph cached after first build."""
        cached = self._icon_cache.get("pointer")
        if cached is not None:
            return cached
        size = 40
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        # Classic cursor arrow: tip near (10,8), body slanted down-right.
        arrow = [
            (10, 8),
            (10, 30),
            (16, 24),
            (20, 32),
            (24, 30),
            (20, 22),
            (28, 22),
        ]
        pygame.draw.polygon(surf, PALETTE.text_strong, arrow)
        pygame.draw.polygon(surf, PALETTE.bg_deep, arrow, 2)
        self._icon_cache["pointer"] = surf
        return surf

    def _render_tooltip(self, surface: pygame.Surface) -> None:
        for w, slot in zip(self._widgets, self.slots):
            if w.hovered:
                self._draw_tooltip(surface, slot, w.rect)
                break

    def _draw_tooltip(
        self, surface: pygame.Surface, slot: ToolSlot, anchor: pygame.Rect
    ) -> None:
        locked = not self.is_slot_unlocked(slot)
        if locked:
            node = (
                self.research.research_node_unlocking(slot.prefab.id)
                if self.research is not None and slot.prefab is not None
                else None
            )
            sub = f"Requires research: {node.name}" if node is not None else "Requires research"
            line1 = self.assets.render_text(
                slot.label, TYPE.caption, PALETTE.text_strong
            )
            line2 = self.assets.render_text(sub, TYPE.label, PALETTE.warning)
            text_w = max(line1.get_width(), line2.get_width())
            text_h = line1.get_height() + line2.get_height() + 2
        else:
            line1 = self.assets.render_text(
                slot.label, TYPE.caption, PALETTE.text_strong
            )
            line2 = None
            text_w = line1.get_width()
            text_h = line1.get_height()

        pad = THEME.spacing.sm
        rect = pygame.Rect(
            anchor.centerx - text_w // 2 - pad,
            anchor.y - text_h - pad * 2 - 4,
            text_w + pad * 2,
            text_h + pad,
        )
        beveled_panel(surface, rect, fill=PALETTE.bg_deep, border=PALETTE.line)
        surface.blit(line1, (rect.x + pad, rect.y + pad // 2))
        if line2 is not None:
            surface.blit(
                line2,
                (rect.x + pad, rect.y + pad // 2 + line1.get_height() + 2),
            )
