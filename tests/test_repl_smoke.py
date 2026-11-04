"""Smoke-тесты Repl через create_pipe_input + DummyOutput.

Весь Repl прогоняется в потоке: команды пишутся в pipe-stdin, вывод
собирается через echo-колбэк. Проверяются: исполнение команд, EOF →
on_eof (app.stop()), exit-команда, история.
"""

from __future__ import annotations

import threading

from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from src.core.engine_result import EngineResult
from src.repl.confirm import ConfirmPolicy
from src.repl.engine_control import EngineControl
from src.repl.repl import Repl
from src.repl.status import StatusSnapshot, TrackSummary


class StubControl(EngineControl):
    """Минимальный стаб EngineControl для smoke."""

    def get_status(self) -> StatusSnapshot:
        return StatusSnapshot(
            running=True,
            bpm=118.0,
            swing=0.0,
            clock_source="internal",
            clock_pending=None,
            clock_error=None,
            link_active=False,
            link_peers=0,
            root="F#",
            scale="aeolian",
            tracks=(
                TrackSummary(
                    name="Pad 1",
                    kind="melodic",
                    profile="pad",
                    sources=(),
                    mutation_count=0,
                ),
            ),
            total_mutations=0,
            ports=(),
            log_error=None,
        )

    def get_logs(self, n: int) -> list[str]:
        return ["smoke-log-line"]

    def start_transport(self) -> EngineResult:
        return EngineResult.ok("transport started")

    def stop_transport(self) -> EngineResult:
        return EngineResult.ok("transport stopped")

    def set_bpm(self, bpm: float) -> EngineResult:
        return EngineResult.ok(f"bpm set to {bpm:.1f}")

    def set_swing(self, amount: float) -> EngineResult:
        return EngineResult.ok(f"swing set to {amount:.2f}")

    def request_clock_source(self, source: str) -> EngineResult:
        return EngineResult.ok(f"switched to {source} on next beat")

    def rescan_ports(self) -> EngineResult:
        return EngineResult.ok("scan complete: no changes")

    def switch_port(self, label: str, match: str) -> EngineResult:
        return EngineResult.ok(f"switch scheduled: {label!r} → match {match!r}")

    def set_root(self, root: str) -> EngineResult:
        return EngineResult.ok(f"root set to {root}")

    def set_scale(self, name: str) -> EngineResult:
        return EngineResult.ok(f"scale set to {name}")

    def list_tracks(self) -> list[TrackSummary]:
        return list(self.get_status().tracks)

    def create_track(self, profile: str, channel: int | None = None) -> EngineResult:
        return EngineResult.ok('created track "Pad 9"', track="Pad 9")

    def set_track_channel(self, name: str, channel: int) -> EngineResult:
        return EngineResult.ok(f'track "{name}": channel → {channel}')

    def remove_track(self, name: str) -> EngineResult:
        return EngineResult.ok(f'deleted track "{name}"')

    def route_track(self, name: str, label: str) -> EngineResult:
        return EngineResult.ok(f'track "{name}" → port "{label}"')

    def unroute_track(self, name: str) -> EngineResult:
        return EngineResult.ok(f'track "{name}" disconnected')

    def freeze(self, name: str | None = None) -> EngineResult:
        return EngineResult.ok("all tracks frozen")

    def evolve(self) -> EngineResult:
        return EngineResult.ok("all tracks evolved")

    def create_drum_track(self) -> EngineResult:
        return EngineResult.ok("created track", track="Pad 9")

    def set_track_sources(self, name: str, *sources: str) -> EngineResult:
        return EngineResult.ok("sources set")

    def set_track_gate(self, name: str, gate: float) -> EngineResult:
        return EngineResult.ok("gate set")

    def set_track_density(self, name: str, density: float) -> EngineResult:
        return EngineResult.ok("density set")

    def set_track_mutate(self, name: str, mutate: float) -> EngineResult:
        return EngineResult.ok("mutate set")

    def evolve_track(self, name: str) -> EngineResult:
        return EngineResult.ok("evolved")


def run_repl(
    tmp_path, text: str, on_eof, *, close_input: bool = False
) -> tuple[list[str], list[str]]:
    """Прогнать Repl на тексте в pipe. Вернуть (echoed, eof_calls).

    Аргументы:
        close_input: Закрыть pipe после отправки текста — prompt получит
            EOF (путь Ctrl+D / обрыва SSH).
    """
    outputs: list[str] = []
    eof_calls: list[str] = []
    with create_pipe_input() as inp:
        repl = Repl(
            StubControl(),
            history_path=tmp_path / "repl_history",
            policy=ConfirmPolicy.ALWAYS,
            on_eof=lambda: eof_calls.append("eof"),
            input=inp,
            output=DummyOutput(),
            echo=outputs.append,
            color=False,
        )
        inp.send_text(text)
        if close_input:
            inp.close()
        thread = threading.Thread(target=repl.run, daemon=True)
        thread.start()
        thread.join(timeout=10)
        assert not thread.is_alive(), "REPL thread did not finish"
    return outputs, eof_calls


def joined(outputs: list[str]) -> str:
    return "\n".join(outputs)


class TestSmoke:
    def test_commands_execute_and_echo(self, tmp_path):
        outputs, _ = run_repl(
            tmp_path, "status\nbpm 128\ntracks\nfreeze\nlogs\nexit\n", lambda: None
        )
        text = joined(outputs)
        assert "root: F#" in text
        assert "scale: aeolian" in text
        assert "bpm set to 128.0" in text
        assert "Pad 1" in text
        assert "all tracks frozen" in text
        assert "smoke-log-line" in text

    def test_exit_calls_on_eof(self, tmp_path):
        _, eof_calls = run_repl(tmp_path, "exit\n", None)
        assert eof_calls == ["eof"]

    def test_eof_calls_on_eof(self, tmp_path):
        """Ctrl+D (EOF из pipe) → on_eof, поток завершается."""
        outputs, eof_calls = run_repl(tmp_path, "status\n", None, close_input=True)
        # После закрытия pipe prompt получает EOF
        assert eof_calls == ["eof"]
        assert "root: F#" in joined(outputs)

    def test_unknown_command_does_not_crash_loop(self, tmp_path):
        outputs, eof_calls = run_repl(tmp_path, "bogus\nexit\n", None)
        assert "unknown command" in joined(outputs)
        assert eof_calls == ["eof"]

    def test_history_written(self, tmp_path):
        run_repl(tmp_path, "status\nbpm 128\nexit\n", None)
        history = tmp_path / "repl_history"
        assert history.exists()
        content = history.read_text(encoding="utf-8")
        assert "bpm 128" in content

    def test_repl_stop_unblocks_prompt(self, tmp_path):
        """stop() из другого потока завершает цикл (для SIGTERM-пути)."""
        outputs: list[str] = []
        with create_pipe_input() as inp:
            repl = Repl(
                StubControl(),
                history_path=tmp_path / "repl_history",
                policy=ConfirmPolicy.ALWAYS,
                input=inp,
                output=DummyOutput(),
                echo=outputs.append,
                color=False,
            )
            thread = threading.Thread(target=repl.run, daemon=True)
            thread.start()
            # Дать циклу стартануть и дать prompt
            import time

            time.sleep(0.5)
            repl.stop()
            thread.join(timeout=5)
            assert not thread.is_alive(), "stop() did not unblock REPL thread"


class TestToolbarRegression:
    """Регресс: ANSI-коды не должны уходить в bottom_toolbar plain-строкой."""

    def _make_repl(self, tmp_path, color):
        return Repl(
            StubControl(),
            history_path=tmp_path / "repl_history",
            policy=ConfirmPolicy.ALWAYS,
            echo=lambda _t: None,
            color=color,
        )

    def test_toolbar_returns_ansi_object_when_color_on(self, tmp_path):
        """color=True → ANSI (escape-коды распарсятся в стили), не plain str."""
        from prompt_toolkit.formatted_text import ANSI

        repl = self._make_repl(tmp_path, color=True)
        toolbar = repl._toolbar()
        assert isinstance(toolbar, ANSI)
        assert not isinstance(toolbar, str)

    def test_toolbar_returns_plain_str_when_color_off(self, tmp_path):
        """color=False → чистый ASCII без escape-кодов."""
        repl = self._make_repl(tmp_path, color=False)
        toolbar = repl._toolbar()
        assert isinstance(toolbar, str)
        assert "\x1b" not in toolbar
