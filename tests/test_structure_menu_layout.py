"""Tests for the structure-menu hero-band layout under rotation / mirror.

These lock down:

* Band height reserves space above/below the diagram when any N/S port
  is present (and no vertical padding when only E/W ports exist).
* N/S callouts distribute horizontally at each port-marker's ``centerx``
  (rather than all stacking at the panel center) so rotated buildings
  with multiple vertical ports lay out legibly.
* Connector endpoints terminate at the *near* edge of the marker for
  every anchor side so no line visually crosses through its marker.
* ``_diagram_center`` shifts down by the top-callout band so the
  diagram doesn't collide with N callouts.
"""

from __future__ import annotations

import pygame

from src.assets.loader import AssetLoader
from src.buildings.registry import BUILDINGS
from src.ui import info as info_mod
from src.ui.structure_diagram import PORT_MARKER, layout_diagram
from src.ui.structure_menu import StructureMenu, _connector_endpoints
from src.world.direction import Direction


def _menu() -> StructureMenu:
    """Build a ``StructureMenu`` skipping asset I/O: we only touch pure math."""
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.HIDDEN)
    menu = StructureMenu.__new__(StructureMenu)
    menu.assets = AssetLoader.__new__(AssetLoader)  # type: ignore[attr-defined]
    return menu


# ---------------------------------------------------------------------------
# Band height
# ---------------------------------------------------------------------------


def test_east_facing_has_no_nb_bands() -> None:
    """A default E-facing assembler places ports only on W/E -- no N/S padding."""
    menu = _menu()
    info = info_mod.for_assembler(
        BUILDINGS.mixer_chocolate.factory((0, 0), Direction.E)
    )
    top_h, bottom_h = menu._top_bottom_band_heights(info)
    assert top_h == 0
    assert bottom_h == 0


def test_north_facing_reserves_both_nb_bands() -> None:
    """Rotating 90° puts inputs on S and outputs on N -- both bands populated."""
    menu = _menu()
    info = info_mod.for_assembler(
        BUILDINGS.mixer_chocolate.factory((0, 0), Direction.N)
    )
    top_h, bottom_h = menu._top_bottom_band_heights(info)
    assert top_h > 0
    assert bottom_h > 0


def test_south_facing_reserves_both_nb_bands() -> None:
    """S-facing: inputs at N (top band), output at S (bottom band)."""
    menu = _menu()
    info = info_mod.for_assembler(
        BUILDINGS.mixer_chocolate.factory((0, 0), Direction.S)
    )
    top_h, bottom_h = menu._top_bottom_band_heights(info)
    assert top_h > 0
    assert bottom_h > 0


def test_band_height_grows_with_n_s_ports() -> None:
    """Band height for N-facing must strictly exceed the E-facing version."""
    menu = _menu()
    info_e = info_mod.for_assembler(
        BUILDINGS.mixer_chocolate.factory((0, 0), Direction.E)
    )
    info_n = info_mod.for_assembler(
        BUILDINGS.mixer_chocolate.factory((0, 0), Direction.N)
    )
    assert menu._hero_band_height(info_n) > menu._hero_band_height(info_e)


# ---------------------------------------------------------------------------
# Horizontal distribution of N/S callouts
# ---------------------------------------------------------------------------


def test_wrapper_s_facing_two_top_callouts_spread_horizontally() -> None:
    """Wrapper facing S has 2 inputs on N; they must sit side-by-side."""
    menu = _menu()
    wrapper = BUILDINGS.wrapper_candy.factory((0, 0), Direction.S, False)
    info = info_mod.for_assembler(wrapper)

    top_ports = [p for p in info.port_rows if p.side is Direction.N]
    assert len(top_ports) == 2

    panel = pygame.Rect(0, 0, 600, 2000)
    diag_center = (panel.centerx, 500)
    _, hits = layout_diagram(diag_center, info)
    hits_by_index = {h.index: h for h in hits}

    placed = menu._layout_nb_callouts(top_ports, hits_by_index, panel)
    xs = sorted(r.x for r, _ in placed)
    # Distinct x AND the same row index (0 = closest to diagram) so
    # they're laid out horizontally rather than stacked.
    assert xs[0] != xs[1]
    assert all(r.y == 0 for r, _ in placed)


def test_wrapper_n_facing_two_bottom_callouts_spread_horizontally() -> None:
    """Wrapper facing N has 2 inputs on S -- bottom band mirrors the top case."""
    menu = _menu()
    wrapper = BUILDINGS.wrapper_candy.factory((0, 0), Direction.N, False)
    info = info_mod.for_assembler(wrapper)

    bottom_ports = [p for p in info.port_rows if p.side is Direction.S]
    assert len(bottom_ports) == 2

    panel = pygame.Rect(0, 0, 600, 2000)
    diag_center = (panel.centerx, 500)
    _, hits = layout_diagram(diag_center, info)
    hits_by_index = {h.index: h for h in hits}

    placed = menu._layout_nb_callouts(bottom_ports, hits_by_index, panel)
    xs = sorted(r.x for r, _ in placed)
    assert xs[0] != xs[1]


def test_nb_callouts_track_marker_centerx() -> None:
    """Each callout centers roughly on its marker's x (within panel bounds)."""
    menu = _menu()
    wrapper = BUILDINGS.wrapper_candy.factory((0, 0), Direction.S, False)
    info = info_mod.for_assembler(wrapper)
    top_ports = [p for p in info.port_rows if p.side is Direction.N]

    panel = pygame.Rect(0, 0, 600, 2000)
    diag_center = (panel.centerx, 500)
    _, hits = layout_diagram(diag_center, info)
    hits_by_index = {h.index: h for h in hits}
    placed = menu._layout_nb_callouts(top_ports, hits_by_index, panel)

    # At most the two callouts may shift by ~cw/2 due to edge clamping;
    # in practice for a 600-wide panel they're uncropped and the centers
    # should line up exactly with their markers.
    for rect, port in placed:
        hit = hits_by_index[port.index]
        center_x = rect.x + rect.w // 2
        assert abs(center_x - hit.rect.centerx) <= rect.w // 2


# ---------------------------------------------------------------------------
# Diagram center shifts with the top band
# ---------------------------------------------------------------------------


def test_diagram_center_shifts_down_for_north_ports() -> None:
    """Adding a top callout band pushes the diagram center downward."""
    menu = _menu()
    info_e = info_mod.for_assembler(
        BUILDINGS.mixer_chocolate.factory((0, 0), Direction.E)
    )
    info_n = info_mod.for_assembler(
        BUILDINGS.mixer_chocolate.factory((0, 0), Direction.N)
    )
    panel = pygame.Rect(0, 0, 600, 2000)
    cy_e = menu._diagram_center(panel, info_e)[1]
    cy_n = menu._diagram_center(panel, info_n)[1]
    assert cy_n > cy_e


# ---------------------------------------------------------------------------
# Connector endpoints terminate at the near edge of the marker
# ---------------------------------------------------------------------------


def test_connector_left_anchor_ends_at_marker_right_edge() -> None:
    """anchor 'left' => callout to the right; end at marker's RIGHT edge."""
    callout = pygame.Rect(400, 100, 136, 56)  # callout right of marker
    marker = pygame.Rect(200, 100, PORT_MARKER, PORT_MARKER)
    _, end = _connector_endpoints(callout, marker, "left")
    assert end == (marker.right, marker.centery)


def test_connector_right_anchor_ends_at_marker_left_edge() -> None:
    """anchor 'right' => callout to the left; end at marker's LEFT edge."""
    callout = pygame.Rect(50, 100, 136, 56)  # callout left of marker
    marker = pygame.Rect(400, 100, PORT_MARKER, PORT_MARKER)
    _, end = _connector_endpoints(callout, marker, "right")
    assert end == (marker.left, marker.centery)


def test_connector_top_anchor_ends_at_marker_bottom_edge() -> None:
    """anchor 'top' => callout below marker; end at marker's BOTTOM edge."""
    callout = pygame.Rect(100, 400, 136, 56)  # callout below marker
    marker = pygame.Rect(100, 200, PORT_MARKER, PORT_MARKER)
    _, end = _connector_endpoints(callout, marker, "top")
    assert end == (marker.centerx, marker.bottom)


def test_connector_bottom_anchor_ends_at_marker_top_edge() -> None:
    """anchor 'bottom' => callout above marker; end at marker's TOP edge."""
    callout = pygame.Rect(100, 50, 136, 56)  # callout above marker
    marker = pygame.Rect(100, 400, PORT_MARKER, PORT_MARKER)
    _, end = _connector_endpoints(callout, marker, "bottom")
    assert end == (marker.centerx, marker.top)


def test_connector_start_is_on_expected_callout_edge() -> None:
    """Sanity-check: ``start`` is always on the edge named by ``anchor_side``."""
    callout = pygame.Rect(100, 100, 140, 60)
    marker = pygame.Rect(400, 400, PORT_MARKER, PORT_MARKER)
    cases = {
        "left": (callout.left, callout.centery),
        "right": (callout.right, callout.centery),
        "top": (callout.centerx, callout.top),
        "bottom": (callout.centerx, callout.bottom),
    }
    for side, expected in cases.items():
        start, _ = _connector_endpoints(callout, marker, side)
        assert start == expected, side
