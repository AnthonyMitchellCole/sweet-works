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
    cocoa_bean: ItemType
    sugar_crystal: ItemType
    milk: ItemType
    chocolate: ItemType
    caramel: ItemType
    candy_bar: ItemType

    def all(self) -> tuple[ItemType, ...]:
        return (
            self.cocoa_bean,
            self.sugar_crystal,
            self.milk,
            self.chocolate,
            self.caramel,
            self.candy_bar,
        )

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
    ItemType("cocoa_bean", "Cocoa Bean", PALETTE.cocoa_bean, "item_cocoa_bean"),
    ItemType("sugar_crystal", "Sugar Crystal", PALETTE.sugar_crystal, "item_sugar_crystal"),
    ItemType("milk", "Milk", PALETTE.milk, "item_milk"),
    ItemType("chocolate", "Chocolate Bar", PALETTE.chocolate, "item_chocolate"),
    ItemType("caramel", "Caramel", PALETTE.caramel, "item_caramel"),
    ItemType("candy_bar", "Candy Bar", PALETTE.candy_bar, "item_candy_bar"),
)

# Assign stable type_ids: slot 0 reserved for EMPTY, real types start at 1.
_WITH_IDS: tuple[ItemType, ...] = tuple(
    _with_id(t, i + 1) for i, t in enumerate(_BASE_ITEMS)
)

ITEMS = ItemRegistry(
    cocoa_bean=_WITH_IDS[0],
    sugar_crystal=_WITH_IDS[1],
    milk=_WITH_IDS[2],
    chocolate=_WITH_IDS[3],
    caramel=_WITH_IDS[4],
    candy_bar=_WITH_IDS[5],
)

# O(1) lookup by type_id. Index 0 = None (empty).
ITEM_TYPE_BY_ID: tuple[ItemType | None, ...] = (None,) + _WITH_IDS

_BY_STR: dict[str, ItemType] = {t.id: t for t in _WITH_IDS}


def type_id_of(item: ItemType) -> int:
    return item.type_id
