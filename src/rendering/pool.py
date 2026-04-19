"""Reusable ``pygame.Surface`` pool for UI primitives.

Several UI paths (HUD pulse halo, menu chevrons, cursor ghost) used to
allocate a fresh ``Surface`` every frame. Because Surface creation
triggers a malloc + SDL call, this is visible in a profiler at 60 FPS.
The pool keys surfaces by ``(size, flags)`` and hands back a cleared
surface on each acquire.
"""

from __future__ import annotations

from collections.abc import Iterator

import pygame


class SurfacePool:
    """Pool surfaces by ``(width, height, flags)``."""

    def __init__(self) -> None:
        self._free: dict[tuple[int, int, int], list[pygame.Surface]] = {}

    def acquire(
        self, size: tuple[int, int], flags: int = pygame.SRCALPHA
    ) -> pygame.Surface:
        w, h = size
        key = (w, h, flags)
        bucket = self._free.get(key)
        if bucket:
            surf = bucket.pop()
        else:
            surf = pygame.Surface((w, h), flags)
        # Clear the surface before handing it back.
        surf.fill((0, 0, 0, 0))
        return surf

    def release(self, surf: pygame.Surface) -> None:
        w, h = surf.get_size()
        flags = surf.get_flags()
        self._free.setdefault((w, h, flags), []).append(surf)

    def clear(self) -> None:
        self._free.clear()

    def __iter__(self) -> Iterator[pygame.Surface]:
        for bucket in self._free.values():
            yield from bucket


POOL = SurfacePool()


class _ScopedSurface:
    """Context manager sugar: ``with acquired(pool, size) as surf: ...``."""

    def __init__(self, pool: SurfacePool, size: tuple[int, int], flags: int) -> None:
        self._pool = pool
        self._size = size
        self._flags = flags
        self._surf: pygame.Surface | None = None

    def __enter__(self) -> pygame.Surface:
        self._surf = self._pool.acquire(self._size, self._flags)
        return self._surf

    def __exit__(self, *_: object) -> None:
        if self._surf is not None:
            self._pool.release(self._surf)
            self._surf = None


def acquired(
    size: tuple[int, int], flags: int = pygame.SRCALPHA, pool: SurfacePool = POOL
) -> _ScopedSurface:
    return _ScopedSurface(pool, size, flags)


__all__ = ["POOL", "SurfacePool", "acquired"]
