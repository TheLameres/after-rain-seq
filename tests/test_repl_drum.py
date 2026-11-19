"""REPL-команды домена ``drum`` — parser/executor/completer (блок 5 tasks).

Парсинг по образцу test_repl_parser.py, executor — по test_repl_executor.py
(мок-контроль с записью вызовов), completer — динамические контексты
``drum pattern``.
"""

from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from src.core.engine_result import EngineResult
from src.repl.completer import ReplCompleter
from src.repl.executor import CommandExecutor
from src.repl.parser import CommandParser
from tests.test_repl_executor import MockControl


class DrumMockControl(MockControl):
    """Мок с записью ``set_drum_pattern`` (в базовом моке — дефолт ABC)."""

    def set_drum_pattern(self, name: str, lane: str, pattern: str) -> EngineResult:
        self.calls.append(("set_drum_pattern", (name, lane, pattern)))
        if self.error_on == "set_drum_pattern":
            return EngineResult.fail("set_drum_pattern failed")
        return EngineResult.ok(f'track "{name}": lane {lane}: pattern set')


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParserDrumAdd:
    def test_no_name(self) -> None:
        cmd = CommandParser().parse("drum add")
        assert cmd.error is None
        assert cmd.name == "drum add"
        assert cmd.args == ()

    def test_quoted_name(self) -> None:
        cmd = CommandParser().parse('drum add "Big Drums"')
        assert cmd.error is None
        assert cmd.args == ("Big Drums",)

    def test_unquoted_name_joins(self) -> None:
        cmd = CommandParser().parse("drum add Big Drums")
        assert cmd.error is None
        assert cmd.args == ("Big Drums",)

    def test_case_insensitive(self) -> None:
        cmd = CommandParser().parse("DRUM ADD Drums")
        assert cmd.error is None
        assert cmd.args == ("Drums",)


class TestParserDrumPattern:
    def test_notation_single_token(self) -> None:
        cmd = CommandParser().parse("drum pattern Drums kick x..x")
        assert cmd.error is None
        assert cmd.name == "drum pattern"
        assert cmd.args == ("Drums", "kick", "x..x")

    def test_quoted_track_and_euclid(self) -> None:
        cmd = CommandParser().parse('drum pattern "My Drums" 38 (3,8,1)')
        assert cmd.error is None
        assert cmd.args == ("My Drums", "38", "(3,8,1)")

    def test_notation_with_spaces_and_bars(self) -> None:
        cmd = CommandParser().parse("drum pattern Drums kick x..x|.... ....")
        assert cmd.error is None
        assert cmd.args == ("Drums", "kick", "x..x|....", "....")

    def test_two_args_clear_lane(self) -> None:
        cmd = CommandParser().parse("drum pattern Drums kick")
        assert cmd.error is None
        assert cmd.args == ("Drums", "kick")

    def test_one_arg_is_arity_error(self) -> None:
        cmd = CommandParser().parse("drum pattern Drums")
        assert cmd.error is not None
        assert "expected 2" in cmd.error

    def test_drum_without_action(self) -> None:
        cmd = CommandParser().parse("drum")
        assert cmd.error is not None
        assert "missing action" in cmd.error

    def test_unknown_action(self) -> None:
        cmd = CommandParser().parse("drum mute Drums")
        assert cmd.error is not None
        assert "unknown action" in cmd.error


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class TestExecutorDrum:
    def test_drum_add_without_name(self) -> None:
        control = DrumMockControl()
        result = CommandExecutor(control).execute("drum add")
        assert result.code == 0
        assert ("create_drum_track", (None,)) in control.calls

    def test_drum_add_with_name(self) -> None:
        control = DrumMockControl()
        CommandExecutor(control).execute('drum add "Big Drums"')
        assert ("create_drum_track", ("Big Drums",)) in control.calls

    def test_drum_pattern_calls_facade(self) -> None:
        control = DrumMockControl()
        result = CommandExecutor(control).execute("drum pattern Drums kick x..x")
        assert result.code == 0
        assert ("set_drum_pattern", ("Drums", "kick", "x..x")) in control.calls

    def test_drum_pattern_joins_notation_tokens(self) -> None:
        control = DrumMockControl()
        CommandExecutor(control).execute("drum pattern Drums kick x..x|.... ....")
        assert (
            "set_drum_pattern",
            ("Drums", "kick", "x..x|.... ...."),
        ) in control.calls

    def test_drum_pattern_two_args_clears(self) -> None:
        control = DrumMockControl()
        CommandExecutor(control).execute("drum pattern Drums kick")
        assert ("set_drum_pattern", ("Drums", "kick", "")) in control.calls

    def test_engine_error_is_code_1_loop_lives(self) -> None:
        """Ошибка установки → CommandResult(code=1), executor готов к следующей."""
        control = DrumMockControl()
        control.error_on = "set_drum_pattern"
        executor = CommandExecutor(control)
        result = executor.execute("drum pattern Nope kick x..x")
        assert result.code == 1
        # Цикл живёт: следующая команда исполняется.
        follow = executor.execute("drum add")
        assert follow.code == 0


# ---------------------------------------------------------------------------
# Completer
# ---------------------------------------------------------------------------

LANE_NAMES = ("Kick", "Rimshot", "Snare", "ClosedHat", "Shaker", "Conga")


def _completions(completer: ReplCompleter, text: str) -> list[str]:
    """Тексты подсказок для строки ввода."""
    doc = Document(text, len(text))
    return [c.text for c in completer.get_completions(doc, CompleteEvent())]


class TestCompleterDrum:
    def test_drum_domain_offers_actions(self) -> None:
        control = MockControl()
        completer = ReplCompleter(control)
        texts = _completions(completer, "drum ")
        assert "add" in texts
        assert "pattern" in texts

    def test_after_pattern_offers_track_names(self) -> None:
        control = MockControl()
        completer = ReplCompleter(control)
        texts = _completions(completer, "drum pattern Dr")
        assert "Drum 1" in texts

    def test_lane_provider_offers_lane_names(self) -> None:
        control = MockControl()
        completer = ReplCompleter(control, providers={"lane": lambda: LANE_NAMES})
        texts = _completions(completer, "drum pattern Drums ki")
        assert "Kick" in texts
        assert "Snare" not in texts

    def test_missing_lane_provider_gives_empty(self) -> None:
        control = MockControl()
        completer = ReplCompleter(control)
        assert _completions(completer, "drum pattern Drums ki") == []
