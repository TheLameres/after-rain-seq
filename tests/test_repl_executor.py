"""Tests for CommandExecutor — мок EngineControl: команды, коды, confirm."""

from __future__ import annotations

import pytest

from src.core.engine_result import EngineResult
from src.repl.confirm import ConfirmPolicy
from src.repl.engine_control import EngineControl
from src.repl.executor import CommandExecutor
from src.repl.status import StatusSnapshot, TrackSummary


class MockControl(EngineControl):
    """Стаб EngineControl с записью вызовов."""

    def __init__(self) -> None:
        self.bpm: float = 120.0
        self.calls: list[tuple[str, tuple]] = []
        self.transport_running = True
        self.error_on: str | None = None  # метод, который вернёт ошибку

    def get_status(self) -> StatusSnapshot:
        return StatusSnapshot(
            running=self.transport_running,
            bpm=self.bpm,
            swing=0.25,
            clock_source="internal",
            clock_pending=None,
            clock_error=None,
            link_active=False,
            link_peers=0,
            root="A",
            scale="dorian",
            tracks=(
                TrackSummary(
                    name="Pad 1",
                    kind="melodic",
                    profile="pad",
                    sources=(),
                    mutation_count=3,
                    mutate=0.0,
                ),
                TrackSummary(
                    name="Drum 1",
                    kind="drum",
                    profile="drum",
                    sources=(),
                    mutation_count=7,
                    mutate=0.5,
                ),
            ),
            total_mutations=10,
            ports=(),
            log_error=None,
        )

    def get_logs(self, n: int) -> list[str]:
        self.calls.append(("get_logs", (n,)))
        return [f"line-{i}" for i in range(min(n, 5))]

    def start_transport(self) -> EngineResult:
        self.calls.append(("start_transport", ()))
        return EngineResult.ok("transport started")

    def stop_transport(self) -> EngineResult:
        self.calls.append(("stop_transport", ()))
        return EngineResult.ok("transport stopped")

    def set_bpm(self, bpm: float) -> EngineResult:
        if bpm < 20 or bpm > 300:
            return EngineResult.fail(f"bpm {bpm} out of range")
        self.bpm = bpm
        return EngineResult.ok(f"bpm set to {bpm:.1f}")

    def set_swing(self, amount: float) -> EngineResult:
        return EngineResult.ok(f"swing set to {amount:.2f}")

    def request_clock_source(self, source: str) -> EngineResult:
        self.calls.append(("request_clock_source", (source,)))
        if source == "link":
            return EngineResult.fail("Ableton Link not installed")
        return EngineResult.ok(f"switched to {source} on next beat")

    def rescan_ports(self) -> EngineResult:
        self.calls.append(("rescan_ports", ()))
        return EngineResult.ok("scan complete: no changes")

    def switch_port(self, label: str, match: str) -> EngineResult:
        self.calls.append(("switch_port", (label, match)))
        if label not in ("main", "keys"):
            return EngineResult.fail(f"unknown port label: {label!r}")
        return EngineResult.ok(f"switch scheduled: {label!r} → match {match!r}")

    def set_root(self, root: str) -> EngineResult:
        self.calls.append(("set_root", (root,)))
        return EngineResult.ok(f"root set to {root}")

    def set_scale(self, name: str) -> EngineResult:
        self.calls.append(("set_scale", (name,)))
        return EngineResult.ok(f"scale set to {name}")

    def list_tracks(self) -> list[TrackSummary]:
        return list(self.get_status().tracks)

    def create_track(self, profile: str, channel: int | None = None) -> EngineResult:
        if profile == "bogus":
            return EngineResult.fail("unknown profile")
        self.calls.append(("create_track", (profile, channel)))
        return EngineResult.ok('created track "Pad 9"', track="Pad 9")

    def set_track_channel(self, name: str, channel: int) -> EngineResult:
        self.calls.append(("set_track_channel", (name, channel)))
        return EngineResult.ok(f'track "{name}": channel 0 → {channel}')

    def remove_track(self, name: str) -> EngineResult:
        self.calls.append(("remove_track", (name,)))
        return EngineResult.ok(f'deleted track "{name}"')

    def route_track(self, name: str, label: str) -> EngineResult:
        self.calls.append(("route_track", (name, label)))
        return EngineResult.ok(f'track "{name}" → port "{label}" (was "default")')

    def unroute_track(self, name: str) -> EngineResult:
        self.calls.append(("unroute_track", (name,)))
        return EngineResult.ok(f'track "{name}" disconnected (was "main")')

    def freeze(self, name: str | None = None) -> EngineResult:
        self.calls.append(("freeze", (name,)))
        return EngineResult.ok("all tracks frozen" if name is None else f"froze {name}")

    def evolve(self) -> EngineResult:
        self.calls.append(("evolve", ()))
        return EngineResult.ok("all tracks evolved")

    def create_drum_track(self) -> EngineResult:
        return EngineResult.ok("created track", track="Pad 9")

    def set_track_sources(self, name: str, *sources: str) -> EngineResult:
        self.calls.append(("set_track_sources", (name, *sources)))
        return EngineResult.ok("sources set")

    def set_track_gate(self, name: str, gate: float) -> EngineResult:
        return EngineResult.ok("gate set")

    def set_track_density(self, name: str, density: float) -> EngineResult:
        self.calls.append(("set_track_density", (name, density)))
        return EngineResult.ok("density set")

    def set_track_mutate(self, name: str, mutate: float) -> EngineResult:
        self.calls.append(("set_track_mutate", (name, mutate)))
        return EngineResult.ok("mutate set")

    def evolve_track(self, name: str) -> EngineResult:
        return EngineResult.ok("evolved")


@pytest.fixture
def control() -> MockControl:
    return MockControl()


@pytest.fixture
def ex(control) -> CommandExecutor:
    return CommandExecutor(control)


class TestStatusCommands:
    """Команды мониторинга."""

    def test_status(self, ex):
        result = ex.execute("status")
        assert result.code == 0
        assert "120.0" in result.output
        assert "root: A" in result.output
        assert "scale: dorian" in result.output
        assert "Pad 1" in result.output

    def test_clock_status(self, ex):
        result = ex.execute("clock")
        assert result.code == 0
        assert "internal" in result.output

    def test_tracks(self, ex):
        result = ex.execute("tracks")
        assert result.code == 0
        assert "Pad 1" in result.output
        assert "frozen" in result.output

    def test_track_show(self, ex):
        result = ex.execute("track show Pad 1")
        assert result.code == 0
        assert "profile: pad" in result.output
        assert "mutations: 3" in result.output

    def test_track_show_not_found(self, ex):
        result = ex.execute("track show Nope")
        assert result.code == 1
        assert "not found" in result.output

    def test_ports_empty_configured(self, ex):
        result = ex.execute("ports")
        assert result.code == 0

    def test_mutations(self, ex):
        result = ex.execute("mutations")
        assert result.code == 0
        assert "10" in result.output

    def test_logs_default(self, ex, control):
        result = ex.execute("logs")
        assert result.code == 0
        assert ("get_logs", (20,)) in control.calls

    def test_logs_n(self, ex, control):
        result = ex.execute("logs 3")
        assert result.code == 0
        assert ("get_logs", (3,)) in control.calls

    def test_logs_invalid_n(self, ex):
        assert ex.execute("logs abc").code == 1


class TestControlCommands:
    """Команды управления (не деструктивные)."""

    def test_bpm(self, ex, control):
        result = ex.execute("bpm 128")
        assert result.code == 0
        assert control.bpm == 128.0

    def test_bpm_not_a_number(self, ex):
        assert ex.execute("bpm abc").code == 1

    def test_bpm_engine_error(self, ex):
        result = ex.execute("bpm 999")
        assert result.code == 1
        assert result.output.startswith("error:")

    def test_clock_source_ok(self, ex, control):
        result = ex.execute("clock source midi")
        assert result.code == 0
        assert ("request_clock_source", ("midi",)) in control.calls

    def test_clock_source_engine_error(self, ex):
        result = ex.execute("clock source link")
        assert result.code == 1
        assert "Ableton Link" in result.output

    def test_ports_scan(self, ex, control):
        result = ex.execute("ports scan")
        assert result.code == 0
        assert ("rescan_ports", ()) in control.calls

    def test_ports_switch(self, ex, control):
        result = ex.execute('ports switch main "Bus Two"')
        assert result.code == 0
        assert ("switch_port", ("main", "Bus Two")) in control.calls
        assert "switch scheduled" in result.output

    def test_ports_switch_engine_error(self, ex):
        result = ex.execute("ports switch nope bus")
        assert result.code == 1
        assert "unknown port label" in result.output

    def test_ports_switch_requires_two_args(self, ex):
        result = ex.execute("ports switch main")
        assert result.code == 1
        assert "ports switch <label> <match>" in result.output

    def test_track_route(self, ex, control):
        result = ex.execute('track route "Pad 1" main')
        assert result.code == 0
        assert ("route_track", ("Pad 1", "main")) in control.calls
        assert 'port "main"' in result.output

    def test_track_route_requires_two_args(self, ex):
        result = ex.execute("track route Pad1")
        assert result.code == 1
        assert "track route <name> <label>" in result.output

    def test_track_unroute(self, ex, control):
        result = ex.execute("track unroute Pad1")
        assert result.code == 0
        assert ("unroute_track", ("Pad1",)) in control.calls
        assert "disconnected" in result.output

    def test_track_add(self, ex, control):
        result = ex.execute("track add pad")
        assert result.code == 0
        assert ("create_track", ("pad", None)) in control.calls

    def test_track_add_with_channel(self, ex, control):
        """Явный канал пробрасывается в движок."""
        result = ex.execute("track add pad 3")
        assert result.code == 0
        assert ("create_track", ("pad", 3)) in control.calls

    def test_track_add_bad_channel(self, ex, control):
        """Не-числовой канал — ошибка без вызова движка."""
        result = ex.execute("track add pad abc")
        assert result.code == 1
        assert "not a number" in result.output
        assert ("create_track", ("pad", None)) not in control.calls

    def test_track_channel(self, ex, control):
        """Смена канала дорожки в рантайме."""
        result = ex.execute("track channel Pad1 5")
        assert result.code == 0
        assert ("set_track_channel", ("Pad1", 5)) in control.calls

    def test_track_channel_bad_channel(self, ex, control):
        result = ex.execute("track channel Pad1 x")
        assert result.code == 1
        assert "not a number" in result.output

    def test_track_add_engine_error(self, ex):
        result = ex.execute("track add bogus")
        assert result.code == 1

    def test_root_scale(self, ex, control):
        assert ex.execute("root F#").code == 0
        assert ("set_root", ("F#",)) in control.calls
        assert ex.execute("scale aeolian").code == 0
        assert ("set_scale", ("aeolian",)) in control.calls

    def test_freeze_all(self, ex, control):
        result = ex.execute("freeze")
        assert result.code == 0
        assert ("freeze", (None,)) in control.calls

    def test_freeze_one(self, ex, control):
        result = ex.execute("freeze Pad 1")
        assert result.code == 0
        assert ("freeze", ("Pad 1",)) in control.calls

    def test_evolve(self, ex, control):
        result = ex.execute("evolve")
        assert result.code == 0
        assert ("evolve", ()) in control.calls

    def test_start(self, ex, control):
        result = ex.execute("start")
        assert result.code == 0
        assert ("start_transport", ()) in control.calls


class TestConfirmations:
    """Деструктивные команды: y/N, --yes, ALWAYS."""

    def test_stop_confirmed_with_yes_answer(self, control):
        answers = iter(["y"])
        ex = CommandExecutor(control, prompt=lambda _q: next(answers))
        result = ex.execute("stop")
        assert result.code == 0
        assert ("stop_transport", ()) in control.calls

    def test_stop_cancelled_with_empty_answer(self, control):
        ex = CommandExecutor(control, prompt=lambda _q: "")
        result = ex.execute("stop")
        assert result.code == 0
        assert result.output == "cancelled"
        assert ("stop_transport", ()) not in control.calls

    def test_stop_cancelled_with_no(self, control):
        ex = CommandExecutor(control, prompt=lambda _q: "no")
        result = ex.execute("stop")
        assert result.output == "cancelled"
        assert ("stop_transport", ()) not in control.calls

    def test_stop_flag_yes_skips_question(self, control):
        def boom(_q):
            raise AssertionError("question must not be asked")

        ex = CommandExecutor(control, prompt=boom)
        result = ex.execute("stop --yes")
        assert result.code == 0
        assert ("stop_transport", ()) in control.calls

    def test_policy_always_never_asks(self, control):
        def boom(_q):
            raise AssertionError("question must not be asked")

        ex = CommandExecutor(control, policy=ConfirmPolicy.ALWAYS, prompt=boom)
        assert ex.execute("stop").code == 0
        assert ("stop_transport", ()) in control.calls
        assert ex.execute("track delete Pad 1").code == 0
        assert ("remove_track", ("Pad 1",)) in control.calls

    def test_delete_confirmed(self, control):
        ex = CommandExecutor(control, prompt=lambda _q: "yes")
        result = ex.execute("track delete Pad 1")
        assert result.code == 0
        assert ("remove_track", ("Pad 1",)) in control.calls

    def test_delete_cancelled(self, control):
        ex = CommandExecutor(control, prompt=lambda _q: "n")
        result = ex.execute("track delete Drum 1")
        assert result.output == "cancelled"
        assert ("remove_track", ("Drum 1",)) not in control.calls


class TestErrorsAndExit:
    """Обработка ошибок, help, exit."""

    def test_unknown_command(self, ex):
        result = ex.execute("frobnicate")
        assert result.code == 1
        assert "unknown command" in result.output

    def test_syntax_error_shows_usage(self, ex):
        result = ex.execute("bpm")
        assert result.code == 1
        assert "usage: bpm" in result.output

    def test_engine_exception_becomes_error(self, control):
        def boom():
            raise RuntimeError("engine on fire")

        control.stop_transport = boom  # type: ignore[method-assign]
        ex = CommandExecutor(control, policy=ConfirmPolicy.ALWAYS)
        result = ex.execute("stop")
        assert result.code == 1
        assert "engine on fire" in result.output

    def test_help_lists(self, ex):
        result = ex.execute("help")
        assert result.code == 0
        assert "status" in result.output

    def test_help_command(self, ex):
        result = ex.execute("help bpm")
        assert result.code == 0

    def test_help_unknown(self, ex):
        assert ex.execute("help nope").code == 1

    def test_exit(self, ex):
        result = ex.execute("exit")
        assert result.exit is True

    def test_quit(self, ex):
        result = ex.execute("quit")
        assert result.exit is True

    def test_empty_line_noop(self, ex, control):
        result = ex.execute("")
        assert result.code == 0
        assert result.output == ""
        assert control.calls == []
