"""Canonical item registry."""

from __future__ import annotations

from dataclasses import dataclass

from ..design.palette import PALETTE
from .item_type import ItemType


@dataclass(frozen=True)
class ItemRegistry:
    iron: ItemType = ItemType("iron", "Iron Ore", PALETTE.iron, "item_iron")
    copper: ItemType = ItemType("copper", "Copper Ore", PALETTE.copper, "item_copper")
    coal: ItemType = ItemType("coal", "Coal", PALETTE.coal, "item_coal")
    plate: ItemType = ItemType("plate", "Iron Plate", PALETTE.plate, "item_plate")
    gear: ItemType = ItemType("gear", "Iron Gear", PALETTE.gear, "item_gear")

    def all(self) -> tuple[ItemType, ...]:
        return (self.iron, self.copper, self.coal, self.plate, self.gear)

    def by_id(self, item_id: str) -> ItemType:
        for t in self.all():
            if t.id == item_id:
                return t
        raise KeyError(item_id)


ITEMS = ItemRegistry()
