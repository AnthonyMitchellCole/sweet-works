"""Title screen with an animated chevron prompt."""

from __future__ import annotations

import math

import pygame

from ..core import config
from ..design.palette import PALETTE, with_alpha
from ..design.typography import TYPE
from ..rendering.animation import Tween
from ..rendering.pixel import beveled_panel, gradient_fill
from .scene import Scene


class MenuScene(Scene):
    def __init__(self) -> None:
        super().__init__()
        self._t: float = 0.0
        self._fade = Tween(start=0.0, end=1.0, duration=0.5)

    def on_enter(self) -> None:
        self._t = 0.0
        self._fade = Tween(start=0.0, end=1.0, duration=0.5)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._start()
            elif event.key == pygame.K_ESCAPE and self.game is not None:
                self.game.quit()

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
        cy = h // 2 - 40

        bg = pygame.Rect(0, 0, title.get_width() + 48, title.get_height() + 32)
        bg.center = (cx, cy)
        beveled_panel(surface, bg, fill=PALETTE.bg_raised, border=PALETTE.primary)
        surface.blit(title, (cx - title.get_width() // 2, cy - title.get_height() // 2))

        surface.blit(
            sub,
            (cx - sub.get_width() // 2, bg.bottom + 16),
        )

    def _render_prompt(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets
        prompt = assets.render_text("PRESS ENTER", TYPE.label, PALETTE.primary)
        w, h = surface.get_size()
        alpha = int(120 + 120 * (0.5 + 0.5 * math.sin(self._t * 3.0)))
        scratch = prompt.copy()
        scratch.set_alpha(alpha)
        surface.blit(
            scratch,
            (w // 2 - prompt.get_width() // 2, h - 100),
        )
        # Chevron
        chev_color = with_alpha(PALETTE.primary, alpha)
        cx = w // 2
        cy = h - 60
        for i in range(3):
            off = int((self._t * 60 + i * 14) % 42) - 14
            points = [
                (cx - 10, cy + off),
                (cx, cy + off + 10),
                (cx + 10, cy + off),
            ]
            surf = pygame.Surface((22, 22), pygame.SRCALPHA)
            pygame.draw.polygon(
                surf,
                chev_color,
                [(p[0] - cx + 11, p[1] - cy + 6) for p in points],
                1,
            )
            surface.blit(surf, (cx - 11, cy - 6))

    def _start(self) -> None:
        if self.game is None:
            return
        from .play_scene import PlayScene  # local import avoids cycle

        self.game.replace_scene(PlayScene())
