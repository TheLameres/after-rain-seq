"""REPL: ``track chain`` — parser/executor/completer (блок 6 tasks).

Парсинг по образцу test_repl_track_sources.py, executor — мок-контроль
с записью вызовов (test_repl_executor.py) плюс реальная сессия,
completer — динамические контексты (test_repl_drum.py).
"""

from __future__ import annotations

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.core.engine_result import EngineResult
from src.repl.completer import ReplCompleter
from src.repl.executor import CommandExecutor
from src.repl.parser import CommandParser
from src.session.session import Session
from tests.test_repl_executor import MockControl


class ChainMockControl(MockControl):
    """Мок с записью ``track_chain_add`` (проверка передачи параметров)."""

    def track_chain(self, name: str) -> EngineResult:
        self.calls.append(("track_chain", (name,)))
        return EngineResult.ok(f'track "{name}": chain = — (empty)', chain=[])

    def track_chain_add(
        self, name: str, stage_name: str, params: dict[str, str]
    ) -> EngineResult:
        self.calls.append(("track_chain_add", (name, stage_name, params)))
        return EngineResult.ok(f'track "{name}": chain = {stage_name}', chain=[])

    def track_chain_remove(self, name: str, index: int) -> EngineResult:
        self.calls.append(("track_chain_remove", (name, index)))
        return EngineResult.ok(f'track "{name}": chain = — (empty)', chain=[])


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParsing:
    def test_show(self) -> None:
        cmd = CommandParser().parse('track chain "Pad 1" show')
        assert cmd.error is None
        assert cmd.name == "track chain"
        assert cmd.args == ("Pad 1", "show")

    def test_add_with_params(self) -> None:
        cmd = CommandParser().parse(
            'track chain "Pad 1" add arpeggiate step=0.25 direction=up'
        )
        assert cmd.error is None
        assert cmd.args == (
            "Pad 1",
            "add",
            "arpeggiate",
            "step=0.25",
            "direction=up",
        )

    def test_add_without_params(self) -> None:
        cmd = CommandParser().parse('track chain "Pad 1" add densify density=0.5')
        assert cmd.error is None
        assert cmd.args == ("Pad 1", "add", "densify", "density=0.5")

    def test_remove(self) -> None:
        cmd = CommandParser().parse('track chain "Pad 1" remove 2')
        assert cmd.error is None
        assert cmd.args == ("Pad 1", "remove", "2")

    def test_no_args_is_usage_error(self) -> None:
        cmd = CommandParser().parse("track chain")
        assert cmd.error is not None
        assert "2" in cmd.error

    def test_name_only_is_usage_error(self) -> None:
        cmd = CommandParser().parse('track chain "Pad 1"')
        assert cmd.error is not None

    def test_help_mentions_usage(self) -> None:
        text = CommandParser().help_text("track chain")
        assert "track chain" in text and "remove" in text


# ---------------------------------------------------------------------------
# Executor — мок-контроль
# ---------------------------------------------------------------------------


class TestExecutorCalls:
    def test_show_calls_facade(self) -> None:
        control = ChainMockControl()
        ex = CommandExecutor(control)
        res = ex.execute('track chain "Pad 1" show')
        assert res.code == 0
        assert control.calls == [("track_chain", ("Pad 1",))]

    def test_add_passes_params_as_strings(self) -> None:
        control = ChainMockControl()
        ex = CommandExecutor(control)
        res = ex.execute('track chain "Pad 1" add arpeggiate step=0.25 direction=up')
        assert res.code == 0
        assert control.calls == [
            (
                "track_chain_add",
                ("Pad 1", "arpeggiate", {"step": "0.25", "direction": "up"}),
            )
        ]

    def test_remove_parses_index(self) -> None:
        control = ChainMockControl()
        ex = CommandExecutor(control)
        res = ex.execute('track chain "Pad 1" remove 2')
        assert res.code == 0
        assert control.calls == [("track_chain_remove", ("Pad 1", 2))]

    def test_unknown_action_is_code_1(self) -> None:
        control = ChainMockControl()
        ex = CommandExecutor(control)
        res = ex.execute('track chain "Pad 1" foo')
        assert res.code == 1
        assert "unknown action" in res.output
        assert control.calls == []

    def test_add_missing_stage_is_code_1(self) -> None:
        control = ChainMockControl()
        ex = CommandExecutor(control)
        res = ex.execute('track chain "Pad 1" add')
        assert res.code == 1
        assert control.calls == []

    def test_remove_missing_index_is_code_1(self) -> None:
        control = ChainMockControl()
        ex = CommandExecutor(control)
        res = ex.execute('track chain "Pad 1" remove')
        assert res.code == 1
        assert control.calls == []

    def test_remove_non_number_is_code_1(self) -> None:
        control = ChainMockControl()
        ex = CommandExecutor(control)
        res = ex.execute('track chain "Pad 1" remove abc')
        assert res.code == 1
        assert "is not a number" in res.output
        assert control.calls == []

    def test_loop_lives_after_error(self) -> None:
        control = ChainMockControl()
        ex = CommandExecutor(control)
        assert ex.execute('track chain "Pad 1" foo').code == 1
        assert ex.execute("tracks").code == 0


# ---------------------------------------------------------------------------
# Executor — реальная сессия (AppEngineControl)
# ---------------------------------------------------------------------------


def _repl() -> tuple[CommandExecutor, Session]:
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    # "Pad 1" — авто-имя pad-дорожки; chain-тесты адресуют её по имени.
    app._session.create_melodic_track("pad")
    return CommandExecutor(AppEngineControl(app)), app._session


class TestExecutorAgainstSession:
    def test_show_empty_chain(self) -> None:
        ex, _session = _repl()
        res = ex.execute('track chain "Pad 1" show')
        assert res.code == 0, res.output
        assert "— (empty)" in res.output

    def test_add_and_show(self) -> None:
        ex, session = _repl()
        res = ex.execute('track chain "Pad 1" add arpeggiate step=0.25 direction=up')
        assert res.code == 0, res.output
        track = session.get_track("Pad 1")
        assert [s.name for s in track.chain.stages] == ["arpeggiate"]
        res = ex.execute('track chain "Pad 1" show')
        assert "arpeggiate step=0.25 direction=up" in res.output

    def test_remove(self) -> None:
        ex, session = _repl()
        ex.execute('track chain "Pad 1" add densify density=0.5')
        res = ex.execute('track chain "Pad 1" remove 1')
        assert res.code == 0, res.output
        assert len(session.get_track("Pad 1").chain) == 0

    def test_unknown_stage_leaves_chain_unchanged(self) -> None:
        ex, session = _repl()
        res = ex.execute('track chain "Pad 1" add transpose step=1')
        assert res.code == 1
        assert "Неизвестный этап" in res.output
        assert len(session.get_track("Pad 1").chain) == 0

    def test_token_without_value_is_code_1(self) -> None:
        ex, session = _repl()
        res = ex.execute('track chain "Pad 1" add arpeggiate step')
        assert res.code == 1
        assert len(session.get_track("Pad 1").chain) == 0

    def test_duplicate_key_is_code_1(self) -> None:
        ex, session = _repl()
        res = ex.execute('track chain "Pad 1" add arpeggiate step=1 step=2')
        assert res.code == 1
        assert "дубликат" in res.output
        assert len(session.get_track("Pad 1").chain) == 0

    def test_invalid_value_is_code_1(self) -> None:
        ex, session = _repl()
        res = ex.execute('track chain "Pad 1" add densify density=2')
        assert res.code == 1
        assert len(session.get_track("Pad 1").chain) == 0

    def test_unknown_track_is_code_1(self) -> None:
        ex, _session = _repl()
        res = ex.execute('track chain "Nope" show')
        assert res.code == 1
        assert "not found" in res.output

    def test_quoted_name_with_spaces(self) -> None:
        ex, session = _repl()
        session.create_melodic_track("pad", name="My Pad")
        res = ex.execute('track chain "My Pad" show')
        assert res.code == 0, res.output

    def test_drum_track_is_success_with_warning(self) -> None:
        ex, session = _repl()
        session.create_drum_track()
        res = ex.execute('track chain "Drum 1" add arpeggiate step=0.25')
        assert res.code == 0, res.output
        assert "цепочка игнорируется" in res.output
        assert len(session.get_track("Drum 1").chain) == 0


# ---------------------------------------------------------------------------
# Completer
# ---------------------------------------------------------------------------


def _completions(completer: ReplCompleter, text: str) -> list[str]:
    """Тексты подсказок для строки ввода."""
    doc = Document(text, len(text))
    return [c.text for c in completer.get_completions(doc, CompleteEvent())]


class TestCompleterChain:
    def test_track_domain_offers_chain_action(self) -> None:
        completer = ReplCompleter(MockControl())
        assert "chain" in _completions(completer, "track ")

    def test_after_chain_offers_track_names(self) -> None:
        completer = ReplCompleter(MockControl())
        texts = _completions(completer, "track chain ")
        assert "Pad 1" in texts
        assert "Drum 1" in texts

    def test_after_name_offers_actions(self) -> None:
        completer = ReplCompleter(MockControl())
        texts = _completions(completer, 'track chain "Pad 1" ')
        assert "show" in texts
        assert "add" in texts
        assert "remove" in texts

    def test_after_add_offers_stage_names(self) -> None:
        completer = ReplCompleter(
            MockControl(), providers={"stage": lambda: ("arpeggiate", "densify")}
        )
        texts = _completions(completer, 'track chain "Pad 1" add ar')
        assert texts == ["arpeggiate"]

    def test_missing_stage_provider_gives_empty(self) -> None:
        completer = ReplCompleter(MockControl())
        assert _completions(completer, 'track chain "Pad 1" add ar') == []


@pytest.mark.parametrize(
    ("line", "args"),
    [
        ('track chain "Pad 1" show', ("Pad 1", "show")),
        ('track chain "Drum 1" remove 3', ("Drum 1", "remove", "3")),
    ],
)
def test_parse_forms(line: str, args: tuple[str, ...]) -> None:
    cmd = CommandParser().parse(line)
    assert cmd.error is None
    assert cmd.args == args
