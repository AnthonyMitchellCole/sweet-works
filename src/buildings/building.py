"""Base class for all buildings (multi-cell, with typed ports)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design.palette import PALETTE
from ..world.direction import Direction
from ..world.tile import Coord
from .port import Port, PortKind

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera
    from ..world.world import World


class Building:
    """Abstract building.

    Subclasses declare their footprint and port layout, then implement `tick`.
    """

    name: str = "building"
    footprint: tuple[int, int] = (1, 1)

    def __init__(self, origin: Coord, rotation: Direction = Direction.E) -> None:
        self.origin: Coord = origin
        self.rotation: Direction = rotation
        self.inputs: list[Port] = []
        self.outputs: list[Port] = []
        self._configure_ports()

    # -- port layout -------------------------------------------------------

    def _configure_ports(self) -> None:
        """Override to declare input/output ports relative to `self.origin`."""

    def _add_port(
        self,
        kind: PortKind,
        side: Direction,
        cell_offset: Coord = (0, 0),
        **kwargs,
    ) -> Port:
        ox, oy = self.origin
        dx, dy = cell_offset
        port = Port(kind=kind, side=side, cell=(ox + dx, oy + dy), **kwargs)
        (self.inputs if kind is PortKind.INPUT else self.outputs).append(port)
        return port

    def input_port_at(self, cell: Coord, side: Direction) -> Port | None:
        for p in self.inputs:
            if p.cell == cell and p.side == side:
                return p
        return None

    def output_port_at(self, cell: Coord, side: Direction) -> Port | None:
        for p in self.outputs:
            if p.cell == cell and p.side == side:
                return p
        return None

    # -- simulation --------------------------------------------------------

    def tick(self, world: "World") -> None:  # pragma: no cover - overridden
        pass

    def _drain_output_port(self, port: Port, world: "World") -> None:
        """Try to push the next buffered item onto the adjacent belt."""
        if not port.buffer:
            return
        from ..belts.belt import ConveyorBelt  # local to avoid cycle

        dx, dy = port.side.vector
        next_cell = (port.cell[0] + dx, port.cell[1] + dy)
        target = world.tile_at(next_cell)
        if isinstance(target, ConveyorBelt):
            item = port.buffer[0]
            if target.accept(item):
                port.buffer.popleft()

    # -- rendering ---------------------------------------------------------

    def render(
        self,
        surface: pygame.Surface,
        camera: "Camera",
        assets: "AssetLoader",
        time: float,
        sim_alpha: float,
    ) -> None:
        w, h = self.footprint
        base = assets.sprite("building_base")
        size = int(config.TILE * camera.zoom)
        for dy in range(h):
            for dx in range(w):
                x, y = camera.world_to_screen(
                    (self.origin[0] + dx) * config.TILE,
                    (self.origin[1] + dy) * config.TILE,
                )
                tile = base
                if camera.zoom != 1.0:
                    tile = pygame.transform.scale(tile, (size, size))
                surface.blit(tile, (x, y))
        self._render_accent(surface, camera)
        self._render_ports(surface, camera)

    def _render_accent(self, surface: pygame.Surface, camera: "Camera") -> None:
        w, h = self.footprint
        ox, oy = self.origin
        size = int(config.TILE * camera.zoom)
        x, y = camera.world_to_screen(ox * config.TILE, oy * config.TILE)
        rect = pygame.Rect(
            x + size // 4, y + size // 4, size * w - size // 2, size * h - size // 2
        )
        pygame.draw.rect(surface, PALETTE.surface, rect)
        pygame.draw.rect(surface, PALETTE.line, rect, 1)

    def _render_ports(self, surface: pygame.Surface, camera: "Camera") -> None:
        size = int(config.TILE * camera.zoom)
        for port in self.inputs:
            self._render_port_marker(surface, camera, port, PALETTE.secondary, size)
        for port in self.outputs:
            self._render_port_marker(surface, camera, port, PALETTE.primary, size)

    def _render_port_marker(
        self,
        surface: pygame.Surface,
        camera: "Camera",
        port: Port,
        color,
        size: int,
    ) -> None:
        cx_world = port.cell[0] * config.TILE + config.TILE // 2
        cy_world = port.cell[1] * config.TILE + config.TILE // 2
        cx, cy = camera.world_to_screen(cx_world, cy_world)
        dx, dy = port.side.vector
        half = size // 2
        px = cx + int(dx * (half - 3))
        py = cy + int(dy * (half - 3))
        marker = pygame.Rect(0, 0, max(4, size // 8), max(4, size // 8))
        marker.center = (px, py)
        pygame.draw.rect(surface, color, marker)
