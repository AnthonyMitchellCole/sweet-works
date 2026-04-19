"""Smoothly-lerped camera with zoom and world/screen conversions."""

from __future__ import annotations

import math

from ..core import config


class Camera:
    def __init__(self, viewport: tuple[int, int]) -> None:
        self.viewport_w, self.viewport_h = viewport
        self.x: float = 0.0  # world-space top-left
        self.y: float = 0.0
        self.target_x: float = 0.0
        self.target_y: float = 0.0
        self.zoom: float = config.DEFAULT_ZOOM

    # -- controls ----------------------------------------------------------

    def set_center(self, world_x: float, world_y: float) -> None:
        self.target_x = world_x - self.viewport_w / (2 * self.zoom)
        self.target_y = world_y - self.viewport_h / (2 * self.zoom)
        self.x, self.y = self.target_x, self.target_y

    def pan(self, dx: float, dy: float) -> None:
        self.target_x += dx
        self.target_y += dy

    def set_zoom(self, z: float) -> None:
        self.zoom = max(config.MIN_ZOOM, min(config.MAX_ZOOM, z))

    def zoom_by(self, factor: float, around_screen: tuple[int, int] | None = None) -> None:
        prev = self.zoom
        self.set_zoom(prev * factor)
        if around_screen is None or self.zoom == prev:
            return
        sx, sy = around_screen
        wx_before = self.target_x + sx / prev
        wy_before = self.target_y + sy / prev
        self.target_x = wx_before - sx / self.zoom
        self.target_y = wy_before - sy / self.zoom

    def update(self, dt: float) -> None:
        k = 1.0 - math.exp(-config.CAMERA_SMOOTH * dt)
        self.x += (self.target_x - self.x) * k
        self.y += (self.target_y - self.y) * k

    # -- conversions -------------------------------------------------------

    def world_to_screen(self, wx: float, wy: float) -> tuple[int, int]:
        sx = (wx - self.x) * self.zoom
        sy = (wy - self.y) * self.zoom
        return int(sx), int(sy)

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return self.x + sx / self.zoom, self.y + sy / self.zoom

    def screen_to_tile(self, sx: float, sy: float) -> tuple[int, int]:
        wx, wy = self.screen_to_world(sx, sy)
        return int(wx // config.TILE), int(wy // config.TILE)

    def visible_tile_rect(self) -> tuple[int, int, int, int]:
        min_x, min_y = self.screen_to_world(0, 0)
        max_x, max_y = self.screen_to_world(self.viewport_w, self.viewport_h)
        return (
            int(min_x // config.TILE) - 1,
            int(min_y // config.TILE) - 1,
            int(max_x // config.TILE) + 1,
            int(max_y // config.TILE) + 1,
        )
