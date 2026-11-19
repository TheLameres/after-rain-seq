"""Интеграция захвата: очередь → Transport → AppEngineControl → SMF (tasks 7.1).

Реальный Transport с прикреплённым recorder (как в App), доставка
note-событий двух «дорожек» (каналы 0 и 9), стоп через фасад на мок-App,
файл читается mido. Файл — в tmp_path.
"""

from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import mido
import pytest

from src.app import engine_control as engine_control_module
from src.app.engine_control import AppEngineControl
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport import Transport
from src.sync.transport_event import TransportEvent


class MockApp:
    """Дублер AppPorts (как в test_engine_control_capture.py)."""

    def __init__(self, transport: Transport | None) -> None:
        self.transport = transport
        self.clock_manager = SimpleNamespace(
            state=SimpleNamespace(bpm=120.0, running=True)
        )
        self._sync_bpm_value = 120.0

    @property
    def sync_bpm(self) -> float:
        return self._sync_bpm_value


def _make_app_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AppEngineControl, Transport, queue.Queue[TransportEvent]]:
    """Фасад на мок-App с реальным Transport; CAPTURE_DIR — в tmp_path."""
    registry = MagicMock()
    adapter = MagicMock()
    adapter.label = "Synth A"
    registry.get_output.return_value = adapter
    registry.all_outputs.return_value = [adapter]
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=100)
    transport = Transport(
        event_queue=q,
        port_registry=registry,
        swing=SwingApplier(SwingConfig(amount=0.0)),
    )
    app = MockApp(transport)
    monkeypatch.setattr(
        engine_control_module, "CAPTURE_DIR", str(tmp_path / "captures")
    )
    return AppEngineControl(app), transport, q  # type: ignore[arg-type]


def _notes(mid: mido.MidiFile) -> list[tuple[int, str, int, int]]:
    """(абсолютный тик, вид, канал, нота) всех note-сообщений."""
    result: list[tuple[int, str, int, int]] = []
    tick = 0
    for msg in mid.tracks[0]:
        tick += msg.time
        if msg.type in ("note_on", "note_off"):
            result.append((tick, msg.type, msg.channel, msg.note))
    return result


class TestCaptureIntegration:
    """Полный фасад-путь: доставка → накопитель → SMF-файл."""

    def test_two_tracks_delivered_and_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, transport, q = _make_app_control(tmp_path, monkeypatch)
        target = tmp_path / "integ.mid"
        started = ctl.capture_start(str(target))
        assert not started.error

        # «дорожка 1» — каналы 0 (melodic), «дорожка 2» — канал 9 (drum);
        # CC между нотами транспорт доставляет, но в файл он не попадает
        events = [
            TransportEvent.note_on(
                "Synth A", channel=0, note=60, velocity=90, beat=0.0
            ),
            TransportEvent.control_change(
                "Synth A", channel=0, control=74, value=64, beat=0.0
            ),
            TransportEvent.note_on(
                "Synth A", channel=9, note=36, velocity=120, beat=0.0
            ),
            TransportEvent.note_off("Synth A", channel=0, note=60, beat=0.5),
            TransportEvent.note_off("Synth A", channel=9, note=36, beat=0.25),
            TransportEvent.note_on(
                "Synth A", channel=9, note=38, velocity=100, beat=1.0
            ),
            TransportEvent.note_off("Synth A", channel=9, note=38, beat=1.25),
        ]
        for event in events:
            q.put(event)
        transport.process_events(current_beat=2.0)

        stopped = ctl.capture_stop()
        assert not stopped.error
        assert "6 note events" in stopped.message

        mid = mido.MidiFile(target)
        notes = _notes(mid)
        # note-события в порядке файла, CC отсутствует
        assert notes == [
            (0, "note_on", 0, 60),
            (0, "note_on", 9, 36),
            (120, "note_off", 9, 36),
            (240, "note_off", 0, 60),
            (480, "note_on", 9, 38),
            (600, "note_off", 9, 38),
        ]
        assert all(msg.type != "control_change" for msg in mid.tracks[0])
        # меты на месте
        types = {msg.type for msg in mid.tracks[0]}
        assert {"track_name", "set_tempo", "time_signature"} <= types
        assert mid.type == 0
        assert mid.ticks_per_beat == 480

    def test_events_before_start_not_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Доставка до capture_start не попадает в файл."""
        ctl, transport, q = _make_app_control(tmp_path, monkeypatch)
        q.put(
            TransportEvent.note_on("Synth A", channel=0, note=50, velocity=80, beat=0.0)
        )
        transport.process_events(current_beat=1.0)
        target = tmp_path / "integ.mid"
        assert ctl.capture_start(str(target)).error is False
        q.put(
            TransportEvent.note_on("Synth A", channel=0, note=60, velocity=90, beat=1.0)
        )
        transport.process_events(current_beat=2.0)
        assert ctl.capture_stop().error is False
        notes = _notes(mido.MidiFile(target))
        assert notes == [(480, "note_on", 0, 60)]
