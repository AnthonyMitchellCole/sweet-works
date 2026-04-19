"""Animated corner-bracket highlight around a hovered tile or footprint."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design.palette import PALETTE, Color, with_alpha
from ..rendering.pool import acquired

if TYPE_CHECKING:
    from ..world.camera import Camera


def draw_hover_brackets(
    surface: pygame.Surface,
    camera: Camera,
    origin: tuple[int, int],
    footprint: tuple[int, int],
    *,
    time: float,
    strength: float = 1.0,
    color: Color = PALETTE.secondary,
) -> None:
    """Draw four animated corner brackets around the target footprint.

    ``strength`` in [0,1] controls overall alpha, letting callers fade the
    highlight in and out as hover targets change.
    """
    if strength <= 0.01:
        return
    size = int(config.TILE * camera.zoom)
    fw, fh = footprint
    x, y = camera.world_to_screen(origin[0] * config.TILE, origin[1] * config.TILE)
    rect = pygame.Rect(x, y, size * fw, size * fh)

    pulse = 0.5 + 0.5 * math.sin(time * 5.5)
    base_alpha = int(140 + 90 * pulse)
    alpha = int(base_alpha * max(0.0, min(1.0, strength)))
    seg = max(6, min(rect.w, rect.h) // 5)
    thickness = 2

    with acquired(rect.size) as layer:
        c = with_alpha(color, alpha)
        w, h = rect.size
        # Top-left
        pygame.draw.line(layer, c, (0, 0), (seg, 0), thickness)
        pygame.draw.line(layer, c, (0, 0), (0, seg), thickness)
        # Top-right
        pygame.draw.line(layer, c, (w - seg, 0), (w - 1, 0), thickness)
        pygame.draw.line(layer, c, (w - 1, 0), (w - 1, seg), thickness)
        # Bottom-left
        pygame.draw.line(layer, c, (0, h - 1), (seg, h - 1), thickness)
        pygame.draw.line(layer, c, (0, h - seg), (0, h - 1), thickness)
        # Bottom-right
        pygame.draw.line(layer, c, (w - seg, h - 1), (w - 1, h - 1), thickness)
        pygame.draw.line(layer, c, (w - 1, h - seg), (w - 1, h - 1), thickness)

        # Subtle scanline to tie in with the rest of the accent chrome.
        sheen_y = int((0.5 + 0.5 * math.sin(time * 2.2)) * max(0, h - 2))
        pygame.draw.line(
            layer,
            with_alpha(color, max(0, alpha // 3)),
            (2, sheen_y),
            (w - 3, sheen_y),
            1,
        )
        surface.blit(layer, rect.topleft)
