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
from ..world.camera import Camera
from .scene import Scene

# Board-grid cell size in "world" (pre-zoom) pixels.
NODE_STRIDE_X: int = 320
NODE_STRIDE_Y: int = 240
CARD_W: int = 240
CARD_H: int = 140


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
        if event.type == pygame.MOUSEWHEEL and self.camera is not None:
            factor = 1.10 ** event.y
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

        for node in RESEARCH:
            self._card_reveal[node.id].update(dt)
            self._card_pulse[node.id].update(dt)

        # Pick hover node (topmost match under cursor; menu blocks hovers).
        self._hover_node = None if over_menu or self._drag_pan.active else self._find_node_at(mouse_pos)

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
            self.camera.set_center(cx, cy)

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
        self._render_sprinkles(surface, fade)
        self._render_edges(surface, fade)
        self._render_nodes(surface, fade)

        self.fx.render(surface, self.camera, self._time)

        self._render_header(surface, fade)
        self._render_legend(surface, fade)

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
        if fade <= 0.02:
            return
        for parent_id, child_id in all_edges():
            try:
                parent = by_id(parent_id)
                child = by_id(child_id)
            except KeyError:
                continue
            p_status = self.research.status_of(parent)
            c_status = self.research.status_of(child)

            p_center = self._card_screen_rect(parent).center
            c_center = self._card_screen_rect(child).center

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

            alpha = int(200 * fade)
            if dashed:
                self._draw_dashed_line(
                    surface, with_alpha(color, alpha), p_center, c_center, width
                )
            else:
                self._draw_line_aa(
                    surface, with_alpha(color, alpha), p_center, c_center, width
                )

    def _draw_line_aa(
        self,
        surface: pygame.Surface,
        color: tuple[int, int, int, int],
        a: tuple[int, int],
        b: tuple[int, int],
        width: int,
    ) -> None:
        # Render into a transparent layer so line alpha is honoured.
        w, h = surface.get_size()
        with acquired((w, h)) as layer:
            pygame.draw.line(layer, color, a, b, width)
            surface.blit(layer, (0, 0))

    def _draw_dashed_line(
        self,
        surface: pygame.Surface,
        color: tuple[int, int, int, int],
        a: tuple[int, int],
        b: tuple[int, int],
        width: int,
    ) -> None:
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        dist = math.hypot(dx, dy)
        if dist < 1e-3:
            return
        ux = dx / dist
        uy = dy / dist
        dash = 10
        gap = 7
        step = dash + gap
        phase = (self._time * 40.0) % step
        w, h = surface.get_size()
        with acquired((w, h)) as layer:
            travelled = -phase
            while travelled < dist:
                seg_start = max(0.0, travelled)
                seg_end = min(dist, travelled + dash)
                if seg_end > seg_start:
                    p1 = (a[0] + ux * seg_start, a[1] + uy * seg_start)
                    p2 = (a[0] + ux * seg_end, a[1] + uy * seg_end)
                    pygame.draw.line(
                        layer, color, (int(p1[0]), int(p1[1])),
                        (int(p2[0]), int(p2[1])), width
                    )
                travelled += step
            surface.blit(layer, (0, 0))

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
        assert self.camera is not None
        status = self.research.status_of(node)
        hovered = self._hover_node is node
        selected = self._selected_node is node
        zoom = self.camera.zoom

        # Reveal: fade + small Y offset.
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

        # Outer halo for availability + selection.
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
            pad = 10
            with acquired((r.w + pad * 2, r.h + pad * 2)) as halo:
                pygame.draw.rect(
                    halo,
                    with_alpha(halo_color, halo_alpha),
                    halo.get_rect().inflate(-2, -2),
                    3,
                )
                surface.blit(halo, (r.x - pad, r.y - pad))

        with acquired(r.size) as card:
            card_rect = pygame.Rect(0, 0, r.w, r.h)
            beveled_panel(card, card_rect, fill=fill, border=border)

            if selected:
                pygame.draw.rect(card, lighten(border, 0.2), card_rect, 3)

            # Accent stripe on the left edge.
            stripe = pygame.Rect(0, 4, 4, r.h - 8)
            pygame.draw.rect(card, accent, stripe)

            # Icon on the left.
            pad = max(6, int(10 * zoom / 2))
            icon_size = min(r.h - pad * 2, int(72 * zoom))
            icon_rect = pygame.Rect(pad + 6, (r.h - icon_size) // 2, icon_size, icon_size)
            self._draw_card_icon(card, icon_rect, node, status)

            # Text stack on the right.
            text_x = icon_rect.right + 8
            cat_col = PALETTE.muted if status != "locked" else PALETTE.line
            title_col = PALETTE.text_strong if status != "locked" else PALETTE.muted
            cat_surf = self.game.assets.render_text(
                node.category.upper(), TYPE.label, cat_col
            )
            title_surf = self.game.assets.render_text(
                node.name, TYPE.body, title_col
            )
            card.blit(cat_surf, (text_x, 10))
            card.blit(title_surf, (text_x, 10 + cat_surf.get_height() + 2))

            # Effect chips (max 2 on the card footer).
            effects = node.effects[:2]
            chip_x = text_x
            chip_y = r.h - 22
            for eff in effects:
                row = effect_row(eff)
                label = row.value
                surf = self.game.assets.render_text(label, TYPE.label, accent)
                chip_w = surf.get_width() + 10
                chip_rect = pygame.Rect(chip_x, chip_y - 2, chip_w, 16)
                pygame.draw.rect(card, with_alpha(accent, 40), chip_rect)
                pygame.draw.rect(card, accent, chip_rect, 1)
                card.blit(surf, (chip_rect.x + 5, chip_rect.y))
                chip_x += chip_w + 4

            # Status glyph / lock icon in the top-right.
            self._draw_status_glyph(card, pygame.Rect(r.w - 28, 8, 20, 20), status)

            # Hover brightening.
            if hovered and status != "locked":
                overlay = pygame.Surface(r.size, pygame.SRCALPHA)
                overlay.fill(with_alpha(PALETTE.text_strong, 14))
                card.blit(overlay, (0, 0))

            # Researched glow overlay.
            if status == "researched":
                shine = pygame.Surface(r.size, pygame.SRCALPHA)
                pygame.draw.rect(
                    shine, with_alpha(PALETTE.success, 30), shine.get_rect()
                )
                card.blit(shine, (0, 0))

            card.set_alpha(int(255 * reveal))
            surface.blit(card, r.topleft)

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
        cx = rect.centerx
        cy = rect.centery
        if status == "researched":
            pygame.draw.circle(surface, PALETTE.success, (cx, cy), 9)
            pygame.draw.circle(surface, PALETTE.bg_deep, (cx, cy), 9, 1)
            pygame.draw.lines(
                surface,
                PALETTE.bg_deep,
                False,
                [(cx - 4, cy), (cx - 1, cy + 3), (cx + 4, cy - 3)],
                2,
            )
        elif status == "locked":
            # Padlock.
            body = pygame.Rect(cx - 5, cy - 1, 10, 8)
            pygame.draw.rect(surface, PALETTE.warning, body)
            pygame.draw.rect(surface, PALETTE.bg_deep, body, 1)
            shackle = pygame.Rect(cx - 3, cy - 6, 6, 6)
            pygame.draw.arc(
                surface, PALETTE.warning, shackle, math.pi * 0.1, math.pi * 0.9, 2
            )
        else:  # available: small sparkle
            pulse = 0.5 + 0.5 * math.sin(self._time * 3.0)
            radius = int(3 + 2 * pulse)
            pygame.draw.circle(
                surface,
                with_alpha(PALETTE.primary, int(180 + 60 * pulse)),
                (cx, cy),
                radius,
            )

    # -- scene chrome ------------------------------------------------------

    def _render_header(self, surface: pygame.Surface, fade: float) -> None:
        assert self.game is not None
        alpha = int(255 * fade)
        title = self.game.assets.render_text(
            "RESEARCH TREE", TYPE.h1, PALETTE.text_strong
        )
        sub = self.game.assets.render_text(
            "Factory paused  ·  TAB / ESC to resume  ·  R to recenter  ·  scroll to zoom",
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
