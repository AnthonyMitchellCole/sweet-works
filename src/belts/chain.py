"""Struct-of-arrays belt chain model backed by numpy.

Each ``BeltChainsSoA`` represents a set of independent belt chains. A chain
is a maximal linear sequence of conveyor-belt tiles where each belt feeds
exactly one successor. All chains share contiguous numpy arrays indexed in
CSR style by ``chain_offset``.

Tick algorithm per step, fully vectorised across all chains:

1. ``prev_slots[:] = slots``                -- snapshot for render interpolation.
2. ``can_move = (slots[:-1] != 0) & (slots[1:] == 0) & boundary_mask``;
   shift items forward by one slot in a single vectorised write.
   ``boundary_mask`` is False at every chain boundary, so items never
   cross chains during this step: each item moves at most one slot.
3. For each chain k in reverse-topological order, try to exit the tail
   into the successor chain's head (or a building input port). Doing
   this after propagation means the downstream head slot has already
   had its chance to move forward this tick, so tail exits don't
   "double-pump" an item across a chain boundary in one tick.

Correctness note: this preserves the classic "gap propagates upstream
at one slot per tick" semantics. Each item moves exactly one slot per
tick, including at chain-to-chain handoffs.

Render interpolation: ``prev_slot_idx[i]`` records the global slot index
that slot ``i`` received its item from this tick (``-1`` for static or
fresh arrivals). The renderer looks up the world-space centre of both
the source and destination slots and interpolates between them, so items
moving across belts that face different directions (turns, chain handoffs)
render as a smooth diagonal instead of a teleport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core import config
from ..items.item_type import EMPTY_ID

if TYPE_CHECKING:
    from ..buildings.port import Port


# Per-belt slot count, kept consistent with ``ConveyorBelt.SLOTS``.
SLOTS_PER_BELT: int = 4


@dataclass
class BeltChainsSoA:
    """Contiguous numpy SoA for a set of belt chains."""

    # -- hot simulation state (per slot) ------------------------------------
    slots: np.ndarray           # int16, shape (total_slots,). 0 = empty.
    prev_slots: np.ndarray      # int16, shape (total_slots,). Pre-tick snapshot.

    # Per-slot "source" for the move that produced this tick's state.
    # ``prev_slot_idx[i]`` is the global slot index that slot ``i`` received
    # its item from this tick, or ``-1`` for static / freshly sourced items.
    # Used by the renderer to interpolate both straight moves *and* turns
    # in world space (generic and direction-agnostic).
    prev_slot_idx: np.ndarray

    # -- per-chain topology -------------------------------------------------
    chain_offset: np.ndarray     # int32, shape (C + 1,)  CSR: chain k = [off[k]:off[k+1]].
    chain_succ_chain: np.ndarray  # int32, shape (C,)      downstream chain id or -1.
    chain_succ_port: np.ndarray   # int32, shape (C,)      downstream port index or -1.
    chain_bbox: np.ndarray        # int32, shape (C, 4)    world-tile x0,y0,x1,y1 for culling.
    topo_order: np.ndarray        # int32, shape (C,)      reverse-topological chain order.

    # Precomputed mask: shape (total_slots - 1,). True on edges inside a chain.
    boundary_mask: np.ndarray

    # -- per-belt metadata (for rendering) ----------------------------------
    belt_chain: np.ndarray        # int32, shape (B,)     chain id of each belt.
    belt_local_start: np.ndarray  # int32, shape (B,)     slot index where belt begins.
    belt_pos: np.ndarray          # int32, shape (B, 2)   world-tile (x, y).
    belt_dir: np.ndarray          # int8,  shape (B,)     0 = E, 1 = N, 2 = W, 3 = S.

    # Per-slot back-pointer to owning belt index. Pre-computed; enables
    # O(1) vectorised "which belt owns this slot?" lookups in the renderer.
    slot_belt_idx: np.ndarray     # int32, shape (total_slots,).

    # -- optional benchmark specials ---------------------------------------
    # When set, chains in ``auto_sink_chains`` unconditionally drain their
    # tail each tick and chains in ``auto_source_chains`` receive ``auto_source_tid``
    # at their head. Used only by the benchmark layout.
    auto_sink_chains: np.ndarray | None = None
    auto_source_chains: np.ndarray | None = None
    auto_source_tid: int = EMPTY_ID

    # -- ports (building edges) --------------------------------------------
    ports: list[Port] | None = None

    # ---- construction helpers --------------------------------------------

    @classmethod
    def empty(cls) -> BeltChainsSoA:
        zero_i16 = np.zeros(0, dtype=np.int16)
        zero_i32 = np.zeros(0, dtype=np.int32)
        zero_i8 = np.zeros(0, dtype=np.int8)
        zero_bool = np.zeros(0, dtype=bool)
        return cls(
            slots=zero_i16,
            prev_slots=zero_i16.copy(),
            prev_slot_idx=zero_i32,
            chain_offset=np.zeros(1, dtype=np.int32),
            chain_succ_chain=zero_i32,
            chain_succ_port=zero_i32,
            chain_bbox=np.zeros((0, 4), dtype=np.int32),
            topo_order=zero_i32,
            boundary_mask=zero_bool,
            belt_chain=zero_i32,
            belt_local_start=zero_i32,
            belt_pos=np.zeros((0, 2), dtype=np.int32),
            belt_dir=zero_i8,
            slot_belt_idx=zero_i32,
        )

    # ---- properties ------------------------------------------------------

    @property
    def chain_count(self) -> int:
        return int(self.chain_offset.size - 1)

    @property
    def belt_count(self) -> int:
        return int(self.belt_chain.size)

    @property
    def total_slots(self) -> int:
        return int(self.slots.size)

    def total_items(self) -> int:
        return int(np.count_nonzero(self.slots))

    # ---- sim -------------------------------------------------------------

    def tick(self) -> None:
        """Advance one simulation step across all chains (numpy vectorised)."""
        slots = self.slots
        if slots.size == 0:
            return

        # 1. Snapshot pre-tick state for the renderer. One memcpy, no alloc.
        np.copyto(self.prev_slots, slots)

        # Clear previous-tick provenance; in-chain and tail-exit steps
        # below set entries for slots that received an item this tick.
        prev_slot_idx = self.prev_slot_idx
        prev_slot_idx.fill(-1)

        # 2. Benchmark auto-sink: drain tails FIRST, so propagation can
        #    refill them this tick (keeps the stress test at steady state
        #    and guarantees the "one slot per tick" rule still holds).
        if self.auto_sink_chains is not None:
            sink_tail = self.chain_offset[self.auto_sink_chains + 1] - 1
            slots[sink_tail] = EMPTY_ID

        # 3. Vectorised propagation: any occupied slot whose downstream
        #    neighbour (inside the same chain) is empty shifts one cell
        #    forward. Boundary mask ensures items never cross chains here.
        occ = slots != EMPTY_ID
        can_move = np.empty(slots.size - 1, dtype=bool)
        # can_move[i] = occ[i] AND NOT occ[i+1] AND boundary_mask[i]
        np.logical_and(occ[:-1], ~occ[1:], out=can_move)
        np.logical_and(can_move, self.boundary_mask, out=can_move)

        src = slots[:-1][can_move]
        slots[1:][can_move] = src
        slots[:-1][can_move] = EMPTY_ID

        # Record in-chain provenance: slot i moving to i+1 means the
        # destination slot i+1 was sourced from i.
        moved_src = np.flatnonzero(can_move).astype(np.int32, copy=False)
        if moved_src.size:
            prev_slot_idx[moved_src + 1] = moved_src

        # 4. Tail exits, in reverse-topological order. Downstream chain
        #    heads have already moved this tick, so an exit here is at
        #    most a one-slot translation.
        tail_moved = self._resolve_tail_exits()
        for head, tail in tail_moved:
            prev_slot_idx[head] = tail

        # 5. Benchmark auto-source: refill empty chain heads. Runs AFTER
        #    propagation so the newly-sourced item is a fresh arrival
        #    (prev_slot_idx remains -1 for heads -> drawn statically).
        if self.auto_source_chains is not None and self.auto_source_tid != EMPTY_ID:
            src_head = self.chain_offset[self.auto_source_chains]
            empty = slots[src_head] == EMPTY_ID
            fillable = src_head[empty]
            if fillable.size:
                slots[fillable] = self.auto_source_tid

    def _resolve_tail_exits(self) -> list[tuple[int, int]]:
        """Try to drain each chain's tail slot into the next chain / port.

        Returns a list of ``(head, tail)`` slot-index pairs: the head is
        the destination slot that just received an item via a cross-chain
        handoff, and tail is its source. The caller uses this to write
        ``prev_slot_idx[head] = tail`` so the renderer can interpolate
        cross-chain handoffs (including direction-change turns) smoothly.
        """
        slots = self.slots
        offsets = self.chain_offset
        succ_chain = self.chain_succ_chain
        succ_port = self.chain_succ_port
        ports = self.ports
        moved: list[tuple[int, int]] = []

        for k in self.topo_order:
            tail = int(offsets[k + 1] - 1)
            tid = int(slots[tail])
            if tid == EMPTY_ID:
                continue
            sc = int(succ_chain[k])
            if sc >= 0:
                head = int(offsets[sc])
                if int(slots[head]) == EMPTY_ID:
                    slots[head] = tid
                    slots[tail] = EMPTY_ID
                    moved.append((head, tail))
                continue
            sp = int(succ_port[k])
            if sp >= 0 and ports is not None:
                port = ports[sp]
                if port.accept_id(tid):
                    slots[tail] = EMPTY_ID
        return moved

    # ---- accept / peek (used by world.building ticks) --------------------

    def accept_at_belt(self, belt_idx: int, tid: int) -> bool:
        """Push ``tid`` into belt ``belt_idx``'s upstream-most slot.

        Returns True if the slot was empty and now holds ``tid``.
        """
        if tid == EMPTY_ID:
            return False
        s = int(self.belt_local_start[belt_idx])
        if int(self.slots[s]) != EMPTY_ID:
            return False
        self.slots[s] = tid
        return True

    def item_at_belt(self, belt_idx: int, local_slot: int) -> int:
        s = int(self.belt_local_start[belt_idx]) + int(local_slot)
        return int(self.slots[s])

    # ---- benchmark helpers -----------------------------------------------

    def fill_all(self, tid: int) -> None:
        """Set every slot in every chain to ``tid``."""
        self.slots.fill(tid)

    def fill_chain(self, k: int, tid: int) -> None:
        s = int(self.chain_offset[k])
        e = int(self.chain_offset[k + 1])
        self.slots[s:e] = tid


def compute_boundary_mask(chain_offset: np.ndarray, total_slots: int) -> np.ndarray:
    """Return shape (total_slots-1,) bool mask: True for intra-chain edges."""
    if total_slots <= 1:
        return np.zeros(max(0, total_slots - 1), dtype=bool)
    mask = np.ones(total_slots - 1, dtype=bool)
    # Edges at index chain_offset[k+1] - 1 for k in [0, C - 2] are boundaries.
    C = chain_offset.size - 1
    if C >= 2:
        boundaries = chain_offset[1:C].astype(np.int64) - 1
        # Only touch indices inside the valid range.
        boundaries = boundaries[(boundaries >= 0) & (boundaries < mask.size)]
        mask[boundaries] = False
    return mask


__all__ = [
    "SLOTS_PER_BELT",
    "BeltChainsSoA",
    "compute_boundary_mask",
]


# Re-export config constants for quick import from this module.
_ = config
