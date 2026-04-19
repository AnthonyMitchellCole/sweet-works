"""Industrial-dark color palette, exposed as a frozen dataclass singleton."""

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
    # Backgrounds
    bg_deep: Color = _hex("#0E1014")
    bg_base: Color = _hex("#161A22")
    bg_raised: Color = _hex("#1F2530")
    surface: Color = _hex("#2A3240")

    # Lines and muted
    line: Color = _hex("#394456")
    muted: Color = _hex("#6B7689")

    # Text
    text_body: Color = _hex("#B8C2D1")
    text_strong: Color = _hex("#E8EDF5")

    # Accents
    primary: Color = _hex("#F5A524")
    secondary: Color = _hex("#4DA3FF")
    success: Color = _hex("#3DD68C")
    danger: Color = _hex("#F26D6D")
    warning: Color = _hex("#E8C547")

    # Items
    iron: Color = _hex("#B8C2D1")
    copper: Color = _hex("#E28447")
    coal: Color = _hex("#2B2F36")
    plate: Color = _hex("#9AA6B8")
    gear: Color = _hex("#D9A441")


PALETTE = Palette()
