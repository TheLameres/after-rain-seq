"""Тесты UI-фреймворка (widgets.py) и реестра экранов (screens.py, D2-7).

Пиксельные проверки грубые, но устойчивые: в области виджета есть
не-фоновые пиксели нужного цвета (аналогично test_screens_render).
"""

from __future__ import annotations

import numpy
import pytest

from src.devices.display_state import ScreenView, TrackRowView
from src.devices.push2.display import _FONTS
from src.devices.push2.renderer import FRAME_W, Colors, FrameBuffer
from src.devices.push2.screens import (
    DEFAULT_SCREENS,
    TAB_CELLS,
    Screen,
    Screens,
)
from src.devices.push2.widgets import (
    BODY_Y0,
    COL_W,
    Bar,
    Column,
    ColumnGrid,
    Label,
    Marker,
    Rect,
    TabStrip,
)


def make_fb() -> FrameBuffer:
    fb = FrameBuffer(fonts=_FONTS)
    fb.fill(Colors.BG)
    fb.dirty.clear()
    return fb


def non_bg_count(fb: FrameBuffer, x: int, y: int, w: int, h: int) -> int:
    region = fb.pixels[x : x + w, y : y + h]
    return int(numpy.count_nonzero(region != Colors.BG))


def color_count(fb: FrameBuffer, color: int, x: int, y: int, w: int, h: int) -> int:
    region = fb.pixels[x : x + w, y : y + h]
    return int(numpy.count_nonzero(region == color))


# ── Rect ──────────────────────────────────────────────────────────────────────


class TestRect:
    def test_cx_bottom(self) -> None:
        rect = Rect(100, 20, 120, 40)
        assert rect.cx == 160
        assert rect.bottom == 60

    def test_inset(self) -> None:
        rect = Rect(0, 0, 120, 60)
        inner = rect.inset(10, 5)
        assert (inner.x, inner.y, inner.w, inner.h) == (10, 5, 100, 50)

    def test_inset_clamps_to_one(self) -> None:
        rect = Rect(0, 0, 10, 10)
        inner = rect.inset(8, 8)
        assert inner.w == 1 and inner.h == 1


# ── Label ─────────────────────────────────────────────────────────────────────


class TestLabel:
    def test_left_align(self) -> None:
        fb = make_fb()
        Label("ABC", "sm", Colors.WHITE, "l").render(fb, Rect(10, 10, 200, 12))
        # Текст у левого края rect: пиксели есть, до края — фон.
        assert non_bg_count(fb, 10, 10, 30, 12) > 0
        assert non_bg_count(fb, 180, 10, 30, 12) == 0

    def test_center_align(self) -> None:
        fb = make_fb()
        Label("ABC", "sm", Colors.WHITE, "c").render(fb, Rect(0, 10, 200, 12))
        width = fb.text_width("ABC", "sm")
        # Центр rect = 100; текст отступает (200 - width) // 2 слева.
        left_pad = (200 - width) // 2
        assert non_bg_count(fb, left_pad + 2, 10, width - 4, 12) > 0
        assert non_bg_count(fb, 0, 10, left_pad - 4, 12) == 0

    def test_right_align(self) -> None:
        fb = make_fb()
        Label("ABC", "sm", Colors.WHITE, "r").render(fb, Rect(0, 10, 200, 12))
        width = fb.text_width("ABC", "sm")
        # Текст упирается в правый край rect.
        assert non_bg_count(fb, 200 - width, 10, width, 12) > 0
        assert non_bg_count(fb, 0, 10, 30, 12) == 0

    def test_empty_text_noop(self) -> None:
        fb = make_fb()
        Label("", "sm", Colors.WHITE).render(fb, Rect(0, 0, 100, 12))
        assert non_bg_count(fb, 0, 0, 100, 12) == 0


# ── Marker / Bar ──────────────────────────────────────────────────────────────


class TestMarker:
    def test_square_of_color(self) -> None:
        fb = make_fb()
        Marker(Colors.CONNECTED, size=7).render(fb, Rect(10, 10, 20, 13))
        # Квадрат 7×7, отцентрирован по вертикали (y = 10 + (13-7)//2 = 13).
        assert color_count(fb, Colors.CONNECTED, 10, 13, 7, 7) == 49


class TestBar:
    def test_frac_draws_fill(self) -> None:
        fb = make_fb()
        Bar(0.5).render(fb, Rect(10, 10, 100, 8))
        # Фон-бар всегда (100×8), заливка ~половина: 50×8 = 400 px.
        fill_area = color_count(fb, Colors.TRACK_FILL, 10, 10, 100, 8)
        assert fill_area > 300
        assert color_count(fb, Colors.ENCODER_BG, 10, 10, 100, 8) == 800 - fill_area

    def test_none_draws_nothing(self) -> None:
        fb = make_fb()
        Bar(None).render(fb, Rect(10, 10, 100, 8))
        assert non_bg_count(fb, 10, 10, 100, 8) == 0

    def test_clamped(self) -> None:
        fb = make_fb()
        Bar(1.5).render(fb, Rect(10, 10, 100, 8))
        assert color_count(fb, Colors.TRACK_FILL, 10, 10, 100, 8) == 800


# ── Column / ColumnGrid ───────────────────────────────────────────────────────


class TestColumn:
    def test_label_value_bar(self) -> None:
        fb = make_fb()
        Column("GATE (E3)", "45 %", 0.45).render(fb, Rect(240, BODY_Y0, COL_W, 60))
        # Метка мелко сверху, значение крупно, бар с заливкой под значением.
        assert non_bg_count(fb, 240, BODY_Y0 + 4, COL_W, 12) > 3
        assert non_bg_count(fb, 240, BODY_Y0 + 22, COL_W, 16) > 5
        assert color_count(fb, Colors.TRACK_FILL, 250, BODY_Y0 + 46, 100, 8) > 10

    def test_no_frac_no_bar(self) -> None:
        fb = make_fb()
        Column("SRC (E1)", "—").render(fb, Rect(0, BODY_Y0, COL_W, 60))
        assert color_count(fb, Colors.TRACK_FILL, 10, BODY_Y0 + 46, 100, 8) == 0


class TestColumnGrid:
    def test_eight_columns_of_120(self) -> None:
        grid = ColumnGrid()
        assert grid.count == 8
        for i in range(8):
            rect = grid.rect(i)
            assert rect.x == i * 120
            assert rect.w == COL_W
        assert grid.rect(8).x == 0  # i по модулю count
        assert grid.center_x(0) == 60

    def test_custom_vertical_range(self) -> None:
        grid = ColumnGrid(y0=100, y1=120)
        assert (grid.rect(3).y, grid.rect(3).h) == (100, 20)


# ── TabStrip ──────────────────────────────────────────────────────────────────


class TestTabStrip:
    def test_active_cell_white(self) -> None:
        fb = make_fb()
        TabStrip(TAB_CELLS, active="gen").render(fb, Rect(0, 0, FRAME_W, 22))
        # Активная ячейка GEN: белая заливка (инверсия текста).
        gen_cx = dict(TAB_CELLS)["GEN"]
        assert color_count(fb, Colors.WHITE, gen_cx - 50, 2, 100, 18) > 100
        # Неактивная PORTS: белой заливки нет.
        ports_cx = dict(TAB_CELLS)["PORTS"]
        assert color_count(fb, Colors.WHITE, ports_cx - 50, 2, 100, 18) == 0

    def test_no_active_all_passive(self) -> None:
        fb = make_fb()
        TabStrip(TAB_CELLS, active=None).render(fb, Rect(0, 0, FRAME_W, 22))
        assert color_count(fb, Colors.WHITE, 0, 0, FRAME_W, 22) == 0


# ── Screens: реестр и композитор ──────────────────────────────────────────────


class TestScreens:
    def test_default_screens_registered(self) -> None:
        screens = Screens()
        assert screens.names() == tuple(s.name for s in DEFAULT_SCREENS)
        assert screens.names() == (
            "tracks",
            "gen",
            "macro",
            "wizard",
            "scale",
            "setup",
            "ports",
            "demo",
        )

    def test_register_custom_screen(self) -> None:
        """Расширяемость: новый экран — подкласс Screen + register().

        Экран без своего DTO переопределяет draw() целиком; draw_body
        остаётся no-op (абстрактный метод требует реализации).
        """

        class CustomScreen(Screen):
            name = "custom"
            view_attr = "tracks"  # не используется — рисуем в draw()

            def draw_body(self, fb: FrameBuffer, body: object) -> None:
                pass  # draw() переопределён ниже

            def draw(self, fb: FrameBuffer, view: ScreenView) -> None:
                Label("CUSTOM", "lg", Colors.WHITE).render(fb, Rect(4, 40, 200, 18))

        screens = Screens()
        screens.register(CustomScreen())
        assert "custom" in screens.names()

        view = ScreenView(screen="custom", title="CUSTOM", tab=None, flash=None)
        fb = make_fb()
        screens.draw_body(fb, view)
        assert non_bg_count(fb, 4, 40, 200, 18) > 5

    def test_register_duplicate_raises(self) -> None:
        screens = Screens()
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            screens.register(DEFAULT_SCREENS[0])

    def test_unknown_screen_clears_body(self) -> None:
        """Неизвестный view.screen — body заливается фоном, без падения."""
        screens = Screens()
        view = ScreenView(screen="nope", title="?", tab=None, flash=None)
        fb = make_fb()
        fb.fill_rect(0, 40, 50, 50, Colors.WHITE)  # «мусор» в body
        screens.draw_body(fb, view)
        assert non_bg_count(fb, 0, BODY_Y0, FRAME_W, 120) == 0

    def test_screen_view_none_body_clears(self) -> None:
        """DTO тела None (например track=None) — body очищается фоном."""
        screens = Screens()
        view = ScreenView(screen="gen", title="GEN", tab="gen", flash=None)
        fb = make_fb()
        fb.fill_rect(0, 40, 50, 50, Colors.WHITE)
        screens.draw_body(fb, view)
        assert non_bg_count(fb, 0, BODY_Y0, FRAME_W, 120) == 0

    def test_draw_header_renders_title_and_flash(self) -> None:
        screens = Screens()
        view = ScreenView(screen="tracks", title="TRACKS", tab=None, flash="error: x")
        fb = make_fb()
        screens.draw_header(fb, view)
        assert non_bg_count(fb, 4, 23, 300, 12) > 5  # заголовок
        assert color_count(fb, Colors.DISCONNECTED, 400, 25, 556, 10) > 3  # error:

    def test_draw_full_frame(self) -> None:
        """draw() = header + body целиком (спайки/эмулятор)."""
        screens = Screens()
        row = TrackRowView(
            name="Pad 1",
            kind="melodic",
            profile="pad",
            channel=0,
            port=None,
            frozen=False,
            mutation_count=0,
            selected=True,
            color=Colors.CONNECTED,
        )
        view = ScreenView(
            screen="tracks", title="TRACKS 1-8/1", tab=None, flash=None, tracks=(row,)
        )
        fb = make_fb()
        screens.draw(fb, view)
        assert non_bg_count(fb, 0, 0, FRAME_W, 22) > 10  # таб-бар
        assert non_bg_count(fb, 0, 23, 300, 12) > 5  # заголовок
        assert non_bg_count(fb, 0, BODY_Y0, FRAME_W, 120) > 20  # body
