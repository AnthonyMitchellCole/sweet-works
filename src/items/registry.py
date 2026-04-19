"""Canonical item registry.

Every concrete ``ItemType`` receives a stable ``type_id`` in [1, N] on module
import. ``type_id = 0`` is reserved for "empty" in the SoA belt / port arrays.
Lookups are O(1) by id via ``ITEM_TYPE_BY_ID``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..design.palette import PALETTE
from .item_type import EMPTY_ID, ItemType


def _with_id(base: ItemType, type_id: int) -> ItemType:
    # ItemType is frozen; clone with the numeric id set.
    return ItemType(
        id=base.id,
        name=base.name,
        color=base.color,
        sprite_key=base.sprite_key,
        type_id=type_id,
    )


@dataclass(frozen=True)
class ItemRegistry:
    iron: ItemType
    copper: ItemType
    coal: ItemType
    plate: ItemType
    gear: ItemType

    def all(self) -> tuple[ItemType, ...]:
        return (self.iron, self.copper, self.coal, self.plate, self.gear)

    def by_id(self, item_id: str) -> ItemType:
        found = _BY_STR.get(item_id)
        if found is None:
            raise KeyError(item_id)
        return found

    def by_type_id(self, type_id: int) -> ItemType | None:
        if type_id <= EMPTY_ID or type_id >= len(ITEM_TYPE_BY_ID):
            return None
        return ITEM_TYPE_BY_ID[type_id]


_BASE_ITEMS: tuple[ItemType, ...] = (
    ItemType("iron", "Iron Ore", PALETTE.iron, "item_iron"),
    ItemType("copper", "Copper Ore", PALETTE.copper, "item_copper"),
    ItemType("coal", "Coal", PALETTE.coal, "item_coal"),
    ItemType("plate", "Iron Plate", PALETTE.plate, "item_plate"),
    ItemType("gear", "Iron Gear", PALETTE.gear, "item_gear"),
)

# Assign stable type_ids: slot 0 reserved for EMPTY, real types start at 1.
_WITH_IDS: tuple[ItemType, ...] = tuple(
    _with_id(t, i + 1) for i, t in enumerate(_BASE_ITEMS)
)

ITEMS = ItemRegistry(
    iron=_WITH_IDS[0],
    copper=_WITH_IDS[1],
    coal=_WITH_IDS[2],
    plate=_WITH_IDS[3],
    gear=_WITH_IDS[4],
)

# O(1) lookup by type_id. Index 0 = None (empty).
ITEM_TYPE_BY_ID: tuple[ItemType | None, ...] = (None,) + _WITH_IDS

_BY_STR: dict[str, ItemType] = {t.id: t for t in _WITH_IDS}


def type_id_of(item: ItemType) -> int:
    return item.type_id
