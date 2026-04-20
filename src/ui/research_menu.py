"""Detail panel for the Research scene.

Design-matched with :class:`~src.ui.structure_menu.StructureMenu` so
both panels feel like siblings: slide-in from the nearest window edge,
staggered per-section reveal, soft drop shadow, beveled body, accent
stripe keyed to the node status. Sections top-to-bottom:

* Header - icon box + title + category + close button.
* Hero band - large sprite with soft accent glow and status chip.
* Effects list - one row per ``Effect`` (chip + label + value).
* Prerequisites - clickable rows that pan the camera to the prereq
  node on the research board.
* Action bar - ``Research`` primary button (disabled when the node
  is locked or already researched).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING

import pygame

from ..audio.sfx import SFX
from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from ..research.info import ResearchInfo, for_node
from ..research.node import ResearchNode
from ..research.state import ResearchState
from .controls import Button
from .widget import Widget

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


PANEL_W = 420
_MIN_PANEL_H = 360
_MARGIN = 24
_PAD = THEME.spacing.lg
_SECTION_GAP = THEME.spacing.md

_HEADER_H = 56
_HERO_H = 120
_EFFECT_ROW_H = 26
_PREREQ_ROW_H = 24
_ACTION_H = 44
_CLOSE_SIZE = 24
_SHADOW_ALPHA = 150
_SLIDE_MARGIN = 24

_ICON_BOX = 44
_HERO_ICON = 80


# Per-section reveal phases (0..1 across the reveal tween).
_PHASES: dict[str, tuple[float, float]] = {
    "header": (0.00, 0.30),
    "hero": (0.15, 0.55),
    "effects": (0.30, 0.75),
    "prereqs": (0.45, 0.85),
    "action": (0.60, 1.00),
}


def _phase_progress(reveal: float, key: str) -> float:
    start, end = _PHASES[key]
    if end <= start:
        return 1.0
    return max(0.0, min(1.0, (reveal - start) / (end - start)))


def _phase_offset(p: float, magnitude: int = 12) -> int:
    """Ease-out vertical slide for a freshly-revealed section."""
    eased = 1.0 - (1.0 - p) * (1.0 - p)
    return int(round((1.0 - eased) * magnitude))


class ResearchMenu:
    """Slide-in research detail panel."""

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self._node: ResearchNode | None = None
        self._info: ResearchInfo | None = None
        self._state: ResearchState | None = None
        self._window_size: tuple[int, int] = (0, 0)
        self._is_open: bool = False
        self._closing: bool = False
        self._time: float = 0.0

        self._on_research: Callable[[ResearchNode], None] | None = None
        self._on_focus_prereq: Callable[[str], None] | None = None

        # Slide + reveal.
        self._slide_progress = Tween(
            start=0.0, end=0.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out
        )
        self._slide_progress.done = True
        self._slide_value: float = 0.0
        self._reveal_anim = AnimValue(value=0.0, target=0.0, speed=6.5)
        self._status_pulse = AnimValue(value=0.0, target=0.0, speed=4.5)

        self._close_btn = Widget(pygame.Rect(0, 0, _CLOSE_SIZE, _CLOSE_SIZE))
        self._action_btn: Button | None = None
        self._prereq_widgets: list[Widget] = []

    # -- callbacks ---------------------------------------------------------

    def bind(
        self,
        *,
        on_research: Callable[[ResearchNode], None] | None = None,
        on_focus_prereq: Callable[[str], None] | None = None,
    ) -> None:
        self._on_research = on_research
        self._on_focus_prereq = on_focus_prereq

    def attach_state(self, state: ResearchState) -> None:
        self._state = state

    # -- layout ------------------------------------------------------------

    def layout(self, window_size: tuple[int, int]) -> None:
        self._window_size = window_size

    def _resting_pos(self) -> tuple[int, int]:
        w, h = self._window_size
        x = max(_MARGIN, w - PANEL_W - _MARGIN)
        panel_h = self._panel_height()
        y = max(_MARGIN, (h - panel_h) // 2)
        return (x, y)

    def _panel_height(self) -> int:
        base = _HEADER_H + _HERO_H + _ACTION_H + _PAD * 5 + _SECTION_GAP * 2
        if self._info is None:
            return max(_MIN_PANEL_H, base)
        effects = len(self._info.effect_rows) * _EFFECT_ROW_H
        prereqs = 0
        if self._info.prereq_rows:
            prereqs = len(self._info.prereq_rows) * _PREREQ_ROW_H + 18 + _SECTION_GAP
        blurb_lines = _wrap(self._info.blurb, 42)
        blurb_h = len(blurb_lines) * 16 + (_SECTION_GAP if blurb_lines else 0)
        return max(_MIN_PANEL_H, base + effects + prereqs + blurb_h + 18)

    def _current_pos(self) -> tuple[int, int]:
        rx, ry = self._resting_pos()
        off = 1.0 - max(0.0, min(1.0, self._slide_value))
        return (int(rx + (PANEL_W + _SLIDE_MARGIN) * off), int(ry))

    def rect(self) -> pygame.Rect | None:
        if not self._is_open:
            return None
        x, y = self._current_pos()
        return pygame.Rect(x, y, PANEL_W, self._panel_height())

    # -- API ---------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open_node(self, node: ResearchNode) -> None:
        was_closing = self._is_open and self._closing
        self._node = node
        self._is_open = True
        self._closing = False
        self._reveal_anim.set(0.0)
        self._reveal_anim.to(1.0)
        self._status_pulse.set(0.0)
        start = float(self._slide_value) if was_closing else 0.0
        self._slide_progress = Tween(
            start=start,
            end=1.0,
            duration=THEME.anim.slow,
            ease=THEME.anim.ease_out,
        )
        self._slide_value = start
        SFX.play("ui.open")

    def close(self) -> None:
        if not self._is_open:
            return
        self._closing = True
        self._reveal_anim.to(0.0)
        self._slide_progress = Tween(
            start=float(self._slide_value),
            end=0.0,
            duration=THEME.anim.base,
            ease=THEME.anim.ease_out,
        )

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self._is_open:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return True
        return False

    def flash_status(self) -> None:
        """Briefly pulse the status chip (used on successful research)."""
        self._status_pulse.set(1.0)
        self._status_pulse.to(0.0)

    # -- update ------------------------------------------------------------

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_released: bool,
    ) -> None:
        self._time += dt
        self._slide_value = float(self._slide_progress.update(dt))
        self._reveal_anim.update(dt)
        self._status_pulse.update(dt)

        if self._closing and self._slide_progress.done:
            self._is_open = False
            self._closing = False
            self._node = None
            self._info = None
            self._action_btn = None
            self._prereq_widgets = []
            return
        if not self._is_open or self._node is None or self._state is None:
            return

        self._info = for_node(self._node, self._state)

        rect = self.rect()
        if rect is None:
            return

        self._close_btn.rect = pygame.Rect(
            rect.right - _CLOSE_SIZE - _PAD,
            rect.top + _PAD,
            _CLOSE_SIZE,
            _CLOSE_SIZE,
        )
        self._close_btn.update(dt, mouse_pos, mouse_down)
        if self._close_btn.clicked(mouse_released):
            SFX.play("ui.close")
            self.close()

        self._update_action_button(rect, dt, mouse_pos, mouse_down, mouse_released)
        self._update_prereq_widgets(rect, dt, mouse_pos, mouse_down, mouse_released)

    def _update_action_button(
        self,
        rect: pygame.Rect,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_released: bool,
    ) -> None:
        assert self._info is not None and self._node is not None
        info = self._info

        btn_rect = pygame.Rect(
            rect.left + _PAD,
            rect.bottom - _ACTION_H - _PAD,
            rect.w - _PAD * 2,
            _ACTION_H,
        )
        enabled = info.is_available
        if info.is_researched:
            label = "Researched"
            kind = "ghost"
        elif info.is_locked:
            label = "Locked - prerequisites required"
            kind = "ghost"
        else:
            label = "Research"
            kind = "primary"

        node = self._node
        if self._action_btn is None:
            self._action_btn = Button(
                btn_rect,
                label,
                kind=kind,
                enabled=enabled,
                on_click=lambda n=node: self._trigger_research(n),
            )
        else:
            self._action_btn.rect = btn_rect
            self._action_btn.label = label
            self._action_btn.kind = kind
            self._action_btn.enabled = enabled
            self._action_btn.on_click = lambda n=node: self._trigger_research(n)
        self._action_btn.update(
            dt, mouse_pos, mouse_down, mouse_released=mouse_released
        )

    def _trigger_research(self, node: ResearchNode) -> None:
        if self._on_research is not None:
            self._on_research(node)

    def _update_prereq_widgets(
        self,
        rect: pygame.Rect,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_released: bool,
    ) -> None:
        assert self._info is not None
        count = len(self._info.prereq_rows)
        while len(self._prereq_widgets) < count:
            self._prereq_widgets.append(
                Widget(pygame.Rect(0, 0, 0, _PREREQ_ROW_H))
            )
        del self._prereq_widgets[count:]
        y = self._prereq_section_y(rect)
        for i, row in enumerate(self._info.prereq_rows):
            w = self._prereq_widgets[i]
            w.rect = pygame.Rect(
                rect.left + _PAD,
                y + i * _PREREQ_ROW_H,
                rect.w - _PAD * 2,
                _PREREQ_ROW_H - 2,
            )
            w.update(dt, mouse_pos, mouse_down)
            if w.clicked(mouse_released):
                SFX.play("ui.click_soft")
                if self._on_focus_prereq is not None:
                    self._on_focus_prereq(row.node_id)

    def _prereq_section_y(self, rect: pygame.Rect) -> int:
        assert self._info is not None
        y = rect.top + _HEADER_H + _SECTION_GAP + _HERO_H + _SECTION_GAP
        blurb_lines = _wrap(self._info.blurb, 42)
        y += len(blurb_lines) * 16 + (_SECTION_GAP if blurb_lines else 0)
        y += len(self._info.effect_rows) * _EFFECT_ROW_H + _SECTION_GAP + 18
        return y

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        rect = self.rect()
        if rect is None or self._info is None:
            return
        reveal = max(0.0, min(1.0, self._reveal_anim.value))
        alpha = int(255 * reveal)
        if alpha <= 0:
            return

        with acquired((rect.w + 12, rect.h + 12)) as shadow:
            shadow.fill(with_alpha(PALETTE.bg_deep, int(_SHADOW_ALPHA * reveal)))
            surface.blit(shadow, (rect.x - 3, rect.y + 6))

        with acquired(rect.size) as panel:
            body = pygame.Rect(0, 0, rect.w, rect.h)
            beveled_panel(
                panel, body, fill=PALETTE.bg_base, border=PALETTE.line
            )
            stripe = pygame.Rect(0, 4, 4, rect.h - 8)
            pygame.draw.rect(panel, self._info.accent, stripe)

            self._render_header(panel, body, reveal)
            self._render_hero(panel, body, reveal)
            self._render_effects(panel, body, reveal)
            self._render_prereqs(panel, body, reveal)
            self._render_action(panel, body, reveal)

            panel.set_alpha(alpha)
            surface.blit(panel, rect.topleft)

        # The action button draws directly to the main surface so hover
        # glows stay crisp above the shadow.
        if self._action_btn is not None and reveal > 0.5:
            self._action_btn.render(surface, self.assets)

        self._render_close(surface, reveal)

    def _render_header(
        self, panel: pygame.Surface, body: pygame.Rect, reveal: float
    ) -> None:
        assert self._info is not None
        p = _phase_progress(reveal, "header")
        oy = _phase_offset(p)
        info = self._info

        header_rect = pygame.Rect(body.x, body.y + oy, body.w, _HEADER_H)
        pygame.draw.line(
            panel,
            PALETTE.line,
            (header_rect.left + _PAD, header_rect.bottom - 1),
            (header_rect.right - _PAD, header_rect.bottom - 1),
        )

        icon_rect = pygame.Rect(
            header_rect.left + _PAD,
            header_rect.top + (_HEADER_H - _ICON_BOX) // 2,
            _ICON_BOX,
            _ICON_BOX,
        )
        self._draw_icon_box(panel, icon_rect, info, small=True)

        tx = icon_rect.right + THEME.spacing.md
        ty = icon_rect.top - 2
        cat = self.assets.render_text(
            info.category.upper(), TYPE.label, PALETTE.muted
        )
        title = self.assets.render_text(info.title, TYPE.h2, PALETTE.text_strong)
        panel.blit(cat, (tx, ty))
        panel.blit(title, (tx, ty + cat.get_height()))

    def _render_hero(
        self, panel: pygame.Surface, body: pygame.Rect, reveal: float
    ) -> None:
        assert self._info is not None
        p = _phase_progress(reveal, "hero")
        oy = _phase_offset(p, magnitude=16)
        info = self._info

        hero_y = body.y + _HEADER_H + _SECTION_GAP + oy
        hero_rect = pygame.Rect(body.x + _PAD, hero_y, body.w - _PAD * 2, _HERO_H)
        beveled_panel(
            panel,
            hero_rect,
            fill=darken(PALETTE.bg_raised, 0.1),
            border=PALETTE.line,
        )

        # Soft accent glow behind the hero icon.
        pulse = 0.5 + 0.5 * math.sin(self._time * 1.6)
        flash = self._status_pulse.value
        glow_alpha = int(40 + 60 * pulse + 160 * flash) if info.is_available or flash > 0.01 else 25
        with acquired(hero_rect.size) as glow:
            pygame.draw.circle(
                glow,
                with_alpha(info.accent, min(255, max(0, glow_alpha))),
                (hero_rect.w // 2, hero_rect.h // 2),
                int(hero_rect.h * 0.55),
            )
            panel.blit(glow, hero_rect.topleft)

        icon_rect = pygame.Rect(
            hero_rect.centerx - _HERO_ICON // 2,
            hero_rect.top + 10,
            _HERO_ICON,
            _HERO_ICON,
        )
        self._draw_icon_box(panel, icon_rect, info, small=False)

        # Status chip.
        chip_label = {
            "researched": "RESEARCHED",
            "available": "AVAILABLE",
            "locked": "LOCKED",
        }[info.status]
        chip_surf = self.assets.render_text(
            chip_label, TYPE.label, PALETTE.text_strong
        )
        chip_w = chip_surf.get_width() + 16
        chip_h = chip_surf.get_height() + 6
        chip_rect = pygame.Rect(
            hero_rect.centerx - chip_w // 2,
            hero_rect.bottom - chip_h - 10,
            chip_w,
            chip_h,
        )
        chip_bg = lighten(info.accent, 0.1 * flash)
        pygame.draw.rect(panel, with_alpha(chip_bg, 80), chip_rect)
        pygame.draw.rect(panel, info.accent, chip_rect, 2)
        panel.blit(
            chip_surf,
            (chip_rect.centerx - chip_surf.get_width() // 2, chip_rect.y + 3),
        )

        # Blurb below the hero.
        blurb_lines = _wrap(info.blurb, 42)
        by = hero_rect.bottom + THEME.spacing.sm
        for line in blurb_lines:
            s = self.assets.render_text(line, TYPE.caption, PALETTE.text_body)
            panel.blit(s, (body.x + _PAD, by))
            by += 16

    def _render_effects(
        self, panel: pygame.Surface, body: pygame.Rect, reveal: float
    ) -> None:
        assert self._info is not None
        p = _phase_progress(reveal, "effects")
        if p <= 0.01:
            return
        oy = _phase_offset(p, magnitude=10)
        info = self._info

        blurb_lines = _wrap(info.blurb, 42)
        y0 = (
            body.y
            + _HEADER_H
            + _SECTION_GAP
            + _HERO_H
            + THEME.spacing.sm
            + len(blurb_lines) * 16
            + _SECTION_GAP
            + oy
        )
        label = self.assets.render_text("EFFECTS", TYPE.label, PALETTE.muted)
        panel.blit(label, (body.x + _PAD, y0))
        y = y0 + label.get_height() + 4

        for i, r in enumerate(info.effect_rows):
            row_y = y + i * _EFFECT_ROW_H
            # Chip
            chip = pygame.Rect(body.x + _PAD, row_y + 6, 10, 10)
            pygame.draw.rect(panel, info.accent, chip)
            pygame.draw.rect(panel, PALETTE.line, chip, 1)

            name_surf = self.assets.render_text(
                r.label, TYPE.body, PALETTE.text_body
            )
            panel.blit(name_surf, (chip.right + THEME.spacing.sm, row_y + 2))

            val_surf = self.assets.render_text(
                r.value, TYPE.body, PALETTE.text_strong
            )
            panel.blit(
                val_surf,
                (body.right - _PAD - val_surf.get_width(), row_y + 2),
            )

    def _render_prereqs(
        self, panel: pygame.Surface, body: pygame.Rect, reveal: float
    ) -> None:
        assert self._info is not None
        if not self._info.prereq_rows:
            return
        p = _phase_progress(reveal, "prereqs")
        if p <= 0.01:
            return
        oy = _phase_offset(p, magnitude=10)
        info = self._info

        blurb_lines = _wrap(info.blurb, 42)
        y0 = (
            body.y
            + _HEADER_H
            + _SECTION_GAP
            + _HERO_H
            + THEME.spacing.sm
            + len(blurb_lines) * 16
            + _SECTION_GAP
            + len(info.effect_rows) * _EFFECT_ROW_H
            + _SECTION_GAP
            + oy
        )
        label = self.assets.render_text(
            "PREREQUISITES", TYPE.label, PALETTE.muted
        )
        panel.blit(label, (body.x + _PAD, y0))
        y = y0 + label.get_height() + 4

        for i, row in enumerate(info.prereq_rows):
            row_y = y + i * _PREREQ_ROW_H
            widget = self._prereq_widgets[i] if i < len(self._prereq_widgets) else None
            hover = widget.hover_anim.value if widget is not None else 0.0

            glyph = "✓" if row.satisfied else "✕"
            glyph_color = PALETTE.success if row.satisfied else PALETTE.danger
            name_color = (
                lighten(PALETTE.text_body, 0.15 * hover)
                if row.satisfied
                else PALETTE.muted
            )

            if hover > 0.02:
                hover_rect = pygame.Rect(
                    body.x + _PAD - 4,
                    row_y - 2,
                    body.w - _PAD * 2 + 8,
                    _PREREQ_ROW_H - 2,
                )
                pygame.draw.rect(
                    panel,
                    with_alpha(PALETTE.line, int(40 + 60 * hover)),
                    hover_rect,
                )

            g = self.assets.render_text(glyph, TYPE.body, glyph_color)
            panel.blit(g, (body.x + _PAD, row_y + 2))
            n = self.assets.render_text(row.name, TYPE.body, name_color)
            panel.blit(n, (body.x + _PAD + 20, row_y + 2))

            hint = "Focus" if hover > 0.4 else ""
            if hint:
                h = self.assets.render_text(hint, TYPE.label, PALETTE.muted)
                panel.blit(
                    h,
                    (body.right - _PAD - h.get_width(), row_y + 4),
                )

    def _render_action(
        self, panel: pygame.Surface, body: pygame.Rect, reveal: float
    ) -> None:
        # Divider above the action zone.
        p = _phase_progress(reveal, "action")
        if p <= 0.01:
            return
        divider_y = body.bottom - _ACTION_H - _PAD - 6
        pygame.draw.line(
            panel,
            PALETTE.line,
            (body.x + _PAD, divider_y),
            (body.right - _PAD, divider_y),
        )

    def _render_close(self, surface: pygame.Surface, reveal: float) -> None:
        p = _phase_progress(reveal, "header")
        if p <= 0.05:
            return
        rect = self._close_btn.rect
        hover = self._close_btn.hover_anim.value
        press = self._close_btn.press_anim.value
        color = lighten(PALETTE.text_body, 0.25 * hover - 0.15 * press)
        pygame.draw.rect(surface, PALETTE.bg_raised, rect)
        pygame.draw.rect(surface, PALETTE.line, rect, 1)
        pad = 6
        pygame.draw.line(
            surface, color, (rect.left + pad, rect.top + pad),
            (rect.right - pad, rect.bottom - pad), 2,
        )
        pygame.draw.line(
            surface, color, (rect.right - pad, rect.top + pad),
            (rect.left + pad, rect.bottom - pad), 2,
        )

    # -- icon helpers ------------------------------------------------------

    def _draw_icon_box(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        info: ResearchInfo,
        *,
        small: bool,
    ) -> None:
        beveled_panel(
            surface, rect, fill=darken(PALETTE.bg_raised, 0.12), border=PALETTE.line
        )
        icon = self._resolve_icon_surface(info, rect.w - 8)
        if icon is not None:
            ix = rect.centerx - icon.get_width() // 2
            iy = rect.centery - icon.get_height() // 2
            if info.is_locked:
                tinted = icon.copy()
                veil = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
                veil.fill(with_alpha(PALETTE.bg_deep, 140))
                tinted.blit(veil, (0, 0))
                surface.blit(tinted, (ix, iy))
            else:
                surface.blit(icon, (ix, iy))
        if info.is_researched and not small:
            # Tiny checkmark badge on the hero icon.
            badge_r = 10
            cx = rect.right - badge_r - 2
            cy = rect.top + badge_r + 2
            pygame.draw.circle(surface, PALETTE.success, (cx, cy), badge_r)
            pygame.draw.circle(surface, PALETTE.bg_deep, (cx, cy), badge_r, 1)
            pygame.draw.lines(
                surface,
                PALETTE.bg_deep,
                False,
                [(cx - 4, cy), (cx - 1, cy + 3), (cx + 4, cy - 3)],
                2,
            )

    def _resolve_icon_surface(
        self, info: ResearchInfo, target: int
    ) -> pygame.Surface | None:
        if info.icon_sprite_key is not None:
            try:
                base = self.assets.sprite(info.icon_sprite_key)
            except FileNotFoundError:
                base = None
        else:
            base = None
        if base is None and info.icon_item is not None:
            try:
                base = self.assets.sprite(info.icon_item.sprite_key)
            except FileNotFoundError:
                base = None
        if base is None:
            return None
        if base.get_width() == target:
            return base
        return pygame.transform.smoothscale(base, (target, target))


def _wrap(text: str, max_chars: int) -> list[str]:
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for w in words:
        add = len(w) + (1 if current else 0)
        if length + add > max_chars and current:
            lines.append(" ".join(current))
            current = [w]
            length = len(w)
        else:
            current.append(w)
            length += add
    if current:
        lines.append(" ".join(current))
    return lines


__all__ = ["PANEL_W", "ResearchMenu"]
