"""Base class for all buildings (multi-cell, with typed ports).

Every building carries a ``rotation`` (one of :class:`Direction`) and a
``mirrored`` flag. Subclasses declare their ports in a **local frame**
(authored as if the building faces :attr:`Direction.E`, un-mirrored)
via :meth:`Building._add_local_port`; the framework resolves those to
world-space ``Port`` records under the live transform pair. Rotating or
mirroring a placed building re-runs port resolution and flushes any
stranded items back into the belt network, so the simulation stays
consistent with what the UI is drawing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design.palette import PALETTE
from ..items.item_type import EMPTY_ID
from ..world.direction import (
    Direction,
    resolve_local_port,
)
from ..world.tile import Coord
from .port import Port, PortKind

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera
    from ..world.world import World


class Building:
    """Abstract building.

    Subclasses declare their footprint and port layout, then implement
    :meth:`tick`. Ports are authored in the local (E-facing,
    un-mirrored) frame via :meth:`_add_local_port` so rotation + mirror
    transforms flow through the framework.
    """

    name: str = "building"
    footprint: tuple[int, int] = (1, 1)
    sprite_base: str = "building_base"

    def __init__(
        self,
        origin: Coord,
        rotation: Direction = Direction.E,
        *,
        mirrored: bool = False,
        sprite_base: str | None = None,
    ) -> None:
        self.origin: Coord = origin
        self.rotation: Direction = rotation
        self.mirrored: bool = bool(mirrored)
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
        """Override to declare input/output ports in the local (E-facing) frame."""

    def _add_local_port(
        self,
        kind: PortKind,
        side_local: Direction,
        cell_offset_local: Coord = (0, 0),
        **kwargs,
    ) -> Port:
        """Declare a port in the building-local (E-facing, un-mirrored) frame."""
        side, cell_offset = resolve_local_port(
            side_local,
            cell_offset_local,
            self.rotation,
            self.mirrored,
            self.footprint,
        )
        ox, oy = self.origin
        world_cell = (ox + cell_offset[0], oy + cell_offset[1])
        port = Port(kind=kind, side=side, cell=world_cell, **kwargs)
        (self.inputs if kind is PortKind.INPUT else self.outputs).append(port)
        return port

    def _add_port(
        self,
        kind: PortKind,
        side: Direction,
        cell_offset: Coord = (0, 0),
        **kwargs,
    ) -> Port:
        """Legacy absolute-side port helper.

        Kept as a thin pass-through so any external subclasses that
        author ports in world space continue to work. All in-tree
        buildings use :meth:`_add_local_port` instead.
        """
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

    # -- live transforms (rotation / mirror while placed) ------------------

    def rotate_cw(self, *, world: World | None = None) -> None:
        """Rotate the building 90 degrees clockwise in place.

        Port buffers are drained (best-effort) onto the belt network
        before the ports are re-resolved, so no items are stranded on
        the old output side.
        """
        self._drain_ports_to_network(world)
        self.rotation = self.rotation.rotate_cw()
        self._reconfigure_ports()
        self._notify_topology(world)

    def toggle_mirror(self, *, world: World | None = None) -> None:
        """Flip the building's port layout across its facing axis."""
        self._drain_ports_to_network(world)
        self.mirrored = not self.mirrored
        self._reconfigure_ports()
        self._notify_topology(world)

    def _reconfigure_ports(self) -> None:
        self.inputs = []
        self.outputs = []
        self._configure_ports()

    def _drain_ports_to_network(self, world: World | None) -> None:
        """Push buffered output items onto the belt network, drop inputs.

        This is best-effort: items that can't be pushed onto an adjacent
        belt are simply discarded (they'd be discarded anyway since the
        port is about to move). Matches the forgiving "never strand
        items on rotate" feel of placement FX.
        """
        if world is None or world.belt_network is None:
            return
        net = world.belt_network
        for port in self.outputs:
            while not port.is_empty():
                tid = port.peek_id()
                if tid == EMPTY_ID:
                    port.pop_id()
                    continue
                dx, dy = port.side.vector
                adj = (port.cell[0] + dx, port.cell[1] + dy)
                if net.accept(adj, tid):
                    port.pop_id()
                else:
                    break

    def _notify_topology(self, world: World | None) -> None:
        if world is not None and world.belt_network is not None:
            world.belt_network.on_building_changed()

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
            return assets.structure_sprite_oriented(
                key, self.rotation, self.mirrored, zoom
            )
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
