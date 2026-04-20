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


def _extractor_cocoa(origin: Coord, rotation: Direction) -> Building:
    return Miner(
        origin,
        ITEMS.cocoa_bean,
        period_ticks=10,
        rotation=rotation,
        sprite_base="structure_extractor_cocoa",
    )


def _extractor_sugar(origin: Coord, rotation: Direction) -> Building:
    return Miner(
        origin,
        ITEMS.sugar_crystal,
        period_ticks=10,
        rotation=rotation,
        sprite_base="structure_extractor_sugar",
    )


def _well_milk(origin: Coord, rotation: Direction) -> Building:
    return Miner(
        origin,
        ITEMS.milk,
        period_ticks=12,
        rotation=rotation,
        sprite_base="structure_well_milk",
    )


_RECIPE_CHOCOLATE = Recipe(
    inputs=((ITEMS.cocoa_bean, 1),),
    outputs=((ITEMS.chocolate, 1),),
    ticks=20,
)

_RECIPE_CARAMEL = Recipe(
    inputs=((ITEMS.sugar_crystal, 1), (ITEMS.milk, 1)),
    outputs=((ITEMS.caramel, 1),),
    ticks=20,
)

_RECIPE_CANDY = Recipe(
    inputs=((ITEMS.chocolate, 1), (ITEMS.caramel, 1)),
    outputs=((ITEMS.candy_bar, 1),),
    ticks=30,
)


def _mixer_chocolate(origin: Coord, rotation: Direction) -> Building:
    return Assembler(
        origin, _RECIPE_CHOCOLATE, rotation, sprite_base="structure_mixer_chocolate"
    )


def _pot_caramel(origin: Coord, rotation: Direction) -> Building:
    return Assembler(
        origin, _RECIPE_CARAMEL, rotation, sprite_base="structure_pot_caramel"
    )


def _wrapper_candy(origin: Coord, rotation: Direction) -> Building:
    return Assembler(
        origin, _RECIPE_CANDY, rotation, sprite_base="structure_wrapper_candy"
    )


@dataclass(frozen=True)
class BuildingRegistry:
    extractor_cocoa: BuildingPrefab = BuildingPrefab(
        "extractor_cocoa",
        "Cocoa Extractor",
        (1, 1),
        _extractor_cocoa,
        sprite_base="structure_extractor_cocoa",
    )
    extractor_sugar: BuildingPrefab = BuildingPrefab(
        "extractor_sugar",
        "Sugar Extractor",
        (1, 1),
        _extractor_sugar,
        sprite_base="structure_extractor_sugar",
    )
    well_milk: BuildingPrefab = BuildingPrefab(
        "well_milk",
        "Milk Well",
        (1, 1),
        _well_milk,
        sprite_base="structure_well_milk",
    )
    mixer_chocolate: BuildingPrefab = BuildingPrefab(
        "mixer_chocolate",
        "Chocolate Mixer",
        (2, 2),
        _mixer_chocolate,
        sprite_base="structure_mixer_chocolate",
    )
    pot_caramel: BuildingPrefab = BuildingPrefab(
        "pot_caramel",
        "Caramel Pot",
        (2, 2),
        _pot_caramel,
        sprite_base="structure_pot_caramel",
    )
    wrapper_candy: BuildingPrefab = BuildingPrefab(
        "wrapper_candy",
        "Candy Wrapper",
        (2, 2),
        _wrapper_candy,
        sprite_base="structure_wrapper_candy",
    )

    def all(self) -> tuple[BuildingPrefab, ...]:
        return (
            self.extractor_cocoa,
            self.extractor_sugar,
            self.well_milk,
            self.mixer_chocolate,
            self.pot_caramel,
            self.wrapper_candy,
        )


BUILDINGS = BuildingRegistry()
