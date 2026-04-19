"""Global constants. Kept flat so any module can import without cycles."""

from __future__ import annotations

TITLE: str = "fac-py"

WINDOW_W: int = 1280
WINDOW_H: int = 720
WINDOW: tuple[int, int] = (WINDOW_W, WINDOW_H)

MIN_WINDOW_W: int = 640
MIN_WINDOW_H: int = 400
RESIZABLE: bool = True

# 0 = uncapped; any positive integer caps the render loop at that FPS.
FPS: int = 0

# Fixed-timestep simulation rate (Hz). Decoupled from render.
TICK_HZ: int = 20
TICK_DT: float = 1.0 / TICK_HZ

TILE: int = 64
ITEM_PX: int = 24

DEFAULT_ZOOM: float = 1.0
MIN_ZOOM: float = 0.15
MAX_ZOOM: float = 2.5

CAMERA_PAN_SPEED: float = 480.0  # world px / second
CAMERA_SMOOTH: float = 12.0      # higher = snappier

# Middle-mouse drag-pan.
CAMERA_DRAG_INERTIA_DECAY: float = 6.0  # higher = inertia stops faster
CAMERA_DRAG_MIN_SPEED: float = 8.0      # world px/s below which inertia halts
CAMERA_DRAG_VEL_EMA: float = 0.35       # 0..1; higher = snappier velocity tracking

BELT_FRAMES: int = 4
BELT_ANIM_HZ: float = 8.0  # frames per second

# -- performance tunables ---------------------------------------------------

# Per-chunk tile dimension for the baked chunk-atlas renderer.
CHUNK_SIZE: int = 16

# Camera zoom is rounded to the nearest 1/ZOOM_QUANT for the scaled-sprite
# cache. Higher = more bins (smoother) but more cache memory.
ZOOM_QUANT: int = 16

# Number of frame samples kept by PerfCounter ring buffers (~4 s at 60 FPS).
PERF_SAMPLES: int = 240

# Max entries retained by AssetLoader's text render cache (LRU eviction).
TEXT_CACHE_MAX: int = 512

# -- benchmark ---------------------------------------------------------------

# Target item count for the stress-test layout.
BENCHMARK_ITEMS: int = 1_000_000

# Chain shape: N_CHAINS * BELTS_PER_CHAIN * ConveyorBelt.SLOTS ~= BENCHMARK_ITEMS.
BENCHMARK_CHAINS: int = 1000
BENCHMARK_BELTS_PER_CHAIN: int = 256

# Benchmark phases, in seconds.
BENCHMARK_FLYOVER_S: float = 2.0
BENCHMARK_WARMUP_S: float = 5.0
BENCHMARK_MEASURE_S: float = 15.0

# Perf gates (in milliseconds per tick / per render frame).
GATE_BELT_TICK_P95_MS: float = 20.0
GATE_BELT_TICK_MAX_MS: float = 40.0
GATE_RENDER_FRAME_P95_MS: float = 16.7
GATE_CHAIN_BUILD_MS: float = 500.0
