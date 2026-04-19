"""Zoom-aware scaled-sprite cache.

``pygame.transform.scale`` is expensive enough that doing it per-blit (as
every original renderer path did) becomes the dominant cost once there are
many tiles on screen. The cache maps ``(sprite_key, zoom_bin)`` to a
pre-scaled ``Surface``, with ``zoom_bin = round(zoom * ZOOM_QUANT)``.

The cache evicts bins aggressively: only the most recently used bin for
each sprite is retained by default, so the memory footprint stays bounded
even while the user zooms around smoothly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..core import config

if TYPE_CHECKING:
    pass


def zoom_bin(zoom: float) -> int:
    """Quantise a float zoom to the nearest bin index."""
    return max(1, int(round(zoom * config.ZOOM_QUANT)))


def zoom_from_bin(bin_idx: int) -> float:
    return bin_idx / config.ZOOM_QUANT


class ScaledSpriteCache:
    """Cache of zoom-scaled surfaces keyed by (sprite_key, bin)."""

    def __init__(self, max_bins_per_sprite: int = 2) -> None:
        self._cache: dict[tuple[str, int], pygame.Surface] = {}
        self._recent: dict[str, list[int]] = {}
        self._max = max(1, max_bins_per_sprite)

    def get(self, key: str, base: pygame.Surface, zoom: float) -> pygame.Surface:
        b = zoom_bin(zoom)
        cache_key = (key, b)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # No scaling needed at the canonical bin.
        if b == config.ZOOM_QUANT:
            surf = base
        else:
            size = max(1, int(round(base.get_width() * zoom_from_bin(b))))
            if size == base.get_width():
                surf = base
            else:
                surf = pygame.transform.scale(base, (size, size))

        self._cache[cache_key] = surf
        recent = self._recent.setdefault(key, [])
        if b in recent:
            recent.remove(b)
        recent.append(b)
        # LRU-evict older bins for this sprite.
        while len(recent) > self._max:
            drop = recent.pop(0)
            self._cache.pop((key, drop), None)
        return surf

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
            self._recent.clear()
            return
        for b in self._recent.pop(key, ()):
            self._cache.pop((key, b), None)

    def __len__(self) -> int:
        return len(self._cache)


__all__ = ["ScaledSpriteCache", "zoom_bin", "zoom_from_bin"]
