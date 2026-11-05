"""Voicing и октава: фасад, REPL, GEN (E7 — voicing, E8 — octave) и экран Push 2."""

from __future__ import annotations

import dataclasses
import queue

import pytest

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.devices.push2.layout import List, Range
from src.devices.push2.screens import TrackGenScreen
from src.harmony.voicings import VOICING_NAMES
from src.repl.executor import CommandExecutor
from src.session.model.melodic_track import MAX_OCTAVE
from src.session.session import Session
from tests.test_screen_controller import btn, enc, make_controller, make_track


def _facade() -> tuple[AppEngineControl, Session]:
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    return AppEngineControl(app), app._session


def _repl() -> tuple[CommandExecutor, Session]:
    ctl, session = _facade()
    return CommandExecutor(ctl), session


class TestFacadeOctave:
    def test_sets_octave(self) -> None:
        ctl, session = _facade()
        pad = session.create_melodic_track("pad")
        result = ctl.set_track_octave(pad.name, 3)
        assert not result.error
        assert pad.octave == 3
        assert result.message == f'track "{pad.name}": octave = 3'

    @pytest.mark.parametrize("bad", [-1, MAX_OCTAVE + 1])
    def test_out_of_range_is_error_and_state_kept(self, bad: int) -> None:
        ctl, session = _facade()
        pad = session.create_melodic_track("pad")
        before = pad.octave
        assert ctl.set_track_octave(pad.name, bad).error
        assert pad.octave == before

    def test_boundaries_accepted(self) -> None:
        ctl, session = _facade()
        pad = session.create_melodic_track("pad")
        assert not ctl.set_track_octave(pad.name, 0).error
        assert not ctl.set_track_octave(pad.name, MAX_OCTAVE).error

    def test_cc_only_track_is_error(self) -> None:
        ctl, session = _facade()
        cc = session.create_melodic_track("cc_filter")
        assert ctl.set_track_octave(cc.name, 4).error

    def test_drum_track_is_error(self) -> None:
        ctl, session = _facade()
        drum = session.create_drum_track()
        assert ctl.set_track_octave(drum.name, 4).error


class TestReplOctaveAndVoicing:
    def test_octave_command(self) -> None:
        ex, session = _repl()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track octave {pad.name} 6")
        assert res.code == 0
        assert pad.octave == 6

    def test_octave_name_with_space(self) -> None:
        ex, session = _repl()
        first = session.create_melodic_track("pad")
        session.create_melodic_track("pad")
        default_octave = first.octave
        res = ex.execute("track octave Pad 2 2")
        assert res.code == 0, res.output
        assert session.get_track("Pad 2").octave == 2
        assert first.octave == default_octave

    def test_octave_out_of_range_reports_error(self) -> None:
        ex, session = _repl()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track octave {pad.name} 9")
        assert res.code == 1
        assert res.output.startswith("error:")

    def test_octave_not_a_number(self) -> None:
        ex, session = _repl()
        pad = session.create_melodic_track("pad")
        res = ex.execute(f"track octave {pad.name} high")
        assert res.code == 1
        assert "not a number" in res.output

    def test_voicing_command_sets_voicing(self) -> None:
        ex, session = _repl()
        pad = session.create_melodic_track("pad")
        assert ex.execute(f"track voicing {pad.name} 1-3-5-7").code == 0
        assert pad.voicing == "1-3-5-7"

    def test_voicings_list_contains_all_names(self) -> None:
        ex, _ = _repl()
        names = ex.execute("voicings").output.removeprefix("voicings: ").split(", ")
        assert names == list(VOICING_NAMES)


def _gen(voicing: str | None = None, octave: int = 5, profile: str = "pad"):
    track = make_track("A", profile=profile)
    track = dataclasses.replace(
        track, voicing=track.voicing if voicing is None else voicing, octave=octave
    )
    ctl, engine, _ = make_controller((track,))
    btn(ctl, "Clip")
    return ctl, engine


class TestGenEncodersE7E8:
    def test_e7_steps_to_next_voicing(self) -> None:
        ctl, engine = _gen(voicing="1-3-5")
        enc(ctl, 7, inc=1)
        assert engine.called("set_track_voicing") == [
            ("A", VOICING_NAMES[VOICING_NAMES.index("1-3-5") + 1])
        ]

    def test_e7_backward(self) -> None:
        ctl, engine = _gen(voicing="1-3-5")
        enc(ctl, 7, inc=-1)
        assert engine.called("set_track_voicing") == [
            ("A", VOICING_NAMES[VOICING_NAMES.index("1-3-5") - 1])
        ]

    def test_e7_wraps_at_end(self) -> None:
        last = VOICING_NAMES[-1]
        ctl, engine = _gen(voicing=last)
        enc(ctl, 7, inc=1)
        assert engine.called("set_track_voicing") == [("A", VOICING_NAMES[0])]

    def test_e8_increments_octave(self) -> None:
        ctl, engine = _gen(octave=5)
        enc(ctl, 8, inc=1)
        assert engine.called("set_track_octave") == [("A", 6)]

    def test_e8_clamps_at_top(self) -> None:
        ctl, engine = _gen(octave=MAX_OCTAVE)
        enc(ctl, 8, inc=2)
        assert engine.called("set_track_octave") == [("A", MAX_OCTAVE)]

    def test_e8_clamps_at_bottom(self) -> None:
        ctl, engine = _gen(octave=0)
        enc(ctl, 8, inc=-3)
        assert engine.called("set_track_octave") == [("A", 0)]

    def test_e8_zero_increment_sends_nothing(self) -> None:
        ctl, engine = _gen(octave=5)
        enc(ctl, 8, inc=0)
        assert engine.called("set_track_octave") == []

    def test_cc_only_track_ignores_e7_e8(self) -> None:
        ctl, engine = _gen(voicing="", profile="cc_filter")
        enc(ctl, 7, inc=1)
        enc(ctl, 8, inc=1)
        assert engine.called("set_track_voicing") == []
        assert engine.called("set_track_octave") == []

    def test_e6_still_cycles_preset_not_voicing(self) -> None:
        ctl, engine = _gen()
        enc(ctl, 6, inc=1)
        assert engine.called("set_track_voicing") == []
        assert engine.called("set_track_degrees") != []


class TestGenLayout:
    def _layout(self, *, voicing: str, octave: int | None, kind: str = "melodic"):
        from src.devices.display_state import ScreenView, TrackDetailView

        detail = TrackDetailView(
            name="A",
            kind=kind,
            profile="pad",
            channel=0,
            port="Synth",
            sources=(),
            gate=0.9,
            voicing=voicing,
            density=None,
            mutate=0.5,
            degrees=(0, 3),
            preset="",
            octave=octave,
        )
        return TrackGenScreen().layout(
            ScreenView(screen="gen", title="", flash=None, track=detail)
        )

    def test_e7_is_voicing_list_with_cursor(self) -> None:
        e7 = self._layout(voicing="1-3-5", octave=5).encoders[6]
        assert isinstance(e7, List)
        assert e7.options == VOICING_NAMES
        assert e7.options[e7.index] == "1-3-5"

    def test_e8_is_octave_range(self) -> None:
        e8 = self._layout(voicing="1-3-5", octave=5).encoders[7]
        assert isinstance(e8, Range)
        assert e8.value == 5.0
        assert e8.hi == float(MAX_OCTAVE)
        assert e8.unit == ""

    def test_drum_or_cc_shows_no_voicing_and_no_octave(self) -> None:
        layout = self._layout(voicing="", octave=None, kind="drum")
        e7, e8 = layout.encoders[6], layout.encoders[7]
        assert not isinstance(e7, List)
        assert isinstance(e8, Range) and e8.value is None


class TestEndToEndVoicingPlays:
    """Смена voicing через фасад меняет ноты, которые строит движок."""

    def test_voicing_change_changes_chord_size(self) -> None:
        from src.harmony.harmony import Harmony
        from src.session.engine.melodic_engine import MelodicEngine

        ctl, session = _facade()
        pad = session.create_melodic_track("pad", degrees=[0])
        engine = MelodicEngine(pad, Harmony("A", "dorian"), queue.Queue(), "main")
        before, _ = engine._pattern()
        assert ctl.set_track_voicing(pad.name, "1-3-5-7").error is False
        after, _ = engine._pattern()
        assert len(before) == 3 and len(after) == 4
