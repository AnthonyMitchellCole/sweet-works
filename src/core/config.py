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

TILE: int = 48
ITEM_PX: int = 16

DEFAULT_ZOOM: float = 1.0
MIN_ZOOM: float = 0.75
MAX_ZOOM: float = 2.5

CAMERA_PAN_SPEED: float = 480.0  # world px / second
CAMERA_SMOOTH: float = 12.0      # higher = snappier

BELT_FRAMES: int = 4
BELT_ANIM_HZ: float = 8.0  # frames per second
