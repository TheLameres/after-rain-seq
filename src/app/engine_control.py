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
from typing import Protocol

from src.core.engine_result import EngineResult
from src.harmony.degree_names import format_degrees
from src.harmony.harmony import Harmony, HarmonyError
from src.repl.engine_control import EngineControl
from src.repl.log_buffer import LogBuffer
from src.repl.status import StatusSnapshot, TrackSummary
from src.session.model.drum_track import DrumTrack
from src.session.model.melodic_profile import PROFILES
from src.session.model.melodic_track import MAX_OCTAVE, MelodicTrack
from src.session.session import Session
from src.sync.clock_manager import ClockManager
from src.sync.clock_source import ClockSource
from src.sync.ports import PortManager
from src.sync.routing import PortRegistry
from src.sync.swing import SwingApplier
from src.sync.transport import Transport

log = logging.getLogger(__name__)


class AppPorts(Protocol):
    """Что фасаду команд нужно от приложения: ровно те 12 членов, что он читает.

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

    def set_sync_bpm(self, value: float) -> None: ...
    def route_track(self, name: str, label: str) -> EngineResult: ...
    def unroute_track(self, name: str) -> EngineResult: ...
    def drop_track(self, name: str) -> EngineResult: ...


# Диапазон BPM (совпадает с валидацией SyncConfig).
MIN_BPM: float = 20.0
MAX_BPM: float = 300.0


class AppEngineControl(EngineControl):
    """Мост между REPL и App: реализует контракт EngineControl.

    Параметры:
        app: Запущенное приложение (через read-only свойства).
        log_buffer: Кольцевой буфер логов (``logs``/``log_error``).
    """

    def __init__(self, app: AppPorts, log_buffer: LogBuffer | None = None) -> None:
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

    def create_track(self, profile: str, channel: int | None = None) -> EngineResult:
        """Создать melodic-дорожку профиля (лимиты — текстом).

        Канал: ``None`` — автоназначение первого свободного (без слипания
        с другими дорожками на порту); иначе явный 0..15.
        Дорожка сразу привязывается к первому настроенному выходу.
        """
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        if profile not in PROFILES:
            known = ", ".join(sorted(PROFILES))
            return EngineResult.fail(f"unknown profile {profile!r} (choose: {known})")
        try:
            track = session.create_melodic_track(profile, channel=channel)
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

    def freeze(self, name: str | None = None) -> EngineResult:
        """Заморозить все дорожки или одну по имени."""
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        if name is None:
            session.freeze_all()
            return EngineResult.ok("all tracks frozen")
        track = session.get_track(name)
        if track is None:
            return EngineResult.fail(f"track {name!r} not found")
        if not isinstance(track, (MelodicTrack, DrumTrack)):
            return EngineResult.fail(f"cannot freeze track {name!r}")
        track.freeze()  # MelodicTrack: mutate=0; DrumTrack: базовый паттерн
        return EngineResult.ok(f'froze track "{name}"')

    def evolve(self) -> EngineResult:
        """Разморозить и продолжить эволюцию."""
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        session.evolve_all()
        return EngineResult.ok("all tracks evolved")

    # ------------------------------------------------------------------
    # Сессия — расширения D2 (экраны TRACK/TRACKS)
    # ------------------------------------------------------------------

    def create_drum_track(self) -> EngineResult:
        """Создать drum-дорожку (лимит 2 — текстом из ValueError)."""
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        try:
            track = session.create_drum_track()
        except ValueError as exc:
            return EngineResult.fail(f"{exc}")
        self._route_new_track(track.name)
        port = track.port or "—"
        return EngineResult.ok(
            f'created track "{track.name}" (drum, ch {track.channel}, port {port})',
            track=track.name,
        )

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
        return EngineResult.ok(f'track "{name}": sources = {joined}')

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

    def set_track_mutate(self, name: str, mutate: float) -> EngineResult:
        """Установить вероятность мутации (0.0–1.0, макро-ось MUT)."""
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        track = session.get_track(name)
        if track is None:
            return EngineResult.fail(f"track {name!r} not found")
        if not isinstance(track, (MelodicTrack, DrumTrack)):
            return EngineResult.fail(f"track {name!r} is not mutable")
        if not 0.0 <= mutate <= 1.0:
            return EngineResult.fail(f"mutate must be 0..1, got {mutate}")
        track.mutate = float(mutate)
        return EngineResult.ok(f'track "{name}": mutate = {mutate:.2f}')

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

    def evolve_track(self, name: str) -> EngineResult:
        """Разморозить одну дорожку (MelodicTrack: mutate=0.5, DrumTrack: 0.5)."""
        session = self._app.session
        if session is None:
            return EngineResult.fail("session not available")
        track = session.get_track(name)
        if track is None:
            return EngineResult.fail(f"track {name!r} not found")
        if not isinstance(track, (MelodicTrack, DrumTrack)):
            return EngineResult.fail(f"cannot evolve track {name!r}")
        track.mutate = 0.5
        return EngineResult.ok(f'evolved track "{name}"')
