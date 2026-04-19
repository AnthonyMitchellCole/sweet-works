"""Procedural pixel-art asset generation.

Generates every sprite the game needs from the color palette alone, so the
project runs with zero external art. All internal dimensions scale from
`config.TILE` and `config.ITEM_PX`, so changing those constants produces a
proportionally-correct sprite set.
"""

from __future__ import annotations

import pygame

from ..core import config
from ..design.palette import PALETTE, Color, darken, lighten, with_alpha
from . import paths


def _tile() -> int:
    return config.TILE


def _item() -> int:
    return config.ITEM_PX


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
    tile = _tile()
    s = _new(tile, alpha=False)
    s.fill(PALETTE.bg_base)
    checker = darken(PALETTE.bg_base, 0.25)
    cell = max(4, tile // 6)
    for y in range(0, tile, cell):
        for x in range(0, tile, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                _rect(s, checker, x, y, cell, cell)
    _rect(s, PALETTE.line, 0, 0, tile, 1)
    _rect(s, PALETTE.line, 0, 0, 1, tile)
    return s


# ---------- Belt ----------


def _belt_east(frame: int) -> pygame.Surface:
    """East-facing belt tile, animated via `frame` in [0, 3]."""
    tile = _tile()
    s = _new(tile)

    base = darken(PALETTE.bg_raised, 0.15)
    mid = PALETTE.surface
    hi = PALETTE.line
    chev = lighten(PALETTE.secondary, 0.05)
    bottom = darken(PALETTE.bg_deep, 0.0)

    border = max(3, tile // 10)      # thickness of top/bottom dark strips
    spacing = max(8, tile // 4)       # chevron spacing in px
    chev_w = max(4, tile // 8)
    chev_h = max(6, tile // 5)

    _rect(s, base, 0, 0, tile, tile)
    _rect(s, mid, 0, border, tile, tile - border * 2)
    _rect(s, hi, 0, border, tile, 1)
    _rect(s, bottom, 0, tile - border - 1, tile, 1)

    # Each frame moves chevrons forward by (spacing / 4), so after 4 frames
    # they advance exactly one spacing and wrap seamlessly.
    step = max(1, spacing // 4)
    offset = (frame * step) % spacing
    y0 = (tile - chev_h) // 2
    for base_x in range(-spacing, tile + spacing, spacing):
        x = base_x + offset
        for i in range(chev_w):
            _rect(s, chev, x + i, y0 + i, 1, 1)
            _rect(s, chev, x + i, y0 + chev_h - 1 - i, 1, 1)
    return s


_ROTATIONS: dict[str, int] = {"E": 0, "N": 90, "W": 180, "S": 270}


def _belts() -> dict[tuple[str, int], pygame.Surface]:
    out: dict[tuple[str, int], pygame.Surface] = {}
    for frame in range(config.BELT_FRAMES):
        east = _belt_east(frame)
        for direction, angle in _ROTATIONS.items():
            out[(direction, frame)] = pygame.transform.rotate(east, angle)
    return out


# ---------- Building base ----------


def _building_base() -> pygame.Surface:
    tile = _tile()
    s = _new(tile)
    plate = PALETTE.bg_raised
    face = lighten(PALETTE.bg_raised, 0.08)
    top_edge = lighten(PALETTE.bg_raised, 0.18)
    bottom_edge = darken(PALETTE.bg_raised, 0.25)
    bolt = PALETTE.muted

    inset = max(2, tile // 12)

    _rect(s, plate, 1, 1, tile - 2, tile - 2)
    _rect(s, face, inset, inset, tile - inset * 2, tile - inset * 2)

    _rect(s, top_edge, 1, 1, tile - 2, 1)
    _rect(s, top_edge, 1, 1, 1, tile - 2)
    _rect(s, bottom_edge, 1, tile - 2, tile - 2, 1)
    _rect(s, bottom_edge, tile - 2, 1, 1, tile - 2)

    b = max(2, tile // 16)
    for cx, cy in ((b, b), (tile - 1 - b, b), (b, tile - 1 - b), (tile - 1 - b, tile - 1 - b)):
        _rect(s, bolt, cx, cy, 1, 1)
    return s


# ---------- Ghost placement ----------


def _ghost() -> pygame.Surface:
    tile = _tile()
    s = _new(tile)
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
            _px(s, outline, x + dx * i, y)
            _px(s, outline, x, y + dy * i)
    return s


# ---------- Items ----------


def _item_icon(kind: str) -> pygame.Surface:
    item = _item()
    s = _new(item)

    # Proportionally scale inset/thickness from the canonical 16-px design.
    def r(px_at_16: int) -> int:
        return max(1, round(px_at_16 * item / 16))

    if kind == "iron":
        c = PALETTE.iron
        hi = lighten(c, 0.25)
        sh = darken(c, 0.35)
        _rect(s, sh, r(2), r(3), r(12), r(10))
        _rect(s, c,  r(2), r(3), r(12), r(8))
        _rect(s, hi, r(3), r(4), r(10), r(2))
    elif kind == "copper":
        c = PALETTE.copper
        hi = lighten(c, 0.25)
        sh = darken(c, 0.35)
        _rect(s, sh, r(2), r(5), r(12), r(8))
        _rect(s, c,  r(2), r(4), r(12), r(7))
        _rect(s, hi, r(3), r(5), r(10), r(2))
    elif kind == "coal":
        c = PALETTE.coal
        hi = lighten(c, 0.35)
        for x, y, w, h in ((r(3), r(4), r(10), r(8)), (r(5), r(3), r(6), r(2)), (r(4), r(11), r(8), r(2))):
            _rect(s, c, x, y, w, h)
        for px, py in ((r(5), r(6)), (r(9), r(7)), (r(7), r(9))):
            _rect(s, hi, px, py, max(1, r(1)), max(1, r(1)))
    elif kind == "plate":
        c = PALETTE.plate
        hi = lighten(c, 0.3)
        sh = darken(c, 0.3)
        _rect(s, sh, r(1), r(6), r(14), r(5))
        _rect(s, c,  r(1), r(6), r(14), r(4))
        _rect(s, hi, r(2), r(7), r(12), r(1))
    elif kind == "gear":
        c = PALETTE.gear
        hi = lighten(c, 0.25)
        sh = darken(c, 0.3)
        cx = item // 2
        cy = item // 2
        outer = max(4, item // 2 - 2)
        inner = max(1, item // 8)
        pygame.draw.circle(s, sh, (cx, cy), outer)
        pygame.draw.circle(s, c, (cx, cy), outer - 1)
        pygame.draw.circle(s, PALETTE.bg_raised, (cx, cy), inner)
        tooth = max(2, outer - 2)
        for dx, dy in ((0, -tooth), (tooth, 0), (0, tooth), (-tooth, 0),
                       (tooth - 1, -(tooth - 1)), (-(tooth - 1), (tooth - 1)),
                       ((tooth - 1), (tooth - 1)), (-(tooth - 1), -(tooth - 1))):
            _rect(s, hi, cx + dx, cy + dy, max(1, r(1)), max(1, r(1)))
    else:
        _rect(s, PALETTE.danger, r(2), r(2), r(12), r(12))
    return s


ITEM_KINDS: tuple[str, ...] = ("iron", "copper", "coal", "plate", "gear")


# ---------- Public API ----------


def generate_all(force: bool = False) -> None:
    """Generate every sprite to the tile-size-scoped cache directory."""
    paths.ensure_dirs()
    out_dir = paths.sprites_dir()

    def _save(surf: pygame.Surface, name: str) -> None:
        out = out_dir / name
        if force or not out.exists():
            pygame.image.save(surf, str(out))

    _save(_floor(), "floor.png")
    _save(_building_base(), "building_base.png")
    _save(_ghost(), "ghost.png")

    for (direction, frame), surf in _belts().items():
        _save(surf, f"belt_{direction}_f{frame}.png")

    for kind in ITEM_KINDS:
        _save(_item_icon(kind), f"item_{kind}.png")
