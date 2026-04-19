"""Tests for the ``ui.info`` projection: ipm math + row shapes.

These lock down the items-per-minute numbers the tooltip and the
selected-structure menu display, so any regression in
``buildings/registry.py`` recipe constants (``period_ticks`` or
``recipe.ticks``) is caught here before it hits the UI.
"""

from __future__ import annotations

from src.belts.belt import ConveyorBelt
from src.buildings.port import PortKind
from src.buildings.registry import BUILDINGS
from src.core import config
from src.items.registry import ITEMS
from src.ui import info as info_mod
from src.world.direction import Direction

# ---------------------------------------------------------------------------
# Math primitives
# ---------------------------------------------------------------------------


def test_miner_ipm_matches_tick_math() -> None:
    # Default miner prefabs use period_ticks=10 (iron/copper) and 12 (coal).
    assert info_mod.miner_ipm(10) == (60.0 * config.TICK_HZ) / 10
    assert info_mod.miner_ipm(12) == (60.0 * config.TICK_HZ) / 12
    # period_ticks is floored at 1.
    assert info_mod.miner_ipm(0) == 60.0 * config.TICK_HZ


def test_assembler_cycles_per_minute() -> None:
    assert info_mod.assembler_cycles_per_minute(20) == (60.0 * config.TICK_HZ) / 20
    assert info_mod.assembler_cycles_per_minute(30) == (60.0 * config.TICK_HZ) / 30


def test_belt_max_ipm_is_one_slot_per_tick() -> None:
    # One slot advancement per tick -> 20 * 60 = 1200 items/min per lane.
    assert info_mod.belt_max_ipm() == 60.0 * config.TICK_HZ


# ---------------------------------------------------------------------------
# Concrete prefabs
# ---------------------------------------------------------------------------


def test_for_miner_iron_reports_120_per_min() -> None:
    miner = BUILDINGS.miner_iron.factory((0, 0), Direction.E)
    info = info_mod.for_miner(miner)
    assert info.kind == "miner"
    assert info.primary_item is ITEMS.iron
    # Iron miner prefab has period_ticks=10 -> exactly 120/min.
    rate_labels = {row.label: row.value for row in info.rate_rows}
    assert "Output" in rate_labels
    assert "120/min" in rate_labels["Output"]
    assert "Cycle" in rate_labels
    # A single output port.
    assert len(info.port_rows) == 1
    assert info.port_rows[0].kind is PortKind.OUTPUT
    assert info.port_rows[0].item is ITEMS.iron


def test_for_miner_coal_reports_100_per_min() -> None:
    miner = BUILDINGS.miner_coal.factory((0, 0), Direction.E)
    info = info_mod.for_miner(miner)
    rate_labels = {row.label: row.value for row in info.rate_rows}
    assert "100/min" in rate_labels["Output"]


def test_for_assembler_plate_reports_60_iron_in_60_plate_out() -> None:
    asm = BUILDINGS.assembler_plate.factory((0, 0), Direction.E)
    info = info_mod.for_assembler(asm)
    assert info.kind == "assembler"
    assert info.primary_item is ITEMS.plate
    labels = [row.label for row in info.rate_rows]
    assert any(lbl.startswith("In - Iron") for lbl in labels)
    assert any(lbl.startswith("Out - Iron Plate") for lbl in labels)
    values_by_label = {row.label: row.value for row in info.rate_rows}
    # Plate recipe: 20 ticks, 1 iron -> 1 plate. cpm = 60, so 60/min each.
    assert "60/min" in next(v for k, v in values_by_label.items() if k.startswith("In"))
    assert "60/min" in next(v for k, v in values_by_label.items() if k.startswith("Out"))
    # Port rows include both input and output.
    kinds = {p.kind for p in info.port_rows}
    assert PortKind.INPUT in kinds
    assert PortKind.OUTPUT in kinds
    # Not yet crafting -> zeroed progress, non-None so the bar still draws.
    assert info.progress == 0.0


def test_for_assembler_gear_reports_80_plate_in_40_gear_out() -> None:
    asm = BUILDINGS.assembler_gear.factory((0, 0), Direction.E)
    info = info_mod.for_assembler(asm)
    values_by_label = {row.label: row.value for row in info.rate_rows}
    in_val = next(v for k, v in values_by_label.items() if k.startswith("In"))
    out_val = next(v for k, v in values_by_label.items() if k.startswith("Out"))
    # Gear recipe: 30 ticks, 2 plate -> 1 gear. cpm = 40. in 80/min, out 40/min.
    assert "80/min" in in_val
    assert "40/min" in out_val


def test_for_belt_reports_max_lane_throughput() -> None:
    belt = ConveyorBelt((5, 5), Direction.E)
    info = info_mod.for_belt(belt, None)
    assert info.kind == "belt"
    labels = {row.label: row.value for row in info.rate_rows}
    # 20 Hz * 60 = 1200 items/min theoretical max.
    assert "1200/min" in labels["Max flow"]
    assert labels["Slots"].startswith("4")


def test_for_building_dispatches_by_type() -> None:
    miner = BUILDINGS.miner_iron.factory((0, 0), Direction.E)
    asm = BUILDINGS.assembler_plate.factory((2, 0), Direction.E)
    assert info_mod.for_building(miner).kind == "miner"
    assert info_mod.for_building(asm).kind == "assembler"


def test_brief_returns_tooltip_rows() -> None:
    miner = BUILDINGS.miner_iron.factory((0, 0), Direction.E)
    info = info_mod.for_miner(miner)
    rows = info_mod.brief(info)
    assert rows is info.tooltip_rows
    assert len(rows) >= 2
