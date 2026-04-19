"""Crisp pixel-art drawing helpers used by UI panels and HUD."""

from __future__ import annotations

import pygame

from ..design.palette import PALETTE, Color, darken, lighten


def beveled_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    fill: Color | None = None,
    border: Color | None = None,
    top_highlight: bool = True,
) -> None:
    fill_c = fill if fill is not None else PALETTE.bg_raised
    border_c = border if border is not None else PALETTE.line
    pygame.draw.rect(surface, fill_c, rect)
    pygame.draw.rect(surface, border_c, rect, 1)
    if top_highlight:
        hi = lighten(fill_c, 0.15)
        pygame.draw.line(
            surface, hi, (rect.x + 1, rect.y + 1), (rect.right - 2, rect.y + 1)
        )
        sh = darken(fill_c, 0.25)
        pygame.draw.line(
            surface,
            sh,
            (rect.x + 1, rect.bottom - 2),
            (rect.right - 2, rect.bottom - 2),
        )


def outlined_rect(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: Color,
    *,
    thickness: int = 1,
) -> None:
    pygame.draw.rect(surface, color, rect, thickness)


def gradient_fill(
    surface: pygame.Surface,
    rect: pygame.Rect,
    top: Color,
    bottom: Color,
) -> None:
    h = max(1, rect.h)
    for y in range(rect.h):
        t = y / h
        c = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
        pygame.draw.line(surface, c, (rect.x, rect.y + y), (rect.right - 1, rect.y + y))


def dashed_rect(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: Color,
    *,
    dash: int = 3,
    gap: int = 2,
    phase: int = 0,
) -> None:
    x0, y0, x1, y1 = rect.left, rect.top, rect.right - 1, rect.bottom - 1
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

    run(x0, y0, 1, 0, x1 - x0 + 1)
    run(x1, y0, 0, 1, y1 - y0 + 1)
    run(x1, y1, -1, 0, x1 - x0 + 1)
    run(x0, y1, 0, -1, y1 - y0 + 1)
