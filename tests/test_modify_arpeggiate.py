"""Тесты этапа Arpeggiate (§5.3)."""

from __future__ import annotations

import itertools

import pytest

from src.session.events.note_event import NoteEvent
from src.session.modify import Chain, StageContext
from src.session.modify.arpeggiate import ArpeggiateStage

CTX = StageContext(beat=0.0, bpm=120.0, track_name="Pad 1")


def _note(
    beat: float, degree: int, duration: float = 1.0, velocity: int = 100
) -> NoteEvent:
    return NoteEvent(beat=beat, degree=degree, velocity=velocity, duration=duration)


def _chord(
    beat: float, degrees: tuple[int, ...], duration: float = 1.0
) -> list[NoteEvent]:
    return [_note(beat, d, duration) for d in degrees]


class TestValidation:
    def test_step_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="step"):
            ArpeggiateStage(step=0.0)

    def test_negative_step_rejected(self) -> None:
        with pytest.raises(ValueError, match="step"):
            ArpeggiateStage(step=-0.25)

    def test_unknown_direction_rejected(self) -> None:
        with pytest.raises(ValueError, match="направление"):
            ArpeggiateStage(direction="sideways")

    @pytest.mark.parametrize("direction", ["up", "down", "updown"])
    def test_known_directions_accepted(self, direction: str) -> None:
        assert ArpeggiateStage(direction=direction).direction == direction


class TestUp:
    def test_chord_becomes_sequence(self) -> None:
        out = Chain([ArpeggiateStage(step=0.25)]).process(_chord(0.0, (0, 2, 4)), CTX)
        assert [round(e.beat, 6) for e in out] == [0.0, 0.25, 0.5]
        assert [e.degree for e in out] == [0, 2, 4]

    def test_all_notes_kept(self) -> None:
        src = _chord(0.0, (0, 2, 4, 7))
        out = Chain([ArpeggiateStage(step=0.25)]).process(src, CTX)
        assert len(out) == len(src)

    def test_duration_equals_step(self) -> None:
        """Иначе ноты наложатся и снова прозвучит аккорд."""
        out = Chain([ArpeggiateStage(step=0.25)]).process(_chord(0.0, (0, 2, 4)), CTX)
        assert all(e.duration == 0.25 for e in out)

    def test_no_overlap_between_notes(self) -> None:
        out = Chain([ArpeggiateStage(step=0.25)]).process(
            _chord(0.0, (0, 2, 4, 7)), CTX
        )
        for prev, nxt in itertools.pairwise(out):
            assert prev.beat + prev.duration <= nxt.beat + 1e-9

    def test_velocity_preserved(self) -> None:
        src = [
            NoteEvent(beat=0.0, degree=0, velocity=127, duration=1.0),
            NoteEvent(beat=0.0, degree=4, velocity=60, duration=1.0),
        ]
        out = Chain([ArpeggiateStage(step=0.25)]).process(src, CTX)
        assert [e.velocity for e in out] == [127, 60]

    def test_octave_offset_preserved(self) -> None:
        src = [
            NoteEvent(beat=0.0, degree=0, velocity=100, duration=1.0, octave_offset=1),
            NoteEvent(beat=0.0, degree=4, velocity=100, duration=1.0, octave_offset=1),
        ]
        out = Chain([ArpeggiateStage(step=0.25)]).process(src, CTX)
        assert all(e.octave_offset == 1 for e in out)


class TestDown:
    def test_descending_order(self) -> None:
        out = Chain([ArpeggiateStage(step=0.25, direction="down")]).process(
            _chord(0.0, (0, 2, 4)), CTX
        )
        assert [e.degree for e in out] == [4, 2, 0]
        assert [round(e.beat, 6) for e in out] == [0.0, 0.25, 0.5]


class TestUpDown:
    def test_no_repeated_extremes(self) -> None:
        out = Chain([ArpeggiateStage(step=0.25, direction="updown")]).process(
            _chord(0.0, (0, 2, 4)), CTX
        )
        # 0,2,4 вверх и 2 вниз — крайние не дублируются
        assert [e.degree for e in out] == [0, 2, 4, 2]

    def test_single_note_unchanged(self) -> None:
        out = Chain([ArpeggiateStage(direction="updown")]).process(
            _chord(0.0, (5,)), CTX
        )
        assert [e.degree for e in out] == [5]

    def test_two_notes_do_not_duplicate(self) -> None:
        out = Chain([ArpeggiateStage(step=0.25, direction="updown")]).process(
            _chord(0.0, (0, 4)), CTX
        )
        assert [e.degree for e in out] == [0, 4]


class TestDoesNotEatNextChord:
    def test_step_shrinks_to_fit(self) -> None:
        """Аккорд не должен налезать на следующий onset."""
        batch = _chord(0.0, (0, 2, 4, 7)) + _chord(0.5, (1, 3, 5))
        out = Chain([ArpeggiateStage(step=0.5)]).process(batch, CTX)
        first = [e for e in out if e.beat < 0.5]
        assert len(first) == 4
        # 0.5 / 4 ноты = 0.125 на ноту
        assert [round(e.beat, 6) for e in first] == [0.0, 0.125, 0.25, 0.375]
        assert all(e.beat + e.duration <= 0.5 + 1e-9 for e in first)

    def test_last_chord_uses_full_step(self) -> None:
        """После последнего аккорда растягивать некуда — шаг как задан."""
        out = Chain([ArpeggiateStage(step=0.25)]).process(_chord(0.0, (0, 2, 4)), CTX)
        assert [round(e.beat, 6) for e in out] == [0.0, 0.25, 0.5]

    def test_no_crossing_into_next_chord(self) -> None:
        batch = _chord(0.0, (0, 2, 4, 7, 9)) + _chord(0.25, (1, 3))
        out = Chain([ArpeggiateStage(step=1.0)]).process(batch, CTX)
        early = [e for e in out if e.beat < 0.25]
        assert {e.degree for e in early} == {0, 2, 4, 7, 9}
        assert all(e.beat < 0.25 for e in early)


class TestMultipleChords:
    def test_each_chord_arpeggiated(self) -> None:
        batch = _chord(0.0, (0, 4)) + _chord(2.0, (1, 5))
        out = Chain([ArpeggiateStage(step=0.25)]).process(batch, CTX)
        assert [round(e.beat, 6) for e in out] == [0.0, 0.25, 2.0, 2.25]
        assert [e.degree for e in out] == [0, 4, 1, 5]

    def test_output_sorted(self) -> None:
        batch = _chord(1.0, (2, 0)) + _chord(0.0, (5, 3))
        out = Chain([ArpeggiateStage(step=0.25)]).process(batch, CTX)
        beats = [e.beat for e in out]
        assert beats == sorted(beats)


class TestPassThrough:
    def test_empty(self) -> None:
        assert Chain([ArpeggiateStage()]).process([], CTX) == []

    def test_single_event_unchanged(self) -> None:
        src = [_note(0.0, 3)]
        out = Chain([ArpeggiateStage()]).process(src, CTX)
        assert out == src

    def test_monophonic_line_unchanged(self) -> None:
        """У lead/bass по одной ноте на beat — трогать нечего."""
        src = [_note(0.0, 0), _note(1.0, 2), _note(2.0, 4)]
        out = Chain([ArpeggiateStage(step=0.5)]).process(src, CTX)
        assert out == src

    def test_input_not_mutated(self) -> None:
        src = _chord(0.0, (0, 2, 4))
        snapshot = list(src)
        Chain([ArpeggiateStage(step=0.25)]).process(src, CTX)
        assert src == snapshot


class TestFloatGrouping:
    def test_near_equal_beats_form_one_chord(self) -> None:
        """Ноты одного аккорда могут отличаться на ulp — это не два аккорда."""
        src = [
            NoteEvent(beat=0.1 + 0.2, degree=0, velocity=100, duration=1.0),
            NoteEvent(beat=0.30000000000000004, degree=4, velocity=100, duration=1.0),
        ]
        out = Chain([ArpeggiateStage(step=0.25)]).process(src, CTX)
        assert len({round(e.beat - out[0].beat, 6) for e in out}) == 2


class TestWithDensify:
    def test_composes_in_chain(self) -> None:
        from src.session.modify.densify import DensifyStage

        batch = _chord(0.0, (0, 2, 4)) + _chord(1.0, (1, 3, 5))
        out = Chain([ArpeggiateStage(step=0.25), DensifyStage(1.0)]).process(batch, CTX)
        assert len(out) == 6

    def test_names_in_order(self) -> None:
        from src.session.modify.densify import DensifyStage

        chain = Chain([ArpeggiateStage(), DensifyStage(1.0)])
        assert chain.names == ("arpeggiate", "densify")


class TestUpDownFitsNextChord:
    """updown добавляет ноты — защита от наезда должна считать их все."""

    def test_six_notes_fit_before_next_chord(self) -> None:
        batch = _chord(0.0, (0, 2, 4, 7)) + _chord(0.5, (1, 3))
        out = Chain([ArpeggiateStage(step=0.25, direction="updown")]).process(
            batch, CTX
        )
        first = [e for e in out if e.beat < 0.5]
        assert len(first) == 6  # 4 вверх + 2 вниз (крайние не дублируются)
        assert [e.degree for e in first] == [0, 2, 4, 7, 4, 2]
        # шаг = 0.5 / 6, последняя нота заканчивается ровно на границе
        assert first[1].beat - first[0].beat == pytest.approx(0.5 / 6)
        assert first[-1].beat + first[-1].duration == pytest.approx(0.5)
