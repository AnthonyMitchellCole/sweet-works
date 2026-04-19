"""Static, data-only definition of an item kind."""

from __future__ import annotations

from dataclasses import dataclass

from ..design.palette import Color

# Sentinel int16 used across the SoA belt & port buffers. 0 always means
# "slot / buffer cell is empty". Real item type_ids are 1..N.
EMPTY_ID: int = 0


@dataclass(frozen=True)
class ItemType:
    id: str
    name: str
    color: Color
    sprite_key: str  # resolved via AssetLoader.item_icon(id)
    type_id: int = 0  # numeric id used by the SoA sim. Assigned by ItemRegistry.
