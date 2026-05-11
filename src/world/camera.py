"""Smoothly-lerped camera with zoom and world/screen conversions."""

from __future__ import annotations

import math

from ..core import config


class Camera:
    def __init__(self, viewport: tuple[int, int]) -> None:
        self.viewport_w, self.viewport_h = viewport
        self.x: float = 0.0  # world-space top-left (current, smoothly tracked)
        self.y: float = 0.0
        self.target_x: float = 0.0
        self.target_y: float = 0.0
        self.zoom: float = config.DEFAULT_ZOOM
        # Separate target zoom so wheel/keyboard/programmatic smooth zoom
        # share the same lerp kernel as position. ``set_zoom`` still snaps
        # both (preserves benchmark/test behaviour); ``zoom_by`` / ``zoom_to``
        # only nudge the target so the change eases in over a few frames.
        self.target_zoom: float = config.DEFAULT_ZOOM

    def resize(self, viewport: tuple[int, int]) -> None:
        prev_w, prev_h = self.viewport_w, self.viewport_h
        self.viewport_w, self.viewport_h = viewport
        # Keep the world point previously at the screen center still centered.
        dx = (prev_w - viewport[0]) / (2 * self.zoom)
        dy = (prev_h - viewport[1]) / (2 * self.zoom)
        self.x += dx
        self.y += dy
        self.target_x += dx
        self.target_y += dy

    # -- controls ----------------------------------------------------------

    def set_center(self, world_x: float, world_y: float) -> None:
        """Snap the camera so ``(world_x, world_y)`` is the viewport centre."""
        self.target_x = world_x - self.viewport_w / (2 * self.target_zoom)
        self.target_y = world_y - self.viewport_h / (2 * self.target_zoom)
        self.x, self.y = self.target_x, self.target_y

    def pan_to(self, world_x: float, world_y: float) -> None:
        """Smoothly pan toward centring ``(world_x, world_y)``.

        Same destination as :meth:`set_center` but only the target is moved,
        so :meth:`update` lerps the current position in over a few frames.
        """
        self.target_x = world_x - self.viewport_w / (2 * self.target_zoom)
        self.target_y = world_y - self.viewport_h / (2 * self.target_zoom)

    def pan(self, dx: float, dy: float) -> None:
        self.target_x += dx
        self.target_y += dy

    def pan_instant(self, dx: float, dy: float) -> None:
        """1:1 pan: moves both current and target, bypassing smoothing."""
        self.x += dx
        self.y += dy
        self.target_x += dx
        self.target_y += dy

    def set_zoom(self, z: float) -> None:
        """Instantly snap both current and target zoom (used by benchmarks)."""
        z = max(config.MIN_ZOOM, min(config.MAX_ZOOM, z))
        self.zoom = z
        self.target_zoom = z

    def zoom_to(
        self, z: float, around_screen: tuple[int, int] | None = None
    ) -> None:
        """Smoothly zoom toward ``z`` while keeping ``around_screen`` anchored.

        The world point currently under ``around_screen`` stays under that
        screen point once the camera settles. The anchoring is computed
        against ``target_zoom`` / ``target_x/y`` so chained calls (e.g.
        rapid wheel ticks) compose cleanly instead of drifting.
        """
        prev_target = self.target_zoom
        new_target = max(config.MIN_ZOOM, min(config.MAX_ZOOM, z))
        self.target_zoom = new_target
        if around_screen is None or new_target == prev_target:
            return
        sx, sy = around_screen
        wx_before = self.target_x + sx / prev_target
        wy_before = self.target_y + sy / prev_target
        self.target_x = wx_before - sx / new_target
        self.target_y = wy_before - sy / new_target

    def zoom_by(self, factor: float, around_screen: tuple[int, int] | None = None) -> None:
        """Smoothly multiply zoom by ``factor``, anchored on ``around_screen``."""
        self.zoom_to(self.target_zoom * factor, around_screen=around_screen)

    def update(self, dt: float) -> None:
        k = 1.0 - math.exp(-config.CAMERA_SMOOTH * dt)
        self.x += (self.target_x - self.x) * k
        self.y += (self.target_y - self.y) * k
        self.zoom += (self.target_zoom - self.zoom) * k

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
