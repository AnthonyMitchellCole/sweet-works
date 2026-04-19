"""Scene base class used by the Game scene stack."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from ..core.game import Game


class Scene:
    def __init__(self) -> None:
        self.game: Game | None = None

    # -- lifecycle ---------------------------------------------------------

    def enter(self, game: Game) -> None:
        self.game = game
        self.on_enter()

    def exit(self) -> None:
        self.on_exit()
        self.game = None

    def pause(self) -> None:
        self.on_pause()

    def resume(self) -> None:
        self.on_resume()

    # -- hooks (override) --------------------------------------------------

    def on_enter(self) -> None: ...
    def on_exit(self) -> None: ...
    def on_pause(self) -> None: ...
    def on_resume(self) -> None: ...
    def on_resize(self, size: tuple[int, int]) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None: ...
    def update(self, dt: float, sim_ticks: int, sim_alpha: float) -> None: ...
    def render(self, surface: pygame.Surface) -> None: ...
