"""Tests for :mod:`src.research.state`.

Covers the core state transitions and derived views the rest of the
game leans on:

* ``status_of`` rolls between ``"locked" -> "available" -> "researched"``
  as prereqs are satisfied.
* ``research`` only succeeds when all prereqs are met and then emits
  the ``research.changed`` event exactly once with the researched id.
* ``is_unlocked`` falls back to :data:`~src.research.tree.STARTING_UNLOCKS`
  and grows as unlock nodes are completed.
* Multiplicative modifier effects compound ``(1 + amount)`` factors.
* The additive :attr:`~src.research.node.ModKey.PORT_CAPACITY` modifier
  sums plainly.
* ``reset`` clears progress and (if it had any) emits the change event.
"""

from __future__ import annotations

from collections.abc import Callable

from src.core.events import EventBus
from src.research.node import ModKey
from src.research.state import ResearchState
from src.research.tree import (
    RESEARCH,
    STARTING_UNLOCKS,
    by_id,
)


def _event_recorder(bus: EventBus) -> tuple[list[dict[str, object]], Callable[[], None]]:
    """Capture every ``research.changed`` payload for easy assertions."""
    calls: list[dict[str, object]] = []

    def _on(**payload: object) -> None:
        calls.append(payload)

    off = bus.on("research.changed", _on)
    return calls, off


# -- status transitions ----------------------------------------------------


def test_status_of_starts_at_roots_available_others_locked() -> None:
    state = ResearchState()
    root_statuses = {n.id: state.status_of(n) for n in RESEARCH if not n.prereqs}
    locked_statuses = {
        n.id: state.status_of(n) for n in RESEARCH if n.prereqs
    }
    assert all(s == "available" for s in root_statuses.values())
    assert all(s == "locked" for s in locked_statuses.values())


def test_status_transitions_through_research() -> None:
    state = ResearchState()

    assert state.status_of("sugar_harvest") == "available"
    assert state.status_of("refined_mixing") == "locked"

    assert state.research("sugar_harvest") is True

    assert state.status_of("sugar_harvest") == "researched"
    assert state.status_of("refined_mixing") == "available"
    # caramel_crafting requires BOTH sugar and dairy; still locked.
    assert state.status_of("caramel_crafting") == "locked"

    state.research("dairy_extraction")
    assert state.status_of("caramel_crafting") == "available"


# -- prereq gating ---------------------------------------------------------


def test_research_rejects_nodes_with_unmet_prereqs() -> None:
    state = ResearchState()
    assert state.can_research("refined_mixing") is False
    assert state.research("refined_mixing") is False
    assert "refined_mixing" not in state.researched


def test_research_rejects_duplicate_research() -> None:
    state = ResearchState()
    state.research("sugar_harvest")
    assert state.can_research("sugar_harvest") is False
    assert state.research("sugar_harvest") is False


def test_research_rejects_unknown_ids() -> None:
    state = ResearchState()
    assert state.research("not_a_real_node") is False
    assert state.can_research("not_a_real_node") is False


# -- event emission --------------------------------------------------------


def test_research_emits_change_event_with_node_id() -> None:
    bus = EventBus()
    calls, _off = _event_recorder(bus)

    state = ResearchState(bus)
    state.research("sugar_harvest")

    assert len(calls) == 1
    payload = calls[0]
    assert payload["node_id"] == "sugar_harvest"
    assert payload["state"] is state


def test_failed_research_does_not_emit() -> None:
    bus = EventBus()
    calls, _off = _event_recorder(bus)

    state = ResearchState(bus)
    # prereq unmet
    state.research("refined_mixing")
    # unknown id
    state.research("not_a_real_node")
    # duplicate
    state.research("sugar_harvest")
    state.research("sugar_harvest")

    assert len(calls) == 1  # only the successful sugar_harvest call above
    assert calls[0]["node_id"] == "sugar_harvest"


def test_reset_emits_change_event_only_when_progress_existed() -> None:
    bus = EventBus()
    calls, _off = _event_recorder(bus)
    state = ResearchState(bus)

    # Reset from an empty state: no event.
    state.reset()
    assert calls == []

    state.research("sugar_harvest")
    calls.clear()

    state.reset()
    assert len(calls) == 1
    assert calls[0]["node_id"] is None
    assert calls[0]["state"] is state
    assert state.researched == set()


# -- unlock predicate ------------------------------------------------------


def test_is_unlocked_honours_starting_unlocks() -> None:
    state = ResearchState()
    for pid in STARTING_UNLOCKS:
        assert state.is_unlocked(pid)
    # A gated prefab is not unlocked yet.
    assert not state.is_unlocked("extractor_sugar")


def test_is_unlocked_turns_on_after_research() -> None:
    state = ResearchState()
    assert not state.is_unlocked("extractor_sugar")
    state.research("sugar_harvest")
    assert state.is_unlocked("extractor_sugar")


def test_research_node_unlocking_returns_matching_node() -> None:
    state = ResearchState()
    node = state.research_node_unlocking("extractor_sugar")
    assert node is not None
    assert node.id == "sugar_harvest"

    # Starting-unlock prefabs are intentionally ``None``.
    assert state.research_node_unlocking("belt") is None
    # Unknown prefab ids produce ``None``.
    assert state.research_node_unlocking("totally_fake") is None


def test_unlocked_buildings_starts_from_starting_unlocks() -> None:
    state = ResearchState()
    assert set(state.unlocked_buildings()) == set(STARTING_UNLOCKS)
    state.research("sugar_harvest")
    assert "extractor_sugar" in state.unlocked_buildings()


# -- modifier math ---------------------------------------------------------


def test_multiplicative_modifier_defaults_to_one() -> None:
    state = ResearchState()
    assert state.modifier(ModKey.MINER_SPEED) == 1.0
    assert state.modifier(ModKey.ASSEMBLER_SPEED) == 1.0
    assert state.modifier(ModKey.BELT_THROUGHPUT) == 1.0


def test_port_capacity_modifier_defaults_to_zero() -> None:
    state = ResearchState()
    assert state.modifier(ModKey.PORT_CAPACITY) == 0.0


def test_multiplicative_modifiers_compound() -> None:
    state = ResearchState()
    # Unlock the miner-speed branch: both nodes grant +15% each.
    state.research("sugar_harvest")
    state.research("rapid_extraction_i")
    assert abs(state.modifier(ModKey.MINER_SPEED) - 1.15) < 1e-9
    state.research("rapid_extraction_ii")
    # (1 + 0.15) * (1 + 0.15) = 1.3225
    assert abs(state.modifier(ModKey.MINER_SPEED) - 1.3225) < 1e-9


def test_port_capacity_modifier_sums() -> None:
    state = ResearchState()
    # Walk the prereq chain: sugar -> dairy -> caramel -> larger_buffers.
    state.research("sugar_harvest")
    state.research("dairy_extraction")
    state.research("caramel_crafting")
    state.research("larger_buffers")
    assert state.modifier(ModKey.PORT_CAPACITY) == 1.0


def test_modifier_only_counts_researched_nodes() -> None:
    state = ResearchState()
    # With nothing researched, the MINER_SPEED modifier is neutral even
    # though two nodes in the tree grant it.
    assert state.modifier(ModKey.MINER_SPEED) == 1.0

    # After researching only the first tier, only that effect applies.
    state.research("sugar_harvest")
    state.research("rapid_extraction_i")
    assert abs(state.modifier(ModKey.MINER_SPEED) - 1.15) < 1e-9


def test_collect_effects_returns_nodes_effects() -> None:
    state = ResearchState()
    node = by_id("sugar_harvest")
    assert state.collect_effects(node) == node.effects


# -- integration: walk the whole tree once --------------------------------


def test_full_tree_can_be_researched_in_topological_order() -> None:
    """Every node is reachable when walking the tree in prereq order."""
    state = ResearchState()
    remaining = [n.id for n in RESEARCH]
    # Naive topological walk: loop until every node has been researched.
    safety = 0
    while remaining:
        safety += 1
        assert safety < 100, "research tree appears to have a cycle"
        progressed = False
        for nid in list(remaining):
            if state.can_research(nid):
                assert state.research(nid) is True
                remaining.remove(nid)
                progressed = True
        assert progressed, f"no node became available from {remaining}"
    # After the walk, every node is researched and every gated prefab is unlocked.
    assert {n.id for n in RESEARCH} == state.researched
