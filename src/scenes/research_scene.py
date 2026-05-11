"""Paused-overlay Research Tree scene.

Pushed over :class:`~src.scenes.play_scene.PlayScene` on TAB (or via
the HUD cogwheel button); the sim stops because only the top-of-stack
scene's ``update`` runs. The scene renders a pan/zoom board populated
with research node cards, animated connector edges, a hover tooltip,
and a slide-in detail menu -- visually mirroring the main gameplay's
building + tooltip + structure-menu triad so everything feels of a
piece.
"""

from __future__ import annotations

import math
import random

import pygame

from ..audio.sfx import SFX
from ..buildings.registry import BUILDINGS
from ..core import config
from ..design import easing
from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..items.registry import ITEMS
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from ..research.info import effect_row, for_node
from ..research.node import ResearchNode
from ..research.state import ResearchState
from ..research.tree import RESEARCH, all_edges, by_id
from ..ui.drag_pan import DragPanController
from ..ui.placement_fx import PlacementFx
from ..ui.research_menu import ResearchMenu
from ..ui.research_tooltip import ResearchTooltip
from ..ui.zoom_controls import ZoomControls
from ..world.camera import Camera
from .scene import Scene

# Board-grid cell size in "world" (pre-zoom) pixels.
NODE_STRIDE_X: int = 320
NODE_STRIDE_Y: int = 240
# Cards are always rendered into a fixed "design-resolution" surface of
# ``CARD_W x CARD_H`` and then smoothscaled to the on-screen rect, so
# every pixel (text glyphs, icon, chips, halo, stripe, status glyph)
# scales together with zoom. The actual on-screen rect is still
# ``CARD_W * zoom`` wide / ``CARD_H * zoom`` tall (clamped).
CARD_W: int = 240
CARD_H: int = 140
# Design-space layout knobs for the card. Kept here so the cards stay
# DRY with any future card-style widget.
_CARD_PAD: int = 12
_CARD_STRIPE_W: int = 6
_CARD_ICON: int = 80
_CARD_ICON_X: int = 16
_CARD_TEXT_X: int = _CARD_ICON_X + _CARD_ICON + 14
_CARD_TEXT_Y: int = 18
_CARD_CHIP_Y: int = CARD_H - 30
_CARD_GLYPH: pygame.Rect = pygame.Rect(CARD_W - 36, 14, 26, 26)
_CARD_HALO_PAD: int = 10

# Minimap panel size (bottom-left corner).
_MINIMAP_W: int = 168
_MINIMAP_H: int = 120

# Category visual grouping. Soft tinted AABB + floating chip per category;
# colors reflect the candy theme (warm extractor, pink processor, mint logistics).
_CATEGORY_ACCENT: dict[str, tuple[int, int, int]] = {
    "Extraction": PALETTE.warning,
    "Processing": PALETTE.primary,
    "Packaging": PALETTE.success,
    "Logistics": PALETTE.secondary,
}


_PAN_KEYS: dict[int, tuple[int, int]] = {
    pygame.K_w: (0, -1),
    pygame.K_a: (-1, 0),
    pygame.K_s: (0, 1),
    pygame.K_d: (1, 0),
    pygame.K_UP: (0, -1),
    pygame.K_LEFT: (-1, 0),
    pygame.K_DOWN: (0, 1),
    pygame.K_RIGHT: (1, 0),
}

# Multiplier per wheel-tick + per zoom-button click. Same on both
# so wheel + on-screen + keyboard all feel identical.
_ZOOM_STEP: float = 1.10


class ResearchScene(Scene):
    """Research board overlay pushed on top of ``PlayScene``."""

    def __init__(self, research: ResearchState) -> None:
        super().__init__()
        self.research = research
        self.camera: Camera | None = None
        self.tooltip: ResearchTooltip | None = None
        self.menu: ResearchMenu | None = None
        self.fx = PlacementFx()
        self._drag_pan = DragPanController()
        self._time: float = 0.0

        self._fade = Tween(
            start=0.0, end=1.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out
        )
        self._fade_value: float = 0.0
        self._closing = False
        self._close_tween: Tween | None = None
        self._close_value: float = 1.0

        self._hover_node: ResearchNode | None = None
        self._selected_node: ResearchNode | None = None
        self._card_reveal: dict[str, AnimValue] = {}
        self._card_pulse: dict[str, AnimValue] = {}

        rng = random.Random(0x5E7C31)
        self._sprinkle_hues = (
            PALETTE.primary,
            PALETTE.secondary,
            PALETTE.success,
            PALETTE.warning,
            PALETTE.sugar_crystal,
        )
        # Per-sprinkle tuple:
        #   0: xn       - normalised x (0..1) before drift
        #   1: phase    - 0..1, used as both colour wobble seed and an
        #                 evenly-spread vertical offset so the rain reads
        #                 as a continuous column instead of a cluster
        #   2: hue_idx  - index into ``_sprinkle_hues``
        #   3: rot0     - base rotation of the short line segment
        #   4: speed    - fall speed (px/s)
        #   5: depth    - 0..1 parallax factor (size + alpha + drift)
        #   6: spin     - rotational drift in rad/s (positive or negative)
        self._sprinkles: list[
            tuple[float, float, int, float, float, float, float]
        ] = [
            (
                rng.random(),
                (i + rng.random()) / 48.0,
                rng.randrange(len(self._sprinkle_hues)),
                rng.uniform(0.0, math.pi * 2),
                rng.uniform(14.0, 30.0),
                rng.uniform(0.35, 1.0),
                rng.uniform(-1.8, 1.8),
            )
            for i in range(48)
        ]

        self._unsub_changed = None

        # Return-to-game button (top-right). Mirrors the HUD's research
        # pill in reverse: chevron glyph + label, with the same hover/
        # press springs so the two screens feel stitched together.
        self._return_btn_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
        self._return_btn_hover = AnimValue(value=0.0, speed=18.0)
        self._return_btn_press = AnimValue(value=0.0, speed=22.0)
        self._return_btn_hovered: bool = False
        self._return_btn_prev_hover: bool = False

        # Minimap (bottom-left). Click-and-drag scrubs the camera to that
        # spot via the smooth ``pan_to``; the viewport frame on the
        # minimap reflects the live camera, not the lerp target.
        self._minimap_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
        self._minimap_hover: bool = False
        self._minimap_glow = AnimValue(value=0.0, speed=14.0)

        # On-screen zoom controls (created in ``on_enter`` so it can read
        # the runtime asset loader; the field is initialised here to keep
        # type-checker happy and avoid attribute-error in early frames).
        self._zoom_controls: ZoomControls | None = None

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self) -> None:
        assert self.game is not None
        window_size = self.game.window_size
        self.camera = Camera(window_size)
        # Center camera on the centroid of currently-reachable nodes so the
        # available research is visible without panning on first open.
        self._center_camera()

        self.tooltip = ResearchTooltip(self.game.assets)
        self.menu = ResearchMenu(self.game.assets)
        self.menu.attach_state(self.research)
        self.menu.bind(
            on_research=self._on_menu_research,
            on_focus_prereq=self._on_focus_prereq,
        )
        self.menu.layout(window_size)

        self._zoom_controls = ZoomControls(
            on_zoom_in=lambda: self._zoom_to_centre(_ZOOM_STEP),
            on_zoom_out=lambda: self._zoom_to_centre(1.0 / _ZOOM_STEP),
            on_fit=self._fit_to_all,
            zoom_provider=self._current_zoom_for_readout,
        )
        self._layout_zoom_controls(window_size)

        for node in RESEARCH:
            self._card_reveal[node.id] = AnimValue(
                value=0.0, target=1.0, speed=3.5
            )
            self._card_pulse[node.id] = AnimValue(value=0.0, target=0.0, speed=5.0)

        # Kick off staggered reveal. The perceived stagger comes from
        # the global fade-in tween below; each card still lerps in on
        # its own ``AnimValue`` so selected/pulsed cards pop cleanly.
        for node in RESEARCH:
            self._card_reveal[node.id].set(0.0)
            self._card_reveal[node.id].to(1.0)

        self._fade = Tween(
            start=0.0, end=1.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out
        )
        self._fade_value = 0.0
        self._closing = False
        self._close_tween = None
        self._close_value = 1.0

        if self.game is not None:
            self._unsub_changed = self.game.events.on(
                "research.changed", self._on_research_changed
            )

        SFX.play("ui.open")

    def on_exit(self) -> None:
        self._drag_pan.release()
        if self._unsub_changed is not None:
            self._unsub_changed()
            self._unsub_changed = None

    def on_resize(self, size: tuple[int, int]) -> None:
        if self.camera is not None:
            self.camera.resize(size)
        if self.menu is not None:
            self.menu.layout(size)
        if self._zoom_controls is not None:
            self._layout_zoom_controls(size)

    def _layout_zoom_controls(self, window_size: tuple[int, int]) -> None:
        """Position the zoom cluster above the legend in the bottom-right."""
        if self._zoom_controls is None:
            return
        # Reserve a slot above the (variable-width) legend row by
        # nudging the cluster up by the legend's nominal row height.
        legend_height = THEME.spacing.md + 28
        self._zoom_controls.layout_bottom_right(
            window_size, bottom_margin=legend_height
        )

    # -- event routing -----------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        assert self.game is not None
        if self.menu is not None and self.menu.handle_event(event):
            return
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_TAB, pygame.K_ESCAPE):
                self._begin_close()
                return
            if event.key == pygame.K_r:
                self._center_camera()
                return
            if event.key == pygame.K_f:
                self._fit_to_all()
                return
            if event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                self._zoom_to_centre(_ZOOM_STEP)
                return
            if event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self._zoom_to_centre(1.0 / _ZOOM_STEP)
                return
        if event.type == pygame.MOUSEWHEEL and self.camera is not None:
            factor = _ZOOM_STEP ** event.y
            self.camera.zoom_by(factor, around_screen=self.game.input.mouse_pos)

    # -- update ------------------------------------------------------------

    def update(self, dt: float, sim_ticks: int, sim_alpha: float) -> None:
        assert self.game is not None
        assert self.camera is not None
        self._time += dt

        self._fade_value = float(self._fade.update(dt))
        if self._closing and self._close_tween is not None:
            self._close_value = float(self._close_tween.update(dt))
            if self._close_tween.done:
                self.game.pop_scene()
                return

        self._drag_pan.update(dt, self.game.input, self.camera)
        self._pan_camera(dt)
        self.camera.update(dt)

        mouse_pos = self.game.input.mouse_pos

        if self.menu is not None:
            self.menu.update(
                dt,
                mouse_pos,
                self.game.input.mouse(1),
                self.game.input.mouse_released(1),
            )

        over_menu = self.menu is not None and self.menu.rect() is not None and \
            self.menu.rect().collidepoint(mouse_pos)

        self._update_return_button(dt, mouse_pos)
        self._update_minimap(dt, mouse_pos, self.game.input.mouse(1))
        if self._zoom_controls is not None:
            self._zoom_controls.update(
                dt,
                mouse_pos,
                self.game.input.mouse(1),
                mouse_released=self.game.input.mouse_released(1),
            )

        for node in RESEARCH:
            self._card_reveal[node.id].update(dt)
            self._card_pulse[node.id].update(dt)

        # Pick hover node (topmost match under cursor; menu + the return
        # button + minimap + zoom controls all swallow hovers so cards
        # don't light up behind UI).
        over_zoom = (
            self._zoom_controls is not None and self._zoom_controls.hovered
        )
        block_hover = (
            over_menu
            or self._drag_pan.active
            or self._return_btn_hovered
            or self._minimap_hover
            or over_zoom
        )
        self._hover_node = None if block_hover else self._find_node_at(mouse_pos)

        if self.tooltip is not None:
            if self._hover_node is not None and self._selected_node is None:
                info = for_node(self._hover_node, self.research)
                avoid = self.menu.rect() if self.menu is not None else None
                self.tooltip.set(info, mouse_pos, avoid=avoid)
            else:
                self.tooltip.set(None, mouse_pos)
            self.tooltip.update(dt)

        # Click handling (ignored while dragging to pan).
        if (
            self._hover_node is not None
            and self.game.input.mouse_released(1)
            and not self._drag_pan.active
            and not over_menu
        ):
            self._select_node(self._hover_node)

        if self.fx is not None:
            pass  # fx updated/drawn per frame; no explicit tick required

    def _update_return_button(
        self, dt: float, mouse_pos: tuple[int, int]
    ) -> None:
        """Tick the return-to-game button's hover/press springs + click.

        Uses the rect captured during the previous frame's render, just
        like the HUD's research button, so the hit region always tracks
        whatever layout the header produced.
        """
        assert self.game is not None
        hover = (
            self._return_btn_rect.w > 0
            and self._return_btn_rect.collidepoint(mouse_pos)
            and not self._closing
        )
        self._return_btn_hovered = hover
        self._return_btn_hover.to(1.0 if hover else 0.0)
        self._return_btn_hover.update(dt)
        pressed_now = hover and self.game.input.mouse(1)
        self._return_btn_press.to(1.0 if pressed_now else 0.0)
        self._return_btn_press.update(dt)
        if hover and not self._return_btn_prev_hover:
            SFX.play("ui.hover")
        if hover and self.game.input.mouse_released(1):
            self._begin_close()
        self._return_btn_prev_hover = hover

    def _update_minimap(
        self, dt: float, mouse_pos: tuple[int, int], mouse_down: bool
    ) -> None:
        """Hover-glow + click-and-drag pan-scrub for the minimap.

        Holding the left mouse button anywhere over the minimap pans the
        camera smoothly toward the matching world position via
        :meth:`Camera.pan_to`. We use ``mouse_down`` rather than
        ``mouse_released`` so the camera scrubs continuously while the
        cursor is dragged across the minimap.
        """
        if self._minimap_rect.w == 0:
            self._minimap_hover = False
            self._minimap_glow.to(0.0)
            self._minimap_glow.update(dt)
            return
        hover = self._minimap_rect.collidepoint(mouse_pos)
        if hover and not self._minimap_hover:
            SFX.play("ui.hover")
        self._minimap_hover = hover
        self._minimap_glow.to(1.0 if hover else 0.0)
        self._minimap_glow.update(dt)
        if hover and mouse_down and self.camera is not None:
            wx, wy = self._minimap_to_world(mouse_pos)
            self.camera.pan_to(wx, wy)

    def _world_bounds(self) -> pygame.Rect:
        """AABB of all research cards in world space (deterministic)."""
        xs = [n.grid_pos[0] for n in RESEARCH]
        ys = [n.grid_pos[1] for n in RESEARCH]
        min_x = min(xs) * NODE_STRIDE_X
        min_y = min(ys) * NODE_STRIDE_Y
        max_x = (max(xs) + 1) * NODE_STRIDE_X
        max_y = (max(ys) + 1) * NODE_STRIDE_Y
        return pygame.Rect(min_x, min_y, max_x - min_x, max_y - min_y)

    def _minimap_projection(self) -> tuple[pygame.Rect, float, float, float]:
        """Return the minimap inset rect + ``(scale, ox, oy)`` projector.

        The shape is letterboxed: the larger of the two axis scales is
        kept so the tree's aspect ratio is preserved, then centred inside
        the inset.
        """
        bounds = self._world_bounds()
        inset = pygame.Rect(
            8, 8, self._minimap_rect.w - 16, self._minimap_rect.h - 16
        )
        if bounds.w <= 0 or bounds.h <= 0:
            return inset, 1.0, float(inset.x), float(inset.y)
        scale = min(inset.w / bounds.w, inset.h / bounds.h)
        proj_w = bounds.w * scale
        proj_h = bounds.h * scale
        ox = inset.x + (inset.w - proj_w) / 2 - bounds.x * scale
        oy = inset.y + (inset.h - proj_h) / 2 - bounds.y * scale
        return inset, scale, ox, oy

    def _minimap_to_world(self, screen_pos: tuple[int, int]) -> tuple[float, float]:
        """Inverse-project a screen-space minimap click into world coords."""
        local_x = screen_pos[0] - self._minimap_rect.x
        local_y = screen_pos[1] - self._minimap_rect.y
        _inset, scale, ox, oy = self._minimap_projection()
        if scale <= 0:
            return (0.0, 0.0)
        return ((local_x - ox) / scale, (local_y - oy) / scale)

    def _pan_camera(self, dt: float) -> None:
        assert self.game is not None
        assert self.camera is not None
        dx = dy = 0
        for key, (kx, ky) in _PAN_KEYS.items():
            if self.game.input.key(key):
                dx += kx
                dy += ky
        if dx == 0 and dy == 0:
            return
        mag = (dx * dx + dy * dy) ** 0.5
        nx, ny = dx / mag, dy / mag
        speed = config.CAMERA_PAN_SPEED * dt / max(0.5, self.camera.zoom)
        self.camera.pan(nx * speed, ny * speed)

    # -- interactions ------------------------------------------------------

    def _select_node(self, node: ResearchNode) -> None:
        self._selected_node = node
        if self.menu is not None:
            self.menu.open_node(node)
        if self.tooltip is not None:
            self.tooltip.set(None, (0, 0))
        SFX.play("ui.click")

    def _on_menu_research(self, node: ResearchNode) -> None:
        if not self.research.research(node):
            SFX.play("ui.error")
            return
        SFX.play("ui.toggle_on")
        # Placement-fx ripple centred on the card.
        cx_world, cy_world = self._card_center_world(node)
        # PlacementFx expects tile origin/footprint. Convert the virtual
        # board position to a 1-tile footprint anchored on the card centre.
        tile = config.TILE
        fx_origin = (int(cx_world // tile) - 1, int(cy_world // tile) - 1)
        self.fx.spawn_click_ripple(fx_origin, (3, 3), self._time, PALETTE.success)
        self.fx.spawn_place(fx_origin, (3, 3), self._time, PALETTE.success)
        self._card_pulse[node.id].set(1.0)
        self._card_pulse[node.id].to(0.0)
        if self.menu is not None:
            self.menu.flash_status()

    def _on_focus_prereq(self, node_id: str) -> None:
        try:
            node = by_id(node_id)
        except KeyError:
            return
        cx, cy = self._card_center_world(node)
        if self.camera is not None:
            # Smooth pan -- ``pan_to`` only nudges target_x/y so
            # :meth:`Camera.update` lerps the current position in.
            self.camera.pan_to(cx, cy)

    def _on_research_changed(self, **_: object) -> None:
        # Force a re-draw / pulse of newly-unlocked children.
        for node in RESEARCH:
            status = self.research.status_of(node)
            if status == "available":
                pulse = self._card_pulse.get(node.id)
                if pulse is not None and pulse.value < 0.05:
                    pulse.set(0.6)
                    pulse.to(0.0)

    # -- camera helpers ----------------------------------------------------

    def _center_camera(self) -> None:
        if self.camera is None:
            return
        available = [
            n
            for n in RESEARCH
            if self.research.status_of(n) in ("available", "researched")
        ]
        if not available:
            available = list(RESEARCH[:1])
        xs = [self._card_center_world(n)[0] for n in available]
        ys = [self._card_center_world(n)[1] for n in available]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        self.camera.set_center(cx, cy)

    def _zoom_to_centre(self, factor: float) -> None:
        """Zoom by ``factor`` anchored on the window centre."""
        if self.camera is None:
            return
        cx = self.camera.viewport_w // 2
        cy = self.camera.viewport_h // 2
        self.camera.zoom_by(factor, around_screen=(cx, cy))

    def _fit_to_all(self) -> None:
        """Smooth-pan + smooth-zoom so every node fits comfortably onscreen.

        Same destination as ``_center_camera`` for translation, but the
        zoom level is solved from the tree's world bounds + a small
        margin so all cards (and their category bands) are visible.
        """
        if self.camera is None:
            return
        bounds = self._world_bounds()
        margin = THEME.spacing.xxl * 2
        target_w = max(1.0, float(bounds.w) + margin * 2)
        target_h = max(1.0, float(bounds.h) + margin * 2)
        zoom = min(
            self.camera.viewport_w / target_w,
            self.camera.viewport_h / target_h,
        )
        zoom = max(config.MIN_ZOOM, min(config.MAX_ZOOM, zoom))
        self.camera.zoom_to(
            zoom,
            around_screen=(
                self.camera.viewport_w // 2,
                self.camera.viewport_h // 2,
            ),
        )
        cx = bounds.x + bounds.w / 2
        cy = bounds.y + bounds.h / 2
        self.camera.pan_to(cx, cy)

    def _current_zoom_for_readout(self) -> float:
        """Camera-zoom for the on-screen readout; falls back to 1.0 pre-init."""
        return float(self.camera.zoom) if self.camera is not None else 1.0

    # -- geometry ----------------------------------------------------------

    def _card_center_world(self, node: ResearchNode) -> tuple[float, float]:
        gx, gy = node.grid_pos
        return (
            gx * NODE_STRIDE_X + NODE_STRIDE_X / 2,
            gy * NODE_STRIDE_Y + NODE_STRIDE_Y / 2,
        )

    def _card_screen_rect(self, node: ResearchNode) -> pygame.Rect:
        assert self.camera is not None
        cx, cy = self._card_center_world(node)
        sx, sy = self.camera.world_to_screen(cx, cy)
        zoom = self.camera.zoom
        w = max(40, int(CARD_W * zoom))
        h = max(30, int(CARD_H * zoom))
        return pygame.Rect(sx - w // 2, sy - h // 2, w, h)

    def _find_node_at(self, pos: tuple[int, int]) -> ResearchNode | None:
        # Iterate back-to-front (the ordering doesn't truly matter because
        # cards don't overlap, but this keeps intent explicit).
        for node in reversed(RESEARCH):
            if self._card_screen_rect(node).collidepoint(pos):
                return node
        return None

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assert self.camera is not None

        fade = self._fade_value
        if self._closing:
            fade = max(0.0, self._close_value)

        self._render_background(surface, fade)
        self._render_board_grid(surface, fade)
        self._render_category_bands(surface, fade)
        self._render_sprinkles(surface, fade)
        self._render_edges(surface, fade)
        self._render_nodes(surface, fade)

        self.fx.render(surface, self.camera, self._time)

        self._render_header(surface, fade)
        self._render_legend(surface, fade)
        self._render_minimap(surface, fade)
        if self._zoom_controls is not None:
            self._zoom_controls.render(surface, self.game.assets, fade)
        self._render_return_button(surface, fade)

        if self.menu is not None:
            self.menu.render(surface)
        if self.tooltip is not None:
            self.tooltip.render(surface)

        self._drag_pan.render_indicator(
            surface, self.game.input.mouse_pos, self._time
        )

    def _render_background(self, surface: pygame.Surface, fade: float) -> None:
        surface.fill(PALETTE.bg_deep)
        veil = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        veil.fill(with_alpha(PALETTE.bg_base, int(160 * max(0.0, min(1.0, fade)))))
        surface.blit(veil, (0, 0))

    def _render_board_grid(self, surface: pygame.Surface, fade: float) -> None:
        assert self.camera is not None
        alpha = int(50 * fade)
        if alpha <= 0:
            return
        zoom = self.camera.zoom
        # World-space step for a faint dot grid.
        step = 64
        cam_x = self.camera.x
        cam_y = self.camera.y
        start_x = int(cam_x // step) * step
        start_y = int(cam_y // step) * step
        w, h = surface.get_size()
        color = with_alpha(PALETTE.line, alpha)
        with acquired((w, h)) as layer:
            y = start_y
            while True:
                sy = int((y - cam_y) * zoom)
                if sy > h + 2:
                    break
                x = start_x
                while True:
                    sx = int((x - cam_x) * zoom)
                    if sx > w + 2:
                        break
                    pygame.draw.circle(layer, color, (sx, sy), 1)
                    x += step
                y += step
            surface.blit(layer, (0, 0))

    def _render_category_bands(self, surface: pygame.Surface, fade: float) -> None:
        """Soft tinted AABB per research category + floating category chip.

        Sits between the dot-grid and the sprinkle/edge/node layers so the
        bands read as quiet background scaffolding. Each band's footprint
        is the AABB of its category's cards in screen space (so the
        grouping moves and scales with the camera), padded by
        ``THEME.spacing.lg`` and tinted by the per-category accent.
        A small floating chip carrying the category name floats just
        above each band like a label tab.
        """
        if fade <= 0.05:
            return
        assert self.game is not None
        # Group nodes by category.
        by_cat: dict[str, list[ResearchNode]] = {}
        for node in RESEARCH:
            by_cat.setdefault(node.category, []).append(node)

        w, h = surface.get_size()
        padding = THEME.spacing.lg
        alpha_factor = max(0.0, min(1.0, fade))
        screen_rect = pygame.Rect(0, 0, w, h)
        with acquired((w, h)) as layer:
            for category, nodes in by_cat.items():
                accent = _CATEGORY_ACCENT.get(category, PALETTE.muted)
                rects = [self._card_screen_rect(n) for n in nodes]
                xs = [r.x for r in rects] + [r.right for r in rects]
                ys = [r.y for r in rects] + [r.bottom for r in rects]
                band = pygame.Rect(
                    min(xs) - padding,
                    min(ys) - padding,
                    (max(xs) - min(xs)) + 2 * padding,
                    (max(ys) - min(ys)) + 2 * padding,
                )
                if not screen_rect.colliderect(band):
                    continue

                band_a = int(22 * alpha_factor)
                border_a = int(60 * alpha_factor)
                pygame.draw.rect(layer, with_alpha(accent, band_a), band)
                pygame.draw.rect(layer, with_alpha(accent, border_a), band, 1)

                chip_label = self.game.assets.render_text(
                    category.upper(), TYPE.label, accent
                )
                chip_pad_x = 8
                chip_pad_y = 4
                chip_w = chip_label.get_width() + chip_pad_x * 2
                chip_h = chip_label.get_height() + chip_pad_y * 2
                chip_rect = pygame.Rect(
                    band.x + 4,
                    band.y - chip_h - 2,
                    chip_w,
                    chip_h,
                )
                if not screen_rect.colliderect(chip_rect):
                    continue
                pygame.draw.rect(
                    layer,
                    with_alpha(PALETTE.bg_deep, int(200 * alpha_factor)),
                    chip_rect,
                )
                pygame.draw.rect(
                    layer,
                    with_alpha(accent, int(220 * alpha_factor)),
                    chip_rect,
                    1,
                )
                layer.blit(
                    chip_label,
                    (chip_rect.x + chip_pad_x, chip_rect.y + chip_pad_y),
                )
            surface.blit(layer, (0, 0))

    def _render_sprinkles(self, surface: pygame.Surface, fade: float) -> None:
        """Continuous, lightly-parallaxed rain of sprinkles.

        Each piece loops vertically in isolation (its y-position modulos
        against the viewport height), so the rain reads as unbroken.
        Depth drives size, alpha and horizontal drift so the far and
        near pieces separate into layers rather than reading as noise.
        """
        w, h = surface.get_size()
        base_alpha = 95.0 * max(0.0, min(1.0, fade))
        if base_alpha <= 0.5:
            return
        t = self._time
        span = h + 48
        with acquired((w, h)) as layer:
            for xn, phase, hue_idx, rot0, speed, depth, spin in self._sprinkles:
                # Wrap around so a fresh sprinkle enters just above the
                # screen the moment one exits the bottom.
                y = ((t * speed + phase * span) % span) - 24
                drift = 18.0 + 26.0 * depth
                x = xn * w + math.sin(t * 0.55 + phase * math.tau) * drift
                a_rot = rot0 + t * spin
                half = 3.0 + 3.5 * depth
                dx = math.cos(a_rot) * half
                dy = math.sin(a_rot) * half
                alpha = int(max(0.0, min(255.0, base_alpha * (0.3 + 0.8 * depth))))
                color = with_alpha(self._sprinkle_hues[hue_idx], alpha)
                width = 2 if depth > 0.55 else 1
                pygame.draw.line(
                    layer,
                    color,
                    (x - dx, y - dy),
                    (x + dx, y + dy),
                    width,
                )
            surface.blit(layer, (0, 0))

    def _render_edges(self, surface: pygame.Surface, fade: float) -> None:
        """Draw all edges with orthogonal Manhattan routing.

        Every edge enters/exits the cards on their N/S faces and travels
        in axis-aligned segments with a shared mid-row turning point.
        Corner joints get a small filleted dot and the endpoints get
        ``solder-pad`` style dots so the connections feel deliberate --
        the visual language is "circuit trace" rather than "ruler line".
        """
        if fade <= 0.02:
            return
        w, h = surface.get_size()
        alpha_factor = max(0.0, min(1.0, fade))
        with acquired((w, h)) as layer:
            for parent_id, child_id in all_edges():
                try:
                    parent = by_id(parent_id)
                    child = by_id(child_id)
                except KeyError:
                    continue
                p_status = self.research.status_of(parent)
                c_status = self.research.status_of(child)

                p_rect = self._card_screen_rect(parent)
                c_rect = self._card_screen_rect(child)

                if p_status == "researched" and c_status == "researched":
                    color = PALETTE.success
                    width = 3
                    dashed = False
                elif p_status == "researched":
                    color = PALETTE.primary
                    width = 2
                    dashed = True
                else:
                    color = PALETTE.line
                    width = 1
                    dashed = False

                alpha = int(200 * alpha_factor)
                col_a = with_alpha(color, alpha)
                points, corners = self._route_orthogonal(p_rect, c_rect)
                if dashed:
                    self._draw_polyline_dashed(layer, col_a, points, width)
                else:
                    self._draw_polyline(layer, col_a, points, width)

                # Rounded corner fillets soften L-joints.
                radius = max(1, width // 2 + 2)
                for cx_p, cy_p in corners:
                    pygame.draw.circle(layer, col_a, (cx_p, cy_p), radius)
                # "Solder pad" end dots at parent exit / child entry.
                dot_r = max(2, width + 1)
                pygame.draw.circle(layer, col_a, points[0], dot_r)
                pygame.draw.circle(layer, col_a, points[-1], dot_r)
            surface.blit(layer, (0, 0))

    @staticmethod
    def _route_orthogonal(
        p_rect: pygame.Rect, c_rect: pygame.Rect
    ) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        """Return ``(polyline_points, corner_pivots)`` for an edge.

        Generally parents sit above children in the tree, so we exit the
        parent at its bottom-centre and enter the child at its
        top-centre. When the two cards share an x column the path
        collapses to a single straight segment and there are no corners
        to round.
        """
        p_x = p_rect.centerx
        p_y = p_rect.bottom
        c_x = c_rect.centerx
        c_y = c_rect.top
        if abs(c_x - p_x) < 2:
            return [(p_x, p_y), (c_x, c_y)], []
        mid_y = (p_y + c_y) // 2
        return (
            [(p_x, p_y), (p_x, mid_y), (c_x, mid_y), (c_x, c_y)],
            [(p_x, mid_y), (c_x, mid_y)],
        )

    @staticmethod
    def _draw_polyline(
        surface: pygame.Surface,
        color: tuple[int, int, int, int],
        points: list[tuple[int, int]],
        width: int,
    ) -> None:
        if len(points) < 2:
            return
        for i in range(len(points) - 1):
            pygame.draw.line(surface, color, points[i], points[i + 1], width)

    def _draw_polyline_dashed(
        self,
        surface: pygame.Surface,
        color: tuple[int, int, int, int],
        points: list[tuple[int, int]],
        width: int,
    ) -> None:
        """Draw a dashed polyline where dashes flow across corners.

        Each segment carries its own dash run but the global ``local_phase``
        chases the dash cycle as we cross corners so the pattern reads as
        one continuous "marching ants" stream from parent to child --
        even on multi-segment Manhattan paths.
        """
        if len(points) < 2:
            return
        dash = 10
        gap = 7
        step = dash + gap
        local_phase = (self._time * 40.0) % step
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            length = math.hypot(x2 - x1, y2 - y1)
            if length < 1e-3:
                continue
            ux = (x2 - x1) / length
            uy = (y2 - y1) / length
            offset = -local_phase
            while offset < length:
                seg_start = max(0.0, offset)
                seg_end = min(length, offset + dash)
                if seg_end > seg_start:
                    p1 = (x1 + ux * seg_start, y1 + uy * seg_start)
                    p2 = (x1 + ux * seg_end, y1 + uy * seg_end)
                    pygame.draw.line(
                        surface,
                        color,
                        (int(p1[0]), int(p1[1])),
                        (int(p2[0]), int(p2[1])),
                        width,
                    )
                offset += step
            local_phase = (local_phase + length) % step

    def _render_nodes(self, surface: pygame.Surface, fade: float) -> None:
        assert self.camera is not None
        w, h = surface.get_size()
        viewport = pygame.Rect(-32, -32, w + 64, h + 64)
        for node in RESEARCH:
            rect = self._card_screen_rect(node)
            if not viewport.colliderect(rect):
                continue
            reveal = self._card_reveal[node.id].value * fade
            if reveal <= 0.02:
                continue
            pulse = self._card_pulse[node.id].value
            self._render_node_card(surface, node, rect, reveal, pulse)

    def _render_node_card(
        self,
        surface: pygame.Surface,
        node: ResearchNode,
        rect: pygame.Rect,
        reveal: float,
        pulse: float,
    ) -> None:
        """Render a single research card.

        The card body (and its halo) are drawn into off-screen surfaces at
        a fixed design resolution -- ``CARD_W x CARD_H`` for the body,
        ``CARD_W + 2*pad`` x ``CARD_H + 2*pad`` for the halo -- and then
        smoothscaled to the camera-zoomed screen rect. That single
        transformation scales every glyph, icon, chip border, accent
        stripe, hover overlay and shine in perfect lockstep so the card
        always reads as one cohesive unit at any zoom level.
        """
        assert self.camera is not None
        status = self.research.status_of(node)
        hovered = self._hover_node is node
        selected = self._selected_node is node
        zoom = self.camera.zoom

        # Reveal slide is screen-space (constant pixels regardless of zoom)
        # so the entry animation feels equally snappy no matter how far
        # in/out the player is.
        oy = int(round((1.0 - easing.out_quart(reveal)) * 14))
        r = rect.move(0, oy)

        # Palette by status.
        if status == "researched":
            accent = PALETTE.success
            fill = darken(PALETTE.bg_raised, 0.05)
            border = PALETTE.success
        elif status == "available":
            accent = PALETTE.primary
            fill = PALETTE.bg_raised
            border = PALETTE.primary
        else:
            accent = PALETTE.muted
            fill = darken(PALETTE.bg_raised, 0.22)
            border = PALETTE.line

        # Outer halo: drawn in design space and smoothscaled by the same
        # zoom factor as the card so its perceived thickness/glow stays
        # locked to the card edge.
        halo_alpha = 0
        halo_color = accent
        if status == "available":
            phase = 0.5 + 0.5 * math.sin(self._time * 2.4)
            halo_alpha = int(70 + 80 * phase)
        if pulse > 0.01:
            halo_alpha = max(halo_alpha, int(230 * pulse))
            halo_color = PALETTE.success if status == "researched" else accent
        if selected:
            halo_alpha = max(halo_alpha, 160)
        if halo_alpha > 0:
            pad_design = _CARD_HALO_PAD
            halo_design = (CARD_W + pad_design * 2, CARD_H + pad_design * 2)
            with acquired(halo_design) as halo:
                pygame.draw.rect(
                    halo,
                    with_alpha(halo_color, halo_alpha),
                    halo.get_rect().inflate(-2, -2),
                    3,
                )
                pad_screen = max(2, int(round(pad_design * zoom)))
                halo_screen = (r.w + pad_screen * 2, r.h + pad_screen * 2)
                if halo_screen != halo_design:
                    halo_scaled = pygame.transform.smoothscale(halo, halo_screen)
                else:
                    halo_scaled = halo
                surface.blit(halo_scaled, (r.x - pad_screen, r.y - pad_screen))

        with acquired((CARD_W, CARD_H)) as card:
            card_rect = pygame.Rect(0, 0, CARD_W, CARD_H)
            beveled_panel(card, card_rect, fill=fill, border=border)

            if selected:
                pygame.draw.rect(card, lighten(border, 0.2), card_rect, 3)

            # Accent stripe on the left edge.
            stripe = pygame.Rect(
                0, _CARD_PAD // 2, _CARD_STRIPE_W, CARD_H - _CARD_PAD
            )
            pygame.draw.rect(card, accent, stripe)

            # Icon on the left.
            icon_rect = pygame.Rect(
                _CARD_ICON_X,
                (CARD_H - _CARD_ICON) // 2,
                _CARD_ICON,
                _CARD_ICON,
            )
            self._draw_card_icon(card, icon_rect, node, status)

            # Text stack on the right.
            text_x = _CARD_TEXT_X
            cat_col = PALETTE.muted if status != "locked" else PALETTE.line
            title_col = PALETTE.text_strong if status != "locked" else PALETTE.muted
            cat_surf = self.game.assets.render_text(
                node.category.upper(), TYPE.label, cat_col
            )
            title_surf = self.game.assets.render_text(
                node.name, TYPE.body, title_col
            )
            card.blit(cat_surf, (text_x, _CARD_TEXT_Y))
            card.blit(title_surf, (text_x, _CARD_TEXT_Y + cat_surf.get_height() + 4))

            # Effect chips (max 2 on the card footer).
            effects = node.effects[:2]
            chip_x = text_x
            chip_y = _CARD_CHIP_Y
            for eff in effects:
                row = effect_row(eff)
                label = row.value
                surf = self.game.assets.render_text(label, TYPE.label, accent)
                chip_w = surf.get_width() + 12
                chip_rect = pygame.Rect(chip_x, chip_y, chip_w, 20)
                pygame.draw.rect(card, with_alpha(accent, 40), chip_rect)
                pygame.draw.rect(card, accent, chip_rect, 1)
                card.blit(
                    surf,
                    (
                        chip_rect.x + 6,
                        chip_rect.y + (chip_rect.h - surf.get_height()) // 2,
                    ),
                )
                chip_x += chip_w + 6

            # Status glyph / lock icon in the top-right.
            self._draw_status_glyph(card, _CARD_GLYPH.copy(), status)

            # Hover brightening.
            if hovered and status != "locked":
                overlay = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
                overlay.fill(with_alpha(PALETTE.text_strong, 14))
                card.blit(overlay, (0, 0))

            # Researched glow overlay.
            if status == "researched":
                shine = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
                pygame.draw.rect(
                    shine, with_alpha(PALETTE.success, 30), shine.get_rect()
                )
                card.blit(shine, (0, 0))

            # smoothscale always returns a fresh surface; copy() does the
            # same for the rare 1:1 case so the per-surface alpha we set
            # below never leaks into a pooled card.
            if r.size != (CARD_W, CARD_H):
                scaled = pygame.transform.smoothscale(card, r.size)
            else:
                scaled = card.copy()

        scaled.set_alpha(int(255 * reveal))
        surface.blit(scaled, r.topleft)

    def _draw_card_icon(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        node: ResearchNode,
        status: str,
    ) -> None:
        assert self.game is not None
        beveled_panel(
            surface, rect, fill=darken(PALETTE.bg_deep, 0.1), border=PALETTE.line
        )
        sprite = None
        target = rect.w - 8
        if node.icon_building_id:
            key = None
            for p in BUILDINGS.all():
                if p.id == node.icon_building_id:
                    key = f"{p.sprite_base}_idle_f0"
                    break
            if key is not None:
                try:
                    sprite = self.game.assets.sprite(key)
                except FileNotFoundError:
                    sprite = None
        if sprite is None and node.icon_item_id:
            try:
                sprite = self.game.assets.sprite(
                    ITEMS.by_id(node.icon_item_id).sprite_key
                )
            except (KeyError, FileNotFoundError):
                sprite = None
        if sprite is not None:
            if sprite.get_width() != target:
                sprite = pygame.transform.smoothscale(sprite, (target, target))
            if status == "locked":
                sprite = sprite.copy()
                veil = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
                veil.fill(with_alpha(PALETTE.bg_deep, 160))
                sprite.blit(veil, (0, 0))
            surface.blit(
                sprite,
                (rect.centerx - sprite.get_width() // 2, rect.centery - sprite.get_height() // 2),
            )

    def _draw_status_glyph(
        self, surface: pygame.Surface, rect: pygame.Rect, status: str
    ) -> None:
        """Draw the top-right status glyph at the rect's native size.

        Sized off ``rect`` rather than hard-coded magic numbers so the
        same helper can paint the (slightly larger) design-space glyph on
        the cards AND the smaller minimap-corner badge if we ever want to
        reuse it elsewhere.
        """
        cx = rect.centerx
        cy = rect.centery
        radius = max(6, rect.w // 2 - 2)
        if status == "researched":
            pygame.draw.circle(surface, PALETTE.success, (cx, cy), radius)
            pygame.draw.circle(surface, PALETTE.bg_deep, (cx, cy), radius, 1)
            arm = max(3, radius - 5)
            pygame.draw.lines(
                surface,
                PALETTE.bg_deep,
                False,
                [
                    (cx - arm, cy),
                    (cx - 1, cy + arm - 1),
                    (cx + arm, cy - arm + 1),
                ],
                max(2, radius // 5),
            )
        elif status == "locked":
            body_h = max(8, rect.h // 2 + 2)
            body_w = max(10, rect.w // 2 + 4)
            body = pygame.Rect(cx - body_w // 2, cy - 1, body_w, body_h)
            pygame.draw.rect(surface, PALETTE.warning, body)
            pygame.draw.rect(surface, PALETTE.bg_deep, body, 1)
            shackle_w = body_w - 4
            shackle = pygame.Rect(
                cx - shackle_w // 2, body.y - shackle_w, shackle_w, shackle_w
            )
            pygame.draw.arc(
                surface,
                PALETTE.warning,
                shackle,
                math.pi * 0.1,
                math.pi * 0.9,
                2,
            )
        else:  # available: small sparkle
            pulse = 0.5 + 0.5 * math.sin(self._time * 3.0)
            r = max(3, int(radius * 0.5 + 2 * pulse))
            pygame.draw.circle(
                surface,
                with_alpha(PALETTE.primary, int(180 + 60 * pulse)),
                (cx, cy),
                r,
            )

    # -- scene chrome ------------------------------------------------------

    def _render_header(self, surface: pygame.Surface, fade: float) -> None:
        assert self.game is not None
        alpha = int(255 * fade)
        title = self.game.assets.render_text(
            "RESEARCH TREE", TYPE.h1, PALETTE.text_strong
        )
        sub = self.game.assets.render_text(
            "Factory paused  \u00b7  drag to pan  \u00b7  scroll / + - to zoom  \u00b7  "
            "R recenter  \u00b7  F fit",
            TYPE.caption,
            PALETTE.muted,
        )
        pad = THEME.spacing.lg
        panel_w = max(title.get_width(), sub.get_width()) + pad * 2 + 24
        panel_h = title.get_height() + sub.get_height() + pad + 6
        rect = pygame.Rect(pad, pad, panel_w, panel_h)
        with acquired(rect.size) as layer:
            beveled_panel(
                layer,
                pygame.Rect(0, 0, rect.w, rect.h),
                fill=PALETTE.bg_deep,
                border=PALETTE.line,
            )
            stripe = pygame.Rect(0, 4, 4, rect.h - 8)
            pygame.draw.rect(layer, PALETTE.primary, stripe)
            layer.blit(title, (pad + 8, pad // 2))
            layer.blit(sub, (pad + 8, pad // 2 + title.get_height() + 2))
            layer.set_alpha(alpha)
            surface.blit(layer, rect.topleft)

    def _render_legend(self, surface: pygame.Surface, fade: float) -> None:
        assert self.game is not None
        alpha = int(255 * fade)
        entries = (
            ("Researched", PALETTE.success),
            ("Available", PALETTE.primary),
            ("Locked", PALETTE.muted),
        )
        gap = 14
        pad = THEME.spacing.md
        surfs = [
            self.game.assets.render_text(label, TYPE.caption, color)
            for label, color in entries
        ]
        total_w = sum(s.get_width() for s in surfs) + gap * (len(surfs) - 1) + pad * 2 + 40
        row_h = max(s.get_height() for s in surfs) + pad
        w, h = surface.get_size()
        rect = pygame.Rect(w - total_w - pad, h - row_h - pad, total_w, row_h)
        with acquired(rect.size) as layer:
            beveled_panel(
                layer,
                pygame.Rect(0, 0, rect.w, rect.h),
                fill=PALETTE.bg_deep,
                border=PALETTE.line,
            )
            x = pad + 4
            y = (rect.h - surfs[0].get_height()) // 2
            for (_label, color), s in zip(entries, surfs, strict=False):
                pygame.draw.rect(layer, color, pygame.Rect(x, y + 3, 10, 10))
                pygame.draw.rect(
                    layer, PALETTE.line, pygame.Rect(x, y + 3, 10, 10), 1
                )
                layer.blit(s, (x + 16, y))
                x += 16 + s.get_width() + gap
            layer.set_alpha(alpha)
            surface.blit(layer, rect.topleft)

    def _render_minimap(self, surface: pygame.Surface, fade: float) -> None:
        """Bottom-left minimap with status-coloured node dots + viewport.

        Matches the legend's beveled-panel + accent-stripe vocabulary so
        the two bottom-left UI elements feel related. The viewport
        rectangle reads the *live* camera (not the lerp target) so it
        tracks panning/zoom in real time.
        """
        assert self.camera is not None
        alpha = int(255 * fade)
        if alpha <= 4:
            self._minimap_rect = pygame.Rect(0, 0, 0, 0)
            return
        pad = THEME.spacing.md
        _w, h = surface.get_size()
        rect = pygame.Rect(pad, h - _MINIMAP_H - pad, _MINIMAP_W, _MINIMAP_H)
        self._minimap_rect = rect

        glow = self._minimap_glow.value
        with acquired(rect.size) as layer:
            local = pygame.Rect(0, 0, rect.w, rect.h)
            beveled_panel(
                layer,
                local,
                fill=PALETTE.bg_deep,
                border=lighten(PALETTE.line, 0.2 * glow),
            )
            stripe = pygame.Rect(0, 4, 4, rect.h - 8)
            pygame.draw.rect(layer, PALETTE.primary, stripe)

            _inset, scale, ox, oy = self._minimap_projection()
            # The (scale, ox, oy) returned already bakes the world-bounds
            # origin in, so every projection is just ``ox + wx * scale``.

            # Faint edges underlay so the topology reads at a glance.
            edge_col = with_alpha(PALETTE.line, 220)
            for parent_id, child_id in all_edges():
                try:
                    p = by_id(parent_id)
                    c = by_id(child_id)
                except KeyError:
                    continue
                pcx, pcy = self._card_center_world(p)
                ccx, ccy = self._card_center_world(c)
                pygame.draw.line(
                    layer,
                    edge_col,
                    (int(ox + pcx * scale), int(oy + pcy * scale)),
                    (int(ox + ccx * scale), int(oy + ccy * scale)),
                    1,
                )

            # Status-coloured node dots.
            for node in RESEARCH:
                status = self.research.status_of(node)
                if status == "researched":
                    col = PALETTE.success
                elif status == "available":
                    col = PALETTE.primary
                else:
                    col = PALETTE.muted
                cx_w, cy_w = self._card_center_world(node)
                dot = pygame.Rect(
                    int(ox + cx_w * scale - 3),
                    int(oy + cy_w * scale - 2),
                    6,
                    4,
                )
                pygame.draw.rect(layer, col, dot)
                pygame.draw.rect(layer, PALETTE.bg_deep, dot, 1)

            # Camera viewport indicator. The translucent fill is blitted
            # as a Surface (rather than ``pygame.draw.rect`` with an alpha
            # tuple, which OVERWRITES pixels on an SRCALPHA layer) so the
            # node dots underneath still show through.
            cam = self.camera
            view_x = int(ox + cam.x * scale)
            view_y = int(oy + cam.y * scale)
            view_w = max(2, int((cam.viewport_w / cam.zoom) * scale))
            view_h = max(2, int((cam.viewport_h / cam.zoom) * scale))
            view_rect = pygame.Rect(view_x, view_y, view_w, view_h).clip(_inset)
            if view_rect.w > 0 and view_rect.h > 0:
                fill = pygame.Surface(view_rect.size, pygame.SRCALPHA)
                fill.fill(with_alpha(PALETTE.text_strong, 50))
                layer.blit(fill, view_rect.topleft)
                pygame.draw.rect(layer, PALETTE.text_strong, view_rect, 1)

            # Hover/active glow border.
            if glow > 0.02:
                pygame.draw.rect(
                    layer,
                    with_alpha(PALETTE.primary, int(180 * glow)),
                    local,
                    2,
                )

            # Tiny corner label so the minimap reads as a "MAP" rather
            # than as a stray panel.
            label = self.game.assets.render_text(
                "MAP", TYPE.label, PALETTE.muted
            )
            layer.blit(label, (rect.w - label.get_width() - 6, 4))

            layer.set_alpha(alpha)
            surface.blit(layer, rect.topleft)

    def _render_return_button(
        self, surface: pygame.Surface, fade: float
    ) -> None:
        """Pill-shaped "Return to Game" button in the top-right corner.

        Mirrors the HUD's research pill (beveled + hover glow + hover
        underline + press darken) but with a left-pointing chevron so
        the direction of travel reads instantly.
        """
        assert self.game is not None
        alpha = int(255 * fade)
        if alpha <= 4:
            self._return_btn_rect = pygame.Rect(0, 0, 0, 0)
            return

        pad = THEME.spacing.lg
        label = self.game.assets.render_text(
            "RETURN TO GAME", TYPE.label, PALETTE.text_strong
        )
        hint = self.game.assets.render_text(
            "TAB", TYPE.label, PALETTE.muted
        )
        glyph_slot = 18
        gap = 10
        hint_gap = 8
        hint_pad_x = 6
        hint_w = hint.get_width() + hint_pad_x * 2
        inner_w = (
            glyph_slot + gap + label.get_width() + hint_gap + hint_w
        )
        btn_w = inner_w + pad * 2
        btn_h = 36
        w, _ = surface.get_size()
        rect = pygame.Rect(w - btn_w - pad, pad, btn_w, btn_h)
        self._return_btn_rect = rect

        hover = self._return_btn_hover.value
        press = self._return_btn_press.value

        fill = lighten(PALETTE.bg_raised, 0.04 + 0.05 * hover)
        border = lighten(PALETTE.primary, 0.05 * hover)

        with acquired(rect.size) as layer:
            local = pygame.Rect(0, 0, rect.w, rect.h)
            beveled_panel(layer, local, fill=fill, border=border)

            glow_a = int(28 + 56 * hover - 30 * press)
            if glow_a > 0:
                glow = pygame.Surface(rect.size, pygame.SRCALPHA)
                glow.fill(with_alpha(PALETTE.primary, glow_a))
                layer.blit(glow, (0, 0))

            if press > 0.01:
                dim = pygame.Surface(rect.size, pygame.SRCALPHA)
                dim.fill(with_alpha(PALETTE.bg_deep, int(50 * press)))
                layer.blit(dim, (0, 0))

            # Accent stripe on the LEFT edge mirrors the header stripe
            # and reinforces the "this is the way back" direction.
            pygame.draw.rect(
                layer, PALETTE.primary, pygame.Rect(0, 4, 4, rect.h - 8)
            )

            # Back chevron glyph, nudged on hover/press for a tactile feel.
            chev_cx = 8 + glyph_slot // 2 + int(-3 * hover) - int(round(press * 1))
            chev_cy = rect.h // 2
            self._draw_back_chevron(
                layer, (chev_cx, chev_cy), 7, PALETTE.primary
            )

            # Label.
            label_x = 8 + glyph_slot + gap
            label_y = (rect.h - label.get_height()) // 2 - int(round(press * 1))
            layer.blit(label, (label_x, label_y))

            # "TAB" hotkey hint chip on the right.
            chip_x = label_x + label.get_width() + hint_gap
            chip_y = (rect.h - 18) // 2
            chip_rect = pygame.Rect(chip_x, chip_y, hint_w, 18)
            pygame.draw.rect(
                layer, with_alpha(PALETTE.line, 120), chip_rect
            )
            pygame.draw.rect(layer, PALETTE.line, chip_rect, 1)
            layer.blit(
                hint,
                (
                    chip_rect.x + (chip_rect.w - hint.get_width()) // 2,
                    chip_rect.y + (chip_rect.h - hint.get_height()) // 2,
                ),
            )

            if hover > 0.02:
                ul_w = rect.w - 6
                ul = pygame.Surface((ul_w, 2), pygame.SRCALPHA)
                ul.fill(with_alpha(PALETTE.primary, int(200 * hover)))
                layer.blit(ul, (3, rect.h - 3))

            layer.set_alpha(alpha)
            surface.blit(layer, rect.topleft)

    @staticmethod
    def _draw_back_chevron(
        surface: pygame.Surface,
        center: tuple[int, int],
        size: int,
        color: tuple[int, int, int],
    ) -> None:
        """Chunky left-pointing chevron glyph (two parallel strokes)."""
        cx, cy = center
        # Outer triangle-style chevron drawn with thick lines so it
        # reads at any scale.
        pygame.draw.lines(
            surface,
            color,
            False,
            [
                (cx + size // 2, cy - size),
                (cx - size // 2, cy),
                (cx + size // 2, cy + size),
            ],
            3,
        )
        # A second, shorter stroke behind the first gives the glyph
        # weight without an extra draw pass's worth of anti-aliasing.
        pygame.draw.line(
            surface,
            color,
            (cx - size // 2, cy),
            (cx + size, cy),
            2,
        )

    # -- closing -----------------------------------------------------------

    def _begin_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._close_tween = Tween(
            start=float(self._fade_value),
            end=0.0,
            duration=THEME.anim.base,
            ease=THEME.anim.ease_out,
        )
        SFX.play("ui.close")


__all__ = ["ResearchScene"]
