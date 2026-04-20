"""Top-level Game: owns the services, runs the main loop, manages scenes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..assets.loader import AssetLoader
from . import config
from . import settings as settings_mod
from .clock import Clock
from .events import EventBus
from .input import Input
from .perf import PERF, timed
from .settings import UserSettings

if TYPE_CHECKING:
    from ..scenes.scene import Scene


class Game:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption(config.TITLE)

        # Load persisted user settings and fold them into ``config`` before
        # we construct anything that reads from it (Clock, AssetLoader caches
        # sized by config, etc.).
        self.settings: UserSettings = settings_mod.load()
        settings_mod.apply_to_config(self.settings)

        self._fullscreen: bool = bool(self.settings.fullscreen)
        self.screen: pygame.Surface = pygame.display.set_mode(
            (config.WINDOW_W, config.WINDOW_H), self._display_flags()
        )

        self.assets = AssetLoader()
        self.assets.prepare()
        self.assets.warm_fonts()

        self.clock = Clock()
        self.input = Input()
        self.events = EventBus()
        self.perf = PERF

        self._scenes: list[Scene] = []
        self._running: bool = False

    # -- scene stack -------------------------------------------------------

    @property
    def scene(self) -> Scene | None:
        return self._scenes[-1] if self._scenes else None

    def push_scene(self, scene: Scene) -> None:
        if self.scene is not None:
            self.scene.pause()
        self._scenes.append(scene)
        scene.enter(self)

    def pop_scene(self) -> None:
        if not self._scenes:
            return
        top = self._scenes.pop()
        top.exit()
        if self.scene is not None:
            self.scene.resume()

    def replace_scene(self, scene: Scene) -> None:
        while self._scenes:
            top = self._scenes.pop()
            top.exit()
        self._scenes.append(scene)
        scene.enter(self)

    # -- window ------------------------------------------------------------

    def _display_flags(self) -> int:
        flags = 0
        if config.RESIZABLE and not self._fullscreen:
            flags |= pygame.RESIZABLE
        if self._fullscreen:
            flags |= pygame.FULLSCREEN
        return flags

    def _on_resize(self, w: int, h: int) -> None:
        w = max(config.MIN_WINDOW_W, w)
        h = max(config.MIN_WINDOW_H, h)
        self.screen = pygame.display.set_mode((w, h), self._display_flags())
        for scene in self._scenes:
            scene.on_resize((w, h))

    def apply_display(self, w: int, h: int, fullscreen: bool) -> None:
        """Rebuild the window with the given size / fullscreen flag."""
        w = max(config.MIN_WINDOW_W, int(w))
        h = max(config.MIN_WINDOW_H, int(h))
        self._fullscreen = bool(fullscreen)
        self.screen = pygame.display.set_mode((w, h), self._display_flags())
        for scene in self._scenes:
            scene.on_resize(self.screen.get_size())

    def apply_settings(self, new: UserSettings, *, persist: bool = True) -> None:
        """Persist and apply a new :class:`UserSettings` to the live game."""
        self.settings = new
        if persist:
            try:
                settings_mod.save(new)
            except OSError:
                pass
        settings_mod.apply(new, self)

    @property
    def window_size(self) -> tuple[int, int]:
        return self.screen.get_size()

    # -- loop --------------------------------------------------------------

    def quit(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        while self._running:
            self._step()
        pygame.quit()

    def _step(self) -> None:
        with timed(self.perf.frame):
            self.input.begin_frame()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                    return
                if event.type == pygame.VIDEORESIZE:
                    self._on_resize(event.w, event.h)
                self.input.handle(event)
                if self.scene is not None:
                    self.scene.handle_event(event)

            pending_ticks = self.clock.tick()

            if self.scene is not None:
                with timed(self.perf.update):
                    self.scene.update(
                        self.clock.dt, pending_ticks, self.clock.sim_alpha
                    )

            # Scenes own their own background fill (many render a gradient or
            # layered world, so a blanket screen.fill here would be wasted work).
            if self.scene is not None:
                with timed(self.perf.render):
                    self.scene.render(self.screen)
            pygame.display.flip()
