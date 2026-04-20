"""Hover tooltip for the Research scene.

Near-mirror of :class:`~src.ui.tooltip.WorldTooltip` retargeted at
:class:`~src.research.info.ResearchInfo`. Shares the same drop-shadow
+ bevel + accent-stripe look so the two panels feel like siblings.
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
from ..research.info import ResearchInfo

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


_PAD = THEME.spacing.md
_ROW_GAP = 4
_CHIP = 8
_ACCENT_STRIPE = 3
_SHADOW_ALPHA = 140
_MOUSE_OFFSET = (18, 14)


class ResearchTooltip:
    """Mouse-anchored tooltip summarising a :class:`ResearchInfo`."""

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self._fade = AnimValue(value=0.0, target=0.0, speed=16.0)
        self._info: ResearchInfo | None = None
        self._mouse: tuple[int, int] = (0, 0)
        self._avoid: pygame.Rect | None = None

    # -- API ---------------------------------------------------------------

    def set(
        self,
        info: ResearchInfo | None,
        mouse_pos: tuple[int, int],
        avoid: pygame.Rect | None = None,
    ) -> None:
        self._info = info if info is not None else self._info
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

        title_surf = self.assets.render_text(
            info.title, TYPE.h2, PALETTE.text_strong
        )
        category_surf = self.assets.render_text(
            info.category.upper(), TYPE.label, PALETTE.muted
        )
        status_surf = self.assets.render_text(
            _status_label(info), TYPE.caption, info.accent
        )

        # Word-wrap the blurb at a comfortable width.
        blurb_lines = _wrap(info.blurb, max_chars=38)
        blurb_surfs = [
            self.assets.render_text(line, TYPE.caption, PALETTE.text_body)
            for line in blurb_lines
        ]

        effect_rows = info.effect_rows
        eff_labels: list[pygame.Surface] = []
        eff_values: list[pygame.Surface] = []
        for r in effect_rows:
            eff_labels.append(
                self.assets.render_text(r.label, TYPE.caption, PALETTE.muted)
            )
            eff_values.append(
                self.assets.render_text(r.value, TYPE.body, PALETTE.text_strong)
            )

        prereq_surfs: list[pygame.Surface] = []
        for p in info.prereq_rows:
            glyph = "✓" if p.satisfied else "✕"
            color = PALETTE.success if p.satisfied else PALETTE.danger
            text = f"{glyph}  {p.name}"
            prereq_surfs.append(self.assets.render_text(text, TYPE.caption, color))

        row_h = max(
            (eff_values[i].get_height() for i in range(len(effect_rows))),
            default=0,
        )

        effects_w = max(
            (
                eff_labels[i].get_width()
                + _CHIP
                + THEME.spacing.sm
                + eff_values[i].get_width()
                + THEME.spacing.lg
                for i in range(len(effect_rows))
            ),
            default=0,
        )
        prereq_w = max((s.get_width() for s in prereq_surfs), default=0)
        blurb_w = max((s.get_width() for s in blurb_surfs), default=0)

        inner_w = max(
            title_surf.get_width(),
            category_surf.get_width() + THEME.spacing.sm + status_surf.get_width(),
            blurb_w,
            effects_w,
            prereq_w,
        )

        inner_h = (
            category_surf.get_height()
            + 2
            + title_surf.get_height()
            + THEME.spacing.sm
        )
        if blurb_surfs:
            inner_h += sum(s.get_height() + 2 for s in blurb_surfs) + THEME.spacing.sm
        if effect_rows:
            inner_h += len(effect_rows) * (row_h + _ROW_GAP)
        if prereq_surfs:
            inner_h += (
                THEME.spacing.sm
                + sum(s.get_height() + 2 for s in prereq_surfs)
                - 2
            )

        panel_w = inner_w + _PAD * 2 + _ACCENT_STRIPE
        panel_h = inner_h + _PAD * 2

        slide = int((1.0 - alpha) * 6)
        px = self._mouse[0] + _MOUSE_OFFSET[0]
        py = self._mouse[1] + _MOUSE_OFFSET[1] + slide

        rect = pygame.Rect(px, py, panel_w, panel_h)
        rect = _clamp(rect, surface.get_rect(), self._avoid)

        shadow_alpha = int(_SHADOW_ALPHA * alpha)
        with acquired((rect.w + 8, rect.h + 8)) as shadow:
            shadow.fill(with_alpha(PALETTE.bg_deep, shadow_alpha))
            surface.blit(shadow, (rect.x - 2, rect.y + 4))

        panel_alpha = int(255 * alpha)
        with acquired(rect.size) as panel:
            beveled_panel(
                panel,
                pygame.Rect(0, 0, rect.w, rect.h),
                fill=PALETTE.bg_deep,
                border=PALETTE.line,
            )
            stripe = pygame.Rect(0, 2, _ACCENT_STRIPE, rect.h - 4)
            pygame.draw.rect(panel, info.accent, stripe)

            tx = _PAD + _ACCENT_STRIPE
            ty = _PAD
            panel.blit(category_surf, (tx, ty))
            # Status chip trailing the category text.
            chip_x = tx + category_surf.get_width() + THEME.spacing.sm
            chip_rect = pygame.Rect(
                chip_x - 3,
                ty - 1,
                status_surf.get_width() + 6,
                status_surf.get_height() + 2,
            )
            pygame.draw.rect(panel, with_alpha(info.accent, 40), chip_rect)
            pygame.draw.rect(panel, info.accent, chip_rect, 1)
            panel.blit(status_surf, (chip_x, ty))
            ty += category_surf.get_height() + 2
            panel.blit(title_surf, (tx, ty))
            ty += title_surf.get_height() + THEME.spacing.sm

            for s in blurb_surfs:
                panel.blit(s, (tx, ty))
                ty += s.get_height() + 2
            if blurb_surfs:
                ty += THEME.spacing.sm - 2
                pygame.draw.line(
                    panel,
                    PALETTE.line,
                    (tx, ty - THEME.spacing.sm // 2),
                    (rect.w - _PAD, ty - THEME.spacing.sm // 2),
                )

            for i in range(len(effect_rows)):
                label_s = eff_labels[i]
                value_s = eff_values[i]
                row_y = ty + i * (row_h + _ROW_GAP) + (row_h - label_s.get_height()) // 2
                chip = pygame.Rect(
                    tx,
                    ty + i * (row_h + _ROW_GAP) + (row_h - _CHIP) // 2,
                    _CHIP,
                    _CHIP,
                )
                pygame.draw.rect(panel, info.accent, chip)
                pygame.draw.rect(panel, PALETTE.line, chip, 1)
                panel.blit(label_s, (tx + _CHIP + THEME.spacing.sm, row_y))
                vx = rect.w - _PAD - value_s.get_width()
                vy = ty + i * (row_h + _ROW_GAP) + (row_h - value_s.get_height()) // 2
                panel.blit(value_s, (vx, vy))

            if effect_rows:
                ty += len(effect_rows) * (row_h + _ROW_GAP)

            if prereq_surfs:
                ty += THEME.spacing.sm
                pygame.draw.line(
                    panel,
                    PALETTE.line,
                    (tx, ty - THEME.spacing.sm // 2),
                    (rect.w - _PAD, ty - THEME.spacing.sm // 2),
                )
                for s in prereq_surfs:
                    panel.blit(s, (tx, ty))
                    ty += s.get_height() + 2

            panel.set_alpha(panel_alpha)
            surface.blit(panel, rect.topleft)


# -- helpers ----------------------------------------------------------------


def _status_label(info: ResearchInfo) -> str:
    return {
        "researched": "RESEARCHED",
        "available": "AVAILABLE",
        "locked": "LOCKED",
    }[info.status]


def _wrap(text: str, *, max_chars: int) -> list[str]:
    """Naive word-wrap tuned for short research blurbs (no font metrics)."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for w in words:
        add = len(w) + (1 if current else 0)
        if length + add > max_chars and current:
            lines.append(" ".join(current))
            current = [w]
            length = len(w)
        else:
            current.append(w)
            length += add
    if current:
        lines.append(" ".join(current))
    return lines


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
    if avoid is not None and r.colliderect(avoid):
        shifted = r.copy()
        shifted.bottom = avoid.top - 6
        if shifted.top >= bounds.top + margin:
            r = shifted
    return r


__all__ = ["ResearchTooltip"]
