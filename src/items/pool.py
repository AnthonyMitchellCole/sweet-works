"""Object pool for ``Item`` instances.

The simulation proper does not need ``Item`` objects -- belts and ports
store ``int16`` type-ids directly. A tiny pool exists here for UI affordances
(hover tooltips, cursor previews) that still want the convenience of an
``Item`` wrapper.
"""

from __future__ import annotations

from .item import Item
from .item_type import ItemType
from .registry import ITEM_TYPE_BY_ID


class ItemPool:
    __slots__ = ("_free",)

    def __init__(self, initial: int = 0) -> None:
        self._free: list[Item] = []
        if initial:
            # Pre-warm with a placeholder type; callers always overwrite.
            iron = ITEM_TYPE_BY_ID[1]
            assert iron is not None
            for _ in range(initial):
                self._free.append(Item(type=iron))

    def acquire(self, type_id: int) -> Item:
        itype = ITEM_TYPE_BY_ID[type_id]
        if itype is None:
            raise ValueError(f"invalid item type_id: {type_id}")
        if self._free:
            it = self._free.pop()
            it.type = itype
            it.prev_slot = 0.0
            it.slot = 0.0
            return it
        return Item(type=itype)

    def acquire_of(self, item_type: ItemType) -> Item:
        return self.acquire(item_type.type_id)

    def release(self, item: Item) -> None:
        self._free.append(item)

    def __len__(self) -> int:
        return len(self._free)


POOL = ItemPool()
