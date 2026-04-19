"""Filesystem locations for fonts and sprites (absolute paths)."""

from __future__ import annotations

from pathlib import Path


ROOT: Path = Path(__file__).resolve().parents[2]
ASSETS: Path = ROOT / "assets"
FONTS_DIR: Path = ASSETS / "fonts"
SPRITES_DIR: Path = ASSETS / "sprites"


FONT_FILES: dict[str, str] = {
    "PressStart2P": "PressStart2P-Regular.ttf",
    "PixelifySans": "PixelifySans.ttf",
}


FONT_URLS: dict[str, str] = {
    "PressStart2P-Regular.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/"
        "ofl/pressstart2p/PressStart2P-Regular.ttf"
    ),
    "PixelifySans.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/"
        "ofl/pixelifysans/PixelifySans%5Bwght%5D.ttf"
    ),
}


def ensure_dirs() -> None:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    SPRITES_DIR.mkdir(parents=True, exist_ok=True)
