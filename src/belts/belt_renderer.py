"""Animated belt renderer with sub-tick item interpolation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..core import config
from .belt import ConveyorBelt

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera


def _frame_index(time: float) -> int:
    return int(time * config.BELT_ANIM_HZ) % config.BELT_FRAMES


def draw_belt(
    belt: ConveyorBelt,
    surface: pygame.Surface,
    camera: "Camera",
    assets: "AssetLoader",
    time: float,
) -> None:
    frame = _frame_index(time)
    sprite = assets.belt(belt.direction.value, frame)
    x, y = camera.world_to_screen(belt.pos[0] * config.TILE, belt.pos[1] * config.TILE)
    size = int(config.TILE * camera.zoom)
    if camera.zoom != 1.0:
        sprite = pygame.transform.scale(sprite, (size, size))
    surface.blit(sprite, (x, y))


def draw_belt_items(
    belt: ConveyorBelt,
    surface: pygame.Surface,
    camera: "Camera",
    assets: "AssetLoader",
    sim_alpha: float,
) -> None:
    dx, dy = belt.direction.vector
    size = int(config.TILE * camera.zoom)
    origin_x, origin_y = camera.world_to_screen(
        belt.pos[0] * config.TILE, belt.pos[1] * config.TILE
    )

    for slot_index, item in enumerate(belt.slots):
        if item is None:
            continue
        frac = _interp_slot(item, sim_alpha, belt.SLOTS)
        t = (frac + 0.5) / belt.SLOTS  # position along the tile (0..1)
        # Compute center in screen-space
        if dx != 0:
            cx = origin_x + int(size * (0.5 + dx * (t - 0.5)))
            cy = origin_y + size // 2
        else:
            cx = origin_x + size // 2
            cy = origin_y + int(size * (0.5 + dy * (t - 0.5)))
        _ = slot_index  # kept for clarity; slot math uses item.slot

        icon = assets.item_icon(item.type.id)
        icon_size = max(8, int(config.ITEM_PX * camera.zoom))
        if icon.get_width() != icon_size:
            icon = pygame.transform.scale(icon, (icon_size, icon_size))
        surface.blit(icon, (cx - icon_size // 2, cy - icon_size // 2))


def _interp_slot(item, sim_alpha: float, slots: int) -> float:
    a = max(0.0, min(1.0, sim_alpha))
    return item.prev_slot + (item.slot - item.prev_slot) * a
