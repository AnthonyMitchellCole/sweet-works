"""Master catalog of every sprite key + a factory that builds it.

Generation paths (``generate_all`` / ``regenerate``) iterate this tuple
to produce exactly the sprite set the loader expects; adding a new
sprite only requires extending this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pygame

from ...core import config
from . import belts as belts_mod
from . import items as items_mod
from . import misc as misc_mod
from . import specs as specs_mod
from . import structure as structure_mod


SpriteFactory = Callable[[], pygame.Surface]


@dataclass(frozen=True)
class SpriteEntry:
    key: str
    family: str  # "floor" | "ghost" | "belt" | "item" | "structure" | "building_base"
    spec_id: str | None
    phase: str | None
    frame: int | None
    make: SpriteFactory


def structure_key(spec_id: str, phase: str, frame: int) -> str:
    return f"structure_{spec_id}_{phase}_f{frame}"


def all_entries() -> tuple[SpriteEntry, ...]:
    entries: list[SpriteEntry] = []

    entries.append(SpriteEntry("floor", "floor", None, None, None, misc_mod.floor))
    entries.append(SpriteEntry("ghost", "ghost", None, None, None, misc_mod.ghost))
    entries.append(
        SpriteEntry(
            "building_base", "building_base", None, None, None, misc_mod.building_base
        )
    )

    for frame in range(config.BELT_FRAMES):
        for direction in ("E", "N", "W", "S"):
            entries.append(
                SpriteEntry(
                    key=f"belt_{direction}_f{frame}",
                    family="belt",
                    spec_id=None,
                    phase=direction,
                    frame=frame,
                    make=_bind_belt(direction, frame),
                )
            )

    for kind in items_mod.ITEM_KINDS:
        entries.append(
            SpriteEntry(
                key=f"item_{kind}",
                family="item",
                spec_id=None,
                phase=None,
                frame=None,
                make=_bind_item(kind),
            )
        )

    for sid in sorted(specs_mod.STRUCTURE_SPECS.keys()):
        entries.append(
            SpriteEntry(
                key=structure_key(sid, "idle", 0),
                family="structure",
                spec_id=sid,
                phase="idle",
                frame=0,
                make=_bind_structure(sid, "idle", 0),
            )
        )
        for frame in range(config.STRUCTURE_FRAMES):
            entries.append(
                SpriteEntry(
                    key=structure_key(sid, "active", frame),
                    family="structure",
                    spec_id=sid,
                    phase="active",
                    frame=frame,
                    make=_bind_structure(sid, "active", frame),
                )
            )
    return tuple(entries)


def entries_for_spec(spec_id: str) -> tuple[SpriteEntry, ...]:
    return tuple(e for e in all_entries() if e.spec_id == spec_id)


def _bind_belt(direction: str, frame: int) -> SpriteFactory:
    def _make() -> pygame.Surface:
        return belts_mod.belt(direction, frame)

    return _make


def _bind_item(kind: str) -> SpriteFactory:
    def _make() -> pygame.Surface:
        return items_mod.item_icon(kind)

    return _make


def _bind_structure(sid: str, phase: str, frame: int) -> SpriteFactory:
    def _make() -> pygame.Surface:
        spec = specs_mod.STRUCTURE_SPECS[sid]
        return structure_mod.render_structure(spec, phase, frame)

    return _make


__all__ = ["SpriteEntry", "all_entries", "entries_for_spec", "structure_key"]
