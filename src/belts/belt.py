"""Conveyor belt tile: a straight 4-slot lane in one cardinal direction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..items.item import Item
from ..world.direction import Direction
from ..world.tile import Coord, Tile

if TYPE_CHECKING:
    pass


class ConveyorBelt(Tile):
    SLOTS: int = 4

    def __init__(self, pos: Coord, direction: Direction) -> None:
        super().__init__(pos)
        self.direction = direction
        self.slots: list[Item | None] = [None] * self.SLOTS

    # -- interface used by BeltNetwork & building ports --------------------

    def can_accept(self) -> bool:
        return self.slots[0] is None

    def accept(self, item: Item) -> bool:
        if not self.can_accept():
            return False
        self.slots[0] = item
        item.prev_slot = -1.0
        item.slot = 0.0
        return True

    # -- enumeration helpers ----------------------------------------------

    def occupied_count(self) -> int:
        return sum(1 for s in self.slots if s is not None)
