"""Tests for `_run_scripts` (main.py) — startup/CLI-скрипты, fail-fast.

E2e-сессия на моках: MockApp (записывает stop()) + MockControl (записывает
вызовы). Полные сценарии приложения проверяются спайками ``--simulate``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.main import _run_scripts
from tests.test_scripting_session import MockControl

ROOT = Path(__file__).resolve().parent.parent


class MockApp:
    """Стаб App: записывает stop()."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def app() -> MockApp:
    return MockApp()


@pytest.fixture
def control() -> MockControl:
    return MockControl()


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


class TestStartupDisabled:
    def test_empty_startup_runs_nothing(
        self, app: MockApp, control: MockControl
    ) -> None:
        """``scripting.startup=""`` — ничего не исполняется."""
        _run_scripts(app, control, "")
        assert control.calls == []
        assert app.stopped is False


class TestStartupValid:
    def test_valid_startup_executed_before_main_loop(
        self, app: MockApp, control: MockControl, tmp_path: Path
    ) -> None:
        """Валидный startup исполнен до main loop; приложение стартует."""
        path = _write(
            tmp_path,
            "startup.arain.py",
            "session.set_bpm(110)\nsession.start()\n",
        )
        _run_scripts(app, control, str(path))
        assert ("start_transport", ()) in control.calls
        assert app.stopped is False

    def test_simulate_scenario_full_session(
        self, app: MockApp, control: MockControl, tmp_path: Path
    ) -> None:
        """``--script`` + ``--simulate``: e2e-сессия на моках (2 melodic + drum)."""
        path = _write(
            tmp_path,
            "session.arain.py",
            "session.add_track(TrackProposal(profile_name='pad'))\n"
            "session.add_track(TrackProposal(profile_name='sub'))\n"
            "session.add_drum(DrumProposal())\n"
            "session.set_root('A')\n"
            "session.start()\n",
        )
        _run_scripts(app, control, "", str(path))
        assert not app.stopped
        assert [c[0] for c in control.calls].count("create_track") == 2
        assert ("create_drum_track", (None,)) in control.calls
        assert ("start_transport", ()) in control.calls


class TestStartupFailed:
    def test_invalid_startup_exits(
        self,
        app: MockApp,
        control: MockControl,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Невалидный startup (voicing): приложение не стартует — exit до app.run."""
        path = _write(
            tmp_path,
            "bad.arain.py",
            "TrackProposal(profile_name='pad', voicing='1-2-3-5-7')\n",
        )
        with (
            caplog.at_level(logging.ERROR, logger="src.main"),
            pytest.raises(SystemExit) as excinfo,
        ):
            _run_scripts(app, control, str(path))
        assert excinfo.value.code == 1
        assert app.stopped is True
        assert control.calls == []
        assert "script failed" in caplog.text
        assert "1-2-3-5-7" in capsys.readouterr().out

    def test_runtime_failure_third_line_no_rollback(
        self, app: MockApp, control: MockControl, tmp_path: Path
    ) -> None:
        """Провал на 3-й строке: выход; 1–2 применённые команды не откатываются."""
        control.fail_on = "set_root"
        path = _write(
            tmp_path,
            "partial.arain.py",
            "session.set_bpm(120)\nsession.set_root('A')\nsession.start()\n",
        )
        with pytest.raises(SystemExit) as excinfo:
            _run_scripts(app, control, str(path))
        assert excinfo.value.code == 1
        assert app.stopped is True
        assert [c[0] for c in control.calls] == ["set_bpm", "set_root"]


class TestStartupThenCli:
    def test_startup_then_cli_order(
        self, app: MockApp, control: MockControl, tmp_path: Path
    ) -> None:
        """Порядок: startup из config, затем --script из CLI."""
        startup = _write(tmp_path, "startup.arain.py", "session.start()\n")
        cli = _write(tmp_path, "cli.arain.py", "session.set_bpm(128)\n")
        _run_scripts(app, control, str(startup), str(cli))
        assert [c[0] for c in control.calls] == ["start_transport", "set_bpm"]
        assert app.stopped is False

    def test_cli_script_missing_file_exits(
        self,
        app: MockApp,
        control: MockControl,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--script`` без файла: exit 1, сообщение в отчёте."""
        missing = tmp_path / "missing.arain.py"
        with pytest.raises(SystemExit) as excinfo:
            _run_scripts(app, control, "", str(missing))
        assert excinfo.value.code == 1
        assert "file not found" in capsys.readouterr().out
        assert app.stopped is True


class TestCanonicalFixture:
    def test_canonical_script_runs_on_mocks(
        self, app: MockApp, control: MockControl
    ) -> None:
        """Canonical-пример proposal_script.py — прогон через _run_scripts."""
        _run_scripts(app, control, str(ROOT / "proposal_script.py"))
        assert not app.stopped
        assert ("start_transport", ()) in control.calls
