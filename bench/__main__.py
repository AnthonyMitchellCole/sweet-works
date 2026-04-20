"""Headless performance benchmark.

Runs the SoA belt simulation (and optionally a render pass) without
opening a window, measures tick/render timing, and exits non-zero when
any performance gate is violated.

Usage examples
--------------
::

    python -m bench                          # default: 1M items, 600 ticks
    python -m bench --items 500000 --ticks 400
    python -m bench --json                   # machine-readable result
    python -m bench --render                 # also time a headless render pass

The CLI is the primary entry point used by CI and ``make bench``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

# IMPORTANT: set SDL driver before importing pygame. ``dummy`` lets the
# bench run on CI/headless boxes with no display server.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# Ensure ``src.*`` imports resolve when the package is executed from repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402

from src.belts.chain import SLOTS_PER_BELT  # noqa: E402
from src.belts.topology import build_benchmark  # noqa: E402
from src.core import config  # noqa: E402

# ---------------------------------------------------------------------------
# sizing
# ---------------------------------------------------------------------------


def _solve_shape(items: int, belts_per_chain: int) -> tuple[int, int]:
    """Return (n_chains, belts_per_chain) roughly matching ``items`` slots."""
    if belts_per_chain <= 0:
        belts_per_chain = config.BENCHMARK_BELTS_PER_CHAIN
    per_chain_slots = belts_per_chain * SLOTS_PER_BELT
    n_chains = max(1, round(items / per_chain_slots))
    return n_chains, belts_per_chain


# ---------------------------------------------------------------------------
# percentile helpers (pure python to avoid pulling full numpy stats)
# ---------------------------------------------------------------------------


def _pct(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    k = int(round(max(0.0, min(1.0, p)) * (len(s) - 1)))
    return s[k]


@dataclass
class BenchResult:
    items: int
    chains: int
    belts_per_chain: int
    ticks: int
    tick_ms_mean: float
    tick_ms_p50: float
    tick_ms_p95: float
    tick_ms_p99: float
    tick_ms_max: float
    build_ms: float
    render_ms_p95: float
    render_ms_mean: float
    render_frames: int
    passed: bool
    violations: list[str]
    gates: dict[str, float]
    numpy_version: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# benchmarks
# ---------------------------------------------------------------------------


def _bench_tick(soa, ticks: int) -> list[float]:
    """Warm up a few ticks and return ``ticks`` timing samples (ms)."""
    for _ in range(min(10, max(1, ticks // 20))):
        soa.tick()

    samples: list[float] = [0.0] * ticks
    perf = time.perf_counter
    for i in range(ticks):
        t0 = perf()
        soa.tick()
        samples[i] = (perf() - t0) * 1000.0
    return samples


def _bench_render(soa, frames: int, window: tuple[int, int]) -> list[float]:
    """Optional: measure a headless render pass at the given window size."""
    import pygame

    from src.assets.loader import AssetLoader
    from src.belts.network_soa import BeltNetworkSoA
    from src.core.events import EventBus
    from src.rendering.renderer import Renderer
    from src.world.camera import Camera
    from src.world.world import World

    pygame.display.init()
    pygame.font.init()
    # Use set_mode (not Surface) so convert_alpha has a pixel format.
    surface = pygame.display.set_mode(window)

    assets = AssetLoader()
    assets.prepare()
    assets.warm_fonts()

    world = World(EventBus())
    network = BeltNetworkSoA()
    network.set_soa(soa)
    world.belt_network = network

    camera = Camera(window)
    # Zoom out far enough that a big slice of chains is visible.
    camera.set_zoom(max(config.MIN_ZOOM, 0.4))
    # Center on the middle of the layout.
    if soa.belt_pos.size:
        cx = float(soa.belt_pos[:, 0].mean()) * config.TILE
        cy = float(soa.belt_pos[:, 1].mean()) * config.TILE
        camera.set_center(cx, cy)

    renderer = Renderer(assets)

    # Warm one frame so chunk/cache baking does not pollute samples.
    renderer.draw_world(surface, world, camera, 0.0, 0.0)

    samples: list[float] = [0.0] * frames
    perf = time.perf_counter
    for i in range(frames):
        t0 = perf()
        renderer.draw_world(surface, world, camera, float(i) / 60.0, 0.0)
        samples[i] = (perf() - t0) * 1000.0
    return samples


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m bench", description=__doc__)
    p.add_argument(
        "--items",
        type=int,
        default=config.BENCHMARK_ITEMS,
        help="target number of items on belts (default: %(default)s)",
    )
    p.add_argument(
        "--ticks",
        type=int,
        default=600,
        help="number of simulation ticks to time (default: %(default)s)",
    )
    p.add_argument(
        "--belts-per-chain",
        type=int,
        default=config.BENCHMARK_BELTS_PER_CHAIN,
        help="chain length in belts (default: %(default)s)",
    )
    p.add_argument(
        "--render",
        action="store_true",
        help="also time a headless render pass (uses SDL dummy driver)",
    )
    p.add_argument(
        "--render-frames",
        type=int,
        default=120,
        help="frames to render when --render is set (default: %(default)s)",
    )
    p.add_argument(
        "--window",
        type=str,
        default=f"{config.WINDOW_W}x{config.WINDOW_H}",
        help="WxH of the headless render window (default: %(default)s)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit a single JSON object on stdout (suppresses human output)",
    )
    p.add_argument(
        "--tick-p95-ms",
        type=float,
        default=config.GATE_BELT_TICK_P95_MS,
        help="gate: p95 tick time in ms (default: %(default)s)",
    )
    p.add_argument(
        "--tick-max-ms",
        type=float,
        default=config.GATE_BELT_TICK_MAX_MS,
        help="gate: max tick time in ms (default: %(default)s)",
    )
    p.add_argument(
        "--build-ms",
        type=float,
        default=config.GATE_CHAIN_BUILD_MS,
        help="gate: chain build time in ms (default: %(default)s)",
    )
    p.add_argument(
        "--render-p95-ms",
        type=float,
        default=config.GATE_RENDER_FRAME_P95_MS,
        help="gate: p95 render frame time in ms (default: %(default)s)",
    )
    p.add_argument(
        "--no-gates",
        action="store_true",
        help="run for profiling only; always exit 0",
    )
    return p.parse_args(argv)


def _parse_window(s: str) -> tuple[int, int]:
    parts = s.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"window must be WxH, got {s!r}")
    return int(parts[0]), int(parts[1])


def run(argv: list[str] | None = None) -> BenchResult:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    n_chains, belts_per_chain = _solve_shape(args.items, args.belts_per_chain)
    fill_tid = 1  # Any positive id works with build_benchmark.

    t0 = time.perf_counter()
    soa = build_benchmark(
        n_chains=n_chains, belts_per_chain=belts_per_chain, fill_tid=fill_tid
    )
    build_ms = (time.perf_counter() - t0) * 1000.0
    real_items = int(soa.total_items())

    tick_samples = _bench_tick(soa, args.ticks)

    render_samples: list[float] = []
    if args.render:
        render_samples = _bench_render(soa, args.render_frames, _parse_window(args.window))

    gates = {
        "tick_p95_ms": args.tick_p95_ms,
        "tick_max_ms": args.tick_max_ms,
        "build_ms": args.build_ms,
        "render_p95_ms": args.render_p95_ms,
    }
    violations: list[str] = []

    tick_p95 = _pct(tick_samples, 0.95)
    tick_p99 = _pct(tick_samples, 0.99)
    tick_p50 = _pct(tick_samples, 0.50)
    tick_max = max(tick_samples) if tick_samples else 0.0
    tick_mean = sum(tick_samples) / len(tick_samples) if tick_samples else 0.0

    render_p95 = _pct(render_samples, 0.95) if render_samples else 0.0
    render_mean = sum(render_samples) / len(render_samples) if render_samples else 0.0

    if not args.no_gates:
        if tick_p95 > args.tick_p95_ms:
            violations.append(f"tick_p95 {tick_p95:.2f}ms > {args.tick_p95_ms:.2f}ms")
        if tick_max > args.tick_max_ms:
            violations.append(f"tick_max {tick_max:.2f}ms > {args.tick_max_ms:.2f}ms")
        if build_ms > args.build_ms:
            violations.append(f"build {build_ms:.1f}ms > {args.build_ms:.1f}ms")
        if args.render and render_p95 > args.render_p95_ms:
            violations.append(
                f"render_p95 {render_p95:.2f}ms > {args.render_p95_ms:.2f}ms"
            )

    result = BenchResult(
        items=real_items,
        chains=n_chains,
        belts_per_chain=belts_per_chain,
        ticks=args.ticks,
        tick_ms_mean=tick_mean,
        tick_ms_p50=tick_p50,
        tick_ms_p95=tick_p95,
        tick_ms_p99=tick_p99,
        tick_ms_max=tick_max,
        build_ms=build_ms,
        render_ms_p95=render_p95,
        render_ms_mean=render_mean,
        render_frames=len(render_samples),
        passed=not violations,
        violations=violations,
        gates=gates,
        numpy_version=np.__version__,
    )

    if args.json:
        json.dump(result.as_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_human(result)

    return result


def _print_human(r: BenchResult) -> None:
    status = "PASS" if r.passed else "FAIL"
    print("=" * 72)
    print(f" sweet-works bench                                              [{status}] ")
    print("=" * 72)
    print(f"  layout       : {r.chains:,} chains x {r.belts_per_chain} belts")
    print(f"  items        : {r.items:,}")
    print(f"  ticks        : {r.ticks:,}  @ 20 Hz budget = {1000 / config.TICK_HZ:.1f} ms")
    print(f"  build_ms     : {r.build_ms:8.2f}   (gate {r.gates['build_ms']:.0f} ms)")
    print(f"  tick mean    : {r.tick_ms_mean:8.3f} ms")
    print(f"  tick p50     : {r.tick_ms_p50:8.3f} ms")
    print(
        f"  tick p95     : {r.tick_ms_p95:8.3f} ms"
        f"   (gate {r.gates['tick_p95_ms']:.1f} ms)"
    )
    print(f"  tick p99     : {r.tick_ms_p99:8.3f} ms")
    print(
        f"  tick max     : {r.tick_ms_max:8.3f} ms"
        f"   (gate {r.gates['tick_max_ms']:.1f} ms)"
    )
    if r.render_frames:
        print(f"  render frames: {r.render_frames}")
        print(f"  render mean  : {r.render_ms_mean:8.3f} ms")
        print(
            f"  render p95   : {r.render_ms_p95:8.3f} ms"
            f"   (gate {r.gates['render_p95_ms']:.2f} ms)"
        )
    print(f"  numpy        : {r.numpy_version}")
    if r.violations:
        print()
        print("  VIOLATIONS:")
        for v in r.violations:
            print(f"    - {v}")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    result = run(argv)
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
