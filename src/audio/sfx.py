"""Centralised sound system.

Exposes a small :class:`SoundSystem` with a semantic **cue catalogue**: call
sites play by intent (``"ui.click"``, ``"world.place"``) instead of binding
to a file path. Each cue declares its volume, throttling window, channel
group, and a pool of pitch-variant ratios. Pitch variants are baked once at
load time by resampling the source sound via numpy -- pygame's mixer can't
pitch-shift at runtime, but resampling a ~10 KB wav is a one-shot cost.

The system **fails soft**: if ``pygame.mixer.init`` raises (headless CI,
missing drivers), :attr:`is_available` stays ``False`` and :meth:`play`
short-circuits. Benchmarks and unit tests -- which construct ``World``
directly without a :class:`~src.core.game.Game` -- therefore pay nothing.

Playback respects a tiny settings model (mute, master/SFX volume, per-group
toggles) that :meth:`apply_settings` pulls off a ``UserSettings``-shaped
object, so live settings changes take effect on the next ``play`` without
touching any channels mid-flight.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pygame

try:  # pragma: no cover - defensive: sndarray ships with pygame but may
    # be missing in stripped installs.
    import pygame.sndarray as _sndarray
except ImportError:  # pragma: no cover
    _sndarray = None  # type: ignore[assignment]

try:
    import numpy as _np
except ImportError:  # pragma: no cover - numpy is a hard project dep, but
    # keep the import guarded so audio never breaks test collection.
    _np = None  # type: ignore[assignment]

from ..assets import paths


# Low-latency mixer config. 256-frame buffer keeps click->hear latency
# around ~6 ms at 44.1 kHz; 24 channels is plenty for the cue fan-out.
_FREQ: int = 44_100
_SIZE: int = -16
_CHANNELS: int = 2
_BUFFER: int = 256
_NUM_CHANNELS: int = 24

_SOUNDS_DIR: Path = paths.ASSETS / "sounds"


# -- cue model -------------------------------------------------------------


@dataclass(frozen=True)
class Cue:
    """Static description of one semantic sound."""

    id: str
    source: str               # key into the loaded sound base catalogue
    volume: float = 1.0       # 0..1, multiplied against master/sfx at play time
    throttle_ms: int = 0      # swallowed replays within this window
    group: str = "ui"         # ui | world | sim
    pitch_variants: tuple[float, ...] = (1.0,)  # sample rate ratios to pick from


# Filename stems (without ``.mp3``) that the cue catalogue references.
_SOUND_FILES: dict[str, str] = {
    "high-click": "high-click.mp3",
    "low-click": "low-click.mp3",
    "high-tick": "high-retro-tick.mp3",
    "low-tick": "low-retro-tick.mp3",
}


_CUES: tuple[Cue, ...] = (
    # -- UI ---------------------------------------------------------------
    Cue(
        "ui.hover",
        "high-tick",
        volume=0.22,
        throttle_ms=45,
        group="ui",
        pitch_variants=(0.94, 1.0, 1.06),
    ),
    Cue(
        "ui.click",
        "high-click",
        volume=0.70,
        group="ui",
        pitch_variants=(0.97, 1.0, 1.03),
    ),
    Cue(
        "ui.click_soft",
        "low-click",
        volume=0.55,
        group="ui",
        pitch_variants=(0.97, 1.0, 1.03),
    ),
    Cue(
        "ui.toggle_on",
        "high-click",
        volume=0.65,
        group="ui",
        pitch_variants=(1.05,),
    ),
    Cue(
        "ui.toggle_off",
        "low-click",
        volume=0.55,
        group="ui",
        pitch_variants=(0.92,),
    ),
    Cue(
        "ui.stepper",
        "low-tick",
        volume=0.42,
        group="ui",
        pitch_variants=(0.95, 1.0, 1.05),
    ),
    Cue(
        "ui.slider_tick",
        "low-tick",
        volume=0.30,
        throttle_ms=55,
        group="ui",
        pitch_variants=(0.94, 1.0, 1.06),
    ),
    Cue(
        "ui.open",
        "high-tick",
        volume=0.50,
        group="ui",
        pitch_variants=(1.10,),
    ),
    Cue(
        "ui.close",
        "low-tick",
        volume=0.50,
        group="ui",
        pitch_variants=(0.90,),
    ),
    Cue(
        "ui.error",
        "low-click",
        volume=0.70,
        throttle_ms=120,
        group="ui",
        pitch_variants=(0.78,),
    ),
    # -- World ------------------------------------------------------------
    Cue(
        "world.place",
        "high-click",
        volume=0.75,
        group="world",
        pitch_variants=(0.98, 1.0, 1.02),
    ),
    Cue(
        "world.remove",
        "low-click",
        volume=0.70,
        group="world",
        pitch_variants=(0.95, 1.0, 1.05),
    ),
    Cue(
        "world.rotate",
        "high-tick",
        volume=0.55,
        group="world",
        pitch_variants=(0.95, 1.0, 1.05),
    ),
    Cue(
        "world.mirror",
        "low-tick",
        volume=0.55,
        group="world",
        pitch_variants=(0.95, 1.0, 1.05),
    ),
    Cue(
        "world.tool_select",
        "high-tick",
        volume=0.45,
        group="world",
        pitch_variants=(0.88, 1.0, 1.12),
    ),
    # -- Sim --------------------------------------------------------------
    Cue(
        "sim.produced",
        "low-tick",
        volume=0.18,
        throttle_ms=120,
        group="sim",
        pitch_variants=(0.92, 1.0, 1.08),
    ),
)


# -- sound system ----------------------------------------------------------


class SoundSystem:
    """Owns loaded sounds, per-cue throttles and the tiny settings model."""

    def __init__(self) -> None:
        self._cues: dict[str, Cue] = {c.id: c for c in _CUES}
        self._variants: dict[tuple[str, float], pygame.mixer.Sound] = {}
        self._last_fired: dict[str, int] = {}
        self._listeners: list[Callable[[str], None]] = []
        self.is_available: bool = False

        # Live settings state. Defaults mirror ``UserSettings`` so the
        # system is usable even before ``apply_settings`` is called.
        self._muted: bool = False
        self._master: float = 0.8
        self._sfx: float = 0.9
        self._enabled_groups: dict[str, bool] = {
            "ui": True,
            "world": True,
            "sim": True,
        }

    # -- bootstrap ---------------------------------------------------------

    @staticmethod
    def prepare_mixer() -> None:
        """Call *before* :func:`pygame.init` for low-latency playback."""
        try:
            pygame.mixer.pre_init(_FREQ, _SIZE, _CHANNELS, _BUFFER)
        except pygame.error:
            pass

    def load(self) -> None:
        """Initialise the mixer, load mp3s, bake pitch variants. Fails soft."""
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(_FREQ, _SIZE, _CHANNELS, _BUFFER)
            pygame.mixer.set_num_channels(_NUM_CHANNELS)
        except pygame.error:
            self.is_available = False
            return

        bases: dict[str, pygame.mixer.Sound] = {}
        for key, filename in _SOUND_FILES.items():
            path = _SOUNDS_DIR / filename
            if not path.exists():
                continue
            try:
                bases[key] = pygame.mixer.Sound(str(path))
            except pygame.error:
                continue

        if not bases:
            # No sound assets found -- keep the system "off" so callers
            # don't waste time entering the play path.
            self.is_available = False
            return

        # Collect every (base, ratio) pair the catalogue will actually use.
        needed: dict[str, set[float]] = {key: {1.0} for key in bases}
        for cue in self._cues.values():
            if cue.source not in needed:
                continue
            for ratio in cue.pitch_variants:
                needed[cue.source].add(float(ratio))

        for base_key, ratios in needed.items():
            base_sound = bases[base_key]
            for ratio in ratios:
                variant = self._pitch_shift(base_sound, ratio)
                self._variants[(base_key, ratio)] = variant

        self.is_available = True

    # -- live settings -----------------------------------------------------

    def apply_settings(self, settings: Any) -> None:
        """Pull audio fields off any ``UserSettings``-shaped object."""
        self._muted = bool(getattr(settings, "audio_muted", False))
        self._master = _clamp01(getattr(settings, "audio_master", 0.8))
        self._sfx = _clamp01(getattr(settings, "audio_sfx", 0.9))
        self._enabled_groups["ui"] = bool(getattr(settings, "audio_ui", True))
        self._enabled_groups["world"] = bool(getattr(settings, "audio_world", True))
        self._enabled_groups["sim"] = bool(getattr(settings, "audio_sim", True))

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def master(self) -> float:
        return self._master

    @property
    def sfx(self) -> float:
        return self._sfx

    def group_enabled(self, group: str) -> bool:
        return self._enabled_groups.get(group, True)

    # -- listeners ---------------------------------------------------------

    def on_played(self, cb: Callable[[str], None]) -> Callable[[], None]:
        """Subscribe to a ``(cue_id,)`` callback each successful playback.

        Returns an unsubscribe function mirroring :class:`EventBus.on`.
        """
        self._listeners.append(cb)

        def off() -> None:
            try:
                self._listeners.remove(cb)
            except ValueError:
                pass

        return off

    # -- playback ----------------------------------------------------------

    def play(self, cue_id: str) -> None:
        """Fire a cue by semantic id. No-op when unavailable / muted / throttled."""
        if not self.is_available or self._muted:
            return
        cue = self._cues.get(cue_id)
        if cue is None:
            return
        if not self._enabled_groups.get(cue.group, True):
            return

        now = pygame.time.get_ticks()
        if cue.throttle_ms > 0:
            last = self._last_fired.get(cue_id, -1_000_000)
            if now - last < cue.throttle_ms:
                return

        ratio = random.choice(cue.pitch_variants) if cue.pitch_variants else 1.0
        sound = self._variants.get((cue.source, ratio))
        if sound is None:
            # Fall back to the unshifted base if the variant bake failed.
            sound = self._variants.get((cue.source, 1.0))
        if sound is None:
            return

        vol = max(0.0, min(1.0, cue.volume * self._sfx * self._master))
        try:
            sound.set_volume(vol)
            channel = pygame.mixer.find_channel(True)
            if channel is None:
                return
            channel.play(sound)
        except pygame.error:
            return

        self._last_fired[cue_id] = now
        for cb in self._listeners:
            try:
                cb(cue_id)
            except Exception:  # pragma: no cover - don't let a misbehaving
                # listener kill audio for everyone.
                pass

    # -- diagnostics -------------------------------------------------------

    def cue_ids(self) -> tuple[str, ...]:
        return tuple(self._cues.keys())

    # -- internals ---------------------------------------------------------

    def _pitch_shift(
        self, sound: pygame.mixer.Sound, ratio: float
    ) -> pygame.mixer.Sound:
        """Return a new ``Sound`` resampled at ``ratio`` (``>1`` = higher)."""
        if abs(ratio - 1.0) < 1e-6 or _np is None or _sndarray is None:
            return sound
        try:
            arr = _sndarray.array(sound)
        except (pygame.error, ValueError):
            return sound
        if arr.size == 0:
            return sound
        try:
            src_n = arr.shape[0]
            new_n = max(1, int(src_n / ratio))
            xp = _np.linspace(0.0, src_n - 1, num=new_n)
            xi = _np.arange(src_n)
            if arr.ndim == 1:
                out = _np.interp(xp, xi, arr.astype(_np.float64)).astype(arr.dtype)
            else:
                out = _np.empty((new_n, arr.shape[1]), dtype=arr.dtype)
                for ch in range(arr.shape[1]):
                    out[:, ch] = _np.interp(
                        xp, xi, arr[:, ch].astype(_np.float64)
                    ).astype(arr.dtype)
            return _sndarray.make_sound(out)
        except (pygame.error, ValueError, TypeError):
            return sound


def _clamp01(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


# Module-level singleton (mirrors ``PALETTE`` / ``THEME`` / ``PERF``).
SFX: SoundSystem = SoundSystem()


def play(cue_id: str) -> None:
    """Convenience wrapper for ``SFX.play``."""
    SFX.play(cue_id)


__all__ = ["SFX", "Cue", "SoundSystem", "play"]
