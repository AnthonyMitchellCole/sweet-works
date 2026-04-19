"""Live performance HUD: tick/render/FPS stats with a smooth sparkline."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..core import config
from ..core.perf import PerfSnapshot
from ..design import easing
from ..design.palette import PALETTE, darken, lighten
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.pixel import beveled_panel

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


PANEL_W: int = 280
PANEL_H: int = 132
ROW_H: int = 18


def _fmt_ms(v: float) -> str:
    if v <= 0.0:
        return "   -- ms"
    return f"{v:>5.2f} ms"


def _fmt_int(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}k"
    return str(v)


class PerfHUD:
    """A single stat panel rendered in the top-right of the screen."""

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self.visible: bool = False
        self._pass: bool = True

    def toggle(self) -> None:
        self.visible = not self.visible

    def set_pass(self, ok: bool) -> None:
        self._pass = ok

    # ---- render ----------------------------------------------------------

    def render(
        self,
        surface: pygame.Surface,
        snap: PerfSnapshot,
        *,
        gates: tuple[float, float] | None = None,
    ) -> None:
        if not self.visible:
            return
        sw, _ = surface.get_size()
        x = sw - PANEL_W - THEME.spacing.lg
        y = THEME.spacing.lg + 48 + THEME.spacing.sm  # below the main HUD
        rect = pygame.Rect(x, y, PANEL_W, PANEL_H)
        beveled_panel(surface, rect, fill=PALETTE.bg_base, border=PALETTE.line)

        title = self.assets.render_text("PERF", TYPE.label, PALETTE.primary)
        surface.blit(title, (rect.x + THEME.spacing.sm, rect.y + 6))

        badge_color = PALETTE.success if self._pass else PALETTE.danger
        badge = self.assets.render_text(
            "PASS" if self._pass else "FAIL", TYPE.label, badge_color
        )
        surface.blit(
            badge,
            (rect.right - badge.get_width() - THEME.spacing.sm, rect.y + 6),
        )

        row_y = rect.y + 22
        row_y = self._row(surface, rect, row_y, "FPS", f"{snap.fps:>6.1f}")
        row_y = self._row(
            surface,
            rect,
            row_y,
            "frame",
            _fmt_ms(snap.frame_ms_p95),
            warn=gates and snap.frame_ms_p95 > config.GATE_RENDER_FRAME_P95_MS,
        )
        row_y = self._row(
            surface,
            rect,
            row_y,
            "tick p95",
            _fmt_ms(snap.tick_ms_p95),
            warn=gates and snap.tick_ms_p95 > config.GATE_BELT_TICK_P95_MS,
        )
        row_y = self._row(
            surface,
            rect,
            row_y,
            "tick max",
            _fmt_ms(snap.tick_ms_max),
            warn=gates and snap.tick_ms_max > config.GATE_BELT_TICK_MAX_MS,
        )
        row_y = self._row(
            surface, rect, row_y, "render p95", _fmt_ms(snap.render_ms_p95)
        )
        row_y = self._row(
            surface,
            rect,
            row_y,
            "items",
            f"{_fmt_int(snap.item_count):>6}  vis {_fmt_int(snap.visible_items)}",
        )

        self._sparkline(
            surface,
            pygame.Rect(rect.x + THEME.spacing.sm, rect.bottom - 20, rect.w - THEME.spacing.sm * 2, 14),
            snap.samples_tick,
            color=PALETTE.secondary,
        )

    def _row(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        y: int,
        label: str,
        value: str,
        *,
        warn: bool | None = False,
    ) -> int:
        lbl = self.assets.render_text(label, TYPE.caption, PALETTE.muted)
        surface.blit(lbl, (rect.x + THEME.spacing.sm, y))
        color = PALETTE.danger if warn else PALETTE.text_strong
        val = self.assets.render_text(value, TYPE.mono, color)
        surface.blit(val, (rect.right - val.get_width() - THEME.spacing.sm, y - 2))
        return y + ROW_H

    def _sparkline(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        samples: list[float],
        *,
        color,
    ) -> None:
        pygame.draw.rect(surface, darken(PALETTE.bg_deep, 0.1), rect)
        pygame.draw.rect(surface, PALETTE.line, rect, 1)
        if len(samples) < 2:
            return
        n = len(samples)
        hi = max(samples)
        lo = min(samples)
        span = max(1e-6, hi - lo)
        prev = None
        for i, v in enumerate(samples):
            x = rect.x + 1 + int((rect.w - 2) * easing.out_quint(i / max(1, n - 1)))
            t = (v - lo) / span
            y = rect.bottom - 2 - int((rect.h - 3) * t)
            if prev is not None:
                pygame.draw.line(surface, color, prev, (x, y), 1)
            prev = (x, y)
        if prev is not None:
            pygame.draw.rect(
                surface,
                lighten(color, 0.2),
                pygame.Rect(prev[0] - 1, prev[1] - 1, 3, 3),
            )


__all__ = ["PerfHUD"]
