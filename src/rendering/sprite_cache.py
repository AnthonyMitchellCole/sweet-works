"""Zoom-aware scaled-sprite cache.

``pygame.transform.scale`` is expensive enough that doing it per-blit (as
every original renderer path did) becomes the dominant cost once there are
many tiles on screen. The cache maps ``(sprite_key, zoom_bin)`` to a
pre-scaled ``Surface``, with ``zoom_bin = round(zoom * ZOOM_QUANT)``.

The cache evicts bins aggressively: only the most recently used bin for
each sprite is retained by default, so the memory footprint stays bounded
even while the user zooms around smoothly.

A lightweight second tier keyed by ``(sprite_key, bin, angle_deg, mirrored)``
stores rotated + flipped variants on top of the scaled base. Rotations
are 90-deg-quantised (used by buildings' in-world rotation), so the
variant count is bounded (<= 8 per scale bin).
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


def _normalize_angle(angle_deg: float) -> int:
    """Normalise to one of 0/90/180/270 for rotation cache keying."""
    a = int(round(angle_deg)) % 360
    if a < 0:
        a += 360
    # Snap to nearest 90 (the only rotations we actually use here).
    return (a + 45) // 90 % 4 * 90


class ScaledSpriteCache:
    """Cache of zoom-scaled surfaces keyed by (sprite_key, bin).

    Scaled surfaces live in ``_cache``; rotated+flipped variants live in
    ``_variant_cache`` keyed by ``(sprite_key, bin, angle_deg, mirrored)``
    and are derived lazily from the scaled base.
    """

    def __init__(self, max_bins_per_sprite: int = 2) -> None:
        self._cache: dict[tuple[str, int], pygame.Surface] = {}
        self._recent: dict[str, list[int]] = {}
        self._max = max(1, max_bins_per_sprite)
        self._variant_cache: dict[
            tuple[str, int, int, bool], pygame.Surface
        ] = {}

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
            # Drop all variants that derived from the evicted base.
            for vk in [k for k in self._variant_cache if k[0] == key and k[1] == drop]:
                self._variant_cache.pop(vk, None)
        return surf

    def get_oriented(
        self,
        key: str,
        base: pygame.Surface,
        zoom: float,
        angle_deg: float,
        mirrored: bool,
    ) -> pygame.Surface:
        """Return the scaled sprite with a 90-deg rotation + optional flip.

        Mirror is applied **before** rotation so the transform matches
        the port-layout math (local-frame flip, then rotation).
        """
        scaled = self.get(key, base, zoom)
        a = _normalize_angle(angle_deg)
        m = bool(mirrored)
        if a == 0 and not m:
            return scaled
        vkey = (key, zoom_bin(zoom), a, m)
        cached = self._variant_cache.get(vkey)
        if cached is not None:
            return cached
        surf = scaled
        if m:
            surf = pygame.transform.flip(surf, True, False)
        if a != 0:
            surf = pygame.transform.rotate(surf, a)
        self._variant_cache[vkey] = surf
        return surf

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
            self._recent.clear()
            self._variant_cache.clear()
            return
        for b in self._recent.pop(key, ()):
            self._cache.pop((key, b), None)
        for vk in [k for k in self._variant_cache if k[0] == key]:
            self._variant_cache.pop(vk, None)

    def __len__(self) -> int:
        return len(self._cache)


__all__ = ["ScaledSpriteCache", "zoom_bin", "zoom_from_bin"]
