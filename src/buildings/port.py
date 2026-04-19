"""Input / output port on a building cell."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from ..items.item import Item
from ..items.item_type import ItemType
from ..world.direction import Direction
from ..world.tile import Coord


class PortKind(Enum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass
class Port:
    kind: PortKind
    side: Direction            # outward-facing side of the building
    cell: Coord                # absolute world-cell this port lives on
    filter: ItemType | None = None
    capacity: int = 8
    buffer: deque[Item] = field(default_factory=deque)

    # -- input ports -------------------------------------------------------

    def can_accept(self, item: Item) -> bool:
        if self.kind is not PortKind.INPUT:
            return False
        if self.filter is not None and item.type is not self.filter:
            return False
        return len(self.buffer) < self.capacity

    def accept(self, item: Item) -> bool:
        if not self.can_accept(item):
            return False
        self.buffer.append(item)
        return True

    # -- output ports ------------------------------------------------------

    def has_item(self) -> bool:
        return bool(self.buffer)

    def peek(self) -> Item | None:
        return self.buffer[0] if self.buffer else None

    def pop(self) -> Item | None:
        return self.buffer.popleft() if self.buffer else None

    def push(self, item: Item) -> bool:
        if self.kind is not PortKind.OUTPUT:
            return False
        if len(self.buffer) >= self.capacity:
            return False
        self.buffer.append(item)
        return True

    # -- filter helpers ----------------------------------------------------

    def count_of(self, item_type: ItemType) -> int:
        return sum(1 for i in self.buffer if i.type is item_type)

    def drain_of(self, item_type: ItemType, n: int) -> int:
        """Remove up to n items of the given type. Returns amount removed."""
        removed = 0
        remaining = deque()
        while self.buffer and removed < n:
            it = self.buffer.popleft()
            if it.type is item_type:
                removed += 1
            else:
                remaining.append(it)
        # preserve non-matching order
        for it in remaining:
            self.buffer.appendleft(it)
        return removed
