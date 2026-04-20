"""Top-down hero diagram of a building for the Structure menu.

Renders the building's footprint as a cell grid with spatially accurate
port markers on the correct side of the correct cell. Callouts in the
menu connect to the ``PortHit`` rects returned from
:func:`draw_diagram`, and the diagram is also responsible for the
compass chevron that signals the building's rotation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from ..buildings.port import PortKind
from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from ..world.direction import Direction
from .info import StructureInfo

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


# Public layout constants the menu uses to budget space.
CELL_PX: int = 96
GRID_GAP: int = 2           # gap between cells inside the grid
PORT_MARKER: int = 28       # visible marker edge size
PORT_OFFSET: int = 20       # outward distance from cell edge to marker center
DIAGRAM_MARGIN: int = 40    # padding reserved around the grid for markers
HIT_INFLATE: int = 14       # extra padding on the hit rect for easier hovering


@dataclass(frozen=True)
class PortHit:
    """Hit-test record for a single port marker on the diagram.

    ``rect`` is the visible marker bounds (used by the menu to anchor
    connector lines from callouts to markers). ``hit_rect`` is inflated
    by :data:`HIT_INFLATE` so hovering the port is forgiving on the mouse.
    """

    index: int
    side: Direction
    cell_offset: tuple[int, int]
    rect: pygame.Rect
    hit_rect: pygame.Rect


def diagram_size(info: StructureInfo) -> tuple[int, int]:
    """Total pixel footprint of the diagram for the given structure."""
    fw, fh = info.footprint
    grid_w = fw * CELL_PX + max(0, fw - 1) * GRID_GAP
    grid_h = fh * CELL_PX + max(0, fh - 1) * GRID_GAP
    return grid_w + DIAGRAM_MARGIN * 2, grid_h + DIAGRAM_MARGIN * 2


def layout_diagram(
    center: tuple[int, int],
    info: StructureInfo,
) -> tuple[pygame.Rect, tuple[PortHit, ...]]:
    """Pure layout pass (no drawing). Returns the grid rect and port hits."""
    fw, fh = info.footprint
    grid_w = fw * CELL_PX + max(0, fw - 1) * GRID_GAP
    grid_h = fh * CELL_PX + max(0, fh - 1) * GRID_GAP
    grid_origin = (center[0] - grid_w // 2, center[1] - grid_h // 2)
    grid_rect = pygame.Rect(grid_origin[0], grid_origin[1], grid_w, grid_h)
    hits: list[PortHit] = []
    for port in info.port_rows:
        cx, cy = port.cell_offset
        if not (0 <= cx < fw and 0 <= cy < fh):
            continue
        cell = _cell_rect(grid_origin, cx, cy)
        mx, my = _marker_center(cell, port.side)
        marker_rect = pygame.Rect(
            mx - PORT_MARKER // 2,
            my - PORT_MARKER // 2,
            PORT_MARKER,
            PORT_MARKER,
        )
        hits.append(
            PortHit(
                index=port.index,
                side=port.side,
                cell_offset=port.cell_offset,
                rect=marker_rect,
                hit_rect=marker_rect.inflate(HIT_INFLATE, HIT_INFLATE),
            )
        )
    return grid_rect, tuple(hits)


def _cell_rect(grid_origin: tuple[int, int], cx: int, cy: int) -> pygame.Rect:
    ox, oy = grid_origin
    return pygame.Rect(
        ox + cx * (CELL_PX + GRID_GAP),
        oy + cy * (CELL_PX + GRID_GAP),
        CELL_PX,
        CELL_PX,
    )


def _marker_center(cell: pygame.Rect, side: Direction) -> tuple[int, int]:
    if side is Direction.E:
        return (cell.right + PORT_OFFSET, cell.centery)
    if side is Direction.W:
        return (cell.left - PORT_OFFSET, cell.centery)
    if side is Direction.N:
        return (cell.centerx, cell.top - PORT_OFFSET)
    return (cell.centerx, cell.bottom + PORT_OFFSET)


def draw_diagram(
    surface: pygame.Surface,
    center: tuple[int, int],
    info: StructureInfo,
    assets: AssetLoader,
    *,
    time: float,
    port_fill: Mapping[int, float],
    hovered_index: int | None,
) -> tuple[pygame.Rect, tuple[PortHit, ...]]:
    """Draw the diagram centered at ``center`` and return (grid_rect, hits)."""
    grid_rect, hits = layout_diagram(center, info)
    fw, fh = info.footprint
    grid_origin = (grid_rect.x, grid_rect.y)

    for cy in range(fh):
        for cx in range(fw):
            cell = _cell_rect(grid_origin, cx, cy)
            beveled_panel(
                surface,
                cell,
                fill=darken(PALETTE.bg_raised, 0.15),
                border=PALETTE.line,
            )
            _draw_cell_glyph(surface, cell, info, assets)

    _draw_rotation_glyph(surface, grid_rect, info, time)
    if info.mirrored:
        _draw_mirror_glyph(surface, grid_rect, info, time)

    hits_by_index = {h.index: h for h in hits}
    for port in info.port_rows:
        hit = hits_by_index.get(port.index)
        if hit is None:
            continue
        fill_frac = float(port_fill.get(port.index, port.fill))
        is_hovered = hovered_index is not None and hovered_index == port.index
        _draw_port_marker(
            surface,
            hit.rect,
            port_kind=port.kind,
            side=port.side,
            item_color=port.item.color if port.item is not None else info.accent,
            fill_frac=fill_frac,
            is_full=port.is_full,
            is_hovered=is_hovered,
            time=time,
        )

    return grid_rect, hits


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _draw_cell_glyph(
    surface: pygame.Surface,
    cell: pygame.Rect,
    info: StructureInfo,
    assets: AssetLoader,
) -> None:
    """Draw a faint inner glyph that identifies the building in each cell."""
    inner = cell.inflate(-24, -24)
    sprite: pygame.Surface | None = None
    if info.primary_item is not None:
        try:
            sprite = assets.item_icon(info.primary_item.id)
        except (FileNotFoundError, pygame.error):
            sprite = None

    if sprite is not None:
        scaled = pygame.transform.smoothscale(sprite, (inner.w, inner.h))
        scaled.set_alpha(90)
        surface.blit(scaled, inner.topleft)
        return

    pygame.draw.rect(surface, with_alpha(info.accent, 40), inner)
    pygame.draw.rect(surface, with_alpha(info.accent, 110), inner, 1)


def _draw_rotation_glyph(
    surface: pygame.Surface,
    grid: pygame.Rect,
    info: StructureInfo,
    time: float,
) -> None:
    """Small chevron on the building's front edge + a soft breathing ring."""
    dx, dy = info.rotation.vector
    edge_x = grid.centerx + int(dx * (grid.w / 2 - 14))
    edge_y = grid.centery + int(dy * (grid.h / 2 - 14))

    # Breathing halo around the chevron so it reads as "live".
    pulse = 0.5 + 0.5 * math.sin(time * 2.5)
    halo_alpha = int(70 + 60 * pulse)
    d = 40
    with acquired((d, d)) as halo:
        pygame.draw.circle(
            halo,
            with_alpha(PALETTE.primary, halo_alpha // 2),
            (d // 2, d // 2),
            d // 2,
        )
        pygame.draw.circle(
            halo,
            with_alpha(PALETTE.primary, halo_alpha),
            (d // 2, d // 2),
            d // 2 - 4,
            1,
        )
        surface.blit(halo, (edge_x - d // 2, edge_y - d // 2))

    # Chevron pointing in the rotation direction.
    size = 9
    color = lighten(PALETTE.primary, 0.15)
    if info.rotation is Direction.E:
        pts = [(edge_x - size, edge_y - size), (edge_x + size, edge_y), (edge_x - size, edge_y + size)]
    elif info.rotation is Direction.W:
        pts = [(edge_x + size, edge_y - size), (edge_x - size, edge_y), (edge_x + size, edge_y + size)]
    elif info.rotation is Direction.N:
        pts = [(edge_x - size, edge_y + size), (edge_x, edge_y - size), (edge_x + size, edge_y + size)]
    else:  # S
        pts = [(edge_x - size, edge_y - size), (edge_x, edge_y + size), (edge_x + size, edge_y - size)]
    pygame.draw.polygon(surface, color, pts)
    pygame.draw.polygon(surface, PALETTE.bg_deep, pts, 1)


def _draw_mirror_glyph(
    surface: pygame.Surface,
    grid: pygame.Rect,
    info: StructureInfo,
    time: float,
) -> None:
    """Two-stroke reflection arrow drawn on the side opposite the chevron.

    Placed on the "back" edge of the building (opposite the facing
    direction) so it never overlaps the rotation chevron. Uses the same
    breathing-halo idiom for visual consistency.
    """
    back = info.rotation.opposite
    dx, dy = back.vector
    edge_x = grid.centerx + int(dx * (grid.w / 2 - 14))
    edge_y = grid.centery + int(dy * (grid.h / 2 - 14))

    pulse = 0.5 + 0.5 * math.sin(time * 2.5 + math.pi)
    halo_alpha = int(70 + 60 * pulse)
    d = 40
    with acquired((d, d)) as halo:
        pygame.draw.circle(
            halo,
            with_alpha(PALETTE.secondary, halo_alpha // 2),
            (d // 2, d // 2),
            d // 2,
        )
        pygame.draw.circle(
            halo,
            with_alpha(PALETTE.secondary, halo_alpha),
            (d // 2, d // 2),
            d // 2 - 4,
            1,
        )
        surface.blit(halo, (edge_x - d // 2, edge_y - d // 2))

    # Two arrowheads pointing away from each other along the axis
    # perpendicular to facing -- the "flip" axis.
    color = lighten(PALETTE.secondary, 0.2)
    # Perpendicular unit vector to facing.
    fx, fy = info.rotation.vector
    perp = (-fy, fx)
    s = 8
    ax = edge_x + perp[0] * 7
    ay = edge_y + perp[1] * 7
    bx = edge_x - perp[0] * 7
    by = edge_y - perp[1] * 7
    _arrowhead(surface, (ax, ay), perp, color, size=s)
    _arrowhead(surface, (bx, by), (-perp[0], -perp[1]), color, size=s)
    # Central divider line.
    pygame.draw.line(
        surface,
        with_alpha(PALETTE.bg_deep, 200),
        (edge_x + fx * 6, edge_y + fy * 6),
        (edge_x - fx * 6, edge_y - fy * 6),
        2,
    )


def _arrowhead(
    surface: pygame.Surface,
    tip: tuple[int, int],
    direction: tuple[int, int],
    color: tuple[int, int, int],
    *,
    size: int = 6,
) -> None:
    dx, dy = direction
    perp = (-dy, dx)
    back = (tip[0] - dx * size, tip[1] - dy * size)
    left = (back[0] + perp[0] * size // 2, back[1] + perp[1] * size // 2)
    right = (back[0] - perp[0] * size // 2, back[1] - perp[1] * size // 2)
    pygame.draw.polygon(surface, color, [tip, left, right])
    pygame.draw.polygon(surface, PALETTE.bg_deep, [tip, left, right], 1)


def _draw_port_marker(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    port_kind: PortKind,
    side: Direction,
    item_color: tuple[int, int, int],
    fill_frac: float,
    is_full: bool,
    is_hovered: bool,
    time: float,
) -> None:
    """Square port marker with fill ring + arrow + hover/full halos."""
    border = PALETTE.secondary if port_kind is PortKind.INPUT else PALETTE.primary

    # Hover halo (underlay).
    if is_hovered:
        halo_rect = rect.inflate(20, 20)
        with acquired(halo_rect.size) as halo:
            pygame.draw.rect(
                halo,
                with_alpha(item_color, 90),
                pygame.Rect(0, 0, halo_rect.w, halo_rect.h),
                border_radius=6,
            )
            pygame.draw.rect(
                halo,
                with_alpha(item_color, 160),
                pygame.Rect(0, 0, halo_rect.w, halo_rect.h),
                1,
                border_radius=6,
            )
            surface.blit(halo, halo_rect.topleft)

    # Full-state warning pulse overlay (outer).
    if is_full:
        pulse = 0.5 + 0.5 * math.sin(time * 6.0)
        warn_alpha = int(90 + 110 * pulse)
        warn_rect = rect.inflate(14, 14)
        with acquired(warn_rect.size) as warn:
            pygame.draw.rect(
                warn,
                with_alpha(PALETTE.warning, warn_alpha),
                pygame.Rect(0, 0, warn_rect.w, warn_rect.h),
                2,
                border_radius=3,
            )
            surface.blit(warn, warn_rect.topleft)

    # Body.
    body_rect = rect.inflate(6, 6) if is_hovered else rect
    beveled_panel(surface, body_rect, fill=darken(item_color, 0.25), border=border)
    inner = body_rect.inflate(-8, -8)
    pygame.draw.rect(surface, item_color, inner)
    pygame.draw.rect(surface, lighten(item_color, 0.25), inner, 1)

    # Fill ring (animated) around the marker.
    _draw_fill_ring(
        surface, body_rect, frac=fill_frac, color=item_color, is_full=is_full, time=time
    )

    # Directional arrow (input = toward cell, output = away from cell).
    _draw_port_arrow(surface, body_rect, side, port_kind)


def _draw_fill_ring(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    frac: float,
    color: tuple[int, int, int],
    is_full: bool,
    time: float,
) -> None:
    frac = max(0.0, min(1.0, frac))
    if frac <= 0.005:
        return
    ring_rect = rect.inflate(12, 12)
    with acquired(ring_rect.size) as layer:
        cx, cy = ring_rect.w // 2, ring_rect.h // 2
        radius = min(cx, cy) - 1
        # Faint track.
        pygame.draw.circle(layer, with_alpha(color, 40), (cx, cy), radius, 2)
        # Animated arc from top (-pi/2) clockwise.
        start = -math.pi / 2
        end = start + 2 * math.pi * frac
        ring_color = with_alpha(color, 220)
        if is_full:
            pulse = 0.5 + 0.5 * math.sin(time * 6.0)
            ring_color = with_alpha(
                lighten(color, 0.15 + 0.15 * pulse), int(230 + 25 * pulse)
            )
        pygame.draw.arc(
            layer,
            ring_color,
            pygame.Rect(1, 1, ring_rect.w - 2, ring_rect.h - 2),
            -end, -start,  # pygame arc uses math angles (CCW, so we swap)
            2,
        )
        surface.blit(layer, ring_rect.topleft)


def _draw_port_arrow(
    surface: pygame.Surface,
    rect: pygame.Rect,
    side: Direction,
    port_kind: PortKind,
) -> None:
    """Tiny triangle arrow that shows flow direction at the marker."""
    cx, cy = rect.center
    size = 5

    # Outward = away from the building cell (along ``side``).
    if side is Direction.E:
        outward = (1, 0)
    elif side is Direction.W:
        outward = (-1, 0)
    elif side is Direction.N:
        outward = (0, -1)
    else:
        outward = (0, 1)

    dx, dy = outward
    if port_kind is PortKind.INPUT:
        dx, dy = -dx, -dy  # arrow points INTO the cell

    # Perpendicular for the triangle base.
    px, py = -dy, dx
    tip = (cx + dx * size, cy + dy * size)
    base_a = (cx - dx * size + px * size, cy - dy * size + py * size)
    base_b = (cx - dx * size - px * size, cy - dy * size - py * size)
    pygame.draw.polygon(surface, PALETTE.text_strong, [tip, base_a, base_b])
