"""Moves items between conveyor belts (and into building input ports)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..items.item import Item
from ..world.direction import Direction
from .belt import ConveyorBelt

if TYPE_CHECKING:
    from ..world.world import World


class BeltNetwork:
    def tick(self, world: "World") -> None:
        belts = [t for t in world.grid if isinstance(t, ConveyorBelt)]

        # Snapshot previous slot positions for render interpolation.
        for b in belts:
            for i, item in enumerate(b.slots):
                if item is not None:
                    item.prev_slot = float(i)

        visited: set[int] = set()

        def advance(b: ConveyorBelt) -> None:
            if id(b) in visited:
                return
            visited.add(id(b))

            # Advance the downstream belt first so its input slot may free.
            nxt_belt = self._next_belt(b, world)
            if nxt_belt is not None:
                advance(nxt_belt)

            # Try to push the output slot outside this belt.
            out = b.slots[-1]
            if out is not None:
                if self._try_push(b, out, world):
                    out.slot = float(b.SLOTS)  # visually exit off the end
                    b.slots[-1] = None

            # Slide remaining items forward within this belt.
            for i in range(b.SLOTS - 1, 0, -1):
                if b.slots[i] is None and b.slots[i - 1] is not None:
                    item = b.slots[i - 1]
                    b.slots[i] = item
                    b.slots[i - 1] = None
                    assert item is not None
                    item.slot = float(i)

        for b in belts:
            advance(b)

    # -- routing helpers ---------------------------------------------------

    def _next_pos(self, belt: ConveyorBelt) -> tuple[int, int]:
        dx, dy = belt.direction.vector
        return (belt.pos[0] + dx, belt.pos[1] + dy)

    def _next_belt(self, belt: ConveyorBelt, world: "World") -> ConveyorBelt | None:
        pos = self._next_pos(belt)
        tile = world.tile_at(pos)
        if isinstance(tile, ConveyorBelt):
            return tile
        return None

    def _try_push(self, belt: ConveyorBelt, item: Item, world: "World") -> bool:
        next_pos = self._next_pos(belt)
        tile = world.tile_at(next_pos)
        if isinstance(tile, ConveyorBelt):
            return tile.accept(item)
        building = world.building_at(next_pos)
        if building is not None:
            incoming_side: Direction = belt.direction.opposite
            port = building.input_port_at(next_pos, incoming_side)
            if port is not None and port.accept(item):
                return True
        return False
