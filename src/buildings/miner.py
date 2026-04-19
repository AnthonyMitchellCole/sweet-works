"""Miner: produces items at a configured rate out of a single output port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..belts.belt import ConveyorBelt
from ..core import config
from ..items.item import Item
from ..items.item_type import ItemType
from ..world.direction import Direction
from ..world.tile import Coord
from .building import Building
from .port import PortKind

if TYPE_CHECKING:
    from ..world.world import World


class Miner(Building):
    name = "miner"
    footprint = (1, 1)

    def __init__(
        self,
        origin: Coord,
        item: ItemType,
        period_ticks: int = 12,
        rotation: Direction = Direction.E,
    ) -> None:
        self.item = item
        self.period_ticks = max(1, period_ticks)
        self._timer: int = 0
        super().__init__(origin, rotation)

    def _configure_ports(self) -> None:
        self._add_port(PortKind.OUTPUT, side=self.rotation, cell_offset=(0, 0))

    def tick(self, world: "World") -> None:
        self._timer += 1
        if self._timer < self.period_ticks:
            return
        out = self.outputs[0]
        item = Item(type=self.item)

        dx, dy = out.side.vector
        next_cell = (out.cell[0] + dx, out.cell[1] + dy)
        target = world.tile_at(next_cell)
        placed = False
        if isinstance(target, ConveyorBelt):
            placed = target.accept(item)
        if not placed:
            placed = out.push(item)
        if placed:
            self._timer = 0
            world.events.emit("item.produced", self.item)
