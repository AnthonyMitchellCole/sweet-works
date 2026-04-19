"""Procedural pixel-art asset generation.

Generates every sprite the game needs from the color palette alone, so the
project runs with zero external art. Outputs are cached to `assets/sprites/`.
"""

from __future__ import annotations

import pygame

from ..design.palette import PALETTE, Color, darken, lighten, with_alpha
from . import paths


TILE: int = 48
ITEM: int = 16


def _new(size: int, alpha: bool = True) -> pygame.Surface:
    flags = pygame.SRCALPHA if alpha else 0
    return pygame.Surface((size, size), flags)


def _rect(surf: pygame.Surface, c: Color, x: int, y: int, w: int, h: int) -> None:
    surf.fill(c, rect=pygame.Rect(x, y, w, h))


def _px(surf: pygame.Surface, c: Color, x: int, y: int) -> None:
    if 0 <= x < surf.get_width() and 0 <= y < surf.get_height():
        surf.set_at((x, y), c)


# ---------- Floor ----------


def _floor() -> pygame.Surface:
    s = _new(TILE, alpha=False)
    s.fill(PALETTE.bg_base)
    checker = darken(PALETTE.bg_base, 0.25)
    cell = 8
    for y in range(0, TILE, cell):
        for x in range(0, TILE, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                _rect(s, checker, x, y, cell, cell)
    _rect(s, PALETTE.line, 0, 0, TILE, 1)
    _rect(s, PALETTE.line, 0, 0, 1, TILE)
    return s


# ---------- Belt ----------


def _belt_east(frame: int) -> pygame.Surface:
    """Draw an east-facing belt tile, animating with `frame` in [0,3]."""
    s = _new(TILE)
    base = darken(PALETTE.bg_raised, 0.15)
    mid = PALETTE.surface
    hi = PALETTE.line
    chev = lighten(PALETTE.secondary, 0.05)
    shadow = darken(PALETTE.bg_deep, 0.0)

    _rect(s, base, 0, 0, TILE, TILE)
    _rect(s, mid, 0, 4, TILE, TILE - 8)
    _rect(s, hi, 0, 4, TILE, 1)
    _rect(s, shadow, 0, TILE - 5, TILE, 1)

    # Chevrons of 8x8 marching east, spaced 12px apart.
    offset = (frame * 3) % 12
    chev_w = 6
    chev_h = 10
    y0 = (TILE - chev_h) // 2
    for base_x in range(-12, TILE, 12):
        x = base_x + offset
        for i in range(chev_w):
            _rect(s, chev, x + i, y0 + i, 1, 1)
            _rect(s, chev, x + i, y0 + chev_h - 1 - i, 1, 1)
    return s


_ROTATIONS: dict[str, int] = {"E": 0, "N": 90, "W": 180, "S": 270}


def _belts() -> dict[tuple[str, int], pygame.Surface]:
    out: dict[tuple[str, int], pygame.Surface] = {}
    for frame in range(4):
        east = _belt_east(frame)
        for direction, angle in _ROTATIONS.items():
            out[(direction, frame)] = pygame.transform.rotate(east, angle)
    return out


# ---------- Building base ----------


def _building_base() -> pygame.Surface:
    s = _new(TILE)
    plate = PALETTE.bg_raised
    face = lighten(PALETTE.bg_raised, 0.08)
    top_edge = lighten(PALETTE.bg_raised, 0.18)
    bottom_edge = darken(PALETTE.bg_raised, 0.25)
    bolt = PALETTE.muted

    _rect(s, plate, 1, 1, TILE - 2, TILE - 2)
    _rect(s, face, 4, 4, TILE - 8, TILE - 8)

    _rect(s, top_edge, 1, 1, TILE - 2, 1)
    _rect(s, top_edge, 1, 1, 1, TILE - 2)
    _rect(s, bottom_edge, 1, TILE - 2, TILE - 2, 1)
    _rect(s, bottom_edge, TILE - 2, 1, 1, TILE - 2)

    for cx, cy in ((3, 3), (TILE - 4, 3), (3, TILE - 4), (TILE - 4, TILE - 4)):
        _px(s, bolt, cx, cy)
    return s


# ---------- Ghost placement ----------


def _ghost() -> pygame.Surface:
    s = _new(TILE)
    c = with_alpha(PALETTE.secondary, 70)
    outline = with_alpha(PALETTE.secondary, 200)
    pygame.draw.rect(s, c, pygame.Rect(2, 2, TILE - 4, TILE - 4))
    for t in range(2):
        pygame.draw.rect(
            s, outline, pygame.Rect(t, t, TILE - 2 * t, TILE - 2 * t), 1
        )
    corner = 6
    for x, y in ((0, 0), (TILE - 1, 0), (0, TILE - 1), (TILE - 1, TILE - 1)):
        dx = 1 if x == 0 else -1
        dy = 1 if y == 0 else -1
        for i in range(corner):
            _px(s, outline, x + dx * i, y)
            _px(s, outline, x, y + dy * i)
    return s


# ---------- Items ----------


def _item_icon(kind: str) -> pygame.Surface:
    s = _new(ITEM)
    if kind == "iron":
        c = PALETTE.iron
        hi = lighten(c, 0.25)
        sh = darken(c, 0.35)
        _rect(s, sh, 2, 3, 12, 10)
        _rect(s, c, 2, 3, 12, 8)
        _rect(s, hi, 3, 4, 10, 2)
    elif kind == "copper":
        c = PALETTE.copper
        hi = lighten(c, 0.25)
        sh = darken(c, 0.35)
        _rect(s, sh, 2, 5, 12, 8)
        _rect(s, c, 2, 4, 12, 7)
        _rect(s, hi, 3, 5, 10, 2)
    elif kind == "coal":
        c = PALETTE.coal
        hi = lighten(c, 0.35)
        for x, y, w, h in ((3, 4, 10, 8), (5, 3, 6, 2), (4, 11, 8, 2)):
            _rect(s, c, x, y, w, h)
        for px, py in ((5, 6), (9, 7), (7, 9)):
            _px(s, hi, px, py)
    elif kind == "plate":
        c = PALETTE.plate
        hi = lighten(c, 0.3)
        sh = darken(c, 0.3)
        _rect(s, sh, 1, 6, 14, 5)
        _rect(s, c, 1, 6, 14, 4)
        _rect(s, hi, 2, 7, 12, 1)
    elif kind == "gear":
        c = PALETTE.gear
        hi = lighten(c, 0.25)
        sh = darken(c, 0.3)
        pygame.draw.circle(s, sh, (8, 8), 6)
        pygame.draw.circle(s, c, (8, 8), 5)
        pygame.draw.circle(s, PALETTE.bg_raised, (8, 8), 2)
        for dx, dy in ((0, -7), (7, 0), (0, 7), (-7, 0), (5, -5), (-5, 5), (5, 5), (-5, -5)):
            _px(s, hi, 8 + dx, 8 + dy)
    else:
        _rect(s, PALETTE.danger, 2, 2, 12, 12)
    return s


ITEM_KINDS: tuple[str, ...] = ("iron", "copper", "coal", "plate", "gear")


# ---------- Public API ----------


def generate_all(force: bool = False) -> None:
    """Generate every sprite to disk, idempotently."""
    paths.ensure_dirs()
    # Pygame needs a display or headless video driver before converting. We
    # avoid `.convert()` here and save raw surfaces so this works pre-init.

    def _save(surf: pygame.Surface, name: str) -> None:
        out = paths.SPRITES_DIR / name
        if force or not out.exists():
            pygame.image.save(surf, str(out))

    _save(_floor(), "floor.png")
    _save(_building_base(), "building_base.png")
    _save(_ghost(), "ghost.png")

    for (direction, frame), surf in _belts().items():
        _save(surf, f"belt_{direction}_f{frame}.png")

    for kind in ITEM_KINDS:
        _save(_item_icon(kind), f"item_{kind}.png")
