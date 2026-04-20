"""Warm confectionery dark palette, exposed as a frozen dataclass singleton."""

from __future__ import annotations

from dataclasses import dataclass

Color = tuple[int, int, int]
ColorA = tuple[int, int, int, int]


def _hex(h: str) -> Color:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def with_alpha(c: Color, a: int) -> ColorA:
    return (c[0], c[1], c[2], a)


def lighten(c: Color, amount: float) -> Color:
    return (
        min(255, int(c[0] + (255 - c[0]) * amount)),
        min(255, int(c[1] + (255 - c[1]) * amount)),
        min(255, int(c[2] + (255 - c[2]) * amount)),
    )


def darken(c: Color, amount: float) -> Color:
    return (
        max(0, int(c[0] * (1 - amount))),
        max(0, int(c[1] * (1 - amount))),
        max(0, int(c[2] * (1 - amount))),
    )


@dataclass(frozen=True)
class Palette:
    # Backgrounds - warm cocoa-dark so pastel items pop.
    bg_deep: Color = _hex("#1A120B")
    bg_base: Color = _hex("#221914")
    bg_raised: Color = _hex("#2E221B")
    surface: Color = _hex("#3D2D22")

    # Lines and muted
    line: Color = _hex("#524030")
    muted: Color = _hex("#A89786")

    # Text
    text_body: Color = _hex("#E8DBC3")
    text_strong: Color = _hex("#FFF6E6")

    # Accents
    primary: Color = _hex("#F26DA5")   # candy pink
    secondary: Color = _hex("#7ED6DF") # mint
    success: Color = _hex("#A8D56B")   # pistachio
    danger: Color = _hex("#F25C5C")    # strawberry
    warning: Color = _hex("#F2C94C")   # banana

    # Items
    cocoa_bean: Color = _hex("#5C3317")
    sugar_crystal: Color = _hex("#FFD1DC")
    milk: Color = _hex("#F4ECDF")
    chocolate: Color = _hex("#7A4A2B")
    caramel: Color = _hex("#C98A3F")
    candy_bar: Color = _hex("#E94E8F")


PALETTE = Palette()
