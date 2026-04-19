"""Topology builder that turns a ``Grid`` of ``ConveyorBelt`` tiles into a
``BeltChainsSoA`` ready to tick.

Chains are maximal linear sequences where each belt feeds exactly one
downstream belt and has at most one upstream belt. Junctions / merges /
splits are broken: the ambiguous belt starts a fresh chain.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import numpy as np

from ..items.item_type import EMPTY_ID
from ..world.direction import Direction
from .belt import ConveyorBelt
from .chain import SLOTS_PER_BELT, BeltChainsSoA, compute_boundary_mask

if TYPE_CHECKING:
    from ..buildings.port import Port
    from ..world.world import World


_DIR_CODES: dict[Direction, int] = {
    Direction.E: 0,
    Direction.N: 1,
    Direction.W: 2,
    Direction.S: 3,
}


def _step(pos: tuple[int, int], d: Direction) -> tuple[int, int]:
    dx, dy = d.vector
    return (pos[0] + dx, pos[1] + dy)


def _inv_step(pos: tuple[int, int], d: Direction) -> tuple[int, int]:
    dx, dy = d.opposite.vector
    return (pos[0] + dx, pos[1] + dy)


def build_chains(belts: Iterable[ConveyorBelt], world: World | None = None) -> BeltChainsSoA:
    """Build a ``BeltChainsSoA`` from an iterable of ``ConveyorBelt`` tiles.

    Passing ``world`` enables successor-port resolution (tail exits into
    building input ports).
    """
    belts_by_pos: dict[tuple[int, int], ConveyorBelt] = {b.pos: b for b in belts}
    B = len(belts_by_pos)

    if B == 0:
        return BeltChainsSoA.empty()

    # -- 1. Compute per-belt successor belt and upstream count --------------
    succ_of: dict[tuple[int, int], tuple[int, int] | None] = {}
    upstream_count: dict[tuple[int, int], int] = {pos: 0 for pos in belts_by_pos}
    for pos, belt in belts_by_pos.items():
        nxt = _step(pos, belt.direction)
        nxt_belt = belts_by_pos.get(nxt)
        if nxt_belt is None:
            succ_of[pos] = None
            continue
        # A successor is valid only if the downstream belt has no other
        # belt already feeding it from a different direction, preserving
        # the linear-chain invariant.
        # We count upstreams in a second pass, then break chains after.
        succ_of[pos] = nxt
        upstream_count[nxt] += 1

    # Break chains at merge points: if belt X has >=2 upstream belts, its
    # predecessor (whoever feeds it) still has succ set, but X itself starts
    # a new chain because its upstream-count is >= 2. When walking chains we
    # stop extending past a merge.
    merge_targets = {p for p, n in upstream_count.items() if n >= 2}

    # -- 2. Find chain heads ------------------------------------------------
    heads: list[tuple[int, int]] = []
    for pos in belts_by_pos:
        upstream_pos = _inv_step(pos, belts_by_pos[pos].direction)
        upstream_belt = belts_by_pos.get(upstream_pos)
        is_head = (
            upstream_belt is None
            or pos in merge_targets
            or succ_of.get(upstream_pos) != pos
        )
        if is_head:
            heads.append(pos)

    # -- 3. Walk chains from heads -----------------------------------------
    # Each chain collects its belts in order (head -> tail).
    chains: list[list[tuple[int, int]]] = []
    chain_of_belt_pos: dict[tuple[int, int], int] = {}
    for head in heads:
        chain: list[tuple[int, int]] = []
        cur: tuple[int, int] | None = head
        visited_positions: set[tuple[int, int]] = set()
        while cur is not None and cur not in visited_positions:
            if cur in chain_of_belt_pos:
                break  # should not happen, but defend against cycles
            visited_positions.add(cur)
            chain.append(cur)
            chain_of_belt_pos[cur] = len(chains)
            nxt = succ_of.get(cur)
            if nxt is None:
                break
            if nxt in merge_targets:
                break  # downstream belt starts its own chain
            cur = nxt
        chains.append(chain)

    # Any belt that wasn't picked up as a chain head (shouldn't happen but
    # belts in cycles would fall through): assign each orphan its own chain.
    for pos in belts_by_pos:
        if pos not in chain_of_belt_pos:
            chain_of_belt_pos[pos] = len(chains)
            chains.append([pos])

    C = len(chains)

    # -- 4. Populate per-belt and per-chain numpy arrays -------------------
    belt_pos_arr = np.zeros((B, 2), dtype=np.int32)
    belt_dir_arr = np.zeros(B, dtype=np.int8)
    belt_chain_arr = np.zeros(B, dtype=np.int32)
    belt_local_start_arr = np.zeros(B, dtype=np.int32)
    chain_offset = np.zeros(C + 1, dtype=np.int32)

    chain_lens = [len(c) * SLOTS_PER_BELT for c in chains]
    chain_offset[1:] = np.cumsum(chain_lens, dtype=np.int32)

    # Assign belt -> chain/local-start.
    belt_idx = 0
    belt_idx_of_pos: dict[tuple[int, int], int] = {}
    for k, chain in enumerate(chains):
        local = 0
        for pos in chain:
            belt = belts_by_pos[pos]
            belt_pos_arr[belt_idx] = pos
            belt_dir_arr[belt_idx] = _DIR_CODES[belt.direction]
            belt_chain_arr[belt_idx] = k
            belt_local_start_arr[belt_idx] = int(chain_offset[k]) + local
            belt_idx_of_pos[pos] = belt_idx
            local += SLOTS_PER_BELT
            belt_idx += 1

    total_slots = int(chain_offset[-1])

    # -- 5. Successor chain / port per chain --------------------------------
    chain_succ_chain = np.full(C, -1, dtype=np.int32)
    chain_succ_port = np.full(C, -1, dtype=np.int32)
    port_list: list[Port] = []
    port_index_by_id: dict[int, int] = {}

    for k, chain in enumerate(chains):
        tail_pos = chain[-1]
        tail_belt = belts_by_pos[tail_pos]
        tail_dir = tail_belt.direction
        downstream_pos = _step(tail_pos, tail_dir)
        down_belt = belts_by_pos.get(downstream_pos)
        if down_belt is not None:
            chain_succ_chain[k] = chain_of_belt_pos[downstream_pos]
            continue
        if world is not None:
            building = world.building_at(downstream_pos)
            if building is not None:
                incoming_side = tail_dir.opposite
                port = building.input_port_at(downstream_pos, incoming_side)
                if port is not None:
                    pid = id(port)
                    idx = port_index_by_id.get(pid)
                    if idx is None:
                        idx = len(port_list)
                        port_list.append(port)
                        port_index_by_id[pid] = idx
                    chain_succ_port[k] = idx

    # -- 6. Chain bounding boxes in world-tile coordinates ------------------
    chain_bbox = np.zeros((C, 4), dtype=np.int32)
    for k, chain in enumerate(chains):
        xs = [p[0] for p in chain]
        ys = [p[1] for p in chain]
        chain_bbox[k] = (min(xs), min(ys), max(xs), max(ys))

    # -- 7. Reverse topological order --------------------------------------
    topo_order = _reverse_topo_order(chain_succ_chain)

    # -- 8. Boundary mask for vectorised propagation -----------------------
    boundary_mask = compute_boundary_mask(chain_offset, total_slots)

    # -- 9. Assemble SoA ----------------------------------------------------
    slots = np.zeros(total_slots, dtype=np.int16)
    prev_slots = np.zeros(total_slots, dtype=np.int16)
    prev_offset = np.zeros(total_slots, dtype=np.int8)

    soa = BeltChainsSoA(
        slots=slots,
        prev_slots=prev_slots,
        prev_offset=prev_offset,
        chain_offset=chain_offset,
        chain_succ_chain=chain_succ_chain,
        chain_succ_port=chain_succ_port,
        chain_bbox=chain_bbox,
        topo_order=topo_order,
        boundary_mask=boundary_mask,
        belt_chain=belt_chain_arr,
        belt_local_start=belt_local_start_arr,
        belt_pos=belt_pos_arr,
        belt_dir=belt_dir_arr,
        ports=port_list if port_list else None,
    )

    # Back-reference belt tile -> soa index so belt.accept goes through SoA.
    for pos, bi in belt_idx_of_pos.items():
        belt = belts_by_pos[pos]
        belt.soa_index = bi
        belt.chain_index = int(belt_chain_arr[bi])

    return soa


def _reverse_topo_order(succ_chain: np.ndarray) -> np.ndarray:
    """Return a reverse-topological ordering of chains (leaves first).

    Cycles are broken by processing remaining nodes in ascending id. The
    result is used by ``BeltChainsSoA.tick`` to resolve tail exits with
    downstream-first coupling.
    """
    C = int(succ_chain.size)
    if C == 0:
        return np.zeros(0, dtype=np.int32)

    # Count incoming edges (in-degree from successor arrows means this
    # node has an upstream chain that points at it). We want to visit
    # leaves (no successor) first; a reverse topological order for the
    # edge "k -> succ_chain[k]" is: DFS finish order reversed.
    order: list[int] = []
    color = np.zeros(C, dtype=np.int8)  # 0 = white, 1 = gray, 2 = black

    # Iterative DFS to avoid recursion limits.
    for start in range(C):
        if color[start] != 0:
            continue
        stack: list[tuple[int, int]] = [(start, 0)]
        while stack:
            node, state = stack[-1]
            if state == 0:
                if color[node] != 0:
                    stack.pop()
                    continue
                color[node] = 1
                succ = int(succ_chain[node])
                stack[-1] = (node, 1)
                if succ >= 0 and color[succ] == 0:
                    stack.append((succ, 0))
            else:
                color[node] = 2
                order.append(node)
                stack.pop()

    # DFS finish order IS reverse-topological when edges point k -> succ;
    # processing in ``order`` therefore hits every leaf/sink first, which
    # is exactly what ``BeltChainsSoA._resolve_tail_exits`` wants.
    return np.asarray(order, dtype=np.int32)


def build_empty() -> BeltChainsSoA:
    return BeltChainsSoA.empty()


def build_benchmark(
    n_chains: int,
    belts_per_chain: int,
    fill_tid: int,
    spacing_y: int = 2,
) -> BeltChainsSoA:
    """Synthesize a pure-numpy ``BeltChainsSoA`` for the 1M-item stress
    layout without touching ``Grid``.

    Produces ``n_chains`` straight east-facing chains of ``belts_per_chain``
    belts each, all slots prefilled with ``fill_tid``. Each chain auto-sinks
    at its tail and auto-sources at its head, so items circulate at max
    work per tick.
    """
    assert n_chains > 0 and belts_per_chain > 0

    belts_per_chain_slots = belts_per_chain * SLOTS_PER_BELT
    total_slots = n_chains * belts_per_chain_slots
    B = n_chains * belts_per_chain

    chain_offset = np.arange(0, total_slots + 1, belts_per_chain_slots, dtype=np.int32)
    slots = np.full(total_slots, fill_tid, dtype=np.int16)
    prev_slots = slots.copy()
    prev_offset = np.zeros(total_slots, dtype=np.int8)

    chain_succ_chain = np.full(n_chains, -1, dtype=np.int32)
    chain_succ_port = np.full(n_chains, -1, dtype=np.int32)

    # Per-belt arrays
    belt_pos = np.zeros((B, 2), dtype=np.int32)
    belt_dir = np.zeros(B, dtype=np.int8)
    belt_chain = np.repeat(np.arange(n_chains, dtype=np.int32), belts_per_chain)
    belt_local_start = np.zeros(B, dtype=np.int32)

    idx = np.arange(B, dtype=np.int32)
    within = idx % belts_per_chain
    row = idx // belts_per_chain
    belt_pos[:, 0] = within
    belt_pos[:, 1] = row * spacing_y
    belt_local_start[:] = belt_chain * belts_per_chain_slots + within * SLOTS_PER_BELT

    chain_bbox = np.zeros((n_chains, 4), dtype=np.int32)
    chain_bbox[:, 0] = 0
    chain_bbox[:, 1] = np.arange(n_chains, dtype=np.int32) * spacing_y
    chain_bbox[:, 2] = belts_per_chain - 1
    chain_bbox[:, 3] = chain_bbox[:, 1]

    topo_order = np.arange(n_chains, dtype=np.int32)
    boundary_mask = compute_boundary_mask(chain_offset, total_slots)

    soa = BeltChainsSoA(
        slots=slots,
        prev_slots=prev_slots,
        prev_offset=prev_offset,
        chain_offset=chain_offset,
        chain_succ_chain=chain_succ_chain,
        chain_succ_port=chain_succ_port,
        chain_bbox=chain_bbox,
        topo_order=topo_order,
        boundary_mask=boundary_mask,
        belt_chain=belt_chain,
        belt_local_start=belt_local_start,
        belt_pos=belt_pos,
        belt_dir=belt_dir,
        auto_sink_chains=np.arange(n_chains, dtype=np.int32),
        auto_source_chains=np.arange(n_chains, dtype=np.int32),
        auto_source_tid=int(fill_tid) if fill_tid != EMPTY_ID else 1,
    )
    return soa


__all__ = [
    "build_benchmark",
    "build_chains",
    "build_empty",
]
