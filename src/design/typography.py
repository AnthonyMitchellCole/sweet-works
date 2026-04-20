"""Typography scale.

Defines a set of named text styles (family + size). Resolving a style to a
`pygame.Font` is done by the asset loader; this module stays pure-data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FontFamily(str, Enum):
    DISPLAY = "Silkscreen"
    UI = "Jersey10"


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
    # Silkscreen is dense; UI (Jersey 10) renders a bit small so body/caption/label
    # sizes are nudged up relative to the old Pixelify Sans defaults.
    display: TextStyle = TextStyle("display", FontFamily.DISPLAY, 28)
    h1: TextStyle = TextStyle("h1", FontFamily.UI, 32, FontWeight.BOLD)
    h2: TextStyle = TextStyle("h2", FontFamily.UI, 24, FontWeight.SEMIBOLD)
    body: TextStyle = TextStyle("body", FontFamily.UI, 20, FontWeight.MEDIUM)
    caption: TextStyle = TextStyle("caption", FontFamily.UI, 16, FontWeight.REGULAR)
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
