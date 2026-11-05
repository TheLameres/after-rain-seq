"""Пресеты прогрессий на Push 2: E6 на экране GEN и отображение (словарь progressions)."""

from __future__ import annotations

import pytest

from src.devices.display_state import TrackDetailView
from src.devices.push2.layout import List
from src.devices.push2.screens import TrackGenScreen
from src.harmony import progressions
from src.harmony.progressions import PROGRESSIONS, next_progression
from src.session.model.melodic_track import MelodicTrack
from tests.test_screen_controller import btn, enc, make_controller, make_track

POP = (0, 4, 5, 3)
CLASSIC = (0, 3, 4, 0)
CANON = (0, 4, 5, 2, 3, 0, 3, 4)


def _gen(tracks, degrees):
    """Контроллер с дорожкой A на экране GEN; ступени дорожки заданы в снимке."""
    tracks = tuple(t.__class__(**{**t.__dict__, "degrees": degrees}) for t in tracks)
    ctl, engine, _sent = make_controller(tracks)
    btn(ctl, "Clip")
    return ctl, engine


class TestPresetDictionary:
    def test_names_are_unique(self) -> None:
        names = [p.name for p in PROGRESSIONS]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("preset", PROGRESSIONS, ids=lambda p: p.name)
    def test_each_preset_is_valid_melodic_degrees(self, preset) -> None:
        track = MelodicTrack(name="T", profile_name="pad", degrees=list(preset.degrees))
        assert track.degrees == preset.degrees

    def test_known_romans(self) -> None:
        assert progressions.PROGRESSIONS[0].roman == "I V VI IV"
        assert progressions.PROGRESSIONS[1].roman == "I IV V I"

    def test_name_of(self) -> None:
        assert progressions.name_of(POP) == "Pop"
        assert progressions.name_of((1, 2, 3)) == ""


class TestNextProgression:
    def test_forward(self) -> None:
        assert next_progression(CLASSIC, 1).degrees == (5, 3, 0, 4)  # Sad

    def test_backward(self) -> None:
        assert next_progression(CLASSIC, -1).degrees == POP

    def test_wraps_forward_from_last(self) -> None:
        assert next_progression(CANON, 1).degrees == POP

    def test_wraps_backward_from_first(self) -> None:
        assert next_progression(POP, -1).degrees == CANON

    def test_custom_forward_takes_first(self) -> None:
        assert next_progression((1, 2), 1).degrees == POP

    def test_custom_backward_takes_last(self) -> None:
        assert next_progression((1, 2), -1).degrees == CANON


class TestGenEncoderE6:
    def test_e6_switches_to_next_preset(self) -> None:
        ctl, engine = _gen((make_track("A"),), CLASSIC)
        enc(ctl, 6, inc=1)
        assert engine.called("set_track_degrees") == [("A", (5, 3, 0, 4))]  # Sad

    def test_e6_backward(self) -> None:
        ctl, engine = _gen((make_track("A"),), CLASSIC)
        enc(ctl, 6, inc=-1)
        assert engine.called("set_track_degrees") == [("A", POP)]

    def test_e6_zero_increment_is_noop(self) -> None:
        ctl, engine = _gen((make_track("A"),), CLASSIC)
        enc(ctl, 6, inc=0)
        assert engine.called("set_track_degrees") == []

    def test_e6_on_custom_degrees_starts_from_first(self) -> None:
        ctl, engine = _gen((make_track("A"),), (1, 2))
        enc(ctl, 6, inc=1)
        assert engine.called("set_track_degrees") == [("A", POP)]

    def test_e6_does_not_touch_other_gen_encoders(self) -> None:
        ctl, engine = _gen((make_track("A"),), CLASSIC)
        enc(ctl, 6, inc=1)
        assert engine.called("set_track_gate") == []
        assert engine.called("set_track_mutate") == []


class TestGenScreenShowsPreset:
    def _view(self, degrees) -> TrackDetailView:
        return TrackDetailView(
            name="A",
            kind="melodic",
            profile="pad",
            channel=0,
            port="Synth",
            sources=(),
            gate=0.9,
            voicing="1-3-5",
            density=None,
            mutate=0.5,
            degrees=degrees,
            preset=progressions.name_of(degrees),
        )

    def _layout(self, detail: TrackDetailView):
        from src.devices.display_state import ScreenView

        view = ScreenView(screen="gen", title="", flash=None, track=detail)
        return TrackGenScreen().layout(view)

    def test_preset_name_on_e6(self) -> None:
        layout = self._layout(self._view(POP))
        assert "Pop" in repr(layout.encoders[5])

    def test_custom_label_when_not_a_preset(self) -> None:
        layout = self._layout(self._view((1, 2)))
        assert "custom" in repr(layout.encoders[5])

    def test_roman_degrees_in_foot(self) -> None:
        layout = self._layout(self._view(POP))
        assert "I V VI IV" in repr(layout.foot)


class TestE6IsAListLikeSrc:
    """E6 — тот же виджет List, что SRC (E1): пункты и курсор на текущем значении."""

    def _e6(self, degrees) -> List:
        view = TestGenScreenShowsPreset()._view(degrees)
        layout = TestGenScreenShowsPreset()._layout(view)
        return layout.encoders[5]

    def test_same_widget_as_src(self) -> None:
        view = TestGenScreenShowsPreset()._view(POP)
        layout = TestGenScreenShowsPreset()._layout(view)
        assert isinstance(layout.encoders[0], List)
        assert isinstance(layout.encoders[5], List)

    def test_lists_all_presets(self) -> None:
        e6 = self._e6(POP)
        assert e6.options == tuple(p.name for p in PROGRESSIONS)

    def test_cursor_on_current_preset(self) -> None:
        e6 = self._e6(CLASSIC)
        assert e6.options[e6.index] == "Classic"

    def test_custom_adds_row_with_cursor(self) -> None:
        e6 = self._e6((1, 2))
        assert e6.options[-1] == "custom"
        assert e6.index == len(e6.options) - 1

    def test_no_custom_row_for_preset(self) -> None:
        e6 = self._e6(POP)
        assert "custom" not in e6.options
