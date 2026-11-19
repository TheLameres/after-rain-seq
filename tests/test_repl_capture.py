"""REPL-команды домена ``capture`` — parser/executor/completer (tasks 5.3).

Парсинг по образцу test_repl_parser.py, executor — по test_repl_drum.py
(мок-контроль с записью вызовов), completer — статическое дерево.
"""

from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from src.core.engine_result import EngineResult
from src.repl.completer import ReplCompleter
from src.repl.executor import CommandExecutor
from src.repl.parser import CommandParser
from tests.test_repl_executor import MockControl


class CaptureMockControl(MockControl):
    """Мок с записью capture_* (в базовом моке — дефолт ABC)."""

    def capture_start(self, path: str | None) -> EngineResult:
        self.calls.append(("capture_start", (path,)))
        if self.error_on == "capture_start":
            return EngineResult.fail("file exists: x.mid")
        return EngineResult.ok(f"capture started → {path or 'auto'} (bpm 120)")

    def capture_stop(self) -> EngineResult:
        self.calls.append(("capture_stop", ()))
        if self.error_on == "capture_stop":
            return EngineResult.fail("capture is not active")
        return EngineResult.ok("capture stopped: x.mid (5 note events)")

    def capture_status(self) -> EngineResult:
        self.calls.append(("capture_status", ()))
        if self.error_on == "capture_status":
            return EngineResult.fail("capture_status failed")
        return EngineResult.ok("capture is not active")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParserCapture:
    def test_bare_is_status(self) -> None:
        cmd = CommandParser().parse("capture")
        assert cmd.error is None
        assert cmd.name == "capture"
        assert cmd.args == ()

    def test_start_without_path(self) -> None:
        cmd = CommandParser().parse("capture start")
        assert cmd.error is None
        assert cmd.name == "capture start"
        assert cmd.args == ()

    def test_start_with_path(self) -> None:
        cmd = CommandParser().parse("capture start takes/take1.mid")
        assert cmd.error is None
        assert cmd.name == "capture start"
        assert cmd.args == ("takes/take1.mid",)

    def test_start_quoted_path_with_spaces(self) -> None:
        cmd = CommandParser().parse('capture start "My Takes/take 1.mid"')
        assert cmd.error is None
        assert cmd.args == ("My Takes/take 1.mid",)

    def test_start_unquoted_path_with_spaces_joins(self) -> None:
        cmd = CommandParser().parse("capture start My Takes/take 1.mid")
        assert cmd.error is None
        assert cmd.args == ("My Takes/take 1.mid",)

    def test_stop(self) -> None:
        cmd = CommandParser().parse("capture stop")
        assert cmd.error is None
        assert cmd.name == "capture stop"
        assert cmd.args == ()

    def test_stop_with_argument_is_arity_error(self) -> None:
        cmd = CommandParser().parse("capture stop x")
        assert cmd.error is not None
        assert "argument" in cmd.error

    def test_start_too_many_args_is_arity_error(self) -> None:
        cmd = CommandParser().parse(
            "capture start " + " ".join(f"a{i}" for i in range(17))
        )
        assert cmd.error is not None
        assert "argument" in cmd.error

    def test_bare_with_extra_token_is_arity_error(self) -> None:
        """``capture foo`` — домен с bare: как ``clock foo``, ошибка арности."""
        cmd = CommandParser().parse("capture rewind")
        assert cmd.error is not None


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class TestExecutorCapture:
    def test_bare_calls_status(self) -> None:
        control = CaptureMockControl()
        result = CommandExecutor(control).execute("capture")
        assert result.code == 0
        assert ("capture_status", ()) in control.calls

    def test_start_without_path_passes_none(self) -> None:
        control = CaptureMockControl()
        result = CommandExecutor(control).execute("capture start")
        assert result.code == 0
        assert ("capture_start", (None,)) in control.calls
        assert "capture started" in result.output

    def test_start_with_path_passes_joined_string(self) -> None:
        control = CaptureMockControl()
        result = CommandExecutor(control).execute('capture start "My Takes/take 1.mid"')
        assert result.code == 0
        assert ("capture_start", ("My Takes/take 1.mid",)) in control.calls

    def test_stop_calls_facade(self) -> None:
        control = CaptureMockControl()
        result = CommandExecutor(control).execute("capture stop")
        assert result.code == 0
        assert ("capture_stop", ()) in control.calls

    def test_engine_error_gives_code_1_and_loop_lives(self) -> None:
        control = CaptureMockControl()
        control.error_on = "capture_stop"
        result = CommandExecutor(control).execute("capture stop")
        assert result.code == 1
        assert result.output.startswith("error:")
        # цикл живёт: следующая команда исполняется
        follow = CommandExecutor(control).execute("capture")
        assert follow.code == 0


# ---------------------------------------------------------------------------
# Completer
# ---------------------------------------------------------------------------


def _completions(completer: ReplCompleter, text: str) -> list[str]:
    """Тексты подсказок для строки ввода."""
    doc = Document(text, len(text))
    return [c.text for c in completer.get_completions(doc, CompleteEvent())]


class TestCompleterCapture:
    def test_capture_domain_offered(self) -> None:
        completer = ReplCompleter(CaptureMockControl())
        assert "capture" in _completions(completer, "cap")

    def test_actions_offered(self) -> None:
        completer = ReplCompleter(CaptureMockControl())
        texts = _completions(completer, "capture ")
        assert "start" in texts
        assert "stop" in texts

    def test_partial_action_prefix(self) -> None:
        completer = ReplCompleter(CaptureMockControl())
        texts = _completions(completer, "capture sta")
        assert "start" in texts
        assert "stop" not in texts
