"""User-editable runtime settings.

Persisted to ``assets/user_settings.json`` (same directory pattern as
``assets/sprites/overrides.json``). Loaded once at :class:`Game` boot and
applied to the relevant ``src/core/config`` module attributes + the live
``Clock`` / display so every call site that reads ``config.X`` at runtime
picks up the new value transparently.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import config

if TYPE_CHECKING:
    from .game import Game


SETTINGS_PATH: Path = Path("assets") / "user_settings.json"


@dataclass(frozen=True)
class UserSettings:
    """User-tunable runtime settings.

    Defaults mirror ``src/core/config`` at import time; see
    :func:`defaults` for a fresh default instance.
    """

    # Display
    window_w: int = config.WINDOW_W
    window_h: int = config.WINDOW_H
    fullscreen: bool = False
    fps_cap: int = config.FPS  # 0 = uncapped

    # Simulation
    tick_hz: int = config.TICK_HZ
    belt_anim_hz: float = config.BELT_ANIM_HZ
    structure_anim_hz: float = config.STRUCTURE_ANIM_HZ

    # Camera
    camera_pan_speed: float = config.CAMERA_PAN_SPEED
    camera_smooth: float = config.CAMERA_SMOOTH
    camera_drag_inertia_decay: float = config.CAMERA_DRAG_INERTIA_DECAY
    default_zoom: float = config.DEFAULT_ZOOM

    # Audio (0..1 volumes, booleans for the channel toggles).
    audio_muted: bool = False
    audio_master: float = 0.8
    audio_sfx: float = 0.9
    audio_ui: bool = True
    audio_world: bool = True
    audio_sim: bool = True

    def merged(self, **overrides: Any) -> UserSettings:
        return replace(self, **overrides)


# Captured once, at module import, as the ground-truth factory defaults so
# a later "reset to defaults" never reflects a previously-mutated config.
_DEFAULTS_SNAPSHOT: UserSettings = UserSettings()


def defaults() -> UserSettings:
    """Return the original defaults captured at import time."""
    return _DEFAULTS_SNAPSHOT


# -- persistence -----------------------------------------------------------


def load(path: Path = SETTINGS_PATH) -> UserSettings:
    """Load settings from ``path``. Missing file or keys fall back to defaults."""
    if not path.exists():
        return defaults()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults()
    if not isinstance(raw, dict):
        return defaults()
    known = {f.name for f in fields(UserSettings)}
    kwargs: dict[str, Any] = {}
    for k, v in raw.items():
        if k in known:
            kwargs[k] = v
    return defaults().merged(**kwargs)


def save(settings: UserSettings, path: Path = SETTINGS_PATH) -> None:
    """Atomically persist settings to ``path`` (parent dir is created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(settings), indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(prefix=".user_settings.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# -- runtime application ---------------------------------------------------


def apply_to_config(s: UserSettings) -> None:
    """Mutate ``src/core/config`` attributes read at runtime by the game.

    Every attribute listed here is looked up as ``config.X`` in the hot
    path, so simply rebinding the module attribute is enough.
    """
    config.WINDOW_W = int(s.window_w)
    config.WINDOW_H = int(s.window_h)
    config.WINDOW = (config.WINDOW_W, config.WINDOW_H)

    config.FPS = max(0, int(s.fps_cap))

    config.TICK_HZ = max(1, int(s.tick_hz))
    config.TICK_DT = 1.0 / config.TICK_HZ

    config.BELT_ANIM_HZ = float(s.belt_anim_hz)
    config.STRUCTURE_ANIM_HZ = float(s.structure_anim_hz)

    config.CAMERA_PAN_SPEED = float(s.camera_pan_speed)
    config.CAMERA_SMOOTH = float(s.camera_smooth)
    config.CAMERA_DRAG_INERTIA_DECAY = float(s.camera_drag_inertia_decay)
    config.DEFAULT_ZOOM = float(s.default_zoom)

    # Audio: the sound system carries its own live state; pushing the
    # ``UserSettings`` into it is enough for the next ``play`` to respect
    # new mute/volume/group flags.
    from ..audio.sfx import SFX  # noqa: PLC0415 - local import avoids cycles

    SFX.apply_settings(s)


def apply(s: UserSettings, game: Game, *, force_display: bool = False) -> None:
    """Apply settings to ``config``, the game's ``Clock`` and display.

    ``force_display`` rebuilds the window even when the resolution /
    fullscreen flag are unchanged, which is handy on first boot.
    """
    prev_w, prev_h = game.window_size
    prev_fs = bool(getattr(game, "_fullscreen", False))

    apply_to_config(s)

    game.clock.set_fps_cap(config.FPS)
    game.clock.set_tick_hz(config.TICK_HZ)

    wants_display = (
        force_display
        or prev_w != int(s.window_w)
        or prev_h != int(s.window_h)
        or prev_fs != bool(s.fullscreen)
    )
    if wants_display:
        game.apply_display(int(s.window_w), int(s.window_h), bool(s.fullscreen))
