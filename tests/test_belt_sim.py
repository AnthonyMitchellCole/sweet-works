"""Golden-trace tests for the vectorised belt simulator.

These assert the classic conveyor semantics on small SoAs constructed
by hand (no ``Grid`` required):

- A lone item on an empty chain advances one slot per tick.
- A gap upstream of a blocked tail propagates upstream at one slot/tick.
- A full chain with a blocked tail is completely frozen.
- The head slot accepts a push from ``accept_at_belt`` when empty.
- A chain's tail drains into a downstream chain's head every tick while
  the head is empty; it stalls when the head is occupied.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.belts.chain import SLOTS_PER_BELT, BeltChainsSoA, compute_boundary_mask
from src.items.item_type import EMPTY_ID

# ---------------------------------------------------------------------------
# helpers to assemble SoAs by hand
# ---------------------------------------------------------------------------


def _single_chain(n_belts: int) -> BeltChainsSoA:
    total = n_belts * SLOTS_PER_BELT
    chain_offset = np.array([0, total], dtype=np.int32)
    slots = np.zeros(total, dtype=np.int16)
    prev_slots = slots.copy()
    prev_slot_idx = np.full(total, -1, dtype=np.int32)

    belt_pos = np.stack(
        [np.arange(n_belts, dtype=np.int32), np.zeros(n_belts, dtype=np.int32)],
        axis=1,
    )
    belt_chain = np.zeros(n_belts, dtype=np.int32)
    belt_local_start = np.arange(0, total, SLOTS_PER_BELT, dtype=np.int32)
    belt_dir = np.zeros(n_belts, dtype=np.int8)
    slot_belt_idx = np.repeat(np.arange(n_belts, dtype=np.int32), SLOTS_PER_BELT)

    chain_bbox = np.array(
        [[0, 0, n_belts - 1, 0]], dtype=np.int32
    )
    topo_order = np.array([0], dtype=np.int32)
    boundary_mask = compute_boundary_mask(chain_offset, total)

    return BeltChainsSoA(
        slots=slots,
        prev_slots=prev_slots,
        prev_slot_idx=prev_slot_idx,
        chain_offset=chain_offset,
        chain_succ_chain=np.array([-1], dtype=np.int32),
        chain_succ_port=np.array([-1], dtype=np.int32),
        chain_bbox=chain_bbox,
        topo_order=topo_order,
        boundary_mask=boundary_mask,
        belt_chain=belt_chain,
        belt_local_start=belt_local_start,
        belt_pos=belt_pos,
        belt_dir=belt_dir,
        belt_is_turn_receiver=np.zeros(n_belts, dtype=bool),
        slot_belt_idx=slot_belt_idx,
    )


def _two_chain_handoff(n1: int, n2: int) -> BeltChainsSoA:
    """Chain 0 tail feeds chain 1 head. Chains sit in a single array."""
    t1 = n1 * SLOTS_PER_BELT
    t2 = n2 * SLOTS_PER_BELT
    total = t1 + t2
    chain_offset = np.array([0, t1, total], dtype=np.int32)
    slots = np.zeros(total, dtype=np.int16)
    prev_slots = slots.copy()
    prev_slot_idx = np.full(total, -1, dtype=np.int32)

    n_belts = n1 + n2
    belt_chain = np.concatenate(
        [np.zeros(n1, dtype=np.int32), np.ones(n2, dtype=np.int32)]
    )
    belt_local_start = np.concatenate(
        [
            np.arange(0, t1, SLOTS_PER_BELT, dtype=np.int32),
            np.arange(t1, total, SLOTS_PER_BELT, dtype=np.int32),
        ]
    )
    belt_pos = np.stack(
        [np.arange(n_belts, dtype=np.int32), np.zeros(n_belts, dtype=np.int32)],
        axis=1,
    )
    belt_dir = np.zeros(n_belts, dtype=np.int8)
    slot_belt_idx = np.repeat(np.arange(n_belts, dtype=np.int32), SLOTS_PER_BELT)
    chain_bbox = np.array(
        [[0, 0, n1 - 1, 0], [n1, 0, n1 + n2 - 1, 0]], dtype=np.int32
    )
    # Reverse topo: leaf first. Chain 0 points at chain 1, so order = [1, 0].
    topo_order = np.array([1, 0], dtype=np.int32)
    boundary_mask = compute_boundary_mask(chain_offset, total)

    return BeltChainsSoA(
        slots=slots,
        prev_slots=prev_slots,
        prev_slot_idx=prev_slot_idx,
        chain_offset=chain_offset,
        chain_succ_chain=np.array([1, -1], dtype=np.int32),
        chain_succ_port=np.array([-1, -1], dtype=np.int32),
        chain_bbox=chain_bbox,
        topo_order=topo_order,
        boundary_mask=boundary_mask,
        belt_chain=belt_chain,
        belt_local_start=belt_local_start,
        belt_pos=belt_pos,
        belt_dir=belt_dir,
        belt_is_turn_receiver=np.zeros(n_belts, dtype=bool),
        slot_belt_idx=slot_belt_idx,
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_single_item_advances_one_slot_per_tick() -> None:
    soa = _single_chain(3)  # 12 slots
    soa.slots[0] = 7
    for expected in range(1, 12):
        soa.tick()
        assert soa.slots[expected] == 7
        assert (soa.slots == 7).sum() == 1


def test_head_slot_rejected_when_occupied() -> None:
    soa = _single_chain(1)  # 4 slots
    soa.slots[0] = 5
    assert soa.accept_at_belt(0, 9) is False
    # Verify head state untouched.
    assert soa.slots[0] == 5


def test_accept_at_belt_puts_item_at_upstream_most_slot() -> None:
    soa = _single_chain(2)  # 8 slots
    assert soa.accept_at_belt(0, 3) is True
    assert soa.slots[0] == 3
    assert soa.accept_at_belt(0, 4) is False  # head still occupied
    # After a tick the head clears, accept succeeds again.
    soa.tick()
    assert soa.slots[0] == EMPTY_ID
    assert soa.accept_at_belt(0, 4) is True
    assert soa.slots[0] == 4


def test_gap_propagates_one_slot_per_tick_behind_a_stalled_tail() -> None:
    soa = _single_chain(2)  # 8 slots, tail at idx 7
    soa.slots[:] = 1  # fully packed, nothing can move
    soa.tick()
    assert (soa.slots == 1).all(), "fully packed chain must not move"

    # Create a gap at slot 3: slot 4 is still occupied, the tail is stuck.
    soa.slots[3] = EMPTY_ID
    # After one tick, slot 2 should have slid into slot 3, leaving a new gap at 2.
    soa.tick()
    assert soa.slots[3] == 1
    assert soa.slots[2] == EMPTY_ID
    # After another tick, gap moves upstream again.
    soa.tick()
    assert soa.slots[2] == 1
    assert soa.slots[1] == EMPTY_ID


def test_chain_to_chain_handoff_moves_tail_to_downstream_head() -> None:
    soa = _two_chain_handoff(1, 1)  # 4 + 4 = 8 slots
    # Place an item at chain 0's tail.
    soa.slots[3] = 9
    soa.tick()
    # Tail exit fires BEFORE propagation; the item must now be at chain 1's head.
    assert soa.slots[3] == EMPTY_ID
    assert soa.slots[4] == 9


def test_handoff_stalls_when_downstream_chain_fully_packed() -> None:
    soa = _two_chain_handoff(1, 1)  # 4 + 4 slots
    soa.slots[3] = 9
    soa.slots[4:8] = 1  # downstream chain packed, no propagation possible
    soa.tick()
    assert soa.slots[3] == 9  # chain 0 tail has nowhere to go
    assert (soa.slots[4:8] == 1).all()  # downstream stays put


def test_handoff_yields_after_downstream_propagates() -> None:
    soa = _two_chain_handoff(1, 1)
    soa.slots[3] = 9
    soa.slots[4] = 1  # downstream head has item, but slot 5..7 are empty
    soa.tick()
    # Propagation moved 4->5 this tick, freeing the head; tail exit then
    # places item from slot 3 into slot 4.
    assert soa.slots[3] == EMPTY_ID
    assert soa.slots[4] == 9
    assert soa.slots[5] == 1


def test_prev_slots_snapshot_matches_pre_tick_state() -> None:
    soa = _single_chain(3)
    soa.slots[0] = 7
    snapshot = soa.slots.copy()
    soa.tick()
    # After the tick, prev_slots should still reflect the pre-tick state.
    assert np.array_equal(soa.prev_slots, snapshot)


def test_prev_slot_idx_marks_source_slot_after_propagation() -> None:
    soa = _single_chain(2)  # 8 slots
    soa.slots[0] = 2
    soa.tick()
    # Slot 1 was filled by slot 0, so its source index is 0. Slot 0 now
    # holds nothing (got moved), and nothing moved INTO slot 0, so -1.
    assert soa.prev_slot_idx[1] == 0
    assert soa.prev_slot_idx[0] == -1


def test_prev_slot_idx_marks_cross_chain_handoff_source() -> None:
    soa = _two_chain_handoff(2, 2)
    # Chain 0 tail (slot 7) has item 1; chain 1 is empty so the head
    # (slot 8) must receive via the tail-exit path, recording 7 as source.
    soa.slots[7] = 1
    soa.tick()
    assert soa.slots[8] == 1
    assert soa.prev_slot_idx[8] == 7


def test_total_items_counts_only_nonempty_slots() -> None:
    soa = _single_chain(3)
    assert soa.total_items() == 0
    soa.slots[[0, 3, 7, 11]] = 1
    assert soa.total_items() == 4
    soa.tick()
    assert soa.total_items() == 4, "propagation preserves item count"


def test_reverse_topo_order_keeps_tail_exits_downstream_first() -> None:
    soa = _two_chain_handoff(2, 2)
    # Chain 0 tail (slot 7) has item 1; chain 1 is empty.
    soa.slots[7] = 1
    soa.tick()
    # Chain 1 must have received it at its head (slot 8), not kept it in chain 0.
    assert soa.slots[7] == EMPTY_ID
    assert soa.slots[8] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
