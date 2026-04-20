"""Assembler: consumes from typed input ports and emits via an output port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..design.palette import PALETTE, darken, lighten
from ..items.item_type import ItemType
from ..world.direction import Direction
from ..world.tile import Coord
from .building import Building
from .port import Port, PortKind

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader
    from ..world.camera import Camera
    from ..world.world import World


@dataclass(frozen=True)
class Recipe:
    inputs: tuple[tuple[ItemType, int], ...]
    outputs: tuple[tuple[ItemType, int], ...]
    ticks: int = 30


@dataclass
class _Craft:
    remaining: int
    total: int

    @property
    def progress(self) -> float:
        return 1.0 - (self.remaining / self.total) if self.total > 0 else 0.0


class Assembler(Building):
    name = "assembler"
    footprint = (2, 2)

    def __init__(
        self,
        origin: Coord,
        recipe: Recipe,
        rotation: Direction = Direction.E,
        *,
        mirrored: bool = False,
        sprite_base: str | None = None,
    ) -> None:
        self.recipe = recipe
        self._craft: _Craft | None = None
        self._input_ports_by_type: dict[int, Port] = {}
        super().__init__(
            origin, rotation, mirrored=mirrored, sprite_base=sprite_base
        )

    # -- animation state hooks --------------------------------------------

    def is_active(self) -> bool:
        return self._craft is not None

    def anim_progress(self) -> float:
        return self.craft_progress

    # -- public introspection (UI) -----------------------------------------

    @property
    def is_crafting(self) -> bool:
        return self._craft is not None

    @property
    def craft_progress(self) -> float:
        return self._craft.progress if self._craft is not None else 0.0

    @property
    def craft_ticks(self) -> tuple[int, int]:
        if self._craft is None:
            return (0, 0)
        return (self._craft.total - self._craft.remaining, self._craft.total)

    def _configure_ports(self) -> None:
        # Canonical E-facing, un-mirrored frame: inputs live on the
        # local W edge (one per recipe row), outputs on the local E
        # edge at the top-right cell. The framework rotates / mirrors
        # these into world space.
        self._input_ports_by_type = {}
        for i, (item_type, _) in enumerate(self.recipe.inputs):
            port = self._add_local_port(
                PortKind.INPUT,
                side_local=Direction.W,
                cell_offset_local=(0, min(i, self.footprint[1] - 1)),
                filter=item_type,
                capacity=8,
            )
            self._input_ports_by_type[item_type.type_id] = port

        for item_type, _ in self.recipe.outputs:
            self._add_local_port(
                PortKind.OUTPUT,
                side_local=Direction.E,
                cell_offset_local=(self.footprint[0] - 1, 0),
                filter=item_type,
                capacity=8,
            )

    # -- tick --------------------------------------------------------------

    def tick(self, world: World) -> None:
        if self._craft is None:
            if self._can_start_craft():
                self._begin_craft()
        else:
            self._craft.remaining -= 1
            if self._craft.remaining <= 0:
                self._finish_craft(world)

        for port in self.outputs:
            self._drain_output_port(port, world)

    def _can_start_craft(self) -> bool:
        for item_type, qty in self.recipe.inputs:
            port = self._input_ports_by_type.get(item_type.type_id)
            if port is None or port.count_of_id(item_type.type_id) < qty:
                return False
        for item_type, _ in self.recipe.outputs:
            out = self._output_port_for(item_type)
            if out is None or out.is_full():
                return False
        return True

    def _begin_craft(self) -> None:
        for item_type, qty in self.recipe.inputs:
            port = self._input_ports_by_type[item_type.type_id]
            port.drain_of_id(item_type.type_id, qty)
        self._craft = _Craft(remaining=self.recipe.ticks, total=self.recipe.ticks)

    def _finish_craft(self, world: World) -> None:
        for item_type, qty in self.recipe.outputs:
            port = self._output_port_for(item_type)
            if port is None:
                continue
            for _ in range(qty):
                if not port.push_id(item_type.type_id):
                    break
                world.events.emit("item.produced", item_type)
        self._craft = None

    def _output_port_for(self, item_type: ItemType) -> Port | None:
        for p in self.outputs:
            if p.filter is item_type:
                return p
        return self.outputs[0] if self.outputs else None

    # -- render ------------------------------------------------------------

    def render(
        self,
        surface: pygame.Surface,
        camera: Camera,
        assets: AssetLoader,
        time: float,
        sim_alpha: float,
    ) -> None:
        super().render(surface, camera, assets, time, sim_alpha)
        self._render_progress(surface, camera, sim_alpha)

    def _render_progress(
        self, surface: pygame.Surface, camera: Camera, sim_alpha: float
    ) -> None:
        size = int(config.TILE * camera.zoom)
        x, y = camera.world_to_screen(
            self.origin[0] * config.TILE, self.origin[1] * config.TILE
        )
        w = size * self.footprint[0]
        bar_h = max(3, size // 12)
        bar_y = y - bar_h - 4

        bg_rect = pygame.Rect(x + 4, bar_y, w - 8, bar_h)
        pygame.draw.rect(surface, darken(PALETTE.bg_raised, 0.2), bg_rect)
        pygame.draw.rect(surface, PALETTE.line, bg_rect, 1)

        if self._craft is not None:
            progress = self._craft.progress
            smoothed = min(
                1.0,
                (self._craft.total - self._craft.remaining + sim_alpha)
                / max(1, self._craft.total),
            )
            fill_w = int((bg_rect.w - 2) * max(progress, smoothed))
            if fill_w > 0:
                fill_rect = pygame.Rect(bg_rect.x + 1, bg_rect.y + 1, fill_w, bar_h - 2)
                pygame.draw.rect(surface, PALETTE.primary, fill_rect)
                pygame.draw.rect(
                    surface,
                    lighten(PALETTE.primary, 0.25),
                    pygame.Rect(fill_rect.x, fill_rect.y, fill_rect.w, 1),
                )
