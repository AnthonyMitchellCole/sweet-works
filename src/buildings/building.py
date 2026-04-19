"""Base class for all buildings (multi-cell, with typed ports)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design.palette import PALETTE
from ..items.item_type import EMPTY_ID
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
    sprite_base: str = "building_base"

    def __init__(
        self,
        origin: Coord,
        rotation: Direction = Direction.E,
        *,
        sprite_base: str | None = None,
    ) -> None:
        self.origin: Coord = origin
        self.rotation: Direction = rotation
        self.inputs: list[Port] = []
        self.outputs: list[Port] = []
        if sprite_base is not None:
            self.sprite_base = sprite_base
        self._configure_ports()

    # -- animation state hooks --------------------------------------------

    def is_active(self) -> bool:
        """Return ``True`` while the building's animated "active" phase should play."""
        return False

    def anim_progress(self) -> float:
        """Normalised 0..1 animation position while active."""
        return 0.0

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

    def tick(self, world: World) -> None:  # pragma: no cover - overridden
        pass

    def _drain_output_port(self, port: Port, world: World) -> None:
        """Try to push the next buffered item onto the adjacent belt."""
        if port.is_empty():
            return
        dx, dy = port.side.vector
        next_cell = (port.cell[0] + dx, port.cell[1] + dy)
        network = world.belt_network
        if network is None:
            return
        tid = port.peek_id()
        if tid == EMPTY_ID:
            return
        if network.accept(next_cell, tid):
            port.pop_id()

    # -- rendering ---------------------------------------------------------

    def render(
        self,
        surface: pygame.Surface,
        camera: Camera,
        assets: AssetLoader,
        time: float,
        sim_alpha: float,
    ) -> None:
        phase, frame = self._resolve_anim_frame()
        x, y = camera.world_to_screen(
            self.origin[0] * config.TILE, self.origin[1] * config.TILE
        )
        fw, fh = self.footprint

        sprite = self._resolve_structure_sprite(assets, phase, frame, camera.zoom)
        if sprite is not None:
            surface.blit(sprite, (x, y))
            port_size = sprite.get_width() // max(1, fw)
        else:
            base = assets.sprite_scaled("building_base", camera.zoom)
            port_size = base.get_width()
            for dy in range(fh):
                for dx in range(fw):
                    bx, by = camera.world_to_screen(
                        (self.origin[0] + dx) * config.TILE,
                        (self.origin[1] + dy) * config.TILE,
                    )
                    surface.blit(base, (bx, by))

        self._render_ports(surface, camera, port_size)

    def _resolve_anim_frame(self) -> tuple[str, int]:
        if self.is_active():
            frames = max(1, config.STRUCTURE_FRAMES)
            return "active", int(self.anim_progress() * frames) % frames
        return "idle", 0

    def _resolve_structure_sprite(
        self,
        assets: AssetLoader,
        phase: str,
        frame: int,
        zoom: float,
    ) -> pygame.Surface | None:
        if not self.sprite_base or self.sprite_base == "building_base":
            return None
        key = f"{self.sprite_base}_{phase}_f{frame}"
        try:
            return assets.sprite_scaled(key, zoom)
        except FileNotFoundError:
            return None

    def _render_ports(self, surface: pygame.Surface, camera: Camera, size: int) -> None:
        for port in self.inputs:
            self._render_port_marker(surface, camera, port, PALETTE.secondary, size)
        for port in self.outputs:
            self._render_port_marker(surface, camera, port, PALETTE.primary, size)

    def _render_port_marker(
        self,
        surface: pygame.Surface,
        camera: Camera,
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
