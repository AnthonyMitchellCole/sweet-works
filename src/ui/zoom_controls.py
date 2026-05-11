"""Reusable on-screen zoom-control cluster.

A vertical stack of three beveled buttons (``+`` / ``-`` / ``Fit``) plus
a small live ``Nx`` zoom readout, intended to sit in a corner of any
pan-zoom scene (research tree, future overworld map, etc.). The widget
takes the same design vocabulary as the rest of the UI:

* :class:`~src.ui.widget.Widget` for hover/press tweens,
* :func:`~src.rendering.pixel.beveled_panel` for the body,
* :data:`~src.design.palette.PALETTE`, :data:`~src.design.theme.THEME`
  and :data:`~src.design.typography.TYPE` design tokens.

The widget is callback-driven: the owning scene passes ``on_zoom_in``,
``on_zoom_out`` and ``on_fit`` lambdas at construction time. The
control doesn't know what a ``Camera`` is, so it stays cheaply reusable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pygame

from ..design.palette import PALETTE, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from .widget import Widget

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


BTN_SIZE: int = 36
BTN_GAP: int = 6
READOUT_H: int = 22


class _ZoomButton(Widget):
    """Internal: one of the three round buttons in the cluster."""

    def __init__(
        self, rect: pygame.Rect, glyph: str, on_click: Callable[[], None]
    ) -> None:
        super().__init__(rect)
        self.glyph = glyph
        self.on_click = on_click

    def render(
        self, surface: pygame.Surface, assets: AssetLoader, alpha: int
    ) -> None:
        hover = self.hover_anim.value
        press = self.press_anim.value
        fill = lighten(PALETTE.bg_raised, 0.04 + 0.05 * hover)
        border = lighten(PALETTE.primary, 0.05 * hover)
        with acquired(self.rect.size) as layer:
            local = pygame.Rect(0, 0, self.rect.w, self.rect.h)
            beveled_panel(layer, local, fill=fill, border=border)
            glow_a = int(28 + 56 * hover - 30 * press)
            if glow_a > 0:
                glow = pygame.Surface(self.rect.size, pygame.SRCALPHA)
                glow.fill(with_alpha(PALETTE.primary, glow_a))
                layer.blit(glow, (0, 0))
            if press > 0.01:
                dim = pygame.Surface(self.rect.size, pygame.SRCALPHA)
                dim.fill(with_alpha(PALETTE.bg_deep, int(50 * press)))
                layer.blit(dim, (0, 0))
            # Glyph: rendered with the "h2" style for the bold ``+`` /
            # ``-`` arithmetic glyphs and the smaller "label" for "Fit"
            # so each button is visually balanced.
            style = TYPE.h2 if len(self.glyph) == 1 else TYPE.label
            text = assets.render_text(self.glyph, style, PALETTE.text_strong)
            tx = (self.rect.w - text.get_width()) // 2
            ty = (self.rect.h - text.get_height()) // 2 - int(round(press * 1))
            layer.blit(text, (tx, ty))
            if hover > 0.02:
                ul = pygame.Surface((self.rect.w - 6, 2), pygame.SRCALPHA)
                ul.fill(with_alpha(PALETTE.primary, int(200 * hover)))
                layer.blit(ul, (3, self.rect.h - 3))
            layer.set_alpha(alpha)
            surface.blit(layer, self.rect.topleft)


class ZoomControls:
    """A small floating zoom-control cluster.

    Usage::

        controls = ZoomControls(
            on_zoom_in=lambda: camera.zoom_by(1.10),
            on_zoom_out=lambda: camera.zoom_by(1 / 1.10),
            on_fit=lambda: _fit_to_all(),
            zoom_provider=lambda: camera.zoom,
        )
        controls.layout_bottom_right(window_size)
        controls.update(dt, mouse_pos, mouse_down, mouse_released=...)
        controls.render(surface, assets, fade)
    """

    def __init__(
        self,
        *,
        on_zoom_in: Callable[[], None],
        on_zoom_out: Callable[[], None],
        on_fit: Callable[[], None],
        zoom_provider: Callable[[], float],
        margin_right: int = 0,
    ) -> None:
        self._on_zoom_in = on_zoom_in
        self._on_zoom_out = on_zoom_out
        self._on_fit = on_fit
        self._zoom_provider = zoom_provider
        self._margin_right = margin_right
        self._plus = _ZoomButton(
            pygame.Rect(0, 0, BTN_SIZE, BTN_SIZE), "+", on_zoom_in
        )
        self._minus = _ZoomButton(
            pygame.Rect(0, 0, BTN_SIZE, BTN_SIZE), "-", on_zoom_out
        )
        self._fit = _ZoomButton(
            pygame.Rect(0, 0, BTN_SIZE, BTN_SIZE), "FIT", on_fit
        )
        # Readout flash on zoom-bin change so the value pops when the
        # user nudges zoom by keyboard / wheel / button.
        self._readout_flash = AnimValue(value=0.0, speed=8.0)
        self._last_bin: int = -1
        self._rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)

    # -- layout ------------------------------------------------------------

    @property
    def total_height(self) -> int:
        return BTN_SIZE * 3 + BTN_GAP * 2 + READOUT_H + 4

    @property
    def width(self) -> int:
        return BTN_SIZE

    @property
    def rect(self) -> pygame.Rect:
        return self._rect.copy()

    def layout_bottom_right(
        self, window_size: tuple[int, int], *, bottom_margin: int = 0
    ) -> None:
        """Place the cluster at the right edge, with ``bottom_margin``
        above the bottom of the window (useful to clear the legend).
        """
        w, h = window_size
        pad = THEME.spacing.md
        x = w - BTN_SIZE - pad - self._margin_right
        y = h - bottom_margin - self.total_height - pad
        self._rect = pygame.Rect(x, y, BTN_SIZE, self.total_height)
        self._plus.rect = pygame.Rect(x, y, BTN_SIZE, BTN_SIZE)
        self._minus.rect = pygame.Rect(
            x, y + BTN_SIZE + BTN_GAP, BTN_SIZE, BTN_SIZE
        )
        self._fit.rect = pygame.Rect(
            x, y + (BTN_SIZE + BTN_GAP) * 2, BTN_SIZE, BTN_SIZE
        )

    # -- input -------------------------------------------------------------

    @property
    def hovered(self) -> bool:
        return (
            self._plus.hovered or self._minus.hovered or self._fit.hovered
        )

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int],
        mouse_down: bool,
        *,
        mouse_released: bool = False,
    ) -> None:
        for btn in (self._plus, self._minus, self._fit):
            btn.update(dt, mouse_pos, mouse_down)
            if btn.clicked(mouse_released):
                # Pulse the readout when the cluster mutates the zoom
                # so the change reads back to the user immediately.
                self._readout_flash.set(1.0)
                self._readout_flash.to(0.0)
                btn.on_click()
        self._readout_flash.update(dt)
        # Bin-based flash so wheel/keyboard changes also light the
        # readout (any consumer can call ``on_zoom_changed`` for an
        # explicit pulse, but the bin diff catches every path).
        new_bin = round(self._zoom_provider() * 100)
        if new_bin != self._last_bin and self._last_bin != -1:
            self._readout_flash.to(1.0)
            self._readout_flash.value = max(self._readout_flash.value, 0.6)
            self._readout_flash.to(0.0)
        self._last_bin = new_bin

    # -- render ------------------------------------------------------------

    def render(
        self, surface: pygame.Surface, assets: AssetLoader, fade: float
    ) -> None:
        if self._rect.w == 0:
            return
        alpha = int(255 * max(0.0, min(1.0, fade)))
        if alpha <= 4:
            return
        self._plus.render(surface, assets, alpha)
        self._minus.render(surface, assets, alpha)
        self._fit.render(surface, assets, alpha)

        # Readout chip below the FIT button.
        chip_rect = pygame.Rect(
            self._rect.x,
            self._fit.rect.bottom + 4,
            self._rect.w,
            READOUT_H,
        )
        flash = self._readout_flash.value
        with acquired(chip_rect.size) as layer:
            local = pygame.Rect(0, 0, chip_rect.w, chip_rect.h)
            beveled_panel(
                layer,
                local,
                fill=PALETTE.bg_deep,
                border=lighten(PALETTE.line, 0.2 * flash),
            )
            if flash > 0.02:
                glow = pygame.Surface(local.size, pygame.SRCALPHA)
                glow.fill(with_alpha(PALETTE.primary, int(70 * flash)))
                layer.blit(glow, (0, 0))
            text = assets.render_text(
                f"{self._zoom_provider():.1f}x", TYPE.label, PALETTE.text_body
            )
            tx = (local.w - text.get_width()) // 2
            ty = (local.h - text.get_height()) // 2
            layer.blit(text, (tx, ty))
            layer.set_alpha(alpha)
            surface.blit(layer, chip_rect.topleft)


__all__ = ["ZoomControls"]
