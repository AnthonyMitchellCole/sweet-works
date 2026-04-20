"""Reusable UI controls: Button, Toggle, Stepper, Slider, Section.

All controls extend :class:`Widget` (for hover/press animation state) and
use the project's design system (``PALETTE``, ``TYPE``, ``THEME``,
``beveled_panel``). Each control exposes an ``update`` method that is
driven by the owning scene and a ``render`` method that paints it to a
surface.

The controls are deliberately self-contained: they own their animated
state, emit changes through simple callbacks, and never mutate external
config directly. Consumers map callback changes back to their own data
model (e.g. a dataclass draft).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Generic, TypeVar

import pygame

from ..audio.sfx import SFX
from ..design.palette import PALETTE, Color, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from .widget import Widget


# Maps Button ``kind`` → semantic click cue id.
_BUTTON_CUE_BY_KIND: dict[str, str] = {
    "primary": "ui.click",
    "secondary": "ui.click_soft",
    "ghost": "ui.click_soft",
}

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


T = TypeVar("T")


# -- Button ----------------------------------------------------------------


class Button(Widget):
    """A beveled button with hover/press tweens and three visual kinds.

    ``kind`` values:

    * ``"primary"`` - accent-filled, for confirm/apply actions
    * ``"secondary"`` - muted accent (warning), for reset-style actions
    * ``"ghost"`` - outlined only, for back/cancel actions
    """

    def __init__(
        self,
        rect: pygame.Rect,
        label: str,
        *,
        kind: str = "primary",
        on_click: Callable[[], None] | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(rect)
        self.label = label
        self.kind = kind
        self.on_click = on_click or (lambda: None)
        self.enabled = enabled
        self._disabled_anim = AnimValue(value=0.0, speed=10.0)

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_pressed: bool = False,
        mouse_released: bool = False,
    ) -> None:
        super().update(dt, mouse_pos, mouse_down if self.enabled else False)
        self._disabled_anim.to(0.0 if self.enabled else 1.0)
        self._disabled_anim.update(dt)
        if self.enabled and self.clicked(mouse_released):
            SFX.play(_BUTTON_CUE_BY_KIND.get(self.kind, "ui.click"))
            self.on_click()

    def render(self, surface: pygame.Surface, assets: AssetLoader) -> None:
        hover = self.hover_anim.value if self.enabled else 0.0
        press = self.press_anim.value if self.enabled else 0.0
        disabled = self._disabled_anim.value

        rect = self.rect.copy()
        fill, border, text_col, glow_col, glow_a = self._palette(hover, press)

        beveled_panel(surface, rect, fill=fill, border=border)

        if glow_a > 0:
            with acquired(rect.size) as glow:
                glow.fill(with_alpha(glow_col, glow_a))
                surface.blit(glow, rect.topleft)

        if self.kind == "primary" and self.enabled:
            pygame.draw.rect(surface, border, rect, 2)

        if press > 0.01:
            with acquired(rect.size) as dark:
                dark.fill(with_alpha(PALETTE.bg_deep, int(50 * press)))
                surface.blit(dark, rect.topleft)

        text_surface = assets.render_text(self.label, TYPE.h2, text_col)
        tx = rect.centerx - text_surface.get_width() // 2
        ty = rect.centery - text_surface.get_height() // 2
        if disabled > 0.01:
            text_surface = text_surface.copy()
            text_surface.set_alpha(int(255 * (1.0 - 0.55 * disabled)))
        surface.blit(text_surface, (tx, ty))

    def _palette(self, hover: float, press: float) -> tuple[Color, Color, Color, Color, int]:
        if not self.enabled:
            return (
                PALETTE.bg_base,
                PALETTE.line,
                PALETTE.muted,
                PALETTE.bg_deep,
                0,
            )
        if self.kind == "primary":
            fill = lighten(PALETTE.bg_raised, 0.05 + 0.05 * hover)
            border = PALETTE.primary
            text_col = PALETTE.text_strong
            glow = PALETTE.primary
            glow_a = int(28 + 48 * hover - 30 * press)
            return fill, border, text_col, glow, max(0, glow_a)
        if self.kind == "secondary":
            fill = lighten(PALETTE.bg_raised, 0.03 + 0.05 * hover)
            border = lighten(PALETTE.warning, 0.05 * hover)
            text_col = PALETTE.text_strong if hover > 0.2 else PALETTE.text_body
            glow = PALETTE.warning
            glow_a = int(18 + 28 * hover - 20 * press)
            return fill, border, text_col, glow, max(0, glow_a)
        # ghost
        fill = lighten(PALETTE.bg_base, 0.02 + 0.05 * hover)
        border = lighten(PALETTE.line, 0.2 * hover)
        text_col = PALETTE.text_body if hover < 0.3 else PALETTE.text_strong
        return fill, border, text_col, PALETTE.text_strong, int(10 * hover)


# -- Toggle ----------------------------------------------------------------


class Toggle(Widget):
    """Pill toggle with a sliding knob driven by an ``AnimValue``."""

    WIDTH = 56
    HEIGHT = 28

    def __init__(
        self,
        topleft: tuple[int, int],
        value: bool,
        on_change: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(pygame.Rect(topleft[0], topleft[1], self.WIDTH, self.HEIGHT))
        self._value: bool = bool(value)
        self.on_change = on_change or (lambda _v: None)
        # Seed both ``value`` and ``target`` -- otherwise the knob lerps
        # from the correct initial position back to the dataclass default
        # of 0, making a toggle constructed ON animate immediately to OFF.
        knob_target = 1.0 if self._value else 0.0
        self._knob = AnimValue(value=knob_target, target=knob_target, speed=18.0)

    @property
    def value(self) -> bool:
        return self._value

    def set_value(self, value: bool, *, notify: bool = True) -> None:
        v = bool(value)
        if v == self._value:
            return
        self._value = v
        self._knob.to(1.0 if v else 0.0)
        if notify:
            SFX.play("ui.toggle_on" if v else "ui.toggle_off")
            self.on_change(v)

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_pressed: bool = False,
        mouse_released: bool = False,
    ) -> None:
        super().update(dt, mouse_pos, mouse_down)
        self._knob.update(dt)
        if self.clicked(mouse_released):
            self.set_value(not self._value)

    def render(self, surface: pygame.Surface, assets: AssetLoader) -> None:
        t = self._knob.value
        hover = self.hover_anim.value
        rect = self.rect
        track_off = PALETTE.bg_raised
        track_on = PALETTE.success
        track = _blend(track_off, track_on, t)
        track = lighten(track, 0.05 * hover)
        # Track (pill). pygame doesn't do rounded rects natively without 2+,
        # so we approximate with two circles + rect.
        radius = rect.h // 2
        body = pygame.Rect(rect.x + radius, rect.y, rect.w - radius * 2, rect.h)
        pygame.draw.rect(surface, track, body)
        pygame.draw.circle(surface, track, (rect.x + radius, rect.centery), radius)
        pygame.draw.circle(
            surface, track, (rect.right - radius - 1, rect.centery), radius
        )
        # Inner shadow line for depth.
        pygame.draw.line(
            surface,
            with_alpha(PALETTE.bg_deep, 80),
            (rect.x + radius, rect.y),
            (rect.right - radius, rect.y),
        )

        # Knob.
        kx = rect.x + radius + int((rect.w - radius * 2) * t)
        ky = rect.centery
        knob_r = radius - 3
        pygame.draw.circle(surface, PALETTE.text_strong, (kx, ky), knob_r)
        pygame.draw.circle(surface, with_alpha(PALETTE.bg_deep, 90), (kx, ky), knob_r, 1)


# -- Stepper ---------------------------------------------------------------


class Stepper(Widget, Generic[T]):
    """Value stepper ``< label >`` with tween-based value cross-fade."""

    ARROW_W = 28

    def __init__(
        self,
        rect: pygame.Rect,
        values: Sequence[T],
        index: int,
        *,
        format: Callable[[T], str] | None = None,
        on_change: Callable[[int, T], None] | None = None,
    ) -> None:
        super().__init__(rect)
        if len(values) == 0:
            raise ValueError("Stepper requires at least one value")
        self._values: tuple[T, ...] = tuple(values)
        self._index: int = max(0, min(len(self._values) - 1, index))
        self.format: Callable[[T], str] = format or (lambda v: str(v))
        self.on_change = on_change or (lambda _i, _v: None)

        self._left = Widget(self._left_rect())
        self._right = Widget(self._right_rect())

        self._flash = Tween(
            start=0.0, end=0.0, duration=THEME.anim.fast, ease=THEME.anim.ease_out
        )
        self._flash.done = True

    # -- accessors
    @property
    def index(self) -> int:
        return self._index

    @property
    def value(self) -> T:
        return self._values[self._index]

    def set_index(self, i: int, *, notify: bool = True) -> None:
        i = max(0, min(len(self._values) - 1, i))
        if i == self._index:
            return
        self._index = i
        self._flash = Tween(start=1.0, end=0.0, duration=THEME.anim.fast, ease=THEME.anim.ease_out)
        if notify:
            SFX.play("ui.stepper")
            self.on_change(i, self.value)

    def set_values(self, values: Sequence[T], index: int | None = None) -> None:
        self._values = tuple(values)
        if not self._values:
            raise ValueError("Stepper requires at least one value")
        new_idx = self._index if index is None else index
        self._index = max(0, min(len(self._values) - 1, new_idx))

    # -- layout
    def _left_rect(self) -> pygame.Rect:
        return pygame.Rect(self.rect.x, self.rect.y, self.ARROW_W, self.rect.h)

    def _right_rect(self) -> pygame.Rect:
        return pygame.Rect(
            self.rect.right - self.ARROW_W, self.rect.y, self.ARROW_W, self.rect.h
        )

    def relayout(self) -> None:
        self._left.rect = self._left_rect()
        self._right.rect = self._right_rect()

    # -- update / render
    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_pressed: bool = False,
        mouse_released: bool = False,
    ) -> None:
        super().update(dt, mouse_pos, mouse_down)
        self.relayout()
        self._left.update(dt, mouse_pos, mouse_down)
        self._right.update(dt, mouse_pos, mouse_down)
        self._flash.update(dt)
        if self._left.clicked(mouse_released):
            self.set_index(self._index - 1)
        elif self._right.clicked(mouse_released):
            self.set_index(self._index + 1)

    def render(self, surface: pygame.Surface, assets: AssetLoader) -> None:
        hover = self.hover_anim.value

        fill = lighten(PALETTE.bg_raised, 0.03 + 0.04 * hover)
        border = lighten(PALETTE.line, 0.25 * hover)
        beveled_panel(surface, self.rect, fill=fill, border=border)

        # Arrows
        self._draw_arrow(surface, self._left, direction=-1)
        self._draw_arrow(surface, self._right, direction=+1)

        # Value text with a soft flash on change.
        label = self.format(self.value)
        base_col = PALETTE.text_strong
        text = assets.render_text(label, TYPE.body, base_col)
        center = self.rect.center
        flash = 0.0 if self._flash.done else max(0.0, min(1.0, 1.0 - self._flash.elapsed / self._flash.duration))
        if flash > 0.01:
            with acquired(self.rect.size) as glow:
                glow.fill(with_alpha(PALETTE.primary, int(55 * flash)))
                surface.blit(glow, self.rect.topleft)
        surface.blit(text, (center[0] - text.get_width() // 2, center[1] - text.get_height() // 2))

    def _draw_arrow(self, surface: pygame.Surface, widget: Widget, *, direction: int) -> None:
        hover = widget.hover_anim.value
        press = widget.press_anim.value
        color = PALETTE.text_body if hover < 0.1 else PALETTE.text_strong
        if press > 0.01:
            color = PALETTE.primary
        rect = widget.rect
        cx = rect.centerx
        cy = rect.centery
        size = 6 - int(press * 1.5)
        if direction < 0:
            pts = [(cx + size // 2, cy - size), (cx - size // 2 - 1, cy), (cx + size // 2, cy + size)]
        else:
            pts = [(cx - size // 2, cy - size), (cx + size // 2 + 1, cy), (cx - size // 2, cy + size)]
        pygame.draw.polygon(surface, color, pts)


# -- Slider ----------------------------------------------------------------


class Slider(Widget):
    """Horizontal slider with a smooth animated thumb and drag capture."""

    THUMB_R = 9
    TRACK_H = 6

    def __init__(
        self,
        rect: pygame.Rect,
        vmin: float,
        vmax: float,
        value: float,
        *,
        step: float | None = None,
        on_change: Callable[[float], None] | None = None,
        format: Callable[[float], str] | None = None,
    ) -> None:
        super().__init__(rect)
        if vmax <= vmin:
            raise ValueError("Slider vmax must be > vmin")
        self.vmin = float(vmin)
        self.vmax = float(vmax)
        self.step = step
        self.on_change = on_change or (lambda _v: None)
        self.format: Callable[[float], str] = format or (lambda v: f"{v:.2f}")
        self._value: float = self._clamp(value)
        # Seed value + target together: AnimValue.target defaults to 0.0,
        # which would otherwise drag the thumb straight to the left edge
        # on the first ``update`` regardless of the real value.
        frac = self._fraction(self._value)
        self._thumb_anim = AnimValue(value=frac, target=frac, speed=22.0)
        self._dragging: bool = False

    # -- accessors
    @property
    def value(self) -> float:
        return self._value

    def set_value(self, value: float, *, notify: bool = True) -> None:
        v = self._clamp(value)
        if v == self._value:
            return
        self._value = v
        self._thumb_anim.to(self._fraction(v))
        if notify:
            # Throttled in the SFX catalogue so continuous drags
            # produce a rhythmic tick rather than a solid tone.
            SFX.play("ui.slider_tick")
            self.on_change(v)

    # -- helpers
    def _clamp(self, v: float) -> float:
        v = max(self.vmin, min(self.vmax, float(v)))
        if self.step is not None and self.step > 0:
            n = round((v - self.vmin) / self.step)
            v = self.vmin + n * self.step
            v = max(self.vmin, min(self.vmax, v))
        return v

    def _fraction(self, v: float) -> float:
        return (v - self.vmin) / (self.vmax - self.vmin)

    def _track_rect(self) -> pygame.Rect:
        r = self.rect
        y = r.centery - self.TRACK_H // 2
        return pygame.Rect(r.x + self.THUMB_R, y, r.w - self.THUMB_R * 2, self.TRACK_H)

    def _thumb_x(self, frac: float) -> int:
        t = self._track_rect()
        return t.x + int(t.w * frac)

    # -- update / render
    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        mouse_pressed: bool = False,
        mouse_released: bool = False,
    ) -> None:
        super().update(dt, mouse_pos, mouse_down)
        if mouse_pressed and self.rect.collidepoint(mouse_pos):
            self._dragging = True
        if self._dragging and not mouse_down:
            self._dragging = False
        if self._dragging:
            t = self._track_rect()
            if t.w > 0:
                frac = (mouse_pos[0] - t.x) / t.w
                frac = max(0.0, min(1.0, frac))
                self.set_value(self.vmin + frac * (self.vmax - self.vmin))
        self._thumb_anim.update(dt)

    def render(self, surface: pygame.Surface, assets: AssetLoader) -> None:
        track = self._track_rect()
        hover = self.hover_anim.value
        # Track background
        pygame.draw.rect(surface, PALETTE.bg_raised, track)
        pygame.draw.rect(surface, lighten(PALETTE.line, 0.15 * hover), track, 1)
        # Filled portion
        filled = track.copy()
        filled.w = int(track.w * self._thumb_anim.value)
        fill_col = lighten(PALETTE.primary, 0.05 * hover)
        pygame.draw.rect(surface, fill_col, filled)

        # Thumb
        tx = self._thumb_x(self._thumb_anim.value)
        ty = track.centery
        thumb_r = self.THUMB_R + int(2 * hover) + (1 if self._dragging else 0)
        # Glow halo while interacting
        if self._dragging or hover > 0.2:
            with acquired((thumb_r * 4, thumb_r * 4)) as halo:
                a = int(55 * hover + 70 * float(self._dragging))
                pygame.draw.circle(
                    halo,
                    with_alpha(PALETTE.primary, a),
                    (thumb_r * 2, thumb_r * 2),
                    thumb_r * 2,
                )
                surface.blit(halo, (tx - thumb_r * 2, ty - thumb_r * 2))
        pygame.draw.circle(surface, PALETTE.text_strong, (tx, ty), thumb_r)
        pygame.draw.circle(surface, PALETTE.primary, (tx, ty), thumb_r, 2)

        # Value label to the right of the track, right-aligned within self.rect.
        label = assets.render_text(self.format(self._value), TYPE.caption, PALETTE.text_body)
        lx = self.rect.right - label.get_width()
        ly = self.rect.y - label.get_height() - 2
        if ly < 0:
            ly = self.rect.bottom + 2
        surface.blit(label, (lx, ly))


# -- Section ---------------------------------------------------------------


class Section:
    """Titled container that paints a header + bevelled body panel.

    The section does not own its children: the scene composes controls
    into the body rectangle returned by :attr:`body_rect`.
    """

    HEADER_H = 28
    PAD = THEME.spacing.md

    def __init__(self, rect: pygame.Rect, title: str) -> None:
        self.rect = rect
        self.title = title
        self._reveal = AnimValue(value=0.0, speed=7.0)

    def body_rect(self) -> pygame.Rect:
        r = self.rect
        return pygame.Rect(
            r.x + self.PAD,
            r.y + self.HEADER_H + self.PAD,
            r.w - self.PAD * 2,
            r.h - self.HEADER_H - self.PAD * 2,
        )

    def set_reveal(self, target: float) -> None:
        self._reveal.to(max(0.0, min(1.0, target)))

    def update(self, dt: float) -> None:
        self._reveal.update(dt)

    def render(self, surface: pygame.Surface, assets: AssetLoader) -> None:
        r = self.rect
        e = THEME.anim.ease_out(self._reveal.value)
        y_off = int((1.0 - e) * 10)
        alpha_i = int(255 * e)
        panel = pygame.Rect(r.x, r.y + self.HEADER_H + y_off, r.w, r.h - self.HEADER_H)
        beveled_panel(
            surface,
            panel,
            fill=lighten(PALETTE.bg_base, 0.03),
            border=PALETTE.line,
        )

        # Header: title + accent rule
        title = assets.render_text(self.title, TYPE.label, PALETTE.primary)
        surface.blit(title, (r.x + 2, r.y + y_off - 4))
        rule_y = r.y + self.HEADER_H - 4 + y_off
        rule_start_x = r.x + title.get_width() + 12
        pygame.draw.line(
            surface,
            with_alpha(PALETTE.line, int(180 * e)),
            (rule_start_x, rule_y),
            (r.right - 4, rule_y),
        )

        if alpha_i < 255:
            with acquired(panel.size) as mask:
                mask.fill(with_alpha(PALETTE.bg_deep, 255 - alpha_i))
                surface.blit(mask, panel.topleft)


# -- helpers ---------------------------------------------------------------


def _blend(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )
