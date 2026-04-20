"""Research node + effect data model.

A :class:`ResearchNode` is a single, immutable cell in the research
tree: an id, a short blurb, a board-grid position, optional prereq
ids, and a tuple of :class:`Effect` payloads that are realised by
:class:`~src.research.state.ResearchState` when the node is
researched. Effects come in two flavours so the same dataclass can
represent both building-unlock gates (``unlock_building``) and
numerical buffs (``mod_key`` + ``amount``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModKey(Enum):
    """Numerical modifier channels applied by researched effects."""

    MINER_SPEED = "miner_speed"              # multiplicative on tick-rate
    ASSEMBLER_SPEED = "assembler_speed"      # multiplicative on craft duration
    BELT_THROUGHPUT = "belt_throughput"      # multiplicative
    PORT_CAPACITY = "port_capacity"          # additive (integer items)


@dataclass(frozen=True)
class Effect:
    """A single payload applied when a node's parent is researched.

    Exactly one of :attr:`unlock_building` or :attr:`mod_key` is set.
    ``amount`` is interpreted as a multiplier fraction for
    ``*_SPEED`` / ``*_THROUGHPUT`` keys (``0.15`` → ``+15%``) and as
    a raw additive count for :attr:`ModKey.PORT_CAPACITY`
    (``1.0`` → ``+1`` slot).
    """

    unlock_building: str | None = None
    mod_key: ModKey | None = None
    amount: float = 0.0

    @staticmethod
    def unlock(building_id: str) -> Effect:
        return Effect(unlock_building=building_id)

    @staticmethod
    def modifier(key: ModKey, amount: float) -> Effect:
        return Effect(mod_key=key, amount=float(amount))

    @property
    def is_unlock(self) -> bool:
        return self.unlock_building is not None

    @property
    def is_modifier(self) -> bool:
        return self.mod_key is not None


@dataclass(frozen=True)
class ResearchNode:
    """An immutable node on the research board.

    The :attr:`grid_pos` is authored in abstract grid units; the scene
    multiplies it by ``NODE_STRIDE_*`` to derive pixel coordinates on
    the virtual research board.
    """

    id: str
    name: str
    blurb: str
    category: str
    grid_pos: tuple[int, int]
    prereqs: tuple[str, ...] = ()
    effects: tuple[Effect, ...] = ()
    icon_item_id: str | None = None
    icon_building_id: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


__all__ = ["Effect", "ModKey", "ResearchNode"]
