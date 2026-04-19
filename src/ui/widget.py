"""Base widget with hover/press animation state."""

from __future__ import annotations

import pygame

from ..rendering.animation import AnimValue


class Widget:
    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect
        self.hover_anim = AnimValue(value=0.0, speed=18.0)
        self.press_anim = AnimValue(value=0.0, speed=24.0)
        self.selected: bool = False
        self._hovered: bool = False
        self._pressed: bool = False

    def update(self, dt: float, mouse_pos: tuple[int, int], mouse_down: bool) -> None:
        self._hovered = self.rect.collidepoint(mouse_pos)
        self._pressed = self._hovered and mouse_down
        self.hover_anim.to(1.0 if self._hovered or self.selected else 0.0)
        self.press_anim.to(1.0 if self._pressed else 0.0)
        self.hover_anim.update(dt)
        self.press_anim.update(dt)

    @property
    def hovered(self) -> bool:
        return self._hovered

    @property
    def pressed(self) -> bool:
        return self._pressed

    def clicked(self, mouse_released_this_frame: bool) -> bool:
        return self._hovered and mouse_released_this_frame
