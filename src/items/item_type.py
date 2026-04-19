"""Static, data-only definition of an item kind."""

from __future__ import annotations

from dataclasses import dataclass

from ..design.palette import Color


@dataclass(frozen=True)
class ItemType:
    id: str
    name: str
    color: Color
    sprite_key: str  # resolved via AssetLoader.item_icon(id)
