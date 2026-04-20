"""Display-data projection of :class:`ResearchNode` + :class:`ResearchState`.

Mirrors the shape of :mod:`src.ui.info` so the research tooltip and
detail menu can be built from a single immutable snapshot. Pure
python, zero pygame imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..buildings.registry import BUILDINGS, BuildingPrefab
from ..design.palette import PALETTE
from ..items.item_type import ItemType
from ..items.registry import ITEMS
from ..ui.info import InfoRow
from .node import Effect, ModKey, ResearchNode
from .state import NodeStatus, ResearchState
from .tree import try_by_id

# -- small helpers -----------------------------------------------------------


def _prefab_by_id(prefab_id: str) -> BuildingPrefab | None:
    for p in BUILDINGS.all():
        if p.id == prefab_id:
            return p
    return None


def _item_by_id(item_id: str | None) -> ItemType | None:
    if item_id is None:
        return None
    try:
        return ITEMS.by_id(item_id)
    except KeyError:
        return None


_MOD_LABEL: dict[ModKey, str] = {
    ModKey.MINER_SPEED: "Miner speed",
    ModKey.ASSEMBLER_SPEED: "Assembler speed",
    ModKey.BELT_THROUGHPUT: "Belt throughput",
    ModKey.PORT_CAPACITY: "Port capacity",
}


def _fmt_modifier(key: ModKey, amount: float) -> str:
    if key is ModKey.PORT_CAPACITY:
        return f"+{int(round(amount))} slot" if abs(amount - 1.0) < 1e-6 else f"+{amount:g} slots"
    pct = amount * 100.0
    if abs(pct - round(pct)) < 1e-6:
        return f"+{int(round(pct))}%"
    return f"+{pct:.1f}%"


def effect_row(effect: Effect) -> InfoRow:
    """Project a single :class:`Effect` into an :class:`InfoRow`."""
    if effect.is_unlock:
        prefab = _prefab_by_id(effect.unlock_building or "")
        label = "Unlocks"
        value = prefab.name if prefab is not None else (effect.unlock_building or "?")
        return InfoRow(label=label, value=value)
    assert effect.mod_key is not None
    return InfoRow(
        label=_MOD_LABEL.get(effect.mod_key, str(effect.mod_key.value)),
        value=_fmt_modifier(effect.mod_key, effect.amount),
    )


# -- prereq row --------------------------------------------------------------


@dataclass(frozen=True)
class PrereqRow:
    """One prereq entry for the menu's prerequisites section."""

    node_id: str
    name: str
    satisfied: bool


# -- root projection --------------------------------------------------------


@dataclass(frozen=True)
class ResearchInfo:
    """Everything the research tooltip + side menu need."""

    node_id: str
    title: str
    blurb: str
    category: str
    status: NodeStatus
    accent: tuple[int, int, int]
    icon_sprite_key: str | None
    icon_item: ItemType | None
    icon_prefab: BuildingPrefab | None
    effect_rows: tuple[InfoRow, ...]
    prereq_rows: tuple[PrereqRow, ...]
    tooltip_rows: tuple[InfoRow, ...]

    @property
    def is_researched(self) -> bool:
        return self.status == "researched"

    @property
    def is_available(self) -> bool:
        return self.status == "available"

    @property
    def is_locked(self) -> bool:
        return self.status == "locked"


def _status_accent(status: NodeStatus) -> tuple[int, int, int]:
    if status == "researched":
        return PALETTE.success
    if status == "available":
        return PALETTE.primary
    return PALETTE.muted


def _status_label(status: NodeStatus) -> str:
    return {
        "researched": "Researched",
        "available": "Available",
        "locked": "Locked",
    }[status]


def for_node(node: ResearchNode, state: ResearchState) -> ResearchInfo:
    """Build a :class:`ResearchInfo` snapshot for ``node`` under ``state``."""
    status = state.status_of(node)
    accent = _status_accent(status)

    prefab = _prefab_by_id(node.icon_building_id) if node.icon_building_id else None
    icon_item = _item_by_id(node.icon_item_id)
    icon_sprite_key: str | None = None
    if prefab is not None:
        icon_sprite_key = f"{prefab.sprite_base}_idle_f0"
    elif icon_item is not None:
        icon_sprite_key = icon_item.sprite_key

    effect_rows = tuple(effect_row(e) for e in node.effects)

    prereq_rows: list[PrereqRow] = []
    for pid in node.prereqs:
        other = try_by_id(pid)
        if other is None:
            continue
        prereq_rows.append(
            PrereqRow(
                node_id=pid,
                name=other.name,
                satisfied=state.is_researched(pid),
            )
        )

    tooltip_rows: list[InfoRow] = [
        InfoRow(label="Status", value=_status_label(status)),
    ]
    tooltip_rows.extend(effect_rows)

    return ResearchInfo(
        node_id=node.id,
        title=node.name,
        blurb=node.blurb,
        category=node.category,
        status=status,
        accent=accent,
        icon_sprite_key=icon_sprite_key,
        icon_item=icon_item,
        icon_prefab=prefab,
        effect_rows=effect_rows,
        prereq_rows=tuple(prereq_rows),
        tooltip_rows=tuple(tooltip_rows),
    )


__all__ = [
    "PrereqRow",
    "ResearchInfo",
    "effect_row",
    "for_node",
]
