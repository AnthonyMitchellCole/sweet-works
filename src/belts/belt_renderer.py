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


def draw_items_batch(
    surface: pygame.Surface,
    chains: BeltChainsSoA,
    visible_chains: np.ndarray,
    camera: Camera,
    assets: AssetLoader,
    sim_alpha: float,
) -> int:
    """Draw all items on every visible chain. Returns visible-item count."""
    if visible_chains.size == 0 or chains.total_slots == 0:
        return 0

    slots = chains.slots
    offsets = chains.chain_offset
    prev_off = chains.prev_offset

    tile = config.TILE
    zoom = camera.zoom
    cam_x, cam_y = camera.x, camera.y
    a = max(0.0, min(1.0, sim_alpha))

    total_drawn = 0

    # Pre-compute a map of item type_id -> scaled sprite (reused across chains).
    sprites_by_tid: dict[int, pygame.Surface] = {}

    for k in visible_chains:
        k = int(k)
        off0 = int(offsets[k])
        off1 = int(offsets[k + 1])
        n = off1 - off0
        if n == 0:
            continue
        ck_slots = slots[off0:off1]
        occ_mask = ck_slots != EMPTY_ID
        if not np.any(occ_mask):
            continue

        # Find which belts make up this chain.
        belt_mask = chains.belt_chain == k
        belt_positions = chains.belt_pos[belt_mask]
        belt_dirs = chains.belt_dir[belt_mask]

        # For every occupied slot we need (world_x, world_y) for the item
        # center, interpolated against the previous-tick offset.
        occ_idx = np.flatnonzero(occ_mask)
        belt_of_slot = occ_idx // SLOTS_PER_BELT
        within_belt = occ_idx % SLOTS_PER_BELT

        bpos = belt_positions[belt_of_slot]
        bdir = belt_dirs[belt_of_slot]
        dir_vecs = _DIR_VEC[bdir]

        # t_now is the position along the tile (0..1) at current tick: the
        # centre of slot i on a 4-slot belt is (i + 0.5) / 4. The previous
        # tick's position is computed from prev_offset.
        t_now = (within_belt.astype(np.float32) + 0.5) / SLOTS_PER_BELT
        prev_shift = prev_off[occ_idx + off0].astype(np.float32) / SLOTS_PER_BELT
        t_prev = t_now + prev_shift
        t = t_prev + (t_now - t_prev) * a

        # World-space center of the tile.
        cxw = bpos[:, 0].astype(np.float32) * tile + tile * 0.5
        cyw = bpos[:, 1].astype(np.float32) * tile + tile * 0.5

        # Offset along the belt direction. t - 0.5 sweeps [-0.5, +0.5]
        # and gets scaled by TILE + belt direction vector.
        offset_world = (t - 0.5).reshape(-1, 1) * tile * dir_vecs

        wx = cxw + offset_world[:, 0]
        wy = cyw + offset_world[:, 1]

        sx = ((wx - cam_x) * zoom).astype(np.int32)
        sy = ((wy - cam_y) * zoom).astype(np.int32)

        tids = ck_slots[occ_idx]

        # Blit by item type_id so each surface.blits call shares a sprite.
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
