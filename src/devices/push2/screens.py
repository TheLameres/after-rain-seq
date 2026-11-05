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
from src.devices.push2.layout import (
    KNOBS_Y0,
    LOWER_BAND,
    Button,
    Empty,
    List,
    Range,
    ScreenLayout,
    SlotItem,
    Tabs,
    Text,
    render_layout,
)
from src.devices.push2.renderer import FRAME_W, Colors, FrameBuffer
from src.devices.push2.widgets import (
    BODY_Y0,
    BODY_Y1,
    COL_W,
    SLOT_COUNT,
    SLOT_W,
    ColumnGrid,
    Label,
    Marker,
    Rect,
)
from src.harmony.degree_names import format_degrees
from src.harmony.progressions import PROGRESSIONS
from src.harmony.voicings import VOICING_NAMES
from src.session.model.melodic_track import MAX_OCTAVE

__all__ = [
    "BODY_Y0",
    "BODY_Y1",
    "COL_W",
    "DEFAULT_SCREENS",
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
    "draw_track",
    "draw_track_macro",
    "draw_tracks",
    "draw_wizard",
]

# Цвет flash-строки: жёлтый для сообщений, красный — для error:.
FLASH = Colors.BPM_MIDI  # orange — reuse: заметный, но не крикливый
FLASH_ERROR = Colors.DISCONNECTED

# SCALE: корни обрамляют сетку ладов сверху и снизу (эталон Push 2).
# Верхний ряд — восходящие квинты от C, нижний — нисходящие от F.
SCALE_QUINT_TOP: tuple[int, ...] = (0, 7, 2, 9, 4, 11)  # C G D A E B
SCALE_QUINT_BOTTOM: tuple[int, ...] = (5, 10, 3, 8, 1, 6)  # F A# D# G# C# F#
_ROW_H = 14  # высота строки списка (шрифт sm)
_TRACK_ROW_H = 13  # строки TRACKS компактнее: внизу полоса имён под Lower Row

# DEMO переведён на Grid (Ф2): вкладки — кнопки Upper/Lower Row, энкодеры —
# в полосе KNOBS. Прежние DEMO_TABS_H / DEMO_COLS_Y0 / DEMO_BOTTOM_H не нужны.

# Цвета статусов портов (значения из PortSummary.status).
_PORT_STATUS_COLORS = {
    "connected": Colors.CONNECTED,
    "disconnected": Colors.DISCONNECTED,
    "ambiguous": Colors.BPM_MIDI,
    "error": Colors.DISCONNECTED,
}


def scale_root_rows(roots: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Разложить тоники по Upper/Lower Row: (верхний ряд, нижний ряд).

    Для 12 тоник — квинтовый круг (как на эталонном экране Scale Push 2): сверху
    C G D A E B, снизу F A# D# G# C# F#. Для другого числа — пополам, чтобы
    экран не падал на нестандартном DTO.
    """
    if len(roots) == 12:
        return (
            tuple(roots[i] for i in SCALE_QUINT_TOP),
            tuple(roots[i] for i in SCALE_QUINT_BOTTOM),
        )
    half = (len(roots) + 1) // 2
    return roots[:half], roots[half:]


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
        """Отрисовывать тело body на FrameBuffer (body очищает сам себя)."""

    def layout(self, view: ScreenView) -> ScreenLayout:
        """Собрать Grid-макет экрана.

        Экраны, переведённые на Grid, переопределяют метод; остальные пока
        рисуют тело через ``draw_body`` — для них макет не определён.
        """
        raise NotImplementedError(
            f"экран {self.name!r} ещё не собран через ScreenLayout"
        )

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

        # Нижняя полоса: имена дорожек — колонка i ровно под кнопкой Lower Row i+1
        # (полоса LOWER_BAND, Ф4); FOOT под ней остаётся пустым.
        grid = ColumnGrid()
        y = LOWER_BAND.y0 + 2
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


def preset_options(current: str) -> tuple[str, ...]:
    """Список пресетов для E6; для своей прогрессии добавляется пункт ``custom``."""
    names = tuple(p.name for p in PROGRESSIONS)
    return names if current else names + ("custom",)


def preset_index(current: str) -> int:
    """Позиция курсора в списке E6: текущий пресет или пункт ``custom``."""
    names = [p.name for p in PROGRESSIONS]
    return names.index(current) if current in names else len(names)


class TrackGenScreen(Screen):
    """GEN (Clip): энкодеры E1–E5 — SRC/SRC2/GATE/DEN/MUT, E6–E8 пустые.

    Grid-макет (Ф3): верхний и нижний ряды пусты — Clip и Lower Row слотов
    на дисплее не имеют. Строка PORT/CH/PROFILE/VOICING — в полосе FOOT.
    """

    name = "gen"
    view_attr = "track"

    def layout(self, view: ScreenView) -> ScreenLayout:
        """GEN: E1–E2 — источники (списки), E3–E5 — GATE/DEN/MUT (доли)."""
        detail = view.track
        if detail is None:
            return ScreenLayout()

        src2 = detail.sources[1] if len(detail.sources) > 1 else "—"
        # Доли 0..1 на экране показываются процентами («25 %»), как было до Grid.
        gate = detail.gate * 100 if detail.kind != "drum" else None
        den = detail.density * 100 if detail.density is not None else None

        encoders: tuple[SlotItem, ...] = (
            List("SRC (E1)", detail.sources or ("—",)),
            List("SRC2 (E2)", (src2,) if src2 != "—" else ("—",)),
            Range("GATE (E3)", gate, 0.0, 100.0, unit=" %"),
            Range("DEN (E4)", den, 0.0, 100.0, unit=" %"),
            Range("MUT (E5)", detail.mutate * 100, 0.0, 100.0, unit=" %"),
            List(
                "PRESET (E6)",
                preset_options(detail.preset),
                index=preset_index(detail.preset),
                rows=3,
            ),
            List(
                "VOICING (E7)",
                VOICING_NAMES,
                index=VOICING_NAMES.index(detail.voicing)
                if detail.voicing in VOICING_NAMES
                else 0,
                rows=3,
            )
            if detail.voicing
            else Empty(),
            Range(
                "OCT (E8)",
                float(detail.octave) if detail.octave is not None else None,
                0.0,
                float(MAX_OCTAVE),
                unit="",
            ),
        ) + (Empty(),) * (SLOT_COUNT - 8)

        foot: tuple[SlotItem, ...] = (
            Text("PORT", f"> {detail.port}" if detail.port else "—"),
            Text("CH", str(detail.channel)),
            Text("PROFILE", detail.profile),
            Text("VOICING", detail.voicing or "—")
            if detail.kind != "drum"
            else Empty(),
            Text("DEG", format_degrees(detail.degrees) if detail.degrees else "\u2014"),
        ) + (Empty(),) * 3

        return ScreenLayout(
            encoders=encoders,
            foot=foot,
            stripe=detail.color or None,
        )

    def draw_body(self, fb: FrameBuffer, body: TrackDetailView) -> None:
        """GEN body через Grid-макет."""
        view = ScreenView(screen=self.name, title="", flash=None, track=body)
        render_layout(fb, self.layout(view))


# ── TRACK MACRO (макро-контроль синтов) ───────────────────────────────────────


class TrackMacroScreen(Screen):
    """MACRO (Device): энкодеры E1–E3 — TONE/SPACE/DEPTH (performance-CC), E4–E8 пустые."""

    name = "macro"
    view_attr = "track_macro"

    def layout(self, view: ScreenView) -> ScreenLayout:
        """MACRO: три оси в долях 0..127; -1 — значение не применимо."""
        macro = view.track_macro
        if macro is None:
            return ScreenLayout()

        labels = ("TONE (E1)", "SPACE (E2)", "DEPTH (E3)")
        encoders: tuple[SlotItem, ...] = tuple(
            Range(
                label,
                None if value < 0 else float(max(0, min(127, value))),
                0.0,
                127.0,
            )
            for label, value in zip(labels, macro.macros, strict=True)
        ) + (Empty(),) * (SLOT_COUNT - 3)

        if macro.port:
            foot: tuple[SlotItem, ...] = (
                Text("PORT", f"> {macro.port}"),
                Text("CH", str(macro.channel)),
            ) + (Empty(),) * 6
        else:
            foot = (
                Text("PORT", "NO PORT — CC NOT SENT", color=Colors.DISCONNECTED),
            ) + (Empty(),) * 7

        return ScreenLayout(encoders=encoders, foot=foot, stripe=macro.color or None)

    def draw_body(self, fb: FrameBuffer, body: TrackMacroView) -> None:
        """MACRO body через Grid-макет."""
        view = ScreenView(screen=self.name, title="", flash=None, track_macro=body)
        render_layout(fb, self.layout(view))


# ── WIZARD (создание дорожки) ─────────────────────────────────────────────────


class WizardScreen(Screen):
    """Wizard Add Track: шаг (kind/profile/route), варианты в E1, шаг и страницы — в FOOT."""

    name = "wizard"
    view_attr = "wizard"

    def layout(self, view: ScreenView) -> ScreenLayout:
        """WIZARD: E1 — ``List`` вариантов, FOOT — имя шага и «N/M»."""
        wizard = view.wizard
        if wizard is None:
            return ScreenLayout()

        step_label = {
            "kind": "KIND",
            "profile": "PROFILE",
            "route": "ROUTE (PORT)",
        }.get(wizard.step, wizard.step.upper())

        encoders: tuple[SlotItem, ...] = (
            List("OPTIONS (E1)", wizard.options, index=wizard.selected, rows=5),
        ) + (Empty(),) * (SLOT_COUNT - 1)
        foot: tuple[SlotItem, ...] = (
            Text("STEP", step_label),
            Text("PAGE", f"{wizard.page + 1}/{wizard.page_count}")
            if wizard.page_count > 1
            else Empty(),
        ) + (Empty(),) * 6
        return ScreenLayout(encoders=encoders, foot=foot)

    def draw_body(self, fb: FrameBuffer, body: WizardView) -> None:
        """WIZARD body через Grid-макет."""
        view = ScreenView(screen=self.name, title="", flash=None, wizard=body)
        render_layout(fb, self.layout(view))


# ── SCALE (корень/лад) ──────────────────────────────────────────────────────


class ScaleScreen(Screen):
    """SCALE — выбор тональности и лада по образцу экрана Scale Push 2 (Ф5).

    Корни обрамляют сетку ладов: Upper Row 1–6 — восходящие квинты (C G D A E B),
    Lower Row 1–6 — нисходящие от F (F A# D# G# C# F#). Лады — по одному на слот
    полосы KNOBS (E1–E8), активный заливкой строки. FOOT — текущая пара.
    """

    name = "scale"
    view_attr = "scale"

    def layout(self, view: ScreenView) -> ScreenLayout:
        """SCALE: 6 корней сверху и 6 снизу кнопками, 8 ладов в KNOBS, пара в FOOT."""
        scale = view.scale
        if scale is None:
            return ScreenLayout()

        top, bottom = scale_root_rows(scale.roots)
        current = _active_root(scale)
        upper: tuple[SlotItem, ...] = tuple(
            Button(root, active=root == current) for root in top
        ) + (Empty(),) * (SLOT_COUNT - len(top))
        lower: tuple[SlotItem, ...] = tuple(
            Button(root, active=root == current) for root in bottom
        ) + (Empty(),) * (SLOT_COUNT - len(bottom))

        # Лады: по одному на слот; активный — белой заливкой строки (как в эталоне).
        scales = scale.scales
        encoders: tuple[SlotItem, ...] = tuple(
            Text("", name, font="md", active=i == scale.scale_index)
            for i, name in enumerate(scales)
        ) + (Empty(),) * (SLOT_COUNT - len(scales))

        foot: tuple[SlotItem, ...] = (
            Text("KEY", _active_root(scale), color=Colors.WHITE),
            Text("SCALE", _active_scale(scale), color=Colors.WHITE),
        ) + (Empty(),) * (SLOT_COUNT - 2)

        return ScreenLayout(
            upper=upper[:SLOT_COUNT],
            encoders=encoders[:SLOT_COUNT],
            lower=lower[:SLOT_COUNT],
            foot=foot[:SLOT_COUNT],
        )

    def draw_body(self, fb: FrameBuffer, body: ScaleView) -> None:
        """SCALE body через Grid-макет."""
        view = ScreenView(screen=self.name, title="", flash=None, scale=body)
        render_layout(fb, self.layout(view))


def _active_root(scale: ScaleView) -> str:
    """Текущая тоника (устойчиво к индексу вне диапазона)."""
    if not scale.roots:
        return "—"
    return scale.roots[scale.root_index % len(scale.roots)]


def _active_scale(scale: ScaleView) -> str:
    """Текущий лад (устойчиво к индексу вне диапазона)."""
    if not scale.scales:
        return "—"
    return scale.scales[scale.scale_index % len(scale.scales)]


# ── SETUP (суб-вкладки настроек) ──────────────────────────────────────────────


class SetupScreen(Screen):
    """SETUP: E1 — список источников клока (вкладка CLOCK), FOOT — сегментные вкладки.

    Информационные строки вкладки живут справа от слота 0 в полосе KNOBS:
    слот 0 занят списком источников, остальное место — под текст.
    """

    name = "setup"
    view_attr = "sync"

    def layout(self, view: ScreenView) -> ScreenLayout:
        """SETUP: E1 — List источников клока (только CLOCK), низ — Tabs."""
        sync = view.sync
        if sync is None:
            return ScreenLayout()

        if sync.tab == "clock":
            sources = sync.sources or ("—",)
            index = sources.index(sync.source) if sync.source in sources else 0
            encoders: tuple[SlotItem, ...] = (
                List("SOURCE (E1)", sources, index=index),
            )
        else:
            encoders = ()
        encoders += (Empty(),) * (SLOT_COUNT - len(encoders))

        return ScreenLayout(
            encoders=encoders,
            tabs=Tabs(sync.tabs, active=sync.tab),
        )

    def draw_body(self, fb: FrameBuffer, body: SyncView) -> None:
        """SETUP body: Grid-макет + строки активной вкладки справа от слота 0."""
        view = ScreenView(screen=self.name, title="", flash=None, sync=body)
        render_layout(fb, self.layout(view))

        # Текст вкладки — в полосе KNOBS, правее слота 0 (списка источников).
        x = SLOT_W + 8
        w = FRAME_W - x - 8
        y = KNOBS_Y0 + 6
        for label, value, color in self._info_lines(body):
            Text(label, value, color=color).render(fb, Rect(x, y, w, 16))
            y += 18

    @staticmethod
    def _info_lines(view: SyncView) -> tuple[tuple[str, str, int], ...]:
        """Строки «метка / значение» для активной суб-вкладки."""
        if view.tab == "midi":
            return (
                ("MIDI CLOCK DEVICE", view.midi_device, Colors.WHITE),
                ("SET VIA", "config (sync.midi_clock_device)", Colors.GRAY),
            )
        if view.tab == "link":
            state = "active" if view.link_active else "off"
            return (
                ("ABLETON LINK", f"{state}  peers: {view.link_peers}", Colors.WHITE),
                ("ENABLE", "package abletonlink (sync.clock_source)", Colors.GRAY),
            )
        lines = [
            ("DEVICE", view.midi_device, Colors.GRAY),
            ("TEMPO", f"{view.bpm:.1f} (local)", Colors.WHITE),
        ]
        status = ["running" if view.running else "stopped"]
        if view.link_active:
            status.append(f"LINK peers {view.link_peers}")
        lines.append(("STATUS", "  ".join(status), Colors.GRAY))
        if view.error:
            lines.append(("ERROR", view.error, FLASH_ERROR))
        if view.pending:
            lines.append(("PENDING", f"-> {view.pending}...", FLASH))
        return tuple(lines)


# ── DEMO (образец экрана фреймворка) ──────────────────────────────────────────


class DemoScreen(Screen):
    """DEMO (Note): эталонный экран Grid-макета (Ф2).

    Верхние вкладки — Button в слотах 0–3 полосы UPPER, нижние — в слотах 0–4
    полосы LOWER, E1/E2 — ``List`` по вкладкам, E3–E8 — ``Range`` 0..127 с барами.
    Всё, что выше полосы KNOBS, рисует только :func:`render_layout`.
    """

    name = "demo"
    view_attr = "demo"

    def layout(self, view: ScreenView) -> ScreenLayout:
        """DEMO: верхние вкладки — Button в слотах 0–3, нижние — в 0–4.

        E1/E2 — ``List`` по вкладкам, E3–E8 — ``Range`` 0..127 со значением.
        Эталонный экран для :func:`render_layout` (Ф2 плана).
        """
        demo = view.demo
        if demo is None or not demo.top_tabs:
            return ScreenLayout()

        top = demo.top_tabs
        top_active = demo.top_index % len(top)
        upper = tuple(
            Button(tab, active=i == top_active)
            for i, tab in enumerate(top[:SLOT_COUNT])
        ) + (Empty(),) * (SLOT_COUNT - len(top[:SLOT_COUNT]))

        bottom = demo.bottom_tabs
        lower: tuple[SlotItem, ...] = ()
        if bottom:
            bottom_active = demo.bottom_index % len(bottom)
            lower = tuple(
                Button(tab.upper(), active=i == bottom_active)
                for i, tab in enumerate(bottom[:SLOT_COUNT])
            ) + (Empty(),) * (SLOT_COUNT - len(bottom[:SLOT_COUNT]))

        encoders: tuple[SlotItem, ...] = (
            List("TOP (E1)", top, index=top_active),
            List(
                "BOTTOM (E2)",
                bottom,
                index=demo.bottom_index % len(bottom) if bottom else 0,
            ),
        ) + tuple(
            Range(f"E{i + 3}", max(0, min(127, value)), 0.0, 127.0)
            for i, value in enumerate(demo.values[:6])
        )
        return ScreenLayout(
            upper=upper,
            encoders=encoders + (Empty(),) * (SLOT_COUNT - len(encoders)),
            lower=lower,
        )

    def draw_body(self, fb: FrameBuffer, body: DemoView) -> None:
        """DEMO body через Grid-макет (совместимость со старым путём)."""
        view = ScreenView(screen=self.name, title="", flash=None, demo=body)
        render_layout(fb, self.layout(view))

    @staticmethod
    def _bottom_name(view: DemoView) -> str:
        """Активная нижняя вкладка; пустой ряд не должен ронять рендер."""
        if not view.bottom_tabs:
            return ""
        return view.bottom_tabs[view.bottom_index % len(view.bottom_tabs)]


# ── PORTS ─────────────────────────────────────────────────────────────────────


class PortsScreen(Screen):
    """PORTS: E1 — выбор дорожки, E2 — выбор порта, список портов — в FOOT."""

    name = "ports"
    view_attr = "ports"

    def layout(self, view: ScreenView) -> ScreenLayout:
        """PORTS: E1/E2 — List дорожек и портов; ROUTE — в FOOT."""
        ports = view.ports
        if ports is None:
            return ScreenLayout()

        encoders: tuple[SlotItem, ...] = (
            List("TRACK (E1)", ports.tracks or ("—",), index=ports.track_index),
            List(
                "PORT (E2)",
                ("—",) + tuple(row.label for row in ports.rows),
                index=ports.port_index,
            ),
        ) + (Empty(),) * (SLOT_COUNT - 2)

        # Статус портов строками в FOOT (по два слота на порт).
        foot: list[SlotItem] = []
        for row in ports.rows[:4]:
            foot.append(
                Text(
                    row.label,
                    row.status,
                    color=_PORT_STATUS_COLORS.get(row.status, Colors.DIM),
                )
            )
        route = f"{ports.route_track} -> " + (
            f"> {ports.route_port}" if ports.route_port else "-"
        )
        foot.append(Text("ROUTE", route, color=Colors.WHITE))
        padded = tuple(foot) + (Empty(),) * (SLOT_COUNT - len(foot))
        return ScreenLayout(encoders=encoders, foot=padded[:SLOT_COUNT])

    def draw_body(self, fb: FrameBuffer, body: PortsView) -> None:
        """PORTS body через Grid-макет."""
        view = ScreenView(screen=self.name, title="", flash=None, ports=body)
        render_layout(fb, self.layout(view))


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
    """y 0–13: заголовок слева (шрифт sm), flash-строка справа."""
    fb.fill_rect(0, 0, FRAME_W, 14, Colors.BG)
    Label(title, "sm", Colors.WHITE).render(fb, Rect(4, 0, 400, 13))
    if flash:
        color = FLASH_ERROR if flash.startswith("error:") else FLASH
        Label(flash, "sm", color, "r").render(fb, Rect(FRAME_W - 80, 1, 76, 12))


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
        """y 0–13: заголовок с flash-строкой."""
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
