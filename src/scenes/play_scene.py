"""Play scene: wires world, renderer, camera, HUD, toolbar and placement cursor."""

from __future__ import annotations

import pygame

from ..belts.belt import ConveyorBelt
from ..belts.belt_network import BeltNetwork
from ..buildings.registry import BUILDINGS, BuildingPrefab
from ..core import config
from ..design.palette import PALETTE
from ..design.typography import TYPE
from ..items.registry import ITEMS
from ..rendering.renderer import Renderer
from ..ui.cursor import PlacementCursor
from ..ui.hud import HUD
from ..ui.toolbar import Toolbar, ToolSlot
from ..world.camera import Camera
from ..world.direction import Direction
from ..world.world import World
from .scene import Scene


PAN_KEYS = {
    pygame.K_w: (0, -1),
    pygame.K_a: (-1, 0),
    pygame.K_s: (0, 1),
    pygame.K_d: (1, 0),
    pygame.K_UP: (0, -1),
    pygame.K_LEFT: (-1, 0),
    pygame.K_DOWN: (0, 1),
    pygame.K_RIGHT: (1, 0),
}


class PlayScene(Scene):
    def __init__(self) -> None:
        super().__init__()
        self.world: World | None = None
        self.camera: Camera | None = None
        self.renderer: Renderer | None = None
        self.hud: HUD | None = None
        self.toolbar: Toolbar | None = None
        self.cursor: PlacementCursor | None = None

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self) -> None:
        assert self.game is not None
        self.world = World(self.game.events)
        self.world.belt_network = BeltNetwork()
        self.camera = Camera(config.WINDOW)
        self.renderer = Renderer(self.game.assets)
        self.hud = HUD(self.game.assets, self.game.events)
        self.toolbar = Toolbar(self.game.assets, on_select=self._on_tool_select)
        self.cursor = PlacementCursor(self.game.assets)
        self.cursor.set_tool(self.toolbar.selected_slot())

        self.camera.set_center(6 * config.TILE, 4 * config.TILE)

        self._build_demo_factory()

    def on_exit(self) -> None:
        if self.hud is not None:
            self.hud.close()

    # -- events ------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        assert self.game is not None
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.game.quit()
            elif event.key == pygame.K_r and self.cursor is not None:
                self.cursor.rotate_cw()
            elif self.toolbar is not None and self.toolbar.handle_hotkey(event.key):
                pass
        elif event.type == pygame.MOUSEWHEEL and self.camera is not None:
            factor = 1.1 if event.y > 0 else (1 / 1.1)
            self.camera.zoom_by(factor, around_screen=pygame.mouse.get_pos())

    # -- update ------------------------------------------------------------

    def update(self, dt: float, sim_ticks: int, sim_alpha: float) -> None:
        assert self.game is not None
        assert self.world is not None
        assert self.camera is not None
        assert self.toolbar is not None
        assert self.cursor is not None
        assert self.hud is not None

        self._pan_camera(dt)
        self.camera.update(dt)

        mouse_pos = self.game.input.mouse_pos
        over_ui = self._point_over_ui(mouse_pos)

        self.toolbar.update(
            dt,
            mouse_pos,
            self.game.input.mouse(1),
            self.game.input.mouse_released(1),
        )
        self.cursor.set_tool(self.toolbar.selected_slot())

        tile_pos = self.camera.screen_to_tile(*mouse_pos)
        self.cursor.update(dt, tile_pos)

        if not over_ui:
            if self.game.input.mouse_pressed(1):
                self._place(tile_pos)
            if self.game.input.mouse_pressed(3):
                self.world.remove_at(tile_pos)

        for _ in range(sim_ticks):
            self.world.tick()

        self.world.advance_time(dt)
        self.hud.update(dt)

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        assert self.world is not None
        assert self.camera is not None
        assert self.renderer is not None
        assert self.toolbar is not None
        assert self.cursor is not None
        assert self.hud is not None
        assert self.game is not None

        surface.fill(PALETTE.bg_deep)
        self.renderer.draw_world(
            surface, self.world, self.camera, self.world.time, self.game.clock.sim_alpha
        )
        self.cursor.render(surface, self.camera)
        self.hud.render(surface, self.game.clock.fps)
        self.toolbar.render(surface)
        self._render_hint(surface)

    # -- helpers -----------------------------------------------------------

    def _pan_camera(self, dt: float) -> None:
        assert self.game is not None
        assert self.camera is not None
        dx = dy = 0
        for key, (kx, ky) in PAN_KEYS.items():
            if self.game.input.key(key):
                dx += kx
                dy += ky
        if dx == 0 and dy == 0:
            return
        mag = (dx * dx + dy * dy) ** 0.5
        nx, ny = dx / mag, dy / mag
        speed = config.CAMERA_PAN_SPEED * dt / max(0.5, self.camera.zoom)
        self.camera.pan(nx * speed, ny * speed)

    def _on_tool_select(self, slot: ToolSlot) -> None:
        if self.cursor is not None:
            self.cursor.set_tool(slot)

    def _point_over_ui(self, pos: tuple[int, int]) -> bool:
        if self.toolbar is None:
            return False
        for w in self.toolbar._widgets:  # noqa: SLF001 - scene owns toolbar
            if w.rect.collidepoint(pos):
                return True
        # HUD top bar (padding + 48 h)
        if pos[1] < 16 + 48 + 8:
            return True
        return False

    def _place(self, tile_pos: tuple[int, int]) -> None:
        assert self.world is not None
        assert self.cursor is not None
        slot = self.cursor.tool
        if slot is None:
            return
        if slot.id == "belt":
            if self.world.is_free(tile_pos):
                belt = ConveyorBelt(tile_pos, self.cursor.rotation)
                self.world.place_tile(belt)
            return
        prefab: BuildingPrefab | None = slot.prefab
        if prefab is None:
            return
        building = prefab.factory(tile_pos, self.cursor.rotation)
        self.world.place_building(building)

    def _render_hint(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        hint = self.game.assets.render_text(
            "WASD pan  -  scroll zoom  -  1-5 tool  -  R rotate  -  LMB place  -  RMB delete",
            TYPE.caption,
            PALETTE.muted,
        )
        surface.blit(
            hint,
            (surface.get_width() // 2 - hint.get_width() // 2, surface.get_height() - 24),
        )

    # -- demo factory ------------------------------------------------------

    def _build_demo_factory(self) -> None:
        assert self.world is not None

        # Iron miner at (0,3) facing east -> belt row -> assembler_plate at (6,3)
        iron_miner = BUILDINGS.miner_iron.factory((0, 3), Direction.E)
        self.world.place_building(iron_miner)
        for x in range(1, 6):
            self.world.place_tile(ConveyorBelt((x, 3), Direction.E))

        # Plate assembler: 2x2 at (6,3). Input W at (6,3); Output E at (7,3).
        plate_asm = BUILDINGS.assembler_plate.factory((6, 3), Direction.E)
        self.world.place_building(plate_asm)

        # Belt chain from plate output east to gear assembler at (14,3)
        for x in range(8, 14):
            self.world.place_tile(ConveyorBelt((x, 3), Direction.E))

        gear_asm = BUILDINGS.assembler_gear.factory((14, 3), Direction.E)
        self.world.place_building(gear_asm)
