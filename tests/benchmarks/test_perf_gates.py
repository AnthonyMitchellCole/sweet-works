"""Performance gates enforced in CI.

These tests are marked ``bench`` so ``pytest -m "not bench"`` keeps the
default unit run fast. Invoke with::

    pytest -m bench tests/benchmarks

Each gate uses ``pytest-benchmark`` to measure a tight inner loop and
then asserts against the numeric ceilings in :mod:`src.core.config`.
The ceilings are set for modest developer laptops; CI runs should
easily clear them.
"""

from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import time

import pytest

from src.belts.chain import SLOTS_PER_BELT
from src.belts.topology import build_benchmark
from src.core import config

pytestmark = pytest.mark.bench


# ---------------------------------------------------------------------------
# sizing
# ---------------------------------------------------------------------------


def _bench_shape(items: int | None = None) -> tuple[int, int]:
    items = items or config.BENCHMARK_ITEMS
    belts_per_chain = config.BENCHMARK_BELTS_PER_CHAIN
    per_chain_slots = belts_per_chain * SLOTS_PER_BELT
    n_chains = max(1, round(items / per_chain_slots))
    return n_chains, belts_per_chain


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def big_soa():
    n, b = _bench_shape()
    return build_benchmark(n_chains=n, belts_per_chain=b, fill_tid=1)


@pytest.fixture(scope="module")
def warm_soa(big_soa):
    # 20 warmup ticks to populate any lazy buffers / caches.
    for _ in range(20):
        big_soa.tick()
    return big_soa


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------


def test_chain_build_under_gate(benchmark) -> None:
    """Building a 1M-item SoA must stay under GATE_CHAIN_BUILD_MS."""
    n, b = _bench_shape()

    def _build():
        return build_benchmark(n_chains=n, belts_per_chain=b, fill_tid=1)

    soa = benchmark(_build)
    assert soa.total_slots >= int(0.98 * config.BENCHMARK_ITEMS)

    # Stats are reported in seconds. Convert to ms.
    mean_ms = benchmark.stats.stats.mean * 1000.0
    assert mean_ms <= config.GATE_CHAIN_BUILD_MS, (
        f"chain build mean {mean_ms:.1f}ms > gate {config.GATE_CHAIN_BUILD_MS}ms"
    )


def test_belt_tick_p95_under_gate(warm_soa, benchmark) -> None:
    """SoA.tick() p95 must stay under GATE_BELT_TICK_P95_MS at 1M items."""
    benchmark.pedantic(warm_soa.tick, iterations=1, rounds=200, warmup_rounds=5)

    # pytest-benchmark's Stats object exposes percentile-adjacent numbers.
    # We compute a p95 from the individual round samples.
    samples = sorted(float(s) for s in benchmark.stats.stats.data)
    p95 = samples[int(0.95 * (len(samples) - 1))]
    p95_ms = p95 * 1000.0
    assert p95_ms <= config.GATE_BELT_TICK_P95_MS, (
        f"tick p95 {p95_ms:.2f}ms > gate {config.GATE_BELT_TICK_P95_MS}ms"
    )

    max_ms = benchmark.stats.stats.max * 1000.0
    assert max_ms <= config.GATE_BELT_TICK_MAX_MS, (
        f"tick max {max_ms:.2f}ms > gate {config.GATE_BELT_TICK_MAX_MS}ms"
    )


def test_render_frame_p95_under_gate(warm_soa, benchmark) -> None:
    """A headless render pass at 1M items must stay under GATE_RENDER_FRAME_P95_MS."""
    import pygame

    from src.assets.loader import AssetLoader
    from src.belts.network_soa import BeltNetworkSoA
    from src.core.events import EventBus
    from src.rendering.renderer import Renderer
    from src.world.camera import Camera
    from src.world.world import World

    pygame.display.init()
    pygame.font.init()
    # set_mode is required so ``convert_alpha`` can pick a pixel format.
    surface = pygame.display.set_mode(config.WINDOW)

    assets = AssetLoader()
    assets.prepare()
    assets.warm_fonts()

    world = World(EventBus())
    network = BeltNetworkSoA()
    network.set_soa(warm_soa)
    world.belt_network = network

    camera = Camera(config.WINDOW)
    camera.set_zoom(max(config.MIN_ZOOM, 0.4))
    if warm_soa.belt_pos.size:
        cx = float(warm_soa.belt_pos[:, 0].mean()) * config.TILE
        cy = float(warm_soa.belt_pos[:, 1].mean()) * config.TILE
        camera.set_center(cx, cy)

    renderer = Renderer(assets)

    # One warm render to bake chunks / caches.
    renderer.draw_world(surface, world, camera, 0.0, 0.0)

    t_ref = time.perf_counter

    def _render() -> None:
        renderer.draw_world(surface, world, camera, t_ref(), 0.0)

    benchmark.pedantic(_render, iterations=1, rounds=60, warmup_rounds=3)

    samples = sorted(float(s) for s in benchmark.stats.stats.data)
    p95 = samples[int(0.95 * (len(samples) - 1))]
    p95_ms = p95 * 1000.0
    assert p95_ms <= config.GATE_RENDER_FRAME_P95_MS, (
        f"render p95 {p95_ms:.2f}ms > gate {config.GATE_RENDER_FRAME_P95_MS}ms"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-m", "bench"]))
