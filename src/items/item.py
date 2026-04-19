"""Runtime item instance.

In the hot sim path items are stored as ``int16`` type-ids inside
``BeltChainsSoA`` / ``Port`` buffers, so no ``Item`` objects are allocated per
tick. ``Item`` is retained for UI affordances (hover tooltips, drag previews,
HUD event payloads) and is pooled through ``src.items.pool``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .item_type import ItemType


@dataclass
class Item:
    type: ItemType
    prev_slot: float = 0.0
    slot: float = 0.0

    @property
    def type_id(self) -> int:
        return self.type.type_id

    def snap(self) -> None:
        self.prev_slot = self.slot
