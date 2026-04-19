"""Belt network: owns the SoA, drives ``tick``, exposes a thin API.

Buildings (miners, assemblers) interact with belts through ``accept``.
World edits (placements, removals, building changes) call ``mark_dirty``
and the network lazily rebuilds its ``BeltChainsSoA`` between ticks via
``flush`` so multiple same-frame edits coalesce into a single rebuild.

Item persistence: every rebuild snapshots the per-belt slot arrays keyed
by world position, then restores them onto the freshly built SoA. Edits
therefore never drop items that were already on a belt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ..items.item_type import EMPTY_ID
from .belt import ConveyorBelt
from .chain import SLOTS_PER_BELT, BeltChainsSoA
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

    def flush(self, world: World | None = None) -> None:
        """Rebuild if dirty. Idempotent and safe to call every tick.

        Call this before the building phase of a sim step so deposits can
        land on the just-placed network in the same frame.
        """
        if self._dirty:
            self.rebuild(world)

    def rebuild(self, world: World | None = None) -> None:
        """Rebuild the SoA, preserving items on belts that survive the edit.

        Items are keyed by belt world position and the per-belt slot index
        (each belt owns ``SLOTS_PER_BELT`` contiguous slots in both the old
        and new SoA), so an item on belt ``(x, y)`` slot 2 before the edit
        lands on the same belt+slot after the edit — regardless of how the
        chain topology reorganised around it.
        """
        snapshot = self._snapshot_items()

        if world is None:
            belts = list(self._belt_by_pos.values())
        else:
            belts = [t for t in world.grid if isinstance(t, ConveyorBelt)]
            self._belt_by_pos = {b.pos: b for b in belts}

        self.soa = build_chains(belts, world)
        self._restore_items(snapshot)
        self._dirty = False

    def set_soa(self, soa: BeltChainsSoA) -> None:
        """Directly install a ``BeltChainsSoA`` (used by the benchmark)."""
        self.soa = soa
        self._dirty = False
        self._belt_by_pos = {}

    # ---- persistence helpers --------------------------------------------

    def _snapshot_items(self) -> dict[tuple[int, int], np.ndarray]:
        """Return ``{belt_pos -> ndarray(SLOTS_PER_BELT,)}`` of current items."""
        soa = self.soa
        if soa.belt_count == 0:
            return {}
        snap: dict[tuple[int, int], np.ndarray] = {}
        for pos, belt in self._belt_by_pos.items():
            if belt.soa_index < 0:
                continue
            s = int(soa.belt_local_start[belt.soa_index])
            snap[pos] = soa.slots[s : s + SLOTS_PER_BELT].copy()
        return snap

    def _restore_items(self, snapshot: dict[tuple[int, int], np.ndarray]) -> None:
        """Write snapshotted slots back onto freshly built belts at the same pos."""
        if not snapshot:
            return
        soa = self.soa
        for pos, belt in self._belt_by_pos.items():
            saved = snapshot.get(pos)
            if saved is None or belt.soa_index < 0:
                continue
            s = int(soa.belt_local_start[belt.soa_index])
            soa.slots[s : s + SLOTS_PER_BELT] = saved
        # Fresh tick starts with a stable snapshot (no phantom interpolation
        # from a now-defunct previous layout).
        np.copyto(soa.prev_slots, soa.slots)
        soa.prev_offset.fill(0)

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
        is occupied. Rebuilds preserve item state, so buildings may always
        call this without worrying about the dirty flag.
        """
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
        # Safety net: if the scene hasn't called ``flush`` yet, do it here
        # so a dirty network never ticks with stale indices.
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
