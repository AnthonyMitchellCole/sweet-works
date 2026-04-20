"""Canonical research tree contents.

The shape is authored as a 5-column, 3-ish-row grid spanning four
categories (*Extraction / Processing / Packaging / Logistics*). The
scene multiplies :attr:`ResearchNode.grid_pos` by a node stride to
lay the cards out on the pan/zoom board.

Starting buildings (``extractor_cocoa``, ``belt``, ``pointer``) are
permanently unlocked; every other building is gated behind exactly
one node so the toolbar reacts cleanly to ``research.changed``.
"""

from __future__ import annotations

from .node import Effect, ModKey, ResearchNode

RESEARCH: tuple[ResearchNode, ...] = (
    # -- Column 0: starting tier -----------------------------------------
    ResearchNode(
        id="sugar_harvest",
        name="Sugar Harvest",
        blurb="Refine the cocoa-farm's irrigation channels to draw up sweet sugar crystals.",
        category="Extraction",
        grid_pos=(0, 0),
        prereqs=(),
        effects=(Effect.unlock("extractor_sugar"),),
        icon_building_id="extractor_sugar",
        icon_item_id="sugar_crystal",
    ),
    ResearchNode(
        id="dairy_extraction",
        name="Dairy Extraction",
        blurb="Tap underground reservoirs of fresh milk with reinforced pumping wells.",
        category="Extraction",
        grid_pos=(0, 1),
        prereqs=(),
        effects=(Effect.unlock("well_milk"),),
        icon_building_id="well_milk",
        icon_item_id="milk",
    ),
    # -- Column 1: first processing tier ---------------------------------
    ResearchNode(
        id="refined_mixing",
        name="Refined Mixing",
        blurb="Stir cocoa into luscious, uniform chocolate using tempered mixer drums.",
        category="Processing",
        grid_pos=(1, 0),
        prereqs=("sugar_harvest",),
        effects=(Effect.unlock("mixer_chocolate"),),
        icon_building_id="mixer_chocolate",
        icon_item_id="chocolate",
    ),
    ResearchNode(
        id="caramel_crafting",
        name="Caramel Crafting",
        blurb="Boil sugar and milk into rich, golden caramel inside insulated pots.",
        category="Processing",
        grid_pos=(1, 1),
        prereqs=("sugar_harvest", "dairy_extraction"),
        effects=(Effect.unlock("pot_caramel"),),
        icon_building_id="pot_caramel",
        icon_item_id="caramel",
    ),
    # -- Column 2: packaging tier ----------------------------------------
    ResearchNode(
        id="wrapping_tech",
        name="Wrapping Technology",
        blurb="Combine chocolate and caramel into beautifully wrapped finished candy bars.",
        category="Packaging",
        grid_pos=(2, 1),
        prereqs=("refined_mixing", "caramel_crafting"),
        effects=(Effect.unlock("wrapper_candy"),),
        icon_building_id="wrapper_candy",
        icon_item_id="candy_bar",
    ),
    # -- Row: extraction modifiers (top row) -----------------------------
    ResearchNode(
        id="rapid_extraction_i",
        name="Rapid Extraction I",
        blurb="Auto-lubricated drill shafts let every extractor cycle a tick faster.",
        category="Extraction",
        grid_pos=(2, 0),
        prereqs=("sugar_harvest",),
        effects=(Effect.modifier(ModKey.MINER_SPEED, 0.15),),
        icon_item_id="cocoa_bean",
        tags=("modifier",),
    ),
    ResearchNode(
        id="rapid_extraction_ii",
        name="Rapid Extraction II",
        blurb="Hardened bits and pressurised feeds push miner throughput another notch.",
        category="Extraction",
        grid_pos=(3, 0),
        prereqs=("rapid_extraction_i",),
        effects=(Effect.modifier(ModKey.MINER_SPEED, 0.15),),
        icon_item_id="sugar_crystal",
        tags=("modifier",),
    ),
    # -- Row: processing modifier ----------------------------------------
    ResearchNode(
        id="precision_assembly",
        name="Precision Assembly",
        blurb="Calibrated servo arms shave idle frames off every assembler's recipe.",
        category="Processing",
        grid_pos=(3, 1),
        prereqs=("refined_mixing",),
        effects=(Effect.modifier(ModKey.ASSEMBLER_SPEED, 0.20),),
        icon_item_id="chocolate",
        tags=("modifier",),
    ),
    # -- Row: logistics --------------------------------------------------
    ResearchNode(
        id="larger_buffers",
        name="Larger Buffers",
        blurb="Reinforce every port with an extra hopper slot to smooth throughput bursts.",
        category="Logistics",
        grid_pos=(3, 2),
        prereqs=("caramel_crafting",),
        effects=(Effect.modifier(ModKey.PORT_CAPACITY, 1.0),),
        icon_item_id="caramel",
        tags=("modifier",),
    ),
    ResearchNode(
        id="belt_tuning",
        name="Belt Tuning",
        blurb="Low-friction rollers nudge belt throughput up across the entire network.",
        category="Logistics",
        grid_pos=(4, 2),
        prereqs=("larger_buffers",),
        effects=(Effect.modifier(ModKey.BELT_THROUGHPUT, 0.25),),
        icon_item_id="candy_bar",
        tags=("modifier",),
    ),
)


# Buildings that are available without any research.
STARTING_UNLOCKS: frozenset[str] = frozenset({"extractor_cocoa", "belt", "pointer"})


_BY_ID: dict[str, ResearchNode] = {n.id: n for n in RESEARCH}


def by_id(node_id: str) -> ResearchNode:
    """Look up a node by id. Raises ``KeyError`` if absent."""
    return _BY_ID[node_id]


def try_by_id(node_id: str) -> ResearchNode | None:
    return _BY_ID.get(node_id)


def roots() -> tuple[ResearchNode, ...]:
    """Nodes that have no prerequisites."""
    return tuple(n for n in RESEARCH if not n.prereqs)


def children_of(node_id: str) -> tuple[ResearchNode, ...]:
    """Nodes that list ``node_id`` as one of their prereqs."""
    return tuple(n for n in RESEARCH if node_id in n.prereqs)


def all_edges() -> tuple[tuple[str, str], ...]:
    """Directed ``(parent_id, child_id)`` edges covering the whole tree."""
    edges: list[tuple[str, str]] = []
    for node in RESEARCH:
        for parent in node.prereqs:
            edges.append((parent, node.id))
    return tuple(edges)


__all__ = [
    "RESEARCH",
    "STARTING_UNLOCKS",
    "all_edges",
    "by_id",
    "children_of",
    "roots",
    "try_by_id",
]
