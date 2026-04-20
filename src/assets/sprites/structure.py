"""Compose a :class:`StructureSpec` into a per-frame Surface."""

from __future__ import annotations

import math

import pygame

from ...core import config
from ...design.palette import PALETTE, Color, darken, lighten
from . import draw
from .specs import (
    AccentStripeSpec,
    BadgeSpec,
    ChassisSpec,
    LightSpec,
    OverlaySpec,
    StructureSpec,
)


def _scale(px_at_64: int) -> int:
    """Scale a design-px value (authored at TILE=64) to the current tile size."""
    return max(1, round(px_at_64 * config.TILE / 64))


def render_structure(spec: StructureSpec, phase: str, frame: int) -> pygame.Surface:
    """Return a ``footprint*TILE`` surface for the structure at the given state.

    ``phase`` is ``"idle"`` or ``"active"``. ``frame`` is the animation
    frame index; at ``phase="idle"`` only frame ``0`` is meaningful.
    """
    fw, fh = spec.footprint
    w = fw * config.TILE
    h = fh * config.TILE
    surf = draw.new_surface((w, h))
    body = pygame.Rect(1, 1, w - 2, h - 2)

    accent_color = spec.accent.color

    _draw_chassis(surf, body, spec.chassis)
    _draw_accent(surf, body, spec.accent)
    _draw_overlay_under(surf, body, spec.overlay, accent_color, phase=phase, frame=frame)
    _draw_badge(surf, body, spec.badge, phase=phase, frame=frame)
    _draw_overlay_over(surf, body, spec.overlay, accent_color, phase=phase, frame=frame)
    _draw_lights(surf, body, spec.lights, phase=phase, frame=frame)

    return surf


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


def _draw_chassis(surf: pygame.Surface, body: pygame.Rect, spec: ChassisSpec) -> None:
    inset = _scale(spec.inset_px_at_64)
    draw.bevel_plate(surf, body, plate=spec.plate)
    face = body.inflate(-inset * 2, -inset * 2)
    pygame.draw.rect(surf, lighten(spec.plate, 0.04), face)
    pygame.draw.rect(surf, darken(spec.plate, 0.18), face, 1)
    draw.rivet_corners(surf, body, inset=1 + _scale(1))
    if spec.bolts > 4:
        _extra_bolts(surf, body, extra=spec.bolts - 4)


def _extra_bolts(surf: pygame.Surface, body: pygame.Rect, *, extra: int) -> None:
    per_edge = max(1, extra // 4)
    y_top = body.top + 2
    y_bot = body.bottom - 3
    for i in range(1, per_edge + 1):
        x = body.left + (body.w * i) // (per_edge + 1)
        draw.rivet(surf, x, y_top)
        draw.rivet(surf, x, y_bot)
    x_l = body.left + 2
    x_r = body.right - 3
    for i in range(1, per_edge + 1):
        y = body.top + (body.h * i) // (per_edge + 1)
        draw.rivet(surf, x_l, y)
        draw.rivet(surf, x_r, y)


def _draw_accent(surf: pygame.Surface, body: pygame.Rect, spec: AccentStripeSpec) -> None:
    inset_px = _scale(4)
    r = body.inflate(-inset_px * 2, -inset_px * 2)
    draw.accent_band(surf, r, spec.side, color=spec.color, thickness=max(1, spec.thickness))


def _draw_badge(
    surf: pygame.Surface,
    body: pygame.Rect,
    spec: BadgeSpec,
    *,
    phase: str,
    frame: int,
) -> None:
    cx = body.centerx
    cy = body.centery
    size = _scale(spec.size_at_64)
    disc_r = size // 2 + 2
    draw.disc(surf, cx, cy, disc_r, darken(PALETTE.bg_raised, 0.35))
    draw.ring(surf, cx, cy, disc_r, lighten(PALETTE.bg_raised, 0.15))

    picto = spec.pictogram
    tint = spec.tint
    frames = max(1, config.STRUCTURE_FRAMES)
    rot = 0.0
    if phase == "active":
        rot = (frame / frames) * math.pi * 2
    if picto == "cocoa_beans":
        draw.insignia_cocoa_beans(surf, cx, cy, size, tint)
    elif picto == "sugar_crystals":
        draw.insignia_sugar_crystals(surf, cx, cy, size, tint)
    elif picto == "milk_drops":
        draw.insignia_milk_drops(surf, cx, cy, size, tint)
    elif picto == "chocolate_stack":
        draw.insignia_chocolate_stack(surf, cx, cy, size, tint)
    elif picto == "caramel_swirl":
        draw.insignia_caramel_swirl(surf, cx, cy, size, tint, rotation=rot)
    elif picto == "candy_swirl":
        draw.insignia_candy_swirl(surf, cx, cy, size, tint, rotation=rot)
    else:
        draw.fill_rect(surf, PALETTE.danger, cx - size // 2, cy - size // 2, size, size)


def _draw_lights(
    surf: pygame.Surface,
    body: pygame.Rect,
    spec: LightSpec,
    *,
    phase: str,
    frame: int,
) -> None:
    n = max(1, spec.count)
    y = body.top + _scale(3) + 1
    for i in range(n):
        x = body.left + body.w * (i + 1) // (n + 1)
        if phase == "idle":
            draw.led_dot(surf, x, y, PALETTE.muted, on=True)
            continue
        pat = spec.pattern or (1,)
        on = bool(pat[(frame + i) % len(pat)])
        draw.led_dot(surf, x, y, spec.color, on=on)


def _draw_overlay_under(
    surf: pygame.Surface,
    body: pygame.Rect,
    spec: OverlaySpec,
    accent: Color,
    *,
    phase: str,
    frame: int,
) -> None:
    if phase != "active":
        return
    if spec.kind == "glow":
        size = _scale(spec.size_at_64)
        frames = max(1, config.STRUCTURE_FRAMES)
        t = (frame % frames) / frames
        pulse = 0.5 + 0.5 * math.sin(t * math.pi * 2)
        draw.glow_halo(surf, body.centerx, body.centery, size // 2, accent, pulse=pulse)


def _draw_overlay_over(
    surf: pygame.Surface,
    body: pygame.Rect,
    spec: OverlaySpec,
    accent: Color,
    *,
    phase: str,
    frame: int,
) -> None:
    if phase != "active":
        return
    frames = max(1, config.STRUCTURE_FRAMES)
    t = (frame % frames) / frames
    if spec.kind == "auger":
        size = _scale(spec.size_at_64)
        cx = body.centerx
        cy = body.centery - _scale(2)
        draw.auger_head(surf, cx, cy, size, phase=t)
    elif spec.kind == "steam":
        size = _scale(spec.size_at_64)
        cx = body.centerx
        cy = body.top + _scale(8)
        draw.steam_plume(surf, cx, cy, size, phase=t, tint=accent)
