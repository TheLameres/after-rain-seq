"""track_chain / track_chain_add / track_chain_remove в AppEngineControl (4.4/4.5).

White-box по образцу test_engine_control_drum_pattern.py: App не запускается,
``_session`` заполняется напрямую.
"""

from __future__ import annotations

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.session.model.drum_track import DrumTrack
from src.session.session import Session
from tests.test_scripting_session import MockControl


def make_control() -> tuple[AppEngineControl, App]:
    """App с сессией (pad-дорожка на старте)."""
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    app._session.create_melodic_track("pad")
    return AppEngineControl(app), app


class TestTrackChainShow:
    def test_empty_chain_message_and_data(self) -> None:
        ctl, _app = make_control()
        result = ctl.track_chain("Pad 1")
        assert not result.error
        assert 'track "Pad 1": chain = — (empty)' in result.message
        assert result.data["chain"] == []

    def test_shows_stages_in_order(self) -> None:
        ctl, _app = make_control()
        ctl.track_chain_add("Pad 1", "densify", {"density": "0.5"})
        result = ctl.track_chain_add("Pad 1", "arpeggiate", {"step": "0.25"})
        assert not result.error
        assert (
            'track "Pad 1": chain = densify density=0.5 → '
            "arpeggiate step=0.25 direction=up"
        ) in result.message
        assert result.data["chain"] == [
            "densify density=0.5",
            "arpeggiate step=0.25 direction=up",
        ]

    def test_quoted_name(self) -> None:
        ctl, app = make_control()
        app._session.create_melodic_track("pad", name="My Pad")
        result = ctl.track_chain("My Pad")
        assert not result.error
        assert 'track "My Pad": chain' in result.message

    def test_no_session_is_error(self) -> None:
        app = App(config_path="config.yaml", simulate=True)
        ctl = AppEngineControl(app)
        result = ctl.track_chain("Pad 1")
        assert result.error
        assert "session" in result.message

    def test_unknown_track_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.track_chain("Nope")
        assert result.error
        assert "not found" in result.message


class TestTrackChainAdd:
    def test_add_appends_stage(self) -> None:
        ctl, app = make_control()
        result = ctl.track_chain_add(
            "Pad 1", "arpeggiate", {"step": "0.25", "direction": "up"}
        )
        assert not result.error
        track = app._session.get_track("Pad 1")
        assert len(track.chain) == 1
        assert result.data["stage"] == "arpeggiate step=0.25 direction=up"
        assert result.data["chain"] == ["arpeggiate step=0.25 direction=up"]

    def test_add_twice_appends_to_end(self) -> None:
        ctl, app = make_control()
        ctl.track_chain_add("Pad 1", "arpeggiate", {})
        result = ctl.track_chain_add("Pad 1", "densify", {"density": "0.5"})
        track = app._session.get_track("Pad 1")
        assert [s.name for s in track.chain.stages] == ["arpeggiate", "densify"]
        assert len(result.data["chain"]) == 2  # type: ignore[arg-type]

    def test_unknown_stage_chain_unchanged(self) -> None:
        ctl, app = make_control()
        result = ctl.track_chain_add("Pad 1", "transpose", {})
        assert result.error
        assert "доступные этапы" in result.message
        assert len(app._session.get_track("Pad 1").chain) == 0

    def test_unknown_param_chain_unchanged(self) -> None:
        ctl, app = make_control()
        result = ctl.track_chain_add("Pad 1", "arpeggiate", {"foo": "1"})
        assert result.error
        assert len(app._session.get_track("Pad 1").chain) == 0

    def test_non_numeric_param_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.track_chain_add("Pad 1", "arpeggiate", {"step": "abc"})
        assert result.error
        assert "должен быть числом" in result.message

    def test_invalid_value_is_error(self) -> None:
        ctl, app = make_control()
        result = ctl.track_chain_add("Pad 1", "densify", {"density": "2"})
        assert result.error
        assert len(app._session.get_track("Pad 1").chain) == 0


class TestTrackChainRemove:
    def test_remove_by_index(self) -> None:
        ctl, app = make_control()
        ctl.track_chain_add("Pad 1", "arpeggiate", {})
        ctl.track_chain_add("Pad 1", "densify", {"density": "0.5"})
        result = ctl.track_chain_remove("Pad 1", 1)
        assert not result.error
        track = app._session.get_track("Pad 1")
        assert [s.name for s in track.chain.stages] == ["densify"]
        assert result.data["chain"] == ["densify density=0.5"]

    def test_index_out_of_range_is_error(self) -> None:
        ctl, app = make_control()
        result = ctl.track_chain_remove("Pad 1", 1)
        assert result.error
        assert "out of range" in result.message
        assert len(app._session.get_track("Pad 1").chain) == 0

    def test_zero_index_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.track_chain_remove("Pad 1", 0)
        assert result.error


class TestDrumTrackNotice:
    def test_show_on_drum_is_success_with_warning(self) -> None:
        ctl, app = make_control()
        app._session.create_drum_track()
        result = ctl.track_chain("Drum 1")
        assert result.error is False
        assert "цепочка игнорируется" in result.message
        assert result.data["chain"] == []

    def test_add_on_drum_not_applied(self) -> None:
        ctl, app = make_control()
        app._session.create_drum_track()
        result = ctl.track_chain_add("Drum 1", "arpeggiate", {"step": "0.25"})
        assert result.error is False
        assert "цепочка игнорируется" in result.message
        drum = app._session.get_track("Drum 1")
        assert isinstance(drum, DrumTrack)
        assert len(drum.chain) == 0
        assert result.data["chain"] == []

    def test_remove_on_drum_not_applied(self) -> None:
        ctl, app = make_control()
        app._session.create_drum_track()
        result = ctl.track_chain_remove("Drum 1", 1)
        assert result.error is False
        assert "цепочка игнорируется" in result.message
        assert result.data["chain"] == []


class TestDefaultStub:
    def test_minimal_control_returns_default_fail(self) -> None:
        """Мок без переопределения track_chain* — дефолт ABC (прецедент C1–C4)."""
        ctl = MockControl()
        for call in (
            lambda: ctl.track_chain("Drums"),
            lambda: ctl.track_chain_add("Drums", "arpeggiate", {}),
            lambda: ctl.track_chain_remove("Drums", 1),
        ):
            result = call()
            assert result.error
            assert result.message == "track chain is not supported by this control"
