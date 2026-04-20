"""Shared middle-mouse drag-pan controller with inertia and cursor swap.

Originally inlined in :class:`~src.scenes.play_scene.PlayScene`. Factored
out so :class:`~src.scenes.research_scene.ResearchScene` (and any future
board-style scenes) can share the exact same feel: 1:1 world tracking
while dragging, EMA-smoothed velocity tracking, exponential inertia
decay on release, and a :data:`pygame.SYSTEM_CURSOR_SIZEALL` swap while
active.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design.palette import PALETTE, with_alpha
from ..rendering.animation import AnimValue
from ..rendering.pool import acquired

if TYPE_CHECKING:
    from ..core.input import Input
    from ..world.camera import Camera


class DragPanController:
    """Middle-mouse drag-pan handler for a :class:`Camera`.

    The controller owns no scene-specific state; call :meth:`update`
    once per frame with the shared :class:`Input` instance and the
    :class:`Camera` to pan, and :meth:`render_indicator` in overlay
    space to draw the subtle ring affordance that signals "dragging".
    """

    def __init__(self) -> None:
        self.active: bool = False
        self._velocity: tuple[float, float] = (0.0, 0.0)
        self._strength = AnimValue(value=0.0, target=0.0, speed=16.0)
        self._cursor_applied: bool = False

    # -- lifecycle ----------------------------------------------------------

    def release(self) -> None:
        """Tear down: clears any lingering cursor override."""
        self._release_cursor()
        self.active = False
        self._velocity = (0.0, 0.0)

    # -- per-frame update --------------------------------------------------

    def update(self, dt: float, input_: Input, camera: Camera) -> None:
        if input_.mouse_pressed(2):
            self.active = True
            self._velocity = (0.0, 0.0)
            self._strength.to(1.0)
            self._apply_cursor()

        if input_.mouse_released(2) and self.active:
            self.active = False
            self._strength.to(0.0)
            self._release_cursor()

        zoom = max(1e-4, camera.zoom)

        if self.active:
            mx, my = input_.mouse_motion
            if mx != 0 or my != 0:
                wx = -mx / zoom
                wy = -my / zoom
                camera.pan_instant(wx, wy)
                if dt > 1e-6:
                    a = config.CAMERA_DRAG_VEL_EMA
                    new_vx = wx / dt
                    new_vy = wy / dt
                    self._velocity = (
                        self._velocity[0] * (1.0 - a) + new_vx * a,
                        self._velocity[1] * (1.0 - a) + new_vy * a,
                    )
            self._strength.update(dt)
            return

        # Inertia coast after release.
        vx, vy = self._velocity
        speed = (vx * vx + vy * vy) ** 0.5
        if speed <= config.CAMERA_DRAG_MIN_SPEED:
            if speed > 0.0:
                self._velocity = (0.0, 0.0)
            self._strength.update(dt)
            return
        camera.pan_instant(vx * dt, vy * dt)
        decay = math.exp(-config.CAMERA_DRAG_INERTIA_DECAY * dt)
        self._velocity = (vx * decay, vy * decay)
        self._strength.update(dt)

    # -- overlay affordance ------------------------------------------------

    def render_indicator(
        self,
        surface: pygame.Surface,
        mouse_pos: tuple[int, int],
        time: float,
    ) -> None:
        """Pulsing primary-tinted ring at the cursor while panning."""
        s = self._strength.value
        if s <= 0.02:
            return
        mx, my = mouse_pos
        pulse = 0.5 + 0.5 * math.sin(time * 5.5)
        radius = int(round(14 + 5 * pulse))
        ring_alpha = int(round(170 * s))
        glow_alpha = int(round(55 * s * (0.6 + 0.4 * pulse)))
        d = radius * 2 + 8
        with acquired((d, d)) as overlay:
            c = (d // 2, d // 2)
            pygame.draw.circle(
                overlay, with_alpha(PALETTE.primary, glow_alpha), c, radius + 3
            )
            pygame.draw.circle(
                overlay, with_alpha(PALETTE.primary, ring_alpha), c, radius, 2
            )
            pygame.draw.circle(
                overlay,
                with_alpha(PALETTE.text_strong, int(ring_alpha * 0.55)),
                c,
                2,
            )
            surface.blit(overlay, (mx - d // 2, my - d // 2))

    # -- cursor swap -------------------------------------------------------

    def _apply_cursor(self) -> None:
        if self._cursor_applied:
            return
        try:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_SIZEALL)
            self._cursor_applied = True
        except (pygame.error, AttributeError, TypeError):
            pass

    def _release_cursor(self) -> None:
        if not self._cursor_applied:
            return
        try:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
        except (pygame.error, AttributeError, TypeError):
            pass
        self._cursor_applied = False


__all__ = ["DragPanController"]
