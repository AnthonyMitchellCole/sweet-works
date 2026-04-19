"""Belt sprite generator (relocated from :mod:`assets.generator`).

Chevron frames are authored east-facing and rotated for the other
cardinal directions so all four directions share a single source of
truth. A subtle row of side rivets has been added so belts read as part
of the same family as the structure chassis.
"""

from __future__ import annotations

import pygame

from ...core import config
from ...design.palette import PALETTE, darken, lighten
from . import draw


_ROTATIONS: dict[str, int] = {"E": 0, "N": 90, "W": 180, "S": 270}


def belt_east(frame: int) -> pygame.Surface:
    tile = config.TILE
    s = draw.new_surface((tile, tile))

    base = darken(PALETTE.bg_raised, 0.15)
    mid = PALETTE.surface
    hi = PALETTE.line
    chev = lighten(PALETTE.secondary, 0.05)
    bottom = PALETTE.bg_deep

    border = max(3, tile // 10)
    spacing = max(8, tile // 4)
    chev_w = max(4, tile // 8)
    chev_h = max(6, tile // 5)

    draw.fill_rect(s, base, 0, 0, tile, tile)
    draw.fill_rect(s, mid, 0, border, tile, tile - border * 2)
    draw.fill_rect(s, hi, 0, border, tile, 1)
    draw.fill_rect(s, bottom, 0, tile - border - 1, tile, 1)

    for y in (border // 2, tile - border // 2 - 1):
        for x in range(4, tile, max(8, tile // 4)):
            draw.pixel(s, PALETTE.muted, x, y)

    step = max(1, spacing // 4)
    offset = (frame * step) % spacing
    y0 = (tile - chev_h) // 2
    for base_x in range(-spacing, tile + spacing, spacing):
        x = base_x + offset
        for i in range(chev_w):
            draw.fill_rect(s, chev, x + i, y0 + i, 1, 1)
            draw.fill_rect(s, chev, x + i, y0 + chev_h - 1 - i, 1, 1)
    return s


def belt(direction: str, frame: int) -> pygame.Surface:
    east = belt_east(frame)
    angle = _ROTATIONS.get(direction, 0)
    return pygame.transform.rotate(east, angle) if angle else east


def belts_all() -> dict[tuple[str, int], pygame.Surface]:
    out: dict[tuple[str, int], pygame.Surface] = {}
    for frame in range(config.BELT_FRAMES):
        east = belt_east(frame)
        for direction, angle in _ROTATIONS.items():
            out[(direction, frame)] = (
                pygame.transform.rotate(east, angle) if angle else east
            )
    return out


__all__ = ["belt", "belt_east", "belts_all"]
