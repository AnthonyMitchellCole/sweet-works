"""Smoke tests for :class:`src.ui.objectives_window.ObjectivesWindow`.

These don't pixel-compare -- they just make sure the panel can be
constructed, attached, opened, updated, rendered, and closed with a
live :class:`StatsTracker` + :class:`ObjectivesState` pair without
raising. That protects against regressions in the data-to-UI bindings
(status snapshot shape, icon resolution, tab payloads) that would
otherwise only surface when the player hits ``J`` in a real session.
"""

from __future__ import annotations

import pygame
import pytest

from src.assets.loader import AssetLoader
from src.core import config
from src.core.events import EventBus
from src.items.registry import ITEMS
from src.stats.objectives import ObjectivesState
from src.stats.tracker import StatsTracker
from src.ui.objectives_window import ObjectivesWindow


@pytest.fixture(scope="module")
def _headless_assets() -> AssetLoader:
    """Prepare pygame + AssetLoader once per test module (fonts, sprites)."""
    pygame.display.init()
    pygame.font.init()
    pygame.display.set_mode(config.WINDOW)
    assets = AssetLoader()
    assets.prepare()
    return assets


def _produce(bus: EventBus, item_id: str, n: int = 1) -> None:
    item = next(i for i in ITEMS.all() if i.id == item_id)
    for _ in range(n):
        bus.emit("item.produced", item_type=item)


def test_window_open_update_render_closes(_headless_assets: AssetLoader) -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    objectives = ObjectivesState(bus, tracker)
    window = ObjectivesWindow(_headless_assets)
    try:
        window.layout(config.WINDOW)
        window.attach(tracker, objectives)

        # Closed panels short-circuit their render paths and must not
        # touch the framebuffer.
        surface = pygame.Surface(config.WINDOW)
        assert window.is_open is False
        window.render(surface)  # no-op

        # Open + one frame of update/render with some real data.
        window.open()
        _produce(bus, "cocoa_bean", 2)
        tracker.update(1.0, 1.0)
        objectives.update(1.0, 1.0)

        for _ in range(3):
            window.update(1 / 60.0, (1, 1), False, False)
            window.render(surface)

        # Escape closes the panel; a few more update ticks settle the
        # slide tween and bring ``is_open`` back to False.
        esc = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_ESCAPE})
        assert window.handle_event(esc) is True
        for _ in range(60):
            window.update(1 / 60.0, (1, 1), False, False)
        assert window.is_open is False
    finally:
        window.close_subscriptions()
        objectives.close()
        tracker.close()


def test_window_tab_switching_via_click(_headless_assets: AssetLoader) -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    objectives = ObjectivesState(bus, tracker)
    window = ObjectivesWindow(_headless_assets)
    try:
        window.layout(config.WINDOW)
        window.attach(tracker, objectives)
        window.open()

        # A single render pass populates ``_hits`` with the tab strip.
        surface = pygame.Surface(config.WINDOW)
        window.update(1 / 60.0, (1, 1), False, False)
        window.render(surface)

        tab_hits = [h for h in window._hits if h.payload[0] == "tab"]
        assert tab_hits, "tab strip should register hit targets after render"
        # Click the last tab and verify active tab switches to it.
        target = tab_hits[-1]
        target_id = target.payload[1]
        click = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": target.rect.center},
        )
        assert window.handle_event(click) is True
        assert window._active_tab == target_id
    finally:
        window.close_subscriptions()
        objectives.close()
        tracker.close()


def test_completion_pulse_triggers_without_error(
    _headless_assets: AssetLoader,
) -> None:
    bus = EventBus()
    tracker = StatsTracker(bus)
    objectives = ObjectivesState(bus, tracker)
    window = ObjectivesWindow(_headless_assets)
    try:
        window.layout(config.WINDOW)
        window.attach(tracker, objectives)
        window.open()

        # Complete the first objective in the default catalog (1 cocoa
        # bean). The window's ``_on_objective_completed`` hook should
        # kick off the pulse animation without raising.
        _produce(bus, "cocoa_bean", 1)
        tracker.update(1.0, 1.0)
        objectives.update(1.0, 1.0)

        surface = pygame.Surface(config.WINDOW)
        for _ in range(10):
            window.update(1 / 60.0, (1, 1), False, False)
            window.render(surface)
    finally:
        window.close_subscriptions()
        objectives.close()
        tracker.close()
