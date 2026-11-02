"""Tests for CaptureOutput — isobar OutputDevice that captures events."""

from __future__ import annotations

import queue

import numpy as np
import pytest

from src.sync.capture_output import CaptureOutput
from src.sync.transport_event import EventKind, TransportEvent


@pytest.fixture()
def event_queue() -> queue.Queue[TransportEvent]:
    """Fresh event queue with small size for overflow testing."""
    return queue.Queue(maxsize=100)


@pytest.fixture()
def capture(event_queue: queue.Queue[TransportEvent]) -> CaptureOutput:
    """Fresh CaptureOutput instance."""
    return CaptureOutput(event_queue, port_label="Synth A")


def _drain(q: queue.Queue[TransportEvent]) -> list[TransportEvent]:
    """Remove and return all items from a queue."""
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


class TestCaptureOutputInterface:
    """Tests for the isobar OutputDevice interface."""

    def test_ticks_per_beat_is_none(self, capture: CaptureOutput):
        """ticks_per_beat returns None (no clock multiplier)."""
        assert capture.ticks_per_beat is None

    def test_tick_is_noop(self, capture: CaptureOutput, event_queue):
        """tick() does not enqueue anything."""
        capture.tick()
        assert event_queue.empty()

    def test_start_is_noop(self, capture: CaptureOutput, event_queue):
        """start() does not enqueue anything."""
        capture.start()
        assert event_queue.empty()

    def test_stop_is_noop(self, capture: CaptureOutput, event_queue):
        """stop() does not enqueue anything."""
        capture.stop()
        assert event_queue.empty()

    def test_port_label_property(self, capture: CaptureOutput):
        """port_label returns the configured label."""
        assert capture.port_label == "Synth A"

    def test_beat_property_default(self, capture: CaptureOutput):
        """beat defaults to 0.0."""
        assert capture.beat == 0.0

    def test_beat_setter(self, capture: CaptureOutput):
        """beat can be updated."""
        capture.beat = 4.5
        assert capture.beat == 4.5

    def test_repr(self, capture: CaptureOutput):
        """repr includes port_label."""
        assert "Synth A" in repr(capture)


class TestCaptureNoteEvents:
    """Tests for note_on / note_off capture."""

    def test_note_on_enqueues_event(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """note_on places a NOTE_ON event in the queue."""
        capture.note_on(note=60, velocity=100, channel=2)
        events = _drain(event_queue)
        assert len(events) == 1
        evt = events[0]
        assert evt.kind is EventKind.NOTE_ON
        assert evt.port_label == "Synth A"
        assert evt.channel == 2
        assert evt.note == 60
        assert evt.velocity == 100

    def test_note_off_enqueues_event(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """note_off places a NOTE_OFF event in the queue."""
        capture.note_off(note=60, channel=2)
        events = _drain(event_queue)
        assert len(events) == 1
        evt = events[0]
        assert evt.kind is EventKind.NOTE_OFF
        assert evt.channel == 2
        assert evt.note == 60
        assert evt.velocity is None

    def test_note_on_default_args(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """note_on works with default arguments."""
        capture.note_on()
        events = _drain(event_queue)
        assert len(events) == 1
        assert events[0].note == 60  # isobar default
        assert events[0].velocity == 64  # isobar default
        assert events[0].channel == 0

    def test_note_on_positional_args(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """note_on accepts positional args (isobar calling convention)."""
        capture.note_on(72, 90, 3)
        events = _drain(event_queue)
        assert events[0].note == 72
        assert events[0].velocity == 90
        assert events[0].channel == 3

    def test_note_off_positional_args(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """note_off accepts positional args (isobar calling convention)."""
        capture.note_off(72, 3)
        events = _drain(event_queue)
        assert events[0].note == 72
        assert events[0].channel == 3

    def test_beat_propagated_to_events(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """Events carry the current beat position."""
        capture.beat = 7.5
        capture.note_on(note=60, velocity=100, channel=0)
        events = _drain(event_queue)
        assert events[0].beat == 7.5


class TestCaptureControlEvents:
    """Tests for control_change capture."""

    def test_control_enqueues_event(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """control() places a CONTROL_CHANGE event in the queue."""
        capture.control(control=74, value=64, channel=1)
        events = _drain(event_queue)
        assert len(events) == 1
        evt = events[0]
        assert evt.kind is EventKind.CONTROL_CHANGE
        assert evt.channel == 1
        assert evt.control == 74
        assert evt.value == 64

    def test_control_positional_args(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """control() accepts positional args (isobar calling convention)."""
        capture.control(74, 100, 5)
        events = _drain(event_queue)
        assert events[0].control == 74
        assert events[0].value == 100
        assert events[0].channel == 5


class TestCaptureAllNotesOff:
    """Tests for all_notes_off capture."""

    def test_all_notes_off_enqueues_event(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """all_notes_off() places an ALL_NOTES_OFF event in the queue."""
        capture.all_notes_off()
        events = _drain(event_queue)
        assert len(events) == 1
        assert events[0].kind is EventKind.ALL_NOTES_OFF
        assert events[0].port_label == "Synth A"


class TestIntConversion:
    """Tests for numpy.int64 → int conversion."""

    def test_numpy_int64_note(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """numpy.int64 values are converted to plain int."""
        capture.note_on(
            note=np.int64(60),  # type: ignore[arg-type]
            velocity=np.int64(100),  # type: ignore[arg-type]
            channel=np.int64(2),  # type: ignore[arg-type]
        )
        events = _drain(event_queue)
        evt = events[0]
        assert type(evt.note) is int
        assert type(evt.velocity) is int
        assert type(evt.channel) is int

    def test_numpy_int64_control(
        self, capture: CaptureOutput, event_queue: queue.Queue[TransportEvent]
    ):
        """numpy.int64 CC values are converted to plain int."""
        capture.control(
            control=np.int64(74),  # type: ignore[arg-type]
            value=np.int64(64),  # type: ignore[arg-type]
            channel=np.int64(0),  # type: ignore[arg-type]
        )
        events = _drain(event_queue)
        evt = events[0]
        assert type(evt.control) is int
        assert type(evt.value) is int
        assert type(evt.channel) is int


class TestQueueOverflow:
    """Tests for queue overflow behaviour."""

    def test_drop_oldest_on_full(self):
        """When queue is full, oldest event is dropped."""
        q: queue.Queue[TransportEvent] = queue.Queue(maxsize=2)
        capture = CaptureOutput(q, port_label="A")

        capture.note_on(note=60, velocity=100, channel=0)  # event 1
        capture.note_on(note=61, velocity=100, channel=0)  # event 2
        capture.note_on(note=62, velocity=100, channel=0)  # event 3 — overflow

        events = _drain(q)
        assert len(events) == 2
        # Oldest (note=60) dropped, newest two survive
        assert events[0].note == 61
        assert events[1].note == 62
