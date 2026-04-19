"""Typography scale.

Defines a set of named text styles (family + size). Resolving a style to a
`pygame.Font` is done by the asset loader; this module stays pure-data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FontFamily(str, Enum):
    DISPLAY = "PressStart2P"
    UI = "PixelifySans"


class FontWeight(int, Enum):
    REGULAR = 400
    MEDIUM = 500
    SEMIBOLD = 600
    BOLD = 700


@dataclass(frozen=True)
class TextStyle:
    name: str
    family: FontFamily
    size: int
    weight: FontWeight = FontWeight.REGULAR
    letter_spacing: int = 0
    line_height: float = 1.2


@dataclass(frozen=True)
class TypeScale:
    display: TextStyle = TextStyle("display", FontFamily.DISPLAY, 28)
    h1: TextStyle = TextStyle("h1", FontFamily.UI, 28, FontWeight.BOLD)
    h2: TextStyle = TextStyle("h2", FontFamily.UI, 20, FontWeight.SEMIBOLD)
    body: TextStyle = TextStyle("body", FontFamily.UI, 16, FontWeight.MEDIUM)
    caption: TextStyle = TextStyle("caption", FontFamily.UI, 13, FontWeight.REGULAR)
    mono: TextStyle = TextStyle("mono", FontFamily.DISPLAY, 12)
    label: TextStyle = TextStyle("label", FontFamily.DISPLAY, 10)


TYPE = TypeScale()

ALL_STYLES: tuple[TextStyle, ...] = (
    TYPE.display,
    TYPE.h1,
    TYPE.h2,
    TYPE.body,
    TYPE.caption,
    TYPE.mono,
    TYPE.label,
)
