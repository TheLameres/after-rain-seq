"""Расширения EngineControl D2: drum/sources/gate/density/evolve_track.

White-box по образцу test_app_routing.py: App не запускается, _session
заполняется напрямую.
"""

from __future__ import annotations

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.session.session import Session


def make_control() -> tuple[AppEngineControl, Session]:
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    return AppEngineControl(app), app._session


class TestCreateDrumTrack:
    def test_creates_drum_track(self) -> None:
        ctl, session = make_control()
        result = ctl.create_drum_track()
        assert result.startswith('created track "Drum 1"')
        assert session.get_track("Drum 1") is not None

    def test_limit_is_text_error(self) -> None:
        ctl, _session = make_control()
        ctl.create_drum_track()
        ctl.create_drum_track()
        result = ctl.create_drum_track()
        assert result.startswith("error:")


class TestSetTrackSources:
    def test_assigns_sources(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        stab = session.create_melodic_track("stab")
        result = ctl.set_track_sources(stab.name, pad.name)
        assert "sources" in result
        assert session.get_track(stab.name).sources == (pad.name,)

    def test_cycle_is_text_error(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        stab = session.create_melodic_track("stab")
        session.set_sources(stab.name, pad.name)
        result = ctl.set_track_sources(pad.name, stab.name)
        assert result.startswith("error:")
        # Значение не применено
        assert session.get_track(pad.name).sources == ()

    def test_unknown_track_is_error(self) -> None:
        ctl, _session = make_control()
        assert ctl.set_track_sources("Nope", "X").startswith("error:")

    def test_unknown_source_is_error(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_sources(pad.name, "Nope")
        assert result.startswith("error:")
        assert session.get_track(pad.name).sources == ()


class TestSetTrackGate:
    def test_sets_gate(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_gate(pad.name, 0.25)
        assert "gate = 0.25" in result
        assert session.get_track(pad.name).gate == 0.25

    def test_validation(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        assert ctl.set_track_gate(pad.name, 1.5).startswith("error:")
        assert ctl.set_track_gate(pad.name, -0.1).startswith("error:")

    def test_drum_track_rejected(self) -> None:
        ctl, session = make_control()
        drum = session.create_drum_track()
        assert ctl.set_track_gate(drum.name, 0.5).startswith("error:")


class TestSetTrackDensity:
    def test_sets_density(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_density(pad.name, 0.4)
        assert "density = 0.40" in result
        assert session.get_track(pad.name).density == 0.4

    def test_validation(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        assert ctl.set_track_density(pad.name, 1.2).startswith("error:")
        assert ctl.set_track_density(pad.name, -0.5).startswith("error:")

    def test_unknown_track_is_error(self) -> None:
        ctl, _session = make_control()
        assert ctl.set_track_density("Nope", 0.5).startswith("error:")


class TestEvolveTrack:
    def test_evolve_one(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        pad.freeze()
        result = ctl.evolve_track(pad.name)
        assert "evolved" in result
        assert pad.mutate == 0.5

    def test_unknown_track_is_error(self) -> None:
        ctl, _session = make_control()
        assert ctl.evolve_track("Nope").startswith("error:")
