"""Mutable per-session research progress.

Lives on the :class:`~src.world.world.World` so both the sim layer
(miners, assemblers, ports) and the UI layer (toolbar, tooltip,
menu) can query the same snapshot. Every successful call to
:meth:`ResearchState.research` emits ``research.changed`` on the
provided :class:`~src.core.events.EventBus` so subscribers can
re-derive their presentation without polling.

The modifier math is deliberately tiny:

* ``*_SPEED`` and ``*_THROUGHPUT`` keys are **multiplicative** -- each
  effect contributes a ``(1 + amount)`` factor; the default return is
  ``1.0`` so "no research" is neutral.
* :attr:`~src.research.node.ModKey.PORT_CAPACITY` is **additive** --
  each effect contributes ``amount`` slots; default is ``0``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .node import Effect, ModKey, ResearchNode
from .tree import RESEARCH, STARTING_UNLOCKS, by_id, try_by_id

if TYPE_CHECKING:
    from ..core.events import EventBus


NodeStatus = Literal["researched", "available", "locked"]


class ResearchState:
    """Tracks which nodes are researched and derives unlocks / modifiers."""

    def __init__(self, events: EventBus | None = None) -> None:
        self._events = events
        self.researched: set[str] = set()

    # -- queries -----------------------------------------------------------

    def is_researched(self, node_id: str) -> bool:
        return node_id in self.researched

    def can_research(self, node: ResearchNode | str) -> bool:
        """True iff ``node`` is not yet researched and all prereqs are."""
        if isinstance(node, str):
            resolved = try_by_id(node)
            if resolved is None:
                return False
            node = resolved
        if node.id in self.researched:
            return False
        return all(p in self.researched for p in node.prereqs)

    def status_of(self, node: ResearchNode | str) -> NodeStatus:
        if isinstance(node, str):
            node = by_id(node)
        if node.id in self.researched:
            return "researched"
        if all(p in self.researched for p in node.prereqs):
            return "available"
        return "locked"

    # -- toolbar gating ----------------------------------------------------

    def is_unlocked(self, prefab_id: str) -> bool:
        """True iff the given building/tool prefab is usable right now."""
        if prefab_id in STARTING_UNLOCKS:
            return True
        for node in RESEARCH:
            if node.id not in self.researched:
                continue
            for eff in node.effects:
                if eff.unlock_building == prefab_id:
                    return True
        return False

    def unlocked_buildings(self) -> frozenset[str]:
        out: set[str] = set(STARTING_UNLOCKS)
        for node in RESEARCH:
            if node.id not in self.researched:
                continue
            for eff in node.effects:
                if eff.unlock_building is not None:
                    out.add(eff.unlock_building)
        return frozenset(out)

    def research_node_unlocking(self, prefab_id: str) -> ResearchNode | None:
        """Return the node whose effects unlock ``prefab_id``, if any."""
        if prefab_id in STARTING_UNLOCKS:
            return None
        for node in RESEARCH:
            for eff in node.effects:
                if eff.unlock_building == prefab_id:
                    return node
        return None

    # -- modifier math -----------------------------------------------------

    def modifier(self, key: ModKey, default: float | None = None) -> float:
        """Resolve a modifier value across all researched nodes.

        * Multiplicative keys return a scalar ≥ 1.0 (default ``1.0``).
        * :attr:`ModKey.PORT_CAPACITY` returns the additive bonus
          (default ``0.0``).
        """
        if key is ModKey.PORT_CAPACITY:
            fallback = 0.0 if default is None else float(default)
            total = fallback
            for node in RESEARCH:
                if node.id not in self.researched:
                    continue
                for eff in node.effects:
                    if eff.mod_key is key:
                        total += float(eff.amount)
            return total

        # Multiplicative: chain (1 + amount) factors.
        fallback = 1.0 if default is None else float(default)
        factor = fallback
        for node in RESEARCH:
            if node.id not in self.researched:
                continue
            for eff in node.effects:
                if eff.mod_key is key:
                    factor *= 1.0 + float(eff.amount)
        return factor

    # -- mutation ----------------------------------------------------------

    def research(self, node: ResearchNode | str) -> bool:
        """Mark ``node`` researched if prereqs are met.

        Returns ``True`` on a successful *new* research (and emits
        ``research.changed``); ``False`` if the node is already
        researched, unknown, or still locked.
        """
        if isinstance(node, str):
            resolved = try_by_id(node)
            if resolved is None:
                return False
            node = resolved
        if node.id in self.researched:
            return False
        if not all(p in self.researched for p in node.prereqs):
            return False
        self.researched.add(node.id)
        if self._events is not None:
            self._events.emit("research.changed", node_id=node.id, state=self)
        return True

    def reset(self) -> None:
        """Drop all progress (used by tests + new-game flow)."""
        had_any = bool(self.researched)
        self.researched.clear()
        if had_any and self._events is not None:
            self._events.emit("research.changed", node_id=None, state=self)

    # -- helpers for UI projection ----------------------------------------

    def collect_effects(self, node: ResearchNode) -> tuple[Effect, ...]:
        return node.effects


__all__ = ["NodeStatus", "ResearchState"]
