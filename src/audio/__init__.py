"""Audio subsystem: semantic SFX cues with throttling + pitch-variant baking.

All game code should play audio through :data:`SFX` (or the bound
:func:`play` helper) -- never import ``pygame.mixer`` directly.
"""

from .sfx import SFX, Cue, SoundSystem, play

__all__ = ["SFX", "Cue", "SoundSystem", "play"]
