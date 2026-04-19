"""Tests for the ``ui.info`` projection: ipm math + row shapes.

These lock down the items-per-minute numbers the tooltip and the
selected-structure menu display, so any regression in
``buildings/registry.py`` recipe constants (``period_ticks`` or
``recipe.ticks``) is caught here before it hits the UI.
"""

from __future__ import annotations

import pygame
import pytest

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


# ---------------------------------------------------------------------------
# Spatial fields (footprint, rotation, cell_offset, index)
# ---------------------------------------------------------------------------


def test_for_miner_populates_footprint_and_rotation() -> None:
    miner = BUILDINGS.miner_iron.factory((3, 5), Direction.E)
    info = info_mod.for_miner(miner)
    assert info.footprint == (1, 1)
    assert info.rotation is Direction.E
    assert len(info.port_rows) == 1
    port = info.port_rows[0]
    assert port.cell_offset == (0, 0)
    assert port.index == 0
    # Miner output port side always follows building rotation.
    assert port.side is Direction.E


def test_for_miner_port_side_rotates_with_building() -> None:
    for rot in (Direction.N, Direction.E, Direction.S, Direction.W):
        miner = BUILDINGS.miner_iron.factory((0, 0), rot)
        info = info_mod.for_miner(miner)
        assert info.rotation is rot
        assert info.port_rows[0].side is rot
        assert info.port_rows[0].cell_offset == (0, 0)


def test_for_assembler_populates_footprint_and_port_layout() -> None:
    asm = BUILDINGS.assembler_plate.factory((6, 3), Direction.E)
    info = info_mod.for_assembler(asm)
    assert info.footprint == (2, 2)
    assert info.rotation is Direction.E
    by_kind: dict[PortKind, info_mod.PortInfo] = {
        p.kind: p for p in info.port_rows
    }
    # Plate assembler: 1 input on (0,0) west, 1 output on (1,0) east.
    assert by_kind[PortKind.INPUT].cell_offset == (0, 0)
    assert by_kind[PortKind.INPUT].side is Direction.W
    assert by_kind[PortKind.OUTPUT].cell_offset == (1, 0)
    assert by_kind[PortKind.OUTPUT].side is Direction.E
    # Stable, unique indices.
    indices = [p.index for p in info.port_rows]
    assert indices == sorted(set(indices))


def test_for_belt_populates_footprint_and_rotation() -> None:
    for rot in (Direction.N, Direction.E, Direction.S, Direction.W):
        belt = ConveyorBelt((0, 0), rot)
        info = info_mod.for_belt(belt, None)
        assert info.footprint == (1, 1)
        assert info.rotation is rot


# ---------------------------------------------------------------------------
# StructureMenu world_highlight smoke test
# ---------------------------------------------------------------------------


class _StubAssets:
    """Minimal AssetLoader stand-in for headless tests."""

    def render_text(self, text: str, style, color) -> pygame.Surface:
        w = max(1, len(text) * 6)
        surf = pygame.Surface((w, 12), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        return surf

    def item_icon(self, item_id: str) -> pygame.Surface:  # pragma: no cover
        raise FileNotFoundError(item_id)


@pytest.fixture
def reset_menu_session():
    """Clear process-wide StructureMenu session state around each test."""
    from src.ui.structure_menu import StructureMenu

    prev_pos = StructureMenu._session_pos
    prev_anchored = StructureMenu._session_anchored
    StructureMenu._session_pos = None
    StructureMenu._session_anchored = False
    try:
        yield
    finally:
        StructureMenu._session_pos = prev_pos
        StructureMenu._session_anchored = prev_anchored


def _snap_menu_to_rest(menu) -> None:
    """Force all menu animations into their fully-settled state."""
    menu._slide_progress.elapsed = menu._slide_progress.duration
    menu._slide_progress.done = True
    menu._slide_value = 1.0
    menu._panel_h_anim.value = menu._panel_h_anim.target
    menu._resting_x_anim.value = menu._resting_x_anim.target
    menu._resting_y_anim.value = menu._resting_y_anim.target


def test_structure_menu_world_highlight_follows_hovered_port(reset_menu_session) -> None:
    pygame.init()
    try:
        from src.ui.structure_diagram import layout_diagram
        from src.ui.structure_menu import StructureMenu

        menu = StructureMenu(_StubAssets())  # type: ignore[arg-type]
        menu.layout((1280, 720))

        origin = (5, 7)
        miner = BUILDINGS.miner_iron.factory(origin, Direction.E)
        menu.open_building(miner)

        # Initial update with mouse far off to populate info + layout.
        menu.update(0.016, (-9999, -9999), False, False)
        assert menu.world_highlight() is None

        # Snap every animation to its fully-settled state so the panel
        # rect stops moving between frames.
        _snap_menu_to_rest(menu)

        info = menu._info
        panel_rect = menu.rect()
        assert info is not None
        assert panel_rect is not None

        diag_center = menu._diagram_center(panel_rect, info)
        _, hits = layout_diagram(diag_center, info)
        assert len(hits) == 1
        mouse = hits[0].rect.center

        menu.update(0.016, mouse, False, False)
        highlight = menu.world_highlight()
        assert highlight is not None
        # Highlight cell = origin + cell_offset; miner port is at (0,0).
        assert highlight.cell == origin
        assert highlight.footprint == (1, 1)
        assert highlight.accent == ITEMS.iron.color
    finally:
        pygame.quit()


# ---------------------------------------------------------------------------
# Draggable StructureMenu
# ---------------------------------------------------------------------------


def test_menu_saves_session_position_after_drag(reset_menu_session) -> None:
    pygame.init()
    try:
        from src.ui.structure_menu import StructureMenu

        menu = StructureMenu(_StubAssets())  # type: ignore[arg-type]
        menu.layout((1280, 720))

        miner = BUILDINGS.miner_iron.factory((3, 3), Direction.E)
        menu.open_building(miner)
        menu.update(0.016, (-1, -1), False, False)
        _snap_menu_to_rest(menu)
        menu.update(0.016, (-1, -1), False, False)

        # Capture the pre-drag resting position to derive the expected
        # drop location below.
        initial_resting = (
            int(menu._resting_x_anim.value),
            int(menu._resting_y_anim.value),
        )

        # Grab: mouse-down over the move button.
        grip = menu._move_btn.rect
        grab_point = grip.center
        grab_offset = (
            grab_point[0] - initial_resting[0],
            grab_point[1] - initial_resting[1],
        )
        menu.update(0.016, grab_point, True, False)
        assert menu._dragging is True

        # Pick a drop location so the resulting panel (mouse - grab offset)
        # still lands inside the safe clamp rect. Using a panel top-left
        # around (200, 120) keeps everything on a 1280x720 window.
        desired_resting = (200, 120)
        target_mouse = (
            desired_resting[0] + grab_offset[0],
            desired_resting[1] + grab_offset[1],
        )
        menu.update(0.016, target_mouse, True, False)
        assert menu._dragging is True
        menu.update(0.016, target_mouse, False, True)

        assert menu._dragging is False
        assert StructureMenu._session_anchored is True
        saved = StructureMenu._session_pos
        assert saved is not None

        # The drop should land at the desired resting position (clamping
        # is a no-op for a location well inside the window).
        assert abs(saved[0] - desired_resting[0]) <= 1
        assert abs(saved[1] - desired_resting[1]) <= 1
        # ...and the saved position should differ meaningfully from the
        # default right-dock anchor.
        assert saved != initial_resting
    finally:
        pygame.quit()


def test_menu_second_open_reuses_session_position(reset_menu_session) -> None:
    pygame.init()
    try:
        from src.ui.structure_menu import StructureMenu

        StructureMenu._session_pos = (120, 80)
        StructureMenu._session_anchored = True

        menu = StructureMenu(_StubAssets())  # type: ignore[arg-type]
        menu.layout((1280, 720))

        miner = BUILDINGS.miner_iron.factory((1, 1), Direction.E)
        menu.open_building(miner)
        # Pump a frame then snap animations so rect() returns the resting pos.
        menu.update(0.016, (-1, -1), False, False)
        _snap_menu_to_rest(menu)
        menu.update(0.016, (-1, -1), False, False)

        r = menu.rect()
        assert r is not None
        assert abs(r.x - 120) <= 1
        assert abs(r.y - 80) <= 1
    finally:
        pygame.quit()


def test_slide_edge_picks_closest(reset_menu_session) -> None:
    pygame.init()
    try:
        from src.ui.structure_menu import StructureMenu

        menu = StructureMenu(_StubAssets())  # type: ignore[arg-type]
        menu.layout((1280, 720))
        # Use the minimum panel height for a deterministic center.
        menu._panel_h_anim.target = 320

        # With a 600x320 panel on a 1280x720 window the center (cx, cy)
        # is (resting.x + 300, resting.y + 160), distances are measured
        # from each window edge.

        # Hugs the left edge: cx is the smallest component.
        assert menu._pick_slide_edge((10, 200)) is Direction.W
        # Hugs the right edge.
        assert menu._pick_slide_edge((670, 200)) is Direction.E
        # Hugs the top edge.
        assert menu._pick_slide_edge((300, 10)) is Direction.N
        # Hugs the bottom edge.
        assert menu._pick_slide_edge((300, 400)) is Direction.S
    finally:
        pygame.quit()
