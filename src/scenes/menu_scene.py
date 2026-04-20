"""Title screen with mouse + keyboard navigation and a cross-fade transition."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

import pygame

from ..audio.sfx import SFX
from ..design.palette import PALETTE, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel, gradient_fill
from ..rendering.pool import acquired
from ..ui.widget import Widget
from .scene import Scene

_ITEM_W = 340
_ITEM_H = 64
_ITEM_GAP = 12


@dataclass(frozen=True)
class _MenuItem:
    id: str
    label: str
    subtitle: str


class MenuScene(Scene):
    def __init__(self) -> None:
        super().__init__()
        self._t: float = 0.0
        self._fade_in = Tween(start=0.0, end=1.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out)
        self._fade_out: Tween | None = None
        self._pending: Callable[[], None] | None = None

        self._items: tuple[_MenuItem, ...] = (
            _MenuItem(id="play", label="PLAY", subtitle="start a fresh sandbox"),
            _MenuItem(id="benchmark", label="BENCHMARK", subtitle="1,000,000 items on belts"),
            _MenuItem(id="settings", label="SETTINGS", subtitle="display, simulation, camera"),
        )
        self._widgets: list[Widget] = [
            Widget(pygame.Rect(0, 0, _ITEM_W, _ITEM_H)) for _ in self._items
        ]
        self._selected: int = 0
        self._underline = AnimValue(value=0.0, target=1.0, speed=14.0)
        # Reveal stagger: each item's per-row tween driven by self._t after on_enter.
        self._reveal_t0: float = 0.0

        # Falling-sprinkle particles. Positions are normalised floats so
        # the layer survives window resizes without reshuffling.
        #
        # Per-sprinkle tuple:
        #   0: x_norm  - 0..1 horizontal seed
        #   1: phase   - 0..1, evenly spread so the column never clumps
        #                (``(i + rand)/count`` ensures continuous fall)
        #   2: hue_idx - index into ``_sprinkle_hues``
        #   3: rot     - base rotation of the short line segment
        #   4: speed   - fall speed (px/s)
        #   5: depth   - 0..1 parallax factor (size + alpha + drift)
        rng = random.Random(0xCA11D1)
        self._sprinkle_hues = (
            PALETTE.primary,
            PALETTE.secondary,
            PALETTE.success,
            PALETTE.warning,
            PALETTE.sugar_crystal,
        )
        _SPRINKLE_COUNT = 44
        self._sprinkles: list[
            tuple[float, float, int, float, float, float]
        ] = [
            (
                rng.random(),
                (i + rng.random()) / _SPRINKLE_COUNT,
                rng.randrange(len(self._sprinkle_hues)),
                rng.uniform(0.0, math.pi * 2),
                rng.uniform(14.0, 26.0),
                rng.uniform(0.35, 1.0),
            )
            for i in range(_SPRINKLE_COUNT)
        ]

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self) -> None:
        self._t = 0.0
        self._reveal_t0 = 0.0
        self._fade_in = Tween(start=0.0, end=1.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out)
        self._fade_out = None
        self._pending = None
        self._underline.set(0.0)
        self._underline.to(1.0)

    def on_resume(self) -> None:
        # Gentle re-fade when returning from a pushed scene (e.g. settings).
        self._t = 0.0
        self._fade_in = Tween(start=0.0, end=1.0, duration=THEME.anim.base, ease=THEME.anim.ease_out)
        self._fade_out = None
        self._pending = None

    # -- events ------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._pending is not None:
            return
        if event.type != pygame.KEYDOWN:
            return
        k = event.key
        if k in (pygame.K_RETURN, pygame.K_SPACE):
            self._activate()
        elif k == pygame.K_ESCAPE and self.game is not None:
            self.game.quit()
        elif k in (pygame.K_UP, pygame.K_w):
            self._move_selection(-1)
        elif k in (pygame.K_DOWN, pygame.K_s):
            self._move_selection(+1)
        elif k == pygame.K_b:
            self._selected = 1
            self._activate()
        elif k == pygame.K_p:
            self._selected = 0
            self._activate()

    # -- update/render -----------------------------------------------------

    def update(self, dt: float, sim_ticks: int, sim_alpha: float) -> None:
        self._t += dt
        self._fade_in.update(dt)
        if self._fade_out is not None:
            v = self._fade_out.update(dt)
            if self._fade_out.done and self._pending is not None:
                cb = self._pending
                self._pending = None
                cb()
                return
            _ = v

        self._layout()

        if self.game is None:
            return
        mouse_pos = self.game.input.mouse_pos
        mouse_down = self.game.input.mouse(1)
        mouse_released = self.game.input.mouse_released(1)

        prev_selected = self._selected
        hovered_index: int | None = None
        for i, w in enumerate(self._widgets):
            w.update(dt, mouse_pos, mouse_down)
            if w.hovered:
                hovered_index = i
        if hovered_index is not None and hovered_index != self._selected:
            self._selected = hovered_index
        # Keep a visual "selected" flag in sync for the Widget's hover lerp.
        for i, w in enumerate(self._widgets):
            w.selected = i == self._selected

        if self._pending is None:
            for i, w in enumerate(self._widgets):
                if w.clicked(mouse_released):
                    self._selected = i
                    self._activate()
                    break

        if prev_selected != self._selected:
            self._underline.set(0.0)
            self._underline.to(1.0)
        self._underline.update(dt)

    def render(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        gradient_fill(
            surface,
            pygame.Rect(0, 0, w, h),
            PALETTE.bg_deep,
            PALETTE.bg_base,
        )
        self._render_grid(surface)
        self._render_title(surface)
        self._render_menu(surface)
        self._render_prompt(surface)
        self._render_fade_overlay(surface)

    # -- helpers -----------------------------------------------------------

    def _layout(self) -> None:
        if self.game is None:
            return
        w, h = self.game.window_size
        cx = w // 2
        base_y = h // 2 + 20
        for i, widget in enumerate(self._widgets):
            y = base_y + i * (_ITEM_H + _ITEM_GAP)
            widget.rect.topleft = (cx - _ITEM_W // 2, y)

    def _move_selection(self, delta: int) -> None:
        n = len(self._items)
        self._selected = (self._selected + delta) % n
        SFX.play("ui.hover")

    def _render_grid(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        color = with_alpha(PALETTE.line, 30)
        step = 48
        line = pygame.Surface((w, 1), pygame.SRCALPHA)
        line.fill(color)
        for y in range(0, h, step):
            surface.blit(line, (0, y))
        vline = pygame.Surface((1, h), pygame.SRCALPHA)
        vline.fill(color)
        for x in range(0, w, step):
            surface.blit(vline, (x, 0))
        self._render_sprinkles(surface)

    def _render_sprinkles(self, surface: pygame.Surface) -> None:
        """Continuous, lightly-parallaxed rain of sprinkles.

        Depth drives size, alpha, and drift amplitude so the far pieces
        sit quietly in the back while the near pieces pop -- the effect
        reads as layered rain instead of uniform noise, which keeps the
        menu title and items comfortably legible.
        """
        w, h = surface.get_size()
        span = h + 20
        for x_norm, phase, hue_idx, rot, speed, depth in self._sprinkles:
            y = ((phase * span + self._t * speed) % span) - 10
            jitter = math.sin(self._t * 0.8 + rot) * (5.0 + 6.0 * depth)
            x = x_norm * w + jitter
            color = self._sprinkle_hues[hue_idx]
            alpha = int(35 + 55 * depth)  # 35..90; far < near, never overpowers
            angle = rot + self._t * 1.5
            half = 2.0 + 1.8 * depth       # 2..3.8 px half-length
            dx = math.cos(angle) * half
            dy = math.sin(angle) * half
            width = 2 if depth > 0.55 else 1
            with acquired((9, 9)) as surf:
                pygame.draw.line(
                    surf,
                    with_alpha(color, alpha),
                    (int(round(4 - dx)), int(round(4 - dy))),
                    (int(round(4 + dx)), int(round(4 + dy))),
                    width,
                )
                surface.blit(surf, (int(x) - 4, int(y) - 4))

    def _render_title(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets

        title = assets.render_text("SWEET WORKS", TYPE.display, PALETTE.text_strong)
        sub = assets.render_text(
            "Extract. Mix. Wrap.", TYPE.body, PALETTE.muted
        )
        w, h = surface.get_size()
        cx = w // 2
        cy = h // 2 - 120

        bg = pygame.Rect(0, 0, title.get_width() + 48, title.get_height() + 32)
        bg.center = (cx, cy)
        beveled_panel(surface, bg, fill=PALETTE.bg_raised, border=PALETTE.primary)
        surface.blit(title, (cx - title.get_width() // 2, cy - title.get_height() // 2))

        surface.blit(
            sub,
            (cx - sub.get_width() // 2, bg.bottom + 12),
        )

    def _render_menu(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets
        for i, (item, widget) in enumerate(zip(self._items, self._widgets)):
            # Per-row reveal stagger: each row slides up + fades in.
            row_delay = 0.08 * i
            row_t = max(0.0, min(1.0, (self._t - row_delay) / THEME.anim.slow))
            row_e = THEME.anim.ease_out(row_t)
            y_offset = int((1.0 - row_e) * 16)
            row_alpha = int(255 * row_e)

            rect = widget.rect.move(0, y_offset)

            hover = widget.hover_anim.value
            press = widget.press_anim.value
            selected = i == self._selected

            # Soft shadow under each card to lift it off the bg.
            shadow = pygame.Rect(rect.x + 2, rect.y + 3, rect.w, rect.h)
            with acquired(shadow.size) as shsurf:
                shsurf.fill(with_alpha(PALETTE.bg_deep, int(90 * row_e)))
                surface.blit(shsurf, shadow.topleft)

            fill = lighten(PALETTE.bg_raised, 0.04 + 0.08 * hover)
            border = PALETTE.primary if selected else lighten(PALETTE.line, 0.1 + 0.2 * hover)
            beveled_panel(surface, rect, fill=fill, border=border)

            if hover > 0.01 or selected:
                with acquired(rect.size) as glow:
                    glow.fill(with_alpha(PALETTE.primary, int(28 * hover + 22 * float(selected))))
                    surface.blit(glow, rect.topleft)

            if selected:
                pygame.draw.rect(surface, PALETTE.primary, rect, 2)

            # Label and subtitle, with a hover-driven inward shift.
            color = PALETTE.text_strong if (selected or hover > 0.1) else PALETTE.text_body
            sub_color = PALETTE.text_body if selected else PALETTE.muted
            lbl = assets.render_text(item.label, TYPE.h2, color)
            sub = assets.render_text(item.subtitle, TYPE.caption, sub_color)

            text_slide = int(6 * hover)
            lbl_x = rect.x + 24 + text_slide
            lbl_y = rect.y + 10
            surface.blit(lbl, (lbl_x, lbl_y))
            surface.blit(sub, (lbl_x, lbl_y + lbl.get_height() + 2))

            # Animated left-edge indicator: chevron that slides in on hover.
            indicator_t = hover if not selected else max(hover, self._underline.value)
            if indicator_t > 0.01:
                cx0 = rect.x + 8 + int((1.0 - indicator_t) * -14)
                cy0 = rect.centery
                color_marker = lighten(PALETTE.primary, 0.15 * (0.5 + 0.5 * math.sin(self._t * 5.0)))
                pts = [
                    (cx0, cy0 - 7),
                    (cx0 + 10, cy0),
                    (cx0, cy0 + 7),
                ]
                pygame.draw.polygon(surface, color_marker, pts)

            # Underline bar under the label for the selected row.
            if selected:
                uw = int((lbl.get_width() + 10) * self._underline.value)
                pygame.draw.rect(
                    surface,
                    PALETTE.primary,
                    pygame.Rect(lbl_x, lbl_y + lbl.get_height() + 1, uw, 2),
                )

            # Press: slight scale-down via a dark overlay for tactile feedback.
            if press > 0.01:
                with acquired(rect.size) as pover:
                    pover.fill(with_alpha(PALETTE.bg_deep, int(70 * press)))
                    surface.blit(pover, rect.topleft)

            # Row-level alpha (blend the subtle reveal).
            if row_alpha < 255:
                with acquired(rect.size) as mask:
                    mask.fill(with_alpha(PALETTE.bg_deep, 255 - row_alpha))
                    surface.blit(mask, rect.topleft)

    def _render_prompt(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets
        prompt = assets.render_text(
            "ENTER select   UP / DOWN nav   CLICK pick   ESC quit",
            TYPE.label,
            PALETTE.primary,
        )
        w, h = surface.get_size()
        alpha = int(120 + 120 * (0.5 + 0.5 * math.sin(self._t * 3.0)))
        scratch = prompt.copy()
        scratch.set_alpha(alpha)
        surface.blit(
            scratch,
            (w // 2 - prompt.get_width() // 2, h - 56),
        )
        chev_color = with_alpha(PALETTE.primary, alpha)
        cx = w // 2
        cy = h - 28
        for i in range(3):
            off = int((self._t * 60 + i * 14) % 42) - 14
            points = [
                (cx - 10, cy + off),
                (cx, cy + off + 10),
                (cx + 10, cy + off),
            ]
            with acquired((22, 22)) as surf:
                pygame.draw.polygon(
                    surf,
                    chev_color,
                    [(p[0] - cx + 11, p[1] - cy + 6) for p in points],
                    1,
                )
                surface.blit(surf, (cx - 11, cy - 6))

    def _render_fade_overlay(self, surface: pygame.Surface) -> None:
        # Fade-in (on enter) and fade-out (on activation) as a black veil.
        fade_in_a = 1.0 - self._fade_in.update(0.0) if not self._fade_in.done else 0.0
        fade_in_a = max(0.0, min(1.0, fade_in_a))
        fade_out_a = 0.0
        if self._fade_out is not None:
            raw = self._fade_out.update(0.0)
            fade_out_a = max(0.0, min(1.0, raw))
        alpha = int(255 * max(fade_in_a, fade_out_a))
        if alpha <= 1:
            return
        w, h = surface.get_size()
        with acquired((w, h)) as veil:
            veil.fill(with_alpha(PALETTE.bg_deep, alpha))
            surface.blit(veil, (0, 0))

    # -- activation / transitions -----------------------------------------

    def _activate(self) -> None:
        if self.game is None or self._pending is not None:
            return
        item = self._items[self._selected]
        SFX.play("ui.click")

        # Build the post-fade action, then start a short fade-out.
        if item.id == "benchmark":
            def go() -> None:
                from .benchmark_scene import BenchmarkScene

                assert self.game is not None
                self.game.replace_scene(BenchmarkScene())
            self._pending = go
        elif item.id == "settings":
            def go() -> None:
                from .settings_scene import SettingsScene

                assert self.game is not None
                self.game.push_scene(SettingsScene())
            self._pending = go
        else:
            def go() -> None:
                from .play_scene import PlayScene

                assert self.game is not None
                self.game.replace_scene(PlayScene())
            self._pending = go

        self._fade_out = Tween(
            start=0.0,
            end=1.0,
            duration=THEME.anim.base,
            ease=THEME.anim.ease_in_out,
        )
