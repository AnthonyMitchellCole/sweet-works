"""Benchmark scene: generate a 1M-item stress layout and measure tick + render."""

from __future__ import annotations

import time
from enum import Enum
from typing import TYPE_CHECKING

import pygame

from ..belts.network_soa import BeltNetworkSoA
from ..belts.topology import build_benchmark
from ..core import config
from ..core.events import EventBus
from ..core.perf import PERF, timed
from ..design import easing
from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..items.registry import ITEMS
from ..rendering.pixel import beveled_panel, gradient_fill
from ..rendering.renderer import Renderer
from ..ui.perf_hud import PerfHUD
from ..world.camera import Camera
from ..world.world import World
from .scene import Scene

if TYPE_CHECKING:
    pass


class _Phase(Enum):
    FLYOVER = "flyover"
    WARMUP = "warmup"
    MEASURE = "measure"
    DONE = "done"


class BenchmarkScene(Scene):
    """Pre-builds a dense SoA layout and runs a timed measurement pass."""

    def __init__(
        self,
        items: int | None = None,
        chains: int | None = None,
        belts_per_chain: int | None = None,
    ) -> None:
        super().__init__()
        # Layout sized to target ~1M items by default.
        self._target_items = items or config.BENCHMARK_ITEMS
        if chains is None or belts_per_chain is None:
            chains = config.BENCHMARK_CHAINS
            belts_per_chain = config.BENCHMARK_BELTS_PER_CHAIN
        self._chains = chains
        self._belts_per_chain = belts_per_chain

        self.world: World | None = None
        self.camera: Camera | None = None
        self.renderer: Renderer | None = None
        self.hud: PerfHUD | None = None

        self._phase: _Phase = _Phase.FLYOVER
        self._phase_t: float = 0.0
        self._build_ms: float = 0.0
        self._start_pos: tuple[float, float] = (0.0, 0.0)
        self._end_pos: tuple[float, float] = (0.0, 0.0)
        self._start_zoom: float = 0.3
        self._end_zoom: float = 1.0

        self._banner_fade: float = 0.0
        self._pass: bool = True
        self._summary: str = ""

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self) -> None:
        assert self.game is not None
        self.world = World(EventBus())
        self.camera = Camera(self.game.window_size)
        self.renderer = Renderer(self.game.assets)
        self.hud = PerfHUD(self.game.assets)
        self.hud.visible = True

        tid = ITEMS.iron.type_id
        t0 = time.perf_counter()
        soa = build_benchmark(
            n_chains=self._chains,
            belts_per_chain=self._belts_per_chain,
            fill_tid=tid,
            spacing_y=2,
        )
        self._build_ms = (time.perf_counter() - t0) * 1000.0

        network = BeltNetworkSoA()
        network.set_soa(soa)
        self.world.belt_network = network

        # Camera flyover targets.
        world_w = self._belts_per_chain * config.TILE
        world_h = self._chains * 2 * config.TILE
        self._start_pos = (world_w * 0.5, world_h * 0.5)
        self._end_pos = (world_w * 0.25, world_h * 0.25)
        self._start_zoom = max(config.MIN_ZOOM, min(0.18, 0.18))
        self._end_zoom = max(config.MIN_ZOOM, 0.22)
        self.camera.set_zoom(self._start_zoom)
        self.camera.set_center(*self._start_pos)

        PERF.reset()
        self._phase = _Phase.FLYOVER
        self._phase_t = 0.0

    def on_exit(self) -> None:
        # Drop the gigantic SoA so the next scene doesn't inherit the working set.
        if self.world is not None:
            self.world.belt_network = None
        if self.renderer is not None:
            self.renderer.invalidate_chunks()

    def on_resize(self, size: tuple[int, int]) -> None:
        if self.camera is not None:
            self.camera.resize(size)

    # -- events ------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        assert self.game is not None
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_ESCAPE:
            from .menu_scene import MenuScene

            self.game.replace_scene(MenuScene())
        elif event.key == pygame.K_r:
            self.game.replace_scene(
                BenchmarkScene(
                    items=self._target_items,
                    chains=self._chains,
                    belts_per_chain=self._belts_per_chain,
                )
            )
        elif event.key == pygame.K_F3 and self.hud is not None:
            self.hud.toggle()

    # -- update / render ---------------------------------------------------

    def update(self, dt: float, sim_ticks: int, sim_alpha: float) -> None:
        assert self.world is not None
        assert self.camera is not None

        self._phase_t += dt

        if self._phase is _Phase.FLYOVER:
            p = min(1.0, self._phase_t / max(0.001, config.BENCHMARK_FLYOVER_S))
            e = easing.in_out_cubic(p)
            cx = self._start_pos[0] + (self._end_pos[0] - self._start_pos[0]) * e
            cy = self._start_pos[1] + (self._end_pos[1] - self._start_pos[1]) * e
            z = self._start_zoom + (self._end_zoom - self._start_zoom) * e
            self.camera.set_zoom(z)
            self.camera.set_center(cx, cy)
            if p >= 1.0:
                self._phase = _Phase.WARMUP
                self._phase_t = 0.0
        elif self._phase is _Phase.WARMUP:
            if self._phase_t >= config.BENCHMARK_WARMUP_S:
                self._phase = _Phase.MEASURE
                self._phase_t = 0.0
                PERF.tick.clear()
                PERF.render.clear()
                PERF.frame.clear()
        elif self._phase is _Phase.MEASURE:
            if self._phase_t >= config.BENCHMARK_MEASURE_S:
                self._phase = _Phase.DONE
                self._phase_t = 0.0
                self._evaluate_gates()

        self.camera.update(dt)

        # Run sim ticks, timed.
        for _ in range(sim_ticks):
            with timed(PERF.tick):
                self.world.tick()

        if self._phase is _Phase.DONE:
            self._banner_fade = min(1.0, self._banner_fade + dt / 0.6)

    def render(self, surface: pygame.Surface) -> None:
        assert self.world is not None
        assert self.camera is not None
        assert self.renderer is not None
        assert self.hud is not None
        assert self.game is not None

        w, h = surface.get_size()
        gradient_fill(surface, pygame.Rect(0, 0, w, h), PALETTE.bg_deep, PALETTE.bg_base)
        self.renderer.draw_world(
            surface, self.world, self.camera, self.world.time, self.game.clock.sim_alpha
        )
        self._render_phase_banner(surface)
        snap = PERF.snapshot(fps=self.game.clock.fps)
        self.hud.set_pass(self._pass)
        self.hud.render(surface, snap, gates=(config.GATE_BELT_TICK_P95_MS, config.GATE_BELT_TICK_MAX_MS))

        if self._phase is _Phase.DONE:
            self._render_final_banner(surface)

    # -- helpers -----------------------------------------------------------

    def _evaluate_gates(self) -> None:
        snap = PERF.snapshot()
        ok = True
        reasons: list[str] = []
        if snap.tick_ms_p95 > config.GATE_BELT_TICK_P95_MS:
            ok = False
            reasons.append(f"tick_p95 {snap.tick_ms_p95:.2f}ms > {config.GATE_BELT_TICK_P95_MS}ms")
        if snap.tick_ms_max > config.GATE_BELT_TICK_MAX_MS:
            ok = False
            reasons.append(f"tick_max {snap.tick_ms_max:.2f}ms > {config.GATE_BELT_TICK_MAX_MS}ms")
        if self._build_ms > config.GATE_CHAIN_BUILD_MS:
            ok = False
            reasons.append(f"build {self._build_ms:.0f}ms > {config.GATE_CHAIN_BUILD_MS:.0f}ms")
        self._pass = ok
        self._summary = (
            f"items={snap.item_count:,}  tick_p95={snap.tick_ms_p95:.2f}ms  "
            f"tick_max={snap.tick_ms_max:.2f}ms  build={self._build_ms:.0f}ms"
        )
        if not ok:
            self._summary += "  | " + "; ".join(reasons)

    def _render_phase_banner(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        if self._phase is _Phase.DONE:
            return
        text = {
            _Phase.FLYOVER: "FLYOVER",
            _Phase.WARMUP: "WARMUP",
            _Phase.MEASURE: "MEASURING",
        }[self._phase]
        s = self.game.assets.render_text(text, TYPE.label, PALETTE.primary)
        x = THEME.spacing.lg
        y = surface.get_height() - s.get_height() - THEME.spacing.lg
        surface.blit(s, (x, y))

    def _render_final_banner(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        a = max(0.0, min(1.0, self._banner_fade))
        w, h = surface.get_size()

        panel_w = min(720, w - 80)
        panel_h = 120
        rect = pygame.Rect(0, 0, panel_w, panel_h)
        rect.center = (w // 2, h // 2)
        beveled_panel(surface, rect, fill=darken(PALETTE.bg_raised, 0.15), border=PALETTE.line)

        accent = PALETTE.success if self._pass else PALETTE.danger
        pygame.draw.rect(surface, accent, pygame.Rect(rect.x, rect.y, rect.w, 3))
        pygame.draw.rect(surface, accent, pygame.Rect(rect.x, rect.bottom - 3, rect.w, 3))

        title = "BENCHMARK PASS" if self._pass else "BENCHMARK FAIL"
        ts = self.game.assets.render_text(title, TYPE.display, lighten(accent, 0.1 * a))
        ts.set_alpha(int(255 * a))
        surface.blit(ts, (rect.centerx - ts.get_width() // 2, rect.y + 16))

        summary = self.game.assets.render_text(self._summary, TYPE.mono, PALETTE.text_body)
        summary.set_alpha(int(255 * a))
        surface.blit(summary, (rect.centerx - summary.get_width() // 2, rect.y + 60))

        hint = self.game.assets.render_text(
            "R rerun  -  ESC menu", TYPE.caption, with_alpha(PALETTE.muted, int(200 * a))[:3]
        )
        hint.set_alpha(int(220 * a))
        surface.blit(hint, (rect.centerx - hint.get_width() // 2, rect.bottom - hint.get_height() - 10))


__all__ = ["BenchmarkScene"]
