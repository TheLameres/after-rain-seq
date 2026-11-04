"""ScreenController — навигация экранов и команды (план D2 §3.3, §3.4).

Живёт в main loop: ``handle()`` дёргается из drain ui_queue, ``build_view()``
— из render-прохода. Пишет команды через ``EngineControl`` (как REPL),
читает данные из ``StatusSnapshot``; session/sync напрямую не импортирует
(единственное исключение — статический реестр ``PROFILES`` для wizard'а
создания дорожки).

Кнопочная карта (переразметка 02.11.2026, дополнения 2–3):
- ``Session`` — экран TRACKS; ``Clip`` — GEN выбранной дорожки;
  ``Device`` — MACRO; ``Scale`` — SCALE (корень/лад); ``Setup`` — SETUP
  (настройки с суб-вкладками);
- ``Upper Row 5`` — PORTS (верхний ряд освобождён: 1–4, 6–8 — резерв D3+);
  таб-бар на дисплее рисуется под кнопками вкладок (GEN под Clip,
  MACRO под Device, PORTS под Upper Row 5); SCALE/SETUP во вкладки
  не входят — это глобальные экраны со своими кнопками;
- ``Lower Row 1–8`` — выбор дорожки на странице + вход в GEN;
  вооружённый ``Delete`` + Lower Row — удаление дорожки по позиции;
- LED: ``button_led_states()`` — подсветка всех рабочих кнопок (п. 4).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from src.app.ui.macro_axes import MacroAxes, MacroAxis
from src.app.ui.screen_id import ScreenId
from src.app.ui.ui_event import UiEvent
from src.app.ui.ui_state import (
    DEMO_VALUE_COUNT,
    DEMO_VALUE_DEFAULT,
    PAGE_SIZE,
    UiState,
)
from src.devices.display_state import (
    DemoView,
    PortRowView,
    PortsView,
    ScaleView,
    ScreenView,
    SyncView,
    TrackDetailView,
    TrackMacroView,
    TrackRowView,
    WizardView,
)
from src.devices.push2.layout import Button
from src.devices.push2.screens import DEFAULT_SCREENS, scale_root_rows
from src.devices.push2.track_colors import track_color
from src.devices.push2.widgets import SLOT_COUNT
from src.repl.engine_control import EngineControl
from src.repl.status import StatusSnapshot, TrackSummary
from src.session import PROFILES

if TYPE_CHECKING:
    from src.config import UiConfig

log = logging.getLogger(__name__)

# Вкладки переключаются выделенными кнопками (Clip/Device) и Upper Row 5
# (PORTS) — см. ниже. Upper Row освобождён под будущее (D3+).
PORTS_BUTTON = "Mix"  # CC 112 — экран PORTS (план Ф0.3)
DEMO_BUTTON = "Note"  # CC 50 — демо-экран фреймворка (вкладки сверху/снизу, 8 энкодеров)

# Выделенные кнопки вне табов (переразметка 02.11.2026).
SESSION_BUTTON = "Session"  # CC 51 — экран TRACKS
CLIP_BUTTON = "Clip"  # CC 113 — GEN выбранной дорожки
DEVICE_BUTTON = "Device"  # CC 110 — MACRO выбранной дорожки
SCALE_BUTTON = "Scale"  # CC 58 — экран SCALE (корень/лад)
SETUP_BUTTON = "Setup"  # CC 30 — экран SETUP (суб-вкладки настроек)
LOWER_ROW_PREFIX = "Lower Row "  # CC 20–27 — дорожка страницы / удаление
DELETE_BUTTON = "Delete"  # CC 118 — вооружается; + Lower Row удаляет трек

# Суб-вкладки SETUP (заложена возможность расширения настроек).
SETUP_TABS: tuple[str, ...] = ("clock", "midi", "link")

# DEMO (Note) — демо-экран фреймворка: два ряда вкладок и шесть значений.
# Верхние вкладки крутит E1, нижние — E2, E3–E8 — значения 0..127.
DEMO_TOP_TABS: tuple[str, ...] = ("alpha", "beta", "gamma", "delta")
DEMO_BOTTOM_TABS: tuple[str, ...] = ("osc", "filter", "env", "fx", "mix")

# LED-цвета кнопок (палитра Push 2: 0 off, 122 white, 125 blue,
# 126 green, 127 red; для белых кнопок значение = яркость).
LED_OFF = 0
LED_DIM = 16
LED_GRAY = 48
LED_WHITE = 122
LED_BLUE = 125
LED_GREEN = 126
LED_RED = 127

# Энкодеры «Track1..8 Encoder» позиционно → E1..E8.
TRACK_ENCODERS: tuple[str, ...] = tuple(
    f"Track{i} Encoder" for i in range(1, PAGE_SIZE + 1)
)

# Wizard создания дорожки (кнопка Add Track, CC 53).
# Шаги: kind (Melodic/Drum) → profile (только melodic) → route (порт).
WIZARD_KINDS: tuple[str, ...] = ("melodic", "drum")
MELODIC_PROFILES: tuple[str, ...] = tuple(PROFILES.keys())
WIZARD_ROUTE_NONE = "—"  # первый вариант шага route: создать без порта

# Имя созданной дорожки из фидбека фасада ('created track "NAME" (...)').
# Формат производит только AppEngineControl — парсинг надёжнее diff'а снапшота.
_CREATED_TRACK_RE = re.compile(r'^created track "([^"]+)"')

# 12 тоник для GLOBAL E1.
ROOTS: tuple[str, ...] = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)
# Лады — в стабильном порядке (HARMONIC_SCALES — frozenset).
SCALES: tuple[str, ...] = (
    "major",
    "dorian",
    "phrygian",
    "lydian",
    "mixolydian",
    "aeolian",
    "locrian",
    "minor",
)
CLOCK_SOURCES: tuple[str, ...] = ("internal", "midi", "link")

# Шаги поворота энкодеров.
GATE_STEP = 0.05  # E3 TRACK
BPM_STEP = 0.5  # Tempo Encoder
SWING_STEP = 0.05  # Swing Encoder

# Касания энкодеров (note-on/nn из спеки): приходят как button-события
# с именами энкодеров — контроллер показывает значение во flash-строке.
ENCODER_TOUCH_TTL = 2.0  # секунды показа BPM/свинга по касанию

# CC-оси на экране MACRO: E1..E3 → TONE/SPACE/DEPTH.
_MACRO_AXIS_BY_ENCODER: dict[int, MacroAxis] = {
    0: MacroAxis.TONE,
    1: MacroAxis.SPACE,
    2: MacroAxis.DEPTH,
}

# Экраны, где Left/Right двигают курсор дорожки.
_TRACK_SCREENS = frozenset({ScreenId.TRACKS, ScreenId.TRACK_GEN, ScreenId.TRACK_MACRO})

# Sender performance-CC: (port_label, param_name, channel, value).
CcSender = Callable[[str, str, int, int], None]


class ScreenController:
    """Навигация, кнопочная карта и сборка ScreenView.

    Parameters
    ----------
    engine:
        Фасад команд (как у REPL). В тестах — мок.
    macro_axes:
        Провалидированный состав CC-осей.
    cc_sender:
        Отправка performance-CC (App резолвит порт через PortRegistry +
        CCMap + троттлинг 30 Hz). None — CC-оси только сохраняют значение.
    ui_config:
        Настройки UI (TTL flash).
    """

    def __init__(
        self,
        engine: EngineControl,
        macro_axes: MacroAxes | None = None,
        cc_sender: CcSender | None = None,
        ui_config: UiConfig | None = None,
    ) -> None:
        self._engine = engine
        self._macro_axes = macro_axes if macro_axes is not None else MacroAxes()
        self._cc_sender = cc_sender
        self._flash_seconds = ui_config.flash_seconds if ui_config else 3.0
        self.state = UiState()

    # ------------------------------------------------------------------
    # Вход: события из UiEventQueue (main loop)
    # ------------------------------------------------------------------

    def handle(self, event: UiEvent, now: float) -> None:
        """Обработать одно UI-событие (вызывается из drain в main loop)."""
        snap = self._engine.get_status()
        if event.kind == "button":
            self._handle_button(event.name, bool(event.value), now, snap)
        elif event.kind == "encoder":
            self._handle_encoder(event.name, event.value, now, snap)
        else:
            log.debug("UiEvent неизвестного kind: %s", event.kind)

    # ------------------------------------------------------------------
    # Выход: view для render-прохода (main loop)
    # ------------------------------------------------------------------

    def build_view(self, snap: StatusSnapshot, now: float) -> ScreenView:
        """Собрать ScreenView для текущего экрана."""
        self._clamp_cursor(snap)
        screen = self.state.screen
        flash = self.state.visible_flash(now)
        title = self._title(snap)
        view = ScreenView(
            screen=screen.value,
            title=title,
            flash=flash,
        )
        if screen is ScreenId.TRACKS:
            return replace(view, tracks=self._track_rows(snap))
        if screen is ScreenId.TRACK_GEN:
            detail = self._track_detail(snap)
            return replace(view, track=detail)
        if screen is ScreenId.TRACK_MACRO:
            macro = self._track_macro(snap)
            return replace(view, track_macro=macro)
        if screen is ScreenId.SCALE:
            root_index = ROOTS.index(snap.root) if snap.root in ROOTS else 0
            scale_index = SCALES.index(snap.scale) if snap.scale in SCALES else 0
            scale_view = ScaleView(
                roots=ROOTS,
                scales=SCALES,
                root_index=root_index,
                scale_index=scale_index,
            )
            return replace(view, scale=scale_view)
        if screen is ScreenId.SETUP:
            tab = SETUP_TABS[self.state.setup_tab % len(SETUP_TABS)]
            sync_view = SyncView(
                source=snap.clock_source,
                pending=snap.clock_pending,
                error=snap.clock_error,
                bpm=snap.bpm,
                running=snap.running,
                link_active=snap.link_active,
                link_peers=snap.link_peers,
                midi_device=snap.midi_clock_device or "—",
                tab=tab,
                tabs=SETUP_TABS,
                sources=CLOCK_SOURCES,
            )
            return replace(view, sync=sync_view)
        if screen is ScreenId.WIZARD:
            options_all = self._wizard_options(snap)
            page, sel = divmod(self.state.wizard_index, PAGE_SIZE)
            page_count = max(1, (len(options_all) + PAGE_SIZE - 1) // PAGE_SIZE)
            window = options_all[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            kind = None
            if self.state.wizard_kind == "kind":
                kind = WIZARD_KINDS[self.state.wizard_index]
            wizard_view = WizardView(
                step=self.state.wizard_kind,
                options=tuple(window),
                selected=sel,
                page=page,
                page_count=page_count,
                kind=kind,
            )
            return replace(view, wizard=wizard_view)
        if screen is ScreenId.DEMO:
            return replace(view, demo=self._demo_view())
        # PORTS
        route_track = self._route_track(snap)
        track_names = tuple(t.name for t in snap.tracks)
        port_options = (None,) + tuple(p.name for p in snap.ports)
        ports_view = PortsView(
            rows=tuple(
                PortRowView(label=p.name, status=p.status, detail=p.detail)
                for p in snap.ports
            ),
            route_track=route_track.name if route_track else "—",
            route_port=route_track.port if route_track else None,
            selected=self.state.selected,
            tracks=track_names,
            track_index=(
                track_names.index(route_track.name)
                if route_track and route_track.name in track_names
                else 0
            ),
            port_index=(
                port_options.index(route_track.port)
                if route_track and route_track.port in port_options
                else 0
            ),
        )
        return replace(view, ports=ports_view)

    # ------------------------------------------------------------------
    # Кнопки (план D2 §3.3)
    # ------------------------------------------------------------------

    def _handle_button(
        self, name: str, pressed: bool, now: float, snap: StatusSnapshot
    ) -> None:
        if name == "Shift":
            self.state.shift = pressed
            return
        if not pressed:
            return  # Действия — по нажатию (press), release игнорим

        # Касания энкодеров (спека: note-on touch) — статус-бара нет (D2-5),
        # значение показываем во flash-строке на пару секунд.
        if name == "Tempo Encoder":
            self.state.flash(
                f"BPM {snap.bpm:.1f} {snap.clock_source.upper()}",
                now,
                ENCODER_TOUCH_TTL,
            )
            return
        if name == "Swing Encoder":
            self.state.flash(f"SWING {snap.swing * 100:.0f} %", now, ENCODER_TOUCH_TTL)
            return

        screen = self.state.screen

        # SCALE: касание энкодера E1–E8 выбирает лад этого слота напрямую.
        if screen is ScreenId.SCALE and name in TRACK_ENCODERS:
            idx = TRACK_ENCODERS.index(name)
            if 0 <= idx < len(SCALES) and SCALES[idx] != snap.scale:
                self._command(self._engine.set_scale(SCALES[idx]), now)
            return

        if name == PORTS_BUTTON:
            self._switch_screen(ScreenId.PORTS)
            return

        # Выделенные кнопки вне табов (переразметка 02.11.2026).
        if name == SESSION_BUTTON:
            self.state.screen = ScreenId.TRACKS
            return
        if name == CLIP_BUTTON:
            self.state.screen = ScreenId.TRACK_GEN
            return
        if name == DEVICE_BUTTON:
            self.state.screen = ScreenId.TRACK_MACRO
            return
        if name == SCALE_BUTTON:
            self.state.screen = ScreenId.SCALE
            return
        if name == SETUP_BUTTON:
            self.state.screen = ScreenId.SETUP
            return
        if name == DEMO_BUTTON:
            self.state.screen = ScreenId.DEMO
            return
        # SCALE: Upper/Lower Row 1–6 выбирают тонику (эталон Scale Push 2).
        if screen is ScreenId.SCALE and self._scale_root_button(name, now, snap):
            return
        if name.startswith(LOWER_ROW_PREFIX):
            self._lower_row_button(name, now, snap)
            return

        # Add Track (CC 53): wizard создания дорожки (kind → profile → route).
        if name == "Add Track":
            if self.state.screen is ScreenId.WIZARD:
                self._wizard_button(name, now, snap)
            else:
                self.state.screen = ScreenId.WIZARD
                self.state.wizard_kind = "kind"
                self.state.wizard_index = 0
                self.state.wizard_profile = None
            return
        if self.state.screen is ScreenId.WIZARD:
            # Модальный экран: стрелки/Select/Delete работают внутри wizard'а.
            self._wizard_button(name, now, snap)
            return

        if screen is ScreenId.DEMO and name in ("Left", "Right", "Up", "Down"):
            self._demo_nav(name)
            return
        if name in ("Left", "Right", "Up", "Down") and screen is ScreenId.SCALE:
            self._scale_nav(name, now, snap)
        elif name in ("Up", "Down") and screen is ScreenId.SETUP:
            step = -1 if name == "Up" else 1
            self.state.setup_tab = (self.state.setup_tab + step) % len(SETUP_TABS)
        elif name == "Left":
            self._nav_left(snap)
        elif name == "Right":
            self._nav_right(snap)
        elif name == "Up":
            self._move_cursor(-1, snap)
        elif name == "Down":
            self._move_cursor(1, snap)
        elif name == "Play":
            self._command(
                (
                    self._engine.start_transport()
                    if not snap.running
                    else self._engine.stop_transport()
                ),
                now,
            )
        elif name == "Record":
            if screen in (ScreenId.TRACK_GEN, ScreenId.TRACK_MACRO):
                track = self._selected_track(snap)
                if track is not None:
                    self._command(self._engine.freeze(track.name), now)
            else:
                self._command(self._engine.freeze(None), now)
        elif name == DELETE_BUTTON:
            if self.state.shift:
                # Shift+Delete — удаление выбранной дорожки (как раньше).
                track = self._selected_track(snap)
                if track is not None:
                    feedback = self._engine.remove_track(track.name)
                    self.state.flash(feedback, now, self._flash_seconds)
            else:
                # Delete вооружается: следующий LOWER ROW удалит дорожку.
                self.state.delete_armed = not self.state.delete_armed
                if self.state.delete_armed:
                    self.state.flash(
                        "DELETE: press LOWER ROW 1-8", now, self._flash_seconds
                    )
        elif name == "Browse" and screen is ScreenId.PORTS:
            self._command(self._engine.rescan_ports(), now)
        # Прочие кнопки не назначены (Duplicate/Layout/Note — резерв).

    def _scale_root_button(
        self, name: str, now: float, snap: StatusSnapshot
    ) -> bool:
        """SCALE: Upper/Lower Row 1–6 выбирают тонику; прочие кнопки — не наши.

        Возвращает True, если кнопка обработана (тогда общий обработчик Lower Row
        её не увидит). Слоты 7–8 не назначены — тоже возвращаем True, чтобы
        нажатие не проваливалось в выбор дорожки.
        """
        for prefix in ("Upper Row ", LOWER_ROW_PREFIX):
            if not name.startswith(prefix):
                continue
            try:
                slot = int(name[len(prefix) :]) - 1
            except ValueError:
                return False
            if not 0 <= slot < SLOT_COUNT:
                return False
            top, bottom = scale_root_rows(ROOTS)
            row = top if prefix == "Upper Row " else bottom
            if slot >= len(row):
                return True  # кнопка ряда, но слот не назначен
            if row[slot] != snap.root:
                self._command(self._engine.set_root(row[slot]), now)
            return True
        return False

    def _lower_row_button(self, name: str, now: float, snap: StatusSnapshot) -> None:
        """Lower Row 1–8: удаление при вооружённом Delete, иначе выбор+GEN."""
        try:
            slot = int(name[len(LOWER_ROW_PREFIX) :]) - 1
        except ValueError:
            return
        if not 0 <= slot < PAGE_SIZE:
            return
        # Абсолютный индекс дорожки: страница + позиция на Lower Row.
        self.state.selected = self.state.page * PAGE_SIZE + slot
        if self.state.delete_armed:
            self.state.delete_armed = False
            track = self._selected_track(snap)
            if track is not None:
                feedback = self._engine.remove_track(track.name)
                self.state.flash(feedback, now, self._flash_seconds)
            return
        if self._selected_track(snap) is not None:
            self.state.screen = ScreenId.TRACK_GEN

    def _switch_screen(self, screen: ScreenId) -> None:
        """Смена экрана: курсор/страница сохраняются per-screen осмысленно."""
        self.state.screen = screen

    def _nav_left(self, snap: StatusSnapshot) -> None:
        """Left: дорожные экраны — курсор по дорожке (Shift — страница из 8)."""
        screen = self.state.screen
        if screen in _TRACK_SCREENS:
            self._move_track(-PAGE_SIZE if self.state.shift else -1, snap)
        elif screen is ScreenId.PORTS:
            self._move_cursor(-1, snap)
        # SCALE/SETUP/WIZARD/DEMO: Left обрабатывается в своих ветках или не нужен.

    def _nav_right(self, snap: StatusSnapshot) -> None:
        """Right: дорожные экраны — курсор по дорожке (Shift — страница из 8)."""
        screen = self.state.screen
        if screen in _TRACK_SCREENS:
            self._move_track(PAGE_SIZE if self.state.shift else 1, snap)
        elif screen is ScreenId.PORTS:
            self._move_cursor(1, snap)

    def _move_track(self, delta: int, snap: StatusSnapshot) -> None:
        """Сдвиг абсолютного курсора дорожки (0..N-1), кламп по длине списка."""
        total = len(snap.tracks)
        if total == 0:
            return
        self.state.selected = max(0, min(total - 1, self.state.selected + delta))

    def _scale_nav(self, name: str, now: float, snap: StatusSnapshot) -> None:
        """SCALE: Left/Right — корень, Up/Down — лад (та же логика, что E1/E2)."""
        if name in ("Left", "Right"):
            inc = 1 if name == "Right" else -1
            pos = ROOTS.index(snap.root) if snap.root in ROOTS else 0
            root = ROOTS[(pos + inc) % len(ROOTS)]
            self._command(self._engine.set_root(root), now)
        else:
            inc = 1 if name == "Down" else -1
            pos = SCALES.index(snap.scale) if snap.scale in SCALES else 0
            scale = SCALES[(pos + inc) % len(SCALES)]
            self._command(self._engine.set_scale(scale), now)

    # ------------------------------------------------------------------
    # Wizard создания дорожки (кнопка Add Track, CC 53)
    # ------------------------------------------------------------------

    def _wizard_options(self, snap: StatusSnapshot) -> tuple[str, ...]:
        """Варианты текущего шага: вид, профили melodic или порты (route)."""
        if self.state.wizard_kind == "kind":
            return WIZARD_KINDS
        if self.state.wizard_kind == "profile":
            return MELODIC_PROFILES
        # route: «—» (без порта) + порты из снапшота.
        return (WIZARD_ROUTE_NONE,) + tuple(p.name for p in snap.ports)

    def _wizard_button(self, name: str, now: float, snap: StatusSnapshot) -> None:
        """Кнопки внутри wizard'а: ^v — выбор, R/Select/Add Track — ок, L/Delete — отмена."""
        if name in ("Up", "Down"):
            self._wizard_rotate(-1 if name == "Up" else 1, snap)
        elif name in ("Left", "Delete"):
            self._wizard_cancel()
        elif name in ("Right", "Select", "Add Track"):
            self._wizard_confirm(now, snap)

    def _wizard_cancel(self) -> None:
        """Отмена: выход на TRACKS, выбор профиля сбрасывается."""
        self.state.screen = ScreenId.TRACKS
        self.state.wizard_profile = None

    def _wizard_rotate(self, increment: int, snap: StatusSnapshot) -> None:
        """Курсор wizard'а по кругу в рамках текущего шага."""
        options = self._wizard_options(snap)
        step = 1 if increment > 0 else -1
        self.state.wizard_index = (self.state.wizard_index + step) % len(options)

    def _wizard_confirm(self, now: float, snap: StatusSnapshot) -> None:
        """Подтверждение шага: kind → profile/route; profile → route;
        route → создать дорожку и при необходимости сразу привязать порт."""
        if self.state.wizard_kind == "kind":
            if self.state.wizard_index == WIZARD_KINDS.index("drum"):
                self.state.wizard_profile = None
                self.state.wizard_kind = "route"
                self.state.wizard_index = 0
            else:
                self.state.wizard_kind = "profile"
                self.state.wizard_index = 0
            return
        if self.state.wizard_kind == "profile":
            self.state.wizard_profile = MELODIC_PROFILES[self.state.wizard_index]
            self.state.wizard_kind = "route"
            self.state.wizard_index = 0
            return
        # route: создаём, затем роутим, если выбран порт.
        options = self._wizard_options(snap)
        port = options[self.state.wizard_index]
        profile = self.state.wizard_profile
        self._wizard_cancel()  # сначала закрыть (сброс profile), потом создавать
        feedback = (
            self._engine.create_drum_track()
            if profile is None
            else self._engine.create_track(profile)
        )
        match = _CREATED_TRACK_RE.match(feedback)
        if port != WIZARD_ROUTE_NONE and match is not None:
            route_feedback = self._engine.route_track(match.group(1), port)
            if route_feedback.startswith("error:"):
                feedback = route_feedback
        self.state.flash(feedback, now, self._flash_seconds)

    def _move_cursor(self, delta: int, snap: StatusSnapshot) -> None:
        limit = self._cursor_limit(snap)
        if limit == 0:
            return
        self.state.selected = max(0, min(limit - 1, self.state.selected + delta))

    def _cursor_limit(self, snap: StatusSnapshot) -> int:
        if self.state.screen in _TRACK_SCREENS:
            return len(snap.tracks)
        if self.state.screen is ScreenId.PORTS:
            return len(snap.ports)
        return 0

    def _clamp_cursor(self, snap: StatusSnapshot) -> None:
        limit = self._cursor_limit(snap)
        # limit == 0 — экран без курсора (TRACK/GLOBAL/SYNC): selected
        # не трогаем, он нужен _selected_track на TRACK (баг: кламп
        # обнулял курсор при входе в TRACK — открывалась дорожка 0).
        if limit and self.state.selected >= limit:
            self.state.selected = max(0, limit - 1)

    # ------------------------------------------------------------------
    # Энкодеры (план D2 §3.4)
    # ------------------------------------------------------------------

    def _handle_encoder(
        self, name: str, increment: int, now: float, snap: StatusSnapshot
    ) -> None:
        screen = self.state.screen
        if name == "Tempo Encoder":
            self._command(self._engine.set_bpm(snap.bpm + increment * BPM_STEP), now)
            return
        if name == "Swing Encoder":
            self._command(
                self._engine.set_swing(snap.swing + increment * SWING_STEP), now
            )
            return
        if name not in TRACK_ENCODERS:
            return
        idx = TRACK_ENCODERS.index(name)

        if screen is ScreenId.WIZARD:
            if idx == 0:
                self._wizard_rotate(increment, snap)
            return
        if screen is ScreenId.TRACK_GEN:
            self._track_gen_encoder(idx, increment, now, snap)
        elif screen is ScreenId.TRACK_MACRO:
            self._track_macro_encoder(idx, increment, snap)
        elif screen is ScreenId.SCALE:
            self._global_encoder(idx, increment, now, snap)
        elif screen is ScreenId.SETUP and idx == 0:
            # E1 меняет источник клока только на вкладке CLOCK.
            if self.state.setup_tab % len(SETUP_TABS) == 0:
                self._sync_encoder(increment, now, snap)
        elif screen is ScreenId.PORTS:
            self._ports_encoder(idx, increment, now, snap)
        elif screen is ScreenId.DEMO:
            self._demo_encoder(idx, increment)
        # TRACKS: поворот на пустом слоте — игнор (§4).

    def _track_gen_encoder(
        self, idx: int, increment: int, now: float, snap: StatusSnapshot
    ) -> None:
        track = self._selected_track(snap)
        if track is None:
            log.debug("GEN: энкодер без выбранной дорожки")
            return
        if idx in (0, 1):
            self._cycle_source(track, slot=idx, delta=increment, now=now, snap=snap)
        elif idx == 2:
            self._command(
                self._engine.set_track_gate(
                    track.name, track.gate + increment * GATE_STEP
                ),
                now,
            )
        elif idx == 3 and track.density_applicable:
            self._command(
                self._engine.set_track_density(
                    track.name, track.density + increment / 127.0
                ),
                now,
            )
        elif idx == 4:
            self._command(
                self._engine.set_track_mutate(
                    track.name, track.mutate + increment / 127.0
                ),
                now,
            )
        # E6..E8 на GEN не назначены (CC-оси переехали на MACRO: E1..E3).

    def _track_macro_encoder(
        self, idx: int, increment: int, snap: StatusSnapshot
    ) -> None:
        track = self._selected_track(snap)
        if track is None:
            log.debug("MACRO: энкодер без выбранной дорожки")
            return
        if idx in _MACRO_AXIS_BY_ENCODER:
            self._cc_axis(track, _MACRO_AXIS_BY_ENCODER[idx], increment)

    def _cc_axis(self, track: TrackSummary, axis: MacroAxis, increment: int) -> None:
        """Performance-CC: сохранить значение + отправить, если есть порт."""
        value = self.state.set_macro_value(
            track.name,
            axis.value,
            self.state.macro_value(track.name, axis.value) + increment,
        )
        if track.port is None or self._cc_sender is None:
            return
        for param in self._macro_axes.cc_params(axis):
            self._cc_sender(track.port, param, track.channel, value)

    def _cycle_source(
        self,
        track: TrackSummary,
        slot: int,
        delta: int,
        now: float,
        snap: StatusSnapshot,
    ) -> None:
        """SRC/SRC2: листаем none → каждая другая дорожка → none."""
        candidates = [None] + [
            t.name
            for t in snap.tracks
            if t.name != track.name and t.name not in track.sources
        ]
        current = track.sources[slot] if len(track.sources) > slot else None
        try:
            pos = candidates.index(current)
        except ValueError:
            pos = 0
        nxt = candidates[(pos + (1 if delta > 0 else -1)) % len(candidates)]
        new_sources = list(track.sources)
        while len(new_sources) <= slot:
            new_sources.append("")
        new_sources[slot] = nxt or ""
        cleaned = tuple(s for s in new_sources if s)
        self._command(self._engine.set_track_sources(track.name, *cleaned), now)

    def _global_encoder(
        self, idx: int, increment: int, now: float, snap: StatusSnapshot
    ) -> None:
        """SCALE: любой энкодер листает лады — слоты KNOBS и есть лады (Ф5).

        Freeze корня — кнопки Upper/Lower Row 1–6 и стрелки Left/Right:
        было бы нельзя, чтобы энкодер менял не то, что написано над ним.
        """
        pos = SCALES.index(snap.scale) if snap.scale in SCALES else 0
        scale = SCALES[(pos + (1 if increment > 0 else -1)) % len(SCALES)]
        self._command(self._engine.set_scale(scale), now)

    def _sync_encoder(self, increment: int, now: float, snap: StatusSnapshot) -> None:
        pos = CLOCK_SOURCES.index(snap.clock_source)
        source = CLOCK_SOURCES[
            (pos + (1 if increment > 0 else -1)) % len(CLOCK_SOURCES)
        ]
        self._command(self._engine.request_clock_source(source), now)

    def _ports_encoder(
        self, idx: int, increment: int, now: float, snap: StatusSnapshot
    ) -> None:
        if idx == 0:
            # E1: листаем дорожку для назначения.
            if not snap.tracks:
                return
            current = self._route_track(snap)
            names = [t.name for t in snap.tracks]
            pos = names.index(current.name) if current else 0
            nxt = names[(pos + (1 if increment > 0 else -1)) % len(names)]
            self.state.ports_route_track = nxt
        elif idx == 1:
            # E2: листаем порт (применение — сразу).
            track = self._route_track(snap)
            if track is None:
                return
            options: list[str | None] = [None] + [p.name for p in snap.ports]
            try:
                pos = options.index(track.port)
            except ValueError:
                pos = 0
            new_port = options[(pos + (1 if increment > 0 else -1)) % len(options)]
            if new_port is None:
                self._command(self._engine.unroute_track(track.name), now)
            else:
                self._command(self._engine.route_track(track.name, new_port), now)

    # ------------------------------------------------------------------
    # DEMO (Note) — демо-экран фреймворка: E1/E2 листают вкладки, E3–E8 — значения
    # ------------------------------------------------------------------

    def _demo_view(self) -> DemoView:
        """Собрать DTO демо-экрана из UiState (индексы всегда в пределах рядов)."""
        return DemoView(
            top_tabs=DEMO_TOP_TABS,
            bottom_tabs=DEMO_BOTTOM_TABS,
            top_index=self.state.demo_top % len(DEMO_TOP_TABS),
            bottom_index=self.state.demo_bottom % len(DEMO_BOTTOM_TABS),
            values=self._demo_values(),
        )

    def _demo_values(self) -> tuple[int, ...]:
        """Ровно ``DEMO_VALUE_COUNT`` значений, даже если в state другая длина."""
        stored = self.state.demo_values
        return tuple(
            stored[i] if i < len(stored) else DEMO_VALUE_DEFAULT
            for i in range(DEMO_VALUE_COUNT)
        )

    def _demo_nav(self, name: str) -> None:
        """Стрелки на DEMO: Left/Right — верхние вкладки, Up/Down — нижние."""
        if name in ("Left", "Right"):
            inc = 1 if name == "Right" else -1
            self.state.demo_top = (self.state.demo_top + inc) % len(DEMO_TOP_TABS)
        else:
            inc = 1 if name == "Down" else -1
            self.state.demo_bottom = (
                self.state.demo_bottom + inc
            ) % len(DEMO_BOTTOM_TABS)

    def _demo_encoder(self, idx: int, increment: int) -> None:
        """E1/E2 — вкладки, E3–E8 — значения 0..127 (пишутся только в UiState)."""
        if idx == 0:
            self.state.demo_top = (
                self.state.demo_top + (1 if increment > 0 else -1)
            ) % len(DEMO_TOP_TABS)
            return
        if idx == 1:
            self.state.demo_bottom = (
                self.state.demo_bottom + (1 if increment > 0 else -1)
            ) % len(DEMO_BOTTOM_TABS)
            return
        slot = idx - 2
        if not 0 <= slot < DEMO_VALUE_COUNT:
            return
        values = list(self._demo_values())
        values[slot] = max(0, min(127, values[slot] + increment))
        self.state.demo_values = tuple(values)

    # ------------------------------------------------------------------
    # LED-подсветка рабочих кнопок (п. 4 запроса 02.11.2026)
    # ------------------------------------------------------------------

    def button_led_states(self, snap: StatusSnapshot) -> dict[str, int]:
        """Карта LED-состояний всех рабочих кнопок (имя → цвет-палитра).

        Не рабочие кнопки в карту не входят (их LED гаснет при дифф-отправке
        значением 0 — Push2Device шлёт полную карту, App диффит).
        """
        state = self.state
        states: dict[str, int] = {
            SESSION_BUTTON: LED_WHITE,
            CLIP_BUTTON: LED_WHITE,
            DEVICE_BUTTON: LED_WHITE,
            SCALE_BUTTON: LED_WHITE,
            SETUP_BUTTON: LED_WHITE,
            DEMO_BUTTON: LED_WHITE,
            "Add Track": LED_WHITE,
            "Browse": LED_WHITE,
            "Left": LED_GRAY,
            "Right": LED_GRAY,
            "Up": LED_GRAY,
            "Down": LED_GRAY,
            "Select": LED_GRAY,
            "Play": LED_GREEN if snap.running else LED_WHITE,
            "Record": LED_RED,
            "Shift": LED_WHITE if state.shift else LED_DIM,
            DELETE_BUTTON: LED_RED if state.delete_armed else LED_DIM,
        }
        # Mix — PORTS (единственное назначение верхнего ряда;
        # остальные кнопки ряда освобождены под будущее и не подсвечиваются).
        states[PORTS_BUTTON] = LED_WHITE if state.screen is ScreenId.PORTS else LED_GRAY
        states[DEMO_BUTTON] = LED_GREEN if state.screen is ScreenId.DEMO else LED_GRAY
        # Upper/Lower Row 1–8 — из Grid-макета экрана (Ф6): Button.active → зелёный,
        # иначе белый. Экраны без макета (TRACKS, SCALE, SETUP, WIZARD) — карта ниже.
        for row_name, buttons in self._layout_button_leds(self.build_view(snap, 0.0)):
            for slot, active in enumerate(buttons):
                states[f"{row_name} {slot + 1}"] = LED_GREEN if active else LED_WHITE
        # TRACKS: Lower Row — дорожки страницы, курсор — зелёный.
        if state.screen is ScreenId.TRACKS:
            start = state.page * PAGE_SIZE
            for i in range(PAGE_SIZE):
                if start + i < len(snap.tracks):
                    states[f"Lower Row {i + 1}"] = (
                        LED_GREEN if i == state.selected % PAGE_SIZE else LED_WHITE
                    )
        if state.screen is ScreenId.WIZARD:
            states["Add Track"] = LED_GREEN  # в wizard — подтверждение шага
        return states

    def _layout_button_leds(
        self, view: ScreenView
    ) -> tuple[tuple[str, tuple[bool, ...]], ...]:
        """Активность Button по рядам Upper/Lower Row из макета экрана.

        Пустой кортеж — экран без Grid-макета (там LED считается ручной картой выше).
        """
        screen = next(
            (s for s in DEFAULT_SCREENS if s.name == self.state.screen.value), None
        )
        if screen is None:
            return ()
        try:
            layout = screen.layout(view)
        except NotImplementedError:
            return ()
        rows: list[tuple[str, tuple[bool, ...]]] = []
        for row_name, row in (("Upper Row", layout.upper), ("Lower Row", layout.lower)):
            if not any(isinstance(item, Button) for item in row):
                continue
            rows.append(
                (row_name, tuple(getattr(item, "active", False) for item in row[:SLOT_COUNT]))
            )
        return tuple(rows)

    # ------------------------------------------------------------------
    # Хелперы view
    # ------------------------------------------------------------------

    def _command(self, feedback: str, now: float) -> None:
        """Фидбек команды: error: → flash; успех — не показываем (шум)."""
        if feedback.startswith("error:"):
            self.state.flash(feedback, now, self._flash_seconds)

    def _selected_track(self, snap: StatusSnapshot) -> TrackSummary | None:
        idx = self.state.selected
        return snap.tracks[idx] if 0 <= idx < len(snap.tracks) else None

    def _route_track(self, snap: StatusSnapshot) -> TrackSummary | None:
        if self.state.ports_route_track:
            for t in snap.tracks:
                if t.name == self.state.ports_route_track:
                    return t
        return self._selected_track(snap)

    def _title(self, snap: StatusSnapshot) -> str:
        screen = self.state.screen
        if screen is ScreenId.TRACKS:
            total = len(snap.tracks)
            start = self.state.page * PAGE_SIZE
            end = min(start + PAGE_SIZE, max(total, start + PAGE_SIZE))
            page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            return f"TRACKS {start + 1}-{end}/{page_count}"
        if screen is ScreenId.TRACK_GEN:
            track = self._selected_track(snap)
            return f"GEN: {track.name}" if track else "GEN: —"
        if screen is ScreenId.TRACK_MACRO:
            track = self._selected_track(snap)
            return f"MACRO: {track.name}" if track else "MACRO: —"
        if screen is ScreenId.SCALE:
            return f"SCALE: {snap.root} {snap.scale}"
        if screen is ScreenId.SETUP:
            tab = SETUP_TABS[self.state.setup_tab % len(SETUP_TABS)]
            return f"SETUP: {tab.upper()}"
        if screen is ScreenId.WIZARD:
            if self.state.wizard_kind == "kind":
                return "ADD TRACK: KIND"
            if self.state.wizard_kind == "profile":
                return "ADD TRACK: PROFILE"
            return "ADD TRACK: ROUTE"
        if screen is ScreenId.DEMO:
            return "DEMO: FRAMEWORK"
        return "PORTS"

    def _track_rows(self, snap: StatusSnapshot) -> tuple[TrackRowView, ...]:
        start = self.state.page * PAGE_SIZE
        page = snap.tracks[start : start + PAGE_SIZE]
        rows = tuple(
            TrackRowView(
                name=t.name,
                kind=t.kind,
                profile=t.profile,
                channel=t.channel,
                port=t.port,
                frozen=t.frozen,
                mutation_count=t.mutation_count,
                selected=i == self.state.selected % PAGE_SIZE,
                # §4.8: цвет — свойство дорожки, а не позиция на странице.
                color=track_color(t.color_slot) if t.color_slot is not None else 0,
            )
            for i, t in enumerate(page)
        )
        # Пустые слоты страницы — до PAGE_SIZE строк (курсор виден на пустой).
        sel = self.state.selected % PAGE_SIZE
        if len(rows) < PAGE_SIZE and sel >= len(rows):
            pad = sel - len(rows) + 1
            rows += tuple(
                TrackRowView(
                    name="—",
                    kind="",
                    profile="",
                    channel=0,
                    port=None,
                    frozen=False,
                    mutation_count=0,
                    selected=True,
                )
                for _ in range(pad if len(rows) + pad <= PAGE_SIZE else 0)
            )
        return rows

    def _track_color_for_selection(self, snap: StatusSnapshot) -> int:
        """Цвет выбранной дорожки — её собственный слот (§4.8).

        Один и тот же слот даёт один и тот же цвет на TRACKS, GEN и MACRO;
        страница и позиция в списке на это не влияют.
        """
        track = self._selected_track(snap)
        if track is None or track.color_slot is None:
            return 0
        return track_color(track.color_slot)

    def _track_detail(self, snap: StatusSnapshot) -> TrackDetailView | None:
        track = self._selected_track(snap)
        if track is None:
            return None
        return TrackDetailView(
            name=track.name,
            kind=track.kind,
            profile=track.profile,
            channel=track.channel,
            port=track.port,
            sources=track.sources,
            gate=track.gate,
            voicing=track.voicing,
            density=track.density if track.density_applicable else None,
            mutate=track.mutate,
            color=self._track_color_for_selection(snap),
        )

    def _track_macro(self, snap: StatusSnapshot) -> TrackMacroView | None:
        track = self._selected_track(snap)
        if track is None:
            return None
        macros = (
            (
                self.state.macro_value(track.name, MacroAxis.TONE.value),
                self.state.macro_value(track.name, MacroAxis.SPACE.value),
                self.state.macro_value(track.name, MacroAxis.DEPTH.value),
            )
            if track.port is not None
            else (-1, -1, -1)
        )
        return TrackMacroView(
            name=track.name,
            kind=track.kind,
            channel=track.channel,
            port=track.port,
            macros=macros,
            color=self._track_color_for_selection(snap),
        )
