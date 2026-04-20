"""Sprite Studio: in-game overlay for tweaking and regenerating structure sprites.

Opens on F4 as a right-docked panel mirroring :class:`StructureMenu`'s
slide-in idiom. A left rail lists every editable structure spec; the
preview pane cycles live ``active`` frames at ``STRUCTURE_ANIM_HZ``; the
knob panel mutates the live spec registry; action buttons regenerate
sprites to disk, reload the asset loader caches so the world picks up
the new look on the next frame, and persist a diff to
``assets/sprites/overrides.json``.

The Studio is inert when closed and imposes no cost on the hot path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pygame

from ..assets import sprites as sprites_api
from ..assets.sprites import specs as specs_mod
from ..assets.sprites.catalog import entries_for_spec
from ..assets.sprites.specs import SIDES, StructureSpec
from ..core import config
from ..design.palette import PALETTE, Color, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


_PANEL_W = 980
_PANEL_MARGIN_Y = 32
_PANEL_MIN_H = 720
_HEADER_H = 52
_CLOSE_SIZE = 28
_PAD = THEME.spacing.lg
_SECTION_GAP = THEME.spacing.md

_LIST_W = 248
_ROW_H = 34

_PREVIEW_BIG = 420   # px: large preview square (flexes down on small windows)
_PREVIEW_STRIP_ITEM = 56
_THUMB_SIZE = 72     # tile-scale thumbnail

_BUTTON_H = 42
_STEPPER_W = 170
_STEPPER_H = 34

_ACCENT = PALETTE.primary


@dataclass
class _Hit:
    """One clickable hit region in the current frame."""

    rect: pygame.Rect
    payload: object
    kind: str = "click"          # "click" | "stepper_dec" | "stepper_inc" | "cycle_prev" | "cycle_next"


class SpriteStudio:
    """F4-toggled in-game spec editor + sprite regenerator."""

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self._is_open: bool = False
        self._closing: bool = False
        self._window_size: tuple[int, int] = (config.WINDOW_W, config.WINDOW_H)

        self._selected: str = self._default_spec_id()
        self._time: float = 0.0

        # Slide-in progress (0 -> offscreen right, 1 -> docked).
        self._slide = Tween(
            start=0.0, end=0.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out
        )
        self._slide.done = True
        self._slide_value: float = 0.0

        # Per-frame hit list rebuilt during render; consumed by handle_event.
        self._hits: list[_Hit] = []
        self._hover_payload: object | None = None
        self._hover_strength = AnimValue(value=0.0, speed=16.0)
        self._regen_pulse = Tween(
            start=0.0, end=0.0, duration=THEME.anim.fast, ease=THEME.anim.ease_out
        )
        self._regen_pulse.done = True
        self._status: str = ""
        self._status_fade = AnimValue(value=0.0, speed=2.5)

        # Row-stagger for the list on first open.
        self._row_reveal = AnimValue(value=0.0, speed=6.0)

    # -- lifecycle ---------------------------------------------------------

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
            start=start, end=1.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out
        )
        self._slide_value = start
        self._row_reveal.set(0.0)
        self._row_reveal.to(1.0)

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

    # -- event handling ----------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Consume an event if the studio is open. Returns True on consume."""
        if not self._is_open:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close()
                return True
            if event.key == pygame.K_F4:
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
        if event.type == pygame.MOUSEWHEEL and self._rect().collidepoint(
            pygame.mouse.get_pos()
        ):
            # Swallow scroll over the panel so world zoom doesn't fire.
            return True
        return False

    # -- update / render ---------------------------------------------------

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
        self._slide_value = self._slide.update(dt)
        if self._closing and self._slide.done and self._slide_value <= 0.001:
            self._is_open = False
            self._closing = False
        self._regen_pulse.update(dt)
        self._hover_strength.update(dt)
        self._row_reveal.update(dt)
        self._status_fade.update(dt)

        hit = self._hit_at(mouse_pos)
        self._hover_payload = hit.payload if hit is not None else None
        self._hover_strength.to(1.0 if hit is not None else 0.0)

    def render(self, surface: pygame.Surface) -> None:
        if not self._is_open and self._slide_value <= 0.0:
            return
        self._hits.clear()

        rect = self._rect()
        beveled_panel(surface, rect, fill=PALETTE.bg_base, border=PALETTE.line)

        self._render_header(surface, rect)
        list_rect, content_rect = self._split(rect)
        self._render_list(surface, list_rect)

        spec = specs_mod.STRUCTURE_SPECS.get(self._selected)
        if spec is not None:
            self._render_preview(surface, content_rect, spec)
            self._render_knobs(surface, content_rect, spec)
            self._render_actions(surface, content_rect)

        self._render_status(surface, rect)

    # -- rect / layout helpers --------------------------------------------

    def _rect(self) -> pygame.Rect:
        w, h = self._window_size
        panel_h = max(_PANEL_MIN_H, h - _PANEL_MARGIN_Y * 2)
        panel_h = min(panel_h, h - 20)
        docked_x = w - _PANEL_W - 16
        offscreen_x = w + 16
        x = int(offscreen_x + (docked_x - offscreen_x) * self._slide_value)
        y = (h - panel_h) // 2
        return pygame.Rect(x, y, _PANEL_W, panel_h)

    def _split(self, rect: pygame.Rect) -> tuple[pygame.Rect, pygame.Rect]:
        inner_top = rect.top + _HEADER_H
        inner_h = rect.bottom - inner_top - _PAD
        list_rect = pygame.Rect(
            rect.left + _PAD, inner_top, _LIST_W, inner_h
        )
        content_rect = pygame.Rect(
            list_rect.right + _PAD,
            inner_top,
            rect.right - _PAD - (list_rect.right + _PAD),
            inner_h,
        )
        return list_rect, content_rect

    # -- header ------------------------------------------------------------

    def _render_header(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        header_rect = pygame.Rect(rect.x, rect.y, rect.w, _HEADER_H)
        pygame.draw.rect(surface, darken(PALETTE.bg_base, 0.15), header_rect)
        pygame.draw.line(
            surface,
            PALETTE.line,
            (header_rect.x, header_rect.bottom - 1),
            (header_rect.right - 1, header_rect.bottom - 1),
        )
        title = self.assets.render_text("SPRITE STUDIO", TYPE.h1, PALETTE.text_strong)
        surface.blit(title, (rect.x + _PAD, rect.y + (_HEADER_H - title.get_height()) // 2))

        sub = self.assets.render_text(
            "F4 to toggle  -  ESC to close", TYPE.body, PALETTE.muted
        )
        surface.blit(
            sub,
            (
                rect.x + _PAD + title.get_width() + _PAD,
                rect.y + (_HEADER_H - sub.get_height()) // 2,
            ),
        )

        close_rect = pygame.Rect(
            rect.right - _CLOSE_SIZE - _PAD,
            rect.y + (_HEADER_H - _CLOSE_SIZE) // 2,
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

    # -- list --------------------------------------------------------------

    def _render_list(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        beveled_panel(surface, rect, fill=darken(PALETTE.bg_base, 0.08), border=PALETTE.line)
        caption = self.assets.render_text("STRUCTURES", TYPE.h2, PALETTE.primary)
        surface.blit(caption, (rect.x + _PAD // 2, rect.y + _PAD // 2))

        y = rect.y + _PAD + caption.get_height()
        ids = sorted(specs_mod.STRUCTURE_SPECS.keys())
        reveal = self._row_reveal.value
        for i, sid in enumerate(ids):
            row_phase = max(
                0.0, min(1.0, reveal * len(ids) - i * 0.6)
            )
            row_rect = pygame.Rect(rect.x + 4, y, rect.w - 8, _ROW_H)
            selected = sid == self._selected
            hovered = self._hover_payload == ("select", sid)
            bg = (
                lighten(PALETTE.bg_raised, 0.1)
                if selected
                else (lighten(PALETTE.bg_raised, 0.04) if hovered else PALETTE.bg_raised)
            )
            if row_phase < 1.0:
                with acquired(row_rect.size) as ghost:
                    ghost.fill(with_alpha(bg, int(255 * row_phase)))
                    surface.blit(ghost, row_rect.topleft)
            else:
                pygame.draw.rect(surface, bg, row_rect)
            if selected:
                pygame.draw.rect(surface, _ACCENT, row_rect, 1)
            spec = specs_mod.STRUCTURE_SPECS[sid]
            swatch = pygame.Rect(row_rect.x + 6, row_rect.y + 8, 10, 10)
            pygame.draw.rect(surface, spec.accent.color, swatch)
            pygame.draw.rect(surface, darken(spec.accent.color, 0.4), swatch, 1)
            label = self.assets.render_text(sid, TYPE.body, PALETTE.text_body)
            surface.blit(
                label,
                (
                    swatch.right + 6,
                    row_rect.y + (row_rect.h - label.get_height()) // 2,
                ),
            )
            self._hits.append(_Hit(row_rect, ("select", sid)))
            y += _ROW_H + 2

    # -- preview -----------------------------------------------------------

    def _knob_panel_rect(self, content_rect: pygame.Rect) -> pygame.Rect:
        """Anchor the knob panel to the bottom of the content so the preview
        can flex vertically. Height is sized for 4 rows + title + padding.
        """
        rows = 4
        row_pitch = _STEPPER_H + 8
        title_h = TYPE.h2.size + 6
        panel_h = _PAD // 2 + title_h + _PAD // 2 + rows * row_pitch + _PAD // 2
        bottom = content_rect.bottom - _BUTTON_H - _PAD * 2
        top = bottom - panel_h
        return pygame.Rect(content_rect.x, top, content_rect.w, panel_h)

    def _render_preview(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        spec: StructureSpec,
    ) -> None:
        hz = max(0.1, config.STRUCTURE_ANIM_HZ)
        frames = max(1, config.STRUCTURE_FRAMES)
        cycle_frame = int(self._time * hz) % frames

        preview_top = rect.top
        # Flex preview to fill everything above the knob panel.
        knob_top = self._knob_panel_rect(rect).top
        label_h = TYPE.body.size + 6
        strip_gap = 10
        label_gap = 4
        top_pad = 8
        max_target = (
            knob_top
            - preview_top
            - top_pad
            - strip_gap
            - _PREVIEW_STRIP_ITEM
            - label_gap
            - label_h
            - 12
        )
        target = max(96, min(_PREVIEW_BIG, rect.w - 32, max_target))

        fw, fh = spec.footprint
        base = sprite_from_spec(spec, "active", cycle_frame)
        preview_surf = pygame.transform.scale(base, (target, target))

        px = rect.x + (rect.w - target) // 2
        py = preview_top + top_pad
        # Soft drop-shadow
        with acquired((target + 8, target + 8)) as shadow:
            pygame.draw.rect(
                shadow,
                with_alpha(PALETTE.bg_deep, 160),
                shadow.get_rect().inflate(-2, -2),
                border_radius=2,
            )
            surface.blit(shadow, (px - 4, py - 2))
        surface.blit(preview_surf, (px, py))
        pygame.draw.rect(
            surface, PALETTE.line, pygame.Rect(px - 1, py - 1, target + 2, target + 2), 1
        )

        # Frame strip
        strip_y = py + target + 10
        strip_h = _PREVIEW_STRIP_ITEM
        strip_x = rect.x + (rect.w - (_PREVIEW_STRIP_ITEM + 4) * frames) // 2
        for i in range(frames):
            cell = pygame.Rect(
                strip_x + i * (_PREVIEW_STRIP_ITEM + 4),
                strip_y,
                _PREVIEW_STRIP_ITEM,
                strip_h,
            )
            pygame.draw.rect(surface, PALETTE.bg_raised, cell)
            frame_surf = sprite_from_spec(spec, "active", i)
            scaled = pygame.transform.scale(
                frame_surf, (_PREVIEW_STRIP_ITEM, _PREVIEW_STRIP_ITEM)
            )
            surface.blit(scaled, cell.topleft)
            border = _ACCENT if i == cycle_frame else PALETTE.line
            pygame.draw.rect(surface, border, cell, 1)

        label = self.assets.render_text(
            f"{spec.id}   footprint {fw}x{fh}   frame {cycle_frame}/{frames - 1}",
            TYPE.body,
            PALETTE.muted,
        )
        surface.blit(label, (rect.x, strip_y + strip_h + 4))

    # -- knobs -------------------------------------------------------------

    def _render_knobs(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        spec: StructureSpec,
    ) -> None:
        panel = self._knob_panel_rect(rect)
        beveled_panel(surface, panel, fill=darken(PALETTE.bg_base, 0.06), border=PALETTE.line)

        y_top = panel.y + _PAD // 2
        title = self.assets.render_text("PARAMETERS", TYPE.h2, PALETTE.primary)
        surface.blit(title, (panel.x + _PAD // 2, y_top))
        y_rows_start = y_top + title.get_height() + _PAD // 2

        rows: list[tuple[str, str, object, object]] = [
            (
                "Accent Side",
                spec.accent.side,
                ("knob", "accent_side", -1),
                ("knob", "accent_side", +1),
            ),
            (
                "Accent Thickness",
                str(spec.accent.thickness),
                ("knob", "accent_thickness", -1),
                ("knob", "accent_thickness", +1),
            ),
            (
                "Chassis Bolts",
                str(spec.chassis.bolts),
                ("knob", "bolts", -1),
                ("knob", "bolts", +1),
            ),
            (
                "Badge Size",
                str(spec.badge.size_at_64),
                ("knob", "badge_size", -1),
                ("knob", "badge_size", +1),
            ),
            (
                "LED Count",
                str(spec.lights.count),
                ("knob", "led_count", -1),
                ("knob", "led_count", +1),
            ),
            (
                "LED Pattern",
                _pattern_name(spec.lights.pattern),
                ("knob", "led_pattern", -1),
                ("knob", "led_pattern", +1),
            ),
            (
                "Overlay",
                spec.overlay.kind,
                ("knob", "overlay_kind", -1),
                ("knob", "overlay_kind", +1),
            ),
            (
                "Overlay Size",
                str(spec.overlay.size_at_64),
                ("knob", "overlay_size", -1),
                ("knob", "overlay_size", +1),
            ),
        ]

        # Two-column grid — roomier at the new panel width.
        col_gap = _PAD
        col_w = (panel.w - _PAD * 2 - col_gap) // 2
        col0_x = panel.x + _PAD
        col1_x = col0_x + col_w + col_gap
        per_col = (len(rows) + 1) // 2
        for i, (label_text, value_text, dec_payload, inc_payload) in enumerate(rows):
            col = 0 if i < per_col else 1
            row_in_col = i if col == 0 else i - per_col
            x = col0_x if col == 0 else col1_x
            y = y_rows_start + row_in_col * (_STEPPER_H + 8)
            self._render_stepper_row(
                surface,
                x,
                col_w,
                y,
                label_text,
                value_text,
                dec_payload,
                inc_payload,
            )

    def _render_stepper_row(
        self,
        surface: pygame.Surface,
        col_x: int,
        col_w: int,
        y: int,
        label_text: str,
        value_text: str,
        dec_payload: object,
        inc_payload: object,
    ) -> None:
        label = self.assets.render_text(label_text, TYPE.body, PALETTE.text_body)
        lx = col_x
        ly = y + (_STEPPER_H - label.get_height()) // 2
        surface.blit(label, (lx, ly))

        stepper_right = col_x + col_w
        stepper_x = stepper_right - _STEPPER_W
        dec_rect = pygame.Rect(stepper_x, y, _STEPPER_H, _STEPPER_H)
        inc_rect = pygame.Rect(stepper_right - _STEPPER_H, y, _STEPPER_H, _STEPPER_H)
        value_rect = pygame.Rect(
            dec_rect.right + 4, y, inc_rect.left - dec_rect.right - 8, _STEPPER_H
        )

        self._render_minibutton(surface, dec_rect, "<", dec_payload)
        self._render_minibutton(surface, inc_rect, ">", inc_payload)

        pygame.draw.rect(surface, PALETTE.bg_raised, value_rect)
        pygame.draw.rect(surface, PALETTE.line, value_rect, 1)
        val = self.assets.render_text(value_text, TYPE.body, PALETTE.text_strong)
        surface.blit(
            val,
            (
                value_rect.centerx - val.get_width() // 2,
                value_rect.centery - val.get_height() // 2,
            ),
        )

    def _render_minibutton(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        glyph: str,
        payload: object,
    ) -> None:
        hovering = self._hover_payload == payload
        bg = lighten(PALETTE.bg_raised, 0.1) if hovering else PALETTE.bg_raised
        pygame.draw.rect(surface, bg, rect)
        pygame.draw.rect(surface, PALETTE.line, rect, 1)
        g = self.assets.render_text(glyph, TYPE.h2, PALETTE.text_strong)
        surface.blit(
            g,
            (
                rect.centerx - g.get_width() // 2,
                rect.centery - g.get_height() // 2,
            ),
        )
        self._hits.append(_Hit(rect, payload))

    # -- action buttons ----------------------------------------------------

    def _render_actions(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        buttons = [
            ("Regenerate", ("action", "regen_one"), _ACCENT, True),
            ("Regenerate All", ("action", "regen_all"), PALETTE.secondary, False),
            ("Save Overrides", ("action", "save"), PALETTE.success, False),
            ("Reset", ("action", "reset"), PALETTE.muted, False),
            ("Reload Disk", ("action", "reload"), PALETTE.warning, False),
        ]
        total = len(buttons)
        spacing = 6
        btn_w = (rect.w - spacing * (total - 1)) // total
        y = rect.bottom - _BUTTON_H
        for i, (label, payload, tint, is_primary) in enumerate(buttons):
            bx = rect.x + i * (btn_w + spacing)
            brect = pygame.Rect(bx, y, btn_w, _BUTTON_H)
            self._render_action_button(
                surface, brect, label, payload, tint, is_primary=is_primary
            )

    def _render_action_button(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        payload: object,
        tint: Color,
        *,
        is_primary: bool,
    ) -> None:
        hovering = self._hover_payload == payload
        if is_primary and not self._regen_pulse.done:
            t = self._regen_pulse.elapsed / max(1e-6, self._regen_pulse.duration)
            scale = 1.0 + (1.0 - t) * 0.06
            scaled = pygame.Rect(0, 0, int(rect.w * scale), int(rect.h * scale))
            scaled.center = rect.center
            rect = scaled
        bg = lighten(PALETTE.bg_raised, 0.08) if hovering else PALETTE.bg_raised
        beveled_panel(surface, rect, fill=bg, border=tint)
        if is_primary:
            glow_alpha = int(70 + 50 * (1.0 - min(1.0, self._regen_pulse.elapsed / max(1e-6, self._regen_pulse.duration))))
            if self._regen_pulse.done:
                glow_alpha = 0
            if glow_alpha > 0:
                with acquired(rect.size) as glow:
                    glow.fill(with_alpha(tint, glow_alpha))
                    surface.blit(glow, rect.topleft)
        txt = self.assets.render_text(label, TYPE.body, PALETTE.text_strong)
        surface.blit(
            txt,
            (
                rect.centerx - txt.get_width() // 2,
                rect.centery - txt.get_height() // 2,
            ),
        )
        self._hits.append(_Hit(rect, payload))

    # -- status line -------------------------------------------------------

    def _render_status(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        if not self._status or self._status_fade.value <= 0.02:
            return
        alpha = int(255 * max(0.0, min(1.0, self._status_fade.value)))
        cached = self.assets.render_text(self._status, TYPE.body, PALETTE.success)
        shadow = pygame.Rect(
            rect.x + _PAD,
            rect.bottom - cached.get_height() - 6,
            cached.get_width() + 8,
            cached.get_height() + 4,
        )
        with acquired(shadow.size) as overlay:
            overlay.fill(with_alpha(PALETTE.bg_deep, min(200, alpha)))
            surface.blit(overlay, shadow.topleft)
        # Copy because the cached text surface is shared across frames.
        text_copy = cached.copy()
        text_copy.set_alpha(alpha)
        surface.blit(text_copy, (shadow.x + 4, shadow.y + 2))

    # -- hit / dispatch ----------------------------------------------------

    def _hit_at(self, pos: tuple[int, int]) -> _Hit | None:
        for h in self._hits:
            if h.rect.collidepoint(pos):
                return h
        return None

    def _dispatch(self, hit: _Hit) -> None:
        payload = hit.payload
        if not isinstance(payload, tuple):
            return
        tag = payload[0]
        if tag == "close":
            self.close()
        elif tag == "select":
            self._selected = payload[1]
        elif tag == "knob":
            self._apply_knob(payload[1], payload[2])
        elif tag == "action":
            self._apply_action(payload[1])

    # -- knob mutations ----------------------------------------------------

    def _apply_knob(self, field_name: str, delta: int) -> None:
        spec = specs_mod.STRUCTURE_SPECS.get(self._selected)
        if spec is None:
            return
        new_spec: StructureSpec | None = None
        if field_name == "accent_side":
            idx = SIDES.index(spec.accent.side) if spec.accent.side in SIDES else 0
            side = SIDES[(idx + delta) % len(SIDES)]
            new_spec = replace(spec, accent=replace(spec.accent, side=side))
        elif field_name == "accent_thickness":
            thickness = max(1, min(6, spec.accent.thickness + delta))
            new_spec = replace(spec, accent=replace(spec.accent, thickness=thickness))
        elif field_name == "bolts":
            bolts = max(4, min(16, spec.chassis.bolts + delta * 2))
            new_spec = replace(spec, chassis=replace(spec.chassis, bolts=bolts))
        elif field_name == "badge_size":
            size = max(6, min(40, spec.badge.size_at_64 + delta * 2))
            new_spec = replace(spec, badge=replace(spec.badge, size_at_64=size))
        elif field_name == "led_count":
            count = max(1, min(5, spec.lights.count + delta))
            new_spec = replace(spec, lights=replace(spec.lights, count=count))
        elif field_name == "led_pattern":
            new_pat = _cycle_pattern(spec.lights.pattern, delta)
            new_spec = replace(spec, lights=replace(spec.lights, pattern=new_pat))
        elif field_name == "overlay_kind":
            kinds = ("none", "auger", "steam", "glow")
            idx = kinds.index(spec.overlay.kind) if spec.overlay.kind in kinds else 0
            kind = kinds[(idx + delta) % len(kinds)]
            new_spec = replace(spec, overlay=replace(spec.overlay, kind=kind))
        elif field_name == "overlay_size":
            size = max(6, min(60, spec.overlay.size_at_64 + delta * 2))
            new_spec = replace(spec, overlay=replace(spec.overlay, size_at_64=size))
        if new_spec is not None and new_spec != spec:
            specs_mod.set_spec(self._selected, new_spec)

    # -- action dispatch ---------------------------------------------------

    def _apply_action(self, name: str) -> None:
        if name == "regen_one":
            keys = [e.key for e in entries_for_spec(self._selected)]
            self._regenerate(keys, f"Regenerated {self._selected}")
        elif name == "regen_all":
            sprites_api.generate_all(force=True)
            self.assets.reload_all_sprites()
            self._flash_status(f"Regenerated {len(sprites_api.all_entries())} sprites.")
        elif name == "save":
            sprites_api.save_overrides()
            self._flash_status(f"Saved overrides -> {sprites_api.overrides_path()}")
        elif name == "reset":
            specs_mod.reset_to_defaults()
            keys = [e.key for e in sprites_api.all_entries() if e.family == "structure"]
            self._regenerate(keys, "Reset all structures to defaults.")
        elif name == "reload":
            sprites_api.apply_overrides_from_disk()
            sprites_api.generate_all(force=True)
            self.assets.reload_all_sprites()
            self._flash_status("Reloaded sprites from disk.")

    def _regenerate(self, keys: list[str], message: str) -> None:
        if not keys:
            return
        sprites_api.regenerate(keys)
        for k in keys:
            self.assets.reload_sprite(k)
        self._regen_pulse = Tween(
            start=0.0, end=1.0, duration=THEME.anim.base, ease=THEME.anim.ease_bounce
        )
        self._flash_status(message)

    def _flash_status(self, msg: str) -> None:
        self._status = msg
        self._status_fade.set(1.2)
        self._status_fade.to(0.0)

    # -- defaults ----------------------------------------------------------

    def _default_spec_id(self) -> str:
        ids = sorted(specs_mod.STRUCTURE_SPECS.keys())
        return ids[0] if ids else ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sprite_from_spec(spec: StructureSpec, phase: str, frame: int) -> pygame.Surface:
    """Render a spec to a surface in-memory (does not touch disk)."""
    from ..assets.sprites.structure import render_structure

    return render_structure(spec, phase, frame)


_PATTERNS: tuple[tuple[int, ...], ...] = (
    (1,),
    (1, 0),
    (1, 1, 0),
    (1, 0, 1, 0),
    (1, 1, 0, 0),
    (1, 1, 0, 1, 0, 0),
    (1, 0, 1, 0, 1, 0),
    (1, 0, 0, 1, 1, 0),
)


def _cycle_pattern(current: tuple[int, ...], delta: int) -> tuple[int, ...]:
    if current in _PATTERNS:
        idx = _PATTERNS.index(current)
    else:
        idx = 0
    return _PATTERNS[(idx + delta) % len(_PATTERNS)]


def _pattern_name(p: tuple[int, ...]) -> str:
    return "".join("-" if v else "." for v in p)


__all__ = ["SpriteStudio"]
