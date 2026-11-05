"""REPL: track degrees / voicing / inversion / profile, voicings (C5)."""

from __future__ import annotations

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.repl.executor import CommandExecutor
from src.session.session import Session


def make_executor() -> tuple[CommandExecutor, Session]:
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    return CommandExecutor(AppEngineControl(app)), app._session


class TestTrackDegreesCommand:
    def test_roman(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track degrees {pad.name} I IV V I")
        assert res.code == 0
        assert pad.degrees == (0, 3, 4, 0)
        assert "I IV V I" in res.output

    def test_numeric_and_mixed(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        assert ex.execute(f"track degrees {pad.name} 0 4 3 0").code == 0
        assert pad.degrees == (0, 4, 3, 0)
        assert ex.execute(f"track degrees {pad.name} I 7 IV 13").code == 0
        assert pad.degrees == (0, 7, 3, 13)

    def test_quoted_name_with_space(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f'track degrees "{pad.name}" I V')
        assert res.code == 0
        assert pad.degrees == (0, 4)

    def test_unquoted_name_with_space_resolves_to_existing_track(self) -> None:
        ex, session = make_executor()
        pad1 = session.create_melodic_track("pad")
        session.create_melodic_track(
            "pad"
        )  # "Pad 2" — значение «1» не должно съесть имя
        res = ex.execute(f"track degrees {pad1.name} I IV")
        assert res.code == 0, res.output
        assert pad1.degrees == (0, 3)

    def test_unknown_track(self) -> None:
        ex, _ = make_executor()
        res = ex.execute("track degrees Nope I IV")
        assert res.code == 1
        assert "no track matches" in res.output

    def test_bad_token(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        before = pad.degrees
        res = ex.execute(f"track degrees {pad.name} I XV")
        assert res.code == 1
        assert res.output.startswith("error:")
        assert pad.degrees == before

    def test_out_of_range_numeric(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track degrees {pad.name} 99")
        assert res.code == 1
        assert res.output.startswith("error:")

    def test_missing_args(self) -> None:
        ex, _ = make_executor()
        assert ex.execute("track degrees").code == 1


class TestTrackVoicingCommand:
    def test_valid(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        assert ex.execute(f"track voicing {pad.name} 1-3-5-7").code == 0
        assert pad.voicing == "1-3-5-7"

    def test_unknown_voicing(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track voicing {pad.name} nonsense")
        assert res.code == 1
        assert res.output.startswith("error:")


class TestTrackInversionCommand:
    def test_valid(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        assert ex.execute(f"track inversion {pad.name} 1").code == 0
        assert pad.inversion == 1

    def test_not_a_number(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track inversion {pad.name} x")
        assert res.code == 1
        assert "not a number" in res.output

    def test_out_of_range(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track inversion {pad.name} 9")
        assert res.code == 1
        assert res.output.startswith("error:")


class TestTrackProfileCommand:
    def test_valid(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        assert ex.execute(f"track profile {pad.name} atmos").code == 0
        assert pad.profile_name == "atmos"

    def test_cc_boundary(self) -> None:
        ex, session = make_executor()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track profile {pad.name} cc_filter")
        assert res.code == 1
        assert res.output.startswith("error:")
        assert pad.profile_name == "pad"


class TestVoicingsCommand:
    def test_lists_voicings(self) -> None:
        ex, _ = make_executor()
        res = ex.execute("voicings")
        assert res.code == 0
        assert res.output.startswith("voicings:")
        names = res.output.removeprefix("voicings: ").split(", ")
        for name in ("1", "1-3-5", "1-3-5-7"):
            assert name in names
