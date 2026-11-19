"""Интеграционный тест dispatch-хука: reset drum-движков на START/STOP.

По образцу hook-тестов tests/test_midi_clock_in.py: App с drum-дорожкой
(ручная сборка), события прокси диспетчатся вручную (воркер остановлен).
STOP → drum_engines[*].scheduler.pending_count == 0 и инициализация
сброшена; повторный START → события начинаются с нулевой фазы таймлайна.
Доставка проверяется через CaptureRecorder (transport.process_events
вычищает очередь на каждом тике).
"""

from __future__ import annotations

import queue
from unittest.mock import MagicMock

import pytest

from src.app.application import App
from src.session.drum.drum_engine import DrumEngine
from src.session.model.drum_track import DrumTrack
from src.session.session import Session
from src.sync.capture_recorder import CaptureRecorder
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.tick_proxy import TickEvent
from src.sync.transport_event import EventKind, TransportEvent


class _Reg:
    """Мок-реестр портов: один адаптер, события никуда не уходят."""

    def __init__(self) -> None:
        self.adapter = MagicMock()

    def all_outputs(self) -> list[MagicMock]:
        return [self.adapter]

    def flush_all(self) -> None:
        return None

    def get_output(self, label: str) -> MagicMock:
        return self.adapter


class _Cfg:
    enabled = True
    clock_source = "internal"
    midi_clock_device = None
    bpm = 120.0
    swing_amount = 0.0


def _app_with_drum() -> tuple[
    App, DrumEngine, DrumTrack, queue.Queue[TransportEvent], CaptureRecorder
]:
    """App с хуком тиков и одной drum-дорожкой (kick на бите 0 цикла)."""
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    app._port_registry = _Reg()  # type: ignore[assignment]
    app._swing_applier = SwingApplier(SwingConfig(amount=0.0))
    event_queue: queue.Queue[TransportEvent] = queue.Queue(maxsize=4096)
    app._event_queue = event_queue
    app._init_clock_manager(_Cfg())
    recorder = CaptureRecorder()
    app._transport.set_capture_sink(recorder)
    proxy = app._tick_proxy
    proxy.stop_worker()
    while not proxy._queue.empty():  # type: ignore[attr-defined]
        proxy._queue.get_nowait()  # type: ignore[attr-defined]

    track = app._session.create_drum_track(name="Drums")
    track.lanes[0].pattern[0] = 1  # kick на бите 0 цикла
    engine = DrumEngine(
        drum_track=track,
        event_queue=event_queue,
        port_label="main",
    )
    app._drum_engines.append(engine)
    return app, engine, track, event_queue, recorder


def _run_ticks(proxy: object, n: int) -> None:
    """Прогнать n тиков вручную (воркер остановлен)."""
    proxy_dispatch = proxy._dispatch  # type: ignore[attr-defined]
    for _ in range(n):
        proxy_dispatch(TickEvent.TICK)


class TestDrumEngineStartStopHook:
    """START/STOP хука сбрасывают drum-движки (задача 2.1)."""

    def test_stop_clears_drum_scheduler(self) -> None:
        """STOP → pending_count == 0 и инициализация сброшена."""
        _app, engine, _track, _q, _recorder = _app_with_drum()
        proxy = _app._tick_proxy
        proxy._dispatch(TickEvent.START)
        _run_ticks(proxy, 33)  # 33/480 бита — окно построено
        assert engine.scheduler.initialized
        assert engine.scheduler.pending_count > 0

        proxy._dispatch(TickEvent.STOP)
        assert engine.scheduler.pending_count == 0
        assert not engine.scheduler.initialized

    def test_restart_starts_from_zero_phase(self) -> None:
        """Повторный START → события начинаются с нулевой фазы таймлайна."""
        _app, engine, _track, _q, recorder = _app_with_drum()
        proxy = _app._tick_proxy
        proxy._dispatch(TickEvent.START)
        _run_ticks(proxy, 33)
        proxy._dispatch(TickEvent.STOP)
        proxy._dispatch(TickEvent.START)
        # Первый тик после START: kick на бите 0, без «доигрывания прошлого».
        proxy._dispatch(TickEvent.TICK)
        ons = [
            e
            for e in recorder.entries()
            if e.kind is EventKind.NOTE_ON and e.note == 36
        ]
        assert len(ons) == 1
        assert ons[0].beat == pytest.approx(0.0)
        assert engine.scheduler.pending_count > 0

    def test_ticks_deliver_once_per_beat(self) -> None:
        """Луп тиков через хук: нет дублирования удара на тик (регресс брифа)."""
        _app, _engine, _track, _q, recorder = _app_with_drum()
        proxy = _app._tick_proxy
        proxy._dispatch(TickEvent.START)
        # 2 такта при 480 PPQN: каждый тик 1/480 бита.
        _run_ticks(proxy, 2 * 4 * 480)
        ons = [
            e
            for e in recorder.entries()
            if e.kind is EventKind.NOTE_ON and e.note == 36
        ]
        offs = [
            e
            for e in recorder.entries()
            if e.kind is EventKind.NOTE_OFF and e.note == 36
        ]
        # Kick на бите 0 каждого цикла: ровно 2 note_on за 2 такта.
        assert [e.beat for e in ons] == pytest.approx([0.0, 4.0])
        # Каждому note_on соответствует note_off на +0.25.
        assert [e.beat for e in offs] == pytest.approx([0.25, 4.25])
