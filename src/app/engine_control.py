"""AppEngineControl — реализация EngineControl для App.

Единственный модуль проекта (кроме самого App), имеющий доступ к
внутренностям приложения. Исключения движка ловятся здесь и
превращаются в текст ошибки — REPL не падает по команде.

Все вызовы команд управления идут через методы движка, спроектированные
для внешних вызовов (как кнопки Push 2): они валидируют вход.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from src.core.engine_result import EngineResult
from src.harmony.degree_names import format_degrees
from src.harmony.harmony import Harmony, HarmonyError
from src.repl.engine_control import EngineControl
from src.repl.log_buffer import LogBuffer
from src.repl.status import StatusSnapshot, TrackSummary
from src.session.model.drum_pattern_lang import DrumPatternCompiler
from src.session.model.drum_track import DrumTrack
from src.session.model.melodic_profile import PROFILES
from src.session.model.melodic_track import MAX_OCTAVE, MelodicTrack
from src.session.model.track import Track
from src.session.mutation.mutation_engine import MutationEngine
from src.session.session import Session
from src.sync.capture_recorder import CaptureRecorder
from src.sync.clock_manager import ClockManager
from src.sync.clock_source import ClockSource
from src.sync.ports import PortManager
from src.sync.routing import PortRegistry
from src.sync.smf_writer import SmfWriter
from src.sync.swing import SwingApplier
from src.sync.transport import Transport

log = logging.getLogger(__name__)


class AppPorts(Protocol):
    """Что фасаду команд нужно от приложения: ровно те члены, что он читает.

    Протокол вместо ``App``: ``engine_control`` не импортирует приложение, и
    цикл ``application`` ↔ ``engine_control`` исчезает. ``App`` подходит
    структурно; при появлении нового члена, который фасад читает, он должен
    попасть сюда, иначе mypy/pyright это покажут.
    """

    @property
    def session(self) -> Session | None: ...
    @property
    def clock_manager(self) -> ClockManager | None: ...
    @property
    def mutation_engine(self) -> MutationEngine | None: ...
    @property
    def port_manager(self) -> PortManager | None: ...
    @property
    def port_registry(self) -> PortRegistry | None: ...
    @property
    def harmony(self) -> Harmony | None: ...
    @property
    def transport(self) -> Transport | None: ...
    @property
    def swing_applier(self) -> SwingApplier | None: ...
    @property
    def status_snapshot(self) -> StatusSnapshot: ...
    @property
    def sync_bpm(self) -> float: ...

    def set_sync_bpm(self, value: float) -> None: ...
    def route_track(self, name: str, label: str) -> EngineResult: ...
    def unroute_track(self, name: str) -> EngineResult: ...
    def drop_track(self, name: str) -> EngineResult: ...


# Диапазон BPM (совпадает с валидацией SyncConfig).
MIN_BPM: float = 20.0
MAX_BPM: float = 300.0

CAPTURE_DIR: str = "captures"
"""Каталог автогенерации capture-файлов (design add-capture-smf §6, Non-Goal:
секция в config.yaml). Тесты monkeypatch-ат эту константу."""


class AppEngineControl(EngineControl):
    """Мост между REPL и App: реализует контракт EngineControl.

    Параметры:
        app: Запущенное приложение (через read-only свойства).
        log_buffer: Кольцевой буфер логов (``logs``/``log_error``).
    """

    def __init__(self, app: AppPorts, log_buffer: LogBuffer | None = None) -> None:
        self._app = app
        self._log_buffer = log_buffer
        # Состояние захвата SMF (add-capture-smf design §6): фасад
        # однопоточный со стороны вызовов (REPL-поток/ScriptRunner).
        self._capture_recorder: CaptureRecorder | None = None
        self._capture_path: Path | None = None
        self._capture_bpm: float | None = None

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

    def start_transport(self) -> EngineResult:
        """Запустить транспорт (старт ClockManager)."""
        cm = self._app.clock_manager
        if cm is None:
            return EngineResult.fail("clock subsystem disabled (sync.enabled=false)")
        if cm.state.running:
            return EngineResult.ok("transport already running")
        cm.start()
        return EngineResult.ok(
            f"transport started (clock: {cm.state.source.name.lower()})"
        )

    def stop_transport(self) -> EngineResult:
        """Остановить транспорт: all notes off + остановка клока."""
        cm = self._app.clock_manager
        if cm is None:
            return EngineResult.fail("clock subsystem disabled (sync.enabled=false)")
        if not cm.state.running:
            return EngineResult.ok("transport is not running")
        transport = self._app.transport
        if transport is not None:
            transport.all_notes_off()
        cm.stop()
        return EngineResult.ok("transport stopped (all notes off)")

    def set_bpm(self, bpm: float) -> EngineResult:
        """Установить BPM через App.set_sync_bpm() (механизм энкодера)."""
        if not MIN_BPM <= bpm <= MAX_BPM:
            return EngineResult.fail(
                f"bpm {bpm} out of range {MIN_BPM:.0f}..{MAX_BPM:.0f}"
            )
        self._app.set_sync_bpm(bpm)
        return EngineResult.ok(f"bpm set to {bpm:.1f}")

    def set_swing(self, amount: float) -> EngineResult:
        """Установить свинг (0.0–1.0) в рантайме."""
        if not 0.0 <= amount <= 1.0:
            return EngineResult.fail(f"swing must be 0..1, got {amount}")
        swing = self._app.swing_applier
        if swing is None:
            return EngineResult.fail("swing not available")
        swing.set_amount(amount)
        return EngineResult.ok(f"swing set to {amount:.2f}")

    def request_clock_source(self, source: str) -> EngineResult:
        """Переключить источник клока на ближайшей доле."""
        cm = self._app.clock_manager
        if cm is None:
            return EngineResult.fail("clock subsystem disabled (sync.enabled=false)")
        mapping = {s.name.lower(): s for s in ClockSource}
        target = mapping.get(source.lower())
        if target is None:
            known = ", ".join(sorted(mapping))
            return EngineResult.fail(
                f"unknown clock source {source!r} (choose: {known})"
            )
        if cm.current_source is target:
            return EngineResult.ok(f"already using {source.lower()}")
        cm.request_source(target)
        state = cm.state
        if state.error:
            return EngineResult.fail(f"{state.error}")
        return EngineResult.ok(f"switched to {source.lower()} on next beat")

    # ------------------------------------------------------------------
    # Порты
    # ------------------------------------------------------------------

    def rescan_ports(self) -> EngineResult:
        """Принудительный rescan портов (тот же путь, что hot-plug poll)."""
        pm = self._app.port_manager
        registry = self._app.port_registry
        if pm is None or registry is None:
            return EngineResult.fail("port manager not available")
        events = pm.poll()
        for event in events:
            registry.handle_port_event(event)
        if not events:
            return EngineResult.ok("scan complete: no changes")
        changes = "; ".join(
            f"{e.label}: {e.old_status.name.lower()} → {e.new_status.name.lower()}"
            for e in events
        )
        return EngineResult.ok(f"scan complete: {len(events)} change(s): {changes}")

    def switch_port(self, label: str, match: str) -> EngineResult:
        """Перенаправить лейбл порта на другое устройство (рантайм-only)."""
        pm = self._app.port_manager
        if pm is None:
            return EngineResult.fail("port manager not available")
        try:
            pm.request_switch(label, match)
        except ValueError as exc:
            return EngineResult.fail(f"{exc}")
        return EngineResult.ok(
            f"switch scheduled: {label!r} → match {match!r}; "
            "applies on next poll (~2 s) — verify with 'ports'"
        )

    # ------------------------------------------------------------------
    # Гармония
    # ------------------------------------------------------------------

    def set_root(self, root: str) -> EngineResult:
        """Сменить тонику (HarmonyError → текст)."""
        harmony = self._app.harmony
        if harmony is None:
            return EngineResult.fail("harmony not available")
        try:
            harmony.set_root(root)
        except HarmonyError as exc:
            return EngineResult.fail(f"{exc}")
        return EngineResult.ok(f"root set to {harmony.root} ({harmony.scale_name})")

    def set_scale(self, name: str) -> EngineResult:
        """Сменить лад с валидацией (пентатоника отклоняется)."""
        harmony = self._app.harmony
        if harmony is None:
            return EngineResult.fail("harmony not available")
        try:
            harmony.set_scale(name)
        except HarmonyError as exc:
            return EngineResult.fail(f"{exc}")
        return EngineResult.ok(f"scale set to {harmony.scale_name} ({harmony.root})")

    # ------------------------------------------------------------------
    # Сессия
    # ------------------------------------------------------------------

    def list_tracks(self) -> list[TrackSummary]:
        """Сводки дорожек из снапшота (топологический порядок)."""
        return list(self.get_status().tracks)

    def _default_output_label(self) -> str | None:
        """Метка первого настроенного выходного порта (или ``None``).

        Новая дорожка сразу привязывается к нему: без маршрута её движок
        пишет в несуществующий порт, и транспорт молча отбрасывает ноты.
        """
        manager = self._app.port_manager
        if manager is None:
            return None
        states = manager.all_states()
        for state in states:
            if state.direction == "output":
                return state.label
        return None

    def _route_new_track(self, name: str) -> None:
        """Привязать только что созданную дорожку к первому выходу.

        Ошибка маршрута не отменяет создание: дорожку можно привязать позже
        (``track route``), а сообщение об этом уходит в лог.
        """
        label = self._default_output_label()
        if label is None:
            return
        routed = self._app.route_track(name, label)
        if routed.error:
            import logging

            logging.getLogger(__name__).warning(
                "create_track: не удалось привязать %s к %r: %s",
                name,
                label,
                routed.message,
            )

    def create_track(
        self, profile: str, channel: int | None = None, name: str | None = None
    ) -> EngineResult:
        """Создать melodic-дорожку профиля (лимиты — текстом).

        Канал: ``None`` — автоназначение первого свободного (без слипания
        с другими дорожками на порту); иначе явный 0..15.
        Имя: ``None`` — автоимя счётчика; иначе явное (пустое/дубликат —
        текст ошибки). Дорожка сразу привязывается к первому настроенному
        выходу.
        """
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        if profile not in PROFILES:
            known = ", ".join(sorted(PROFILES))
            return EngineResult.fail(f"unknown profile {profile!r} (choose: {known})")
        try:
            track = session.create_melodic_track(profile, channel=channel, name=name)
        except ValueError as exc:
            return EngineResult.fail(f"{exc}")
        self._route_new_track(track.name)
        port = track.port or "—"
        return EngineResult.ok(
            f'created track "{track.name}" (profile {profile}, ch {track.channel}, '
            f"port {port})",
            track=track.name,
        )

    def set_track_channel(self, name: str, channel: int) -> EngineResult:
        """Сменить MIDI-канал дорожки в рантайме (движки подхватывают live).

        Аргументы:
            name: Имя дорожки.
            channel: Новый канал 0..15.

        Returns:
            Текст результата; ``error:``-префикс при проблемах.
        """
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        track = session.get_track(name)
        if track is None:
            return EngineResult.fail(f"track {name!r} not found")
        if not 0 <= channel <= 15:
            return EngineResult.fail(f"channel must be 0..15, got {channel}")
        old = track.channel
        track.channel = channel
        return EngineResult.ok(f'track "{name}": channel {old} → {channel}')

    def remove_track(self, name: str) -> EngineResult:
        """Удалить дорожку (вместе с движком); зависимые получают sources = ()."""
        return self._app.drop_track(name)

    def route_track(self, name: str, label: str) -> EngineResult:
        """Привязать дорожку к MIDI-порту (делегирует App)."""
        return self._app.route_track(name, label)

    def unroute_track(self, name: str) -> EngineResult:
        """Отключить дорожку от порта (делегирует App)."""
        return self._app.unroute_track(name)

    # ------------------------------------------------------------------
    # Сессия — расширения D2 (экраны TRACK/TRACKS)
    # ------------------------------------------------------------------

    def create_drum_track(self, name: str | None = None) -> EngineResult:
        """Создать drum-дорожку (лимиты — текстом из ValueError).

        Имя: ``None`` — автоимя счётчика; иначе явное (пустое/дубликат —
        текст ошибки). После создания и маршрутизации дорожка
        регистрируется в механизме истории версий (design §7): undo/
        recall доступны с первой правки. При выключенной мутации
        (движка нет) дорожка создаётся без истории — в фидбеке note.
        """
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        try:
            track = session.create_drum_track(name=name)
        except ValueError as exc:
            return EngineResult.fail(f"{exc}")
        self._route_new_track(track.name)
        engine = self._app.mutation_engine
        message = (
            f'created track "{track.name}" (drum, ch {track.channel}, '
            f"port {track.port or '—'})"
        )
        if engine is not None:
            engine.register_drum_track(track.name, track)
        else:
            message += (
                "\nnote: mutation disabled — no version history "
                "(undo/recall unavailable)"
            )
        return EngineResult.ok(message, track=track.name)

    def track_sources(self) -> dict[str, tuple[str, ...]]:
        """Источники по дорожкам из сессии (снапшот вне запуска пуст)."""
        session = self._app.session
        if session is None:
            return {}
        return {t.name: tuple(t.sources) for t in session.ordered_tracks()}

    def _source_warnings(self, name: str, sources: tuple[str, ...]) -> list[str]:
        """Подписки, которые технически приняты, но на звук не влияют.

        Дорожка без ``reads_source`` (lead, bass) источники игнорирует, а
        DrumTrack в графе гармонии не участвует и ничего не публикует.
        Молчаливое принятие выглядит как «настроил, а не работает» — поэтому
        предупреждаем, но не отказываем: подписку можно включить позже сменой
        профиля.
        """
        session = self._app.session
        if session is None or not sources:
            return []
        warnings: list[str] = []
        track = session.get_track(name)
        profile = getattr(track, "profile", None)
        if profile is not None and not getattr(profile, "reads_source", False):
            warnings.append(
                f"профиль {profile.name if hasattr(profile, 'name') else '?'} "
                f"не читает источники: подписка не влияет на звук"
            )
        silent = [
            src
            for src in sources
            if not getattr(
                getattr(session.get_track(src), "profile", None), "emits_chords", False
            )
        ]
        if silent:
            warnings.append(
                "источник не публикует аккорды: " + ", ".join(repr(s) for s in silent)
            )
        return warnings

    def set_track_sources(self, name: str, *sources: str) -> EngineResult:
        """Назначить источники; цикл графа — человекочитаемый текст."""
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        if session.get_track(name) is None:
            return EngineResult.fail(f"track {name!r} not found")
        for src in sources:
            if session.get_track(src) is None:
                return EngineResult.fail(f"source track {src!r} not found")
        try:
            session.set_sources(name, *sources)
        except ValueError as exc:
            return EngineResult.fail(f"{exc}")
        joined = "+".join(sources) if sources else "—"
        message = f'track "{name}": sources = {joined}'
        for warning in self._source_warnings(name, tuple(sources)):
            message += f"\nnote: {warning}"
        return EngineResult.ok(message)

    def _melodic_track(self, name: str) -> MelodicTrack | EngineResult:
        """MelodicTrack по имени или результат с ошибкой."""
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        track = session.get_track(name)
        if track is None:
            return EngineResult.fail(f"track {name!r} not found")
        if not isinstance(track, MelodicTrack):
            return EngineResult.fail(f"track {name!r} is not melodic")
        return track

    def set_track_gate(self, name: str, gate: float) -> EngineResult:
        """Установить гейт melodic-дорожки (0.0–1.0)."""
        track = self._melodic_track(name)
        if isinstance(track, EngineResult):
            return track
        if not 0.0 <= gate <= 1.0:
            return EngineResult.fail(f"gate must be 0..1, got {gate}")
        track.gate = float(gate)
        return EngineResult.ok(f'track "{name}": gate = {gate:.2f}')

    def set_track_density(self, name: str, density: float) -> EngineResult:
        """Установить плотность паттерна (0.0–1.0, макро-ось DEN)."""
        track = self._melodic_track(name)
        if isinstance(track, EngineResult):
            return track
        if not 0.0 <= density <= 1.0:
            return EngineResult.fail(f"density must be 0..1, got {density}")
        track.density = float(density)
        return EngineResult.ok(f'track "{name}": density = {density:.2f}')

    # ------------------------------------------------------------------
    # Ручная мутация (spec «ручная мутация и линейная история», §3–§8)
    # ------------------------------------------------------------------

    def _mutation_engine(self) -> MutationEngine | EngineResult:
        """MutationEngine приложения или результат с ошибкой."""
        engine = self._app.mutation_engine
        if engine is None:
            return EngineResult.fail("mutation engine not available")
        return engine

    def _session_track(self, name: str) -> Track | EngineResult:
        """Дорожка сессии по имени или результат с ошибкой."""
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        track = session.get_track(name)
        if track is None:
            return EngineResult.fail(f"track {name!r} not found")
        return track

    @staticmethod
    def _cycle_beats(track: Track) -> float:
        """Длина цикла дорожки в битах (spec §5).

        Melodic — период паттерна профиля; drum — ``steps / 4`` (сетка из
        ``steps`` шагов на такт).
        """
        if isinstance(track, DrumTrack):
            return track.steps / 4.0
        if isinstance(track, MelodicTrack):
            return track.pattern_length
        return 4.0

    def request_mutation(self, name: str | None = None) -> EngineResult:
        """Шаг мутации: одна дорожка (``evolve <name>``) или все (``evolve``)."""
        engine = self._mutation_engine()
        if isinstance(engine, EngineResult):
            return engine
        if name is not None:
            track = self._session_track(name)
            if isinstance(track, EngineResult):
                return track
            if track.name not in engine.registered_tracks:
                return EngineResult.fail(f"track {name!r} is not mutable")
            track.pending = True
            engine.request_mutation(track.name, self._cycle_beats(track))
            return EngineResult.ok(f'track "{name}": mutation pending')
        count = 0
        session = self._app.session
        if session is not None:
            for track in session.ordered_tracks():
                if track.name in engine.registered_tracks:
                    track.pending = True
                    engine.request_mutation(track.name, self._cycle_beats(track))
                    count += 1
        return EngineResult.ok(f"mutation pending on {count} tracks")

    def undo_mutation(self, name: str) -> EngineResult:
        """Откатить дорожку на одну версию (spec §8: на корне — отказ)."""
        engine = self._mutation_engine()
        if isinstance(engine, EngineResult):
            return engine
        track = self._session_track(name)
        if isinstance(track, EngineResult):
            return track
        if track.name not in engine.registered_tracks:
            return EngineResult.fail(f"track {name!r} is not mutable")
        if not engine.undo(track.name):
            return EngineResult.fail(
                f'track "{name}": already at root version (nothing to undo)'
            )
        return EngineResult.ok(
            f'track "{name}": undo -> version {engine.current_version(track.name)}'
        )

    def recall_version(self, name: str, index: int) -> EngineResult:
        """Перейти на версию ``index`` (spec §8: неверный номер — отказ)."""
        engine = self._mutation_engine()
        if isinstance(engine, EngineResult):
            return engine
        track = self._session_track(name)
        if isinstance(track, EngineResult):
            return track
        if track.name not in engine.registered_tracks:
            return EngineResult.fail(f"track {name!r} is not mutable")
        if not engine.recall(track.name, index):
            return EngineResult.fail(
                f'track "{name}": no version {index} '
                f"(history has {engine.history_len(track.name)} versions)"
            )
        return EngineResult.ok(f'track "{name}": recall -> version {index}')

    def mutation_history(self, name: str) -> EngineResult:
        """Сводка истории версий дорожки (spec §6)."""
        engine = self._mutation_engine()
        if isinstance(engine, EngineResult):
            return engine
        track = self._session_track(name)
        if isinstance(track, EngineResult):
            return track
        if track.name not in engine.registered_tracks:
            return EngineResult.fail(f"track {name!r} is not mutable")
        total = engine.history_len(track.name)
        cursor = engine.current_version(track.name)
        return EngineResult.ok(
            f'track "{name}": {total} versions, current {cursor} (root 0)'
        )

    def set_drum_pattern(self, name: str, lane: str, pattern: str) -> EngineResult:
        """Задать паттерн lane'а drum-дорожки строкой-нотацией (design §7).

        Порядок: дорожка найдена → isinstance(DrumTrack) → ``resolve_lane``
        → компиляция (``DrumPatternCompiler.compile``, ``ValueError`` →
        fail) → замена ``lane.pattern`` новым списком целиком (reference
        swap) → ``record_manual_version``. Ошибка на любом шаге до замены
        — паттерн не меняется.

        Аргументы:
            name: Имя дорожки.
            lane: Адресация lane'а — индекс 0..15, GM-номер 36..51 или имя.
            pattern: Нотация (пустая строка — очистка lane'а).

        Returns:
            Подтверждение (имя дорожки, lane, число активных шагов) или
            человекочитаемая ошибка.
        """
        track = self._session_track(name)
        if isinstance(track, EngineResult):
            return track
        if not isinstance(track, DrumTrack):
            return EngineResult.fail(f"track {name!r} is not a drum track")
        try:
            lane_index = track.resolve_lane(lane)
        except ValueError as exc:
            return EngineResult.fail(f"track {name!r}: {exc}")
        try:
            cells = DrumPatternCompiler.compile(pattern, track.steps)
        except ValueError as exc:
            return EngineResult.fail(f"track {name!r}: {exc}")
        drum_lane = track.lanes[lane_index]
        drum_lane.pattern = cells
        active = sum(1 for cell in cells if cell)
        base = (
            f'track "{name}": lane {lane_index} ({drum_lane.name}): '
            f"{active} active step(s)"
        )
        engine = self._app.mutation_engine
        if engine is not None and track.name in engine.registered_tracks:
            if engine.record_manual_version(track.name):
                message = base
            else:
                message = f"{base} — без изменений (уже в этой версии)"
        else:
            message = (
                f"{base}\n"
                "note: version not recorded (mutation disabled or track "
                "not registered)"
            )
        return EngineResult.ok(message, track=track.name)

    def track_names(self) -> list[str]:
        """Имена дорожек прямо из сессии (снапшот приложения вне запуска пуст)."""
        session = self._app.session
        return session.track_names() if session is not None else []

    # ------------------------------------------------------------------
    # Degrees / voicing / inversion / profile (C1–C4)
    # ------------------------------------------------------------------

    def _pitched_track(self, name: str) -> MelodicTrack | EngineResult:
        """Мелодическая дорожка, которая играет ноты (не cc_only), или ошибка."""
        track = self._melodic_track(name)
        if isinstance(track, EngineResult):
            return track
        if track.profile.cc_only:
            return EngineResult.fail(f"track {name!r} is cc_only and has no notes")
        return track

    def set_track_degrees(self, name: str, degrees: Sequence[int]) -> EngineResult:
        """Задать прогрессию ступеней (C1). Ошибка — ``EngineResult.fail``."""
        track = self._pitched_track(name)
        if isinstance(track, EngineResult):
            return track
        try:
            track.degrees = list(degrees)
        except (ValueError, TypeError) as exc:
            return EngineResult.fail(f"track {name!r}: {exc}")
        if track.pending_degrees is None:
            text = f'track "{name}": degrees = {format_degrees(track.degrees)}'
        else:
            text = (
                f'track "{name}": degrees queued = '
                f"{format_degrees(track.pending_degrees)} (applies after the current step)"
            )
        return EngineResult.ok(text, degrees=list(track.degrees))

    def set_track_voicing(self, name: str, voicing: str) -> EngineResult:
        """Задать voicing (C2). Неизвестное имя — ``EngineResult.fail``."""
        track = self._pitched_track(name)
        if isinstance(track, EngineResult):
            return track
        try:
            track.voicing = voicing
        except ValueError as exc:  # HarmonyError наследует ValueError
            return EngineResult.fail(f"track {name!r}: {exc}")
        return EngineResult.ok(f'track "{name}": voicing = {track.voicing}')

    def track_routes(self) -> dict[tuple[str, int], str]:
        """Карта (порт, канал) → дорожка из сессии (снапшот вне запуска пуст)."""
        session = self._app.session
        if session is None:
            return {}
        routes: dict[tuple[str, int], str] = {}
        for track in session.ordered_tracks():
            port = getattr(track, "port", None)
            if port:
                routes.setdefault((port, int(track.channel)), track.name)
        return routes

    def midi_trace(self, n: int) -> list[object]:
        """Последние ``n`` исходящих событий (включая отброшенные)."""
        transport = self._app.transport
        trace = transport.trace if transport is not None else None
        return list(trace.recent(n)) if trace is not None else []

    def set_midi_trace(self, enabled: bool) -> EngineResult:
        """Включить/выключить запись исходящего MIDI для команды ``midi``."""
        transport = self._app.transport
        if transport is None:
            return EngineResult.fail("transport not available (sync.enabled=false)")
        if enabled:
            if transport.trace is None:
                transport.enable_trace()
            return EngineResult.ok("midi trace enabled")
        transport.disable_trace()
        return EngineResult.ok("midi trace disabled")

    def clear_midi_trace(self) -> EngineResult:
        """Очистить буфер исходящих событий."""
        transport = self._app.transport
        trace = transport.trace if transport is not None else None
        if trace is None:
            return EngineResult.fail("midi trace is off")
        trace.clear()
        return EngineResult.ok("midi trace cleared")

    def set_track_octave(self, name: str, octave: int) -> EngineResult:
        """Задать октаву (E8 на GEN, ``track octave`` в REPL). Диапазон 0..MAX_OCTAVE."""
        track = self._pitched_track(name)
        if isinstance(track, EngineResult):
            return track
        if not 0 <= octave <= MAX_OCTAVE:
            return EngineResult.fail(
                f"track {name!r}: octave must be 0..{MAX_OCTAVE}, got {octave}"
            )
        track.octave = octave
        return EngineResult.ok(f'track "{name}": octave = {octave}')

    def set_track_inversion(self, name: str, k: int) -> EngineResult:
        """Задать обращение (C3). ``k`` вне ``0..len(voicing)-1`` — ошибка."""
        track = self._pitched_track(name)
        if isinstance(track, EngineResult):
            return track
        try:
            track.inversion = k
        except (ValueError, TypeError) as exc:
            return EngineResult.fail(f"track {name!r}: {exc}")
        return EngineResult.ok(f'track "{name}": inversion = {track.inversion}')

    def set_track_profile(self, name: str, profile_name: str) -> EngineResult:
        """Сменить профиль (C4).

        Смена семьи внутри «нот» (pad ↔ lead и т. п.) не требует пересборки:
        ``generate_notes`` читает ``track.profile`` на каждом вызове, а
        ``MutationEngine`` подтягивает механизм по ``revision`` на следующем тике.

        Переход между cc_only и нотами запрещён: для нотной дорожки
        ``MelodicEngine`` создаётся только при старте, поэтому дорожка осталась бы
        без движка (или с лишним). Нужен перезапуск.
        """
        track = self._melodic_track(name)
        if isinstance(track, EngineResult):
            return track
        if profile_name not in PROFILES:
            return EngineResult.fail(
                f"track {name!r}: unknown profile {profile_name!r}"
            )
        if PROFILES[profile_name].cc_only != track.profile.cc_only:
            return EngineResult.fail(
                f"track {name!r}: switching between cc_only and note profiles "
                "needs a restart (no MelodicEngine for this track)"
            )
        old = track.profile_name
        try:
            track.set_profile(profile_name)
        except ValueError as exc:
            return EngineResult.fail(f"track {name!r}: {exc}")
        return EngineResult.ok(f'track "{name}": profile {old} -> {profile_name}')

    def set_track_muted(self, name: str, muted: bool) -> EngineResult:
        """Заглушить/разглушить дорожку (§4.6).

        Дорожка продолжает генерировать и мутировать — глушится только
        доставка, поэтому снятие mute возвращает её в такт.
        """
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        track = session.get_track(name)
        if track is None:
            return EngineResult.fail(f"track {name!r} not found")
        track.muted = bool(muted)
        state = "muted" if track.muted else "unmuted"
        return EngineResult.ok(f'track "{name}": {state}')

    # ------------------------------------------------------------------
    # Захват SMF (add-capture-smf design §5–§6)
    # ------------------------------------------------------------------

    def _capture_bpm_now(self) -> float:
        """BPM на момент старта захвата: клок, иначе fallback-рантайм."""
        clock_manager = self._app.clock_manager
        clock_bpm = clock_manager.state.bpm if clock_manager is not None else None
        return clock_bpm if clock_bpm is not None else self._app.sync_bpm

    def _generate_capture_path(self) -> Path:
        """Свободное имя ``captures/capture_YYYYmmdd_HHMMSS[_NN].mid``.

        Коллизия внутри той же секунды разрешается суффиксом ``_01.._99``
        — автогенерация выбирает свободное имя, перезаписи нет (design §6).
        Все имена секунды заняты — ``OSError`` наружу.
        """
        Path(CAPTURE_DIR).mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(CAPTURE_DIR) / f"capture_{stamp}.mid"
        if not base.exists():
            return base
        for suffix in range(1, 100):
            candidate = Path(CAPTURE_DIR) / f"capture_{stamp}_{suffix:02d}.mid"
            if not candidate.exists():
                return candidate
        raise OSError(f"no free capture name in {CAPTURE_DIR!r} for {stamp}")

    def capture_start(self, path: str | None) -> EngineResult:
        """Начать запись доставленных note-событий в SMF (design §6).

        Аргументы:
            path: Явный путь файла или ``None`` — автогенерация в каталоге
                ``captures/``. Существующий файл — ошибка (ранний фейл),
                перезапись запрещена.

        Returns:
            Подтверждение с путём и BPM (data ``{"path": ...}``) или
            человекочитаемая ошибка.
        """
        transport = self._app.transport
        if transport is None:
            return EngineResult.fail("transport not available (sync.enabled=false)")
        if self._capture_recorder is not None:
            return EngineResult.fail("capture already running — stop it first")
        if path is None:
            try:
                target = self._generate_capture_path()
            except OSError as exc:
                return EngineResult.fail(f"{exc}")
        else:
            target = Path(path)
            if target.exists():
                return EngineResult.fail(f"file exists: {target}")
        bpm = self._capture_bpm_now()
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        self._capture_recorder = recorder
        self._capture_path = target
        self._capture_bpm = bpm
        return EngineResult.ok(
            f"capture started → {target} (bpm {bpm:g})", path=str(target)
        )

    def capture_stop(self) -> EngineResult:
        """Остановить захват и записать SMF-файл (design §2, §6).

        Sink снимается до записи (транспортный поток отвязан), снимок
        накопителя пишется в REPL-потоке. Ошибка записи — fail без
        потери диагностики.
        """
        recorder = self._capture_recorder
        target = self._capture_path
        bpm = self._capture_bpm
        if recorder is None or target is None:
            return EngineResult.fail("capture is not active")
        transport = self._app.transport
        if transport is not None:
            transport.set_capture_sink(None)
        entries = recorder.entries()
        self._capture_recorder = None
        self._capture_path = None
        self._capture_bpm = None
        try:
            SmfWriter().write(target, entries, bpm=bpm if bpm is not None else 120.0)
        except (FileExistsError, OSError) as exc:
            return EngineResult.fail(f"capture write failed: {exc}")
        return EngineResult.ok(
            f"capture stopped: {target} ({len(entries)} note events)",
            path=str(target),
            events=len(entries),
        )

    def capture_status(self) -> EngineResult:
        """Статус захвата: путь, BPM старта, счётчик событий (design §6)."""
        recorder = self._capture_recorder
        if recorder is None or self._capture_path is None:
            return EngineResult.ok("capture is not active")
        bpm = self._capture_bpm if self._capture_bpm is not None else 0.0
        return EngineResult.ok(
            f"capture running: {self._capture_path} "
            f"(bpm {bpm:g}, {len(recorder)} events)",
            path=str(self._capture_path),
        )
