"""Tests for DrumEvent — value object drum-события."""

import pytest

from src.session.events.drum_event import DrumEvent


def test_drum_event_fields():
    """DrumEvent — frozen dataclass с полями beat/note/velocity/lane/duration."""
    ev = DrumEvent(beat=0.0, note=36, velocity=100, lane_index=0, duration=0.25)
    assert ev.beat == 0.0
    assert ev.note == 36
    assert ev.velocity == 100
    assert ev.lane_index == 0
    assert ev.duration == 0.25


def test_drum_event_frozen():
    """Frozen dataclass не позволяет менять поля."""
    ev = DrumEvent(beat=0.0, note=36, velocity=100, lane_index=0, duration=0.25)
    with pytest.raises(AttributeError):
        ev.note = 38  # type: ignore[misc]


def test_drum_event_different_lanes():
    """Разные лейны — разные события."""
    kick = DrumEvent(beat=0.0, note=36, velocity=100, lane_index=0, duration=0.25)
    snare = DrumEvent(beat=0.5, note=38, velocity=120, lane_index=2, duration=0.25)
    assert kick.note != snare.note
    assert kick.lane_index != snare.lane_index
