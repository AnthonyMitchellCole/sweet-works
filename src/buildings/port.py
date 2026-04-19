"""Input / output port on a building cell.

The internal buffer stores ``int16`` type-ids (0 = empty) in a pre-allocated
numpy ring buffer. This keeps port ops allocation-free and lets
``count_of`` collapse to a vectorised ``np.count_nonzero`` for the
hottest path (``Assembler._can_start_craft``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..items.item_type import EMPTY_ID, ItemType
from ..world.direction import Direction
from ..world.tile import Coord


class PortKind(Enum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass
class Port:
    kind: PortKind
    side: Direction                    # outward-facing side of the building
    cell: Coord                        # absolute world-cell this port lives on
    filter: ItemType | None = None
    capacity: int = 8
    _buf: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int16))
    _head: int = 0
    _tail: int = 0
    _count: int = 0

    def __post_init__(self) -> None:
        if self._buf.size != self.capacity:
            self._buf = np.zeros(self.capacity, dtype=np.int16)
            self._head = 0
            self._tail = 0
            self._count = 0

    # ---- introspection ----------------------------------------------------

    def __len__(self) -> int:
        return self._count

    @property
    def count(self) -> int:
        return self._count

    def is_empty(self) -> bool:
        return self._count == 0

    def is_full(self) -> bool:
        return self._count >= self.capacity

    @property
    def buffer(self) -> np.ndarray:
        """View of current buffer contents (in insertion order)."""
        if self._count == 0:
            return np.zeros(0, dtype=np.int16)
        if self._head < self._tail:
            return self._buf[self._head : self._tail].copy()
        out = np.empty(self._count, dtype=np.int16)
        first = self._buf.size - self._head
        out[:first] = self._buf[self._head :]
        out[first:] = self._buf[: self._tail]
        return out

    # ---- accept (input ports) --------------------------------------------

    def accept_id(self, tid: int) -> bool:
        if self.kind is not PortKind.INPUT:
            return False
        if tid == EMPTY_ID:
            return False
        if self.filter is not None and tid != self.filter.type_id:
            return False
        if self._count >= self.capacity:
            return False
        self._buf[self._tail] = tid
        self._tail = (self._tail + 1) % self.capacity
        self._count += 1
        return True

    # ---- peek/pop (both) --------------------------------------------------

    def has_item(self) -> bool:
        return self._count > 0

    def peek_id(self) -> int:
        if self._count == 0:
            return EMPTY_ID
        return int(self._buf[self._head])

    def pop_id(self) -> int:
        if self._count == 0:
            return EMPTY_ID
        tid = int(self._buf[self._head])
        self._buf[self._head] = EMPTY_ID
        self._head = (self._head + 1) % self.capacity
        self._count -= 1
        return tid

    # ---- push (output ports) ---------------------------------------------

    def push_id(self, tid: int) -> bool:
        if self.kind is not PortKind.OUTPUT:
            return False
        if tid == EMPTY_ID:
            return False
        if self._count >= self.capacity:
            return False
        self._buf[self._tail] = tid
        self._tail = (self._tail + 1) % self.capacity
        self._count += 1
        return True

    # ---- filter helpers (hot on assembler.can_start_craft) ---------------

    def count_of_id(self, tid: int) -> int:
        if self._count == 0:
            return 0
        return int(np.count_nonzero(self.buffer == tid))

    def count_of(self, item_type: ItemType) -> int:
        return self.count_of_id(item_type.type_id)

    def drain_of_id(self, tid: int, n: int) -> int:
        """Remove up to ``n`` items of ``tid``. Preserves order of others."""
        if n <= 0 or self._count == 0 or tid == EMPTY_ID:
            return 0
        removed = 0
        snapshot = self.buffer  # copy
        kept = snapshot.copy()
        write = 0
        for v in snapshot:
            iv = int(v)
            if iv == tid and removed < n:
                removed += 1
                continue
            kept[write] = iv
            write += 1
        # Rewrite circular buffer as a contiguous prefix.
        self._buf[:] = EMPTY_ID
        if write > 0:
            self._buf[:write] = kept[:write]
        self._head = 0
        self._tail = write % self.capacity
        self._count = write
        return removed

    def drain_of(self, item_type: ItemType, n: int) -> int:
        return self.drain_of_id(item_type.type_id, n)
