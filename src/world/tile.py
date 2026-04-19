"""Tile: a 1x1 occupant of a grid cell."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pygame

    from ..assets.loader import AssetLoader
    from .camera import Camera


Coord = tuple[int, int]


class Tile:
    """Base class for single-cell tile occupants (e.g. conveyor belts).

    Buildings with a larger footprint live alongside (not inside) the grid;
    the grid only stores tile-sized occupants.
    """

    def __init__(self, pos: Coord) -> None:
        self.pos: Coord = pos

    # -- lifecycle ---------------------------------------------------------

    def tick(self) -> None:
        """One fixed simulation step."""

    def render(
        self,
        surface: pygame.Surface,
        camera: Camera,
        assets: AssetLoader,
        time: float,
        sim_alpha: float,
    ) -> None:
        """Draw this tile; overridden per-subclass."""
