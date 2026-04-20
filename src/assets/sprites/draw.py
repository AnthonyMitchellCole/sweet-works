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


def insignia_cocoa_beans(
    surf: pygame.Surface, cx: int, cy: int, size: int, base: Color
) -> None:
    """Cluster of 3 cocoa beans (ovals) with a cream highlight stroke."""
    hi = lighten(base, 0.35)
    sh = darken(base, 0.35)
    bw = max(3, size // 3)
    bh = max(2, size // 5)

    def bean(bcx: int, bcy: int) -> None:
        # Body: shadow then base.
        for dy in range(-bh, bh + 1):
            span = max(1, bw - abs(dy))
            fill_rect(surf, sh, bcx - span, bcy + dy, span * 2, 1)
        for dy in range(-bh + 1, bh):
            span = max(1, bw - abs(dy) - 1)
            if span > 0:
                fill_rect(surf, base, bcx - span, bcy + dy, span * 2, 1)
        # Seam highlight down the middle.
        fill_rect(surf, hi, bcx - bw // 2, bcy, max(1, bw - 1), 1)

    bean(cx - bw, cy - bh)
    bean(cx + bw - 1, cy - bh // 2)
    bean(cx - bw // 2, cy + bh + 1)


def insignia_sugar_crystals(
    surf: pygame.Surface, cx: int, cy: int, size: int, base: Color
) -> None:
    """Three diamond prisms with a sparkle dot; uses pink-white tones."""
    hi = lighten(base, 0.25)
    sh = darken(base, 0.25)

    def diamond(dcx: int, dcy: int, s: int) -> None:
        for dy in range(-s, s + 1):
            span = s - abs(dy)
            if span >= 0:
                fill_rect(surf, sh, dcx - span, dcy + dy, span * 2 + 1, 1)
        for dy in range(-s + 1, s):
            span = s - abs(dy) - 1
            if span >= 0:
                fill_rect(surf, base, dcx - span, dcy + dy, span * 2 + 1, 1)
        # Top-left facet highlight.
        for i in range(s - 1):
            pixel(surf, hi, dcx - i, dcy - (s - 1 - i))

    s = max(2, size // 4)
    diamond(cx - s - 1, cy, s)
    diamond(cx + s + 1, cy - 1, s - 1)
    diamond(cx, cy + s, s)
    # Sparkle
    for dx, dy in ((0, -s - 2), (-1, -s - 2), (1, -s - 2), (0, -s - 3)):
        pixel(surf, lighten(hi, 0.4), cx + dx, cy + dy)


def insignia_milk_drops(
    surf: pygame.Surface, cx: int, cy: int, size: int, base: Color
) -> None:
    """Two plump droplets with a highlight blob."""
    hi = lighten(base, 0.25)
    sh = darken(base, 0.25)

    def drop(dcx: int, dcy: int, s: int) -> None:
        # Teardrop: round bottom, pointed top.
        for dy in range(-s, s + 1):
            if dy <= 0:
                span = max(0, s - abs(dy))
            else:
                span = max(0, s - int(dy * 0.3))
            if span <= 0:
                continue
            fill_rect(surf, sh, dcx - span, dcy + dy, span * 2, 1)
        for dy in range(-s + 1, s):
            if dy <= 0:
                span = max(0, s - abs(dy) - 1)
            else:
                span = max(0, s - int(dy * 0.3) - 1)
            if span <= 0:
                continue
            fill_rect(surf, base, dcx - span, dcy + dy, span * 2, 1)
        # Highlight bubble
        fill_rect(surf, hi, dcx - max(1, s // 2), dcy + 1, max(1, s // 2), max(1, s // 3))

    d = max(3, size // 3)
    drop(cx - d, cy - 1, d)
    drop(cx + d, cy + 1, d - 1)


def insignia_chocolate_stack(
    surf: pygame.Surface, cx: int, cy: int, size: int, base: Color
) -> None:
    """Three chocolate bars stacked, each with embossed segments."""
    hi = lighten(base, 0.3)
    sh = darken(base, 0.35)
    plate_w = max(3, size)
    plate_h = max(2, size // 5)
    gap = max(1, plate_h // 2 + 1)
    total_h = plate_h * 3 + gap * 2
    top = cy - total_h // 2
    segs = 3
    for i in range(3):
        y = top + i * (plate_h + gap)
        bar_x = cx - plate_w // 2
        fill_rect(surf, sh, bar_x, y + plate_h - 1, plate_w, 1)
        fill_rect(surf, base, bar_x, y, plate_w, max(1, plate_h - 1))
        fill_rect(surf, hi, bar_x + 1, y, max(1, plate_w - 2), 1)
        # Embossed segment lines.
        for s in range(1, segs):
            sx = bar_x + (plate_w * s) // segs
            fill_rect(surf, sh, sx, y + 1, 1, max(1, plate_h - 2))


def insignia_caramel_swirl(
    surf: pygame.Surface,
    cx: int,
    cy: int,
    size: int,
    base: Color,
    *,
    rotation: float = 0.0,
) -> None:
    """Soft caramel blob with a swirling ribbon highlight."""
    hi = lighten(base, 0.3)
    sh = darken(base, 0.3)
    outer = max(3, size // 2)
    disc(surf, cx, cy, outer, sh)
    disc(surf, cx, cy, max(1, outer - 1), base)
    # Swirl ribbon: parametric spiral of pixels.
    turns = 2
    samples = max(10, outer * 3)
    for i in range(samples):
        t = i / samples
        a = rotation + t * turns * math.pi * 2
        r = outer * (1.0 - t)
        px = cx + int(round(math.cos(a) * r))
        py = cy + int(round(math.sin(a) * r))
        pixel(surf, hi, px, py)
        pixel(surf, hi, px, py - 1)


def insignia_candy_swirl(
    surf: pygame.Surface,
    cx: int,
    cy: int,
    size: int,
    base: Color,
    *,
    rotation: float = 0.0,
    arms: int = 5,
) -> None:
    """Pinwheel candy swirl: N curved arms around a central dot."""
    hi = lighten(base, 0.35)
    sh = darken(base, 0.3)
    outer = max(3, size // 2)
    inner = max(1, outer // 4)
    disc(surf, cx, cy, outer, sh)
    disc(surf, cx, cy, max(1, outer - 1), base)
    # Curved arms: sample a curve per arm and stamp 2x2 dots.
    steps = max(4, outer - 1)
    for arm_i in range(arms):
        base_a = rotation + arm_i * (2 * math.pi / arms)
        for s in range(steps):
            t = s / max(1, steps - 1)
            a = base_a + t * 1.2  # curve by 1.2 rad along the arm
            r = t * (outer - 1)
            px = cx + int(round(math.cos(a) * r))
            py = cy + int(round(math.sin(a) * r))
            fill_rect(surf, hi, px, py, 1, 1)
    disc(surf, cx, cy, inner, lighten(base, 0.55))


# ---------------------------------------------------------------------------
# State-overlay primitives
# ---------------------------------------------------------------------------


def auger_head(
    surf: pygame.Surface, cx: int, cy: int, size: int, *, phase: float
) -> None:
    """Corkscrew auger with its tip anchored at (cx, cy), shaft rising above.

    ``phase`` is a normalised animation position in ``[0, 1]``. The auger
    shakes and descends periodically to register an extraction "bite" at
    ``phase ~= 0.5``. The shaft is two offset pixel columns so it visually
    reads as a helical corkscrew rather than a straight bit.
    """
    shake = int(round(math.sin(phase * math.pi * 2) * max(1, size // 14)))
    descent = int(
        round((1 - math.cos(phase * math.pi * 2)) * 0.5 * max(1, size // 6))
    )
    metal = PALETTE.muted
    metal_hi = lighten(metal, 0.35)
    metal_sh = darken(metal, 0.3)
    shaft_w = max(3, size // 8)
    shaft_h = max(5, size // 2)
    tip_y = cy + descent
    shaft_x = cx - shaft_w // 2 + shake

    # Shaft backing (dim rectangle).
    shaft = pygame.Rect(shaft_x, tip_y - shaft_h, shaft_w, shaft_h)
    pygame.draw.rect(surf, metal_sh, shaft)

    # Helical highlight ribbon: offset pixel columns staggered by row to
    # simulate the twist of a corkscrew.
    twist = max(2, shaft_h // 6)
    for i in range(shaft.h):
        ox = ((i + int(phase * twist * 2)) % twist)
        lx = shaft.x + ox
        rx = shaft.x + shaft_w - 1 - ox
        pixel(surf, metal_hi, lx, shaft.y + i)
        pixel(surf, metal, rx, shaft.y + i)

    # Pointed tip with a bright highlight pixel.
    tip_h = max(2, size // 10)
    for i in range(tip_h):
        w = max(1, shaft_w - i * 2)
        pygame.draw.rect(
            surf,
            metal_hi if i == 0 else metal,
            pygame.Rect(cx - w // 2 + shake, tip_y + i, w, 1),
        )


def steam_plume(
    surf: pygame.Surface, cx: int, cy: int, size: int, *, phase: float, tint: Color
) -> None:
    """Three pastel steam puffs rising above (cx, cy).

    Each puff is a disc whose alpha decays with height and whose x jitters
    on a sine, creating a soft drift. ``phase`` is a normalised 0..1
    animation position; puffs are offset along it so they appear to rise
    continuously frame-to-frame.
    """
    if size <= 0:
        return
    puff_r_base = max(2, size // 10)
    stack = max(3, size // 6)
    # Build a scratch layer so we can alpha-blit cleanly.
    w = size
    h = size
    layer = new_surface((w, h))
    ox = w // 2
    oy = h - 1
    for i in range(stack):
        t = ((phase + i / stack) % 1.0)
        rise = int(t * (h - puff_r_base * 2))
        jitter = int(round(math.sin((phase + i * 0.37) * math.pi * 2) * puff_r_base))
        px = ox + jitter
        py = oy - rise - puff_r_base
        r = int(puff_r_base + (1.0 - t) * puff_r_base)
        alpha = int(max(20, 180 * (1.0 - t)))
        pygame.draw.circle(layer, with_alpha(lighten(tint, 0.45), alpha), (px, py), r)
        pygame.draw.circle(
            layer, with_alpha(lighten(tint, 0.7), min(255, alpha + 40)), (px, py), max(1, r - 2)
        )
    surf.blit(layer, (cx - w // 2, cy - h))


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
