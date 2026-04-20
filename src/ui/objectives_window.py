"""Objectives / stats overlay window.

Right-docked panel toggled on ``J`` (or the HUD button). Visually
mirrors :class:`~src.ui.sprite_studio.SpriteStudio` so the two
overlays feel like siblings: the same right-dock slide-in tween, the
same ``beveled_panel`` chrome, the same per-row reveal stagger.

The window is a tabbed read-out of :class:`~src.stats.StatsTracker`
and :class:`~src.stats.ObjectivesState` with four tabs:

* **Objectives** -- gameplay quests with animated progress bars,
  completion pulses, prereq-gated locks.
* **Items** -- per-item lifetime / windowed rates, min / max / median
  / total and a sparkline of the net production rate.
* **Buildings** -- per-prefab placed / removed / active counts and
  per-class summaries.
* **Session** -- global throughput, belt tile count, items in world,
  session runtime.

All motion is driven by :class:`~src.rendering.animation.AnimValue`
and :class:`~src.rendering.animation.Tween`; colours / fonts come
from the shared design system so the surface area of the change on
the rest of the UI stays tiny.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pygame

from ..audio.sfx import SFX
from ..core import config
from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..items.registry import ITEMS
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from ..stats.objectives import ObjectiveKind, ObjectiveStatus, ObjectivesState
from ..stats.tracker import StatsTracker, prefab_display_name

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


# -- layout constants ------------------------------------------------------

_PANEL_W = 880
_PANEL_MARGIN_Y = 32
_PANEL_MIN_H = 640
_HEADER_H = 58
_TAB_H = 38
_CLOSE_SIZE = 28
_PAD = THEME.spacing.lg
_GAP = THEME.spacing.md
_SM_GAP = THEME.spacing.sm

_CARD_H = 74
_CARD_GAP = 10
_ICON_BOX = 48
_PROGRESS_H = 10

_ITEM_ROW_H = 56
_BUILDING_ROW_H = 50
_WINDOW_CHIP_H = 26

_ACCENT = PALETTE.primary
_ACCENT_SUCCESS = PALETTE.success

_SHADOW_ALPHA = 140


# -- hit region ------------------------------------------------------------


@dataclass
class _Hit:
    rect: pygame.Rect
    payload: object
    kind: str = "click"


@dataclass
class _CardAnim:
    hover: AnimValue = field(default_factory=lambda: AnimValue(speed=18.0))
    bar: AnimValue = field(default_factory=lambda: AnimValue(speed=10.0))
    pulse: Tween = field(
        default_factory=lambda: _finished_tween()
    )


def _finished_tween() -> Tween:
    t = Tween(0.0, 0.0, duration=THEME.anim.fast, ease=THEME.anim.ease_out)
    t.done = True
    return t


# -- window ----------------------------------------------------------------


class ObjectivesWindow:
    """Right-docked overlay showing objectives and centralized stats."""

    _TABS: tuple[tuple[str, str], ...] = (
        ("objectives", "OBJECTIVES"),
        ("items", "ITEMS"),
        ("buildings", "BUILDINGS"),
        ("session", "SESSION"),
    )

    _RATE_WINDOWS: tuple[tuple[int, str], ...] = (
        (10, "10s"),
        (60, "1m"),
        (300, "5m"),
        (1800, "30m"),
    )

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self._is_open: bool = False
        self._closing: bool = False
        self._window_size: tuple[int, int] = (config.WINDOW_W, config.WINDOW_H)

        self._stats: StatsTracker | None = None
        self._objectives: ObjectivesState | None = None
        self._off_completed: Callable[[], None] | None = None

        self._time: float = 0.0

        # Slide animation mirrors Sprite Studio.
        self._slide = Tween(
            start=0.0, end=0.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out
        )
        self._slide.done = True
        self._slide_value: float = 0.0

        # Tab state: active_id + cross-fade from previous tab.
        self._active_tab: str = "objectives"
        self._prev_tab: str | None = None
        self._tab_anim = AnimValue(value=1.0, speed=10.0)
        self._tab_hover = AnimValue(value=0.0, speed=18.0)
        self._rate_window_idx: int = 1  # defaults to 60s

        # Row / card reveal.
        self._row_reveal = AnimValue(value=0.0, speed=5.0)

        # Per-frame hit regions (rebuilt during render, consumed on event).
        self._hits: list[_Hit] = []
        self._hover_payload: object | None = None
        self._hover_strength = AnimValue(value=0.0, speed=16.0)

        # Scroll state per tab (objectives + items are scrollable).
        self._scroll: dict[str, float] = {
            "objectives": 0.0,
            "items": 0.0,
        }
        self._max_scroll: dict[str, float] = {
            "objectives": 0.0,
            "items": 0.0,
        }

        # Per-objective animation state.
        self._card_anims: dict[str, _CardAnim] = {}

    # -- wiring -----------------------------------------------------------

    def attach(self, stats: StatsTracker, objectives: ObjectivesState) -> None:
        self._stats = stats
        self._objectives = objectives
        if self._off_completed is not None:
            self._off_completed()
        self._off_completed = objectives.on_completed(self._on_objective_completed)

    def close_subscriptions(self) -> None:
        if self._off_completed is not None:
            try:
                self._off_completed()
            except Exception:  # pragma: no cover - defensive
                pass
            self._off_completed = None

    # -- lifecycle --------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._is_open

    def layout(self, window_size: tuple[int, int]) -> None:
        self._window_size = window_size

    def toggle(self) -> None:
        if self._is_open and not self._closing:
            self.close()
        else:
            self.open()

    def open(self) -> None:
        if self._is_open and not self._closing:
            return
        start = self._slide_value if self._closing else 0.0
        self._is_open = True
        self._closing = False
        self._slide = Tween(
            start=start,
            end=1.0,
            duration=THEME.anim.slow,
            ease=THEME.anim.ease_out,
        )
        self._slide_value = start
        self._row_reveal.set(0.0)
        self._row_reveal.to(1.0)
        SFX.play("ui.open")

    def close(self) -> None:
        if not self._is_open:
            return
        self._closing = True
        self._slide = Tween(
            start=self._slide_value,
            end=0.0,
            duration=THEME.anim.base,
            ease=THEME.anim.ease_out,
        )
        SFX.play("ui.close")

    # -- input ------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self._is_open:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE or event.key == pygame.K_j:
                self.close()
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            hit = self._hit_at(pos)
            if hit is not None:
                self._dispatch(hit)
                return True
            if self._rect().collidepoint(pos):
                return True
        if event.type == pygame.MOUSEWHEEL:
            mpos = pygame.mouse.get_pos()
            if self._rect().collidepoint(mpos):
                self._scroll_by(event.y)
                return True
        return False

    def _scroll_by(self, wheel_y: int) -> None:
        if self._active_tab not in self._scroll:
            return
        step = 48.0
        self._scroll[self._active_tab] = max(
            0.0,
            min(
                self._max_scroll.get(self._active_tab, 0.0),
                self._scroll[self._active_tab] - wheel_y * step,
            ),
        )

    def _hit_at(self, pos: tuple[int, int]) -> _Hit | None:
        # Later hits (drawn on top) take priority.
        for hit in reversed(self._hits):
            if hit.rect.collidepoint(pos):
                return hit
        return None

    def _dispatch(self, hit: _Hit) -> None:
        payload = hit.payload
        if isinstance(payload, tuple) and payload:
            kind = payload[0]
            if kind == "close":
                self.close()
                return
            if kind == "tab":
                tab_id = payload[1]
                if isinstance(tab_id, str) and tab_id != self._active_tab:
                    self._prev_tab = self._active_tab
                    self._active_tab = tab_id
                    self._tab_anim.set(0.0)
                    self._tab_anim.to(1.0)
                    self._row_reveal.set(0.0)
                    self._row_reveal.to(1.0)
                    SFX.play("ui.click_soft")
                return
            if kind == "rate_window":
                idx = payload[1]
                if isinstance(idx, int) and 0 <= idx < len(self._RATE_WINDOWS):
                    if idx != self._rate_window_idx:
                        self._rate_window_idx = idx
                        SFX.play("ui.click_soft")
                return

    # -- update / render --------------------------------------------------

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_released: bool,
    ) -> None:
        if not self._is_open and self._slide.done and self._slide_value <= 0.0:
            return
        self._time += dt
        self._slide_value = float(self._slide.update(dt))
        if self._closing and self._slide.done and self._slide_value <= 0.001:
            self._is_open = False
            self._closing = False
        self._row_reveal.update(dt)
        self._tab_anim.update(dt)
        self._hover_strength.update(dt)

        for anim in self._card_anims.values():
            anim.hover.update(dt)
            anim.bar.update(dt)
            anim.pulse.update(dt)

        hit = self._hit_at(mouse_pos) if self._is_open else None
        payload = hit.payload if hit is not None else None
        if payload != self._hover_payload and payload is not None:
            SFX.play("ui.hover")
        self._hover_payload = payload
        self._hover_strength.to(1.0 if hit is not None else 0.0)

        # Sync card bar tweens with current progress values.
        if self._objectives is not None:
            for status in self._objectives.statuses():
                anim = self._card_anim_for(status.spec.id)
                anim.bar.to(status.progress_frac)
                if status.completed:
                    anim.bar.to(1.0)

    def render(self, surface: pygame.Surface) -> None:
        if not self._is_open and self._slide_value <= 0.0:
            return
        self._hits.clear()

        rect = self._rect()

        # Soft shadow behind the panel for depth.
        with acquired((rect.w + 24, rect.h + 24)) as shadow:
            shadow.fill(
                with_alpha(PALETTE.bg_deep, int(_SHADOW_ALPHA * self._slide_value))
            )
            surface.blit(shadow, (rect.x - 8, rect.y + 8))

        beveled_panel(surface, rect, fill=PALETTE.bg_base, border=PALETTE.line)

        header_rect, tab_rect, body_rect = self._split(rect)
        self._render_header(surface, header_rect)
        self._render_tabs(surface, tab_rect)
        self._render_body(surface, body_rect)

    # -- rect helpers -----------------------------------------------------

    def _rect(self) -> pygame.Rect:
        w, h = self._window_size
        panel_h = max(_PANEL_MIN_H, h - _PANEL_MARGIN_Y * 2)
        panel_h = min(panel_h, h - 20)
        docked_x = w - _PANEL_W - 16
        offscreen_x = w + 16
        x = int(offscreen_x + (docked_x - offscreen_x) * self._slide_value)
        y = (h - panel_h) // 2
        return pygame.Rect(x, y, _PANEL_W, panel_h)

    def _split(
        self, rect: pygame.Rect
    ) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
        header = pygame.Rect(rect.x, rect.y, rect.w, _HEADER_H)
        tabs = pygame.Rect(rect.x, header.bottom, rect.w, _TAB_H)
        body = pygame.Rect(
            rect.x + _PAD,
            tabs.bottom + _GAP,
            rect.w - _PAD * 2,
            rect.bottom - (tabs.bottom + _GAP) - _PAD,
        )
        return header, tabs, body

    # -- header -----------------------------------------------------------

    def _render_header(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        pygame.draw.rect(surface, darken(PALETTE.bg_base, 0.15), rect)
        pygame.draw.line(
            surface,
            PALETTE.line,
            (rect.x, rect.bottom - 1),
            (rect.right - 1, rect.bottom - 1),
        )

        title = self.assets.render_text(
            "OBJECTIVES", TYPE.h1, PALETTE.text_strong
        )
        surface.blit(
            title,
            (rect.x + _PAD, rect.y + (rect.h - title.get_height()) // 2),
        )

        sub = self.assets.render_text(
            "J to toggle  -  ESC to close", TYPE.body, PALETTE.muted
        )
        surface.blit(
            sub,
            (
                rect.x + _PAD + title.get_width() + _PAD,
                rect.y + (rect.h - sub.get_height()) // 2 + 2,
            ),
        )

        # Session quick-glance readouts in the header right region.
        self._render_header_stats(surface, rect)

        # Close button.
        close_rect = pygame.Rect(
            rect.right - _CLOSE_SIZE - _PAD,
            rect.y + (rect.h - _CLOSE_SIZE) // 2,
            _CLOSE_SIZE,
            _CLOSE_SIZE,
        )
        hovering = self._hover_payload == ("close",)
        bg = lighten(PALETTE.bg_raised, 0.1) if hovering else PALETTE.bg_raised
        beveled_panel(surface, close_rect, fill=bg, border=PALETTE.line)
        x_surf = self.assets.render_text("x", TYPE.h2, PALETTE.text_strong)
        surface.blit(
            x_surf,
            (
                close_rect.centerx - x_surf.get_width() // 2,
                close_rect.centery - x_surf.get_height() // 2,
            ),
        )
        self._hits.append(_Hit(close_rect, ("close",)))

    def _render_header_stats(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        if self._stats is None or self._objectives is None:
            return
        session = self._stats.session()
        completed = len(self._objectives.completed)
        total = len(self._objectives.catalog())
        elapsed = _format_duration(session.elapsed_s)

        # Two compact pills stacked vertically just left of the close box.
        pill_w = 150
        pill_h = 22
        right = rect.right - _PAD - _CLOSE_SIZE - _GAP - pill_w
        top = rect.y + (rect.h - pill_h * 2 - 4) // 2

        objective_rect = pygame.Rect(right, top, pill_w, pill_h)
        time_rect = pygame.Rect(right, top + pill_h + 4, pill_w, pill_h)

        self._render_pill(
            surface,
            objective_rect,
            f"{completed}/{total} COMPLETE",
            PALETTE.success,
        )
        self._render_pill(
            surface,
            time_rect,
            f"TIME {elapsed}",
            PALETTE.secondary,
        )

    def _render_pill(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        text: str,
        accent: tuple[int, int, int],
    ) -> None:
        pygame.draw.rect(surface, PALETTE.bg_raised, rect)
        pygame.draw.rect(surface, accent, rect, 1)
        label = self.assets.render_text(text, TYPE.label, accent)
        surface.blit(
            label,
            (
                rect.centerx - label.get_width() // 2,
                rect.centery - label.get_height() // 2,
            ),
        )

    # -- tabs -------------------------------------------------------------

    def _render_tabs(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        pygame.draw.rect(surface, darken(PALETTE.bg_base, 0.08), rect)

        tab_w = (rect.w - _PAD * 2) // len(self._TABS)
        x = rect.x + _PAD
        for tid, label in self._TABS:
            tab_rect = pygame.Rect(x, rect.y + 4, tab_w - 2, rect.h - 4)
            active = tid == self._active_tab
            hovered = self._hover_payload == ("tab", tid)
            self._render_tab(surface, tab_rect, label, active, hovered)
            self._hits.append(_Hit(tab_rect, ("tab", tid)))
            x += tab_w

        # Bottom border that the active tab eats through.
        pygame.draw.line(
            surface,
            PALETTE.line,
            (rect.x, rect.bottom - 1),
            (rect.right - 1, rect.bottom - 1),
        )

    def _render_tab(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        active: bool,
        hovered: bool,
    ) -> None:
        fill = PALETTE.bg_base if active else darken(PALETTE.bg_base, 0.06)
        if hovered and not active:
            fill = lighten(fill, 0.08)
        pygame.draw.rect(surface, fill, rect)
        if active:
            # Strong top accent + soft bottom notch through the tab strip.
            pygame.draw.line(
                surface,
                _ACCENT,
                (rect.x + 6, rect.y + 2),
                (rect.right - 6, rect.y + 2),
                2,
            )
            pygame.draw.rect(surface, PALETTE.bg_base, rect.inflate(-4, 0), 0)
            pygame.draw.line(
                surface,
                _ACCENT,
                (rect.x + 6, rect.y + 2),
                (rect.right - 6, rect.y + 2),
                2,
            )
            pygame.draw.line(
                surface,
                PALETTE.bg_base,
                (rect.x, rect.bottom - 1),
                (rect.right - 1, rect.bottom - 1),
            )
        else:
            pygame.draw.line(
                surface,
                PALETTE.line,
                (rect.x, rect.bottom - 1),
                (rect.right - 1, rect.bottom - 1),
            )

        text_color = PALETTE.text_strong if active else PALETTE.muted
        text_surf = self.assets.render_text(label, TYPE.label, text_color)
        surface.blit(
            text_surf,
            (
                rect.centerx - text_surf.get_width() // 2,
                rect.centery - text_surf.get_height() // 2 + 2,
            ),
        )

    # -- body dispatch ----------------------------------------------------

    def _render_body(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        if self._stats is None or self._objectives is None:
            return
        # Cross-fade between tabs. ``_prev_tab`` is drawn with ``1 - anim``
        # opacity under the new tab when it's still close to the switch.
        anim = max(0.0, min(1.0, self._tab_anim.value))
        shift = int((1.0 - anim) * 14)

        with acquired(rect.size) as tab_layer:
            offset = (rect.x, rect.y)
            local_rect = pygame.Rect(0, 0, rect.w, rect.h)
            local_rect.x += shift
            if self._active_tab == "objectives":
                self._render_objectives_tab(tab_layer, local_rect, offset)
            elif self._active_tab == "items":
                self._render_items_tab(tab_layer, local_rect, offset)
            elif self._active_tab == "buildings":
                self._render_buildings_tab(tab_layer, local_rect, offset)
            elif self._active_tab == "session":
                self._render_session_tab(tab_layer, local_rect, offset)
            tab_layer.set_alpha(int(255 * anim))
            surface.blit(tab_layer, rect.topleft)

    # -- objectives tab ---------------------------------------------------

    def _render_objectives_tab(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        offset: tuple[int, int],
    ) -> None:
        assert self._objectives is not None
        statuses = self._objectives.statuses()
        # Sort: active (not locked, not completed) first by tier; then
        # locked; then completed at the bottom.
        def sort_key(s: ObjectiveStatus) -> tuple[int, int, str]:
            if s.completed:
                bucket = 2
            elif s.locked:
                bucket = 1
            else:
                bucket = 0
            return (bucket, s.spec.tier, s.spec.id)

        statuses.sort(key=sort_key)

        total_h = len(statuses) * (_CARD_H + _CARD_GAP)
        self._max_scroll["objectives"] = max(0.0, total_h - rect.h)
        scroll = self._scroll["objectives"] = max(
            0.0, min(self._max_scroll["objectives"], self._scroll["objectives"])
        )

        reveal = self._row_reveal.value
        y = rect.y - int(scroll)
        for i, status in enumerate(statuses):
            if y + _CARD_H < rect.y:
                y += _CARD_H + _CARD_GAP
                continue
            if y > rect.bottom:
                break
            # Staggered opacity from the reveal animation.
            row_phase = max(0.0, min(1.0, reveal * len(statuses) - i * 0.5))
            card_rect = pygame.Rect(rect.x, y, rect.w, _CARD_H)
            self._render_objective_card(
                surface, card_rect, status, row_phase, offset
            )
            y += _CARD_H + _CARD_GAP

        self._render_scrollbar(surface, rect, "objectives")

    def _render_objective_card(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        status: ObjectiveStatus,
        alpha_frac: float,
        offset: tuple[int, int],
    ) -> None:
        anim = self._card_anim_for(status.spec.id)
        locked = status.locked
        completed = status.completed
        # Pulse was ticked in ``update``; ``update(0.0)`` peeks the
        # current value without advancing the tween further.
        pulse_strength = (
            0.0 if anim.pulse.done
            else max(0.0, min(1.0, float(anim.pulse.update(0.0))))
        )
        accent = _ACCENT_SUCCESS if completed else (PALETTE.muted if locked else _ACCENT)
        body_fill = PALETTE.bg_raised
        if completed:
            body_fill = darken(PALETTE.bg_raised, 0.05)
        elif locked:
            body_fill = darken(PALETTE.bg_raised, 0.18)

        with acquired(rect.size) as card:
            local = pygame.Rect(0, 0, rect.w, rect.h)
            beveled_panel(card, local, fill=body_fill, border=PALETTE.line)
            # Left accent stripe keyed to status.
            stripe = pygame.Rect(0, 4, 4, local.h - 8)
            pygame.draw.rect(card, accent, stripe)

            # Icon box.
            icon_rect = pygame.Rect(
                _PAD, (local.h - _ICON_BOX) // 2, _ICON_BOX, _ICON_BOX
            )
            self._render_card_icon(card, icon_rect, status, completed, locked)

            # Title + description.
            tx = icon_rect.right + _GAP
            title_col = PALETTE.text_strong if not locked else PALETTE.muted
            title = self.assets.render_text(
                status.spec.title, TYPE.h2, title_col
            )
            card.blit(title, (tx, 8))

            desc_col = PALETTE.text_body if not locked else PALETTE.muted
            desc = self.assets.render_text(
                _truncate(status.spec.description, 70), TYPE.caption, desc_col
            )
            card.blit(desc, (tx, 8 + title.get_height() + 2))

            # Right: progress number / status chip.
            self._render_card_progress_line(card, local, tx, status, accent)

            # Progress bar.
            bar_rect = pygame.Rect(
                tx,
                local.h - _PROGRESS_H - 10,
                local.w - tx - _PAD,
                _PROGRESS_H,
            )
            frac = anim.bar.value if not completed else 1.0
            if locked:
                frac = 0.0
            self._render_progress_bar(
                card, bar_rect, frac, accent, completed=completed, locked=locked
            )

            if completed and pulse_strength > 0.01:
                # Soft golden glow on completion.
                overlay_alpha = int(220 * pulse_strength)
                pygame.draw.rect(
                    card,
                    with_alpha(_ACCENT_SUCCESS, overlay_alpha),
                    local,
                    2,
                )

            card.set_alpha(int(255 * max(0.0, min(1.0, alpha_frac))))
            surface.blit(card, rect.topleft)

        world_rect = pygame.Rect(
            rect.x + offset[0], rect.y + offset[1], rect.w, rect.h
        )
        self._hits.append(_Hit(world_rect, ("objective", status.spec.id)))

    def _render_card_icon(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        status: ObjectiveStatus,
        completed: bool,
        locked: bool,
    ) -> None:
        fill = darken(PALETTE.bg_raised, 0.15)
        beveled_panel(surface, rect, fill=fill, border=PALETTE.line)

        icon_surf: pygame.Surface | None = None
        spec = status.spec
        if spec.icon_item_id is not None:
            icon_surf = _try_sprite(self.assets, f"item_{spec.icon_item_id}")
        elif spec.icon_building_id is not None:
            icon_surf = _try_sprite(
                self.assets, f"structure_{spec.icon_building_id}_idle_f0"
            )
        if icon_surf is None and spec.item_id is not None:
            icon_surf = _try_sprite(self.assets, f"item_{spec.item_id}")

        if icon_surf is not None:
            scaled = pygame.transform.smoothscale(icon_surf, (rect.w - 10, rect.h - 10))
            if locked:
                scaled.set_alpha(90)
            surface.blit(
                scaled,
                (rect.centerx - scaled.get_width() // 2,
                 rect.centery - scaled.get_height() // 2),
            )
        else:
            # Fallback colored dot when no sprite is registered.
            col = PALETTE.muted if locked else _ACCENT
            pygame.draw.circle(surface, col, rect.center, rect.w // 4)

        if completed:
            self._render_check_overlay(surface, rect)
        elif locked:
            self._render_lock_overlay(surface, rect)

    def _render_check_overlay(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        badge = pygame.Rect(rect.right - 18, rect.bottom - 18, 16, 16)
        pygame.draw.rect(surface, _ACCENT_SUCCESS, badge)
        pygame.draw.rect(surface, darken(_ACCENT_SUCCESS, 0.35), badge, 1)
        pygame.draw.lines(
            surface,
            PALETTE.bg_deep,
            False,
            [
                (badge.x + 3, badge.y + 8),
                (badge.x + 7, badge.y + 12),
                (badge.x + 13, badge.y + 4),
            ],
            2,
        )

    def _render_lock_overlay(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        # Simple pixel-art lock glyph centred on the icon box.
        cx, cy = rect.center
        body = pygame.Rect(cx - 6, cy - 2, 12, 10)
        shackle = pygame.Rect(cx - 4, cy - 8, 8, 7)
        pygame.draw.rect(surface, PALETTE.muted, shackle, 2)
        pygame.draw.rect(surface, PALETTE.muted, body)
        pygame.draw.rect(surface, darken(PALETTE.muted, 0.4), body, 1)

    def _render_card_progress_line(
        self,
        surface: pygame.Surface,
        local: pygame.Rect,
        tx: int,
        status: ObjectiveStatus,
        accent: tuple[int, int, int],
    ) -> None:
        right_pad = _PAD
        if status.completed:
            label = "COMPLETE"
            col = _ACCENT_SUCCESS
        elif status.locked:
            prereq_n = len(status.spec.prereq_ids)
            label = f"LOCKED - {prereq_n} prereq" + ("s" if prereq_n != 1 else "")
            col = PALETTE.muted
        else:
            label = _format_progress(status)
            col = accent
        surf = self.assets.render_text(label, TYPE.label, col)
        surface.blit(
            surf,
            (local.w - right_pad - surf.get_width(), 10),
        )

    def _render_progress_bar(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        frac: float,
        accent: tuple[int, int, int],
        *,
        completed: bool = False,
        locked: bool = False,
    ) -> None:
        track = darken(PALETTE.bg_raised, 0.18)
        pygame.draw.rect(surface, track, rect)
        pygame.draw.rect(surface, PALETTE.line, rect, 1)
        if locked:
            return
        frac = max(0.0, min(1.0, frac))
        fill_w = int((rect.w - 2) * frac)
        if fill_w <= 0:
            return
        fill_rect = pygame.Rect(rect.x + 1, rect.y + 1, fill_w, rect.h - 2)
        fill = _ACCENT_SUCCESS if completed else accent
        pygame.draw.rect(surface, fill, fill_rect)
        # Soft highlight on top pixel row.
        if fill_rect.h > 2:
            pygame.draw.line(
                surface,
                lighten(fill, 0.2),
                (fill_rect.x, fill_rect.y),
                (fill_rect.right - 1, fill_rect.y),
            )

    # -- items tab --------------------------------------------------------

    def _render_items_tab(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        offset: tuple[int, int],
    ) -> None:
        assert self._stats is not None
        # Window-selector pill strip at the top of the tab.
        sel_rect = pygame.Rect(rect.x, rect.y, rect.w, _WINDOW_CHIP_H)
        self._render_window_selector(surface, sel_rect, offset)

        table_rect = pygame.Rect(
            rect.x,
            sel_rect.bottom + _GAP,
            rect.w,
            rect.bottom - (sel_rect.bottom + _GAP),
        )
        self._render_items_table(surface, table_rect, offset)

    def _render_window_selector(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        offset: tuple[int, int],
    ) -> None:
        caption = self.assets.render_text(
            "RATE WINDOW", TYPE.label, PALETTE.muted
        )
        surface.blit(caption, (rect.x, rect.y + (rect.h - caption.get_height()) // 2))

        x = rect.x + caption.get_width() + _GAP
        for i, (_secs, label) in enumerate(self._RATE_WINDOWS):
            pill_w = 56
            pill = pygame.Rect(x, rect.y, pill_w, rect.h)
            active = i == self._rate_window_idx
            hovered = self._hover_payload == ("rate_window", i)
            fill = PALETTE.bg_raised
            if active:
                fill = lighten(PALETTE.bg_raised, 0.12)
            elif hovered:
                fill = lighten(PALETTE.bg_raised, 0.05)
            pygame.draw.rect(surface, fill, pill)
            border = _ACCENT if active else PALETTE.line
            pygame.draw.rect(surface, border, pill, 1)
            col = PALETTE.text_strong if active else PALETTE.muted
            text = self.assets.render_text(label, TYPE.label, col)
            surface.blit(
                text,
                (
                    pill.centerx - text.get_width() // 2,
                    pill.centery - text.get_height() // 2,
                ),
            )
            world_pill = pygame.Rect(
                pill.x + offset[0], pill.y + offset[1], pill.w, pill.h
            )
            self._hits.append(_Hit(world_pill, ("rate_window", i)))
            x += pill_w + 6

    def _render_items_table(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        offset: tuple[int, int],
    ) -> None:
        assert self._stats is not None
        window_s = self._RATE_WINDOWS[self._rate_window_idx][0]

        # Column layout (right-aligned numeric columns for quick scanning).
        col_gap = 10
        name_col_w = 180
        spark_col_w = 110
        numeric_col_w = 68
        col_order = ("now", "avg", "max", "min", "med", "total")
        col_titles = {
            "now": "RATE",
            "avg": "AVG",
            "max": "MAX",
            "min": "MIN",
            "med": "MED",
            "total": "TOTAL",
        }

        total_numeric = len(col_order) * numeric_col_w + (len(col_order) - 1) * col_gap
        table_w = name_col_w + col_gap + spark_col_w + col_gap + total_numeric
        x0 = rect.x + max(0, (rect.w - table_w) // 2)

        # Header row.
        header_y = rect.y + 6
        self._render_items_header(
            surface, x0, header_y, name_col_w, spark_col_w, numeric_col_w, col_gap,
            col_order, col_titles,
        )

        row_y = header_y + 22
        items = ITEMS.all()
        total_h = len(items) * (_ITEM_ROW_H + 6)
        self._max_scroll["items"] = max(0.0, total_h - (rect.bottom - row_y))
        self._scroll["items"] = max(
            0.0, min(self._max_scroll["items"], self._scroll["items"])
        )
        scroll = int(self._scroll["items"])
        row_y -= scroll

        reveal = self._row_reveal.value
        for i, item in enumerate(items):
            if row_y + _ITEM_ROW_H < rect.y:
                row_y += _ITEM_ROW_H + 6
                continue
            if row_y > rect.bottom:
                break
            phase = max(0.0, min(1.0, reveal * len(items) - i * 0.5))
            row_rect = pygame.Rect(x0, row_y, table_w, _ITEM_ROW_H)
            self._render_items_row(
                surface, row_rect, item.id, item.name, item.color,
                name_col_w, spark_col_w, numeric_col_w, col_gap, col_order,
                window_s, phase,
            )
            row_y += _ITEM_ROW_H + 6

        self._render_scrollbar(surface, rect, "items")

    def _render_items_header(
        self,
        surface: pygame.Surface,
        x0: int,
        y: int,
        name_w: int,
        spark_w: int,
        num_w: int,
        gap: int,
        col_order: tuple[str, ...],
        titles: dict[str, str],
    ) -> None:
        def _txt(s: str) -> pygame.Surface:
            return self.assets.render_text(s, TYPE.label, PALETTE.muted)

        cx = x0
        name_hdr = _txt("ITEM")
        surface.blit(name_hdr, (cx, y))
        cx += name_w + gap

        spark_hdr = _txt("NET (PER MIN)")
        surface.blit(spark_hdr, (cx, y))
        cx += spark_w + gap

        for col in col_order:
            hdr = _txt(titles[col])
            surface.blit(hdr, (cx + num_w - hdr.get_width(), y))
            cx += num_w + gap

    def _render_items_row(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        item_id: str,
        item_name: str,
        item_color: tuple[int, int, int],
        name_w: int,
        spark_w: int,
        num_w: int,
        gap: int,
        col_order: tuple[str, ...],
        window_s: int,
        phase: float,
    ) -> None:
        stats = self._stats
        assert stats is not None
        beveled_panel(
            surface,
            rect,
            fill=darken(PALETTE.bg_raised, 0.04),
            border=PALETTE.line,
        )

        # Name column: sprite + label + swatch.
        cx = rect.x + 8
        cy = rect.y + rect.h // 2
        icon = _try_sprite(self.assets, f"item_{item_id}")
        icon_w = 28
        if icon is not None:
            icon_surf = pygame.transform.smoothscale(icon, (icon_w, icon_w))
            surface.blit(icon_surf, (cx, cy - icon_w // 2))
        else:
            swatch = pygame.Rect(cx, cy - 6, 12, 12)
            pygame.draw.rect(surface, item_color, swatch)
        name_surf = self.assets.render_text(
            item_name, TYPE.body, PALETTE.text_strong
        )
        surface.blit(name_surf, (cx + icon_w + 6, cy - name_surf.get_height() // 2))

        # Sparkline column.
        spark_x = rect.x + name_w + gap
        spark_rect = pygame.Rect(spark_x, rect.y + 8, spark_w, rect.h - 16)
        series = stats.net_series(item_id, window_s=max(10, window_s), smooth=3)
        self._render_sparkline(surface, spark_rect, series, item_color)

        # Numeric columns (right-aligned per column).
        def _query(col: str) -> float:
            if col == "now":
                return stats.rate_per_min(item_id, "produced", window_s)
            if col == "avg":
                return stats.avg_per_min(item_id, "produced", window_s)
            if col == "max":
                return stats.max_per_min(item_id, "produced", window_s)
            if col == "min":
                return stats.min_per_min(item_id, "produced", window_s)
            if col == "med":
                return stats.median_per_min(item_id, "produced", window_s)
            if col == "total":
                return float(stats.total(item_id, "produced", 0))
            return 0.0

        cx = spark_x + spark_w + gap
        for col in col_order:
            val = _query(col)
            color = _ACCENT if col in ("now", "avg") else PALETTE.text_strong
            label = _format_rate(val) if col != "total" else _format_int(val)
            if col == "total":
                color = PALETTE.text_strong
            surf = self.assets.render_text(label, TYPE.body, color)
            surface.blit(
                surf,
                (cx + num_w - surf.get_width(), cy - surf.get_height() // 2),
            )
            sub = "/min" if col != "total" else "items"
            sub_surf = self.assets.render_text(sub, TYPE.label, PALETTE.muted)
            surface.blit(
                sub_surf,
                (
                    cx + num_w - sub_surf.get_width(),
                    cy + surf.get_height() // 2 - 2,
                ),
            )
            cx += num_w + gap

    def _render_sparkline(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        series: list[float],
        accent: tuple[int, int, int],
    ) -> None:
        pygame.draw.rect(surface, darken(PALETTE.bg_raised, 0.18), rect)
        pygame.draw.rect(surface, PALETTE.line, rect, 1)
        if not series:
            return
        # Baseline at 0 (net rate).
        hi = max(series)
        lo = min(series)
        span = max(1.0, max(hi, -lo) * 2.0)
        mid_y = rect.centery
        half = (rect.h - 4) / 2
        pts: list[tuple[int, int]] = []
        step = (rect.w - 4) / max(1, len(series) - 1) if len(series) > 1 else 0
        for i, v in enumerate(series):
            px = int(rect.x + 2 + i * step)
            py = int(mid_y - (v / (span / 2)) * half)
            py = max(rect.y + 1, min(rect.bottom - 2, py))
            pts.append((px, py))
        # Zero line.
        pygame.draw.line(
            surface,
            with_alpha(PALETTE.muted, 90),
            (rect.x + 2, mid_y),
            (rect.right - 3, mid_y),
        )
        if len(pts) > 1:
            pygame.draw.lines(surface, accent, False, pts, 1)

    # -- buildings tab ----------------------------------------------------

    def _render_buildings_tab(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        offset: tuple[int, int],
    ) -> None:
        assert self._stats is not None
        from ..buildings.registry import BUILDINGS

        header = self.assets.render_text(
            "PREFABS", TYPE.label, PALETTE.primary
        )
        surface.blit(header, (rect.x, rect.y))

        y = rect.y + header.get_height() + 6
        reveal = self._row_reveal.value
        prefabs = BUILDINGS.all()
        prefab_stats = self._stats.building_stats()
        for i, prefab in enumerate(prefabs):
            row_rect = pygame.Rect(rect.x, y, rect.w, _BUILDING_ROW_H)
            stat = prefab_stats.get(prefab.id)
            active = stat.active_count if stat else 0
            placed = stat.placed_total if stat else 0
            removed = stat.removed_total if stat else 0
            phase = max(0.0, min(1.0, reveal * len(prefabs) - i * 0.5))
            self._render_building_row(
                surface,
                row_rect,
                prefab.sprite_base,
                prefab.name,
                active,
                placed,
                removed,
                phase,
            )
            y += _BUILDING_ROW_H + 6

        # Per-class summary.
        y += _GAP
        class_hdr = self.assets.render_text(
            "CLASSES", TYPE.label, PALETTE.primary
        )
        surface.blit(class_hdr, (rect.x, y))
        y += class_hdr.get_height() + 6
        class_stats = self._stats.building_stats_by_class()
        for key in ("miner", "assembler"):
            stat = class_stats.get(key)
            active = stat.active_count if stat else 0
            placed = stat.placed_total if stat else 0
            removed = stat.removed_total if stat else 0
            row_rect = pygame.Rect(rect.x, y, rect.w, _BUILDING_ROW_H - 10)
            self._render_class_row(
                surface, row_rect, key.upper(), active, placed, removed
            )
            y += _BUILDING_ROW_H - 4

    def _render_building_row(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        sprite_base: str,
        name: str,
        active: int,
        placed: int,
        removed: int,
        phase: float,
    ) -> None:
        beveled_panel(
            surface,
            rect,
            fill=darken(PALETTE.bg_raised, 0.04),
            border=PALETTE.line,
        )
        stripe = pygame.Rect(rect.x, rect.y + 4, 3, rect.h - 8)
        pygame.draw.rect(surface, PALETTE.secondary, stripe)

        # Thumbnail using the "idle" first frame.
        icon_rect = pygame.Rect(
            rect.x + 10, rect.y + (rect.h - 36) // 2, 36, 36
        )
        icon = _try_sprite(self.assets, f"{sprite_base}_idle_f0")
        if icon is not None:
            scaled = pygame.transform.smoothscale(icon, (icon_rect.w, icon_rect.h))
            surface.blit(scaled, icon_rect.topleft)
        else:
            pygame.draw.rect(surface, PALETTE.surface, icon_rect)
            pygame.draw.rect(surface, PALETTE.line, icon_rect, 1)

        name_surf = self.assets.render_text(name, TYPE.h2, PALETTE.text_strong)
        surface.blit(name_surf, (icon_rect.right + _GAP, rect.y + 8))

        # Active / placed / removed triple on the right.
        self._render_stat_triple(
            surface,
            rect,
            ("ACTIVE", str(active), _ACCENT),
            ("PLACED", str(placed), PALETTE.text_strong),
            ("REMOVED", str(removed), PALETTE.muted),
        )

    def _render_class_row(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        active: int,
        placed: int,
        removed: int,
    ) -> None:
        pygame.draw.rect(surface, darken(PALETTE.bg_raised, 0.12), rect)
        pygame.draw.rect(surface, PALETTE.line, rect, 1)
        lbl_surf = self.assets.render_text(label, TYPE.body, PALETTE.text_body)
        surface.blit(
            lbl_surf,
            (rect.x + 10, rect.centery - lbl_surf.get_height() // 2),
        )
        self._render_stat_triple(
            surface,
            rect,
            ("ACTIVE", str(active), _ACCENT),
            ("PLACED", str(placed), PALETTE.text_strong),
            ("REMOVED", str(removed), PALETTE.muted),
        )

    def _render_stat_triple(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *cols: tuple[str, str, tuple[int, int, int]],
    ) -> None:
        col_w = 84
        total_w = col_w * len(cols)
        x = rect.right - total_w - 10
        for label, value, color in cols:
            val_surf = self.assets.render_text(value, TYPE.h2, color)
            lbl_surf = self.assets.render_text(label, TYPE.label, PALETTE.muted)
            surface.blit(
                val_surf,
                (x + col_w - val_surf.get_width() - 4, rect.y + 6),
            )
            surface.blit(
                lbl_surf,
                (
                    x + col_w - lbl_surf.get_width() - 4,
                    rect.bottom - lbl_surf.get_height() - 6,
                ),
            )
            x += col_w

    # -- session tab ------------------------------------------------------

    def _render_session_tab(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        offset: tuple[int, int],
    ) -> None:
        assert self._stats is not None
        session = self._stats.session()

        # Hero: big session timer.
        hero_h = 120
        hero_rect = pygame.Rect(rect.x, rect.y, rect.w, hero_h)
        beveled_panel(
            surface,
            hero_rect,
            fill=darken(PALETTE.bg_raised, 0.1),
            border=PALETTE.line,
        )
        # Soft pulsing aura.
        pulse = 0.5 + 0.5 * math.sin(self._time * 1.4)
        with acquired(hero_rect.size) as glow:
            pygame.draw.circle(
                glow,
                with_alpha(PALETTE.primary, int(30 + 35 * pulse)),
                (hero_rect.w // 2, hero_rect.h // 2),
                int(hero_rect.h * 0.7),
            )
            surface.blit(glow, hero_rect.topleft)

        time_surf = self.assets.render_text(
            _format_duration(session.elapsed_s), TYPE.display, PALETTE.text_strong
        )
        surface.blit(
            time_surf,
            (
                hero_rect.centerx - time_surf.get_width() // 2,
                hero_rect.centery - time_surf.get_height() // 2,
            ),
        )
        sub = self.assets.render_text(
            "SESSION TIME", TYPE.label, PALETTE.muted
        )
        surface.blit(
            sub,
            (
                hero_rect.centerx - sub.get_width() // 2,
                hero_rect.bottom - sub.get_height() - 8,
            ),
        )

        # Small stat tiles below in a 3x2 grid.
        grid_top = hero_rect.bottom + _GAP
        tiles = [
            (
                "ITEMS PRODUCED",
                _format_int(float(session.total_produced)),
                PALETTE.primary,
            ),
            (
                "ITEMS CONSUMED",
                _format_int(float(session.total_consumed)),
                PALETTE.secondary,
            ),
            (
                "PEAK PROD (/MIN)",
                _format_rate(session.peak_global_prod_per_min),
                PALETTE.success,
            ),
            (
                "PEAK USE (/MIN)",
                _format_rate(session.peak_global_cons_per_min),
                PALETTE.warning,
            ),
            (
                "BELT TILES",
                str(session.belt_tile_count),
                PALETTE.text_strong,
            ),
            (
                "BUILDINGS",
                str(session.building_count),
                PALETTE.text_strong,
            ),
            (
                "ITEMS IN WORLD",
                str(session.items_in_world),
                PALETTE.text_body,
            ),
            (
                "OBJECTIVES",
                f"{len(self._objectives.completed) if self._objectives else 0}/"
                f"{len(self._objectives.catalog()) if self._objectives else 0}",
                _ACCENT_SUCCESS,
            ),
        ]
        cols = 4
        rows = (len(tiles) + cols - 1) // cols
        tile_w = (rect.w - _GAP * (cols - 1)) // cols
        tile_h = 66
        for i, (label, value, color) in enumerate(tiles):
            r = i // cols
            c = i % cols
            x = rect.x + c * (tile_w + _GAP)
            y = grid_top + r * (tile_h + _GAP)
            tile_rect = pygame.Rect(x, y, tile_w, tile_h)
            self._render_session_tile(surface, tile_rect, label, value, color)

    def _render_session_tile(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        value: str,
        color: tuple[int, int, int],
    ) -> None:
        beveled_panel(
            surface, rect, fill=PALETTE.bg_raised, border=PALETTE.line
        )
        stripe = pygame.Rect(rect.x, rect.y + 4, 3, rect.h - 8)
        pygame.draw.rect(surface, color, stripe)
        val_surf = self.assets.render_text(value, TYPE.h1, PALETTE.text_strong)
        lbl_surf = self.assets.render_text(label, TYPE.label, PALETTE.muted)
        surface.blit(
            val_surf,
            (
                rect.x + 12,
                rect.y + 10,
            ),
        )
        surface.blit(
            lbl_surf,
            (
                rect.x + 12,
                rect.bottom - lbl_surf.get_height() - 8,
            ),
        )

    # -- scrollbar --------------------------------------------------------

    def _render_scrollbar(
        self, surface: pygame.Surface, rect: pygame.Rect, tab_id: str
    ) -> None:
        max_s = self._max_scroll.get(tab_id, 0.0)
        if max_s <= 0:
            return
        track = pygame.Rect(rect.right - 4, rect.y, 3, rect.h)
        pygame.draw.rect(surface, darken(PALETTE.bg_raised, 0.15), track)
        thumb_h = max(24, int(rect.h * rect.h / (rect.h + max_s)))
        t = self._scroll[tab_id] / max_s
        thumb_y = int(rect.y + (rect.h - thumb_h) * t)
        thumb = pygame.Rect(track.x, thumb_y, track.w, thumb_h)
        pygame.draw.rect(surface, PALETTE.muted, thumb)

    # -- objective completion --------------------------------------------

    def _card_anim_for(self, spec_id: str) -> _CardAnim:
        anim = self._card_anims.get(spec_id)
        if anim is None:
            anim = _CardAnim()
            self._card_anims[spec_id] = anim
        return anim

    def _on_objective_completed(self, spec, at: float) -> None:  # noqa: ANN001
        anim = self._card_anim_for(spec.id)
        anim.pulse = Tween(
            start=1.0, end=0.0, duration=0.9, ease=THEME.anim.ease_out
        )
        anim.bar.set(1.0)
        SFX.play("ui.click")


# -- helpers ---------------------------------------------------------------


def _try_sprite(assets: AssetLoader, key: str) -> pygame.Surface | None:
    try:
        return assets.sprite(key)
    except FileNotFoundError:
        return None
    except Exception:  # pragma: no cover - defensive
        return None


def _format_progress(status: ObjectiveStatus) -> str:
    spec = status.spec
    if spec.kind is ObjectiveKind.SUSTAIN_RATE:
        # Show seconds held out of required hold + required rate.
        held = int(status.progress)
        need = int(spec.hold_s)
        return f"{held}/{need}s  @{int(spec.rate_per_min)}/min"
    if spec.kind is ObjectiveKind.BELT_TILES:
        return f"{int(status.progress)}/{int(status.target)} belts"
    if spec.kind is ObjectiveKind.PLACE_BUILDING_COUNT:
        return f"{int(status.progress)}/{int(status.target)} built"
    return f"{_format_int(status.progress)}/{_format_int(status.target)}"


def _format_int(value: float) -> str:
    v = int(value)
    if v >= 10_000_000:
        return f"{v // 1_000_000}M"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 10_000:
        return f"{v // 1_000}K"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def _format_rate(value: float) -> str:
    if value <= 0:
        return "0"
    if value >= 10_000:
        return f"{value / 1000:.1f}K"
    if value >= 100:
        return f"{int(round(value))}"
    return f"{value:.1f}"


def _format_duration(seconds: float) -> str:
    total = int(max(0, seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)].rstrip() + "..."


__all__ = ["ObjectivesWindow"]
