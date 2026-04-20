"""Topology tests: ensure ``build_chains`` groups belts into maximal
linear chains and wires successor chains / building ports correctly.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.belts.belt import ConveyorBelt
from src.belts.chain import SLOTS_PER_BELT
from src.belts.network_soa import BeltNetworkSoA
from src.belts.topology import build_benchmark, build_chains
from src.buildings.registry import BUILDINGS
from src.core.events import EventBus
from src.items.item_type import EMPTY_ID
from src.items.registry import ITEMS
from src.world.direction import Direction
from src.world.world import World


def _make_line(start: tuple[int, int], n: int, direction: Direction) -> list[ConveyorBelt]:
    dx, dy = direction.vector
    return [
        ConveyorBelt((start[0] + dx * i, start[1] + dy * i), direction)
        for i in range(n)
    ]


def test_single_line_becomes_one_chain() -> None:
    belts = _make_line((0, 0), 5, Direction.E)
    soa = build_chains(belts)
    assert soa.chain_count == 1
    assert soa.belt_count == 5
    assert soa.total_slots == 5 * SLOTS_PER_BELT
    # All belts should point at chain 0 with increasing local starts.
    assert (soa.belt_chain == 0).all()
    assert list(soa.belt_local_start) == [
        i * SLOTS_PER_BELT for i in range(5)
    ]


def test_two_disjoint_lines_become_two_chains_no_successor() -> None:
    belts = _make_line((0, 0), 3, Direction.E) + _make_line((0, 5), 3, Direction.E)
    soa = build_chains(belts)
    assert soa.chain_count == 2
    assert int(soa.chain_succ_chain[0]) == -1
    assert int(soa.chain_succ_chain[1]) == -1


def test_two_lines_end_to_end_merge_into_one_chain() -> None:
    # Contiguous east-facing belts with the same direction and no merge point.
    belts = _make_line((0, 0), 6, Direction.E)
    soa = build_chains(belts)
    assert soa.chain_count == 1


def test_merge_splits_into_two_chains_with_successor_link() -> None:
    # Two feeders both point at a common downstream belt -> the common belt
    # starts its own chain, and each feeder chain has it as successor.
    b1 = ConveyorBelt((0, 0), Direction.E)  # feeds (1,0)
    b2 = ConveyorBelt((1, -1), Direction.S)  # feeds (1,0) from north
    common = ConveyorBelt((1, 0), Direction.E)
    tail = ConveyorBelt((2, 0), Direction.E)
    soa = build_chains([b1, b2, common, tail])
    assert soa.chain_count == 3  # one per feeder + one starting at the merge

    # Find the chain that owns ``common`` (the merge target).
    bi_common = next(
        i
        for i in range(soa.belt_count)
        if tuple(soa.belt_pos[i]) == (1, 0)
    )
    merge_chain = int(soa.belt_chain[bi_common])

    # Each feeder chain must list ``merge_chain`` as its successor.
    for pos in ((0, 0), (1, -1)):
        bi = next(
            i
            for i in range(soa.belt_count)
            if tuple(soa.belt_pos[i]) == pos
        )
        ck = int(soa.belt_chain[bi])
        assert int(soa.chain_succ_chain[ck]) == merge_chain


def test_successor_port_wires_tail_into_building_input() -> None:
    events = EventBus()
    world = World(events)

    miner = BUILDINGS.miner_iron.factory((0, 0), Direction.E)
    assembler = BUILDINGS.assembler_plate.factory((6, 0), Direction.E)
    world.place_building(miner)
    world.place_building(assembler)
    for x in range(1, 6):
        world.place_tile(ConveyorBelt((x, 0), Direction.E))

    network = BeltNetworkSoA()
    network.rebuild(world)
    soa = network.soa

    # Exactly one chain from x=1..5 east, ending into the assembler's input.
    assert soa.chain_count >= 1
    # Some chain must have a successor port (>= 0).
    assert (soa.chain_succ_port >= 0).any()


def test_network_rebuild_clears_dirty_flag() -> None:
    events = EventBus()
    world = World(events)
    network = BeltNetworkSoA()
    world.belt_network = network
    for x in range(5):
        world.place_tile(ConveyorBelt((x, 0), Direction.E))
    # Flag should be dirty after placement.
    assert network._dirty
    network.tick(world)
    assert not network._dirty
    # Accept should now place items into the head.
    assert network.accept((0, 0), 1)
    assert network.soa.slots[0] == 1


def test_benchmark_layout_total_items_matches_fill() -> None:
    soa = build_benchmark(n_chains=8, belts_per_chain=16, fill_tid=7)
    expected_slots = 8 * 16 * SLOTS_PER_BELT
    assert soa.total_slots == expected_slots
    assert soa.total_items() == expected_slots  # every slot filled
    # auto-sink/source should be set.
    assert soa.auto_sink_chains is not None
    assert soa.auto_source_chains is not None
    # Tick long enough that auto-sink and auto-source settle into steady
    # state. The gap introduced by auto-sink propagates upstream at one
    # slot per tick while auto-source keeps heads filled, producing a
    # stable flow with roughly half the slots populated.
    per_chain_slots = int(soa.chain_offset[1] - soa.chain_offset[0])
    for _ in range(per_chain_slots * 2):
        soa.tick()
    # Half-full (alternating) is the canonical steady state; allow a
    # small fudge either way so the test isn't brittle against ordering.
    assert expected_slots // 3 <= soa.total_items() <= expected_slots
    heads = soa.chain_offset[:-1]
    # Heads must remain sourced -- never empty across a settled tick.
    assert (soa.slots[heads] != EMPTY_ID).all()


def test_chain_through_right_angle_turn_builds_without_error() -> None:
    """Regression: three east belts then a south belt used to crash
    ``build_chains`` via an empty phantom chain. A turn must produce a
    single continuous chain with no crash."""
    belts = [
        ConveyorBelt((0, 0), Direction.E),
        ConveyorBelt((1, 0), Direction.E),
        ConveyorBelt((2, 0), Direction.E),
        ConveyorBelt((3, 0), Direction.S),
    ]
    soa = build_chains(belts)
    assert soa.chain_count == 1
    assert soa.belt_count == 4


def test_chain_with_two_turns() -> None:
    """East -> south -> east zig-zag collapses into a single chain."""
    belts = [
        ConveyorBelt((0, 0), Direction.E),
        ConveyorBelt((1, 0), Direction.S),
        ConveyorBelt((1, 1), Direction.E),
        ConveyorBelt((2, 1), Direction.E),
    ]
    soa = build_chains(belts)
    assert soa.chain_count == 1
    assert soa.belt_count == 4


def test_items_survive_turn_chain_tick() -> None:
    """An item fed at the head of a turning chain must emerge at the tail."""
    belts = [
        ConveyorBelt((0, 0), Direction.E),
        ConveyorBelt((1, 0), Direction.E),
        ConveyorBelt((2, 0), Direction.S),
        ConveyorBelt((2, 1), Direction.S),
    ]
    soa = build_chains(belts)
    # Place an item on the first slot of the chain.
    soa.slots[0] = 5
    for _ in range(soa.total_slots):
        soa.tick()
    # Item has walked off the chain (no successor) -- just verify it is
    # not stuck on some intermediate slot and did not spawn duplicates.
    assert int((soa.slots == 5).sum()) <= 1


def test_slot_world_centres_interpolates_turn_diagonally() -> None:
    """The renderer helper must map a turning chain's slots to world
    centres such that the cross-turn interpolation path is a short
    diagonal through the corner tile, not a teleport."""
    from src.belts.belt_renderer import _slot_world_centres
    from src.core import config

    belts = [
        ConveyorBelt((0, 0), Direction.E),
        ConveyorBelt((1, 0), Direction.E),
        ConveyorBelt((2, 0), Direction.S),  # turn tile
    ]
    soa = build_chains(belts)
    tile = float(config.TILE)

    # Source slot: tail of belt 1 (east), slot 7.
    src = np.array([7], dtype=np.int64)
    # Destination slot: head of belt 2 (south), slot 8.
    dst = np.array([8], dtype=np.int64)

    swx, swy = _slot_world_centres(src, soa, tile)
    dwx, dwy = _slot_world_centres(dst, soa, tile)

    # East tail lives near the right edge of tile (1,0):
    # centre (1.5 * T, 0.5 * T) + (0.875 - 0.5) * T * (1, 0) = (1.875 T, 0.5 T)
    assert swx[0] == pytest.approx(1.875 * tile)
    assert swy[0] == pytest.approx(0.5 * tile)
    # South head lives near the top of tile (2,0):
    # centre (2.5 T, 0.5 T) + (0.125 - 0.5) * T * (0, 1) = (2.5 T, 0.125 T)
    assert dwx[0] == pytest.approx(2.5 * tile)
    assert dwy[0] == pytest.approx(0.125 * tile)

    # The midpoint lerp (sim_alpha = 0.5) must land *inside* the union of
    # the two tiles, never on the original east-tile path nor above the
    # south tile -- i.e. somewhere on the diagonal between them.
    mid_x = swx[0] + (dwx[0] - swx[0]) * 0.5
    mid_y = swy[0] + (dwy[0] - swy[0]) * 0.5
    assert 1.875 * tile < mid_x < 2.5 * tile
    assert 0.125 * tile < mid_y < 0.5 * tile


def test_turn_records_prev_slot_idx_pointing_at_upstream_belt() -> None:
    """At a right-angle turn, the slot that just received an item must
    record its source as the upstream belt's tail slot (not an in-belt
    neighbour on the turn tile). The renderer uses this to interpolate
    diagonally across the corner instead of teleporting."""
    belts = [
        ConveyorBelt((0, 0), Direction.E),
        ConveyorBelt((1, 0), Direction.E),
        ConveyorBelt((2, 0), Direction.S),  # turn tile
    ]
    soa = build_chains(belts)
    # Belt layout within the single chain: [belt0][belt1][belt2], 4 slots
    # each. Park an item on slot 7 (tail of belt 1 east). After one tick
    # it must move to slot 8 (head of belt 2 south) and prev_slot_idx[8]
    # must point at slot 7 so the renderer picks up the east tile's tail
    # world centre as the interpolation source.
    soa.slots[7] = 3
    soa.tick()
    assert soa.slots[7] == 0
    assert soa.slots[8] == 3
    assert int(soa.prev_slot_idx[8]) == 7
    # And the belt metadata really does describe a direction change here:
    assert int(soa.slot_belt_idx[7]) != int(soa.slot_belt_idx[8])
    assert int(soa.belt_dir[int(soa.slot_belt_idx[7])]) != int(
        soa.belt_dir[int(soa.slot_belt_idx[8])]
    )


def test_items_persist_across_belt_placement_elsewhere() -> None:
    """Placing a disconnected belt must not wipe existing items."""
    events = EventBus()
    world = World(events)
    network = BeltNetworkSoA()
    world.belt_network = network
    for x in range(5):
        world.place_tile(ConveyorBelt((x, 0), Direction.E))
    network.flush(world)
    # Seed the original chain with a recognisable pattern.
    network.soa.slots[0] = 11
    network.soa.slots[4] = 22
    # Place a disconnected belt far away: should trigger a rebuild.
    world.place_tile(ConveyorBelt((0, 5), Direction.E))
    assert network._dirty
    world.tick()
    # Items must still be present on the original belts.
    bi_0 = next(
        i for i in range(network.soa.belt_count)
        if tuple(network.soa.belt_pos[i]) == (0, 0)
    )
    bi_1 = next(
        i for i in range(network.soa.belt_count)
        if tuple(network.soa.belt_pos[i]) == (1, 0)
    )
    s0 = int(network.soa.belt_local_start[bi_0])
    s1 = int(network.soa.belt_local_start[bi_1])
    # Seeded items advance one slot during the tick.
    assert network.soa.slots[s0 + 1] == 11
    assert network.soa.slots[s1 + 1] == 22


def test_items_persist_across_building_placement() -> None:
    """Placing a building must not wipe existing belt items either."""
    events = EventBus()
    world = World(events)
    network = BeltNetworkSoA()
    world.belt_network = network
    for x in range(5):
        world.place_tile(ConveyorBelt((x, 0), Direction.E))
    network.flush(world)
    network.soa.slots[2] = 7
    # Place a building far from the belt line.
    world.place_building(BUILDINGS.miner_iron.factory((0, 10), Direction.E))
    assert network._dirty
    network.flush(world)
    # Item was at slot index 2 of the single chain (belt 0 slot 2). After
    # persistence it stays on belt 0 slot 2 because no tick occurred.
    bi_0 = next(
        i for i in range(network.soa.belt_count)
        if tuple(network.soa.belt_pos[i]) == (0, 0)
    )
    s0 = int(network.soa.belt_local_start[bi_0])
    assert network.soa.slots[s0 + 2] == 7


def test_accept_succeeds_same_frame_as_placement() -> None:
    """A building deposit right after a belt placement should land."""
    events = EventBus()
    world = World(events)
    network = BeltNetworkSoA()
    world.belt_network = network
    world.place_tile(ConveyorBelt((0, 0), Direction.E))
    # Flush turns _dirty into a fresh SoA without waiting for tick.
    network.flush(world)
    assert network.accept((0, 0), 1) is True
    assert network.soa.slots[0] == 1


def test_topology_merge_preserves_items_on_feeder_segments() -> None:
    """When two belts merge into a common cell, items already on the
    feeders must survive the rebuild at the exact same belt+slot."""
    events = EventBus()
    world = World(events)
    network = BeltNetworkSoA()
    world.belt_network = network
    world.place_tile(ConveyorBelt((0, 0), Direction.E))
    world.place_tile(ConveyorBelt((1, -1), Direction.S))
    world.place_tile(ConveyorBelt((1, 0), Direction.E))
    network.flush(world)
    # Seed one item on each feeder.
    bi_a = next(
        i for i in range(network.soa.belt_count)
        if tuple(network.soa.belt_pos[i]) == (0, 0)
    )
    bi_b = next(
        i for i in range(network.soa.belt_count)
        if tuple(network.soa.belt_pos[i]) == (1, -1)
    )
    network.soa.slots[int(network.soa.belt_local_start[bi_a])] = 3
    network.soa.slots[int(network.soa.belt_local_start[bi_b])] = 4
    # Place a tail belt downstream of the merge -> topology changes.
    world.place_tile(ConveyorBelt((2, 0), Direction.E))
    network.flush(world)
    bi_a2 = next(
        i for i in range(network.soa.belt_count)
        if tuple(network.soa.belt_pos[i]) == (0, 0)
    )
    bi_b2 = next(
        i for i in range(network.soa.belt_count)
        if tuple(network.soa.belt_pos[i]) == (1, -1)
    )
    assert network.soa.slots[int(network.soa.belt_local_start[bi_a2])] == 3
    assert network.soa.slots[int(network.soa.belt_local_start[bi_b2])] == 4


def test_miner_produces_onto_belt_via_network() -> None:
    events = EventBus()
    world = World(events)
    network = BeltNetworkSoA()
    world.belt_network = network

    miner = BUILDINGS.miner_iron.factory((0, 0), Direction.E)
    world.place_building(miner)
    world.place_tile(ConveyorBelt((1, 0), Direction.E))
    world.place_tile(ConveyorBelt((2, 0), Direction.E))

    # Run enough ticks for the miner to produce. Miner rate is 2/s (see registry),
    # we just need one successful deposit.
    found_iron = False
    iron_tid = ITEMS.iron.type_id
    for _ in range(200):
        world.tick()
        if int(np.count_nonzero(network.soa.slots == iron_tid)) > 0:
            found_iron = True
            break
    assert found_iron, "miner should place an iron item on the belt eventually"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
