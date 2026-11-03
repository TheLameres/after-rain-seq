"""AppEngineControl — реализация EngineControl для App.

Единственный модуль проекта (кроме самого App), имеющий доступ к
внутренностям приложения. Исключения движка ловятся здесь и
превращаются в текст ошибки — REPL не падает по команде.

Все вызовы команд управления идут через методы движка, спроектированные
для внешних вызовов (как кнопки Push 2): они валидируют вход.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from src.harmony.harmony import HarmonyError
from src.repl.engine_control import EngineControl
from src.repl.log_buffer import LogBuffer
from src.repl.status import StatusSnapshot, TrackSummary
from src.session.model.drum_track import DrumTrack
from src.session.model.melodic_profile import PROFILES
from src.session.model.melodic_track import MelodicTrack
from src.sync.clock_source import ClockSource

if TYPE_CHECKING:
    from src.app.application import App

# Диапазон BPM (совпадает с валидацией SyncConfig).
MIN_BPM: float = 20.0
MAX_BPM: float = 300.0


class AppEngineControl(EngineControl):
    """Мост между REPL и App: реализует контракт EngineControl.

    Параметры:
        app: Запущенное приложение (через read-only свойства).
        log_buffer: Кольцевой буфер логов (``logs``/``log_error``).
    """

    def __init__(self, app: App, log_buffer: LogBuffer | None = None) -> None:
        self._app = app
        self._log_buffer = log_buffer

    # ------------------------------------------------------------------
    # Статус и логи
    # ------------------------------------------------------------------

    def get_status(self) -> StatusSnapshot:
        """Снапшот из main loop + последняя ошибка лога из буфера."""
        snap = self._app.status_snapshot
        if self._log_buffer is not None:
            last_error = self._log_buffer.last_error
            if last_error != snap.log_error:
                snap = replace(snap, log_error=last_error)
        return snap

    def get_logs(self, n: int) -> list[str]:
        """Последние n строк лога."""
        if self._log_buffer is None:
            return []
        return self._log_buffer.get_last(n)

    # ------------------------------------------------------------------
    # Транспорт и клок
    # ------------------------------------------------------------------

    def start_transport(self) -> str:
        """Запустить транспорт (старт ClockManager)."""
        cm = self._app.clock_manager
        if cm is None:
            return "error: clock subsystem disabled (sync.enabled=false)"
        if cm.state.running:
            return "transport already running"
        cm.start()
        return f"transport started (clock: {cm.state.source.name.lower()})"

    def stop_transport(self) -> str:
        """Остановить транспорт: all notes off + остановка клока."""
        cm = self._app.clock_manager
        if cm is None:
            return "error: clock subsystem disabled (sync.enabled=false)"
        if not cm.state.running:
            return "transport is not running"
        transport = self._app.transport
        if transport is not None:
            transport.all_notes_off()
        cm.stop()
        return "transport stopped (all notes off)"

    def set_bpm(self, bpm: float) -> str:
        """Установить BPM через App.set_sync_bpm() (механизм энкодера)."""
        if not MIN_BPM <= bpm <= MAX_BPM:
            return f"error: bpm {bpm} out of range {MIN_BPM:.0f}..{MAX_BPM:.0f}"
        self._app.set_sync_bpm(bpm)
        return f"bpm set to {bpm:.1f}"

    def set_swing(self, amount: float) -> str:
        """Установить свинг (0.0–1.0) в рантайме."""
        if not 0.0 <= amount <= 1.0:
            return f"error: swing must be 0..1, got {amount}"
        swing = self._app.swing_applier
        if swing is None:
            return "error: swing not available"
        swing.set_amount(amount)
        return f"swing set to {amount:.2f}"

    def request_clock_source(self, source: str) -> str:
        """Переключить источник клока на ближайшей доле."""
        cm = self._app.clock_manager
        if cm is None:
            return "error: clock subsystem disabled (sync.enabled=false)"
        mapping = {s.name.lower(): s for s in ClockSource}
        target = mapping.get(source.lower())
        if target is None:
            known = ", ".join(sorted(mapping))
            return f"error: unknown clock source {source!r} (choose: {known})"
        if cm.current_source is target:
            return f"already using {source.lower()}"
        cm.request_source(target)
        state = cm.state
        if state.error:
            return f"error: {state.error}"
        return f"switched to {source.lower()} on next beat"

    # ------------------------------------------------------------------
    # Порты
    # ------------------------------------------------------------------

    def rescan_ports(self) -> str:
        """Принудительный rescan портов (тот же путь, что hot-plug poll)."""
        pm = self._app.port_manager
        registry = self._app.port_registry
        if pm is None or registry is None:
            return "error: port manager not available"
        events = pm.poll()
        for event in events:
            registry.handle_port_event(event)
        if not events:
            return "scan complete: no changes"
        changes = "; ".join(
            f"{e.label}: {e.old_status.name.lower()} → {e.new_status.name.lower()}"
            for e in events
        )
        return f"scan complete: {len(events)} change(s): {changes}"

    def switch_port(self, label: str, match: str) -> str:
        """Перенаправить лейбл порта на другое устройство (рантайм-only)."""
        pm = self._app.port_manager
        if pm is None:
            return "error: port manager not available"
        try:
            pm.request_switch(label, match)
        except ValueError as exc:
            return f"error: {exc}"
        return (
            f"switch scheduled: {label!r} → match {match!r}; "
            "applies on next poll (~2 s) — verify with 'ports'"
        )

    # ------------------------------------------------------------------
    # Гармония
    # ------------------------------------------------------------------

    def set_root(self, root: str) -> str:
        """Сменить тонику (HarmonyError → текст)."""
        harmony = self._app.harmony
        if harmony is None:
            return "error: harmony not available"
        try:
            harmony.set_root(root)
        except HarmonyError as exc:
            return f"error: {exc}"
        return f"root set to {harmony.root} ({harmony.scale_name})"

    def set_scale(self, name: str) -> str:
        """Сменить лад с валидацией (пентатоника отклоняется)."""
        harmony = self._app.harmony
        if harmony is None:
            return "error: harmony not available"
        try:
            harmony.set_scale(name)
        except HarmonyError as exc:
            return f"error: {exc}"
        return f"scale set to {harmony.scale_name} ({harmony.root})"

    # ------------------------------------------------------------------
    # Сессия
    # ------------------------------------------------------------------

    def list_tracks(self) -> list[TrackSummary]:
        """Сводки дорожек из снапшота (топологический порядок)."""
        return list(self.get_status().tracks)

    def create_track(self, profile: str, channel: int | None = None) -> str:
        """Создать melodic-дорожку профиля (лимиты — текстом).

        Канал: ``None`` — автоназначение первого свободного (без слипания
        с другими дорожками на порту); иначе явный 0..15.
        """
        session = self._app.session
        if session is None:
            return "error: session not available"
        if profile not in PROFILES:
            known = ", ".join(sorted(PROFILES))
            return f"error: unknown profile {profile!r} (choose: {known})"
        try:
            track = session.create_melodic_track(profile, channel=channel)
        except ValueError as exc:
            return f"error: {exc}"
        return f'created track "{track.name}" (profile {profile}, ch {track.channel})'

    def set_track_channel(self, name: str, channel: int) -> str:
        """Сменить MIDI-канал дорожки в рантайме (движки подхватывают live).

        Аргументы:
            name: Имя дорожки.
            channel: Новый канал 0..15.

        Returns:
            Текст результата; ``error:``-префикс при проблемах.
        """
        session = self._app.session
        if session is None:
            return "error: session not available"
        track = session.get_track(name)
        if track is None:
            return f"error: track {name!r} not found"
        if not 0 <= channel <= 15:
            return f"error: channel must be 0..15, got {channel}"
        old = track.channel
        track.channel = channel
        return f'track "{name}": channel {old} → {channel}'

    def remove_track(self, name: str) -> str:
        """Удалить дорожку (вместе с движком); зависимые получают sources = ()."""
        return self._app.drop_track(name)

    def route_track(self, name: str, label: str) -> str:
        """Привязать дорожку к MIDI-порту (делегирует App)."""
        return self._app.route_track(name, label)

    def unroute_track(self, name: str) -> str:
        """Отключить дорожку от порта (делегирует App)."""
        return self._app.unroute_track(name)

    def freeze(self, name: str | None = None) -> str:
        """Заморозить все дорожки или одну по имени."""
        session = self._app.session
        if session is None:
            return "error: session not available"
        if name is None:
            session.freeze_all()
            return "all tracks frozen"
        track = session.get_track(name)
        if track is None:
            return f"error: track {name!r} not found"
        if not isinstance(track, (MelodicTrack, DrumTrack)):
            return f"error: cannot freeze track {name!r}"
        track.freeze()  # MelodicTrack: mutate=0; DrumTrack: базовый паттерн
        return f'froze track "{name}"'

    def evolve(self) -> str:
        """Разморозить и продолжить эволюцию."""
        session = self._app.session
        if session is None:
            return "error: session not available"
        session.evolve_all()
        return "all tracks evolved"

    # ------------------------------------------------------------------
    # Сессия — расширения D2 (экраны TRACK/TRACKS)
    # ------------------------------------------------------------------

    def create_drum_track(self) -> str:
        """Создать drum-дорожку (лимит 2 — текстом из ValueError)."""
        session = self._app.session
        if session is None:
            return "error: session not available"
        try:
            track = session.create_drum_track()
        except ValueError as exc:
            return f"error: {exc}"
        return f'created track "{track.name}" (drum, ch {track.channel})'

    def set_track_sources(self, name: str, *sources: str) -> str:
        """Назначить источники; цикл графа — человекочитаемый текст."""
        session = self._app.session
        if session is None:
            return "error: session not available"
        if session.get_track(name) is None:
            return f"error: track {name!r} not found"
        for src in sources:
            if session.get_track(src) is None:
                return f"error: source track {src!r} not found"
        try:
            session.set_sources(name, *sources)
        except ValueError as exc:
            return f"error: {exc}"
        joined = "+".join(sources) if sources else "—"
        return f'track "{name}": sources = {joined}'

    def _melodic_track(self, name: str) -> MelodicTrack | str:
        """MelodicTrack по имени или текст ошибки."""
        session = self._app.session
        if session is None:
            return "error: session not available"
        track = session.get_track(name)
        if track is None:
            return f"error: track {name!r} not found"
        if not isinstance(track, MelodicTrack):
            return f"error: track {name!r} is not melodic"
        return track

    def set_track_gate(self, name: str, gate: float) -> str:
        """Установить гейт melodic-дорожки (0.0–1.0)."""
        track = self._melodic_track(name)
        if isinstance(track, str):
            return track
        if not 0.0 <= gate <= 1.0:
            return f"error: gate must be 0..1, got {gate}"
        track.gate = float(gate)
        return f'track "{name}": gate = {gate:.2f}'

    def set_track_density(self, name: str, density: float) -> str:
        """Установить плотность паттерна (0.0–1.0, макро-ось DEN)."""
        track = self._melodic_track(name)
        if isinstance(track, str):
            return track
        if not 0.0 <= density <= 1.0:
            return f"error: density must be 0..1, got {density}"
        track.density = float(density)
        return f'track "{name}": density = {density:.2f}'

    def set_track_mutate(self, name: str, mutate: float) -> str:
        """Установить вероятность мутации (0.0–1.0, макро-ось MUT)."""
        session = self._app.session
        if session is None:
            return "error: session not available"
        track = session.get_track(name)
        if track is None:
            return f"error: track {name!r} not found"
        if not isinstance(track, (MelodicTrack, DrumTrack)):
            return f"error: track {name!r} is not mutable"
        if not 0.0 <= mutate <= 1.0:
            return f"error: mutate must be 0..1, got {mutate}"
        track.mutate = float(mutate)
        return f'track "{name}": mutate = {mutate:.2f}'

    def set_track_muted(self, name: str, muted: bool) -> str:
        """Заглушить/разглушить дорожку (§4.6).

        Дорожка продолжает генерировать и мутировать — глушится только
        доставка, поэтому снятие mute возвращает её в такт.
        """
        session = self._app.session
        if session is None:
            return "error: session not available"
        track = session.get_track(name)
        if track is None:
            return f"error: track {name!r} not found"
        track.muted = bool(muted)
        state = "muted" if track.muted else "unmuted"
        return f'track "{name}": {state}'

    def evolve_track(self, name: str) -> str:
        """Разморозить одну дорожку (MelodicTrack: mutate=0.5, DrumTrack: 0.5)."""
        session = self._app.session
        if session is None:
            return "error: session not available"
        track = session.get_track(name)
        if track is None:
            return f"error: track {name!r} not found"
        if not isinstance(track, (MelodicTrack, DrumTrack)):
            return f"error: cannot evolve track {name!r}"
        track.mutate = 0.5
        return f'evolved track "{name}"'
