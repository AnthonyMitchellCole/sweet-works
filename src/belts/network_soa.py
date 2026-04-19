"""Belt network: owns the SoA, drives ``tick``, exposes a thin API.

Buildings (miners, assemblers) interact with belts through ``accept``.
The scene / world layer calls ``rebuild`` whenever the belt grid changes
(placement, removal). The network lazily defers rebuilds until the next
``tick`` to avoid thrashing when multiple edits happen in the same frame.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..items.item_type import EMPTY_ID
from .belt import ConveyorBelt
from .chain import BeltChainsSoA
from .topology import build_chains, build_empty

if TYPE_CHECKING:
    from ..world.world import World


class BeltNetworkSoA:
    """Wraps a ``BeltChainsSoA`` + the dirty/rebuild lifecycle."""

    def __init__(self) -> None:
        self.soa: BeltChainsSoA = build_empty()
        self._belt_by_pos: dict[tuple[int, int], ConveyorBelt] = {}
        self._dirty: bool = False

    # ---- lifecycle -------------------------------------------------------

    def mark_dirty(self) -> None:
        self._dirty = True

    def rebuild(self, world: World | None = None) -> None:
        if world is None:
            belts = list(self._belt_by_pos.values())
        else:
            belts = [t for t in world.grid if isinstance(t, ConveyorBelt)]
            self._belt_by_pos = {b.pos: b for b in belts}
        self.soa = build_chains(belts, world)
        self._dirty = False

    def set_soa(self, soa: BeltChainsSoA) -> None:
        """Directly install a ``BeltChainsSoA`` (used by the benchmark)."""
        self.soa = soa
        self._dirty = False
        self._belt_by_pos = {}

    # ---- world integration ----------------------------------------------

    def on_tile_placed(self, tile: ConveyorBelt) -> None:
        self._belt_by_pos[tile.pos] = tile
        self.mark_dirty()

    def on_tile_removed(self, pos: tuple[int, int]) -> None:
        if pos in self._belt_by_pos:
            del self._belt_by_pos[pos]
            self.mark_dirty()

    def on_building_changed(self) -> None:
        # Port successors may change -- cheapest correct path is a rebuild
        # before the next tick.
        self.mark_dirty()

    # ---- API used by buildings ------------------------------------------

    def accept(self, pos: tuple[int, int], tid: int) -> bool:
        """Try to push ``tid`` into the belt at ``pos``'s upstream-most slot.

        Returns False if there is no belt at that cell or its first slot
        is occupied.
        """
        if self._dirty:
            # A rebuild would reset SoA state; defer accept until next tick.
            return False
        belt = self._belt_by_pos.get(pos)
        if belt is None or belt.soa_index < 0:
            return False
        return self.soa.accept_at_belt(belt.soa_index, tid)

    def peek(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        belt = self._belt_by_pos.get(pos)
        if belt is None or belt.soa_index < 0:
            return None
        return belt.chain_index, int(self.soa.belt_local_start[belt.soa_index])

    def belt_at(self, pos: tuple[int, int]) -> ConveyorBelt | None:
        return self._belt_by_pos.get(pos)

    # ---- sim -------------------------------------------------------------

    def tick(self, world: World | None = None) -> None:
        if self._dirty:
            self.rebuild(world)
        self.soa.tick()

    # ---- introspection ---------------------------------------------------

    @property
    def chain_count(self) -> int:
        return self.soa.chain_count

    def total_items(self) -> int:
        return self.soa.total_items()

    def item_count_at(self, pos: tuple[int, int]) -> int:
        belt = self._belt_by_pos.get(pos)
        if belt is None or belt.soa_index < 0:
            return 0
        s = int(self.soa.belt_local_start[belt.soa_index])
        slots = self.soa.slots[s : s + ConveyorBelt.SLOTS]
        return int((slots != EMPTY_ID).sum())
