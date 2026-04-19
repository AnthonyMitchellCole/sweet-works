"""Pixel-art drawing primitives for procedural sprite generation.

Pure functions operating on :class:`pygame.Surface` instances using only
the palette. Every size is expressed as an authoring value at ``TILE=64``
and scaled proportionally by callers, so the same spec renders cleanly at
any tile size.
"""

from __future__ import annotations

import math

import pygame

from ...design.palette import PALETTE, Color, darken, lighten, with_alpha


def new_surface(size: tuple[int, int], *, alpha: bool = True) -> pygame.Surface:
    flags = pygame.SRCALPHA if alpha else 0
    return pygame.Surface(size, flags)


def fill_rect(surf: pygame.Surface, color: Color, x: int, y: int, w: int, h: int) -> None:
    if w <= 0 or h <= 0:
        return
    surf.fill(color, rect=pygame.Rect(x, y, w, h))


def pixel(surf: pygame.Surface, color: Color, x: int, y: int) -> None:
    if 0 <= x < surf.get_width() and 0 <= y < surf.get_height():
        surf.set_at((x, y), color)


# ---------------------------------------------------------------------------
# Chassis primitives
# ---------------------------------------------------------------------------


def bevel_plate(
    surf: pygame.Surface,
    rect: pygame.Rect,
    *,
    plate: Color,
    highlight: Color | None = None,
    shadow: Color | None = None,
) -> None:
    """Bevelled metal plate: flat fill + top/left highlight + bottom/right shadow."""
    hi = highlight if highlight is not None else lighten(plate, 0.18)
    sh = shadow if shadow is not None else darken(plate, 0.25)
    pygame.draw.rect(surf, plate, rect)
    pygame.draw.line(surf, hi, rect.topleft, (rect.right - 1, rect.top))
    pygame.draw.line(surf, hi, rect.topleft, (rect.left, rect.bottom - 1))
    pygame.draw.line(
        surf, sh, (rect.left, rect.bottom - 1), (rect.right - 1, rect.bottom - 1)
    )
    pygame.draw.line(
        surf, sh, (rect.right - 1, rect.top), (rect.right - 1, rect.bottom - 1)
    )


def rivet(surf: pygame.Surface, cx: int, cy: int, *, color: Color | None = None) -> None:
    c = color if color is not None else PALETTE.muted
    fill_rect(surf, c, cx, cy, 1, 1)


def rivet_corners(surf: pygame.Surface, rect: pygame.Rect, *, inset: int = 2) -> None:
    for x, y in (
        (rect.left + inset, rect.top + inset),
        (rect.right - 1 - inset, rect.top + inset),
        (rect.left + inset, rect.bottom - 1 - inset),
        (rect.right - 1 - inset, rect.bottom - 1 - inset),
    ):
        rivet(surf, x, y)


def disc(surf: pygame.Surface, cx: int, cy: int, radius: int, color: Color) -> None:
    if radius <= 0:
        return
    pygame.draw.circle(surf, color, (cx, cy), radius)


def ring(
    surf: pygame.Surface,
    cx: int,
    cy: int,
    radius: int,
    color: Color,
    *,
    thickness: int = 1,
) -> None:
    if radius <= 0:
        return
    pygame.draw.circle(surf, color, (cx, cy), radius, thickness)


def led_dot(surf: pygame.Surface, cx: int, cy: int, color: Color, *, on: bool) -> None:
    """Crisp 2x2 LED. When off, the base is dimmed; when on, a 1 px sparkle is added."""
    base = color if on else darken(color, 0.65)
    fill_rect(surf, base, cx - 1, cy - 1, 2, 2)
    if on:
        pixel(surf, lighten(base, 0.45), cx, cy)


def vent_slats(
    surf: pygame.Surface, rect: pygame.Rect, color: Color, *, count: int = 3
) -> None:
    if rect.h <= 0 or rect.w <= 0 or count <= 0:
        return
    step = max(2, rect.h // count)
    y = rect.top + 1
    while y < rect.bottom - 1:
        pygame.draw.line(surf, color, (rect.left + 1, y), (rect.right - 2, y))
        y += step


def accent_band(
    surf: pygame.Surface,
    rect: pygame.Rect,
    side: str,
    *,
    color: Color,
    thickness: int = 2,
) -> None:
    """Coloured stripe hugging one edge of the chassis."""
    t = max(1, thickness)
    hi = lighten(color, 0.3)
    if side == "N":
        fill_rect(surf, color, rect.left, rect.top, rect.w, t)
        fill_rect(surf, hi, rect.left, rect.top, rect.w, 1)
    elif side == "S":
        fill_rect(surf, color, rect.left, rect.bottom - t, rect.w, t)
        fill_rect(surf, hi, rect.left, rect.bottom - 1, rect.w, 1)
    elif side == "W":
        fill_rect(surf, color, rect.left, rect.top, t, rect.h)
        fill_rect(surf, hi, rect.left, rect.top, 1, rect.h)
    else:  # "E"
        fill_rect(surf, color, rect.right - t, rect.top, t, rect.h)
        fill_rect(surf, hi, rect.right - 1, rect.top, 1, rect.h)


# ---------------------------------------------------------------------------
# Insignia pictograms (shared "item family" vocabulary)
# ---------------------------------------------------------------------------


def insignia_ore_chunks(
    surf: pygame.Surface, cx: int, cy: int, size: int, base: Color
) -> None:
    """Cluster of 3 chunks, rhyming with the iron/copper item icons."""
    hi = lighten(base, 0.3)
    sh = darken(base, 0.35)
    s = max(2, size // 3)
    fill_rect(surf, sh, cx - s, cy - s // 2, s * 2, s + 1)
    fill_rect(surf, base, cx - s, cy - s // 2, s * 2, max(1, s - 1))
    fill_rect(surf, hi, cx - s + 1, cy - s // 2 + 1, s * 2 - 2, 1)
    fill_rect(surf, sh, cx - s - s // 2, cy - s // 2 + s // 2, s, s - 1)
    fill_rect(surf, base, cx - s - s // 2, cy - s // 2 + s // 2, s, max(1, s - 2))
    fill_rect(surf, sh, cx + s, cy, s - 1, s - 1)
    fill_rect(surf, base, cx + s, cy, s - 1, max(1, s - 2))


def insignia_coal_lumps(
    surf: pygame.Surface, cx: int, cy: int, size: int, base: Color
) -> None:
    hi = lighten(base, 0.55)
    s = max(2, size // 3)
    fill_rect(surf, base, cx - s, cy - s // 2, s * 2, s + 1)
    fill_rect(surf, base, cx - s + 1, cy - s // 2 - 1, s * 2 - 2, 2)
    fill_rect(surf, base, cx - s - 1, cy + s // 2, s + 1, s - 1)
    fill_rect(surf, base, cx + s - 2, cy + s // 2 - 1, s - 1, s)
    for dx, dy in ((-s + 1, 0), (s - 2, -s // 2 + 1), (0, s // 2)):
        pixel(surf, hi, cx + dx, cy + dy)


def insignia_plate_stack(
    surf: pygame.Surface, cx: int, cy: int, size: int, base: Color
) -> None:
    hi = lighten(base, 0.3)
    sh = darken(base, 0.3)
    plate_w = max(3, size)
    plate_h = max(1, size // 5)
    gap = max(1, plate_h)
    total_h = plate_h * 3 + gap * 2
    top = cy - total_h // 2
    for i in range(3):
        y = top + i * (plate_h + gap)
        fill_rect(surf, sh, cx - plate_w // 2, y + plate_h - 1, plate_w, 1)
        fill_rect(surf, base, cx - plate_w // 2, y, plate_w, max(1, plate_h - 1))
        fill_rect(surf, hi, cx - plate_w // 2 + 1, y, max(1, plate_w - 2), 1)


def insignia_pinion(
    surf: pygame.Surface,
    cx: int,
    cy: int,
    size: int,
    base: Color,
    *,
    rotation: float = 0.0,
    teeth: int = 6,
) -> None:
    """Gear with N teeth arranged around a central hub."""
    hi = lighten(base, 0.25)
    sh = darken(base, 0.3)
    outer = max(3, size // 2)
    inner = max(1, outer // 3)
    disc(surf, cx, cy, outer, sh)
    disc(surf, cx, cy, max(1, outer - 1), base)
    disc(surf, cx, cy, inner, darken(base, 0.55))
    for i in range(teeth):
        a = rotation + i * (2 * math.pi / teeth)
        tx = cx + int(round(math.cos(a) * (outer + 1)))
        ty = cy + int(round(math.sin(a) * (outer + 1)))
        fill_rect(surf, hi, tx - 1, ty - 1, 2, 2)


# ---------------------------------------------------------------------------
# State-overlay primitives
# ---------------------------------------------------------------------------


def drill_head(
    surf: pygame.Surface, cx: int, cy: int, size: int, *, phase: float
) -> None:
    """Vertical drill with its tip anchored at (cx, cy), shaft rising above.

    ``phase`` is a normalised animation position in ``[0, 1]``. The bit
    shakes and periodically descends to register an "impact" at
    ``phase ~= 0.5``.
    """
    shake = int(round(math.sin(phase * math.pi * 2) * max(1, size // 14)))
    descent = int(
        round((1 - math.cos(phase * math.pi * 2)) * 0.5 * max(1, size // 6))
    )
    metal = PALETTE.muted
    metal_hi = lighten(metal, 0.35)
    shaft_w = max(2, size // 10)
    shaft_h = max(4, size // 2)
    tip_y = cy + descent
    shaft = pygame.Rect(cx - shaft_w // 2 + shake, tip_y - shaft_h, shaft_w, shaft_h)
    pygame.draw.rect(surf, darken(metal, 0.25), shaft)
    pygame.draw.rect(surf, metal_hi, pygame.Rect(shaft.x, shaft.y, 1, shaft.h))
    tip_h = max(2, size // 10)
    for i in range(tip_h):
        w = max(1, shaft_w - i * 2)
        pygame.draw.rect(
            surf,
            metal_hi if i == 0 else metal,
            pygame.Rect(cx - w // 2 + shake, tip_y + i, w, 1),
        )


def glow_halo(
    surf: pygame.Surface,
    cx: int,
    cy: int,
    radius: int,
    color: Color,
    *,
    pulse: float = 1.0,
) -> None:
    """Soft radial halo used by assembler "active" overlays."""
    if radius <= 0:
        return
    pulse = max(0.0, min(1.0, pulse))
    inner_alpha = int(70 + 120 * pulse)
    outer_alpha = int(30 + 50 * pulse)
    d = radius * 2 + 4
    halo = new_surface((d, d))
    cc = (d // 2, d // 2)
    pygame.draw.circle(halo, with_alpha(color, outer_alpha), cc, radius + 1)
    pygame.draw.circle(halo, with_alpha(color, inner_alpha), cc, radius - 1)
    pygame.draw.circle(
        halo, with_alpha(lighten(color, 0.35), min(255, inner_alpha + 40)), cc, radius - 1, 1
    )
    surf.blit(halo, (cx - d // 2, cy - d // 2))
