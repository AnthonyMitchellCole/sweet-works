"""Top HUD: resource counters, FPS, tick indicator.

Each resource cell is a proper hit-tested widget: hovering it lifts the
icon, draws a soft halo in the item's accent colour and surfaces a
full, animated tooltip with the item name and rolling produced /
consumed / net rates. Rates are driven by the ``item.produced`` and
``item.consumed`` events so the numbers reflect what's actually
happening in the world, not just nominal recipe throughput.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pygame

from ..audio.sfx import SFX
from ..core.events import EventBus
from ..design.palette import PALETTE, darken, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..items.item_type import ItemType
from ..items.registry import ITEMS
from ..rendering.animation import AnimValue
from ..rendering.pixel import beveled_panel
from ..rendering.pool import acquired
from ..world.direction import Direction

if TYPE_CHECKING:
    from ..assets.loader import AssetLoader


# -- rolling rate tracker -------------------------------------------------


class RateTracker:
    """Per-item rolling counter over 1-second buckets.

    Stores ``_WINDOW`` seconds of history for both produced and
    consumed events. ``per_minute(window_s)`` returns the rate scaled
    to /min, and auto-clamps during warm-up so the numbers read
    correctly in the first few seconds after a scene starts.
    """

    _WINDOW: int = 60  # seconds of history kept per item.

    __slots__ = (
        "_consumed",
        "_elapsed",
        "_head",
        "_last_sec",
        "_produced",
    )

    def __init__(self) -> None:
        self._produced: list[int] = [0] * self._WINDOW
        self._consumed: list[int] = [0] * self._WINDOW
        self._head: int = 0
        self._last_sec: int = -1
        self._elapsed: float = 0.0

    def add_produced(self, n: int = 1) -> None:
        self._produced[self._head] += n

    def add_consumed(self, n: int = 1) -> None:
        self._consumed[self._head] += n

    def tick_time(self, world_time: float) -> None:
        """Advance the ring buffer to the current world-time second."""
        self._elapsed = max(self._elapsed, world_time)
        if self._last_sec < 0:
            self._last_sec = int(world_time)
            return
        current_sec = int(world_time)
        while self._last_sec < current_sec:
            self._last_sec += 1
            self._head = (self._head + 1) % self._WINDOW
            self._produced[self._head] = 0
            self._consumed[self._head] = 0

    def _sum(self, buf: list[int], window_s: int) -> int:
        window_s = max(1, min(self._WINDOW, window_s))
        h = self._head
        total = 0
        for i in range(window_s):
            total += buf[(h - i) % self._WINDOW]
        return total

    def per_minute_produced(self, window_s: int) -> float:
        return self._rate(self._produced, window_s)

    def per_minute_consumed(self, window_s: int) -> float:
        return self._rate(self._consumed, window_s)

    def _rate(self, buf: list[int], window_s: int) -> float:
        window_s = max(1, min(self._WINDOW, window_s))
        total = self._sum(buf, window_s)
        # During warm-up, dividing by the clamped elapsed window gives
        # the true observed rate instead of under-reporting.
        effective = min(float(window_s), max(0.25, self._elapsed))
        return (total / effective) * 60.0

    def net_series(self, window_s: int = 60, smooth: int = 3) -> list[float]:
        """Per-second net (produced - consumed) rates, oldest -> newest.

        Values are in items/minute. ``smooth`` applies a centred moving
        average across the returned series so single-tick spikes don't
        dominate the sparkline. Empty buckets older than ``_elapsed``
        are returned as 0 so the line naturally starts flat on a fresh
        scene.
        """
        window_s = max(1, min(self._WINDOW, window_s))
        smooth = max(1, int(smooth))
        h = self._head
        raw: list[float] = []
        # Oldest first: index = window_s - 1, window_s - 2, ..., 0 ticks ago.
        for i in range(window_s - 1, -1, -1):
            idx = (h - i) % self._WINDOW
            raw.append(float(self._produced[idx] - self._consumed[idx]) * 60.0)
        if smooth <= 1:
            return raw
        # Centred moving average of width `smooth`.
        half = smooth // 2
        out: list[float] = []
        n = len(raw)
        for i in range(n):
            lo = max(0, i - half)
            hi = min(n, i + half + 1)
            s = 0.0
            for j in range(lo, hi):
                s += raw[j]
            out.append(s / (hi - lo))
        return out


# -- cell + tooltip dataclasses --------------------------------------------


@dataclass
class _Cell:
    item: ItemType
    rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    hover: AnimValue = field(default_factory=lambda: AnimValue(speed=18.0))


# -- tooltip ----------------------------------------------------------------


_TT_PAD = THEME.spacing.md
_TT_ROW_GAP = 4
_TT_STRIPE = 3
_TT_SHADOW_ALPHA = 150
_TT_SPARK_H = 22
_TT_SPARK_WINDOW = 60  # seconds of history plotted in the sparkline


class _HudTooltip:
    """Fade + slide tooltip anchored below an HUD cell."""

    def __init__(self, assets: AssetLoader) -> None:
        self.assets = assets
        self._fade = AnimValue(value=0.0, speed=16.0)
        self._pos_x = AnimValue(speed=22.0)
        self._pos_y = AnimValue(speed=22.0)
        self._current_item: ItemType | None = None
        self._target: tuple[int, int] = (0, 0)
        self._positioned: bool = False

    # -- API --------------------------------------------------------

    def set_target(
        self,
        item: ItemType | None,
        anchor: tuple[int, int] | None,
    ) -> None:
        if item is None or anchor is None:
            self._fade.to(0.0)
            return
        if item is not self._current_item:
            # When switching cells while the panel is already visible,
            # glide to the new position; when fully hidden, snap so the
            # first fade-in doesn't streak across the screen.
            if self._fade.value < 0.05 or not self._positioned:
                self._pos_x.set(anchor[0])
                self._pos_y.set(anchor[1])
                self._positioned = True
            self._current_item = item
        self._target = anchor
        self._pos_x.to(anchor[0])
        self._pos_y.to(anchor[1])
        self._fade.to(1.0)

    def update(self, dt: float) -> None:
        self._fade.update(dt)
        self._pos_x.update(dt)
        self._pos_y.update(dt)

    @property
    def visible(self) -> bool:
        return self._current_item is not None and self._fade.value > 0.01

    @property
    def current_item(self) -> ItemType | None:
        return self._current_item

    # -- render -----------------------------------------------------

    def render(
        self,
        surface: pygame.Surface,
        tracker: RateTracker,
        total_count: int,
    ) -> None:
        if not self.visible or self._current_item is None:
            return

        alpha = max(0.0, min(1.0, self._fade.value))
        item = self._current_item

        prod_1m = tracker.per_minute_produced(60)
        prod_10 = tracker.per_minute_produced(10)
        cons_1m = tracker.per_minute_consumed(60)
        cons_10 = tracker.per_minute_consumed(10)
        net_1m = prod_1m - cons_1m

        # -- prerender text so we can size the panel exactly.
        title_surf = self.assets.render_text(
            item.name, TYPE.h2, PALETTE.text_strong
        )
        subtitle_surf = self.assets.render_text(
            "Resource flow", TYPE.caption, PALETTE.muted
        )

        rows = self._build_rows(total_count, prod_1m, prod_10, cons_1m, cons_10, net_1m)
        row_labels = [
            self.assets.render_text(r.label, TYPE.caption, PALETTE.muted) for r in rows
        ]
        row_values = [
            self.assets.render_text(r.value, TYPE.body, r.value_color) for r in rows
        ]
        sub_labels: list[pygame.Surface | None] = []
        sub_values: list[pygame.Surface | None] = []
        for r in rows:
            if r.sub_label is not None and r.sub_value is not None:
                sub_labels.append(
                    self.assets.render_text(r.sub_label, TYPE.label, PALETTE.muted)
                )
                sub_values.append(
                    self.assets.render_text(r.sub_value, TYPE.label, PALETTE.muted)
                )
            else:
                sub_labels.append(None)
                sub_values.append(None)

        icon = self.assets.item_icon(item.id)
        icon_w = icon.get_width()
        icon_h = icon.get_height()

        # Layout maths -------------------------------------------------
        header_h = max(title_surf.get_height(), icon_h)
        header_w = icon_w + THEME.spacing.sm + title_surf.get_width()

        row_main_h = max((s.get_height() for s in row_values), default=0)
        row_arrow_slot = 9  # px reserved for +/- chevron glyph
        value_max = 0
        for i in range(len(rows)):
            v_w = row_values[i].get_width() + row_arrow_slot + THEME.spacing.xs
            value_max = max(value_max, v_w)
        label_max = max((s.get_width() for s in row_labels), default=0)
        sub_max = 0
        for i in range(len(rows)):
            lw = sub_labels[i].get_width() if sub_labels[i] is not None else 0
            vw = sub_values[i].get_width() if sub_values[i] is not None else 0
            sub_max = max(sub_max, lw + THEME.spacing.sm + vw)

        # Sparkline header (label + current net value, in muted caption).
        spark_label_surf = self.assets.render_text(
            "Net trend  -  60s", TYPE.label, PALETTE.muted
        )
        spark_now_surf = self.assets.render_text(
            self._fmt_net_compact(net_1m), TYPE.label, PALETTE.muted
        )
        spark_min_w = 120  # ensures the line has enough resolution to read

        row_block_w = label_max + THEME.spacing.xl + value_max
        spark_header_w = (
            spark_label_surf.get_width()
            + THEME.spacing.sm
            + spark_now_surf.get_width()
        )
        inner_w = max(
            header_w,
            subtitle_surf.get_width(),
            row_block_w,
            sub_max,
            spark_header_w,
            spark_min_w,
        )

        # total height ------------------------------------------------
        rows_h = 0
        for i, _r in enumerate(rows):
            rows_h += row_main_h
            if sub_labels[i] is not None:
                rows_h += sub_labels[i].get_height() + 2  # type: ignore[union-attr]
            if i < len(rows) - 1:
                rows_h += _TT_ROW_GAP

        spark_block_h = (
            THEME.spacing.sm  # gap above
            + 1               # divider line
            + THEME.spacing.xs
            + spark_label_surf.get_height()
            + 3
            + _TT_SPARK_H
        )

        inner_h = (
            header_h
            + 2
            + subtitle_surf.get_height()
            + THEME.spacing.sm
            + rows_h
            + spark_block_h
        )

        panel_w = inner_w + _TT_PAD * 2 + _TT_STRIPE
        panel_h = inner_h + _TT_PAD * 2

        # position with slide-down while fading in
        slide = int((1.0 - alpha) * -6)  # negative = start above and drop in
        px = int(self._pos_x.value) - panel_w // 2
        py = int(self._pos_y.value) + slide
        rect = pygame.Rect(px, py, panel_w, panel_h)
        rect = self._clamp(rect, surface.get_rect())

        # Drop shadow
        shadow_alpha = int(_TT_SHADOW_ALPHA * alpha)
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
            # Accent stripe in the item colour.
            stripe = pygame.Rect(0, 2, _TT_STRIPE, rect.h - 4)
            pygame.draw.rect(panel, item.color, stripe)

            # Header: icon + title (vertically centred to each other)
            tx = _TT_PAD + _TT_STRIPE
            ty = _TT_PAD
            icon_y = ty + (header_h - icon_h) // 2
            panel.blit(icon, (tx, icon_y))
            title_y = ty + (header_h - title_surf.get_height()) // 2
            panel.blit(title_surf, (tx + icon_w + THEME.spacing.sm, title_y))
            ty += header_h + 2
            panel.blit(subtitle_surf, (tx, ty))
            ty += subtitle_surf.get_height()

            # Divider tinted by accent so it ties into the stripe.
            ty += THEME.spacing.sm // 2
            divider_y = ty
            pygame.draw.line(
                panel,
                PALETTE.line,
                (tx, divider_y),
                (rect.w - _TT_PAD, divider_y),
            )
            pygame.draw.line(
                panel,
                darken(item.color, 0.4),
                (tx, divider_y + 1),
                (tx + 24, divider_y + 1),
            )
            ty += THEME.spacing.sm // 2 + 2

            # Rows
            for i, r in enumerate(rows):
                row_top = ty
                # Label on the left
                panel.blit(
                    row_labels[i],
                    (tx, row_top + (row_main_h - row_labels[i].get_height()) // 2),
                )
                # Chevron (optional) + value, right-aligned
                v_surf = row_values[i]
                vx = rect.w - _TT_PAD - v_surf.get_width()
                vy = row_top + (row_main_h - v_surf.get_height()) // 2
                if r.chevron != 0:
                    self._draw_chevron(
                        panel,
                        (vx - THEME.spacing.xs - row_arrow_slot // 2,
                         row_top + row_main_h // 2),
                        r.chevron,
                        r.value_color,
                    )
                panel.blit(v_surf, (vx, vy))

                ty += row_main_h

                # Secondary (10s) line, dimmer
                sub_l = sub_labels[i]
                sub_v = sub_values[i]
                if sub_l is not None and sub_v is not None:
                    panel.blit(sub_l, (tx + THEME.spacing.sm, ty))
                    sub_vx = rect.w - _TT_PAD - sub_v.get_width()
                    panel.blit(sub_v, (sub_vx, ty))
                    ty += sub_l.get_height() + 2

                if i < len(rows) - 1:
                    ty += _TT_ROW_GAP

            # -- sparkline block --------------------------------------
            ty += THEME.spacing.sm
            divider_y = ty
            pygame.draw.line(
                panel,
                PALETTE.line,
                (tx, divider_y),
                (rect.w - _TT_PAD, divider_y),
            )
            ty += 1 + THEME.spacing.xs
            panel.blit(spark_label_surf, (tx, ty))
            # Right-aligned current net value in muted caption.
            panel.blit(
                spark_now_surf,
                (rect.w - _TT_PAD - spark_now_surf.get_width(), ty),
            )
            ty += spark_label_surf.get_height() + 3

            spark_rect = pygame.Rect(
                tx, ty, rect.w - _TT_PAD - tx, _TT_SPARK_H
            )
            series = tracker.net_series(window_s=_TT_SPARK_WINDOW, smooth=3)
            self._draw_net_sparkline(panel, spark_rect, series, item.color)

            panel.set_alpha(panel_alpha)
            surface.blit(panel, rect.topleft)

    # -- helpers ----------------------------------------------------

    @staticmethod
    def _clamp(rect: pygame.Rect, bounds: pygame.Rect) -> pygame.Rect:
        r = rect.copy()
        margin = 8
        if r.right > bounds.right - margin:
            r.right = bounds.right - margin
        if r.left < bounds.left + margin:
            r.left = bounds.left + margin
        if r.bottom > bounds.bottom - margin:
            r.bottom = bounds.bottom - margin
        if r.top < bounds.top + margin:
            r.top = bounds.top + margin
        return r

    @staticmethod
    def _fmt_net_compact(v: float) -> str:
        sign = "+" if v > 0.05 else ("-" if v < -0.05 else "")
        mag = abs(v)
        if mag >= 100 or abs(mag - round(mag)) < 0.05:
            return f"{sign}{int(round(mag))}/min"
        return f"{sign}{mag:.1f}/min"

    @staticmethod
    def _draw_net_sparkline(
        surface: pygame.Surface,
        rect: pygame.Rect,
        series: list[float],
        accent: tuple[int, int, int],
    ) -> None:
        """Slim trend line of Net (produced - consumed) with zero axis."""
        if rect.w <= 2 or rect.h <= 2 or len(series) < 2:
            return

        # Symmetric range around 0 so the zero line stays centred even
        # when all samples are positive or all negative.
        peak = max((abs(v) for v in series), default=0.0)
        y_span = max(1.0, peak) * 1.15  # small headroom above/below

        # Baseline + background panel area.
        with acquired(rect.size) as layer:
            layer.fill((0, 0, 0, 0))
            # Faint background fill so the graph reads as its own block.
            pygame.draw.rect(
                layer,
                with_alpha(PALETTE.bg_raised, 110),
                pygame.Rect(0, 0, rect.w, rect.h),
            )
            # Subtle border.
            pygame.draw.rect(
                layer,
                with_alpha(PALETTE.line, 180),
                pygame.Rect(0, 0, rect.w, rect.h),
                1,
            )

            mid_y = rect.h // 2
            # Dashed zero line.
            dash = 3
            gap = 2
            x0 = 0
            while x0 < rect.w:
                pygame.draw.line(
                    layer,
                    with_alpha(PALETTE.line, 220),
                    (x0, mid_y),
                    (min(rect.w - 1, x0 + dash - 1), mid_y),
                )
                x0 += dash + gap

            n = len(series)
            inner_w = rect.w - 2
            inner_h = rect.h - 4

            def _px(i: int, v: float) -> tuple[int, int]:
                x = 1 + int(round(i * inner_w / max(1, n - 1)))
                # Positive goes up (smaller y); negative goes down.
                t = max(-1.0, min(1.0, v / y_span))
                y = mid_y - int(round(t * (inner_h / 2)))
                return (x, y)

            pts = [_px(i, v) for i, v in enumerate(series)]

            # Fill under curve: polygon from baseline up to the line.
            # Split into positive / negative segments so colors match sign.
            pos_color = with_alpha(PALETTE.success, 55)
            neg_color = with_alpha(PALETTE.danger, 55)
            _draw_signed_area(layer, pts, mid_y, pos_color, neg_color)

            # Line stroke: coloured by accent, with a bright cap.
            line_color = lighten(accent, 0.15)
            if len(pts) >= 2:
                pygame.draw.lines(layer, line_color, False, pts, 2)

            # Endpoint dot highlighting the latest value.
            lx, ly = pts[-1]
            pygame.draw.circle(layer, PALETTE.text_strong, (lx, ly), 2)
            pygame.draw.circle(
                layer, with_alpha(line_color, 140), (lx, ly), 4, 1
            )

            surface.blit(layer, rect.topleft)

    @staticmethod
    def _draw_chevron(
        surface: pygame.Surface,
        centre: tuple[int, int],
        direction: int,
        color: tuple[int, int, int],
    ) -> None:
        """Tiny triangle chevron: +1 = up (produced), -1 = down (consumed)."""
        cx, cy = centre
        s = 3
        if direction > 0:
            pts = [(cx, cy - s), (cx - s, cy + s - 1), (cx + s, cy + s - 1)]
        else:
            pts = [(cx, cy + s), (cx - s, cy - s + 1), (cx + s, cy - s + 1)]
        pygame.draw.polygon(surface, color, pts)

    @staticmethod
    def _build_rows(
        total: int,
        prod_1m: float,
        prod_10: float,
        cons_1m: float,
        cons_10: float,
        net_1m: float,
    ) -> list[_TTRow]:
        def _fmt_rate(v: float, *, signed: bool) -> str:
            if v <= 0.0 and not signed:
                return "0/min"
            sign = ""
            if signed:
                if v > 0.05:
                    sign = "+"
                elif v < -0.05:
                    sign = "-"
                    v = -v
                else:
                    sign = ""
                    v = 0.0
            if abs(v - round(v)) < 0.05 or v >= 100:
                return f"{sign}{int(round(v))}/min"
            return f"{sign}{v:.1f}/min"

        if net_1m > 0.05:
            net_color = PALETTE.success
            net_chevron = 1
        elif net_1m < -0.05:
            net_color = PALETTE.danger
            net_chevron = -1
        else:
            net_color = PALETTE.muted
            net_chevron = 0

        prod_color = PALETTE.success if prod_1m > 0.05 else PALETTE.muted
        cons_color = PALETTE.danger if cons_1m > 0.05 else PALETTE.muted

        return [
            _TTRow(
                label="Total",
                value=f"{total:,}",
                value_color=PALETTE.text_strong,
                chevron=0,
            ),
            _TTRow(
                label="Produced",
                value=_fmt_rate(prod_1m, signed=False),
                value_color=prod_color,
                chevron=1 if prod_1m > 0.05 else 0,
                sub_label="last 10s",
                sub_value=_fmt_rate(prod_10, signed=False),
            ),
            _TTRow(
                label="Consumed",
                value=_fmt_rate(cons_1m, signed=False),
                value_color=cons_color,
                chevron=-1 if cons_1m > 0.05 else 0,
                sub_label="last 10s",
                sub_value=_fmt_rate(cons_10, signed=False),
            ),
            _TTRow(
                label="Net",
                value=_fmt_rate(net_1m, signed=True),
                value_color=net_color,
                chevron=net_chevron,
            ),
        ]


def _draw_signed_area(
    surface: pygame.Surface,
    pts: list[tuple[int, int]],
    baseline_y: int,
    pos_color: tuple[int, int, int, int],
    neg_color: tuple[int, int, int, int],
) -> None:
    """Fill between the polyline and ``baseline_y`` with sign-tinted colour.

    Walks segment-by-segment so the positive and negative halves of the
    sparkline get coloured separately. Segments that cross zero are
    subdivided at the crossing so no stray colour leaks across.
    """
    if len(pts) < 2:
        return

    def _side(y: int) -> int:
        if y < baseline_y:
            return 1
        if y > baseline_y:
            return -1
        return 0

    def _fill_tri(a: tuple[int, int], b: tuple[int, int], side: int) -> None:
        if side == 0:
            return
        color = pos_color if side > 0 else neg_color
        poly = [a, b, (b[0], baseline_y), (a[0], baseline_y)]
        pygame.draw.polygon(surface, color, poly)

    for i in range(len(pts) - 1):
        a = pts[i]
        b = pts[i + 1]
        sa = _side(a[1])
        sb = _side(b[1])
        if sa == sb or sa == 0 or sb == 0:
            side = sa if sa != 0 else sb
            _fill_tri(a, b, side)
            continue
        # Zero crossing: linear interpolate the x at y = baseline_y.
        dy = b[1] - a[1]
        if dy == 0:
            continue
        t = (baseline_y - a[1]) / dy
        mx = int(round(a[0] + t * (b[0] - a[0])))
        m = (mx, baseline_y)
        _fill_tri(a, m, sa)
        _fill_tri(m, b, sb)


@dataclass(frozen=True)
class _TTRow:
    label: str
    value: str
    value_color: tuple[int, int, int]
    chevron: int = 0  # -1, 0, +1
    sub_label: str | None = None
    sub_value: str | None = None


# -- HUD --------------------------------------------------------------------


class HUD:
    def __init__(
        self,
        assets: AssetLoader,
        events: EventBus,
        *,
        on_open_research: Callable[[], None] | None = None,
    ) -> None:
        self.assets = assets
        self.events = events
        self.on_open_research = on_open_research

        tracked = (
            ITEMS.cocoa_bean,
            ITEMS.sugar_crystal,
            ITEMS.milk,
            ITEMS.chocolate,
            ITEMS.caramel,
            ITEMS.candy_bar,
        )
        self._cells: list[_Cell] = [_Cell(item=t) for t in tracked]
        self._counts: dict[str, int] = {t.id: 0 for t in tracked}
        self._pulses: dict[str, AnimValue] = {
            t.id: AnimValue(value=0.0, speed=10.0) for t in tracked
        }
        self._rates: dict[str, RateTracker] = {t.id: RateTracker() for t in tracked}

        self._off_produced = events.on("item.produced", self._on_produced)
        self._off_consumed = events.on("item.consumed", self._on_consumed)

        # Live transform state mirrored from the placement cursor.
        self._rotation: Direction = Direction.E
        self._mirrored: bool = False

        # Hover state.
        self._hovered_item_id: str | None = None
        self._prev_hovered_item_id: str | None = None
        self._tooltip = _HudTooltip(assets)

        # Research-tree quick-open button (cogwheel glyph + label).
        self._research_btn_rect: pygame.Rect = pygame.Rect(0, 0, 0, 0)
        self._research_btn_hover = AnimValue(value=0.0, speed=18.0)
        self._research_btn_press = AnimValue(value=0.0, speed=22.0)
        self._research_btn_phase: float = 0.0
        self._research_btn_hovered: bool = False
        self._research_btn_prev_hover: bool = False

    def close(self) -> None:
        self._off_produced()
        self._off_consumed()

    # -- events ------------------------------------------------------------

    def _on_produced(self, item_type: ItemType) -> None:
        self._counts[item_type.id] = self._counts.get(item_type.id, 0) + 1
        p = self._pulses.get(item_type.id)
        if p is not None:
            p.value = 1.0
            p.to(0.0)
        tracker = self._rates.get(item_type.id)
        if tracker is not None:
            tracker.add_produced(1)
        # Throttled inside the cue catalogue so a 1M-item benchmark stays
        # whisper-quiet. ``audio_sim`` can also disable this entirely.
        SFX.play("sim.produced")

    def _on_consumed(self, item_type: ItemType) -> None:
        tracker = self._rates.get(item_type.id)
        if tracker is not None:
            tracker.add_consumed(1)

    # -- update/render -----------------------------------------------------

    def update(
        self,
        dt: float,
        mouse_pos: tuple[int, int] | None = None,
        world_time: float = 0.0,
        mouse_down: bool = False,
        mouse_released: bool = False,
    ) -> None:
        for p in self._pulses.values():
            p.update(dt)
        for tracker in self._rates.values():
            tracker.tick_time(world_time)

        # Research button hit-testing (uses last-rendered rect).
        btn_hover = False
        if (
            self.on_open_research is not None
            and mouse_pos is not None
            and self._research_btn_rect.w > 0
            and self._research_btn_rect.collidepoint(mouse_pos)
        ):
            btn_hover = True
        self._research_btn_hovered = btn_hover
        self._research_btn_hover.to(1.0 if btn_hover else 0.0)
        self._research_btn_hover.update(dt)
        self._research_btn_press.to(1.0 if (btn_hover and mouse_down) else 0.0)
        self._research_btn_press.update(dt)
        self._research_btn_phase += dt
        if btn_hover and not self._research_btn_prev_hover:
            SFX.play("ui.hover")
        if btn_hover and mouse_released and self.on_open_research is not None:
            SFX.play("ui.click")
            self.on_open_research()
        self._research_btn_prev_hover = btn_hover

        # Hover test against last-rendered cell rects.
        hovered: str | None = None
        if mouse_pos is not None:
            for cell in self._cells:
                if cell.rect.w > 0 and cell.rect.collidepoint(mouse_pos):
                    hovered = cell.item.id
                    break

        if hovered != self._prev_hovered_item_id:
            if hovered is not None:
                SFX.play("ui.hover")
            self._prev_hovered_item_id = hovered
        self._hovered_item_id = hovered

        for cell in self._cells:
            cell.hover.to(1.0 if cell.item.id == hovered else 0.0)
            cell.hover.update(dt)

        # Feed the tooltip. The anchor is the bottom-centre of the hovered
        # cell; the tooltip will position itself below with a slide-in.
        target_cell = next(
            (c for c in self._cells if c.item.id == hovered), None
        )
        if target_cell is not None:
            anchor = (target_cell.rect.centerx, target_cell.rect.bottom + 10)
            self._tooltip.set_target(target_cell.item, anchor)
        else:
            self._tooltip.set_target(None, None)
        self._tooltip.update(dt)

    def set_transform(self, rotation: Direction, mirrored: bool) -> None:
        """Sync the transform indicator with the live placement cursor."""
        self._rotation = rotation
        self._mirrored = bool(mirrored)

    def render(self, surface: pygame.Surface, fps: float) -> None:
        pad = THEME.spacing.lg
        height = 48
        rect = pygame.Rect(pad, pad, surface.get_width() - pad * 2, height)
        beveled_panel(surface, rect, fill=PALETTE.bg_base, border=PALETTE.line)

        title = self.assets.render_text("SWEET WORKS", TYPE.label, PALETTE.primary)
        surface.blit(title, (rect.x + THEME.spacing.md, rect.y + (height - title.get_height()) // 2))

        x = rect.x + THEME.spacing.md + title.get_width() + THEME.spacing.xl
        for cell in self._cells:
            pulse = self._pulses[cell.item.id].value
            x = self._render_resource(
                surface, rect, x, cell, self._counts[cell.item.id], pulse
            )

        fps_surf = self.assets.render_text(f"{int(fps):>3} FPS", TYPE.mono, PALETTE.muted)
        fps_x = rect.right - fps_surf.get_width() - THEME.spacing.md
        surface.blit(
            fps_surf,
            (fps_x, rect.y + (height - fps_surf.get_height()) // 2),
        )

        # Compact transform indicator lives just left of the FPS counter.
        pip_x = fps_x - THEME.spacing.lg - 24
        pip_y = rect.y + height // 2
        self._render_transform_pip(surface, pip_x, pip_y)

        # Research quick-open button just left of the transform pip.
        if self.on_open_research is not None:
            btn_w = 120
            btn_h = 30
            btn_x = pip_x - 24 - btn_w
            btn_y = rect.y + (height - btn_h) // 2
            self._research_btn_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)
            self._render_research_button(surface, self._research_btn_rect)
        else:
            self._research_btn_rect = pygame.Rect(0, 0, 0, 0)

        # Tooltip sits on top of everything in the HUD layer.
        if self._tooltip.visible:
            active = self._tooltip.current_item
            active_id = active.id if active is not None else self._hovered_item_id
            if active_id is not None:
                self._tooltip.render(
                    surface,
                    self._rates[active_id],
                    self._counts.get(active_id, 0),
                )

    def _render_resource(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        x: int,
        cell: _Cell,
        count: int,
        pulse: float,
    ) -> int:
        item_type = cell.item
        hover = cell.hover.value
        lift = int(round(hover * 2))  # subtle icon+number lift

        icon = self.assets.item_icon(item_type.id)
        icon_y = rect.y + (rect.h - icon.get_height()) // 2 - lift

        count_surf = self.assets.render_text(
            f"{count:>3}", TYPE.mono, PALETTE.text_strong
        )
        tx = x + icon.get_width() + THEME.spacing.xs
        ty = rect.y + (rect.h - count_surf.get_height()) // 2 - lift

        # Measure the full clickable/hover footprint for this cell.
        cell_pad_x = THEME.spacing.xs
        cell_left = x - cell_pad_x
        cell_top = rect.y + 2
        cell_right = tx + count_surf.get_width() + cell_pad_x
        cell_bottom = rect.bottom - 2
        cell.rect = pygame.Rect(
            cell_left, cell_top, cell_right - cell_left, cell_bottom - cell_top
        )

        # Hover halo: grows with hover; produce-pulse stacks on top.
        if hover > 0.02:
            halo_alpha = int(40 + 70 * hover)
            halo_size = (cell.rect.w + 4, cell.rect.h)
            with acquired(halo_size) as halo:
                halo.fill(with_alpha(item_type.color, halo_alpha))
                surface.blit(
                    halo,
                    (cell.rect.x - 2, cell.rect.y),
                    special_flags=pygame.BLEND_PREMULTIPLIED,
                )
            # Accent underline on hover ties into the tooltip stripe below.
            underline_alpha = int(180 * hover)
            if underline_alpha > 0:
                ul_w = cell.rect.w
                with acquired((ul_w, 2)) as ul:
                    ul.fill(with_alpha(lighten(item_type.color, 0.2), underline_alpha))
                    surface.blit(
                        ul,
                        (cell.rect.x, cell.rect.bottom - 2),
                        special_flags=pygame.BLEND_PREMULTIPLIED,
                    )

        # Produce pulse: unchanged legacy halo just behind the icon.
        if pulse > 0.02:
            pulse_size = (icon.get_width() + 6, icon.get_height() + 6)
            with acquired(pulse_size) as p_halo:
                p_halo.fill(with_alpha(item_type.color, int(pulse * 140)))
                surface.blit(
                    p_halo,
                    (x - 3, icon_y - 3),
                    special_flags=pygame.BLEND_PREMULTIPLIED,
                )

        surface.blit(icon, (x, icon_y))
        surface.blit(count_surf, (tx, ty))

        return tx + count_surf.get_width() + THEME.spacing.lg

    def _render_research_button(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        """Beveled pill with a small cogwheel glyph + label."""
        hover = self._research_btn_hover.value
        press = self._research_btn_press.value

        fill = lighten(PALETTE.bg_raised, 0.04 + 0.05 * hover)
        border = lighten(PALETTE.primary, 0.05 * hover)
        beveled_panel(surface, rect, fill=fill, border=border)

        glow_a = int(28 + 48 * hover - 30 * press)
        if glow_a > 0:
            with acquired(rect.size) as glow:
                glow.fill(with_alpha(PALETTE.primary, glow_a))
                surface.blit(glow, rect.topleft)

        if press > 0.01:
            with acquired(rect.size) as dark:
                dark.fill(with_alpha(PALETTE.bg_deep, int(50 * press)))
                surface.blit(dark, rect.topleft)

        pad = 8
        gear_cx = rect.x + pad + 8
        gear_cy = rect.centery
        rot = self._research_btn_phase * (1.8 if hover > 0.01 else 0.6)
        self._draw_gear(surface, (gear_cx, gear_cy), 7, rot, PALETTE.primary)

        label_col = PALETTE.text_strong if hover > 0.1 else PALETTE.text_body
        label = self.assets.render_text("RESEARCH", TYPE.label, label_col)
        lx = gear_cx + 8 + (rect.right - (gear_cx + 8) - label.get_width()) // 2
        ly = rect.centery - label.get_height() // 2 - int(round(press * 1))
        surface.blit(label, (lx, ly))

        # Subtle bottom accent line on hover, ties into the toolbar theme.
        if hover > 0.02:
            line_a = int(200 * hover)
            with acquired((rect.w - 6, 2)) as ul:
                ul.fill(with_alpha(PALETTE.primary, line_a))
                surface.blit(
                    ul,
                    (rect.x + 3, rect.bottom - 3),
                    special_flags=pygame.BLEND_PREMULTIPLIED,
                )

    @staticmethod
    def _draw_gear(
        surface: pygame.Surface,
        center: tuple[int, int],
        radius: int,
        rot: float,
        color: tuple[int, int, int],
    ) -> None:
        """Tiny procedural cogwheel glyph: 8 teeth + inner hub."""
        cx, cy = center
        teeth = 8
        outer = radius
        inner = max(2, radius - 3)
        pts: list[tuple[float, float]] = []
        for i in range(teeth * 2):
            a = rot + (i * math.pi / teeth)
            r = outer if (i % 2 == 0) else inner
            pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
        pygame.draw.polygon(surface, color, [(int(x), int(y)) for x, y in pts])
        pygame.draw.circle(surface, PALETTE.bg_deep, (cx, cy), max(2, radius - 4))
        pygame.draw.circle(surface, color, (cx, cy), max(1, radius - 5), 1)

    def _render_transform_pip(
        self, surface: pygame.Surface, cx: int, cy: int
    ) -> None:
        """Compass chevron + optional flip bar at (cx, cy)."""
        dx, dy = self._rotation.vector
        perp = (-dy, dx)
        size = 7
        tip = (cx + dx * size, cy + dy * size)
        back = (cx - dx * size, cy - dy * size)
        left = (back[0] + perp[0] * size, back[1] + perp[1] * size)
        right = (back[0] - perp[0] * size, back[1] - perp[1] * size)
        color = lighten(PALETTE.primary, 0.1)
        pygame.draw.polygon(surface, color, [tip, left, right])
        pygame.draw.polygon(surface, PALETTE.bg_deep, [tip, left, right], 1)
        if self._mirrored:
            mirror_color = with_alpha(PALETTE.secondary, 220)
            with acquired((24, 24)) as layer:
                pygame.draw.line(
                    layer,
                    mirror_color,
                    (12 + perp[0] * 10, 12 + perp[1] * 10),
                    (12 - perp[0] * 10, 12 - perp[1] * 10),
                    2,
                )
                surface.blit(layer, (cx - 12, cy - 12))
