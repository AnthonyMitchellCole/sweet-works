"""Item icon generator (relocated from :mod:`assets.generator`).

Each icon is authored at the canonical 16-px grid and scaled
proportionally to :data:`config.ITEM_PX`.
"""

from __future__ import annotations

import pygame

from ...core import config
from ...design.palette import PALETTE, darken, lighten
from . import draw


ITEM_KINDS: tuple[str, ...] = ("iron", "copper", "coal", "plate", "gear")


def item_icon(kind: str) -> pygame.Surface:
    item = config.ITEM_PX
    s = draw.new_surface((item, item))

    def r(px_at_16: int) -> int:
        return max(1, round(px_at_16 * item / 16))

    if kind == "iron":
        c = PALETTE.iron
        hi = lighten(c, 0.25)
        sh = darken(c, 0.35)
        draw.fill_rect(s, sh, r(2), r(3), r(12), r(10))
        draw.fill_rect(s, c, r(2), r(3), r(12), r(8))
        draw.fill_rect(s, hi, r(3), r(4), r(10), r(2))
    elif kind == "copper":
        c = PALETTE.copper
        hi = lighten(c, 0.25)
        sh = darken(c, 0.35)
        draw.fill_rect(s, sh, r(2), r(5), r(12), r(8))
        draw.fill_rect(s, c, r(2), r(4), r(12), r(7))
        draw.fill_rect(s, hi, r(3), r(5), r(10), r(2))
    elif kind == "coal":
        c = PALETTE.coal
        hi = lighten(c, 0.35)
        for x, y, w, h in (
            (r(3), r(4), r(10), r(8)),
            (r(5), r(3), r(6), r(2)),
            (r(4), r(11), r(8), r(2)),
        ):
            draw.fill_rect(s, c, x, y, w, h)
        for px, py in ((r(5), r(6)), (r(9), r(7)), (r(7), r(9))):
            draw.fill_rect(s, hi, px, py, max(1, r(1)), max(1, r(1)))
    elif kind == "plate":
        c = PALETTE.plate
        hi = lighten(c, 0.3)
        sh = darken(c, 0.3)
        draw.fill_rect(s, sh, r(1), r(6), r(14), r(5))
        draw.fill_rect(s, c, r(1), r(6), r(14), r(4))
        draw.fill_rect(s, hi, r(2), r(7), r(12), r(1))
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
        for dx, dy in (
            (0, -tooth),
            (tooth, 0),
            (0, tooth),
            (-tooth, 0),
            (tooth - 1, -(tooth - 1)),
            (-(tooth - 1), (tooth - 1)),
            ((tooth - 1), (tooth - 1)),
            (-(tooth - 1), -(tooth - 1)),
        ):
            draw.fill_rect(s, hi, cx + dx, cy + dy, max(1, r(1)), max(1, r(1)))
    else:
        draw.fill_rect(s, PALETTE.danger, r(2), r(2), r(12), r(12))
    return s


__all__ = ["ITEM_KINDS", "item_icon"]
