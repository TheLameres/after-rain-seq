"""CaptureOutput — isobar OutputDevice that captures events into a queue.

Instead of sending MIDI directly, this device intercepts all note_on /
note_off / control_change calls from the isobar Timeline and places them
into a queue as :class:`TransportEvent` instances.  The :class:`Transport`
engine then picks them up and delivers them to physical MIDI ports via
:class:`PortRegistry`.

This indirection is necessary because:

1. The Timeline calls output devices synchronously during ``tick()`` — we
   need to decouple event *generation* from event *delivery*.
2. We need a single point where ``int()`` is applied to all numpy values.
3. We need to apply swing (duration transformation) before delivery.

Usage
-----
>>> event_queue: queue.Queue[TransportEvent] = queue.Queue(maxsize=4096)
>>> capture = CaptureOutput(event_queue, port_label="Synth A")
>>> timeline.add_output_device(capture)
>>> # Timeline.tick() will now feed events into event_queue
"""

from __future__ import annotations

import logging
import queue

from src.sync.transport_event import TransportEvent

log = logging.getLogger(__name__)


class CaptureOutput:
    """isobar-compatible output device that captures events into a queue.

    Implements the isobar ``OutputDevice`` interface:

    - ``tick()`` — no-op (we do not forward MIDI Clock)
    - ``start()`` / ``stop()`` — no-op
    - ``note_on(note, velocity, channel)`` — enqueue TransportEvent
    - ``note_off(note, channel)`` — enqueue TransportEvent
    - ``control(control, value, channel)`` — enqueue TransportEvent
    - ``all_notes_off()`` — enqueue ALL_NOTES_OFF event
    - ``ticks_per_beat`` — returns ``None`` (no clock multiplier needed)

    Parameters
    ----------
    event_queue:
        The queue to place :class:`TransportEvent` instances into.
        Should be created with ``maxsize`` to prevent unbounded growth.
    port_label:
        The port label to attach to every event.  For B4 this is a single
        default port; full per-track routing arrives with Session (C3)
        integration.

    Thread safety
    -------------
    This object is called from the TickProxy worker thread (via
    ``Timeline.tick()``).  The queue must be thread-safe (``queue.Queue``
    is).  On overflow the oldest event is dropped — never block the
    Timeline.
    """

    def __init__(
        self,
        event_queue: queue.Queue[TransportEvent],
        port_label: str,
    ) -> None:
        self._queue = event_queue
        self._port_label = port_label
        self._beat: float = 0.0

    # ------------------------------------------------------------------
    # isobar OutputDevice interface
    # ------------------------------------------------------------------

    @property
    def ticks_per_beat(self) -> None:
        """Return None — no clock multiplier needed for capture.

        isobar's ``make_clock_multiplier`` handles ``None`` by returning
        a multiplier that yields 1 tick per timeline tick.
        """
        return None  # type: ignore[return-value]

    def tick(self) -> None:
        """No-op — we do not forward MIDI Clock to the transport queue."""

    def start(self) -> None:
        """No-op — transport start is handled by ClockManager."""

    def stop(self) -> None:
        """No-op — transport stop is handled by ClockManager."""

    def note_on(self, note: int = 60, velocity: int = 64, channel: int = 0) -> None:
        """Capture a Note On event.

        Parameters match isobar's calling convention:
        ``output_device.note_on(note, amplitude, channel)``.
        """
        event = TransportEvent.note_on(
            port_label=self._port_label,
            channel=int(channel),
            note=int(note),
            velocity=int(velocity),
            beat=self._beat,
        )
        self._enqueue(event)

    def note_off(self, note: int = 60, channel: int = 0) -> None:
        """Capture a Note Off event.

        Parameters match isobar's calling convention:
        ``output_device.note_off(note, channel)``.
        """
        event = TransportEvent.note_off(
            port_label=self._port_label,
            channel=int(channel),
            note=int(note),
            beat=self._beat,
        )
        self._enqueue(event)

    def control(self, control: int = 0, value: int = 0, channel: int = 0) -> None:
        """Capture a Control Change event.

        Parameters match isobar's calling convention:
        ``output_device.control(control, value, channel)``.
        """
        event = TransportEvent.control_change(
            port_label=self._port_label,
            channel=int(channel),
            control=int(control),
            value=int(value),
            beat=self._beat,
        )
        self._enqueue(event)

    def all_notes_off(self) -> None:
        """Capture an All Notes Off event."""
        event = TransportEvent.all_notes_off(port_label=self._port_label)
        self._enqueue(event)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def port_label(self) -> str:
        """The port label attached to every captured event."""
        return self._port_label

    @property
    def beat(self) -> float:
        """Current beat position (set by Transport before each tick)."""
        return self._beat

    @beat.setter
    def beat(self, value: float) -> None:
        """Update the beat position. Called by Transport before each tick."""
        self._beat = value

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _enqueue(self, event: TransportEvent) -> None:
        """Place an event in the queue, dropping the oldest if full."""
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except queue.Empty:
                try:
                    self._queue.put_nowait(event)
                except queue.Full:
                    log.warning(
                        "CaptureOutput: queue still full after drop, event lost"
                    )

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"CaptureOutput(port_label={self._port_label!r})"
