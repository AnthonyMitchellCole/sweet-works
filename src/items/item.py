"""Runtime item instance carried by belts or stored in building buffers."""

from __future__ import annotations

from dataclasses import dataclass

from .item_type import ItemType


@dataclass
class Item:
    type: ItemType
    prev_slot: float = 0.0
    slot: float = 0.0

    def snap(self) -> None:
        self.prev_slot = self.slot
