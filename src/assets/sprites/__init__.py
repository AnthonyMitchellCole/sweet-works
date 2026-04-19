"""Public sprite-generation API.

Replaces the old monolithic ``assets.generator`` with a declarative
registry. :func:`generate_all` iterates the catalog and writes every
entry to the tile/item-sized disk cache; :func:`regenerate` does the
same for a subset of keys; :func:`apply_overrides_from_disk` merges the
optional ``assets/sprites/overrides.json`` blob into the live spec
registry.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

import pygame

from .. import paths
from . import belts as belts_mod
from . import catalog as catalog_mod
from . import items as items_mod
from . import misc as misc_mod
from . import specs as specs_mod
from . import structure as structure_mod
from .catalog import SpriteEntry, all_entries, entries_for_spec, structure_key
from .specs import (
    STRUCTURE_SPECS,
    StructureSpec,
    apply_overrides,
    reset_to_defaults,
    set_spec,
    snapshot,
    to_override_dict,
)


__all__ = [
    "ITEM_KINDS",
    "OVERRIDES_FILENAME",
    "STRUCTURE_SPECS",
    "SpriteEntry",
    "StructureSpec",
    "all_entries",
    "apply_overrides",
    "apply_overrides_from_disk",
    "entries_for_spec",
    "generate_all",
    "overrides_path",
    "regenerate",
    "reset_to_defaults",
    "save_overrides",
    "set_spec",
    "snapshot",
    "spec_for",
    "structure_key",
    "to_override_dict",
    "belts_mod",
    "items_mod",
    "misc_mod",
    "structure_mod",
]


ITEM_KINDS = items_mod.ITEM_KINDS
OVERRIDES_FILENAME = "overrides.json"


def overrides_path():
    return paths.SPRITES_DIR / OVERRIDES_FILENAME


def apply_overrides_from_disk() -> None:
    """Merge user overrides from ``assets/sprites/overrides.json`` (if any)."""
    p = overrides_path()
    if not p.exists():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    structures = raw.get("structures") if isinstance(raw, dict) else None
    if isinstance(structures, dict):
        apply_overrides(structures)


def save_overrides() -> None:
    """Dump the current live specs (as a diff against defaults) to disk."""
    p = overrides_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"structures": to_override_dict()}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def spec_for(spec_id: str) -> StructureSpec | None:
    return STRUCTURE_SPECS.get(spec_id)


def generate_all(force: bool = False) -> None:
    """Write every sprite in the catalog to the current tile/item-sized cache."""
    paths.ensure_dirs()
    apply_overrides_from_disk()
    out_dir = paths.sprites_dir()
    for entry in all_entries():
        path = out_dir / f"{entry.key}.png"
        if force or not path.exists():
            surf = entry.make()
            pygame.image.save(surf, str(path))


def regenerate(keys: Iterable[str] | None = None) -> list[str]:
    """Regenerate a subset (or all when ``keys is None``) and return the keys written."""
    paths.ensure_dirs()
    out_dir = paths.sprites_dir()
    selected: set[str] | None = None if keys is None else {str(k) for k in keys}
    written: list[str] = []
    for entry in all_entries():
        if selected is not None and entry.key not in selected:
            continue
        surf = entry.make()
        pygame.image.save(surf, str(out_dir / f"{entry.key}.png"))
        written.append(entry.key)
    return written
