"""Default objective catalog: a tiered progression for the sweet-works.

Tiers chain via ``prereq_ids`` so later objectives stay locked in the
UI until their foundations are done, producing a readable "what's next"
funnel without any hand-holding pop-ups.
"""

from __future__ import annotations

from .objectives import ObjectiveKind, ObjectiveSpec

# -- Tier 1: Gather ---------------------------------------------------------

_T1_COCOA = ObjectiveSpec(
    id="t1_cocoa",
    title="First Harvest",
    description="Produce your first Cocoa Bean.",
    tier=1,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="cocoa_bean",
    amount=1,
    icon_item_id="cocoa_bean",
)
_T1_SUGAR = ObjectiveSpec(
    id="t1_sugar",
    title="Sugar Rush",
    description="Produce your first Sugar Crystal.",
    tier=1,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="sugar_crystal",
    amount=1,
    icon_item_id="sugar_crystal",
)
_T1_MILK = ObjectiveSpec(
    id="t1_milk",
    title="Dairy Farm",
    description="Produce your first unit of Milk.",
    tier=1,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="milk",
    amount=1,
    icon_item_id="milk",
)
_T1_MINERS = ObjectiveSpec(
    id="t1_miners",
    title="Plant the Flag",
    description="Have three extractors of any type running at once.",
    tier=1,
    kind=ObjectiveKind.PLACE_BUILDING_COUNT,
    building_id="miner",
    amount=3,
    icon_building_id="extractor_cocoa",
)

# -- Tier 2: Craft ----------------------------------------------------------

_T2_CHOCO = ObjectiveSpec(
    id="t2_choco",
    title="First Bar",
    description="Produce your first Chocolate.",
    tier=2,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="chocolate",
    amount=1,
    icon_item_id="chocolate",
    prereq_ids=("t1_cocoa",),
)
_T2_CARAMEL = ObjectiveSpec(
    id="t2_caramel",
    title="Sweet Goo",
    description="Produce your first Caramel.",
    tier=2,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="caramel",
    amount=1,
    icon_item_id="caramel",
    prereq_ids=("t1_sugar", "t1_milk"),
)
_T2_ASSEMBLERS = ObjectiveSpec(
    id="t2_assemblers",
    title="Assembly Line",
    description="Have three assemblers of any type running at once.",
    tier=2,
    kind=ObjectiveKind.PLACE_BUILDING_COUNT,
    building_id="assembler",
    amount=3,
    icon_building_id="mixer_chocolate",
    prereq_ids=("t1_miners",),
)

# -- Tier 3: Scale ----------------------------------------------------------

_T3_STOCKPILE = ObjectiveSpec(
    id="t3_stockpile",
    title="Stockpile",
    description="Produce 100 Chocolate in total.",
    tier=3,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="chocolate",
    amount=100,
    icon_item_id="chocolate",
    prereq_ids=("t2_choco",),
)
_T3_SUSTAIN = ObjectiveSpec(
    id="t3_sustain",
    title="Sustained Supply",
    description="Hold Chocolate production above 60/min for 15 seconds.",
    tier=3,
    kind=ObjectiveKind.SUSTAIN_RATE,
    item_id="chocolate",
    rate_per_min=60.0,
    window_s=10,
    hold_s=15.0,
    icon_item_id="chocolate",
    prereq_ids=("t3_stockpile",),
)
_T3_CANDY = ObjectiveSpec(
    id="t3_candy",
    title="Sweet Empire",
    description="Produce 25 Candy Bars in total.",
    tier=3,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="candy_bar",
    amount=25,
    icon_item_id="candy_bar",
    prereq_ids=("t2_choco", "t2_caramel"),
)
_T3_BELTS = ObjectiveSpec(
    id="t3_belts",
    title="Belt Backbone",
    description="Place 50 conveyor belt tiles.",
    tier=3,
    kind=ObjectiveKind.BELT_TILES,
    amount=50,
    prereq_ids=("t2_assemblers",),
)

# -- Tier 4: Master ---------------------------------------------------------

_T4_COCOA = ObjectiveSpec(
    id="t4_cocoa",
    title="Bean Mountain",
    description="Produce 1,000 Cocoa Beans.",
    tier=4,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="cocoa_bean",
    amount=1000,
    icon_item_id="cocoa_bean",
    prereq_ids=("t3_stockpile",),
)
_T4_CARAMEL = ObjectiveSpec(
    id="t4_caramel",
    title="Caramel Baron",
    description="Produce 250 Caramel.",
    tier=4,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="caramel",
    amount=250,
    icon_item_id="caramel",
    prereq_ids=("t2_caramel",),
)
_T4_CANDY = ObjectiveSpec(
    id="t4_candy",
    title="Candy Factory",
    description="Produce 500 Candy Bars.",
    tier=4,
    kind=ObjectiveKind.PRODUCE_TOTAL,
    item_id="candy_bar",
    amount=500,
    icon_item_id="candy_bar",
    prereq_ids=("t3_candy",),
)
_T4_MASS = ObjectiveSpec(
    id="t4_mass",
    title="Mass Production",
    description="Hold Candy Bar production above 30/min for 20 seconds.",
    tier=4,
    kind=ObjectiveKind.SUSTAIN_RATE,
    item_id="candy_bar",
    rate_per_min=30.0,
    window_s=10,
    hold_s=20.0,
    icon_item_id="candy_bar",
    prereq_ids=("t3_candy",),
)


OBJECTIVES_CATALOG: tuple[ObjectiveSpec, ...] = (
    _T1_COCOA,
    _T1_SUGAR,
    _T1_MILK,
    _T1_MINERS,
    _T2_CHOCO,
    _T2_CARAMEL,
    _T2_ASSEMBLERS,
    _T3_STOCKPILE,
    _T3_SUSTAIN,
    _T3_CANDY,
    _T3_BELTS,
    _T4_COCOA,
    _T4_CARAMEL,
    _T4_CANDY,
    _T4_MASS,
)


__all__ = ["OBJECTIVES_CATALOG"]
