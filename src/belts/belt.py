"""Conveyor belt tile: a 1-cell marker in one cardinal direction.

The heavy sim state (slots, items) is stored as ``int16`` arrays inside
``BeltChainsSoA``. ``ConveyorBelt`` carries only what the world grid and
placement UI need: a world position, a direction, and back-references
into the SoA populated by ``topology.build_chains``.
"""

from __future__ import annotations

from ..world.direction import Direction
from ..world.tile import Coord, Tile


class ConveyorBelt(Tile):
    SLOTS: int = 4

    def __init__(self, pos: Coord, direction: Direction) -> None:
        super().__init__(pos)
        self.direction: Direction = direction
        # Populated by ``topology.build_chains``. -1 means "not wired up yet".
        self.soa_index: int = -1
        self.chain_index: int = -1
