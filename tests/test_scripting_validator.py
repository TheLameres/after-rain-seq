"""Tests for ScriptValidator — compile + AST-линт, сценарии плана G2 §2.4."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.scripting.validator import ScriptValidator

ROOT = Path(__file__).resolve().parent.parent


def _validate(source: str) -> list[str]:
    """Валидация снапшота → список отформатированных диагностик."""
    validator = ScriptValidator()
    return [d.format() for d in validator.validate_source(source, "<test>")]


def _messages(source: str) -> list[str]:
    """Только тексты диагностик (без file:line) — для поиска подстрок."""
    validator = ScriptValidator()
    return [d.message for d in validator.validate_source(source, "<test>")]


class TestFacadeCalls:
    """Вызовы фасада ``session.*``: методы, аргументы, kwarg."""

    def test_valid_add_track(self) -> None:
        source = "pad = TrackProposal(profile_name='pad')\nsession.add_track(pad)\n"
        assert _validate(source) == []

    def test_unknown_method(self) -> None:
        """Неизвестный метод фасада — diagnostic с номером строки."""
        diags = _validate("session.unknown_op()\n")
        assert len(diags) == 1
        assert "unknown session method" in diags[0]
        assert "unknown_op" in diags[0]
        assert diags[0].startswith("<test>:1:")

    def test_missing_argument(self) -> None:
        """Мало позиционных аргументов — diagnostic про аргументы."""
        messages = _messages("session.set_bpm()\n")
        assert len(messages) == 1
        assert "missing required argument" in messages[0]

    def test_kwarg_covering_required_argument(self) -> None:
        """``set_bpm(bpm=120)`` — kwarg входит в keywords, валидно."""
        assert _validate("session.set_bpm(bpm=120)\n") == []

    def test_too_many_positional(self) -> None:
        messages = _messages("session.set_bpm(120, 25)\n")
        assert any("too many positional arguments" in m for m in messages)

    def test_unknown_keyword(self) -> None:
        messages = _messages("session.set_bpm(tempo=120)\n")
        assert any("unknown keyword" in m for m in messages)

    def test_var_positional_sources(self) -> None:
        """``set_track_sources(name, *sources)`` — var-positional, лимита нет."""
        source = "session.set_track_sources('Pad 1', 'A', 'B')\n"
        assert _validate(source) == []

    def test_dynamic_arguments_skipped(self) -> None:
        """Динамика (переменные, выражения) — пропускается, runtime проверит."""
        source = (
            "bpm = 120\n"
            "x = 42\n"
            "session.set_bpm(x)\n"
            "session.set_root('A' + '')\n"
        )
        assert _validate(source) == []

    def test_non_session_attribute_calls_ignored(self) -> None:
        """Вызовы чужих объектов — вне линта."""
        source = "other = lambda *a: None\nother.set_bpm(120)\n"
        assert _validate(source) == []


class TestSetDrumPatternFacade:
    """set_drum_pattern: валидатор подхватывает метод рефлексией (design §8)."""

    def test_valid_call_passes(self) -> None:
        source = "session.set_drum_pattern('Drums', 'kick', 'x..x')\n"
        assert _validate(source) == []

    def test_missing_argument(self) -> None:
        """Два аргумента вместо трёх — diagnostic до исполнения."""
        messages = _messages("session.set_drum_pattern('Drums', 'kick')\n")
        assert len(messages) == 1
        assert "missing required argument" in messages[0]
        assert "needs 3" in messages[0]

    def test_too_many_positional(self) -> None:
        messages = _messages("session.set_drum_pattern('Drums', 'kick', 'x..x', 'e')\n")
        assert any("too many positional arguments" in m for m in messages)

    def test_unknown_keyword(self) -> None:
        msg = "session.set_drum_pattern('Drums', 'kick', 'x..x', pattern2='x')\n"
        messages = _messages(msg)
        assert any("unknown keyword" in m for m in messages)


class TestDtoConstructors:
    """Конструкторы DTO: поля из dataclasses.fields + семантика литералов."""

    def test_valid_canonical(self) -> None:
        source = (
            "pad = TrackProposal(name='Track 1', profile_name='atmos', "
            "voicing='1-3-5-7', degrees=[6, 5, 4])\n"
        )
        assert _validate(source) == []

    def test_unknown_profile(self) -> None:
        """``profile_name`` вне реестра PROFILES — diagnostic."""
        messages = _messages("TrackProposal(profile_name='nope')\n")
        assert len(messages) == 1
        assert "unknown profile" in messages[0]
        assert "'nope'" in messages[0]

    def test_unknown_voicing(self) -> None:
        """Voicing вне реестра VOICINGS — кейс из proposal_script.py до правки."""
        messages = _messages("TrackProposal(profile_name='pad', voicing='1-2-3-5-7')\n")
        assert len(messages) == 1
        assert "unknown voicing" in messages[0]

    def test_degrees_out_of_range(self) -> None:
        """Ступени вне 0..13 — diagnostic; ``[0]`` (тоника) — валидна."""
        assert _validate("TrackProposal(profile_name='pad', degrees=[0])\n") == []
        messages = _messages("TrackProposal(profile_name='pad', degrees=[14])\n")
        assert messages == ["degrees out of 0..13: 14"]
        messages = _messages("TrackProposal(profile_name='pad', degrees=[-1])\n")
        assert messages == ["degrees out of 0..13: -1"]

    def test_degrees_variable_skipped(self) -> None:
        """``degrees=[x]`` — не-литерал, нет diagnostics; runtime проверит."""
        source = "x = 0\nTrackProposal(profile_name='pad', degrees=[x])\n"
        assert _validate(source) == []

    def test_channel_out_of_range(self) -> None:
        messages = _messages("TrackProposal(profile_name='pad', channel=16)\n")
        assert messages == ["channel out of 0..15: 16"]

    def test_unknown_field(self) -> None:
        messages = _messages("TrackProposal(profile_name='pad', foo=1)\n")
        assert messages == ["TrackProposal: unknown field 'foo'"]

    def test_drum_proposal_valid(self) -> None:
        assert _validate("session.add_drum(DrumProposal(name='Kick'))\n") == []

    def test_drum_proposal_unknown_field(self) -> None:
        messages = _messages("DrumProposal(channel=9)\n")
        assert messages == ["DrumProposal: unknown field 'channel'"]

    def test_empty_name(self) -> None:
        messages = _messages("TrackProposal(profile_name='pad', name='')\n")
        assert messages == ["TrackProposal: name must be a non-empty string"]


class TestInjectedNames:
    """Переопределение инжектированных имён."""

    def test_session_reassigned(self) -> None:
        messages = _messages("session = 5\n")
        assert len(messages) == 1
        assert "reassigned" in messages[0]

    def test_dto_reassigned(self) -> None:
        messages = _messages("TrackProposal = dict\n")
        assert len(messages) == 1
        assert "reassigned" in messages[0]

    def test_aug_and_ann_assign(self) -> None:
        assert _messages("session += 1\n") != []
        assert _messages("session: int = 5\n") != []

    def test_other_names_ok(self) -> None:
        assert _validate("session_x = 5\nbpm = 120\n") == []


class TestSyntaxErrors:
    """Синтаксис: line/col из compile."""

    def test_syntax_error(self) -> None:
        diags = ScriptValidator().validate_source("def broken(:\n", "<test>")
        assert len(diags) == 1
        assert diags[0].line == 1
        assert "syntax error" in diags[0].message

    def test_syntax_error_line(self) -> None:
        diags = ScriptValidator().validate_source("a = 1\nb = (2\n", "<test>")
        assert len(diags) == 1
        assert diags[0].line == 2


class TestCanonicalScript:
    """Canonical-пример proposal_script.py проходит валидацию end-to-end."""

    def test_proposal_script_valid(self) -> None:
        source = (ROOT / "proposal_script.py").read_text(encoding="utf-8")
        diags = ScriptValidator().validate_source(source, "proposal_script.py")
        assert diags == [], "\n".join(d.format() for d in diags)


class TestSorting:
    """Отчёт сортируется по (line, col)."""

    def test_sorted_by_line(self) -> None:
        source = "TrackProposal(profile_name='nope')\nsession.unknown_op()\n"
        diags = ScriptValidator().validate_source(source, "<test>")
        assert [d.line for d in diags] == sorted(d.line for d in diags)
        assert len(diags) == 2


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        ("session.set_bpm()\n", "missing required argument"),
        ("session.set_scale()\n", "missing required argument"),
        ("session.switch_port('a')\n", "missing required argument"),
    ],
)
def test_required_argument_counts(source: str, needle: str) -> None:
    """Обязательные аргументы по таблице методов (рефлексия, не руками)."""
    assert any(needle in m for m in _messages(source))


class TestCaptureFacade:
    """capture_start/capture_stop — валидатор подхватывает рефлексией
    (design add-capture-smf §8, фиксируется тестом)."""

    def test_capture_start_no_args_passes(self) -> None:
        assert _validate("session.capture_start()\n") == []

    def test_capture_start_with_path_passes(self) -> None:
        assert _validate("session.capture_start('x.mid')\n") == []

    def test_capture_stop_passes(self) -> None:
        assert _validate("session.capture_stop()\n") == []

    def test_capture_start_fatal_kwarg_passes(self) -> None:
        assert _validate("session.capture_start('x.mid', fatal=False)\n") == []

    def test_capture_start_too_many_positional(self) -> None:
        messages = _messages("session.capture_start('a', 'b')\n")
        assert any("too many positional arguments" in m for m in messages)

    def test_capture_start_unknown_keyword(self) -> None:
        messages = _messages("session.capture_start(file='x.mid')\n")
        assert any("unknown keyword" in m for m in messages)

    def test_capture_stop_too_many_positional(self) -> None:
        messages = _messages("session.capture_stop('x.mid')\n")
        assert any("too many positional arguments" in m for m in messages)


class TestTrackChainFacade:
    """track_chain* — валидатор подхватывает методы рефлексией (5.3).

    ``validator.py`` не меняется: таблица методов строится
    ``inspect.signature(ScriptSession)``, новые обёртки попадают в линт
    арности автоматически.
    """

    def test_valid_calls_pass(self) -> None:
        source = (
            "session.show_track_chain('Pad 1')\n"
            "session.track_chain_add('Pad 1', 'arpeggiate step=0.25')\n"
            "session.track_chain_remove('Pad 1', 1)\n"
        )
        assert _validate(source) == []

    def test_show_with_fatal_kwarg_passes(self) -> None:
        assert _validate("session.show_track_chain('Pad 1', fatal=False)\n") == []

    def test_missing_argument(self) -> None:
        """Один аргумент вместо двух — diagnostic до исполнения."""
        messages = _messages("session.track_chain_add('Pad 1')\n")
        assert len(messages) == 1
        assert "missing required argument" in messages[0]
        assert "needs 2" in messages[0]

    def test_too_many_positional(self) -> None:
        messages = _messages("session.track_chain_add('a', 'b', 'c')\n")
        assert any("too many positional arguments" in m for m in messages)

    def test_unknown_keyword(self) -> None:
        messages = _messages("session.track_chain_add(name='a', spec='b', stage='c')\n")
        assert any("unknown keyword" in m for m in messages)

    def test_remove_missing_index(self) -> None:
        messages = _messages("session.track_chain_remove('Pad 1')\n")
        assert any("missing required argument" in m for m in messages)
