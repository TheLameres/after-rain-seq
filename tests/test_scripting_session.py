"""Tests for ScriptSession — фасад над EngineControl ABC (план G2 §3.7)."""

from __future__ import annotations

import logging

import pytest

from src.core.engine_result import EngineResult
from src.core.proposal import DrumProposal, TrackProposal
from src.repl.engine_control import EngineControl
from src.repl.status import StatusSnapshot, TrackSummary
from src.scripting.error import ScriptError
from src.scripting.script_session import ScriptSession


class MockControl(EngineControl):
    """Стаб EngineControl: записи вызовов + настраиваемые ответы.

    Паттерн ``tests/test_repl_executor.py``. ``fail_on`` — имя метода,
    который вернёт ``EngineResult.fail``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.fail_on: str | None = None

    def _rec(self, method: str, *args: object) -> EngineResult:
        self.calls.append((method, args))
        if self.fail_on == method:
            return EngineResult.fail(f"{method} failed")
        return EngineResult.ok(f"{method} ok", track="Track 1")

    # ------------------------------------------------------------------
    # Мониторинг
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Транспорт и клок
    # ------------------------------------------------------------------

    def start_transport(self) -> EngineResult:
        return self._rec("start_transport")

    def stop_transport(self) -> EngineResult:
        return self._rec("stop_transport")

    def set_bpm(self, bpm: float) -> EngineResult:
        return self._rec("set_bpm", bpm)

    def set_swing(self, amount: float) -> EngineResult:
        return self._rec("set_swing", amount)

    def request_clock_source(self, source: str) -> EngineResult:
        return self._rec("request_clock_source", source)

    # ------------------------------------------------------------------
    # Порты
    # ------------------------------------------------------------------

    def rescan_ports(self) -> EngineResult:
        return self._rec("rescan_ports")

    def switch_port(self, label: str, match: str) -> EngineResult:
        return self._rec("switch_port", label, match)

    # ------------------------------------------------------------------
    # Гармония
    # ------------------------------------------------------------------

    def set_root(self, root: str) -> EngineResult:
        return self._rec("set_root", root)

    def set_scale(self, name: str) -> EngineResult:
        return self._rec("set_scale", name)

    # ------------------------------------------------------------------
    # Сессия
    # ------------------------------------------------------------------

    def list_tracks(self) -> list[TrackSummary]:
        return []

    def create_track(
        self, profile: str, channel: int | None = None, name: str | None = None
    ) -> EngineResult:
        return self._rec("create_track", profile, channel, name)

    def set_track_channel(self, name: str, channel: int) -> EngineResult:
        return self._rec("set_track_channel", name, channel)

    def remove_track(self, name: str) -> EngineResult:
        return self._rec("remove_track", name)

    def route_track(self, name: str, label: str) -> EngineResult:
        return self._rec("route_track", name, label)

    def unroute_track(self, name: str) -> EngineResult:
        return self._rec("unroute_track", name)

    def create_drum_track(self, name: str | None = None) -> EngineResult:
        return self._rec("create_drum_track", name)

    def set_track_sources(self, name: str, *sources: str) -> EngineResult:
        return self._rec("set_track_sources", name, *sources)

    def set_track_gate(self, name: str, gate: float) -> EngineResult:
        return self._rec("set_track_gate", name, gate)

    def set_track_density(self, name: str, density: float) -> EngineResult:
        return self._rec("set_track_density", name, density)

    def set_drum_pattern(self, name: str, lane: str, pattern: str) -> EngineResult:
        return self._rec("set_drum_pattern", name, lane, pattern)

    def set_track_degrees(self, name: str, degrees: object) -> EngineResult:
        return self._rec("set_track_degrees", name, tuple(degrees))  # type: ignore[arg-type]

    def set_track_voicing(self, name: str, voicing: str) -> EngineResult:
        return self._rec("set_track_voicing", name, voicing)

    def set_track_octave(self, name: str, octave: int) -> EngineResult:
        return self._rec("set_track_octave", name, octave)

    def set_track_inversion(self, name: str, k: int) -> EngineResult:
        return self._rec("set_track_inversion", name, k)

    def set_track_profile(self, name: str, profile_name: str) -> EngineResult:
        return self._rec("set_track_profile", name, profile_name)

    def request_mutation(self, name: str | None = None) -> EngineResult:
        return self._rec("request_mutation", name)

    def undo_mutation(self, name: str) -> EngineResult:
        return self._rec("undo_mutation", name)

    def recall_version(self, name: str, index: int) -> EngineResult:
        return self._rec("recall_version", name, index)

    def mutation_history(self, name: str) -> EngineResult:
        return self._rec("mutation_history", name)

    def capture_start(self, path: str | None) -> EngineResult:
        return self._rec("capture_start", path)

    def capture_stop(self) -> EngineResult:
        return self._rec("capture_stop")


@pytest.fixture
def control() -> MockControl:
    return MockControl()


@pytest.fixture
def session(control: MockControl) -> ScriptSession:
    return ScriptSession(control)


# ---------------------------------------------------------------------------
# add_track / add_drum — раскладка proposal
# ---------------------------------------------------------------------------


class TestAddTrack:
    """Цепочка create_track → voicing → degrees."""

    def test_full_chain(self, session: ScriptSession, control: MockControl) -> None:
        proposal = TrackProposal(
            profile_name="atmos",
            voicing="1-3-5-7",
            degrees=(6, 5, 4),
        )
        result = session.add_track(proposal)
        assert not result.error
        assert control.calls == [
            ("create_track", ("atmos", None, None)),
            ("set_track_voicing", ("Track 1", "1-3-5-7")),
            ("set_track_degrees", ("Track 1", (6, 5, 4))),
        ]

    def test_track_name_taken_from_data(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        """Имя для шагов 2–3 — из ``result.data['track']``, не из proposal."""
        proposal = TrackProposal(profile_name="pad", voicing="1-3-5")
        session.add_track(proposal)
        assert ("set_track_voicing", ("Track 1", "1-3-5")) in control.calls

    def test_ignored_fields_skipped(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        """Без voicing/degrees — только create_track."""
        proposal = TrackProposal(profile_name="pad", channel=3, name="My Pad")
        session.add_track(proposal)
        assert control.calls == [("create_track", ("pad", 3, "My Pad"))]

    def test_create_fails_fatal(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        """Ошибка create_track при fatal → ScriptError, voicing не применяется."""
        control.fail_on = "create_track"
        with pytest.raises(ScriptError) as excinfo:
            session.add_track(TrackProposal(profile_name="pad", voicing="1-3-5"))
        assert "create_track failed" in str(excinfo.value)
        assert ("set_track_voicing",) not in [(c[0], c[1][:1]) for c in control.calls]

    def test_create_fails_non_fatal(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        """``fatal=False``: возвращён EngineResult, цепочка прервана."""
        control.fail_on = "create_track"
        result = session.add_track(
            TrackProposal(profile_name="pad", voicing="1-3-5"), fatal=False
        )
        assert result.error
        assert result.message == "create_track failed"
        assert control.calls == [("create_track", ("pad", None, None))]

    def test_voicing_fails_fatal(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        """Ошибка set_track_voicing при fatal → ScriptError."""
        control.fail_on = "set_track_voicing"
        with pytest.raises(ScriptError) as excinfo:
            session.add_track(TrackProposal(profile_name="pad", voicing="1-3-5"))
        assert "set_track_voicing failed" in str(excinfo.value)

    def test_voicing_fails_non_fatal(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        """``fatal=False``: ошибка voicing → EngineResult, degrees не задаются."""
        control.fail_on = "set_track_voicing"
        result = session.add_track(
            TrackProposal(profile_name="pad", voicing="1-3-5", degrees=(1, 3)),
            fatal=False,
        )
        assert result.error
        assert ("set_track_degrees", ("Track 1", (1, 3))) not in control.calls


class TestAddDrum:
    """``add_drum`` — примитив create_drum_track."""

    def test_named(self, session: ScriptSession, control: MockControl) -> None:
        result = session.add_drum(DrumProposal(name="Kick"))
        assert not result.error
        assert control.calls == [("create_drum_track", ("Kick",))]

    def test_nameless(self, session: ScriptSession, control: MockControl) -> None:
        session.add_drum(DrumProposal())
        assert control.calls == [("create_drum_track", (None,))]

    def test_fatal(self, session: ScriptSession, control: MockControl) -> None:
        control.fail_on = "create_drum_track"
        with pytest.raises(ScriptError):
            session.add_drum(DrumProposal())


# ---------------------------------------------------------------------------
# 1:1 обёртки
# ---------------------------------------------------------------------------


class TestWrappers:
    """Простые обёртки над примитивами ABC."""

    def test_start_and_stop(self, session: ScriptSession, control: MockControl) -> None:
        session.start()
        session.stop()
        assert [c[0] for c in control.calls] == ["start_transport", "stop_transport"]

    def test_transport_and_harmony(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        session.set_bpm(120)
        session.set_swing(0.25)
        session.request_clock_source("midi")
        session.set_root("A")
        session.set_scale("dorian")
        assert [c[0] for c in control.calls] == [
            "set_bpm",
            "set_swing",
            "request_clock_source",
            "set_root",
            "set_scale",
        ]

    def test_track_operations(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        session.set_track_channel("Pad 1", 3)
        session.route_track("Pad 1", "main")
        session.unroute_track("Pad 1")
        session.set_track_sources("Pad 1", "Atmos 1", "Sub 1")
        session.set_track_degrees("Pad 1", (1, 3, 5))
        session.set_track_voicing("Pad 1", "1-3-5")
        session.set_track_octave("Pad 1", 4)
        session.set_track_inversion("Pad 1", 1)
        session.set_track_profile("Pad 1", "stab")
        session.set_track_gate("Pad 1", 0.5)
        session.set_track_density("Pad 1", 0.7)
        assert [c[0] for c in control.calls] == [
            "set_track_channel",
            "route_track",
            "unroute_track",
            "set_track_sources",
            "set_track_degrees",
            "set_track_voicing",
            "set_track_octave",
            "set_track_inversion",
            "set_track_profile",
            "set_track_gate",
            "set_track_density",
        ]
        assert control.calls[3] == ("set_track_sources", ("Pad 1", "Atmos 1", "Sub 1"))

    def test_ports(self, session: ScriptSession, control: MockControl) -> None:
        session.rescan_ports()
        session.switch_port("main", "Bus One")
        assert [c[0] for c in control.calls] == ["rescan_ports", "switch_port"]

    def test_set_drum_pattern_passes_arguments(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        """Обёртка 1:1: аргументы прокидываются движку как есть."""
        result = session.set_drum_pattern("Drums", "kick", "x..x")
        assert not result.error
        assert control.calls == [("set_drum_pattern", ("Drums", "kick", "x..x"))]

    def test_set_drum_pattern_fatal_false(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        control.fail_on = "set_drum_pattern"
        result = session.set_drum_pattern("Drums", "kick", "x..x", fatal=False)
        assert result.error
        assert result.message == "set_drum_pattern failed"

    def test_set_drum_pattern_fatal_raises(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        control.fail_on = "set_drum_pattern"
        with pytest.raises(ScriptError) as excinfo:
            session.set_drum_pattern("Drums", "kick", "x..x")
        assert "set_drum_pattern failed" in str(excinfo.value)

    def test_all_return_engine_result(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        """Все методы возвращают ``EngineResult`` (без ``| None``)."""
        assert isinstance(session.start(), EngineResult)
        assert isinstance(session.set_bpm(120), EngineResult)
        assert isinstance(
            session.add_track(TrackProposal(profile_name="pad")), EngineResult
        )


class TestFatal:
    """``fatal`` решает «бросить или вернуть»."""

    def test_error_raises_script_error(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        control.fail_on = "set_bpm"
        with pytest.raises(ScriptError) as excinfo:
            session.set_bpm(120)
        assert excinfo.value.args[0] == "set_bpm failed"

    def test_error_returns_engine_result(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        control.fail_on = "set_bpm"
        result = session.set_bpm(120, fatal=False)
        assert isinstance(result, EngineResult)
        assert result.error
        assert result.message == "set_bpm failed"

    def test_success_always_returns(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        assert session.set_bpm(120).message == "set_bpm ok"


class TestDestructiveAutoConfirm:
    """Деструктивные операции — авто-confirm с записью в лог."""

    def test_stop_auto_confirmed(
        self,
        session: ScriptSession,
        control: MockControl,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="src.scripting.script_session"):
            session.stop()
        assert ("stop_transport", ()) in control.calls
        assert any(
            "auto-confirmed destructive stop" in r.message for r in caplog.records
        )

    def test_remove_track_auto_confirmed(
        self,
        session: ScriptSession,
        control: MockControl,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="src.scripting.script_session"):
            session.remove_track("Pad 1")
        assert ("remove_track", ("Pad 1",)) in control.calls
        assert any(
            "auto-confirmed destructive remove_track" in r.message
            for r in caplog.records
        )

    def test_non_destructive_not_logged(
        self,
        session: ScriptSession,
        control: MockControl,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="src.scripting.script_session"):
            session.set_bpm(120)
        assert not any("auto-confirmed" in r.message for r in caplog.records)


class TestCapture:
    """``capture_start``/``capture_stop`` — обёртки 1:1 (add-capture-smf 6.2)."""

    def test_start_without_path(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        result = session.capture_start()
        assert not result.error
        assert control.calls == [("capture_start", (None,))]

    def test_start_with_explicit_path(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        result = session.capture_start("takes/take1.mid")
        assert not result.error
        assert control.calls == [("capture_start", ("takes/take1.mid",))]

    def test_stop(self, session: ScriptSession, control: MockControl) -> None:
        result = session.capture_stop()
        assert not result.error
        assert control.calls == [("capture_stop", ())]

    def test_error_fatal_raises(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        control.fail_on = "capture_start"
        with pytest.raises(ScriptError) as excinfo:
            session.capture_start("x.mid")
        assert "capture_start failed" in str(excinfo.value)

    def test_error_non_fatal_returns_result(
        self, session: ScriptSession, control: MockControl
    ) -> None:
        control.fail_on = "capture_stop"
        result = session.capture_stop(fatal=False)
        assert isinstance(result, EngineResult)
        assert result.error
        assert result.message == "capture_stop failed"
