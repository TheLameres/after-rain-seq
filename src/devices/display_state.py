"""Typed display state dataclasses for controller device render_display().

Два слоя состояния:

- :class:`DisplayState` — interim status (устройство/клок), остаётся для
  LCXL3-пути и совместимости.
- View-модели экранов (D2) — frozen DTO, которые ``ScreenController``
  собирает в app-слое и спускает вниз. Слои: devices/ не импортирует
  session/sync/app — только эти чистые данные.

Все view-модели frozen и содержат только строки/числа/кортежи.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# View-модели экранов (D2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackRowView:
    """Строка дорожки на экране TRACKS."""

    name: str
    kind: str  # "melodic" | "drum"
    profile: str
    channel: int
    port: str | None  # None — не привязана (молчит)
    frozen: bool
    mutation_count: int
    selected: bool
    color: int = 0  # BGR565 — цветной маркер дорожки (track_colors)


@dataclass(frozen=True)
class TrackDetailView:
    """Экран GEN (CLIP): генерация — параметры выбранной дорожки.

    Семантика «не применимо»: ``density=None`` (chord_source/cc_only),
    ``voicing=""`` (drum/cc_only). CC-макросы — на экране MACRO (DEVICE),
    см. :class:`TrackMacroView`.
    """

    name: str
    kind: str
    profile: str
    channel: int
    port: str | None
    sources: tuple[str, ...]  # ("Pad 1",) | () — «—»
    gate: float  # 0..1; для drum — 0.0 («—»)
    voicing: str  # "1-4-7"; drum/cc_only — ""
    density: float | None  # 0..1; None → «—»
    mutate: float  # 0..1 (0 = frozen)
    color: int = 0  # BGR565 — полоса слева в body


@dataclass(frozen=True)
class TrackMacroView:
    """Экран MACRO (DEVICE): макро-контроль синтезаторов выбранной дорожки.

    Семантика «не применимо»: ``macros=(-1,-1,-1)`` (порт None → «—»,
    значения копятся в UiState, но на синт не уходят).
    """

    name: str
    kind: str
    channel: int
    port: str | None
    macros: tuple[int, int, int]  # TONE/SPACE/DEPTH 0..127; -1 = «—»
    color: int = 0  # BGR565 — полоса слева в body


@dataclass(frozen=True)
class SyncView:
    """Экран SETUP: суб-вкладки настроек (clock/midi/link).

    ``tab`` — активная суб-вкладка; ``tabs`` — все подписи (для таб-бара
    внизу body, образец — экран Setup Push standalone). Поля клока общие,
    рендер по вкладке.
    """

    source: str  # internal|midi|link
    pending: str | None
    error: str | None
    bpm: float  # локальный (при midi/link — «внешний»)
    running: bool
    link_active: bool
    link_peers: int
    midi_device: str  # устройство MIDI-клока или «—»
    tab: str = "clock"
    tabs: tuple[str, ...] = ("clock", "midi", "link")
    sources: tuple[str, ...] = ("internal", "midi", "link")  # варианты источника клока


@dataclass(frozen=True)
class PortRowView:
    """Строка порта на экране PORTS."""

    label: str
    status: str  # connected|disconnected|ambiguous|error
    detail: str


@dataclass(frozen=True)
class PortsView:
    """Экран PORTS: список портов + назначение дорожке."""

    rows: tuple[PortRowView, ...]
    route_track: str  # дорожка для назначения (ENC1)
    route_port: str | None  # её текущий порт (None = «—»)
    selected: int  # курсор
    tracks: tuple[str, ...] = ()  # имена дорожек для E1
    track_index: int = 0  # позиция route_track в tracks
    port_index: int = 0  # позиция route_port в («—», *порты)


@dataclass(frozen=True)
class ScaleView:
    """Экран SCALE: корень (столбцы-заголовки) и лады (сетка ячеек).

    Образец — экран выбора шкалы Push 2: сверху ряд корней, под ним
    лады в несколько колонок; выбранная пара (корень, лад) подсвечена.
    Свинга на экране нет (D2-6): значение — по касанию Swing Encoder.
    """

    roots: tuple[str, ...]  # 12 тоник (C C# D …)
    scales: tuple[str, ...]  # лады (8 гармонических)
    root_index: int  # активный корень (0..11)
    scale_index: int  # активный лад (0..len-1)


@dataclass(frozen=True)
class WizardView:
    """Экран WIZARD: создание дорожки (Add Track).

    Атрибуты:
        step: ``"kind"`` (Melodic/Drum), ``"profile"`` (профили melodic)
            или ``"route"`` (порт: «—» без порта + порты снапшота).
        options: Видимое окно вариантов (страница по PAGE_SIZE).
        selected: Курсор в рамках окна (0..len(options)-1).
        page: Номер страницы (0-based).
        page_count: Число страниц.
        kind: Выбранный вид на шаге kind (``"melodic"``/``"drum"``) или None.
    """

    step: str
    options: tuple[str, ...]
    selected: int
    page: int
    page_count: int
    kind: str | None = None


@dataclass(frozen=True)
class DemoView:
    """Демо-экран фреймворка (D2-8): вкладки сверху и снизу + 8 энкодеров.

    Образец для новых экранов: верхние вкладки (TabStrip), нижние
    (SegmentTabs), середина — восемь колонок под энкодерами E1–E8
    (E1/E2 — выбор вкладки, E3–E8 — значения 0..127).
    """

    top_tabs: tuple[str, ...]  # верхние вкладки
    bottom_tabs: tuple[str, ...]  # нижние вкладки
    top_index: int  # активная верхняя вкладка
    bottom_index: int  # активная нижняя вкладка
    values: tuple[int, ...]  # 6 × 0..127 — значения E3–E8


@dataclass(frozen=True)
class ScreenView:
    """Единый контейнер view, который получает PushDisplay.

    Атрибуты:
        screen: ``ScreenId.value`` (str — enum в devices не тянем).
        title: «TRACKS 1-8/2», «TRACK: Stab 1», … (под таб-баром).
        flash: transient сообщение (ошибка/BPM по касанию) или None.
    """

    screen: str
    title: str
    flash: str | None
    tracks: tuple[TrackRowView, ...] | None = None
    track: TrackDetailView | None = None  # GEN (CLIP)
    track_macro: TrackMacroView | None = None  # MACRO (DEVICE)
    sync: SyncView | None = None
    ports: PortsView | None = None
    scale: ScaleView | None = None
    wizard: WizardView | None = None
    demo: DemoView | None = None  # DEMO (Note)


@dataclass(frozen=True)
class DisplayState:
    """Top-level display state passed to ControllerDevice.render_display()."""

    device_connected: bool
    sync_bpm: float | None = None
    sync_link_peers: int = 0
    sync_link_active: bool = False
    sync_clock_source: str = "off"  # "internal" | "midi" | "link" | "off"
    screen_view: ScreenView | None = None  # D2: экраны Push 2 (None — legacy)
