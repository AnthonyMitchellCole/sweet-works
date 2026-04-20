"""The world: grid of tiles + list of buildings, ticked every sim step."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..belts.belt import ConveyorBelt
from ..core.events import EventBus
from .grid import Grid
from .tile import Coord, Tile

if TYPE_CHECKING:
    from ..belts.network_soa import BeltNetworkSoA
    from ..buildings.building import Building
    from ..research.state import ResearchState


class World:
    def __init__(self, events: EventBus) -> None:
        self.events = events
        self.grid: Grid = Grid()
        self.buildings: list[Building] = []
        self._building_cells: dict[Coord, Building] = {}
        self.belt_network: BeltNetworkSoA | None = None
        self.time: float = 0.0
        # Research state is attached by ``PlayScene`` so the sim stays
        # agnostic when ``World`` is used outside gameplay (tests, demos).
        self.research: ResearchState | None = None

    # -- queries -----------------------------------------------------------

    def is_free(self, pos: Coord) -> bool:
        return pos not in self.grid and pos not in self._building_cells

    def building_at(self, pos: Coord) -> Building | None:
        return self._building_cells.get(pos)

    def tile_at(self, pos: Coord) -> Tile | None:
        return self.grid.get(pos)

    def building_cells(self, building: Building) -> Iterator[Coord]:
        ox, oy = building.origin
        w, h = building.footprint
        for dy in range(h):
            for dx in range(w):
                yield (ox + dx, oy + dy)

    # -- mutations ---------------------------------------------------------

    def place_tile(self, tile: Tile) -> bool:
        if not self.is_free(tile.pos):
            return False
        self.grid.set(tile)
        if isinstance(tile, ConveyorBelt) and self.belt_network is not None:
            self.belt_network.on_tile_placed(tile)
        return True

    def remove_tile(self, pos: Coord) -> Tile | None:
        tile = self.grid.remove(pos)
        if isinstance(tile, ConveyorBelt) and self.belt_network is not None:
            self.belt_network.on_tile_removed(pos)
        return tile

    def place_building(self, building: Building) -> bool:
        cells = list(self.building_cells(building))
        if any(not self.is_free(c) for c in cells):
            return False
        self.buildings.append(building)
        for c in cells:
            self._building_cells[c] = building
        if self.belt_network is not None:
            self.belt_network.on_building_changed()
        return True

    def remove_building(self, building: Building) -> None:
        if building not in self.buildings:
            return
        self.buildings.remove(building)
        for c in list(self.building_cells(building)):
            self._building_cells.pop(c, None)
        if self.belt_network is not None:
            self.belt_network.on_building_changed()

    def remove_at(self, pos: Coord) -> bool:
        tile = self.remove_tile(pos)
        if tile is not None:
            return True
        b = self.building_at(pos)
        if b is not None:
            self.remove_building(b)
            return True
        return False

    # -- simulation --------------------------------------------------------

    def tick(self) -> None:
        """One fixed step: flush belt edits -> buildings produce -> belts propagate.

        Flushing first lets buildings deposit onto belts that were placed
        earlier the same frame. The rebuild preserves items already on the
        belt so there is no visual reset on edits.
        """
        if self.belt_network is not None:
            self.belt_network.flush(self)
        for b in self.buildings:
            b.tick(self)
        if self.belt_network is not None:
            self.belt_network.tick(self)

    def advance_time(self, dt: float) -> None:
        self.time += dt
