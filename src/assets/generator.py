"""Backwards-compat shim.

The sprite generator used to live in this module. It is now implemented
by :mod:`src.assets.sprites`; this module re-exports the public surface
so legacy callers (``AssetLoader.prepare``, tests, scripts) continue to
work unchanged.
"""

from __future__ import annotations

from .sprites import (  # noqa: F401
    ITEM_KINDS,
    STRUCTURE_SPECS,
    apply_overrides_from_disk,
    generate_all,
    overrides_path,
    regenerate,
    save_overrides,
    spec_for,
    structure_key,
)


__all__ = [
    "ITEM_KINDS",
    "STRUCTURE_SPECS",
    "apply_overrides_from_disk",
    "generate_all",
    "overrides_path",
    "regenerate",
    "save_overrides",
    "spec_for",
    "structure_key",
]
