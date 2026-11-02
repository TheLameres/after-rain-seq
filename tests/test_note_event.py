"""Тесты для NoteEvent — нота в ступенях лада."""

from __future__ import annotations

from src.session.events.note_event import NoteEvent


class TestNoteEvent:
    """Тесты для NoteEvent."""

    def test_frozen(self) -> None:
        """NoteEvent — frozen dataclass."""
        note = NoteEvent(beat=0.0, degree=0, velocity=100, duration=1.0)
        try:
            note.velocity = 90  # type: ignore[misc]
        except AttributeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("NoteEvent не frozen")

    def test_fields(self) -> None:
        """Поля сохраняют значения."""
        note = NoteEvent(beat=0.5, degree=3, velocity=90, duration=0.25)
        assert note.beat == 0.5
        assert note.degree == 3
        assert note.velocity == 90
        assert note.duration == 0.25

    def test_equality(self) -> None:
        """Равенство по значениям."""
        a = NoteEvent(beat=0.0, degree=0, velocity=100, duration=1.0)
        b = NoteEvent(beat=0.0, degree=0, velocity=100, duration=1.0)
        c = NoteEvent(beat=1.0, degree=0, velocity=100, duration=1.0)
        assert a == b
        assert a != c

    def test_hashable(self) -> None:
        """NoteEvent можно класть в set (frozen)."""
        a = NoteEvent(beat=0.0, degree=0, velocity=100, duration=1.0)
        b = NoteEvent(beat=0.0, degree=0, velocity=100, duration=1.0)
        assert len({a, b}) == 1

    def test_repr(self) -> None:
        """repr содержит значения."""
        note = NoteEvent(beat=0.0, degree=2, velocity=100, duration=1.0)
        r = repr(note)
        assert "degree=2" in r
        assert "velocity=100" in r
