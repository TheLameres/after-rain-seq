"""Пиксельные тесты рендереров экранов (screens.py).

Проверка — грубая, но устойчивая: в области элемента есть не-фоновые
пиксели нужного цвета (шрифты antialiased, точную маску не считаем).
"""

from __future__ import annotations

import numpy

from src.devices.display_state import (
    DemoView,
    PortRowView,
    PortsView,
    ScaleView,
    SyncView,
    TrackDetailView,
    TrackMacroView,
    TrackRowView,
    WizardView,
)
from src.devices.push2.display import _FONTS
from src.devices.push2.layout import FOOT_BAND, KNOBS_BAND, LOWER_BAND, UPPER_BAND
from src.devices.push2.renderer import FRAME_W, Colors, FrameBuffer
from src.devices.push2.screens import (
    BODY_Y0,
    BODY_Y1,
    draw_demo,
    draw_header,
    draw_ports,
    draw_scale,
    draw_setup,
    draw_track,
    draw_track_macro,
    draw_tracks,
    draw_wizard,
)
from src.devices.push2.track_colors import track_color
from src.devices.push2.widgets import SLOT_W


def make_fb() -> FrameBuffer:
    fb = FrameBuffer(fonts=_FONTS)
    fb.fill(Colors.BG)
    fb.dirty.clear()
    return fb


def non_bg_count(fb: FrameBuffer, x: int, y: int, w: int, h: int) -> int:
    """Число пикселей не фонового цвета в прямоугольнике."""
    region = fb.pixels[x : x + w, y : y + h]
    return int(numpy.count_nonzero(region != Colors.BG))


def color_count(fb: FrameBuffer, color: int, x: int, y: int, w: int, h: int) -> int:
    region = fb.pixels[x : x + w, y : y + h]
    return int(numpy.count_nonzero(region == color))


# ── Фабрики view ──────────────────────────────────────────────────────────────


def track_rows(n: int = 3, selected: int = 0) -> tuple[TrackRowView, ...]:
    return tuple(
        TrackRowView(
            name=f"Pad {i + 1}",
            kind="melodic",
            profile="pad",
            channel=i,
            port="Синт A" if i == 0 else None,
            frozen=i == 1,
            mutation_count=i * 3,
            selected=i == selected,
            color=track_color(i),
        )
        for i in range(n)
    )


def track_detail() -> TrackDetailView:
    return TrackDetailView(
        name="Stab 1",
        kind="melodic",
        profile="stab",
        channel=2,
        port="Синт A",
        sources=("Pad 1",),
        gate=0.25,
        voicing="1-4-7",
        density=0.5,
        mutate=0.5,
        color=track_color(1),
    )


def track_macro() -> TrackMacroView:
    return TrackMacroView(
        name="Stab 1",
        kind="melodic",
        channel=2,
        port="Синт A",
        macros=(64, 90, 20),
        color=track_color(1),
    )


def sync_view(**overrides) -> SyncView:
    base = {
        "source": "internal",
        "pending": None,
        "error": None,
        "bpm": 118.0,
        "running": True,
        "link_active": False,
        "link_peers": 0,
        "midi_device": "LCXL3 1 DAW Out",
    }
    base.update(overrides)
    return SyncView(**base)


def ports_view(**overrides) -> PortsView:
    base = {
        "rows": (
            PortRowView("Синт A", "connected", "LCXL3 1 DAW In"),
            PortRowView("Синт B", "disconnected", "no match"),
        ),
        "route_track": "Pad 1",
        "route_port": "Синт A",
        "selected": 0,
    }
    base.update(overrides)
    return PortsView(**base)


# ── TRACKS ────────────────────────────────────────────────────────────────────


class TestDrawTracks:
    def test_rows_render_non_bg(self) -> None:
        fb = make_fb()
        draw_tracks(fb, track_rows(8))
        assert non_bg_count(fb, 0, BODY_Y0, fb.width, 8 * 13) > 100

    def test_selected_cursor_uses_link_color(self) -> None:
        fb = make_fb()
        draw_tracks(fb, track_rows(3, selected=1))
        # Курсор строки 1 (y = BODY_Y0 + 13) в колонке x<16.
        assert color_count(fb, Colors.BPM_LINK, 0, BODY_Y0 + 13, 16, 13) > 0

    def test_unselected_cursor_is_dim(self) -> None:
        fb = make_fb()
        draw_tracks(fb, track_rows(3, selected=2))
        # Строка 0 не выбрана — там нет link-цвета.
        assert color_count(fb, Colors.BPM_LINK, 0, BODY_Y0, 16, 13) == 0

    def test_frozen_marker(self) -> None:
        fb = make_fb()
        draw_tracks(fb, track_rows(3, selected=0))
        # Строка 1 frozen — маркер на x≈560 (проверяем широкую зону).
        assert non_bg_count(fb, 550, BODY_Y0 + 13, 90, 13) > 3

    def test_color_markers(self) -> None:
        """У каждой строки — цветной маркер (8×8 на x≈16..24)."""
        fb = make_fb()
        rows = track_rows(3)
        draw_tracks(fb, rows)
        for i, row in enumerate(rows):
            y = BODY_Y0 + i * 13
            assert color_count(fb, row.color, 16, y + 2, 10, 10) > 20

    def test_empty_rows_ok(self) -> None:
        fb = make_fb()
        draw_tracks(fb, ())
        # Не падает; body залит фоном (полоса имён — тире DIM, не фон?).
        assert non_bg_count(fb, 0, BODY_Y0, fb.width, 100) == 0

    def test_bottom_names_under_lower_row(self) -> None:
        """Имена дорожек — в полосе LOWER, по колонкам под кнопками Lower Row."""
        fb = make_fb()
        rows = track_rows(3)
        draw_tracks(fb, rows)
        y = LOWER_BAND.y0 + 2
        for i, row in enumerate(rows):
            # Цветной маркер колонки i + не-фоновые пиксели имени.
            assert color_count(fb, row.color, i * 120 + 4, y + 2, 8, 8) > 10
            assert non_bg_count(fb, i * 120 + 16, y, 100, 12) > 3

    def test_bottom_empty_slot_dash(self) -> None:
        """Пустой слот (rows короче 8) — тире в колонке, маркера цвета нет."""
        fb = make_fb()
        draw_tracks(fb, track_rows(2))
        y = LOWER_BAND.y0 + 2
        col_x = 2 * 120
        # Тире нарисовано (не-фон в позиции текста колонки 2).
        assert non_bg_count(fb, col_x + 8, y, 12, 12) > 0
        # Цветной маркер пустого слота не рисуется (track_color(2) отсутствует).
        assert color_count(fb, track_color(2), col_x, y, 120, 12) == 0


# ── TRACK GEN / MACRO ─────────────────────────────────────────────────────────


class TestDrawTrack:
    def test_all_sections_render(self) -> None:
        fb = make_fb()
        draw_track(fb, track_detail())
        body_h = BODY_Y1 - BODY_Y0
        assert non_bg_count(fb, 0, BODY_Y0, fb.width, body_h) > 100

    def test_bars_drawn(self) -> None:
        fb = make_fb()
        draw_track(fb, track_detail())
        # Бары GATE/DEN/MUT — TRACK_FILL пиксели есть (макро уехали на MACRO).
        assert (
            color_count(fb, Colors.TRACK_FILL, 0, BODY_Y0, fb.width, BODY_Y1 - BODY_Y0)
            > 10
        )

    def test_color_strip_left(self) -> None:
        """Полоса цвета дорожи слева во всю высоту body."""
        fb = make_fb()
        view = track_detail()
        draw_track(fb, view)
        assert color_count(fb, view.color, 0, BODY_Y0, 4, BODY_Y1 - BODY_Y0) == 4 * (
            BODY_Y1 - BODY_Y0
        )

    def test_drum_gate_is_dash(self) -> None:
        fb = make_fb()
        view = TrackDetailView(
            **{**track_detail().__dict__, "kind": "drum", "profile": "drum"}
        )
        draw_track(fb, view)
        # Рисуется без падения; VOICING/порт на месте.
        assert non_bg_count(fb, 0, BODY_Y0, fb.width, BODY_Y1 - BODY_Y0) > 50


class TestDrawTrackMacro:
    def test_all_sections_render(self) -> None:
        fb = make_fb()
        draw_track_macro(fb, track_macro())
        assert non_bg_count(fb, 0, BODY_Y0, fb.width, BODY_Y1 - BODY_Y0) > 50

    def test_macro_bars_drawn(self) -> None:
        fb = make_fb()
        draw_track_macro(fb, track_macro())
        # Три оси TONE/SPACE/DEPTH — широкие бары.
        assert (
            color_count(fb, Colors.TRACK_FILL, 0, BODY_Y0, fb.width, BODY_Y1 - BODY_Y0)
            > 100
        )

    def test_color_strip_left(self) -> None:
        fb = make_fb()
        view = track_macro()
        draw_track_macro(fb, view)
        assert color_count(fb, view.color, 0, BODY_Y0, 4, BODY_Y1 - BODY_Y0) == 4 * (
            BODY_Y1 - BODY_Y0
        )

    def test_no_port_dashes_no_bars(self) -> None:
        fb = make_fb()
        view = TrackMacroView(
            **{**track_macro().__dict__, "port": None, "macros": (-1, -1, -1)}
        )
        draw_track_macro(fb, view)
        assert (
            color_count(fb, Colors.TRACK_FILL, 0, BODY_Y0, fb.width, BODY_Y1 - BODY_Y0)
            == 0
        )


# ── SCALE / SETUP / PORTS ─────────────────────────────────────────────────────


def scale_view(**overrides) -> ScaleView:
    base = {
        "roots": ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"),
        "scales": (
            "major",
            "dorian",
            "phrygian",
            "lydian",
            "mixolydian",
            "aeolian",
            "locrian",
            "minor",
        ),
        "root_index": 9,  # A
        "scale_index": 1,  # dorian
    }
    base.update(overrides)
    return ScaleView(**base)


class TestDrawScale:
    def test_renders(self) -> None:
        fb = make_fb()
        draw_scale(fb, scale_view())
        assert non_bg_count(fb, 0, BODY_Y0, fb.width, BODY_Y1 - BODY_Y0) > 100

    def test_roots_in_upper_and_lower_rows(self) -> None:
        """Корни обрамляют сетку ладов: 6 сверху, 6 снизу (эталон Scale Push 2)."""
        fb = make_fb()
        draw_scale(fb, scale_view())
        for slot in range(6):
            assert non_bg_count(fb, slot * SLOT_W, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h) > 5
            assert non_bg_count(fb, slot * SLOT_W, LOWER_BAND.y0, SLOT_W, LOWER_BAND.h) > 5
        # Слоты 7–8 рядов не назначены.
        assert non_bg_count(fb, 6 * SLOT_W, UPPER_BAND.y0, 2 * SLOT_W, UPPER_BAND.h) == 0
        assert non_bg_count(fb, 6 * SLOT_W, LOWER_BAND.y0, 2 * SLOT_W, LOWER_BAND.h) == 0

    def test_quint_circle_order(self) -> None:
        """Сверху — восходящие квинты (C G D A E B), снизу — от F."""
        from src.devices.push2.screens import scale_root_rows

        roots = scale_view().roots
        top, bottom = scale_root_rows(roots)
        assert top == ("C", "G", "D", "A", "E", "B")
        assert bottom == ("F", "A#", "D#", "G#", "C#", "F#")

    def test_active_root_filled_white(self) -> None:
        """Выбранная тоника — белая заливка кнопки своего слота."""
        fb = make_fb()
        draw_scale(fb, scale_view(root_index=7))  # G — слот 2 верхнего ряда
        active = color_count(fb, Colors.WHITE, SLOT_W, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h)
        plain = color_count(fb, Colors.WHITE, 0, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h)
        assert active > 50
        assert active > 30 * plain

    def test_scales_one_per_slot(self) -> None:
        """Лады — по одному на слот KNOBS (8 ладов = 8 слотов)."""
        fb = make_fb()
        draw_scale(fb, scale_view())
        for slot in range(len(scale_view().scales)):
            assert non_bg_count(fb, slot * SLOT_W, KNOBS_BAND.y0, SLOT_W, KNOBS_BAND.h) > 5

    def test_active_scale_filled_white(self) -> None:
        """Активный лад — белая заливка строки, соседи — только текст."""
        fb = make_fb()
        draw_scale(fb, scale_view(scale_index=1))  # dorian — слот 1
        active = color_count(fb, Colors.WHITE, SLOT_W, KNOBS_BAND.y0, SLOT_W, KNOBS_BAND.h)
        plain = color_count(fb, Colors.WHITE, 0, KNOBS_BAND.y0, SLOT_W, KNOBS_BAND.h)
        assert active > 500
        assert plain < active / 10

    def test_foot_shows_key_and_scale(self) -> None:
        """FOOT: текущая пара KEY/SCALE — в слотах 0 и 1."""
        fb = make_fb()
        draw_scale(fb, scale_view())
        assert non_bg_count(fb, 0, FOOT_BAND.y0, SLOT_W, FOOT_BAND.h) > 5
        assert non_bg_count(fb, SLOT_W, FOOT_BAND.y0, SLOT_W, FOOT_BAND.h) > 5

    def test_no_dead_placeholders(self) -> None:
        """Никаких заглушек LAYOUT/DIRECTION: пустые слоты 2–7 FOOT не рисуются."""
        fb = make_fb()
        draw_scale(fb, scale_view())
        assert non_bg_count(fb, 2 * SLOT_W, FOOT_BAND.y0, 6 * SLOT_W, FOOT_BAND.h) == 0

    def test_no_swing_panel(self) -> None:
        """Свинга на экране нет (D2-6): значение — по касанию Swing Encoder."""
        fb = make_fb()
        draw_scale(fb, scale_view())
        # Ни один слот не назван SWING — проверяем, что слоты ладов не содержат баров под значением.
        assert color_count(fb, Colors.TRACK_FILL, 0, KNOBS_BAND.y0, FRAME_W, KNOBS_BAND.h) == 0


class TestDrawSetup:
    def test_active_source_marked(self) -> None:
        """Активный источник клока — курсор списка E1 (слот 0, полоса KNOBS)."""
        fb = make_fb()
        draw_setup(fb, sync_view(source="link", link_active=True, link_peers=2))
        assert color_count(fb, Colors.BPM_LINK, 0, KNOBS_BAND.y0, SLOT_W, KNOBS_BAND.h) > 0

    def test_pending_shown(self) -> None:
        fb = make_fb()
        draw_setup(fb, sync_view(source="internal", pending="link"))
        # Строки вкладки живут правее слота 0, в полосе KNOBS.
        assert non_bg_count(fb, SLOT_W, KNOBS_BAND.y0, FRAME_W - SLOT_W, KNOBS_BAND.h) > 3

    def test_error_red(self) -> None:
        fb = make_fb()
        draw_setup(fb, sync_view(error="link module not installed"))
        assert (
            color_count(fb, Colors.DISCONNECTED, SLOT_W, KNOBS_BAND.y0, FRAME_W - SLOT_W, KNOBS_BAND.h)
            > 0
        )

    def test_tab_bar_highlights_active(self) -> None:
        """Таб-бар внизу body: активная суб-вкладка — белой заливкой."""
        fb = make_fb()
        draw_setup(fb, sync_view(tab="midi"))
        assert color_count(fb, Colors.WHITE, 320, BODY_Y1 - 20, 300, 18) > 50

    def test_midi_tab_body(self) -> None:
        fb = make_fb()
        draw_setup(fb, sync_view(tab="midi", midi_device="LCXL3 1 DAW Out"))
        assert non_bg_count(fb, 0, BODY_Y0, 500, 60) > 30


class TestDrawPorts:
    def test_rows_and_route(self) -> None:
        fb = make_fb()
        draw_ports(fb, ports_view())
        assert non_bg_count(fb, 0, BODY_Y0, fb.width, 2 * 14) > 30
        # ROUTE-строка внизу body.
        assert non_bg_count(fb, 0, BODY_Y1 - 22, 500, 18) > 5

    def test_status_colors(self) -> None:
        """Статусы портов цветом в полосе FOOT."""
        fb = make_fb()
        draw_ports(fb, ports_view())
        assert color_count(fb, Colors.CONNECTED, 0, FOOT_BAND.y0, FRAME_W, FOOT_BAND.h) > 0
        assert color_count(fb, Colors.DISCONNECTED, 0, FOOT_BAND.y0, FRAME_W, FOOT_BAND.h) > 0


# ── Таб-бар / заголовок (chrome) ──────────────────────────────────────────────


class TestChrome:
    def test_header_title(self) -> None:
        fb = make_fb()
        draw_header(fb, "TRACKS 1-8/2", None)
        # Заголовок в полосе y 0–13 (шрифт sm).
        assert non_bg_count(fb, 0, 0, 300, 14) > 10

    def test_header_flash_right(self) -> None:
        fb = make_fb()
        draw_header(fb, "TRACKS", "error: cycle")
        assert color_count(fb, Colors.DISCONNECTED, FRAME_W - 80, 0, 76, 14) > 3


class TestDrawWizard:
    def test_wizard_kind_step(self) -> None:
        fb = make_fb()
        view = WizardView(
            step="kind",
            options=("melodic", "drum"),
            selected=0,
            page=0,
            page_count=1,
            kind="melodic",
        )
        draw_wizard(fb, view)
        # Шаг — в полосе FOOT (слот 0).
        assert non_bg_count(fb, 0, FOOT_BAND.y0, 200, FOOT_BAND.h) > 5  # STEP: KIND
        # Варианты — списком в слоте 0 полосы KNOBS.
        assert non_bg_count(fb, 0, KNOBS_BAND.y0, SLOT_W, KNOBS_BAND.h) > 5
        # Курсор выбранного варианта — акцентным цветом.
        assert color_count(fb, Colors.BPM_LINK, 0, KNOBS_BAND.y0, SLOT_W, KNOBS_BAND.h) > 0

    def test_wizard_profile_page_label(self) -> None:
        fb = make_fb()
        view = WizardView(
            step="profile",
            options=("texture",),
            selected=0,
            page=1,
            page_count=2,
        )
        draw_wizard(fb, view)
        # Индикатор страницы «2/2» — второй слот FOOT.
        assert non_bg_count(fb, SLOT_W, FOOT_BAND.y0, SLOT_W, FOOT_BAND.h) > 3


def demo_view(
    top_index: int = 0,
    bottom_index: int = 0,
    values: tuple[int, ...] = (0, 32, 64, 96, 127, 10),
) -> DemoView:
    return DemoView(
        top_tabs=("alpha", "beta", "gamma", "delta"),
        bottom_tabs=("osc", "filter", "env", "fx", "mix"),
        top_index=top_index,
        bottom_index=bottom_index,
        values=values,
    )


class TestDemoScreenRender:
    def test_top_tabs_are_upper_row_buttons(self) -> None:
        """Верхние вкладки DEMO — кнопки Upper Row в полосе 14–31."""
        fb = make_fb()
        draw_demo(fb, demo_view())
        assert non_bg_count(fb, 0, UPPER_BAND.y0, FRAME_W, UPPER_BAND.h) > 10

    def test_active_top_tab_is_white_in_its_slot(self) -> None:
        fb = make_fb()
        draw_demo(fb, demo_view(top_index=2))  # gamma — слот 2 (x 240..360)
        assert color_count(fb, Colors.WHITE, 2 * SLOT_W, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h) > 50
        # Соседний слот не активен — белой заливки нет.
        assert color_count(fb, Colors.WHITE, SLOT_W, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h) == 0

    def test_lower_tabs_live_in_lower_row(self) -> None:
        """Нижние вкладки DEMO — кнопки Lower Row (124–141), а не полоса внизу body."""
        fb = make_fb()
        draw_demo(fb, demo_view())
        assert non_bg_count(fb, 0, LOWER_BAND.y0, FRAME_W, LOWER_BAND.h) > 10
        # Под-полоса FOOT у DEMO пуста: вкладки там не рисуются.
        assert non_bg_count(fb, 0, FOOT_BAND.y0, FRAME_W, FOOT_BAND.h) == 0

    def test_values_render_as_ranges_in_knobs(self) -> None:
        fb = make_fb()
        draw_demo(fb, demo_view(values=(127, 0, 64, 32, 96, 10)))
        # E3 — слот 2: значение и бар в полосе KNOBS.
        assert non_bg_count(fb, SLOT_W * 2, KNOBS_BAND.y0, SLOT_W, 60) > 5
        assert color_count(fb, Colors.TRACK_FILL, SLOT_W * 2, KNOBS_BAND.y0, SLOT_W, 60) > 10

    def test_zero_value_draws_no_fill(self) -> None:
        fb = make_fb()
        draw_demo(fb, demo_view(values=(127, 0, 64, 32, 96, 10)))
        # E4 — слот 3, value=0: число есть, заливки бара нет.
        assert non_bg_count(fb, SLOT_W * 3, KNOBS_BAND.y0, SLOT_W, 60) > 3
        assert color_count(fb, Colors.TRACK_FILL, SLOT_W * 3, KNOBS_BAND.y0, SLOT_W, 60) == 0


    def test_empty_tabs_do_not_crash(self) -> None:
        fb = make_fb()
        view = DemoView(
            top_tabs=(),
            bottom_tabs=(),
            top_index=0,
            bottom_index=0,
            values=(0, 0, 0, 0, 0, 0),
        )
        draw_demo(fb, view)  # не должно быть ZeroDivisionError / IndexError
        assert non_bg_count(fb, 0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0) == 0
