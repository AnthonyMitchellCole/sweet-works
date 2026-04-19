"""Frame-coherent input state with edge detection."""

from __future__ import annotations

import pygame


class Input:
    def __init__(self) -> None:
        self._keys_down: set[int] = set()
        self._keys_pressed: set[int] = set()
        self._keys_released: set[int] = set()

        self._mouse_down: set[int] = set()
        self._mouse_pressed: set[int] = set()
        self._mouse_released: set[int] = set()

        self.mouse_pos: tuple[int, int] = (0, 0)
        self.mouse_motion: tuple[int, int] = (0, 0)
        self.scroll_y: int = 0
        self.text: str = ""

    def begin_frame(self) -> None:
        self._keys_pressed.clear()
        self._keys_released.clear()
        self._mouse_pressed.clear()
        self._mouse_released.clear()
        self.scroll_y = 0
        self.mouse_motion = (0, 0)
        self.text = ""

    def handle(self, event: pygame.event.Event) -> None:
        t = event.type
        if t == pygame.KEYDOWN:
            if event.key not in self._keys_down:
                self._keys_pressed.add(event.key)
            self._keys_down.add(event.key)
        elif t == pygame.KEYUP:
            self._keys_down.discard(event.key)
            self._keys_released.add(event.key)
        elif t == pygame.MOUSEBUTTONDOWN:
            if event.button not in self._mouse_down:
                self._mouse_pressed.add(event.button)
            self._mouse_down.add(event.button)
        elif t == pygame.MOUSEBUTTONUP:
            self._mouse_down.discard(event.button)
            self._mouse_released.add(event.button)
        elif t == pygame.MOUSEMOTION:
            self.mouse_pos = event.pos
            mx, my = self.mouse_motion
            rx, ry = event.rel
            self.mouse_motion = (mx + rx, my + ry)
        elif t == pygame.MOUSEWHEEL:
            self.scroll_y += event.y
        elif t == pygame.TEXTINPUT:
            self.text += event.text

    # queries
    def key(self, k: int) -> bool:
        return k in self._keys_down

    def key_pressed(self, k: int) -> bool:
        return k in self._keys_pressed

    def key_released(self, k: int) -> bool:
        return k in self._keys_released

    def mouse(self, b: int = 1) -> bool:
        return b in self._mouse_down

    def mouse_pressed(self, b: int = 1) -> bool:
        return b in self._mouse_pressed

    def mouse_released(self, b: int = 1) -> bool:
        return b in self._mouse_released
