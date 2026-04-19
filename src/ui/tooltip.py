"""World-hover tooltip: a compact, animated panel that follows the mouse.

The tooltip reads from :class:`StructureInfo` (see ``ui.info``) so the
exact same data also populates the selected-structure menu. Visuals
reuse the same palette / typography / bevel helpers as the HUD and
toolbar so everything stays consistent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..design.palette import PALETTE, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from .info import InfoRow, StructureInfo

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


_PAD = THEME.spacing.md
_ROW_GAP = 4
_CHIP = 8
_ACCENT_STRIPE = 3
_SHADOW_ALPHA = 140
_MOUSE_OFFSET = (18, 14)


class WorldTooltip:
    """Fade-in tooltip anchored to the mouse."""

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self._fade = AnimValue(value=0.0, target=0.0, speed=16.0)
        self._info: StructureInfo | None = None
        self._mouse: tuple[int, int] = (0, 0)
        self._avoid: pygame.Rect | None = None

    # -- API ---------------------------------------------------------------

    def set(
        self,
        info: StructureInfo | None,
        mouse_pos: tuple[int, int],
        avoid: pygame.Rect | None = None,
    ) -> None:
        self._info = info if info is not None else self._info  # keep last info for fade out
        if info is None:
            self._fade.to(0.0)
        else:
            self._info = info
            self._fade.to(1.0)
        self._mouse = mouse_pos
        self._avoid = avoid

    def clear(self) -> None:
        self._info = None
        self._fade.set(0.0)

    def update(self, dt: float) -> None:
        self._fade.update(dt)

    @property
    def visible(self) -> bool:
        return self._info is not None and self._fade.value > 0.01

    # -- render ------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        if not self.visible or self._info is None:
            return

        alpha = max(0.0, min(1.0, self._fade.value))
        info = self._info

        # Pre-render every text line so we can measure the box exactly.
        title_surf = self.assets.render_text(
            info.title, TYPE.h2, PALETTE.text_strong
        )
        subtitle_surf = self.assets.render_text(
            info.subtitle, TYPE.caption, PALETTE.muted
        )

        rows = info.tooltip_rows
        row_labels: list[pygame.Surface] = []
        row_values: list[pygame.Surface] = []
        for r in rows:
            row_labels.append(
                self.assets.render_text(r.label, TYPE.caption, PALETTE.muted)
            )
            value_color = r.accent if r.accent is not None else PALETTE.text_strong
            row_values.append(
                self.assets.render_text(r.value, TYPE.body, value_color)
            )

        row_h = max(
            (row_values[i].get_height() for i in range(len(rows))),
            default=0,
        )
        inner_w = max(
            title_surf.get_width(),
            subtitle_surf.get_width(),
            max(
                (
                    row_labels[i].get_width()
                    + _CHIP
                    + THEME.spacing.sm
                    + row_values[i].get_width()
                    + THEME.spacing.lg
                    for i in range(len(rows))
                ),
                default=0,
            ),
        )
        inner_h = (
            title_surf.get_height()
            + 2
            + subtitle_surf.get_height()
            + (THEME.spacing.sm if rows else 0)
            + max(0, len(rows)) * (row_h + _ROW_GAP)
            - (_ROW_GAP if rows else 0)
        )

        panel_w = inner_w + _PAD * 2 + _ACCENT_STRIPE
        panel_h = inner_h + _PAD * 2

        # Position: mouse + offset, slide up a touch while fading in.
        slide = int((1.0 - alpha) * 6)
        px = self._mouse[0] + _MOUSE_OFFSET[0]
        py = self._mouse[1] + _MOUSE_OFFSET[1] + slide

        rect = pygame.Rect(px, py, panel_w, panel_h)
        rect = self._clamp(rect, surface.get_rect(), self._avoid)

        # Drop shadow
        shadow_alpha = int(_SHADOW_ALPHA * alpha)
        with acquired((rect.w + 8, rect.h + 8)) as shadow:
            shadow.fill(with_alpha(PALETTE.bg_deep, shadow_alpha))
            surface.blit(shadow, (rect.x - 2, rect.y + 4))

        # Panel body
        panel_alpha = int(255 * alpha)
        with acquired(rect.size) as panel:
            beveled_panel(
                panel,
                pygame.Rect(0, 0, rect.w, rect.h),
                fill=PALETTE.bg_deep,
                border=PALETTE.line,
            )
            # Accent stripe on the left edge.
            stripe = pygame.Rect(0, 2, _ACCENT_STRIPE, rect.h - 4)
            pygame.draw.rect(panel, info.accent, stripe)

            # Title + subtitle
            tx = _PAD + _ACCENT_STRIPE
            ty = _PAD
            panel.blit(title_surf, (tx, ty))
            ty += title_surf.get_height() + 2
            panel.blit(subtitle_surf, (tx, ty))
            ty += subtitle_surf.get_height()

            if rows:
                ty += THEME.spacing.sm
                # Subtle divider
                pygame.draw.line(
                    panel,
                    PALETTE.line,
                    (tx, ty - THEME.spacing.sm // 2),
                    (rect.w - _PAD, ty - THEME.spacing.sm // 2),
                )

            for i, r in enumerate(rows):
                label_s = row_labels[i]
                value_s = row_values[i]
                row_y = ty + i * (row_h + _ROW_GAP) + (row_h - label_s.get_height()) // 2
                cx = tx
                if r.item is not None:
                    chip = pygame.Rect(
                        cx,
                        ty + i * (row_h + _ROW_GAP) + (row_h - _CHIP) // 2,
                        _CHIP,
                        _CHIP,
                    )
                    pygame.draw.rect(panel, r.item.color, chip)
                    pygame.draw.rect(panel, PALETTE.line, chip, 1)
                    cx += _CHIP + THEME.spacing.sm
                panel.blit(label_s, (cx, row_y))
                # Right-aligned value
                vx = rect.w - _PAD - value_s.get_width()
                vy = ty + i * (row_h + _ROW_GAP) + (row_h - value_s.get_height()) // 2
                panel.blit(value_s, (vx, vy))

            panel.set_alpha(panel_alpha)
            surface.blit(panel, rect.topleft)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _clamp(
        rect: pygame.Rect,
        bounds: pygame.Rect,
        avoid: pygame.Rect | None,
    ) -> pygame.Rect:
        r = rect.copy()
        margin = 8
        if r.right > bounds.right - margin:
            r.right = bounds.right - margin
        if r.bottom > bounds.bottom - margin:
            r.bottom = bounds.bottom - margin
        if r.left < bounds.left + margin:
            r.left = bounds.left + margin
        if r.top < bounds.top + margin:
            r.top = bounds.top + margin
        # Avoid covering the toolbar rect (push above if overlapping).
        if avoid is not None and r.colliderect(avoid):
            shifted = r.copy()
            shifted.bottom = avoid.top - 6
            if shifted.top >= bounds.top + margin:
                r = shifted
        return r

    def _row_line_surfaces(self, rows: tuple[InfoRow, ...]):  # pragma: no cover - unused helper
        return rows
