"""Tests for ScriptRunner — сценарии плана G2 §3.2 (мок-EngineControl)."""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.scripting.runner import ScriptRunner, ScriptRunReport, format_report
from src.session.session import Session
from tests.test_scripting_session import MockControl

ROOT = Path(__file__).resolve().parent.parent


class _SyncCfg:
    """Минимальный sync-конфиг для ``_init_clock_manager`` (внутренний клок).

    По образцу ``_Cfg`` из test_drum_engine_hook.py: без него фасадный
    ``start_transport`` возвращает «clock subsystem disabled», и
    ``session.start()`` в скрипте падает на своей строке.
    """

    enabled = True
    clock_source = "internal"
    midi_clock_device = None
    bpm = 120.0
    swing_amount = 0.0


class _Reg:
    """Мок-реестр портов: один адаптер, события никуда не уходят."""

    def __init__(self) -> None:
        self.adapter = MagicMock()

    def all_outputs(self) -> list[MagicMock]:
        return [self.adapter]

    def flush_all(self) -> None:
        return None

    def get_output(self, label: str) -> MagicMock:
        return self.adapter


@pytest.fixture
def control() -> MockControl:
    return MockControl()


@pytest.fixture
def runner(control: MockControl) -> ScriptRunner:
    return ScriptRunner(control)


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


class TestRunValid:
    def test_valid_script_end_to_end(
        self, runner: ScriptRunner, control: MockControl, tmp_path: Path
    ) -> None:
        """Валидный скрипт: add_track + start — фидбек по порядку, старт вызван."""
        path = _write(
            tmp_path,
            "session.arain.py",
            "pad = TrackProposal(profile_name='pad')\n"
            "session.add_track(pad)\n"
            "session.start()\n",
        )
        report = runner.run_file(path)
        assert report.error is None
        assert report.diagnostics == ()
        assert report.lines_executed == 2
        assert report.output_lines == ("create_track ok", "start_transport ok")
        assert ("start_transport", ()) in control.calls

    def test_canonical_script_fixture(
        self, runner: ScriptRunner, control: MockControl
    ) -> None:
        """Canonical-пример proposal_script.py: валидатор + раннер end-to-end."""
        report = runner.run_file(ROOT / "proposal_script.py")
        assert report.error is None, report.error
        assert report.diagnostics == ()
        assert report.lines_executed >= 5
        assert ("start_transport", ()) in control.calls


class TestDrumDubExample:
    def test_example_validates_and_runs(
        self, runner: ScriptRunner, control: MockControl
    ) -> None:
        """Пример examples/drum_dub.py: валидатор чист, исполнение по порядку."""
        report = runner.run_file(ROOT / "examples" / "drum_dub.py")
        assert report.error is None, report.error
        assert report.diagnostics == ()
        assert report.lines_executed == 8
        assert ("create_drum_track", ("Drums",)) in control.calls
        assert (
            "set_drum_pattern",
            ("Drums", "kick", "x..x|x..x|....|...."),
        ) in control.calls
        assert ("set_drum_pattern", ("Drums", "shaker", "(3,8)")) in control.calls
        assert ("set_drum_pattern", ("Drums", "conga", "(2,8,3)")) in control.calls
        assert ("set_bpm", (120,)) in control.calls
        assert ("start_transport", ()) in control.calls


class TestFatalStop:
    def test_second_of_four_fails(
        self, runner: ScriptRunner, control: MockControl, tmp_path: Path
    ) -> None:
        """Провал 2-й из 4: ScriptError; 3-я не исполнена; error с file:line."""
        control.fail_on = "set_bpm"
        path = _write(
            tmp_path,
            "fail.arain.py",
            "session.start()\n"
            "session.set_bpm(120)\n"
            "session.set_root('A')\n"
            "session.set_scale('dorian')\n",
        )
        report = runner.run_file(path)
        assert report.error == f"{path}:2: set_bpm failed"
        assert report.lines_executed == 1
        called_methods = [c[0] for c in control.calls]
        assert called_methods == ["start_transport", "set_bpm"]

    def test_runtime_fail_line_from_current_call(
        self, runner: ScriptRunner, control: MockControl, tmp_path: Path
    ) -> None:
        """Runtime-провал (переменный профиль): линия — из текущего вызова.

        Счётчик §3.8 — «сколько вызовов фасада прошло»: провалившийся
        вызов (ScriptError) в счётчик не входит, поэтому 0.
        """
        control.fail_on = "create_track"
        path = _write(
            tmp_path,
            "dyn.arain.py",
            "profile = 'bogus'\n"
            "session.add_track(TrackProposal(profile_name=profile))\n",
        )
        report = runner.run_file(path)
        assert report.error == f"{path}:2: create_track failed"
        assert report.lines_executed == 0


class TestNonFatal:
    def test_fatal_false_continues(
        self, runner: ScriptRunner, control: MockControl, tmp_path: Path
    ) -> None:
        """``fatal=False``: EngineResult возвращён, 3-я команда исполнена."""
        control.fail_on = "set_bpm"
        path = _write(
            tmp_path,
            "soft.arain.py",
            "session.start()\n"
            "session.set_bpm(120, fatal=False)\n"
            "session.set_root('A')\n",
        )
        report = runner.run_file(path)
        assert report.error is None
        assert report.lines_executed == 3
        assert report.output_lines == (
            "start_transport ok",
            "set_bpm failed",
            "set_root ok",
        )
        assert ("set_root", ("A",)) in control.calls


class TestValidationBlocks:
    def test_diagnostics_block_execution(
        self, runner: ScriptRunner, control: MockControl, tmp_path: Path
    ) -> None:
        """Diagnostics от валидатора: исполнение не начиналось."""
        path = _write(
            tmp_path,
            "bad.arain.py",
            "session.add_track(TrackProposal(profile_name='pad', voicing='1-2-3-5-7'))\n",
        )
        report = runner.run_file(path)
        assert report.error is None
        assert report.lines_executed == 0
        assert len(report.diagnostics) == 1
        assert control.calls == []


class TestExceptions:
    def test_body_exception_caught(
        self, runner: ScriptRunner, control: MockControl, tmp_path: Path
    ) -> None:
        """Исключение в теле скрипта: error='<class>: <text>', раннер жив."""
        path = _write(
            tmp_path,
            "boom.arain.py",
            "session.start()\nx = 1 // 0\n",
        )
        report = runner.run_file(path)
        assert report.error is not None
        assert f"{path}:2:" in report.error
        assert "ZeroDivisionError" in report.error
        assert "integer division or modulo by zero" in report.error
        assert report.lines_executed == 1


class TestDestructiveAutoConfirm:
    def test_stop_auto_confirmed(
        self,
        runner: ScriptRunner,
        control: MockControl,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``stop()`` в скрипте: вызвано без confirm, в логе auto-confirmed."""
        path = _write(tmp_path, "stop.arain.py", "session.stop()\n")
        with caplog.at_level(logging.WARNING, logger="src.scripting.script_session"):
            report = runner.run_file(path)
        assert report.error is None
        assert ("stop_transport", ()) in control.calls
        assert any(
            "auto-confirmed destructive stop" in r.message for r in caplog.records
        )


class TestFileErrors:
    def test_file_not_found(self, runner: ScriptRunner, tmp_path: Path) -> None:
        """Файл не найден: error='file not found', без diagnostics."""
        report = runner.run_file(tmp_path / "missing.arain.py")
        assert report.error == f"file not found: {tmp_path / 'missing.arain.py'}"
        assert report.diagnostics == ()
        assert report.lines_executed == 0

    def test_check_file_not_found(self, runner: ScriptRunner, tmp_path: Path) -> None:
        """``check_file`` на отсутствующем файле: diagnostic line=0."""
        diags = runner.check_file(tmp_path / "missing.arain.py")
        assert len(diags) == 1
        assert diags[0].line == 0
        assert "file not found" in diags[0].message


class TestFormatReport:
    def test_format_success(self, runner: ScriptRunner, tmp_path: Path) -> None:
        """Форматтер: заголовок, линии фидбека, итог ok."""
        path = _write(
            tmp_path,
            "fmt.arain.py",
            "session.start()\nsession.stop()\n",
        )
        report = runner.run_file(path)
        text = format_report(report)
        assert text.startswith(f"script {path}:")
        assert "  1| start_transport ok" in text
        assert "  2| stop_transport ok" in text
        assert "  ok: 2 call(s)" in text

    def test_format_diagnostics(self, runner: ScriptRunner, tmp_path: Path) -> None:
        """Форматтер: diagnostics с file:line, без линий фидбека."""
        path = _write(tmp_path, "fmtbad.arain.py", "session.unknown_op()\n")
        report = runner.run_file(path)
        text = format_report(report)
        assert "validation: 1 diagnostic(s)" in text
        assert f"{path}:1: unknown session method 'unknown_op'" in text
        assert "| " not in text

    def test_report_is_frozen(self, runner: ScriptRunner, tmp_path: Path) -> None:
        """ScriptRunReport — frozen dataclass."""
        report = runner.run_file(tmp_path / "missing.arain.py")
        assert isinstance(report, ScriptRunReport)
        with pytest.raises(FrozenInstanceError):
            report.error = "x"  # type: ignore[misc]


class TestTrackChainScripts:
    """track_chain_add в скриптах: drum — предупреждение, строгий режим — ветвление (5.4)."""

    @staticmethod
    def _app_control(*, drum: bool) -> AppEngineControl:
        """App с сессией, мок-реестром портов и внутренними часами.

        Часы нужны ``session.start()``: фасадный ``start_transport`` требует
        ``clock_manager`` (иначе «clock subsystem disabled»). Реестр портов
        нужен ДО часов: ``_init_clock_manager`` строит Transport вместе с ним
        (иначе «PortRegistry must be initialized before Transport»).
        """
        app = App(config_path="config.yaml", simulate=True)
        app._port_registry = _Reg()  # type: ignore[assignment]
        app._session = Session()
        if drum:
            app._session.create_drum_track()
        else:
            app._session.create_melodic_track("pad")
        app._init_clock_manager(_SyncCfg())
        return AppEngineControl(app)

    def test_drum_chain_add_continues(self, tmp_path: Path) -> None:
        """``track_chain_add`` на drum-дорожке не прерывает скрипт."""
        path = _write(
            tmp_path,
            "drumchain.arain.py",
            "session.track_chain_add('Drum 1', 'arpeggiate step=0.25')\n"
            "session.start()\n",
        )
        runner = ScriptRunner(self._app_control(drum=True))
        report = runner.run_file(path)
        assert report.error is None
        assert report.lines_executed == 2  # счётчик вызовов растёт
        assert len(report.output_lines) == 2
        assert "цепочка игнорируется" in report.output_lines[0]
        assert "transport started" in report.output_lines[1]
        # format_report не менялся: линии фидбека с номерами.
        text = format_report(report)
        assert "  1| " in text
        assert "  ok: 2 call(s)" in text

    def test_strict_mode_branches_on_error(self, tmp_path: Path) -> None:
        """``fatal=False`` + проверка ``result.error`` — скрипт ветвится сам."""
        path = _write(
            tmp_path,
            "strict.arain.py",
            "r = session.track_chain_add('Pad 1', 'transpose step=1', fatal=False)\n"
            "if r.error:\n"
            "    session.track_chain_add('Pad 1', 'arpeggiate step=0.25', fatal=False)\n",
        )
        runner = ScriptRunner(self._app_control(drum=False))
        report = runner.run_file(path)
        assert report.error is None
        assert report.lines_executed == 2
        assert len(report.output_lines) == 2
        assert "Неизвестный этап" in report.output_lines[0]
        assert "arpeggiate step=0.25 direction=up" in report.output_lines[1]
