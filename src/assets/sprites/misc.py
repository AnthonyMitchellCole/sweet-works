"""Floor, ghost, and the legacy ``building_base`` fallback sprite."""

from __future__ import annotations

import pygame

from ...core import config
from ...design.palette import PALETTE, darken, lighten, with_alpha
from . import draw


def floor() -> pygame.Surface:
    tile = config.TILE
    s = draw.new_surface((tile, tile), alpha=False)
    s.fill(PALETTE.bg_base)
    checker = darken(PALETTE.bg_base, 0.25)
    cell = max(4, tile // 6)
    for y in range(0, tile, cell):
        for x in range(0, tile, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                draw.fill_rect(s, checker, x, y, cell, cell)
    draw.fill_rect(s, PALETTE.line, 0, 0, tile, 1)
    draw.fill_rect(s, PALETTE.line, 0, 0, 1, tile)
    return s


def ghost() -> pygame.Surface:
    tile = config.TILE
    s = draw.new_surface((tile, tile))
    fill = with_alpha(PALETTE.secondary, 70)
    outline = with_alpha(PALETTE.secondary, 200)
    pygame.draw.rect(s, fill, pygame.Rect(2, 2, tile - 4, tile - 4))
    for t in range(2):
        pygame.draw.rect(
            s, outline, pygame.Rect(t, t, tile - 2 * t, tile - 2 * t), 1
        )
    corner = max(4, tile // 8)
    for x, y in ((0, 0), (tile - 1, 0), (0, tile - 1), (tile - 1, tile - 1)):
        dx = 1 if x == 0 else -1
        dy = 1 if y == 0 else -1
        for i in range(corner):
            draw.pixel(s, outline, x + dx * i, y)
            draw.pixel(s, outline, x, y + dy * i)
    return s


def building_base() -> pygame.Surface:
    """Legacy 1-tile fallback for buildings without a structure spec."""
    tile = config.TILE
    s = draw.new_surface((tile, tile))
    plate = PALETTE.bg_raised
    face = lighten(plate, 0.08)
    top_edge = lighten(plate, 0.18)
    bottom_edge = darken(plate, 0.25)
    bolt = PALETTE.muted

    inset = max(2, tile // 12)

    draw.fill_rect(s, plate, 1, 1, tile - 2, tile - 2)
    draw.fill_rect(s, face, inset, inset, tile - inset * 2, tile - inset * 2)

    draw.fill_rect(s, top_edge, 1, 1, tile - 2, 1)
    draw.fill_rect(s, top_edge, 1, 1, 1, tile - 2)
    draw.fill_rect(s, bottom_edge, 1, tile - 2, tile - 2, 1)
    draw.fill_rect(s, bottom_edge, tile - 2, 1, 1, tile - 2)

    b = max(2, tile // 16)
    for cx, cy in (
        (b, b),
        (tile - 1 - b, b),
        (b, tile - 1 - b),
        (tile - 1 - b, tile - 1 - b),
    ):
        draw.fill_rect(s, bolt, cx, cy, 1, 1)
    return s


__all__ = ["floor", "ghost", "building_base"]
