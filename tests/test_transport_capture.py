"""Tests for Transport capture sink — точка захвата SMF (tasks 3.2).

Sink пишется только для доставленных note_on/note_off с эффективным
битом: немедленные — ``event.beat``, отложенные свингом — ``deliver_at``
(design add-capture-smf §1). CC и ALL_NOTES_OFF не пишутся; событие без
порта не пишется (trace-семантика не тронута).
"""

from __future__ import annotations

import queue
import threading
from unittest.mock import MagicMock

import pytest

from src.sync.capture_recorder import CaptureRecorder
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport import Transport
from src.sync.transport_event import EventKind, TransportEvent


def _make_registry() -> MagicMock:
    """Мок PortRegistry с одним адаптером (порт найден)."""
    registry = MagicMock()
    adapter = MagicMock()
    adapter.label = "Synth A"
    registry.get_output.return_value = adapter
    registry.all_outputs.return_value = [adapter]
    return registry


def _make_transport(
    swing_amount: float = 0.0,
    registry: MagicMock | None = None,
) -> tuple[Transport, queue.Queue[TransportEvent], MagicMock]:
    """Transport с мок-реестром (как в test_transport.py)."""
    if registry is None:
        registry = _make_registry()
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=100)
    swing = SwingApplier(SwingConfig(amount=swing_amount))
    transport = Transport(event_queue=q, port_registry=registry, swing=swing)
    return transport, q, registry


class TestCaptureSinkRecording:
    """Состав потока: note-события пишутся, остальное — нет."""

    def test_note_on_off_recorded_with_channel_and_velocity(self) -> None:
        transport, q, _ = _make_transport()
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=2, note=60, velocity=100, beat=1.0
            )
        )
        q.put(TransportEvent.note_off("Synth A", channel=2, note=60, beat=2.0))
        transport.process_events(current_beat=2.0)
        entries = recorder.entries()
        assert len(entries) == 2
        assert entries[0].kind is EventKind.NOTE_ON
        assert entries[0].channel == 2
        assert entries[0].note == 60
        assert entries[0].velocity == 100
        assert entries[0].beat == 1.0
        assert entries[1].kind is EventKind.NOTE_OFF
        assert entries[1].velocity is None

    def test_cc_and_all_notes_off_not_recorded(self) -> None:
        transport, q, _ = _make_transport()
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        q.put(TransportEvent.control_change("Synth A", channel=0, control=74, value=64))
        q.put(TransportEvent.all_notes_off("Synth A"))
        transport.process_events(current_beat=0.0)
        assert len(recorder) == 0

    def test_missing_port_not_recorded(self) -> None:
        """Событие без порта отбрасывается и не пишется (design §1)."""
        registry = _make_registry()
        registry.get_output.return_value = None
        transport, q, _ = _make_transport(registry=registry)
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        q.put(
            TransportEvent.note_on(
                "Missing", channel=0, note=60, velocity=100, beat=0.0
            )
        )
        transport.process_events(current_beat=0.0)
        assert len(recorder) == 0

    def test_no_sink_no_error(self) -> None:
        """Без sink доставка работает как раньше."""
        transport, q, registry = _make_transport()
        q.put(TransportEvent.note_on("Synth A", channel=0, note=60, velocity=100))
        assert transport.process_events(current_beat=0.0) == 1
        registry.get_output.return_value.note_on.assert_called_once()


class TestCaptureEffectiveBeat:
    """Эффективный бит: немедленные — event.beat, свинг — deliver_at."""

    def test_immediate_note_uses_event_beat(self) -> None:
        transport, q, _ = _make_transport()
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        # чётный 1/8-шаг — свинг не откладывает
        q.put(
            TransportEvent.note_on(
                "Synth A",
                channel=0,
                note=60,
                velocity=100,
                duration=0.5,
                beat=0.0,
            )
        )
        transport.process_events(current_beat=0.0)
        assert recorder.entries()[0].beat == 0.0

    def test_swing_delayed_note_uses_deliver_at(self) -> None:
        transport, q, registry = _make_transport(swing_amount=0.5)
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        # beat 0.5 → нечётный шаг → отложен на +0.125 бита
        q.put(
            TransportEvent.note_on(
                "Synth A",
                channel=0,
                note=62,
                velocity=100,
                duration=0.5,
                beat=0.5,
            )
        )
        transport.process_events(current_beat=0.5)
        assert len(recorder) == 0  # ещё held
        transport.process_events(current_beat=0.625)
        registry.get_output.return_value.note_on.assert_called_once()
        assert len(recorder) == 1
        # deliver_at = 0.5 + сдвиг 0.125 (нечётный 1/8-шаг, amount 0.5)
        assert recorder.entries()[0].beat == pytest.approx(0.625)

    def test_note_off_swing_free_uses_event_beat(self) -> None:
        transport, q, _ = _make_transport(swing_amount=0.5)
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        q.put(TransportEvent.note_off("Synth A", channel=0, note=62, beat=0.5))
        transport.process_events(current_beat=0.5)
        assert recorder.entries()[0].beat == 0.5


class TestSinkSwap:
    """Атомарная замена ссылки: старт/стоп из другого потока."""

    def test_sink_removal_stops_recording(self) -> None:
        transport, q, _ = _make_transport()
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=60, velocity=100, beat=0.0
            )
        )
        transport.process_events(current_beat=0.0)
        transport.set_capture_sink(None)
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=61, velocity=100, beat=1.0
            )
        )
        transport.process_events(current_beat=1.0)
        assert len(recorder) == 1
        assert recorder.entries()[0].note == 60
        assert transport.capture_sink is None

    def test_stop_from_another_thread_no_deadlock(self) -> None:
        """Стоп из стороннего потока во время доставки — без дедлока."""
        transport, q, _ = _make_transport()
        recorder = CaptureRecorder()
        transport.set_capture_sink(recorder)
        for i in range(50):
            q.put(
                TransportEvent.note_on(
                    "Synth A",
                    channel=0,
                    note=60 + (i % 12),
                    velocity=100,
                    beat=i * 0.25,
                )
            )
        errors: list[Exception] = []

        def stopper() -> None:
            try:
                transport.set_capture_sink(None)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=stopper)
        thread.start()
        while not q.empty():
            transport.process_events(current_beat=100.0)
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert errors == []
        # recorder остаётся валидным снимком
        for entry in recorder.entries():
            assert entry.kind is EventKind.NOTE_ON
