"""Tests for CommandParser — разбор всех команд, ошибки, usage, похожие."""

from __future__ import annotations

import pytest

from src.repl.parser import CommandParser


@pytest.fixture
def parser() -> CommandParser:
    return CommandParser()


class TestBasicParsing:
    """Базовый разбор команд."""

    def test_simple_command(self, parser):
        cmd = parser.parse("status")
        assert cmd.error is None
        assert cmd.name == "status"
        assert cmd.domain == "status"
        assert cmd.action is None
        assert cmd.args == ()

    def test_case_and_spaces_insensitive(self, parser):
        cmd = parser.parse("  CLOCK   SOURCE   MIDI  ")
        assert cmd.error is None
        assert cmd.name == "clock source"
        assert cmd.args == ("MIDI",)

    def test_action_command(self, parser):
        cmd = parser.parse("track add pad")
        assert cmd.error is None
        assert cmd.name == "track add"
        assert cmd.domain == "track"
        assert cmd.action == "add"
        assert cmd.args == ("pad",)

    def test_optional_args(self, parser):
        assert parser.parse("clock").error is None
        assert parser.parse("ports").error is None
        assert parser.parse("logs").args == ()
        assert parser.parse("logs 5").args == ("5",)
        assert parser.parse("help").args == ()

    def test_flags(self, parser):
        cmd = parser.parse("stop --yes")
        assert cmd.error is None
        assert cmd.flags == frozenset({"yes"})
        assert cmd.destructive_confirmed

        cmd = parser.parse("track delete Pad 1 -f")
        assert cmd.flags == frozenset({"f"})
        assert cmd.destructive_confirmed

    def test_empty_input_is_noop(self, parser):
        cmd = parser.parse("")
        assert cmd.error is None
        assert cmd.name == ""

    def test_quit_alias(self, parser):
        assert parser.parse("quit").name == "quit"
        assert parser.parse("exit").name == "exit"


class TestJoinArgs:
    """Имена дорожек с пробелами: джойн и кавычки."""

    def test_join_args_unquoted(self, parser):
        cmd = parser.parse("track delete Pad 1")
        assert cmd.error is None
        assert cmd.args == ("Pad 1",)

    def test_join_args_quoted(self, parser):
        cmd = parser.parse('track delete "Pad 1"')
        assert cmd.error is None
        assert cmd.args == ("Pad 1",)

    def test_track_show_joins(self, parser):
        cmd = parser.parse("track show Drum 1")
        assert cmd.error is None
        assert cmd.args == ("Drum 1",)


class TestMutationCommands:
    """Команды ручной мутации (spec §3, §4c, §8)."""

    def test_evolve_no_args(self, parser):
        cmd = parser.parse("evolve")
        assert cmd.error is None
        assert cmd.args == ()

    def test_evolve_joined_name(self, parser):
        cmd = parser.parse("evolve Pad 1")
        assert cmd.error is None
        assert cmd.args == ("Pad 1",)

    def test_undo_joined_name(self, parser):
        cmd = parser.parse("undo Drum 1")
        assert cmd.error is None
        assert cmd.args == ("Drum 1",)

    def test_undo_requires_name(self, parser):
        cmd = parser.parse("undo")
        assert cmd.error is not None

    def test_recall_name_and_version(self, parser):
        cmd = parser.parse("recall Pad 1 2")
        assert cmd.error is None
        assert cmd.args == ("Pad", "1", "2")

    def test_recall_requires_version(self, parser):
        cmd = parser.parse("recall Pad")
        assert cmd.error is not None

    def test_history_optional_name(self, parser):
        assert parser.parse("history").error is None
        cmd = parser.parse("history Drum 1")
        assert cmd.error is None
        assert cmd.args == ("Drum 1",)


class TestErrors:
    """Ошибки синтаксиса → usage; неизвестные → похожие команды."""

    def test_unknown_command_suggests_similar(self, parser):
        cmd = parser.parse("statuz")
        assert cmd.error is not None
        assert "status" in cmd.error
        assert "help" in cmd.error

    def test_unknown_command_no_suggestion(self, parser):
        cmd = parser.parse("xyzzy")
        assert cmd.error is not None
        assert "unknown command" in cmd.error

    def test_wrong_arg_count_with_usage(self, parser):
        cmd = parser.parse("bpm")
        assert cmd.error is not None
        assert cmd.usage is not None
        assert "usage: bpm" in cmd.usage

    def test_too_many_args(self, parser):
        cmd = parser.parse("bpm 120 130")
        assert cmd.error is not None

    def test_invalid_choice(self, parser):
        cmd = parser.parse("clock source cv")
        assert cmd.error is not None
        assert "internal" in cmd.error

    def test_missing_action(self, parser):
        cmd = parser.parse("track")
        assert cmd.error is not None
        assert "add" in cmd.error

    def test_unknown_action(self, parser):
        cmd = parser.parse("track bogus x")
        assert cmd.error is not None
        assert "unknown action" in cmd.error

    def test_unbalanced_quotes(self, parser):
        cmd = parser.parse('track delete "Pad 1')
        assert cmd.error is not None


class TestHelp:
    """Справка из таблицы команд."""

    def test_help_lists_commands(self, parser):
        text = parser.help_text()
        assert "status" in text
        assert "track add" in text
        assert "destructive" in text.lower() or "(!)" in text

    def test_help_single_command(self, parser):
        text = parser.help_text("clock source")
        assert "usage" in text.lower() or "clock source" in text

    def test_help_unknown(self, parser):
        text = parser.help_text("frobnicate")
        assert text.startswith("error:")


class TestScriptCommands:
    """Домен script: run/check (план G2, этап 4)."""

    def test_script_run(self, parser):
        cmd = parser.parse("script run setup.arain.py")
        assert cmd.error is None
        assert cmd.name == "script run"
        assert cmd.domain == "script"
        assert cmd.action == "run"
        assert cmd.args == ("setup.arain.py",)

    def test_script_check(self, parser):
        cmd = parser.parse("script check proposal_script.py")
        assert cmd.error is None
        assert cmd.name == "script check"
        assert cmd.args == ("proposal_script.py",)

    def test_script_run_without_args(self, parser):
        cmd = parser.parse("script run")
        assert cmd.error is not None
        assert "usage: script run <file>" in cmd.usage

    def test_script_check_too_many_args(self, parser):
        cmd = parser.parse("script check a.py b.py")
        assert cmd.error is not None
        assert "usage: script check <file>" in cmd.usage

    def test_script_domain_without_action(self, parser):
        cmd = parser.parse("script")
        assert cmd.error is not None
        assert "missing action" in cmd.error

    def test_script_close_match_suggestion(self, parser):
        """Опечатка домена: difflib подсказывает script (из parser, бесплатно)."""
        cmd = parser.parse("scrip run x.py")
        assert cmd.error is not None
        assert "script" in cmd.error

    def test_help_lists_script_commands(self, parser):
        text = parser.help_text()
        assert "script run <file>" in text
        assert "script check <file>" in text
