"""Centralized asset loader.

Handles:
- Downloading Google Fonts on first run (or failing clearly).
- Resolving `TextStyle` objects to cached `pygame.Font` instances.
- Loading cached sprites produced by `generator.py`.
- Rendering text surfaces with a small memoization cache.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pygame

from ..design.palette import Color
from ..design.typography import ALL_STYLES, TextStyle
from . import generator, paths


class AssetLoader:
    def __init__(self) -> None:
        self._fonts: dict[tuple[str, int, int], pygame.font.Font] = {}
        self._sprites: dict[str, pygame.Surface] = {}
        self._text_cache: dict[tuple[str, str, Color], pygame.Surface] = {}
        self._ready: bool = False

    # -- bootstrap ---------------------------------------------------------

    def prepare(self) -> None:
        """Download fonts (if missing) and generate sprites (if missing)."""
        paths.ensure_dirs()
        self._ensure_fonts()
        generator.generate_all(force=False)
        self._ready = True

    def _ensure_fonts(self) -> None:
        for filename, url in paths.FONT_URLS.items():
            dest = paths.FONTS_DIR / filename
            if dest.exists():
                continue
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = resp.read()
                dest.write_bytes(data)
            except Exception as exc:  # pragma: no cover - network path
                raise RuntimeError(
                    f"Failed to download font {filename} from {url}. "
                    f"Place it manually in {paths.FONTS_DIR}. ({exc})"
                ) from exc

    # -- fonts -------------------------------------------------------------

    def font(self, style: TextStyle) -> pygame.font.Font:
        key = (style.family.value, int(style.weight), style.size)
        cached = self._fonts.get(key)
        if cached is not None:
            return cached
        filename = paths.FONT_FILES.get(style.family.value)
        if filename is None:
            raise KeyError(f"Unknown font family: {style.family.value}")
        path: Path = paths.FONTS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Font file missing: {path}. Run AssetLoader.prepare() first."
            )
        f = pygame.font.Font(str(path), style.size)
        f.set_bold(int(style.weight) >= 600)
        self._fonts[key] = f
        return f

    def warm_fonts(self) -> None:
        for style in ALL_STYLES:
            self.font(style)

    def render_text(
        self, text: str, style: TextStyle, color: Color
    ) -> pygame.Surface:
        key = (style.name, text, color)
        cached = self._text_cache.get(key)
        if cached is not None:
            return cached
        surf = self.font(style).render(text, False, color)
        self._text_cache[key] = surf
        return surf

    # -- sprites -----------------------------------------------------------

    def sprite(self, key: str) -> pygame.Surface:
        cached = self._sprites.get(key)
        if cached is not None:
            return cached
        path = paths.sprites_dir() / f"{key}.png"
        if not path.exists():
            generator.generate_all(force=False)
        if not path.exists():
            raise FileNotFoundError(f"Sprite missing: {path}")
        surf = pygame.image.load(str(path)).convert_alpha()
        self._sprites[key] = surf
        return surf

    def belt(self, direction: str, frame: int) -> pygame.Surface:
        return self.sprite(f"belt_{direction}_f{frame}")

    def item_icon(self, item_id: str) -> pygame.Surface:
        return self.sprite(f"item_{item_id}")
