"""Filesystem locations for fonts and sprites (absolute paths)."""

from __future__ import annotations

from pathlib import Path


ROOT: Path = Path(__file__).resolve().parents[2]
ASSETS: Path = ROOT / "assets"
FONTS_DIR: Path = ASSETS / "fonts"
SPRITES_DIR: Path = ASSETS / "sprites"


def sprites_dir() -> Path:
    """Sprite cache folder scoped to the current tile/item size.

    Changing `config.TILE` or `config.ITEM_PX` automatically picks a fresh
    cache so stale PNGs generated at a different resolution are never used.
    """
    from ..core import config

    return SPRITES_DIR / f"t{config.TILE}_i{config.ITEM_PX}"


FONT_FILES: dict[str, str] = {
    "Silkscreen": "Silkscreen-Regular.ttf",
    "Jersey10": "Jersey10-Regular.ttf",
}


FONT_URLS: dict[str, str] = {
    "Silkscreen-Regular.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/"
        "ofl/silkscreen/Silkscreen-Regular.ttf"
    ),
    "Jersey10-Regular.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/"
        "ofl/jersey10/Jersey10-Regular.ttf"
    ),
}


def ensure_dirs() -> None:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    SPRITES_DIR.mkdir(parents=True, exist_ok=True)
    sprites_dir().mkdir(parents=True, exist_ok=True)
