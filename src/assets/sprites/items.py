"""Item icon generator (candy factory edition).

Each icon is authored at the canonical 16-px grid and scaled
proportionally to :data:`config.ITEM_PX`.
"""

from __future__ import annotations

import math

import pygame

from ...core import config
from ...design.palette import PALETTE, darken, lighten
from . import draw


ITEM_KINDS: tuple[str, ...] = (
    "cocoa_bean",
    "sugar_crystal",
    "milk",
    "chocolate",
    "caramel",
    "candy_bar",
)


def item_icon(kind: str) -> pygame.Surface:
    item = config.ITEM_PX
    s = draw.new_surface((item, item))

    def r(px_at_16: int) -> int:
        return max(1, round(px_at_16 * item / 16))

    if kind == "cocoa_bean":
        _draw_cocoa_bean(s, r)
    elif kind == "sugar_crystal":
        _draw_sugar_crystal(s, r)
    elif kind == "milk":
        _draw_milk(s, r, item)
    elif kind == "chocolate":
        _draw_chocolate(s, r)
    elif kind == "caramel":
        _draw_caramel(s, r, item)
    elif kind == "candy_bar":
        _draw_candy_bar(s, r)
    else:
        draw.fill_rect(s, PALETTE.danger, r(2), r(2), r(12), r(12))
    return s


def _draw_cocoa_bean(s: pygame.Surface, r) -> None:
    c = PALETTE.cocoa_bean
    hi = lighten(c, 0.35)
    sh = darken(c, 0.35)

    def bean(x: int, y: int, w: int, h: int) -> None:
        # Oval shadow, body, seam highlight.
        for dy in range(h):
            cut = 1 if dy in (0, h - 1) else 0
            draw.fill_rect(s, sh, x + cut, y + dy, w - cut * 2, 1)
        for dy in range(1, h - 1):
            cut = 1 if dy in (1, h - 2) else 0
            draw.fill_rect(s, c, x + cut + 1, y + dy, w - (cut + 1) * 2, 1)
        # Seam highlight down the middle.
        draw.fill_rect(s, hi, x + 2, y + h // 2, w - 4, 1)

    bean(r(2), r(2), r(6), r(4))
    bean(r(8), r(4), r(6), r(4))
    bean(r(3), r(9), r(7), r(4))


def _draw_sugar_crystal(s: pygame.Surface, r) -> None:
    c = PALETTE.sugar_crystal
    hi = lighten(c, 0.25)
    sh = darken(c, 0.25)
    core = lighten(c, 0.55)

    def diamond(cx: int, cy: int, size: int) -> None:
        for dy in range(-size, size + 1):
            span = size - abs(dy)
            if span < 0:
                continue
            draw.fill_rect(s, sh, cx - span, cy + dy, span * 2 + 1, 1)
        for dy in range(-size + 1, size):
            span = size - abs(dy) - 1
            if span < 0:
                continue
            draw.fill_rect(s, c, cx - span, cy + dy, span * 2 + 1, 1)
        for i in range(size - 1):
            draw.pixel(s, hi, cx - i, cy - (size - 1 - i))

    diamond(r(5), r(8), r(3))
    diamond(r(11), r(6), r(3))
    diamond(r(8), r(12), r(3))
    # Sparkle star
    sx = r(12)
    sy = r(3)
    draw.pixel(s, core, sx, sy)
    draw.pixel(s, core, sx - 1, sy)
    draw.pixel(s, core, sx + 1, sy)
    draw.pixel(s, core, sx, sy - 1)
    draw.pixel(s, core, sx, sy + 1)


def _draw_milk(s: pygame.Surface, r, item: int) -> None:
    c = PALETTE.milk
    hi = lighten(c, 0.2)
    sh = darken(c, 0.3)
    cap = PALETTE.secondary

    # Bottle silhouette centered.
    neck_x = r(6)
    neck_y = r(1)
    neck_w = r(4)
    neck_h = r(3)
    body_x = r(4)
    body_y = r(4)
    body_w = r(8)
    body_h = r(10)

    # Cap
    draw.fill_rect(s, darken(cap, 0.3), neck_x, neck_y, neck_w, 1)
    draw.fill_rect(s, cap, neck_x, neck_y + 1, neck_w, neck_h - 1)
    # Shoulder
    draw.fill_rect(s, sh, neck_x - 1, neck_y + neck_h, neck_w + 2, 1)
    # Body
    draw.fill_rect(s, sh, body_x, body_y, body_w, body_h)
    draw.fill_rect(s, c, body_x + 1, body_y + 1, body_w - 2, body_h - 2)
    # Highlight stripe
    draw.fill_rect(s, hi, body_x + 2, body_y + 2, max(1, r(2)), body_h - 4)


def _draw_chocolate(s: pygame.Surface, r) -> None:
    c = PALETTE.chocolate
    hi = lighten(c, 0.3)
    sh = darken(c, 0.4)

    bar_x = r(2)
    bar_y = r(4)
    bar_w = r(12)
    bar_h = r(8)
    # Drop shadow
    draw.fill_rect(s, sh, bar_x, bar_y, bar_w, bar_h)
    # Face
    draw.fill_rect(s, c, bar_x, bar_y, bar_w, max(1, bar_h - 1))
    # Top bevel
    draw.fill_rect(s, hi, bar_x + 1, bar_y, bar_w - 2, 1)
    # Embossed grid: 3 cols x 2 rows.
    cols, rows = 3, 2
    for col in range(1, cols):
        x = bar_x + (bar_w * col) // cols
        draw.fill_rect(s, sh, x, bar_y + 1, 1, bar_h - 2)
        draw.fill_rect(s, hi, x - 1, bar_y + 1, 1, bar_h - 2)
    for row in range(1, rows):
        y = bar_y + (bar_h * row) // rows
        draw.fill_rect(s, sh, bar_x + 1, y, bar_w - 2, 1)


def _draw_caramel(s: pygame.Surface, r, item: int) -> None:
    c = PALETTE.caramel
    hi = lighten(c, 0.3)
    sh = darken(c, 0.3)

    cx = item // 2
    cy = item // 2
    outer = max(3, r(6))
    # Blob
    pygame.draw.circle(s, sh, (cx, cy), outer)
    pygame.draw.circle(s, c, (cx, cy), max(1, outer - 1))
    # Swirl highlight - curved stroke
    sweep_r = max(2, outer - 2)
    for t in range(0, 14):
        a = t * 0.45
        r_ = sweep_r * (1.0 - t / 18)
        px = cx + int(round(math.cos(a) * r_))
        py = cy + int(round(math.sin(a) * r_))
        draw.pixel(s, hi, px, py)
        draw.pixel(s, hi, px, py - 1)
    # Bright core dot
    draw.fill_rect(s, lighten(c, 0.55), cx - 1, cy - 1, 2, 2)


def _draw_candy_bar(s: pygame.Surface, r) -> None:
    c = PALETTE.candy_bar
    hi = lighten(c, 0.3)
    sh = darken(c, 0.3)
    stripe = PALETTE.sugar_crystal

    bar_x = r(3)
    bar_y = r(5)
    bar_w = r(10)
    bar_h = r(6)

    # Twisted end fins
    fin_w = r(2)
    fin_h = r(4)
    # Left fin
    draw.fill_rect(s, sh, bar_x - fin_w, bar_y + 1, fin_w, fin_h - 2)
    draw.fill_rect(s, c, bar_x - fin_w, bar_y + 2, fin_w, max(1, fin_h - 4))
    draw.pixel(s, hi, bar_x - fin_w, bar_y + fin_h // 2)
    # Right fin
    draw.fill_rect(s, sh, bar_x + bar_w, bar_y + 1, fin_w, fin_h - 2)
    draw.fill_rect(s, c, bar_x + bar_w, bar_y + 2, fin_w, max(1, fin_h - 4))
    draw.pixel(s, hi, bar_x + bar_w + fin_w - 1, bar_y + fin_h // 2)

    # Main wrapper
    draw.fill_rect(s, sh, bar_x, bar_y, bar_w, bar_h)
    draw.fill_rect(s, c, bar_x, bar_y, bar_w, max(1, bar_h - 1))
    draw.fill_rect(s, hi, bar_x + 1, bar_y, bar_w - 2, 1)
    # Wrapper stripe
    draw.fill_rect(s, stripe, bar_x + 1, bar_y + bar_h // 2 - 1, bar_w - 2, max(1, r(1)))
    # Pinch marks at wrapper ends
    draw.fill_rect(s, sh, bar_x, bar_y + bar_h // 2, 1, 1)
    draw.fill_rect(s, sh, bar_x + bar_w - 1, bar_y + bar_h // 2, 1, 1)


__all__ = ["ITEM_KINDS", "item_icon"]
