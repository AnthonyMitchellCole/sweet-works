"""Transient placement / removal flourishes rendered over the world.

Two flavours, both keyed to ``world.time`` so they play correctly regardless
of sim-tick cadence:

- ``spawn_place``: a soft flash over the footprint with an expanding rim.
  Uses ``easing.out_back`` so the rim overshoots slightly for a "snap".
- ``spawn_remove``: a dashed rim + radial puff that fades out using
  ``easing.out_quart`` for a clean dissolve.

Both effects auto-expire; ``render`` prunes entries once their age exceeds
the configured duration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design import easing
from ..design.palette import PALETTE, Color, with_alpha
from ..rendering.pool import acquired

if TYPE_CHECKING:
    from ..world.camera import Camera


PLACE_DURATION: float = 0.32
REMOVE_DURATION: float = 0.36


@dataclass
class _Effect:
    origin: tuple[int, int]
    footprint: tuple[int, int]
    color: Color
    started_at: float
    kind: str  # "place" or "remove"


class PlacementFx:
    """Keeps a small list of active pops and dissolves, drawn each frame."""

    def __init__(self) -> None:
        self._fx: list[_Effect] = []

    # -- spawn -------------------------------------------------------------

    def spawn_place(
        self,
        origin: tuple[int, int],
        footprint: tuple[int, int],
        time: float,
        color: Color = PALETTE.primary,
    ) -> None:
        self._fx.append(_Effect(origin, footprint, color, time, "place"))

    def spawn_remove(
        self,
        origin: tuple[int, int],
        footprint: tuple[int, int],
        time: float,
        color: Color = PALETTE.danger,
    ) -> None:
        self._fx.append(_Effect(origin, footprint, color, time, "remove"))

    def clear(self) -> None:
        self._fx.clear()

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface, camera: "Camera", time: float) -> None:
        if not self._fx:
            return
        alive: list[_Effect] = []
        for fx in self._fx:
            duration = PLACE_DURATION if fx.kind == "place" else REMOVE_DURATION
            age = time - fx.started_at
            if age < 0.0 or age >= duration:
                continue
            t = age / duration
            if fx.kind == "place":
                self._draw_place(surface, camera, fx, t)
            else:
                self._draw_remove(surface, camera, fx, t)
            alive.append(fx)
        self._fx = alive

    # -- draw helpers ------------------------------------------------------

    def _draw_place(
        self,
        surface: pygame.Surface,
        camera: "Camera",
        fx: _Effect,
        t: float,
    ) -> None:
        tile = config.TILE
        zoom = camera.zoom
        fw, fh = fx.footprint
        x, y = camera.world_to_screen(fx.origin[0] * tile, fx.origin[1] * tile)
        w = max(1, int(round(tile * fw * zoom)))
        h = max(1, int(round(tile * fh * zoom)))

        # Fill: bright flash fading out.
        fade = 1.0 - easing.out_quart(t)
        fill_alpha = int(200 * fade)
        # Overshooting rim expansion for the snap-to-life feel.
        rim_t = easing.out_back(t)
        rim_grow = int(round(rim_t * max(6, int(zoom * 10))))
        rim_alpha = int(220 * (1.0 - t))

        total_w = w + rim_grow * 2 + 4
        total_h = h + rim_grow * 2 + 4
        with acquired((total_w, total_h)) as overlay:
            inner = pygame.Rect(rim_grow + 2, rim_grow + 2, w, h)
            if fill_alpha > 0:
                pygame.draw.rect(
                    overlay, with_alpha(PALETTE.text_strong, fill_alpha), inner
                )
                # Subtle inset tint of the tool color.
                tint_alpha = int(120 * fade)
                if tint_alpha > 0:
                    pygame.draw.rect(
                        overlay, with_alpha(fx.color, tint_alpha), inner.inflate(-2, -2)
                    )
            # Expanding rim -- two-band stroke for crispness.
            if rim_alpha > 0:
                rim_rect = inner.inflate(rim_grow * 2, rim_grow * 2)
                pygame.draw.rect(overlay, with_alpha(fx.color, rim_alpha), rim_rect, 2)
                inner_rim = rim_rect.inflate(-4, -4)
                pygame.draw.rect(
                    overlay,
                    with_alpha(PALETTE.text_strong, max(0, rim_alpha - 80)),
                    inner_rim,
                    1,
                )
            surface.blit(overlay, (x - rim_grow - 2, y - rim_grow - 2))

    def _draw_remove(
        self,
        surface: pygame.Surface,
        camera: "Camera",
        fx: _Effect,
        t: float,
    ) -> None:
        tile = config.TILE
        zoom = camera.zoom
        fw, fh = fx.footprint
        x, y = camera.world_to_screen(fx.origin[0] * tile, fx.origin[1] * tile)
        w = max(1, int(round(tile * fw * zoom)))
        h = max(1, int(round(tile * fh * zoom)))

        # Shrink + fade. Easing makes it snap, then tail off.
        ease_t = easing.out_quart(t)
        fade = 1.0 - ease_t
        inset = int(round(ease_t * max(3, int(zoom * 6))))
        alpha = int(210 * fade)

        total_w = w + 8
        total_h = h + 8
        with acquired((total_w, total_h)) as overlay:
            rect = pygame.Rect(4 + inset, 4 + inset, max(1, w - inset * 2), max(1, h - inset * 2))
            # Soft inner puff.
            puff_alpha = int(120 * fade * (1.0 - t))
            if puff_alpha > 0:
                pygame.draw.rect(overlay, with_alpha(fx.color, puff_alpha), rect)
            # Dashed rim rotating via phase offset so it feels alive.
            if alpha > 0:
                phase = int((t * 18.0) % 6)
                _dashed_rect(overlay, rect, with_alpha(fx.color, alpha), dash=3, gap=2, phase=phase)
                # Outer sparkle ring.
                outer = rect.inflate(6, 6)
                pygame.draw.rect(
                    overlay,
                    with_alpha(fx.color, max(0, alpha - 100)),
                    outer,
                    1,
                )
            surface.blit(overlay, (x - 4, y - 4))


def _dashed_rect(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: tuple[int, int, int, int],
    *,
    dash: int = 3,
    gap: int = 2,
    phase: int = 0,
) -> None:
    """Alpha-aware dashed rect. Duplicated (not imported) to keep pixel.py
    RGB-only and avoid widening its type signature."""
    x0, y0 = rect.left, rect.top
    x1, y1 = rect.right - 1, rect.bottom - 1
    step = dash + gap

    def run(x: int, y: int, dx: int, dy: int, length: int) -> None:
        traveled = 0
        while traveled < length:
            seg_start = (phase + traveled) % step
            if seg_start < dash:
                run_len = min(dash - seg_start, length - traveled)
                pygame.draw.line(
                    surface,
                    color,
                    (x + dx * traveled, y + dy * traveled),
                    (x + dx * (traveled + run_len - 1), y + dy * (traveled + run_len - 1)),
                )
                traveled += run_len
            else:
                skip = step - seg_start
                traveled += skip

    if x1 <= x0 or y1 <= y0:
        return
    run(x0, y0, 1, 0, x1 - x0 + 1)
    run(x1, y0, 0, 1, y1 - y0 + 1)
    run(x1, y1, -1, 0, x1 - x0 + 1)
    run(x0, y1, 0, -1, y1 - y0 + 1)


__all__ = ["PlacementFx", "PLACE_DURATION", "REMOVE_DURATION"]
