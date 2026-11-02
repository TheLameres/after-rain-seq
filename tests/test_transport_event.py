"""Tests for TransportEvent — MIDI event in the transport queue."""

from __future__ import annotations

import pytest

from src.sync.transport_event import EventKind, TransportEvent


class TestEventKind:
    """Tests for the EventKind enum."""

    def test_four_kinds(self):
        """EventKind has exactly four members."""
        assert len(EventKind) == 4
        assert EventKind.NOTE_ON is not None
        assert EventKind.NOTE_OFF is not None
        assert EventKind.CONTROL_CHANGE is not None
        assert EventKind.ALL_NOTES_OFF is not None


class TestTransportEvent:
    """Tests for the TransportEvent dataclass."""

    def test_frozen(self):
        """TransportEvent is immutable."""
        evt = TransportEvent.note_on("A", channel=0, note=60, velocity=100)
        with pytest.raises(AttributeError):
            evt.note = 61  # type: ignore[misc]

    def test_note_on_constructor(self):
        """note_on classmethod creates a valid NOTE_ON event."""
        evt = TransportEvent.note_on(
            "Synth A", channel=2, note=60, velocity=100, duration=0.5, beat=4.0
        )
        assert evt.kind is EventKind.NOTE_ON
        assert evt.port_label == "Synth A"
        assert evt.channel == 2
        assert evt.note == 60
        assert evt.velocity == 100
        assert evt.duration == 0.5
        assert evt.beat == 4.0
        assert evt.control is None
        assert evt.value is None

    def test_note_off_constructor(self):
        """note_off classmethod creates a valid NOTE_OFF event."""
        evt = TransportEvent.note_off("Synth A", channel=2, note=60, beat=4.5)
        assert evt.kind is EventKind.NOTE_OFF
        assert evt.port_label == "Synth A"
        assert evt.channel == 2
        assert evt.note == 60
        assert evt.velocity is None
        assert evt.duration is None
        assert evt.beat == 4.5

    def test_control_change_constructor(self):
        """control_change classmethod creates a valid CONTROL_CHANGE event."""
        evt = TransportEvent.control_change(
            "Synth B", channel=3, control=74, value=64, beat=8.0
        )
        assert evt.kind is EventKind.CONTROL_CHANGE
        assert evt.port_label == "Synth B"
        assert evt.channel == 3
        assert evt.control == 74
        assert evt.value == 64
        assert evt.note is None
        assert evt.velocity is None
        assert evt.beat == 8.0

    def test_all_notes_off_constructor(self):
        """all_notes_off classmethod creates a valid ALL_NOTES_OFF event."""
        evt = TransportEvent.all_notes_off("Synth A")
        assert evt.kind is EventKind.ALL_NOTES_OFF
        assert evt.port_label == "Synth A"
        assert evt.channel == 0  # default
        assert evt.note is None
        assert evt.velocity is None
        assert evt.control is None
        assert evt.value is None

    def test_int_conversion_in_constructors(self):
        """Constructors convert float/numpy-like values to int."""
        # Simulating numpy.int64 — any object with __int__ works
        evt = TransportEvent.note_on("A", channel=0, note=60.0, velocity=100.0)  # type: ignore[arg-type]
        assert isinstance(evt.note, int)
        assert isinstance(evt.velocity, int)
        assert evt.note == 60
        assert evt.velocity == 100

    def test_default_channel_is_zero(self):
        """Default channel is 0."""
        evt = TransportEvent(kind=EventKind.NOTE_ON, port_label="A")
        assert evt.channel == 0

    def test_default_beat_is_zero(self):
        """Default beat is 0.0."""
        evt = TransportEvent(kind=EventKind.NOTE_ON, port_label="A")
        assert evt.beat == 0.0

    def test_equality(self):
        """Two events with same fields are equal."""
        e1 = TransportEvent.note_on("A", channel=0, note=60, velocity=100)
        e2 = TransportEvent.note_on("A", channel=0, note=60, velocity=100)
        assert e1 == e2

    def test_inequality(self):
        """Events with different fields are not equal."""
        e1 = TransportEvent.note_on("A", channel=0, note=60, velocity=100)
        e2 = TransportEvent.note_on("A", channel=0, note=61, velocity=100)
        assert e1 != e2

    def test_hashable(self):
        """TransportEvent can be used as dict key / in set."""
        evt = TransportEvent.note_on("A", channel=0, note=60, velocity=100)
        d = {evt: "test"}
        assert d[evt] == "test"
