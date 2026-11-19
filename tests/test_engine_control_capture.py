"""Tests for capture facade — AppEngineControl capture_* (tasks 4.4).

App не запускается: мок ``AppPorts`` с реальным Transport (мок-реестр) и
лёгким clock_manager-дублёром. ``CAPTURE_DIR`` monkeypatch-ится в
tmp_path. Минимальный контроль (без override) проверяет дефолтный fail
ABC (прецедент test_engine_control_drum_pattern.py).
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
from src.core.engine_result import EngineResult
from src.repl.engine_control import EngineControl
from src.repl.status import StatusSnapshot, TrackSummary
from src.sync.capture_recorder import CaptureRecorder
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport import Transport
from src.sync.transport_event import TransportEvent


class MockApp:
    """Дублер AppPorts: transport + clock_manager + sync_bpm."""

    def __init__(self, transport: Transport | None) -> None:
        self.transport = transport
        self.clock_manager = SimpleNamespace(
            state=SimpleNamespace(bpm=None, running=False)
        )
        self._sync_bpm_value = 120.0

    @property
    def sync_bpm(self) -> float:
        return self._sync_bpm_value


def _make_transport() -> tuple[Transport, queue.Queue[TransportEvent]]:
    """Transport с мок-реестром (как в test_transport.py)."""
    registry = MagicMock()
    adapter = MagicMock()
    adapter.label = "Synth A"
    registry.get_output.return_value = adapter
    registry.all_outputs.return_value = [adapter]
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=100)
    swing = SwingApplier(SwingConfig(amount=0.0))
    return Transport(event_queue=q, port_registry=registry, swing=swing), q


def make_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bpm_clock: float | None = None
) -> tuple[AppEngineControl, MockApp, Transport, queue.Queue[TransportEvent]]:
    """Фасад на мок-App с CAPTURE_DIR в tmp_path."""
    transport, q = _make_transport()
    app = MockApp(transport)
    if bpm_clock is not None:
        app.clock_manager.state.bpm = bpm_clock
    monkeypatch.setattr(
        engine_control_module, "CAPTURE_DIR", str(tmp_path / "captures")
    )
    return AppEngineControl(app), app, transport, q  # type: ignore[arg-type]


class MinimalControl(EngineControl):
    """Мок без override capture_* — проверка дефолтного fail ABC."""

    def get_status(self) -> StatusSnapshot:
        return StatusSnapshot(
            running=False,
            bpm=120.0,
            swing=0.0,
            clock_source="internal",
            clock_pending=None,
            clock_error=None,
            link_active=False,
            link_peers=0,
            root="A",
            scale="dorian",
            tracks=(),
            total_mutations=0,
            ports=(),
            log_error=None,
        )

    def get_logs(self, n: int) -> list[str]:
        return []

    def start_transport(self) -> EngineResult:
        return EngineResult.ok("start ok")

    def stop_transport(self) -> EngineResult:
        return EngineResult.ok("stop ok")

    def set_bpm(self, bpm: float) -> EngineResult:
        return EngineResult.ok("bpm ok")

    def set_swing(self, amount: float) -> EngineResult:
        return EngineResult.ok("swing ok")

    def request_clock_source(self, source: str) -> EngineResult:
        return EngineResult.ok("clock ok")

    def rescan_ports(self) -> EngineResult:
        return EngineResult.ok("rescan ok")

    def switch_port(self, label: str, match: str) -> EngineResult:
        return EngineResult.ok("switch ok")

    def set_root(self, root: str) -> EngineResult:
        return EngineResult.ok("root ok")

    def set_scale(self, name: str) -> EngineResult:
        return EngineResult.ok("scale ok")

    def list_tracks(self) -> list[TrackSummary]:
        return []

    def create_track(
        self, profile: str, channel: int | None = None, name: str | None = None
    ) -> EngineResult:
        return EngineResult.ok("create ok")

    def set_track_channel(self, name: str, channel: int) -> EngineResult:
        return EngineResult.ok("channel ok")

    def remove_track(self, name: str) -> EngineResult:
        return EngineResult.ok("remove ok")

    def route_track(self, name: str, label: str) -> EngineResult:
        return EngineResult.ok("route ok")

    def unroute_track(self, name: str) -> EngineResult:
        return EngineResult.ok("unroute ok")

    def create_drum_track(self, name: str | None = None) -> EngineResult:
        return EngineResult.ok("drum ok")

    def set_track_sources(self, name: str, *sources: str) -> EngineResult:
        return EngineResult.ok("sources ok")

    def set_track_gate(self, name: str, gate: float) -> EngineResult:
        return EngineResult.ok("gate ok")

    def set_track_density(self, name: str, density: float) -> EngineResult:
        return EngineResult.ok("density ok")

    def request_mutation(self, name: str | None = None) -> EngineResult:
        return EngineResult.ok("evolve ok")

    def undo_mutation(self, name: str) -> EngineResult:
        return EngineResult.ok("undo ok")

    def recall_version(self, name: str, index: int) -> EngineResult:
        return EngineResult.ok("recall ok")

    def mutation_history(self, name: str) -> EngineResult:
        return EngineResult.ok("history ok")


class TestCaptureHappyPath:
    """Старт → статус → доставка → стоп → файл."""

    def test_full_cycle_autogenerated_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, transport, q = make_control(tmp_path, monkeypatch)
        started = ctl.capture_start(None)
        assert not started.error
        data_path = started.data["path"]
        assert isinstance(data_path, str)
        assert data_path.startswith(str(tmp_path / "captures"))
        assert data_path.endswith(".mid")
        assert "capture_" in data_path
        assert (tmp_path / "captures").is_dir()

        status = ctl.capture_status()
        assert not status.error
        assert "capture running" in status.message

        q.put(
            TransportEvent.note_on(
                "Synth A", channel=9, note=36, velocity=120, beat=0.0
            )
        )
        transport.process_events(current_beat=1.0)

        stopped = ctl.capture_stop()
        assert not stopped.error
        assert "1 note events" in stopped.message

    def test_explicit_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch)
        target = tmp_path / "take1.mid"
        started = ctl.capture_start(str(target))
        assert not started.error
        assert str(target) in started.message
        assert ctl.capture_stop().error is False
        assert target.exists()

    def test_stop_writes_valid_smf(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, transport, q = make_control(tmp_path, monkeypatch)
        target = tmp_path / "cap.mid"
        assert ctl.capture_start(str(target)).error is False
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=60, velocity=100, beat=1.0
            )
        )
        transport.process_events(current_beat=2.0)
        assert ctl.capture_stop().error is False
        mid = mido.MidiFile(target)
        notes = [m for m in mid.tracks[0] if m.type in ("note_on", "note_off")]
        assert len(notes) == 1
        assert notes[0].note == 60

    def test_tempo_meta_uses_clock_bpm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch, bpm_clock=96.0)
        target = tmp_path / "cap.mid"
        assert ctl.capture_start(str(target)).error is False
        assert ctl.capture_stop().error is False
        mid = mido.MidiFile(target)
        tempos = [m.tempo for m in mid.tracks[0] if m.type == "set_tempo"]
        assert tempos == [mido.bpm2tempo(96.0)]

    def test_tempo_meta_falls_back_to_sync_bpm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """clock bpm None → fallback sync_bpm (design §5)."""
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch, bpm_clock=None)
        target = tmp_path / "cap.mid"
        assert ctl.capture_start(str(target)).error is False
        assert ctl.capture_stop().error is False
        mid = mido.MidiFile(target)
        tempos = [m.tempo for m in mid.tracks[0] if m.type == "set_tempo"]
        assert tempos == [mido.bpm2tempo(120.0)]

    def test_start_with_stopped_transport_ok_and_empty_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Старт при стоящем транспорте разрешён; файл пуст по нотам."""
        ctl, app, _transport, _q = make_control(tmp_path, monkeypatch)
        app.clock_manager.state.running = False
        target = tmp_path / "cap.mid"
        started = ctl.capture_start(str(target))
        assert not started.error
        stopped = ctl.capture_stop()
        assert not stopped.error
        assert "0 note events" in stopped.message
        notes = [
            m
            for m in mido.MidiFile(target).tracks[0]
            if m.type in ("note_on", "note_off")
        ]
        assert notes == []

    def test_capture_start_reports_bpm_in_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch, bpm_clock=132.0)
        started = ctl.capture_start(None)
        assert not started.error
        assert "bpm 132" in started.message


class TestCaptureErrors:
    """Ошибки старта/стопа — EngineResult.fail без исключений."""

    def test_transport_unavailable(self) -> None:
        app = MockApp(None)
        ctl = AppEngineControl(app)  # type: ignore[arg-type]
        result = ctl.capture_start(None)
        assert result.error
        assert "transport" in result.message

    def test_already_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch)
        assert ctl.capture_start(None).error is False
        again = ctl.capture_start(None)
        assert again.error
        assert "capture already running" in again.message
        # активный захват продолжается: статус показывает путь
        status = ctl.capture_status()
        assert status.error is False
        assert "running" in status.message
        assert ctl.capture_stop().error is False

    def test_stop_without_capture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch)
        result = ctl.capture_stop()
        assert result.error
        assert "capture is not active" in result.message

    def test_explicit_path_exists_fails_early(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch)
        existing = tmp_path / "exists.mid"
        existing.write_bytes(b"x")
        result = ctl.capture_start(str(existing))
        assert result.error
        assert "file exists" in result.message
        # ранний фейл: захват не начат
        assert ctl.capture_status().message == "capture is not active"

    def test_status_without_capture_is_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch)
        result = ctl.capture_status()
        assert not result.error
        assert result.message == "capture is not active"

    def test_stop_write_error_becomes_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Файл появился между стартом и стопом → fail, не перезапись."""
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch)
        target = tmp_path / "cap.mid"
        assert ctl.capture_start(str(target)).error is False
        target.write_bytes(b"sneaky")
        result = ctl.capture_stop()
        assert result.error
        assert "capture write failed" in result.message
        assert target.read_bytes() == b"sneaky"

    def test_capture_dir_collision_gets_suffix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, _transport, _q = make_control(tmp_path, monkeypatch)
        first = ctl.capture_start(None)
        assert not first.error
        first_path = first.data["path"]
        assert isinstance(first_path, str)
        assert ctl.capture_stop().error is False
        assert Path(first_path).exists()
        # второй старт: имя первой записи занято → свободное имя (суффикс _NN
        # при той же секунде, новое имя при смене секунды)
        second = ctl.capture_start(None)
        assert not second.error
        second_path = second.data["path"]
        assert isinstance(second_path, str)
        assert second_path != first_path


class TestDefaultStub:
    def test_minimal_control_returns_default_fail(self) -> None:
        ctl = MinimalControl()
        for result in (
            ctl.capture_start(None),
            ctl.capture_start("x.mid"),
            ctl.capture_stop(),
            ctl.capture_status(),
        ):
            assert result.error
            assert result.message == "capture is not supported by this control"


class TestCaptureRecorderSanity:
    """Смоук: recorder прикрепляется и снимается через фасад."""

    def test_sink_detached_after_stop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctl, _app, transport, _q = make_control(tmp_path, monkeypatch)
        assert ctl.capture_start(None).error is False
        assert isinstance(transport.capture_sink, CaptureRecorder)
        assert ctl.capture_stop().error is False
        assert transport.capture_sink is None
