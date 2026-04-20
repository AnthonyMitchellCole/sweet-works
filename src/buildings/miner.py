"""Miner: produces items at a configured rate out of a single output port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..items.item_type import ItemType
from ..research.node import ModKey
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
        *,
        mirrored: bool = False,
        sprite_base: str | None = None,
    ) -> None:
        self.item = item
        self.period_ticks = max(1, period_ticks)
        self._timer: int = 0
        # Cached effective period; recomputed from ``world.research`` each tick
        # so anim_progress (called from render, which has no world ref) can
        # read a consistent snapshot.
        self._effective_period: int = self.period_ticks
        super().__init__(
            origin, rotation, mirrored=mirrored, sprite_base=sprite_base
        )

    # -- research-aware effective rate ------------------------------------

    def effective_period_ticks(self, world: World | None = None) -> int:
        """Return the period scaled by the ``MINER_SPEED`` research modifier."""
        if world is not None and world.research is not None:
            speed = max(1e-6, world.research.modifier(ModKey.MINER_SPEED, 1.0))
            return max(1, int(round(self.period_ticks / speed)))
        return self.period_ticks

    def _configure_ports(self) -> None:
        # Canonical frame: miner faces east; mirror/rotation are
        # resolved by the framework.
        self._add_local_port(
            PortKind.OUTPUT, side_local=Direction.E, cell_offset_local=(0, 0)
        )

    # -- animation state hooks --------------------------------------------

    def is_active(self) -> bool:
        return self._timer > 0

    def anim_progress(self) -> float:
        return min(1.0, self._timer / max(1, self._effective_period))

    def tick(self, world: World) -> None:
        self._effective_period = self.effective_period_ticks(world)
        self._timer += 1
        if self._timer < self._effective_period:
            return
        out = self.outputs[0]
        tid = self.item.type_id

        dx, dy = out.side.vector
        next_cell = (out.cell[0] + dx, out.cell[1] + dy)
        placed = False
        network = world.belt_network
        if network is not None:
            placed = network.accept(next_cell, tid)
        if not placed:
            placed = out.push_id(tid)
        if placed:
            self._timer = 0
            world.events.emit("item.produced", self.item)
