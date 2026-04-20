"""Play scene: wires world, renderer, camera, HUD, toolbar and placement cursor."""

from __future__ import annotations

import pygame

from ..audio.sfx import SFX
from ..belts.belt import ConveyorBelt
from ..belts.network_soa import BeltNetworkSoA
from ..buildings.building import Building
from ..buildings.registry import BUILDINGS, BuildingPrefab
from ..core import config
from ..core.perf import PERF, timed
from ..design.palette import PALETTE
from ..design.typography import TYPE
from ..rendering.animation import AnimValue
from ..rendering.renderer import Renderer
from ..research.state import ResearchState
from ..ui import info as info_mod
from ..ui.cursor import PlacementCursor
from ..ui.drag_pan import DragPanController
from ..ui.hover_highlight import draw_hover_brackets
from ..ui.hud import HUD
from ..ui.perf_hud import PerfHUD
from ..ui.placement_fx import PlacementFx
from ..ui.sprite_studio import SpriteStudio
from ..ui.structure_menu import StructureMenu
from ..ui.toolbar import Toolbar, ToolSlot
from ..ui.tooltip import WorldTooltip
from ..world.camera import Camera
from ..world.direction import Direction
from ..world.world import World
from .research_scene import ResearchScene
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
        self.perf_hud: PerfHUD | None = None
        self.toolbar: Toolbar | None = None
        self.cursor: PlacementCursor | None = None
        self.tooltip: WorldTooltip | None = None
        self.menu: StructureMenu | None = None
        self.studio: SpriteStudio | None = None
        self.fx: PlacementFx | None = None
        self.research: ResearchState | None = None

        # Hover state and fade
        self._hover_building: Building | None = None
        self._hover_belt: ConveyorBelt | None = None
        self._hover_origin: tuple[int, int] | None = None
        self._hover_footprint: tuple[int, int] = (1, 1)
        self._hover_strength = AnimValue(value=0.0, target=0.0, speed=14.0)

        self._drag_pan = DragPanController()
        self._unsub_research: object = None

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self) -> None:
        assert self.game is not None
        window_size = self.game.window_size
        self.world = World(self.game.events)
        self.world.belt_network = BeltNetworkSoA()
        self.research = ResearchState(self.game.events)
        self.world.research = self.research
        # Re-apply port capacity bumps to every assembler when research
        # changes; placement-time sizing is handled by ``_configure_ports``.
        self._unsub_research = self.game.events.on(
            "research.changed",
            lambda **_: self._apply_research_capacity(),
        )
        self.camera = Camera(window_size)
        self.renderer = Renderer(self.game.assets)
        self.hud = HUD(
            self.game.assets,
            self.game.events,
            on_open_research=self._open_research_tree,
        )
        self.perf_hud = PerfHUD(self.game.assets)
        self.toolbar = Toolbar(
            self.game.assets,
            on_select=self._on_tool_select,
            window_size=window_size,
            research=self.research,
            events=self.game.events,
        )
        self.cursor = PlacementCursor(self.game.assets)
        self.cursor.set_tool(self.toolbar.selected_slot())
        self.tooltip = WorldTooltip(self.game.assets)
        self.menu = StructureMenu(self.game.assets)
        self.menu.attach_world(self.world)
        self.menu.layout(window_size)
        self.studio = SpriteStudio(self.game.assets)
        self.studio.layout(window_size)
        self.fx = PlacementFx()

        self.camera.set_center(6 * config.TILE, 4 * config.TILE)

        self._build_demo_factory()
        # Fold demo placements into the SoA before the first tick.
        self.world.belt_network.rebuild(self.world)

        PERF.reset()

    def on_exit(self) -> None:
        if self.hud is not None:
            self.hud.close()
        self._drag_pan.release()
        if self._unsub_research is not None:
            try:
                self._unsub_research()
            except Exception:
                pass
            self._unsub_research = None

    def on_resize(self, size: tuple[int, int]) -> None:
        if self.camera is not None:
            self.camera.resize(size)
        if self.toolbar is not None:
            self.toolbar.layout(size)
        if self.menu is not None:
            self.menu.layout(size)
        if self.studio is not None:
            self.studio.layout(size)

    # -- events ------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        assert self.game is not None
        # The Sprite Studio takes priority so its clicks never leak to
        # the world or the structure menu beneath it.
        if self.studio is not None and self.studio.handle_event(event):
            return
        # Let the structure menu intercept ESC / its own keys first.
        if self.menu is not None and self.menu.handle_event(event):
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                from .menu_scene import MenuScene

                SFX.play("ui.close")
                self.game.replace_scene(MenuScene())
            elif event.key == pygame.K_TAB:
                self._open_research_tree()
            elif event.key == pygame.K_r and self.cursor is not None:
                self._rotate_at_cursor()
            elif event.key == pygame.K_t and self.cursor is not None:
                self._mirror_at_cursor()
            elif event.key == pygame.K_F3 and self.perf_hud is not None:
                self.perf_hud.toggle()
            elif event.key == pygame.K_F4 and self.studio is not None:
                self.studio.toggle()
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
        assert self.tooltip is not None
        assert self.menu is not None

        self._drag_pan.update(dt, self.game.input, self.camera)
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
        self.toolbar.set_transform(self.cursor.rotation, self.cursor.mirrored)

        tile_pos = self.camera.screen_to_tile(*mouse_pos)

        tool = self.toolbar.selected_slot()
        is_pointer = tool.id == "pointer"
        is_valid = is_pointer or self._footprint_is_free(tile_pos)
        self.cursor.update(dt, tile_pos, is_valid=is_valid)
        mods = pygame.key.get_mods()
        alt_held = bool(mods & pygame.KMOD_ALT)

        # Resolve what's under the cursor (building first; else belt/tile).
        self._refresh_hover(tile_pos, over_ui)

        # Feed the tooltip. Always on in pointer mode; Alt otherwise.
        show_tooltip = (is_pointer or alt_held) and not over_ui
        tip_info = None
        if show_tooltip:
            if self._hover_building is not None:
                tip_info = info_mod.for_building(self._hover_building, self.world)
            elif self._hover_belt is not None:
                tip_info = info_mod.for_belt(
                    self._hover_belt, self.world.belt_network
                )
        self.tooltip.set(tip_info, mouse_pos, avoid=self._toolbar_avoid_rect())
        self.tooltip.update(dt)

        # Fade the hover brackets based on whether we have a highlight target.
        target_strength = 1.0 if (tip_info is not None) else 0.0
        self._hover_strength.to(target_strength)
        self._hover_strength.update(dt)

        # Structure menu update (uses live building reference).
        self.menu.update(
            dt,
            mouse_pos,
            self.game.input.mouse(1),
            self.game.input.mouse_released(1),
        )

        # Sprite Studio update (F4 overlay).
        if self.studio is not None:
            self.studio.update(
                dt,
                mouse_pos,
                self.game.input.mouse(1),
                self.game.input.mouse_released(1),
            )

        studio_open = self.studio is not None and self.studio.is_open

        # LMB/RMB dispatch is suppressed while middle-mouse panning is active,
        # or while the studio is open (otherwise clicks beneath it would
        # place/delete buildings in the world).
        if not over_ui and not self._drag_pan.active and not studio_open:
            if self.game.input.mouse_pressed(1):
                self._on_lmb(tile_pos, is_pointer)
            if self.game.input.mouse_pressed(3) and not is_pointer:
                self._on_rmb(tile_pos)
            # Secondary mouse bindings: X1 = rotate, X2 = mirror.
            if self.game.input.mouse_pressed(pygame.BUTTON_X1):
                self._rotate_at_cursor()
            if self.game.input.mouse_pressed(pygame.BUTTON_X2):
                self._mirror_at_cursor()

        for _ in range(sim_ticks):
            with timed(PERF.tick):
                self.world.tick()

        self.world.advance_time(dt)
        # HUD needs mouse state so its research-tree button can hit-test.
        # Suppress button dispatch while the studio is open so its
        # overlay clicks never bleed through the HUD beneath.
        hud_mouse_down = self.game.input.mouse(1) and not studio_open
        hud_mouse_released = self.game.input.mouse_released(1) and not studio_open
        self.hud.update(
            dt,
            mouse_pos,
            self.world.time,
            mouse_down=hud_mouse_down,
            mouse_released=hud_mouse_released,
        )
        self.hud.set_transform(self.cursor.rotation, self.cursor.mirrored)

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        assert self.world is not None
        assert self.camera is not None
        assert self.renderer is not None
        assert self.toolbar is not None
        assert self.cursor is not None
        assert self.hud is not None
        assert self.perf_hud is not None
        assert self.game is not None
        assert self.tooltip is not None
        assert self.menu is not None

        surface.fill(PALETTE.bg_deep)
        self.renderer.draw_world(
            surface, self.world, self.camera, self.world.time, self.game.clock.sim_alpha
        )

        if self.fx is not None:
            self.fx.render(surface, self.camera, self.world.time)

        self._render_hover_brackets(surface)

        self.cursor.render(surface, self.camera)
        self._drag_pan.render_indicator(
            surface, self.game.input.mouse_pos, self.world.time
        )
        self.hud.render(surface, self.game.clock.fps)
        self.toolbar.render(surface)
        self.menu.render(surface)
        self.tooltip.render(surface)

        snap = PERF.snapshot(fps=self.game.clock.fps)
        self.perf_hud.render(surface, snap)
        if self.studio is not None:
            self.studio.render(surface)
        if not (self.menu is not None and self.menu.is_open) and not (
            self.studio is not None and self.studio.is_open
        ):
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
        SFX.play("world.tool_select")

    def _open_research_tree(self) -> None:
        """Push the research-tree overlay onto the scene stack."""
        assert self.game is not None
        if self.research is None:
            return
        self._drag_pan.release()
        self.game.push_scene(ResearchScene(self.research))

    def _apply_research_capacity(self) -> None:
        """Resize assembler ports in response to a ``research.changed`` event.

        Only assemblers carry research-driven port capacity today; other
        buildings are no-ops. The world reference is looked up lazily so
        this stays safe if the hook fires after ``on_exit``.
        """
        if self.world is None:
            return
        for b in self.world.buildings:
            apply = getattr(b, "apply_port_capacity", None)
            if callable(apply):
                apply(self.world)

    def _rotate_at_cursor(self) -> None:
        """Rotate an existing building under the cursor, otherwise the ghost."""
        if self.cursor is None:
            return
        building = self._building_under_mouse()
        if building is not None:
            building.rotate_cw(world=self.world)
            if self.fx is not None and self.world is not None:
                self.fx.spawn_rotate(
                    building.origin,
                    building.footprint,
                    self.world.time,
                    PALETTE.primary,
                )
        else:
            self.cursor.rotate_cw()
        SFX.play("world.rotate")

    def _mirror_at_cursor(self) -> None:
        """Toggle mirror on the hovered building, otherwise on the ghost."""
        if self.cursor is None:
            return
        building = self._building_under_mouse()
        if building is not None:
            building.toggle_mirror(world=self.world)
            if self.fx is not None and self.world is not None:
                self.fx.spawn_mirror(
                    building.origin,
                    building.footprint,
                    self.world.time,
                    PALETTE.secondary,
                )
        else:
            self.cursor.mirror()
        SFX.play("world.mirror")

    def _building_under_mouse(self) -> Building | None:
        if self.world is None or self.camera is None or self.game is None:
            return None
        tile_pos = self.camera.screen_to_tile(*self.game.input.mouse_pos)
        if self._point_over_ui(self.game.input.mouse_pos):
            return None
        return self.world.building_at(tile_pos)

    def _footprint_is_free(self, origin: tuple[int, int]) -> bool:
        """True when the full footprint of the currently selected tool is free."""
        if self.world is None or self.cursor is None or self.cursor.tool is None:
            return False
        slot = self.cursor.tool
        if slot.id == "pointer":
            return True
        fw, fh = self.cursor.footprint()
        ox, oy = origin
        for dy in range(fh):
            for dx in range(fw):
                if not self.world.is_free((ox + dx, oy + dy)):
                    return False
        return True

    def _point_over_ui(self, pos: tuple[int, int]) -> bool:
        if self.toolbar is None:
            return False
        for w in self.toolbar._widgets:
            if w.rect.collidepoint(pos):
                return True
        # HUD top bar (padding + 48 h). The research quick-open button
        # rides in this band too, so blocking world interaction here
        # doubles as its click-guard.
        if pos[1] < 16 + 48 + 8:
            return True
        # Selected-structure menu occupies its own rect. The menu is
        # responsible for its own internal controls (close + drag
        # handle); covering the full rect here is enough to suppress
        # world interaction while the user drags the panel around.
        if self.menu is not None:
            mrect = self.menu.rect()
            if mrect is not None and mrect.collidepoint(pos):
                return True
        if self.studio is not None and self.studio.is_open:
            return True
        return False

    def _toolbar_avoid_rect(self) -> pygame.Rect | None:
        if self.toolbar is None or not self.toolbar._widgets:
            return None
        rect = self.toolbar._widgets[0].rect.copy()
        for w in self.toolbar._widgets[1:]:
            rect.union_ip(w.rect)
        return rect.inflate(24, 24)

    def _refresh_hover(self, tile_pos: tuple[int, int], over_ui: bool) -> None:
        assert self.world is not None
        if over_ui:
            self._hover_building = None
            self._hover_belt = None
            self._hover_origin = None
            return
        b = self.world.building_at(tile_pos)
        if b is not None:
            self._hover_building = b
            self._hover_belt = None
            self._hover_origin = b.origin
            self._hover_footprint = b.footprint
            return
        tile = self.world.tile_at(tile_pos)
        if isinstance(tile, ConveyorBelt):
            self._hover_building = None
            self._hover_belt = tile
            self._hover_origin = tile.pos
            self._hover_footprint = (1, 1)
            return
        self._hover_building = None
        self._hover_belt = None
        self._hover_origin = None

    def _render_hover_brackets(self, surface: pygame.Surface) -> None:
        assert self.world is not None
        assert self.camera is not None
        origin = self._hover_origin
        if origin is not None and self._hover_strength.value > 0.01:
            draw_hover_brackets(
                surface,
                self.camera,
                origin,
                self._hover_footprint,
                time=self.world.time,
                strength=self._hover_strength.value,
            )

        # Menu-originated highlight (hovering a port in the structure menu).
        if self.menu is not None:
            h = self.menu.world_highlight()
            if h is not None:
                draw_hover_brackets(
                    surface,
                    self.camera,
                    h.cell,
                    h.footprint,
                    time=self.world.time,
                    strength=1.0,
                    color=h.accent,
                )

    def _on_lmb(self, tile_pos: tuple[int, int], is_pointer: bool) -> None:
        assert self.world is not None
        assert self.menu is not None

        # Clicking an existing building always opens the menu (no place).
        b = self.world.building_at(tile_pos)
        if b is not None:
            self.menu.open_building(b)
            return

        # Belt under cursor in pointer mode: open belt menu.
        if is_pointer:
            tile = self.world.tile_at(tile_pos)
            if isinstance(tile, ConveyorBelt):
                self.menu.open_belt(tile, self.world.belt_network)
                return
            # Empty ground click in pointer mode closes the menu.
            self.menu.close()
            return

        # Other tools: place as usual.
        self._place(tile_pos)

    def _place(self, tile_pos: tuple[int, int]) -> None:
        assert self.world is not None
        assert self.cursor is not None
        slot = self.cursor.tool
        if slot is None:
            return
        if slot.id == "pointer":
            return
        if slot.id == "belt":
            if self.world.is_free(tile_pos):
                belt = ConveyorBelt(tile_pos, self.cursor.rotation)
                if self.world.place_tile(belt):
                    if self.fx is not None:
                        self.fx.spawn_place(
                            tile_pos, (1, 1), self.world.time, PALETTE.primary
                        )
                        self.fx.spawn_click_ripple(tile_pos, (1, 1), self.world.time, PALETTE.primary)
                    SFX.play("world.place")
                else:
                    SFX.play("ui.error")
            else:
                SFX.play("ui.error")
            return
        prefab: BuildingPrefab | None = slot.prefab
        if prefab is None:
            return
        building = prefab.factory(tile_pos, self.cursor.rotation, self.cursor.mirrored)
        if self.world.place_building(building):
            if self.fx is not None:
                self.fx.spawn_place(
                    building.origin, building.footprint, self.world.time, PALETTE.secondary
                )
                self.fx.spawn_click_ripple(
                    building.origin, building.footprint, self.world.time, PALETTE.secondary
                )
            SFX.play("world.place")
        else:
            SFX.play("ui.error")

    def _on_rmb(self, tile_pos: tuple[int, int]) -> None:
        """RMB: delete belt or building under cursor with a dissolve flourish."""
        assert self.world is not None
        # Peek first so we can spawn an FX with the right footprint/color.
        building = self.world.building_at(tile_pos)
        tile = self.world.tile_at(tile_pos)
        if self.world.remove_at(tile_pos):
            if self.fx is not None:
                if building is not None:
                    self.fx.spawn_remove(
                        building.origin, building.footprint, self.world.time
                    )
                    self.fx.spawn_click_ripple(
                        building.origin, building.footprint, self.world.time, PALETTE.danger
                    )
                elif isinstance(tile, ConveyorBelt):
                    self.fx.spawn_remove(tile.pos, (1, 1), self.world.time)
                    self.fx.spawn_click_ripple(tile.pos, (1, 1), self.world.time, PALETTE.danger)
            SFX.play("world.remove")

    def _render_hint(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        hint = self.game.assets.render_text(
            "WASD / MMB drag pan  -  scroll zoom  -  Q inspect  -  1-7 tool  -  R / X1 rotate  -  T / X2 mirror  -  F3 perf  -  F4 sprite studio  -  LMB place/select  -  RMB delete  -  Alt hover info  -  ESC menu",
            TYPE.caption,
            PALETTE.muted,
        )
        surface.blit(
            hint,
            (surface.get_width() // 2 - hint.get_width() // 2, surface.get_height() - 24),
        )

    # -- demo factory ------------------------------------------------------

    def _build_demo_factory(self) -> None:
        """Build a working candy chain: cocoa -> chocolate; sugar + milk -> caramel;
        chocolate + caramel -> candy bar.

        Layout (tiles):
          row 1 (y=1): sugar extractor (0,1) -> belt -> caramel pot @ (6,1)
          row 2 (y=2): milk well (0,2) -> belt (joins caramel pot)
          row 3 (y=5): cocoa extractor (0,5) -> belt -> chocolate mixer @ (6,5)
          row 4 (y=3): caramel bus east (caramel -> wrapper top-left in)
          row 5 (y=4): chocolate bus east (chocolate -> wrapper bottom-left in)
          wrapper: (10, 3) 2x2 outputs candy bar east at (12,3).
        """
        assert self.world is not None
        w = self.world

        # --- Sugar + Milk -> Caramel Pot ---
        w.place_building(BUILDINGS.extractor_sugar.factory((0, 1), Direction.E))
        for x in range(1, 6):
            w.place_tile(ConveyorBelt((x, 1), Direction.E))
        w.place_building(BUILDINGS.well_milk.factory((0, 2), Direction.E))
        for x in range(1, 6):
            w.place_tile(ConveyorBelt((x, 2), Direction.E))

        caramel_pot = BUILDINGS.pot_caramel.factory((6, 1), Direction.E)
        w.place_building(caramel_pot)

        # Caramel output bus east to the candy wrapper's top-left input.
        for x in range(8, 10):
            w.place_tile(ConveyorBelt((x, 1), Direction.E))
        for y in range(2, 4):
            w.place_tile(ConveyorBelt((9, y), Direction.S))

        # --- Cocoa -> Chocolate Mixer ---
        w.place_building(BUILDINGS.extractor_cocoa.factory((0, 5), Direction.E))
        for x in range(1, 6):
            w.place_tile(ConveyorBelt((x, 5), Direction.E))
        w.place_building(BUILDINGS.extractor_cocoa.factory((0, 6), Direction.E))
        for x in range(1, 6):
            w.place_tile(ConveyorBelt((x, 6), Direction.E))

        chocolate_mixer = BUILDINGS.mixer_chocolate.factory((6, 5), Direction.E)
        w.place_building(chocolate_mixer)

        # Chocolate output bus east + turn north to wrapper's bottom-left input.
        for x in range(8, 10):
            w.place_tile(ConveyorBelt((x, 5), Direction.E))
        w.place_tile(ConveyorBelt((9, 4), Direction.N))

        # --- Candy Wrapper (2x2) at (10,3) ---
        candy_wrapper = BUILDINGS.wrapper_candy.factory((10, 3), Direction.E)
        w.place_building(candy_wrapper)

        # Candy bar output bus east.
        for x in range(12, 18):
            w.place_tile(ConveyorBelt((x, 3), Direction.E))
