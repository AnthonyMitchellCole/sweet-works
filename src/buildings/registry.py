"""Named building prefabs, used by the toolbar and scenes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..items.registry import ITEMS
from ..world.direction import Direction
from ..world.tile import Coord
from .assembler import Assembler, Recipe
from .building import Building
from .miner import Miner

BuildingFactory = Callable[[Coord, Direction], Building]


@dataclass(frozen=True)
class BuildingPrefab:
    id: str
    name: str
    footprint: tuple[int, int]
    factory: BuildingFactory
    sprite_base: str = "building_base"


def _miner_iron(origin: Coord, rotation: Direction) -> Building:
    return Miner(
        origin,
        ITEMS.iron,
        period_ticks=10,
        rotation=rotation,
        sprite_base="structure_miner_iron",
    )


def _miner_copper(origin: Coord, rotation: Direction) -> Building:
    return Miner(
        origin,
        ITEMS.copper,
        period_ticks=10,
        rotation=rotation,
        sprite_base="structure_miner_copper",
    )


def _miner_coal(origin: Coord, rotation: Direction) -> Building:
    return Miner(
        origin,
        ITEMS.coal,
        period_ticks=12,
        rotation=rotation,
        sprite_base="structure_miner_coal",
    )


_RECIPE_PLATE = Recipe(
    inputs=((ITEMS.iron, 1),),
    outputs=((ITEMS.plate, 1),),
    ticks=20,
)

_RECIPE_GEAR = Recipe(
    inputs=((ITEMS.plate, 2),),
    outputs=((ITEMS.gear, 1),),
    ticks=30,
)


def _assembler_plate(origin: Coord, rotation: Direction) -> Building:
    return Assembler(origin, _RECIPE_PLATE, rotation, sprite_base="structure_assembler_plate")


def _assembler_gear(origin: Coord, rotation: Direction) -> Building:
    return Assembler(origin, _RECIPE_GEAR, rotation, sprite_base="structure_assembler_gear")


@dataclass(frozen=True)
class BuildingRegistry:
    miner_iron: BuildingPrefab = BuildingPrefab(
        "miner_iron", "Iron Miner", (1, 1), _miner_iron, sprite_base="structure_miner_iron"
    )
    miner_copper: BuildingPrefab = BuildingPrefab(
        "miner_copper", "Copper Miner", (1, 1), _miner_copper, sprite_base="structure_miner_copper"
    )
    miner_coal: BuildingPrefab = BuildingPrefab(
        "miner_coal", "Coal Miner", (1, 1), _miner_coal, sprite_base="structure_miner_coal"
    )
    assembler_plate: BuildingPrefab = BuildingPrefab(
        "assembler_plate",
        "Plate Assembler",
        (2, 2),
        _assembler_plate,
        sprite_base="structure_assembler_plate",
    )
    assembler_gear: BuildingPrefab = BuildingPrefab(
        "assembler_gear",
        "Gear Assembler",
        (2, 2),
        _assembler_gear,
        sprite_base="structure_assembler_gear",
    )

    def all(self) -> tuple[BuildingPrefab, ...]:
        return (
            self.miner_iron,
            self.miner_copper,
            self.miner_coal,
            self.assembler_plate,
            self.assembler_gear,
        )


BUILDINGS = BuildingRegistry()
