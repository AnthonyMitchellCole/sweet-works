"""Animated belt + item renderer that batches over visible chains.

Belts are drawn as a pre-rotated animated sprite (direction x frame, cached
by :class:`ScaledSpriteCache`). Items are drawn with a single vectorised
world-to-screen transform per chain, followed by one ``surface.blits``
call so the per-frame Python overhead scales with *visible* items (~2 k
at 1080p) rather than total items on the map (up to 1 M).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pygame

from ..core import config
from ..items.item_type import EMPTY_ID
from ..items.registry import ITEM_TYPE_BY_ID
from .chain import SLOTS_PER_BELT

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..belts.chain import BeltChainsSoA
    from ..world.camera import Camera


_DIR_STR = ("E", "N", "W", "S")
_DIR_VEC = np.array([[1, 0], [0, -1], [-1, 0], [0, 1]], dtype=np.float32)


def frame_index(time: float) -> int:
    return int(time * config.BELT_ANIM_HZ) % config.BELT_FRAMES


def draw_belts_batch(
    surface: pygame.Surface,
    chains: BeltChainsSoA,
    visible_belts: np.ndarray,
    camera: Camera,
    assets: AssetLoader,
    time: float,
) -> int:
    """Draw every visible belt sprite. Returns number drawn."""
    if visible_belts.size == 0:
        return 0

    tile = config.TILE
    zoom = camera.zoom
    cam_x, cam_y = camera.x, camera.y
    f = frame_index(time)

    belt_dir = chains.belt_dir[visible_belts]
    belt_pos = chains.belt_pos[visible_belts]

    sx = (belt_pos[:, 0].astype(np.float32) * tile - cam_x) * zoom
    sy = (belt_pos[:, 1].astype(np.float32) * tile - cam_y) * zoom
    sx_int = sx.astype(np.int32)
    sy_int = sy.astype(np.int32)

    # Group by direction: each group shares a sprite, so we can build a
    # blits() list once per direction.
    sprites_by_dir = {
        d: assets.belt_scaled(_DIR_STR[d], f, zoom) for d in (0, 1, 2, 3)
    }
    for d in (0, 1, 2, 3):
        mask = belt_dir == d
        if not mask.any():
            continue
        sprite = sprites_by_dir[d]
        positions = np.stack([sx_int[mask], sy_int[mask]], axis=1)
        blits = [(sprite, (int(p[0]), int(p[1]))) for p in positions]
        surface.blits(blits, doreturn=False)
    return int(visible_belts.size)


def _slot_world_centres(
    slot_indices: np.ndarray,
    chains: BeltChainsSoA,
    tile: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised world-space centre (``x``, ``y``) for each global slot idx.

    Uses the per-slot ``slot_belt_idx`` back-pointer so the caller can
    resolve *any* slot on the map (including the prior-tick source slot
    of an item that just crossed a turn or a chain handoff), not just
    those in the current chain.
    """
    belt_i = chains.slot_belt_idx[slot_indices]
    belt_start = chains.belt_local_start[belt_i]
    within = (slot_indices - belt_start).astype(np.float32)
    bpos = chains.belt_pos[belt_i]
    bdir = chains.belt_dir[belt_i]
    dir_vecs = _DIR_VEC[bdir]

    # Slot centre in tile-local space sweeps [-0.5, +0.5] along the belt's
    # direction vector for local indices 0..SLOTS_PER_BELT-1.
    t_within = (within + 0.5) / SLOTS_PER_BELT - 0.5
    cx = bpos[:, 0].astype(np.float32) * tile + tile * 0.5
    cy = bpos[:, 1].astype(np.float32) * tile + tile * 0.5

    wx = cx + t_within * tile * dir_vecs[:, 0]
    wy = cy + t_within * tile * dir_vecs[:, 1]
    return wx, wy


def draw_items_batch(
    surface: pygame.Surface,
    chains: BeltChainsSoA,
    visible_chains: np.ndarray,
    camera: Camera,
    assets: AssetLoader,
    sim_alpha: float,
) -> int:
    """Draw all items on every visible chain. Returns visible-item count.

    Interpolation strategy: every item's current slot is resolved to a
    world-space centre via ``_slot_world_centres``. If the simulation
    recorded a source slot last tick (``prev_slot_idx[i] >= 0``) we also
    resolve that position and lerp between them. This renders straight
    belt propagation as a constant-velocity slide *and* direction-change
    turns as a smooth diagonal through the corner tile, instead of
    teleporting onto the new belt's starting slot.
    """
    if visible_chains.size == 0 or chains.total_slots == 0:
        return 0

    slots = chains.slots
    offsets = chains.chain_offset
    prev_slot_idx = chains.prev_slot_idx

    tile = config.TILE
    zoom = camera.zoom
    cam_x, cam_y = camera.x, camera.y
    a = max(0.0, min(1.0, sim_alpha))

    total_drawn = 0
    sprites_by_tid: dict[int, pygame.Surface] = {}

    for k in visible_chains:
        k = int(k)
        off0 = int(offsets[k])
        off1 = int(offsets[k + 1])
        if off1 - off0 == 0:
            continue
        ck_slots = slots[off0:off1]
        occ_mask = ck_slots != EMPTY_ID
        if not np.any(occ_mask):
            continue

        occ_local = np.flatnonzero(occ_mask)
        occ_global = occ_local + off0

        curr_wx, curr_wy = _slot_world_centres(occ_global, chains, tile)

        # Resolve per-item source positions. Slots with a recorded source
        # interpolate from the source centre; static slots (prev == -1)
        # stay at the current centre regardless of ``sim_alpha``.
        prev_g = prev_slot_idx[occ_global]
        has_prev = prev_g >= 0
        wx = curr_wx.copy()
        wy = curr_wy.copy()
        if has_prev.any():
            src_idx = prev_g[has_prev].astype(np.int64, copy=False)
            pwx, pwy = _slot_world_centres(src_idx, chains, tile)
            wx[has_prev] = pwx + (curr_wx[has_prev] - pwx) * a
            wy[has_prev] = pwy + (curr_wy[has_prev] - pwy) * a

        sx = ((wx - cam_x) * zoom).astype(np.int32)
        sy = ((wy - cam_y) * zoom).astype(np.int32)

        tids = ck_slots[occ_local]
        unique_tids = np.unique(tids)
        for tid in unique_tids:
            tid_i = int(tid)
            sprite = sprites_by_tid.get(tid_i)
            if sprite is None:
                itype = ITEM_TYPE_BY_ID[tid_i]
                if itype is None:
                    continue
                sprite = assets.item_icon_scaled(itype.id, zoom)
                sprites_by_tid[tid_i] = sprite
            half = sprite.get_width() // 2
            hh = sprite.get_height() // 2
            mask = tids == tid
            xs = sx[mask] - half
            ys = sy[mask] - hh
            blits = [(sprite, (int(xs[i]), int(ys[i]))) for i in range(xs.size)]
            surface.blits(blits, doreturn=False)
            total_drawn += int(xs.size)

    return total_drawn


__all__ = ["draw_belts_batch", "draw_items_batch", "frame_index"]
