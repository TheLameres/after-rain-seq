"""Фасад AppEngineControl: degrees / voicing / inversion / profile (C1–C4).

White-box по образцу test_engine_control_d2.py: App не запускается, сессия
подставляется напрямую.
"""

from __future__ import annotations

import queue

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.harmony.harmony import Harmony
from src.session.engine.melodic_engine import MelodicEngine
from src.session.session import Session


def make_control() -> tuple[AppEngineControl, Session]:
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    return AppEngineControl(app), app._session


class TestSetTrackDegrees:
    def test_sets_and_reports_roman(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_degrees(pad.name, [0, 4, 3, 0])
        assert not result.error
        assert result.message.startswith(
            f'track "{pad.name}": degrees queued = I V IV I'
        )
        assert pad.pending_degrees == (0, 4, 3, 0)
        assert pad.degrees == (0, 3, 2, 0)  # играет старое до границы ступени

    def test_empty_is_error_and_state_kept(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        before = pad.degrees
        result = ctl.set_track_degrees(pad.name, [])
        assert result.error
        assert pad.degrees == before

    def test_out_of_range_is_error(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        assert ctl.set_track_degrees(pad.name, [99]).error

    def test_unknown_track_is_error(self) -> None:
        ctl, _ = make_control()
        assert ctl.set_track_degrees("Nope", [0]).error

    def test_drum_track_is_error(self) -> None:
        ctl, session = make_control()
        drum = session.create_drum_track()
        assert ctl.set_track_degrees(drum.name, [0]).error

    def test_cc_only_track_is_error(self) -> None:
        ctl, session = make_control()
        cc = session.create_melodic_track("cc_filter")
        result = ctl.set_track_degrees(cc.name, [0, 3])
        assert result.error
        assert "cc_only" in result.message


class TestSetTrackVoicing:
    def test_valid(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_voicing(pad.name, "1-3-5-7")
        assert not result.error
        assert pad.voicing == "1-3-5-7"

    def test_unknown_is_error_and_state_kept(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_voicing(pad.name, "nonsense")
        assert result.error
        assert pad.voicing == "1-3-5"

    def test_cc_only_is_error(self) -> None:
        ctl, session = make_control()
        cc = session.create_melodic_track("cc_space")
        assert ctl.set_track_voicing(cc.name, "1-3-5").error


class TestSetTrackInversion:
    def test_valid(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_inversion(pad.name, 1)
        assert not result.error
        assert pad.inversion == 1

    def test_out_of_range_is_error(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")  # 1-3-5: допустимо 0..2
        result = ctl.set_track_inversion(pad.name, 5)
        assert result.error
        assert pad.inversion == 0


class TestSetTrackProfile:
    def test_switch_within_notes(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad", degrees=[0, 3])
        result = ctl.set_track_profile(pad.name, "atmos")
        assert not result.error
        assert result.message == f'track "{pad.name}": profile pad -> atmos'
        assert pad.profile_name == "atmos"
        assert pad.voicing == "1-3-5-7"  # дефолт нового профиля
        assert pad.degrees == (0, 3)  # прогрессия пользователя сохранена

    def test_unknown_profile_is_error(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        assert ctl.set_track_profile(pad.name, "nope").error
        assert pad.profile_name == "pad"

    def test_cc_only_boundary_is_error(self) -> None:
        ctl, session = make_control()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_profile(pad.name, "cc_filter")
        assert result.error
        assert "restart" in result.message
        assert pad.profile_name == "pad"

    def test_cc_to_notes_is_error(self) -> None:
        ctl, session = make_control()
        cc = session.create_melodic_track("cc_filter")
        assert ctl.set_track_profile(cc.name, "lead").error
        assert cc.profile_name == "cc_filter"

    def test_family_switch_changes_generated_notes(self) -> None:
        """pad (аккорды) -> lead (линия) без пересборки движка меняет звук.

        Движок создаётся один раз и не пересобирается: generate_notes читает
        track.profile на каждом вызове.
        """
        ctl, session = make_control()
        pad = session.create_melodic_track("pad", degrees=[0, 3])
        engine = MelodicEngine(pad, Harmony("A", "dorian"), queue.Queue(), "default")
        before, _ = engine._pattern()
        assert len(before) == 6  # 2 ступени x аккорд 1-3-5

        assert not ctl.set_track_profile(pad.name, "lead").error
        after, _ = engine._pattern()
        assert len(after) == 2  # одна нота на ступень
