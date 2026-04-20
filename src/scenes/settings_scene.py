"""Full-screen Settings scene: edit runtime constants with live preview.

The scene is layered over the menu backdrop (same gradient + grid) for a
seamless transition, with a staggered reveal across header, sections and
action bar. Controls write into a draft :class:`UserSettings`; the
``APPLY`` button hands that draft to :meth:`Game.apply_settings` which
persists it to ``assets/user_settings.json`` and mutates live config +
clock + display in place.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import pygame

from ..core import settings as settings_mod
from ..core.settings import UserSettings
from ..design.palette import PALETTE, lighten, with_alpha
from ..design.theme import THEME
from ..design.typography import TYPE
from ..rendering.animation import AnimValue, Tween
from ..rendering.pixel import beveled_panel, gradient_fill
from ..rendering.pool import acquired
from ..ui.controls import Button, Section, Slider, Stepper, Toggle
from .scene import Scene


# -- layout constants ------------------------------------------------------

_HEADER_H = 84
_SECTION_GAP = 18
_COLUMN_W = 720
_COLUMN_MIN_W = 560
_SIDE_PAD = 40
_ROW_H = 44
_LABEL_COL_W = 220
_CONTROL_X_PAD = 12
_ACTIONS_H = 72
_BTN_H = 44
_BTN_GAP = 12

_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (1280, 720),
    (1366, 768),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
)

_FPS_CAPS: tuple[int, ...] = (0, 30, 60, 120, 144, 240)

_TICK_HZ_CHOICES: tuple[int, ...] = (10, 15, 20, 30, 40)


def _fmt_fps(v: int) -> str:
    return "Unlimited" if v == 0 else f"{v} fps"


def _fmt_res(v: tuple[int, int]) -> str:
    return f"{v[0]} x {v[1]}"


def _fmt_hz(v: int) -> str:
    return f"{v} Hz"


def _find_index(values: tuple[Any, ...], target: Any, *, default: int = 0) -> int:
    try:
        return values.index(target)
    except ValueError:
        return default


# Per-section reveal window (start, end) within ``self._reveal_anim.value``.
_PHASES: tuple[tuple[float, float], ...] = (
    (0.00, 0.35),  # header
    (0.10, 0.50),  # display
    (0.22, 0.62),  # simulation
    (0.34, 0.74),  # camera
    (0.50, 0.90),  # action bar
)


def _phase(reveal: float, start: float, end: float) -> float:
    if end <= start:
        return 1.0
    return max(0.0, min(1.0, (reveal - start) / (end - start)))


class SettingsScene(Scene):
    """Edit runtime-tunable settings. Pushed over :class:`MenuScene`."""

    def __init__(self) -> None:
        super().__init__()
        self._t: float = 0.0
        self._draft: UserSettings = UserSettings()
        self._applied: UserSettings = UserSettings()

        self._reveal = AnimValue(value=0.0, speed=3.2)
        self._fade_in = Tween(start=0.0, end=1.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out)
        self._closing: bool = False
        self._close_tween = Tween(start=0.0, end=0.0, duration=THEME.anim.base, ease=THEME.anim.ease_in_out)
        self._close_tween.done = True
        self._apply_pulse = Tween(start=0.0, end=0.0, duration=THEME.anim.slow, ease=THEME.anim.ease_bounce)
        self._apply_pulse.done = True

        # Rebuilt on layout()
        self._window_size: tuple[int, int] = (0, 0)
        self._section_display: Section | None = None
        self._section_sim: Section | None = None
        self._section_camera: Section | None = None

        # Controls (created lazily in layout())
        self._res: Stepper | None = None
        self._fullscreen: Toggle | None = None
        self._fps: Stepper | None = None

        self._tick: Stepper | None = None
        self._belt_hz: Slider | None = None
        self._struct_hz: Slider | None = None

        self._pan: Slider | None = None
        self._smooth: Slider | None = None
        self._drag: Slider | None = None
        self._zoom: Slider | None = None

        self._btn_back: Button | None = None
        self._btn_reset: Button | None = None
        self._btn_apply: Button | None = None

        self._controls_all: list[Any] = []

    # -- lifecycle ---------------------------------------------------------

    def on_enter(self) -> None:
        assert self.game is not None
        self._t = 0.0
        self._draft = self.game.settings
        self._applied = self.game.settings
        self._reveal.set(0.0)
        self._reveal.to(1.0)
        self._fade_in = Tween(start=0.0, end=1.0, duration=THEME.anim.slow, ease=THEME.anim.ease_out)
        self._closing = False
        self._close_tween.done = True
        self._apply_pulse.done = True
        self._build(self.game.window_size)

    def on_resize(self, size: tuple[int, int]) -> None:
        self._build(size)

    # -- events ------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._closing:
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._go_back()

    # -- update / render ---------------------------------------------------

    def update(self, dt: float, sim_ticks: int, sim_alpha: float) -> None:
        self._t += dt
        self._reveal.update(dt)
        self._fade_in.update(dt)
        self._apply_pulse.update(dt)

        for sec in (self._section_display, self._section_sim, self._section_camera):
            if sec is not None:
                sec.update(dt)

        if self._closing:
            v = self._close_tween.update(dt)
            if self._close_tween.done and self.game is not None:
                self.game.pop_scene()
                return
            _ = v
            return

        if self.game is None:
            return

        mp = self.game.input.mouse_pos
        md = self.game.input.mouse(1)
        mps = self.game.input.mouse_pressed(1)
        mrl = self.game.input.mouse_released(1)

        for ctrl in self._controls_all:
            if ctrl is None:
                continue
            ctrl.update(dt, mp, md, mps, mrl)

        if self._btn_apply is not None:
            self._btn_apply.enabled = self._is_dirty()

    def render(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        gradient_fill(surface, pygame.Rect(0, 0, w, h), PALETTE.bg_deep, PALETTE.bg_base)
        self._render_grid(surface)

        self._render_header(surface)
        self._render_sections(surface)
        self._render_controls(surface)
        self._render_actions(surface)

        self._render_fade_overlay(surface)

    # -- layout ------------------------------------------------------------

    def _build(self, size: tuple[int, int]) -> None:
        self._window_size = size
        w, h = size
        col_w = max(_COLUMN_MIN_W, min(_COLUMN_W, w - _SIDE_PAD * 2))
        col_x = (w - col_w) // 2

        y = _HEADER_H + 16

        disp_rows = 3
        sim_rows = 3
        cam_rows = 4

        def section_height(rows: int) -> int:
            return Section.HEADER_H + Section.PAD * 2 + _ROW_H * rows

        disp_h = section_height(disp_rows)
        sim_h = section_height(sim_rows)
        cam_h = section_height(cam_rows)

        self._section_display = Section(
            pygame.Rect(col_x, y, col_w, disp_h), "DISPLAY"
        )
        y += disp_h + _SECTION_GAP
        self._section_sim = Section(
            pygame.Rect(col_x, y, col_w, sim_h), "SIMULATION"
        )
        y += sim_h + _SECTION_GAP
        self._section_camera = Section(
            pygame.Rect(col_x, y, col_w, cam_h), "CAMERA"
        )
        y += cam_h + _SECTION_GAP

        # Ensure there's room for the action bar; if not, we still render it
        # at the bottom and the content can scroll off (we keep a simple
        # constant layout; the default window height is designed for it).

        # Build controls row-by-row per section.
        self._build_display_controls(self._section_display)
        self._build_sim_controls(self._section_sim)
        self._build_camera_controls(self._section_camera)
        self._build_actions(size)

        self._refresh_controls_from_draft()

        self._controls_all = [
            self._res,
            self._fullscreen,
            self._fps,
            self._tick,
            self._belt_hz,
            self._struct_hz,
            self._pan,
            self._smooth,
            self._drag,
            self._zoom,
            self._btn_back,
            self._btn_reset,
            self._btn_apply,
        ]

    def _control_rect(self, section: Section, row_idx: int) -> pygame.Rect:
        body = section.body_rect()
        row_y = body.y + row_idx * _ROW_H
        x = body.x + _LABEL_COL_W + _CONTROL_X_PAD
        w = body.right - x
        return pygame.Rect(x, row_y + (_ROW_H - 34) // 2, w, 34)

    def _label_pos(self, section: Section, row_idx: int) -> tuple[int, int]:
        body = section.body_rect()
        row_y = body.y + row_idx * _ROW_H + _ROW_H // 2
        return body.x + 4, row_y

    def _build_display_controls(self, section: Section) -> None:
        self._res = Stepper(
            self._control_rect(section, 0),
            _RESOLUTIONS,
            _find_index(_RESOLUTIONS, (self._draft.window_w, self._draft.window_h), default=0),
            format=_fmt_res,
            on_change=self._on_res_change,
        )

        fs_rect = self._control_rect(section, 1)
        self._fullscreen = Toggle(
            (fs_rect.x, fs_rect.y + (fs_rect.h - Toggle.HEIGHT) // 2),
            self._draft.fullscreen,
            on_change=self._on_fullscreen_change,
        )

        self._fps = Stepper(
            self._control_rect(section, 2),
            _FPS_CAPS,
            _find_index(_FPS_CAPS, self._draft.fps_cap, default=0),
            format=_fmt_fps,
            on_change=self._on_fps_change,
        )

    def _build_sim_controls(self, section: Section) -> None:
        self._tick = Stepper(
            self._control_rect(section, 0),
            _TICK_HZ_CHOICES,
            _find_index(_TICK_HZ_CHOICES, self._draft.tick_hz, default=2),
            format=_fmt_hz,
            on_change=self._on_tick_change,
        )
        self._belt_hz = Slider(
            self._control_rect(section, 1),
            vmin=2.0,
            vmax=16.0,
            value=float(self._draft.belt_anim_hz),
            step=1.0,
            format=lambda v: f"{v:.0f} Hz",
            on_change=self._on_belt_hz_change,
        )
        self._struct_hz = Slider(
            self._control_rect(section, 2),
            vmin=2.0,
            vmax=12.0,
            value=float(self._draft.structure_anim_hz),
            step=1.0,
            format=lambda v: f"{v:.0f} Hz",
            on_change=self._on_struct_hz_change,
        )

    def _build_camera_controls(self, section: Section) -> None:
        self._pan = Slider(
            self._control_rect(section, 0),
            vmin=120.0,
            vmax=960.0,
            value=float(self._draft.camera_pan_speed),
            step=20.0,
            format=lambda v: f"{v:.0f} px/s",
            on_change=self._on_pan_change,
        )
        self._smooth = Slider(
            self._control_rect(section, 1),
            vmin=4.0,
            vmax=24.0,
            value=float(self._draft.camera_smooth),
            step=0.5,
            format=lambda v: f"{v:.1f}",
            on_change=self._on_smooth_change,
        )
        self._drag = Slider(
            self._control_rect(section, 2),
            vmin=2.0,
            vmax=12.0,
            value=float(self._draft.camera_drag_inertia_decay),
            step=0.5,
            format=lambda v: f"{v:.1f}",
            on_change=self._on_drag_change,
        )
        self._zoom = Slider(
            self._control_rect(section, 3),
            vmin=0.3,
            vmax=2.0,
            value=float(self._draft.default_zoom),
            step=0.05,
            format=lambda v: f"{v:.2f}x",
            on_change=self._on_zoom_change,
        )

    def _build_actions(self, size: tuple[int, int]) -> None:
        w, h = size
        # Action bar: centered row at the bottom.
        bar_y = h - _ACTIONS_H
        total_w = 3 * 160 + 2 * _BTN_GAP
        x0 = (w - total_w) // 2

        self._btn_back = Button(
            pygame.Rect(x0, bar_y, 160, _BTN_H),
            "BACK",
            kind="ghost",
            on_click=self._go_back,
        )
        self._btn_reset = Button(
            pygame.Rect(x0 + 160 + _BTN_GAP, bar_y, 160, _BTN_H),
            "RESET",
            kind="secondary",
            on_click=self._reset_defaults,
        )
        self._btn_apply = Button(
            pygame.Rect(x0 + (160 + _BTN_GAP) * 2, bar_y, 160, _BTN_H),
            "APPLY",
            kind="primary",
            on_click=self._apply,
            enabled=False,
        )

    def _refresh_controls_from_draft(self) -> None:
        s = self._draft
        if self._res is not None:
            self._res.set_index(
                _find_index(_RESOLUTIONS, (s.window_w, s.window_h), default=0),
                notify=False,
            )
        if self._fullscreen is not None:
            self._fullscreen.set_value(s.fullscreen, notify=False)
        if self._fps is not None:
            self._fps.set_index(_find_index(_FPS_CAPS, s.fps_cap, default=0), notify=False)
        if self._tick is not None:
            self._tick.set_index(_find_index(_TICK_HZ_CHOICES, s.tick_hz, default=2), notify=False)
        if self._belt_hz is not None:
            self._belt_hz.set_value(float(s.belt_anim_hz), notify=False)
        if self._struct_hz is not None:
            self._struct_hz.set_value(float(s.structure_anim_hz), notify=False)
        if self._pan is not None:
            self._pan.set_value(float(s.camera_pan_speed), notify=False)
        if self._smooth is not None:
            self._smooth.set_value(float(s.camera_smooth), notify=False)
        if self._drag is not None:
            self._drag.set_value(float(s.camera_drag_inertia_decay), notify=False)
        if self._zoom is not None:
            self._zoom.set_value(float(s.default_zoom), notify=False)

    # -- draft mutators ----------------------------------------------------

    def _mutate(self, **kwargs: Any) -> None:
        self._draft = replace(self._draft, **kwargs)

    def _on_res_change(self, _i: int, v: tuple[int, int]) -> None:
        self._mutate(window_w=int(v[0]), window_h=int(v[1]))

    def _on_fullscreen_change(self, v: bool) -> None:
        self._mutate(fullscreen=bool(v))

    def _on_fps_change(self, _i: int, v: int) -> None:
        self._mutate(fps_cap=int(v))

    def _on_tick_change(self, _i: int, v: int) -> None:
        self._mutate(tick_hz=int(v))

    def _on_belt_hz_change(self, v: float) -> None:
        self._mutate(belt_anim_hz=float(v))

    def _on_struct_hz_change(self, v: float) -> None:
        self._mutate(structure_anim_hz=float(v))

    def _on_pan_change(self, v: float) -> None:
        self._mutate(camera_pan_speed=float(v))

    def _on_smooth_change(self, v: float) -> None:
        self._mutate(camera_smooth=float(v))

    def _on_drag_change(self, v: float) -> None:
        self._mutate(camera_drag_inertia_decay=float(v))

    def _on_zoom_change(self, v: float) -> None:
        self._mutate(default_zoom=float(v))

    # -- actions -----------------------------------------------------------

    def _is_dirty(self) -> bool:
        return self._draft != self._applied

    def _apply(self) -> None:
        if self.game is None or not self._is_dirty():
            return
        self.game.apply_settings(self._draft)
        self._applied = self.game.settings
        self._draft = self.game.settings
        self._apply_pulse = Tween(
            start=1.0, end=0.0, duration=THEME.anim.slow, ease=THEME.anim.ease_bounce
        )
        # Rebuild layout in case the window was resized by the apply.
        if self.game is not None:
            self._build(self.game.window_size)

    def _reset_defaults(self) -> None:
        self._draft = settings_mod.defaults()
        self._refresh_controls_from_draft()

    def _go_back(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._close_tween = Tween(
            start=0.0, end=1.0, duration=THEME.anim.base, ease=THEME.anim.ease_in_out
        )

    # -- render helpers ----------------------------------------------------

    def _render_grid(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        color = with_alpha(PALETTE.line, 26)
        step = 48
        line = pygame.Surface((w, 1), pygame.SRCALPHA)
        line.fill(color)
        for y in range(0, h, step):
            surface.blit(line, (0, y))
        vline = pygame.Surface((1, h), pygame.SRCALPHA)
        vline.fill(color)
        for x in range(0, w, step):
            surface.blit(vline, (x, 0))

    def _render_header(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets
        w, _ = surface.get_size()

        start, end = _PHASES[0]
        e = THEME.anim.ease_out(_phase(self._reveal.value, start, end))
        y_off = int((1.0 - e) * 14)
        alpha = int(255 * e)

        title = assets.render_text("SETTINGS", TYPE.display, PALETTE.text_strong)
        subtitle = assets.render_text(
            "application constants, applied live and remembered on disk",
            TYPE.caption,
            PALETTE.muted,
        )

        title_x = w // 2 - title.get_width() // 2
        subtitle_x = w // 2 - subtitle.get_width() // 2
        title_y = 20 + y_off
        sub_y = title_y + title.get_height() + 4

        title_scratch = title.copy()
        title_scratch.set_alpha(alpha)
        sub_scratch = subtitle.copy()
        sub_scratch.set_alpha(alpha)
        surface.blit(title_scratch, (title_x, title_y))
        surface.blit(sub_scratch, (subtitle_x, sub_y))

        # Accent underline under the title.
        underline_w = int(title.get_width() * e)
        pygame.draw.rect(
            surface,
            PALETTE.primary,
            pygame.Rect(title_x + (title.get_width() - underline_w) // 2, title_y + title.get_height() + 1, underline_w, 2),
        )

    def _render_sections(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets
        sections = (
            (self._section_display, _PHASES[1]),
            (self._section_sim, _PHASES[2]),
            (self._section_camera, _PHASES[3]),
        )
        for section, phase in sections:
            if section is None:
                continue
            t = _phase(self._reveal.value, *phase)
            section.set_reveal(t)
            section.render(surface, assets)

    def _render_controls(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets

        # Draw row labels + their bound control (controls have their own
        # reveal alpha tied to their owning section).
        self._render_row(surface, self._section_display, 0, "Resolution", self._res)
        self._render_row(surface, self._section_display, 1, "Fullscreen", self._fullscreen)
        self._render_row(surface, self._section_display, 2, "FPS cap", self._fps)

        self._render_row(surface, self._section_sim, 0, "Tick rate", self._tick)
        self._render_row(surface, self._section_sim, 1, "Belt animation", self._belt_hz)
        self._render_row(surface, self._section_sim, 2, "Building animation", self._struct_hz)

        self._render_row(surface, self._section_camera, 0, "Pan speed", self._pan)
        self._render_row(surface, self._section_camera, 1, "Smoothing", self._smooth)
        self._render_row(surface, self._section_camera, 2, "Drag inertia decay", self._drag)
        self._render_row(surface, self._section_camera, 3, "Default zoom", self._zoom)

        # Light divider between label column and control column.
        for sec in (self._section_display, self._section_sim, self._section_camera):
            if sec is None:
                continue
            body = sec.body_rect()
            dx = body.x + _LABEL_COL_W
            pygame.draw.line(
                surface,
                with_alpha(PALETTE.line, 60),
                (dx, body.y + 6),
                (dx, body.bottom - 6),
            )

        _ = assets  # silence unused (render_row consumes assets via controls)

    def _render_row(
        self,
        surface: pygame.Surface,
        section: Section | None,
        row_idx: int,
        label: str,
        control: Any,
    ) -> None:
        if section is None or control is None:
            return
        assert self.game is not None
        assets = self.game.assets
        lbl_x, lbl_y = self._label_pos(section, row_idx)
        txt = assets.render_text(label, TYPE.body, PALETTE.text_body)
        surface.blit(txt, (lbl_x, lbl_y - txt.get_height() // 2))
        control.render(surface, assets)

    def _render_actions(self, surface: pygame.Surface) -> None:
        assert self.game is not None
        assets = self.game.assets

        start, end = _PHASES[4]
        e = THEME.anim.ease_out(_phase(self._reveal.value, start, end))
        if e <= 0.0:
            return

        # Dirty-state banner above the action bar.
        if self._btn_apply is not None:
            bar_rect = self._btn_apply.rect
            if self._is_dirty():
                hint = assets.render_text(
                    "unsaved changes",
                    TYPE.label,
                    PALETTE.warning,
                )
                hint_alpha = int(255 * (0.65 + 0.35 * math.sin(self._t * 3.0)))
                scratch = hint.copy()
                scratch.set_alpha(hint_alpha)
                hx = self._window_size[0] // 2 - hint.get_width() // 2
                hy = bar_rect.y - hint.get_height() - 6
                surface.blit(scratch, (hx, hy))

        # Apply pulse: brief success glow when apply lands.
        pulse = self._apply_pulse.elapsed / self._apply_pulse.duration if self._apply_pulse.duration else 0.0
        pulse = 0.0 if self._apply_pulse.done else max(0.0, min(1.0, 1.0 - pulse))
        if pulse > 0.01 and self._btn_apply is not None:
            r = self._btn_apply.rect.inflate(14, 14)
            with acquired(r.size) as glow:
                glow.fill(with_alpha(PALETTE.success, int(120 * pulse)))
                surface.blit(glow, r.topleft)

        for btn in (self._btn_back, self._btn_reset, self._btn_apply):
            if btn is None:
                continue
            btn.render(surface, assets)

        # Row alpha.
        alpha = int(255 * e)
        if alpha < 255:
            w, h = surface.get_size()
            veil_rect = pygame.Rect(0, h - _ACTIONS_H - 32, w, _ACTIONS_H + 32)
            with acquired(veil_rect.size) as veil:
                veil.fill(with_alpha(PALETTE.bg_deep, 255 - alpha))
                surface.blit(veil, veil_rect.topleft)

    def _render_fade_overlay(self, surface: pygame.Surface) -> None:
        fade_in_a = 0.0
        if not self._fade_in.done:
            v = self._fade_in.update(0.0)
            fade_in_a = 1.0 - max(0.0, min(1.0, v))
        fade_out_a = 0.0
        if self._closing and not self._close_tween.done:
            fade_out_a = max(0.0, min(1.0, self._close_tween.update(0.0)))
        alpha = int(255 * max(fade_in_a, fade_out_a))
        if alpha <= 1:
            return
        w, h = surface.get_size()
        with acquired((w, h)) as veil:
            veil.fill(with_alpha(PALETTE.bg_deep, alpha))
            surface.blit(veil, (0, 0))
