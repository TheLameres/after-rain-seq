"""Экраны Push 2 (D2) — классы Screen + реестр/композитор Screens.

Расширяемая структура (D2-7): новый экран — подкласс :class:`Screen`
(``name`` = ``ScreenId.value``, ``view_attr`` = поле :class:`ScreenView`
с DTO тела, ``draw_body`` собирает тело из виджетов ``widgets.py``),
зарегистрированный в :class:`Screens` — в конструкторе или через
``register()``. Композитор рисует таб-бар + заголовок и диспетчеризует
body по ``ScreenView.screen``.

Module-level ``draw_*`` — тонкие обёртки над ``draw_body`` экранов:
канонический способ нарисовать тело напрямую (пиксельные тесты, spikes),
без сборки ``ScreenView``. Геометрия импортируется из ``widgets.py``
(каноническое место определения колонок).

Никакой логики и никаких импортов выше devices/ — только view-модели
из ``display_state.py``, примитивы ``renderer.py`` и виджеты ``widgets.py``.

Geometry (960×160): таб-бар y 0–21, заголовок y 22–35, body y 36–160.
Body — восемь колонок по 120 px ровно под энкодерами E1–E8 и Lower Row.
Нижнего статус-бара нет (D2-5): BPM — по касанию Tempo Encoder.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, ClassVar

from src.devices.display_state import (
    DemoView,
    PortsView,
    ScaleView,
    ScreenView,
    SyncView,
    TrackDetailView,
    TrackMacroView,
    TrackRowView,
    WizardView,
)
from src.devices.push2.renderer import FRAME_W, Colors, FrameBuffer
from src.devices.push2.widgets import (
    BODY_Y0,
    BODY_Y1,
    COL_W,
    Column,
    ColumnGrid,
    Label,
    Marker,
    Rect,
    SegmentTabs,
    TabStrip,
    slot_cells,
)

__all__ = [
    "BODY_Y0",
    "BODY_Y1",
    "COL_W",
    "DEFAULT_SCREENS",
    "DEMO_BOTTOM_H",
    "DEMO_COLS_Y0",
    "DEMO_COLS_Y1",
    "DEMO_TABS_H",
    "TAB_CELLS",
    "DemoScreen",
    "PortsScreen",
    "ScaleScreen",
    "Screen",
    "Screens",
    "SetupScreen",
    "TrackGenScreen",
    "TrackMacroScreen",
    "TracksScreen",
    "WizardScreen",
    "draw_demo",
    "draw_header",
    "draw_ports",
    "draw_scale",
    "draw_setup",
    "draw_tab_bar",
    "draw_track",
    "draw_track_macro",
    "draw_tracks",
    "draw_wizard",
]

# Ячейки таб-бара: (метка, x-центр). Центры — под физическими кнопками,
# которыми открывается вкладка (схема MidiMapping.png из спеки Ableton):
# GEN под Clip (CC 113), MACRO под Device (CC 110), PORTS под Upper Row 5
# (CC 106). Позиции взяты с картинки спеки, а не выведены из CC: номера CC
# у Clip/Device лежат вне диапазона Upper Row, поэтому ряд из CC не строится.
TAB_CELLS: tuple[tuple[str, int], ...] = (
    ("GEN", 906),
    ("MACRO", 800),
    ("PORTS", 540),
)

# Цвет flash-строки: жёлтый для сообщений, красный — для error:.
FLASH = Colors.BPM_MIDI  # orange — reuse: заметный, но не крикливый
FLASH_ERROR = Colors.DISCONNECTED

_ROW_H = 14  # высота строки списка (шрифт sm)
_TRACK_ROW_H = 13  # строки TRACKS компактнее: внизу полоса имён под Lower Row

# DEMO: полоса верхних вкладок 22 px внутрь body, полоса нижних — 16 px от низа.
# Колонки живут строго между ними, иначе TabStrip/Column перекрывают друг друга.
DEMO_TABS_H = 22
DEMO_BOTTOM_H = 16
DEMO_COLS_Y0 = BODY_Y0 + DEMO_TABS_H
DEMO_COLS_Y1 = BODY_Y1 - DEMO_BOTTOM_H

# Цвета статусов портов (значения из PortSummary.status).
_PORT_STATUS_COLORS = {
    "connected": Colors.CONNECTED,
    "disconnected": Colors.DISCONNECTED,
    "ambiguous": Colors.BPM_MIDI,
    "error": Colors.DISCONNECTED,
}


def _percent(value: float | None) -> tuple[str, float | None]:
    """0..1 → («45 %», 0.45); None → («—», None)."""
    if value is None:
        return "—", None
    frac = max(0.0, min(1.0, value))
    return f"{round(frac * 100)} %", frac


# ── Базовый класс экрана ──────────────────────────────────────────────────────


class Screen(ABC):
    """Один экран Push 2: тело body из виджетов.

    Атрибуты класса:
        name: Идентификатор экрана (``ScreenId.value``) — ключ реестра.
        view_attr: Поле :class:`ScreenView`, в котором лежит DTO тела
            этого экрана (``None`` — body очищается фоном).

    Новый экран: унаследоваться, задать ``name``/``view_attr``, собрать
    ``draw_body`` из виджетов ``widgets.py``, зарегистрировать в Screens.
    """

    name: ClassVar[str]
    view_attr: ClassVar[str]

    @abstractmethod
    def draw_body(self, fb: FrameBuffer, body: Any) -> None:
        """Отрисовать тело body на FrameBuffer (body очищает сам себя)."""

    def draw(self, fb: FrameBuffer, view: ScreenView) -> None:
        """Отрисовать тело из единого ScreenView (вызывает Screens)."""
        body = getattr(view, self.view_attr)
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
        if body is not None:
            self.draw_body(fb, body)


# ── TRACKS ────────────────────────────────────────────────────────────────────


class TracksScreen(Screen):
    """TRACKS (Session): список дорожек + полоса имён под Lower Row."""

    name = "tracks"
    view_attr = "tracks"

    def draw_body(self, fb: FrameBuffer, body: tuple[TrackRowView, ...]) -> None:
        rows = body
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
        for i, row in enumerate(rows):
            y = BODY_Y0 + i * _TRACK_ROW_H
            cursor = ">" if row.selected else " "
            Label(cursor, "sm", Colors.BPM_LINK if row.selected else Colors.DIM).render(
                fb, Rect(4, y, 12, _TRACK_ROW_H)
            )
            # Цветной маркер дорожи (свой цвет у каждой дорожки).
            Marker(row.color or Colors.DIM, size=8).render(
                fb, Rect(16, y, 8, _TRACK_ROW_H)
            )
            name_color = Colors.WHITE if row.selected else Colors.GRAY
            Label(row.name, "sm", name_color).render(fb, Rect(30, y, 150, _TRACK_ROW_H))
            Label(row.profile, "sm", Colors.GRAY).render(
                fb, Rect(190, y, 90, _TRACK_ROW_H)
            )
            Label(f"ch{row.channel}", "sm", Colors.GRAY).render(
                fb, Rect(290, y, 70, _TRACK_ROW_H)
            )
            port = f"> {row.port}" if row.port else "-"
            Label(port, "sm", Colors.GRAY if row.port else Colors.DIM).render(
                fb, Rect(370, y, 190, _TRACK_ROW_H)
            )
            state = "FROZEN" if row.frozen else f"mut:{row.mutation_count}"
            state_color = Colors.BPM_LINK if row.frozen else Colors.DIM
            Label(state, "sm", state_color).render(fb, Rect(570, y, 110, _TRACK_ROW_H))
            if row.kind == "drum":
                Label("DRUM", "sm", Colors.BPM_MIDI).render(
                    fb, Rect(690, y, 80, _TRACK_ROW_H)
                )

        # Нижняя полоса: имена дорожек — колонка i ровно под Lower Row i+1.
        grid = ColumnGrid()
        y = BODY_Y1 - 15
        for i in range(grid.count):
            slot = rows[i] if i < len(rows) else None
            rect = Rect(grid.rect(i).x, y, COL_W, 13)
            if slot is None or slot.kind == "":  # пустой слот страницы
                Label("—", "sm", Colors.DIM).render(fb, Rect(rect.x + 8, y, 20, 13))
                continue
            Marker(slot.color or Colors.DIM).render(fb, Rect(rect.x + 4, y, 7, 13))
            name = slot.name
            max_w = COL_W - 26
            while name and fb.text_width(name, "sm") > max_w:
                name = name[:-1]
            color = Colors.WHITE if slot.selected else Colors.GRAY
            Label(name, "sm", color).render(fb, Rect(rect.x + 16, y, max_w, 13))


# ── TRACK GEN (генерация) ─────────────────────────────────────────────────────


class TrackGenScreen(Screen):
    """GEN (Clip): колонки E1–E5 — SRC/SRC2/GATE/DEN/MUT."""

    name = "gen"
    view_attr = "track"

    def draw_body(self, fb: FrameBuffer, body: TrackDetailView) -> None:
        view = body
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
        fb.fill_rect(0, BODY_Y0, 4, BODY_Y1 - BODY_Y0, view.color or Colors.DIM)

        src = view.sources[0] if len(view.sources) > 0 else "—"
        src2 = view.sources[1] if len(view.sources) > 1 else "—"
        gate_text, gate_frac = _percent(view.gate if view.kind != "drum" else None)
        den_text, den_frac = _percent(view.density)
        mut_text, mut_frac = _percent(view.mutate)

        grid = ColumnGrid()
        Column("SRC (E1)", src).render(fb, grid.rect(0))
        Column("SRC2 (E2)", src2).render(fb, grid.rect(1))
        Column("GATE (E3)", gate_text, gate_frac).render(fb, grid.rect(2))
        Column("DEN (E4)", den_text, den_frac).render(fb, grid.rect(3))
        Column("MUT (E5)", mut_text, mut_frac).render(fb, grid.rect(4))

        # Строка внизу: куда играет дорожка.
        y = BODY_Y1 - 20
        Label("PORT", "sm", Colors.DIM).render(fb, Rect(12, y, 44, 12))
        port = f"> {view.port}" if view.port else "—"
        Label(port, "sm", Colors.GRAY).render(fb, Rect(60, y, 230, 12))
        Label("CH", "sm", Colors.DIM).render(fb, Rect(300, y, 26, 12))
        Label(str(view.channel), "sm", Colors.GRAY).render(fb, Rect(330, y, 40, 12))
        Label("PROFILE", "sm", Colors.DIM).render(fb, Rect(420, y, 64, 12))
        Label(view.profile, "sm", Colors.GRAY).render(fb, Rect(490, y, 150, 12))
        if view.kind != "drum":
            Label("VOICING", "sm", Colors.DIM).render(fb, Rect(650, y, 72, 12))
            Label(view.voicing or "—", "sm", Colors.GRAY).render(
                fb, Rect(730, y, 120, 12)
            )


# ── TRACK MACRO (макро-контроль синтов) ───────────────────────────────────────


class TrackMacroScreen(Screen):
    """MACRO (Device): колонки E1–E3 — TONE/SPACE/DEPTH (performance-CC)."""

    name = "macro"
    view_attr = "track_macro"

    def draw_body(self, fb: FrameBuffer, body: TrackMacroView) -> None:
        view = body
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
        fb.fill_rect(0, BODY_Y0, 4, BODY_Y1 - BODY_Y0, view.color or Colors.DIM)

        labels = ("TONE (E1)", "SPACE (E2)", "DEPTH (E3)")
        grid = ColumnGrid()
        for i, (label, value) in enumerate(zip(labels, view.macros, strict=True)):
            if value < 0:
                Column(label, "—").render(fb, grid.rect(i))
            else:
                frac = max(0, min(127, value)) / 127.0
                Column(label, f"{round(frac * 100)} %", frac).render(fb, grid.rect(i))

        # Строка внизу: куда уходят CC.
        y = BODY_Y1 - 20
        if view.port:
            Label("PORT", "sm", Colors.DIM).render(fb, Rect(12, y, 44, 12))
            Label(f"> {view.port}", "sm", Colors.GRAY).render(fb, Rect(60, y, 230, 12))
            Label("CH", "sm", Colors.DIM).render(fb, Rect(300, y, 26, 12))
            Label(str(view.channel), "sm", Colors.GRAY).render(fb, Rect(330, y, 40, 12))
        else:
            Label("NO PORT — CC NOT SENT", "sm", Colors.DISCONNECTED).render(
                fb, Rect(12, y, 400, 12)
            )


# ── WIZARD (создание дорожки) ─────────────────────────────────────────────────


class WizardScreen(Screen):
    """Wizard Add Track: окно вариантов (kind / profile / route) с курсором."""

    name = "wizard"
    view_attr = "wizard"

    def draw_body(self, fb: FrameBuffer, body: WizardView) -> None:
        view = body
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
        step_label = {
            "kind": "KIND",
            "profile": "PROFILE",
            "route": "ROUTE (PORT)",
        }.get(view.step, view.step.upper())
        Label(f"STEP: {step_label}", "sm", Colors.DIM).render(
            fb, Rect(4, BODY_Y0, 240, _ROW_H)
        )
        for i, option in enumerate(view.options):
            y = BODY_Y0 + 2 * _ROW_H + i * _ROW_H
            selected = i == view.selected
            cursor = ">" if selected else " "
            Label(cursor, "sm", Colors.BPM_LINK if selected else Colors.DIM).render(
                fb, Rect(4, y, 12, _ROW_H)
            )
            Label(option, "sm", Colors.WHITE if selected else Colors.GRAY).render(
                fb, Rect(20, y, 300, _ROW_H)
            )
        if view.page_count > 1:
            Label(f"{view.page + 1}/{view.page_count}", "sm", Colors.DIM, "r").render(
                fb, Rect(FRAME_W - 124, BODY_Y0, 120, _ROW_H)
            )


# ── SCALE (корень/лад) ────────────────────────────────────────────────────────

_ROOT_CELL_W = 74  # 12 корней в ряд (12×74 = 888, x 12..900)
_SCALE_COLS = 4  # лады сеткой 4×2
_SCALE_CELL_W = 222
_SCALE_CELL_H = 38


class ScaleScreen(Screen):
    """SCALE (образец — выбор шкалы Push 2): корни сверху, лады сеткой 4×2."""

    name = "scale"
    view_attr = "scale"

    def draw_body(self, fb: FrameBuffer, body: ScaleView) -> None:
        view = body
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)

        # Ряд корней (заголовки столбцов).
        y_roots = BODY_Y0 + 2
        for i, root in enumerate(view.roots):
            x = 12 + i * _ROOT_CELL_W
            active = i == view.root_index
            if active:
                fb.fill_rect(x - 3, y_roots - 2, _ROOT_CELL_W - 6, 14, Colors.WHITE)
            Label(root, "sm", Colors.BLACK if active else Colors.GRAY).render(
                fb, Rect(x, y_roots, _ROOT_CELL_W - 6, 14)
            )

        # Сетка ладов.
        y_grid = y_roots + 24
        for i, scale in enumerate(view.scales):
            col, row = i % _SCALE_COLS, i // _SCALE_COLS
            x = 12 + col * _SCALE_CELL_W
            y = y_grid + row * _SCALE_CELL_H
            active = i == view.scale_index
            if active:
                fb.rect(x - 4, y - 3, _SCALE_CELL_W - 12, 16, Colors.WHITE)
            Label(scale, "sm", Colors.WHITE if active else Colors.GRAY).render(
                fb, Rect(x, y, _SCALE_CELL_W - 12, 14)
            )


# ── SETUP (суб-вкладки настроек) ──────────────────────────────────────────────


class SetupScreen(Screen):
    """SETUP: тело активной суб-вкладки + таб-бар внизу body."""

    name = "setup"
    view_attr = "sync"

    def draw_body(self, fb: FrameBuffer, body: SyncView) -> None:
        view = body
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
        y0 = BODY_Y0 + 8

        if view.tab == "midi":
            Label("MIDI CLOCK DEVICE", "sm", Colors.DIM).render(
                fb, Rect(4, y0, 200, 14)
            )
            Label(view.midi_device, "sm", Colors.WHITE).render(
                fb, Rect(4, y0 + 16, 400, 14)
            )
            Label("select: config (sync.midi_clock_device)", "sm", Colors.GRAY).render(
                fb, Rect(4, y0 + 40, 400, 14)
            )
        elif view.tab == "link":
            Label("ABLETON LINK", "sm", Colors.DIM).render(fb, Rect(4, y0, 200, 14))
            state = "active" if view.link_active else "off"
            Label(f"{state}  peers: {view.link_peers}", "sm", Colors.WHITE).render(
                fb, Rect(4, y0 + 16, 400, 14)
            )
            Label(
                "enable: package abletonlink (sync.clock_source)", "sm", Colors.GRAY
            ).render(fb, Rect(4, y0 + 40, 400, 14))
        else:  # clock
            Label("SOURCE", "sm", Colors.DIM).render(fb, Rect(4, y0, 60, 14))
            x = 70
            for source in ("internal", "midi", "link"):
                active = source == view.source
                marker = "*" if active else "o"
                color = Colors.CONNECTED if active else Colors.DIM
                Label(marker, "sm", color).render(fb, Rect(x, y0, 10, 14))
                Label(source, "sm", color if active else Colors.GRAY).render(
                    fb, Rect(x + 10, y0, 90, 14)
                )
                x += fb.text_width(source, "sm") + 34
            if view.pending:
                Label(f"-> {view.pending}...", "sm", FLASH).render(
                    fb, Rect(x + 10, y0, 120, 14)
                )

            y1 = y0 + 26
            Label("DEVICE", "sm", Colors.DIM).render(fb, Rect(4, y1, 60, 14))
            Label(view.midi_device, "sm", Colors.GRAY).render(fb, Rect(70, y1, 400, 14))

            y2 = y1 + 26
            Label("TEMPO", "sm", Colors.DIM).render(fb, Rect(4, y2, 60, 14))
            Label(f"{view.bpm:.1f} (local)", "sm", Colors.WHITE).render(
                fb, Rect(70, y2, 200, 14)
            )

            y3 = y2 + 26
            Label("STATUS", "sm", Colors.DIM).render(fb, Rect(4, y3, 60, 14))
            parts = ["running" if view.running else "stopped"]
            if view.link_active:
                parts.append(f"LINK peers {view.link_peers}")
            Label("  ".join(parts), "sm", Colors.GRAY).render(fb, Rect(70, y3, 320, 14))
            if view.error:
                Label(view.error, "sm", FLASH_ERROR).render(fb, Rect(400, y3, 500, 14))

        # Таб-бар внизу body (образец — экран Setup Push standalone).
        SegmentTabs(view.tabs, active=view.tab).render(
            fb, Rect(0, BODY_Y1 - 16, FRAME_W, 16)
        )


# ── DEMO (образец экрана фреймворка) ──────────────────────────────────────────


class DemoScreen(Screen):
    """DEMO (Note): вкладки сверху и снизу + 8 колонок под энкодерами.

    Образец для новых экранов (D2-8): верхняя полоса — TabStrip с
    равномерными центрами, середина — ColumnGrid под E1–E8, низ —
    SegmentTabs на всю ширину. Состояние крутят E1 (верхние вкладки)
    и E2 (нижние), E3–E8 — значения 0..127 с барами.

    Вертикальная раскладка body (y 36–160): верхние вкладки 36–58,
    колонки 58–144, нижние вкладки 144–160 — колонки не заходят под
    таб-бар, иначе TabStrip закрашивает подписи «TOP (E1)»/E3–E8.
    """

    name = "demo"
    view_attr = "demo"

    def draw_body(self, fb: FrameBuffer, body: DemoView) -> None:
        view = body
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
        if not view.top_tabs:
            return  # пустой DTO — тело остаётся фоном (как у Screens для неизвестного экрана)

        # Верхние вкладки: по одной на физический слот (120 px), как кнопки Upper Row.
        n = len(view.top_tabs)
        cells = slot_cells(view.top_tabs)
        active_top = view.top_tabs[view.top_index % n]
        TabStrip(cells, active=active_top).render(
            fb, Rect(0, BODY_Y0, FRAME_W, 22)
        )

        # Середина: восемь колонок под E1–E8 (строго между рядами вкладок).
        grid = ColumnGrid(y0=DEMO_COLS_Y0, y1=DEMO_COLS_Y1)
        Column("TOP (E1)", active_top).render(fb, grid.rect(0))
        Column("BOTTOM (E2)", self._bottom_name(view)).render(fb, grid.rect(1))
        for i, value in enumerate(view.values[:6]):
            raw = max(0, min(127, value))
            Column(f"E{i + 3}", str(raw), raw / 127.0).render(fb, grid.rect(i + 2))

        # Нижние вкладки: равные сегменты (образец — низ экрана Setup).
        SegmentTabs(view.bottom_tabs, active=self._bottom_name(view)).render(
            fb, Rect(0, BODY_Y1 - 16, FRAME_W, 16)
        )

    @staticmethod
    def _bottom_name(view: DemoView) -> str:
        """Активная нижняя вкладка; пустой ряд не должен ронять рендер."""
        if not view.bottom_tabs:
            return ""
        return view.bottom_tabs[view.bottom_index % len(view.bottom_tabs)]


# ── PORTS ─────────────────────────────────────────────────────────────────────


class PortsScreen(Screen):
    """PORTS: список портов (статус цветом) + строка ROUTE."""

    name = "ports"
    view_attr = "ports"

    def draw_body(self, fb: FrameBuffer, body: PortsView) -> None:
        view = body
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
        for i, row in enumerate(view.rows):
            y = BODY_Y0 + i * _ROW_H
            selected = i == view.selected
            cursor = ">" if selected else " "
            Label(cursor, "sm", Colors.BPM_LINK if selected else Colors.DIM).render(
                fb, Rect(4, y, 12, _ROW_H)
            )
            Label(row.label, "sm", Colors.WHITE if selected else Colors.GRAY).render(
                fb, Rect(20, y, 170, _ROW_H)
            )
            color = _PORT_STATUS_COLORS.get(row.status, Colors.DIM)
            Label(row.status, "sm", color).render(fb, Rect(200, y, 150, _ROW_H))
            Label(row.detail, "sm", Colors.GRAY).render(fb, Rect(360, y, 500, _ROW_H))

        # ROUTE-строка внизу body.
        y = BODY_Y1 - 16
        Label("ROUTE", "sm", Colors.DIM).render(fb, Rect(4, y, 60, 14))
        route = f"{view.route_track} -> " + (
            f"> {view.route_port}" if view.route_port else "-"
        )
        Label(route, "sm", Colors.WHITE).render(fb, Rect(70, y, 500, 14))


# ── Реестр и композитор ───────────────────────────────────────────────────────

DEFAULT_SCREENS: tuple[Screen, ...] = (
    TracksScreen(),
    TrackGenScreen(),
    TrackMacroScreen(),
    WizardScreen(),
    ScaleScreen(),
    SetupScreen(),
    PortsScreen(),
    DemoScreen(),
)


def _draw_header_bar(fb: FrameBuffer, title: str, flash: str | None) -> None:
    """y 22–35: заголовок слева (под таб-баром), flash-строка справа."""
    fb.fill_rect(0, 22, FRAME_W, 14, Colors.BG)
    Label(title, "md", Colors.WHITE).render(fb, Rect(4, 23, 480, 12))
    if flash:
        color = FLASH_ERROR if flash.startswith("error:") else FLASH
        Label(flash, "sm", color, "r").render(fb, Rect(400, 25, FRAME_W - 404, 10))


class Screens:
    """Реестр экранов + композитор: таб-бар, заголовок, body по ScreenView.

    ``draw_header()`` / ``draw_body()`` раздельны, чтобы PushDisplay
    перерисовывал только dirty-регионы; ``draw()`` — целиком (спайки).
    Неизвестный ``view.screen`` — body заливается фоном (не падаем).
    """

    def __init__(self, screens: Iterable[Screen] | None = None) -> None:
        self._by_name: dict[str, Screen] = {}
        for screen in DEFAULT_SCREENS if screens is None else screens:
            self.register(screen)

    def register(self, screen: Screen) -> None:
        """Добавить экран в реестр; дубликат имени — ValueError."""
        if screen.name in self._by_name:
            raise ValueError(f"экран {screen.name!r} уже зарегистрирован")
        self._by_name[screen.name] = screen

    def names(self) -> tuple[str, ...]:
        """Имена зарегистрированных экранов (порядок регистрации)."""
        return tuple(self._by_name)

    def draw_header(self, fb: FrameBuffer, view: ScreenView) -> None:
        """y 0–35: таб-бар вкладок + заголовок с flash-строкой."""
        TabStrip(TAB_CELLS, active=view.tab).render(fb, Rect(0, 0, FRAME_W, 22))
        _draw_header_bar(fb, view.title, view.flash)

    def draw_body(self, fb: FrameBuffer, view: ScreenView) -> None:
        """y 36–160: тело активного экрана (по имени из view.screen)."""
        screen = self._by_name.get(view.screen)
        if screen is None:
            fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.BG)
            return
        screen.draw(fb, view)

    def draw(self, fb: FrameBuffer, view: ScreenView) -> None:
        """Весь экран целиком (эмулятор, спайки, отладка)."""
        self.draw_header(fb, view)
        self.draw_body(fb, view)


# ── Module-level обёртки: прямая отрисовка тел (тесты, spikes) ────────────────


def draw_tab_bar(fb: FrameBuffer, active: str | None) -> None:
    """y 0–21: вкладки под своими кнопками; активная — белой заливкой."""
    TabStrip(TAB_CELLS, active=active).render(fb, Rect(0, 0, FRAME_W, 22))


def draw_header(fb: FrameBuffer, title: str, flash: str | None) -> None:
    """y 22–35: заголовок слева, flash-строка справа."""
    _draw_header_bar(fb, title, flash)


def draw_tracks(fb: FrameBuffer, rows: tuple[TrackRowView, ...]) -> None:
    """TRACKS body: список + имена внизу под Lower Row."""
    TracksScreen().draw_body(fb, rows)


def draw_track(fb: FrameBuffer, view: TrackDetailView) -> None:
    """GEN body: колонки SRC/SRC2/GATE/DEN/MUT."""
    TrackGenScreen().draw_body(fb, view)


def draw_track_macro(fb: FrameBuffer, view: TrackMacroView) -> None:
    """MACRO body: колонки TONE/SPACE/DEPTH."""
    TrackMacroScreen().draw_body(fb, view)


def draw_wizard(fb: FrameBuffer, view: WizardView) -> None:
    """Wizard body: окно вариантов с курсором."""
    WizardScreen().draw_body(fb, view)


def draw_scale(fb: FrameBuffer, view: ScaleView) -> None:
    """SCALE body: корни + лады."""
    ScaleScreen().draw_body(fb, view)


def draw_setup(fb: FrameBuffer, view: SyncView) -> None:
    """SETUP body: тело вкладки + таб-бар внизу."""
    SetupScreen().draw_body(fb, view)


def draw_ports(fb: FrameBuffer, view: PortsView) -> None:
    """PORTS body: список портов + ROUTE."""
    PortsScreen().draw_body(fb, view)


def draw_demo(fb: FrameBuffer, view: DemoView) -> None:
    """DEMO body: вкладки сверху/снизу + восемь колонок под E1–E8."""
    DemoScreen().draw_body(fb, view)
