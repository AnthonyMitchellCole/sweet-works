"""Title screen with an animated chevron prompt and a benchmark entry."""

from __future__ import annotations

import math

import pygame

from ..design.palette import PALETTE, lighten, with_alpha
from ..design.typography import TYPE
from ..rendering.animation import Tween
from ..rendering.pixel import beveled_panel, gradient_fill
from ..rendering.pool import acquired
from .scene import Scene


class MenuScene(Scene):
    def __init__(self) -> None:
        super().__init__()
        self._t: float = 0.0
        self._fade = Tween(start=0.0, end=1.0, duration=0.5)
        self._selected: int = 0  # 0 = play, 1 = benchmark

    def on_enter(self) -> None:
        self._t = 0.0
        self._fade = Tween(start=0.0, end=1.0, duration=0.5)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self._activate()
        elif event.key == pygame.K_ESCAPE and self.game is not None:
            self.game.quit()
        elif event.key in (pygame.K_UP, pygame.K_w, pygame.K_DOWN, pygame.K_s):
            if event.key in (pygame.K_UP, pygame.K_w):
                self._selected = (self._selected - 1) % 2
            else:
                self._selected = (self._selected + 1) % 2
        elif event.key == pygame.K_b:
            self._selected = 1
            self._activate()
        elif event.key == pygame.K_p:
            self._selected = 0
            self._activate()

    def update(self, dt: float, sim_ticks: int, sim_alpha: float) -> None:
        self._t += dt
        self._fade.update(dt)

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

    # -- helpers -----------------------------------------------------------

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

    def _render_title(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets

        title = assets.render_text("FAC-PY", TYPE.display, PALETTE.text_strong)
        sub = assets.render_text(
            "Build. Connect. Automate.", TYPE.body, PALETTE.muted
        )
        w, h = surface.get_size()
        cx = w // 2
        cy = h // 2 - 80

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
        w, h = surface.get_size()
        cx = w // 2
        base_y = h // 2 + 20

        items = (
            ("PLAY", "start a fresh sandbox"),
            ("BENCHMARK", "1,000,000 items on belts"),
        )
        for i, (label, subtitle) in enumerate(items):
            selected = i == self._selected
            color = PALETTE.primary if selected else PALETTE.text_body
            sub_color = PALETTE.text_body if selected else PALETTE.muted
            lbl = assets.render_text(label, TYPE.h2, color)
            sub = assets.render_text(subtitle, TYPE.caption, sub_color)
            y = base_y + i * 48
            lx = cx - lbl.get_width() // 2
            surface.blit(lbl, (lx, y))
            surface.blit(sub, (cx - sub.get_width() // 2, y + lbl.get_height() + 2))
            if selected:
                pulse = 0.5 + 0.5 * math.sin(self._t * 4.0)
                marker_color = lighten(PALETTE.primary, 0.2 * pulse)
                mx = lx - 18
                my = y + lbl.get_height() // 2
                points = [(mx, my - 5), (mx + 8, my), (mx, my + 5)]
                pygame.draw.polygon(surface, marker_color, points)

    def _render_prompt(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets
        prompt = assets.render_text("ENTER  /  B bench  /  ESC quit", TYPE.label, PALETTE.primary)
        w, h = surface.get_size()
        alpha = int(120 + 120 * (0.5 + 0.5 * math.sin(self._t * 3.0)))
        scratch = prompt.copy()
        scratch.set_alpha(alpha)
        surface.blit(
            scratch,
            (w // 2 - prompt.get_width() // 2, h - 80),
        )
        chev_color = with_alpha(PALETTE.primary, alpha)
        cx = w // 2
        cy = h - 50
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

    def _activate(self) -> None:
        if self.game is None:
            return
        if self._selected == 1:
            from .benchmark_scene import BenchmarkScene

            self.game.replace_scene(BenchmarkScene())
        else:
            from .play_scene import PlayScene

            self.game.replace_scene(PlayScene())
