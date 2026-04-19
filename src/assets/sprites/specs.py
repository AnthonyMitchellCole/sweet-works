"""Declarative structure specs consumed by :mod:`structure`.

A :class:`StructureSpec` is a flat description of how to compose one
structure sprite (chassis + accent + badge + lights + state overlay).
The spec registry is mutable at runtime so the Sprite Studio overlay and
``overrides.json`` can tweak it without editing source.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any

from ...design.palette import PALETTE, Color
from ...items.registry import ITEMS


# Pictogram vocabulary understood by ``structure.render_structure``.
PICTOGRAMS: tuple[str, ...] = ("ore_chunks", "coal_lumps", "plate_stack", "pinion")
OVERLAY_KINDS: tuple[str, ...] = ("none", "drill", "glow")
SIDES: tuple[str, ...] = ("N", "E", "S", "W")


@dataclass(frozen=True)
class ChassisSpec:
    plate: Color = PALETTE.bg_raised
    bolts: int = 4
    inset_px_at_64: int = 6
    top_highlight: bool = True


@dataclass(frozen=True)
class AccentStripeSpec:
    color: Color = PALETTE.primary
    side: str = "N"
    thickness: int = 2


@dataclass(frozen=True)
class BadgeSpec:
    pictogram: str = "ore_chunks"
    size_at_64: int = 20
    tint: Color = PALETTE.muted


@dataclass(frozen=True)
class LightSpec:
    color: Color = PALETTE.secondary
    pattern: tuple[int, ...] = (1, 1, 0, 0, 1, 0)
    count: int = 2


@dataclass(frozen=True)
class OverlaySpec:
    kind: str = "none"
    size_at_64: int = 18


@dataclass(frozen=True)
class StructureSpec:
    id: str
    footprint: tuple[int, int]
    chassis: ChassisSpec
    accent: AccentStripeSpec
    badge: BadgeSpec
    lights: LightSpec
    overlay: OverlaySpec = OverlaySpec()


# ---------------------------------------------------------------------------
# Default spec set — seeded from the item registry so colours stay in sync.
# ---------------------------------------------------------------------------


def _iron() -> StructureSpec:
    c = ITEMS.iron.color
    return StructureSpec(
        id="miner_iron",
        footprint=(1, 1),
        chassis=ChassisSpec(),
        accent=AccentStripeSpec(color=c, side="N", thickness=2),
        badge=BadgeSpec(pictogram="ore_chunks", tint=c, size_at_64=22),
        lights=LightSpec(color=c, pattern=(1, 1, 0, 1, 0, 0), count=2),
        overlay=OverlaySpec(kind="drill", size_at_64=18),
    )


def _copper() -> StructureSpec:
    c = ITEMS.copper.color
    return StructureSpec(
        id="miner_copper",
        footprint=(1, 1),
        chassis=ChassisSpec(),
        accent=AccentStripeSpec(color=c, side="N", thickness=2),
        badge=BadgeSpec(pictogram="ore_chunks", tint=c, size_at_64=22),
        lights=LightSpec(color=c, pattern=(1, 0, 1, 0, 1, 0), count=2),
        overlay=OverlaySpec(kind="drill", size_at_64=18),
    )


def _coal() -> StructureSpec:
    c = ITEMS.coal.color
    accent = PALETTE.warning
    return StructureSpec(
        id="miner_coal",
        footprint=(1, 1),
        chassis=ChassisSpec(),
        accent=AccentStripeSpec(color=accent, side="N", thickness=2),
        badge=BadgeSpec(pictogram="coal_lumps", tint=c, size_at_64=22),
        lights=LightSpec(color=accent, pattern=(1, 0, 0, 1, 0, 0), count=2),
        overlay=OverlaySpec(kind="drill", size_at_64=18),
    )


def _plate() -> StructureSpec:
    c = ITEMS.plate.color
    return StructureSpec(
        id="assembler_plate",
        footprint=(2, 2),
        chassis=ChassisSpec(bolts=8),
        accent=AccentStripeSpec(color=c, side="N", thickness=2),
        badge=BadgeSpec(pictogram="plate_stack", tint=c, size_at_64=28),
        lights=LightSpec(color=PALETTE.secondary, pattern=(1, 0, 0, 0, 1, 1), count=3),
        overlay=OverlaySpec(kind="glow", size_at_64=44),
    )


def _gear() -> StructureSpec:
    c = ITEMS.gear.color
    return StructureSpec(
        id="assembler_gear",
        footprint=(2, 2),
        chassis=ChassisSpec(bolts=8),
        accent=AccentStripeSpec(color=c, side="N", thickness=2),
        badge=BadgeSpec(pictogram="pinion", tint=c, size_at_64=30),
        lights=LightSpec(color=PALETTE.warning, pattern=(1, 1, 0, 1, 0, 1), count=3),
        overlay=OverlaySpec(kind="glow", size_at_64=48),
    )


def _default_specs() -> dict[str, StructureSpec]:
    return {s.id: s for s in (_iron(), _copper(), _coal(), _plate(), _gear())}


STRUCTURE_SPECS: dict[str, StructureSpec] = _default_specs()


# ---------------------------------------------------------------------------
# Overrides + mutation
# ---------------------------------------------------------------------------


def reset_to_defaults() -> None:
    STRUCTURE_SPECS.clear()
    STRUCTURE_SPECS.update(_default_specs())


def snapshot() -> dict[str, StructureSpec]:
    """Deep copy of the current specs dict (safe for edit-and-discard workflows)."""
    return copy.deepcopy(STRUCTURE_SPECS)


def set_spec(spec_id: str, spec: StructureSpec) -> None:
    STRUCTURE_SPECS[spec_id] = spec


def apply_overrides(overrides: dict[str, Any]) -> None:
    """Merge a structured override dict into :data:`STRUCTURE_SPECS`.

    Schema::

        {
            "miner_iron": {
                "accent": {"side": "E", "thickness": 3},
                "lights": {"pattern": [1, 1, 0]},
                "badge":  {"size_at_64": 22},
                "overlay": {"kind": "glow"}
            }
        }

    Missing keys are inherited from the defaults; unknown structures are
    silently ignored (future-compatible overrides).
    """
    for sid, ov in overrides.items():
        if not isinstance(ov, dict):
            continue
        base = STRUCTURE_SPECS.get(sid)
        if base is None:
            continue
        STRUCTURE_SPECS[sid] = _merge(base, ov)


def _merge(base: StructureSpec, ov: dict[str, Any]) -> StructureSpec:
    parts: dict[str, Any] = {}
    if "footprint" in ov:
        fp = ov["footprint"]
        if isinstance(fp, (list, tuple)) and len(fp) == 2:
            parts["footprint"] = (int(fp[0]), int(fp[1]))
    if "chassis" in ov and isinstance(ov["chassis"], dict):
        parts["chassis"] = replace(base.chassis, **_coerce(ov["chassis"], base.chassis))
    if "accent" in ov and isinstance(ov["accent"], dict):
        parts["accent"] = replace(base.accent, **_coerce(ov["accent"], base.accent))
    if "badge" in ov and isinstance(ov["badge"], dict):
        parts["badge"] = replace(base.badge, **_coerce(ov["badge"], base.badge))
    if "lights" in ov and isinstance(ov["lights"], dict):
        parts["lights"] = replace(base.lights, **_coerce(ov["lights"], base.lights))
    if "overlay" in ov and isinstance(ov["overlay"], dict):
        parts["overlay"] = replace(base.overlay, **_coerce(ov["overlay"], base.overlay))
    return replace(base, **parts)


def _coerce(raw: dict[str, Any], target: Any) -> dict[str, Any]:
    """Coerce JSON values back into frozen-dataclass-friendly types."""
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if not hasattr(target, k):
            continue
        cur = getattr(target, k)
        if isinstance(cur, tuple) and isinstance(v, list):
            out[k] = tuple(v)
        else:
            out[k] = v
    return out


def to_override_dict() -> dict[str, Any]:
    """Dump the live specs as a JSON-friendly override blob."""
    data: dict[str, Any] = {}
    defaults = _default_specs()
    for sid, spec in STRUCTURE_SPECS.items():
        default = defaults.get(sid)
        if default is None:
            continue
        diff: dict[str, Any] = {}
        for part in ("chassis", "accent", "badge", "lights", "overlay"):
            dcur = getattr(spec, part)
            ddef = getattr(default, part)
            if dcur != ddef:
                diff[part] = _part_to_dict(dcur)
        if spec.footprint != default.footprint:
            diff["footprint"] = list(spec.footprint)
        if diff:
            data[sid] = diff
    return data


def _part_to_dict(part: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field_name in part.__dataclass_fields__:
        value = getattr(part, field_name)
        if isinstance(value, tuple):
            out[field_name] = list(value)
        else:
            out[field_name] = value
    return out


__all__ = [
    "ChassisSpec",
    "AccentStripeSpec",
    "BadgeSpec",
    "LightSpec",
    "OverlaySpec",
    "StructureSpec",
    "STRUCTURE_SPECS",
    "PICTOGRAMS",
    "OVERLAY_KINDS",
    "SIDES",
    "reset_to_defaults",
    "snapshot",
    "set_spec",
    "apply_overrides",
    "to_override_dict",
]
