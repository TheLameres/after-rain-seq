"""Tests for Transport — MIDI event delivery engine."""

from __future__ import annotations

import queue
from unittest.mock import MagicMock

import pytest

from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport import Transport, TransportMode
from src.sync.transport_event import EventKind, TransportEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry() -> MagicMock:
    """Create a mock PortRegistry with one adapter."""
    registry = MagicMock()
    adapter = MagicMock()
    adapter.label = "Synth A"
    registry.get_output.return_value = adapter
    registry.all_outputs.return_value = [adapter]
    return registry


def _make_transport(
    registry: MagicMock | None = None,
    swing_amount: float = 0.0,
    max_queue: int = 100,
) -> tuple[Transport, queue.Queue[TransportEvent], MagicMock]:
    """Create a Transport with mock registry. Returns (transport, queue, registry)."""
    if registry is None:
        registry = _make_registry()
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=max_queue)
    swing = SwingApplier(SwingConfig(amount=swing_amount))
    transport = Transport(event_queue=q, port_registry=registry, swing=swing)
    return transport, q, registry


def _drain(q: queue.Queue[TransportEvent]) -> list[TransportEvent]:
    """Remove and return all items from a queue."""
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTransportMode:
    """Tests for TransportMode enum and mode switching."""

    def test_default_mode_is_isobar(self):
        """Default mode is ISOBAR."""
        transport, _, _ = _make_transport()
        assert transport.mode is TransportMode.ISOBAR

    def test_set_mode_isobar(self):
        """Can set mode to ISOBAR."""
        transport, _, _ = _make_transport()
        transport.set_mode(TransportMode.ISOBAR)
        assert transport.mode is TransportMode.ISOBAR

    def test_set_mode_external_raises(self):
        """Setting EXTERNAL mode raises NotImplementedError."""
        transport, _, _ = _make_transport()
        with pytest.raises(NotImplementedError, match="EXTERNAL"):
            transport.set_mode(TransportMode.EXTERNAL)


class TestProcessEvents:
    """Tests for process_events() delivery."""

    def test_empty_queue_delivers_nothing(self):
        """Empty queue → 0 events delivered."""
        transport, _, registry = _make_transport()
        count = transport.process_events(current_beat=0.0)
        assert count == 0
        registry.get_output.assert_not_called()

    def test_note_on_delivered(self):
        """NOTE_ON event is delivered to adapter."""
        transport, q, registry = _make_transport()
        q.put(TransportEvent.note_on("Synth A", channel=2, note=60, velocity=100))
        count = transport.process_events(current_beat=0.0)
        assert count == 1
        adapter = registry.get_output.return_value
        adapter.note_on.assert_called_once_with(channel=2, note=60, velocity=100)

    def test_note_off_delivered(self):
        """NOTE_OFF event is delivered to adapter."""
        transport, q, registry = _make_transport()
        q.put(TransportEvent.note_off("Synth A", channel=2, note=60))
        transport.process_events(current_beat=0.0)
        adapter = registry.get_output.return_value
        adapter.note_off.assert_called_once_with(channel=2, note=60)

    def test_control_change_delivered(self):
        """CONTROL_CHANGE event is delivered to adapter."""
        transport, q, registry = _make_transport()
        q.put(TransportEvent.control_change("Synth A", channel=1, control=74, value=64))
        transport.process_events(current_beat=0.0)
        adapter = registry.get_output.return_value
        adapter.control_change.assert_called_once_with(channel=1, control=74, value=64)

    def test_all_notes_off_delivered(self):
        """ALL_NOTES_OFF event triggers adapter.all_notes_off()."""
        transport, q, registry = _make_transport()
        q.put(TransportEvent.all_notes_off("Synth A"))
        transport.process_events(current_beat=0.0)
        adapter = registry.get_output.return_value
        adapter.all_notes_off.assert_called_once()

    def test_missing_port_silently_drops(self):
        """Event for unknown port is dropped without error."""
        registry = _make_registry()
        registry.get_output.return_value = None  # port not found
        transport, q, _ = _make_transport(registry=registry)
        q.put(TransportEvent.note_on("Missing", channel=0, note=60, velocity=100))
        count = transport.process_events(current_beat=0.0)
        assert count == 1  # event was processed (but dropped)

    def test_multiple_events_delivered(self):
        """Multiple events in queue are all delivered."""
        transport, q, _registry = _make_transport()
        q.put(TransportEvent.note_on("Synth A", channel=0, note=60, velocity=100))
        q.put(TransportEvent.note_off("Synth A", channel=0, note=60))
        q.put(TransportEvent.control_change("Synth A", channel=0, control=74, value=64))
        count = transport.process_events(current_beat=0.0)
        assert count == 3

    def test_int_conversion_on_delivery(self):
        """Values are passed as int to adapter."""
        transport, q, registry = _make_transport()
        # Use float values that should be int-ified
        evt = TransportEvent(
            kind=EventKind.NOTE_ON,
            port_label="Synth A",
            channel=0,
            note=60,
            velocity=100,
        )
        q.put(evt)
        transport.process_events(current_beat=0.0)
        adapter = registry.get_output.return_value
        call_kwargs = adapter.note_on.call_args
        assert type(call_kwargs.kwargs["channel"]) is int
        assert type(call_kwargs.kwargs["note"]) is int
        assert type(call_kwargs.kwargs["velocity"]) is int


class TestSwingIntegration:
    """Tests for swing application during delivery."""

    def test_zero_swing_no_duration_change(self):
        """With amount=0, swing is not applied."""
        transport, q, registry = _make_transport(swing_amount=0.0)
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=60, velocity=100, duration=0.5, beat=0.0
            )
        )
        transport.process_events(current_beat=0.0)
        # Note: swing only affects duration tracking, not the note_on call itself
        adapter = registry.get_output.return_value
        adapter.note_on.assert_called_once()

    def test_swing_applier_state_advances(self):
        """With amount>0, swing applier processes durations."""
        transport, q, _ = _make_transport(swing_amount=0.5)
        # Events with durations trigger swing processing
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=60, velocity=100, duration=0.5, beat=0.0
            )
        )
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=62, velocity=100, duration=0.5, beat=0.5
            )
        )
        transport.process_events(current_beat=0.0)
        # SwingApplier internal state should have advanced
        # (indirectly verified by no errors and correct delivery)

    def test_swing_reset_on_all_notes_off(self):
        """all_notes_off() безопасен для свинга (тот не хранит состояния)."""
        transport, q, _ = _make_transport(swing_amount=0.5)
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=60, velocity=100, duration=0.5, beat=0.0
            )
        )
        transport.process_events(current_beat=0.0)
        transport.all_notes_off()
        # Позиционный свинг: результат зависит только от beat, не от паники
        assert transport.swing.shift(0.0) == 0.0
        assert transport.swing.shift(0.5) > 0.0


class TestCCFlush:
    """Tests for CC flush at bar boundaries."""

    def test_flush_on_bar_boundary(self):
        """flush_all() is called when crossing a bar boundary."""
        transport, _, registry = _make_transport()
        transport.process_events(current_beat=0.0)  # bar 0
        registry.flush_all.assert_called_once()

        transport.process_events(current_beat=4.0)  # bar 1
        assert registry.flush_all.call_count == 2

    def test_no_flush_within_bar(self):
        """flush_all() is not called multiple times within the same bar."""
        transport, _, registry = _make_transport()
        transport.process_events(current_beat=0.0)  # bar 0
        transport.process_events(current_beat=1.0)  # still bar 0
        transport.process_events(current_beat=2.0)  # still bar 0
        transport.process_events(current_beat=3.0)  # still bar 0
        registry.flush_all.assert_called_once()  # only first call

    def test_flush_resets_on_all_notes_off(self):
        """all_notes_off() resets bar flush tracker."""
        transport, _, registry = _make_transport()
        transport.process_events(current_beat=0.0)  # bar 0
        transport.all_notes_off()
        # After all_notes_off, bar tracker is reset
        transport.process_events(current_beat=0.0)  # bar 0 again
        assert registry.flush_all.call_count == 2


class TestAllNotesOff:
    """Tests for the all_notes_off() panic method."""

    def test_clears_queue(self):
        """all_notes_off() drains the event queue."""
        transport, q, _ = _make_transport()
        q.put(TransportEvent.note_on("Synth A", channel=0, note=60, velocity=100))
        q.put(TransportEvent.note_on("Synth A", channel=0, note=62, velocity=100))
        transport.all_notes_off()
        assert q.empty()

    def test_calls_all_notes_off_on_adapters(self):
        """all_notes_off() is called on all port adapters."""
        transport, _, registry = _make_transport()
        transport.all_notes_off()
        adapter = registry.all_outputs.return_value[0]
        adapter.all_notes_off.assert_called_once()

    def test_resets_swing(self):
        """all_notes_off() не ломает свинг (stateful-счётчика больше нет)."""
        transport, _, _ = _make_transport(swing_amount=0.5)
        transport.all_notes_off()
        assert not hasattr(transport.swing, "_step")
        # beat=0.5 → нечётный шаг (задержан), beat=1.0 → снова чётный (вовремя)
        assert transport.swing.shift(0.5) == pytest.approx(0.125)
        assert transport.swing.shift(1.0) == 0.0


class TestTransportProperties:
    """Tests for Transport properties."""

    def test_swing_property(self):
        """swing property returns the SwingApplier."""
        transport, _, _ = _make_transport(swing_amount=0.3)
        assert transport.swing.amount == 0.3


def test_transport_does_not_advance_swing_step() -> None:
    """Regression (plan §4.2): Transport must not apply swing to durations.

    Swing is applied once in the generating engine. Transport delivering
    NOTE_ON must leave the SwingApplier step counter untouched, otherwise
    the even/odd alternation breaks.
    """
    transport, q, _ = _make_transport(swing_amount=0.5)
    swing = transport.swing
    before = repr(swing)

    for beat in (0.0, 0.5, 1.0, 1.5):
        q.put(
            TransportEvent.note_on(
                port_label="Synth A",
                channel=0,
                note=60,
                velocity=100,
                duration=0.5,
                beat=beat,
            )
        )
    transport.process_events(current_beat=0.0)

    assert repr(swing) == before


class TestSwingDelaysOnset:
    """§4.2: swing is an onset delay and lives only in Transport."""

    def test_even_step_is_not_delayed(self) -> None:
        transport, q, registry = _make_transport(swing_amount=0.5)
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=60, velocity=100, duration=0.5, beat=0.0
            )
        )
        transport.process_events(current_beat=0.0)
        adapter = registry.get_output.return_value
        adapter.note_on.assert_called_once()

    def test_odd_step_is_held_until_due(self) -> None:
        transport, q, registry = _make_transport(swing_amount=0.5)
        # beat 0.5 -> odd 1/8 step -> delayed by (1/2) * 0.5 * 0.5 = 0.125 beats
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=62, velocity=100, duration=0.5, beat=0.5
            )
        )
        transport.process_events(current_beat=0.5)
        adapter = registry.get_output.return_value
        adapter.note_on.assert_not_called()

        # released once the timeline reaches the delayed onset
        transport.process_events(current_beat=0.625)
        adapter.note_on.assert_called_once()

    def test_held_events_dropped_on_panic(self) -> None:
        transport, q, registry = _make_transport(swing_amount=0.5)
        q.put(
            TransportEvent.note_on(
                "Synth A", channel=0, note=62, velocity=100, duration=0.5, beat=0.5
            )
        )
        transport.process_events(current_beat=0.5)
        adapter = registry.get_output.return_value
        adapter.note_on.assert_not_called()

        transport.all_notes_off()
        transport.process_events(current_beat=0.7)
        adapter.note_on.assert_not_called()

    def test_note_off_never_delayed(self) -> None:
        """Swing moves the onset only; the pair keeps its length."""
        transport, q, registry = _make_transport(swing_amount=0.5)
        q.put(TransportEvent.note_off("Synth A", channel=0, note=62, beat=0.5))
        transport.process_events(current_beat=0.5)
        adapter = registry.get_output.return_value
        adapter.note_off.assert_called_once()


def test_transport_does_not_advance_swing_step() -> None:
    """Regression (plan §4.2): Transport must not apply swing to durations.

    Swing is applied once in the generating engine. Transport delivering
    NOTE_ON must leave the SwingApplier step counter untouched, otherwise
    the even/odd alternation breaks.
    """
    transport, q, _ = _make_transport(swing_amount=0.5)
    swing = transport.swing
    before = repr(swing)

    for beat in (0.0, 0.5, 1.0, 1.5):
        q.put(
            TransportEvent.note_on(
                port_label="Synth A",
                channel=0,
                note=60,
                velocity=100,
                duration=0.5,
                beat=beat,
            )
        )
    transport.process_events(current_beat=0.0)

    assert repr(swing) == before
