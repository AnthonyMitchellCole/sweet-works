"""Vectorised view-frustum culling for the SoA belt chains."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..belts.chain import BeltChainsSoA
    from ..world.camera import Camera


def visible_chain_ids(chains: BeltChainsSoA, camera: Camera) -> np.ndarray:
    """Return int32 array of chain ids whose bounding box intersects the view."""
    C = chains.chain_count
    if C == 0:
        return np.zeros(0, dtype=np.int32)
    min_tx, min_ty, max_tx, max_ty = camera.visible_tile_rect()
    bb = chains.chain_bbox
    mask = (
        (bb[:, 0] <= max_tx)
        & (bb[:, 2] >= min_tx)
        & (bb[:, 1] <= max_ty)
        & (bb[:, 3] >= min_ty)
    )
    return np.flatnonzero(mask).astype(np.int32, copy=False)


def visible_belts_mask(chains: BeltChainsSoA, camera: Camera) -> np.ndarray:
    """Bool mask of shape (belt_count,) marking belts inside the camera view."""
    if chains.belt_count == 0:
        return np.zeros(0, dtype=bool)
    min_tx, min_ty, max_tx, max_ty = camera.visible_tile_rect()
    bp = chains.belt_pos
    return (
        (bp[:, 0] >= min_tx)
        & (bp[:, 0] <= max_tx)
        & (bp[:, 1] >= min_ty)
        & (bp[:, 1] <= max_ty)
    )


__all__ = ["visible_belts_mask", "visible_chain_ids"]
