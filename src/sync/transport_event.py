"""TransportEvent — a single MIDI event in the transport delivery queue.

This is the common currency between :class:`CaptureOutput` (which produces
events from the isobar Timeline) and :class:`Transport` (which delivers
them to physical MIDI ports via :class:`PortRegistry`).

All numeric fields are plain ``int`` — ``numpy.int64`` from isobar is
converted at capture time so that mido never sees it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EventKind enum
# ---------------------------------------------------------------------------


class EventKind(Enum):
    """Types of MIDI events that flow through the transport queue."""

    NOTE_ON = auto()
    NOTE_OFF = auto()
    CONTROL_CHANGE = auto()
    ALL_NOTES_OFF = auto()


# ---------------------------------------------------------------------------
# TransportEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportEvent:
    """One MIDI event ready for delivery.

    Parameters
    ----------
    kind:
        The type of event (see :class:`EventKind`).
    port_label:
        Target port label from config (e.g. ``"Синт A"``).  The transport
        resolves this to a :class:`MidiPortOutput` via :class:`PortRegistry`.
    channel:
        MIDI channel, 0–15.
    note:
        MIDI note number, 0–127.  Only for ``NOTE_ON`` / ``NOTE_OFF``.
    velocity:
        Note velocity, 0–127.  Only for ``NOTE_ON``.
    control:
        CC number, 0–127 (already resolved from logical name).  Only for
        ``CONTROL_CHANGE``.
    value:
        CC value, 0–127.  Only for ``CONTROL_CHANGE``.
    duration:
        Event duration in beats.  Used by swing to compute step index.
        ``None`` for events without a meaningful duration.
    beat:
        Timeline position in beats when the event was generated.
        Used by swing and for look-ahead scheduling.
    """

    kind: EventKind
    port_label: str
    channel: int = 0
    note: int | None = None
    velocity: int | None = None
    control: int | None = None
    value: int | None = None
    duration: float | None = None
    beat: float = 0.0

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def note_on(
        cls,
        port_label: str,
        channel: int,
        note: int,
        velocity: int,
        duration: float | None = None,
        beat: float = 0.0,
    ) -> TransportEvent:
        """Create a NOTE_ON event."""
        return cls(
            kind=EventKind.NOTE_ON,
            port_label=port_label,
            channel=int(channel),
            note=int(note),
            velocity=int(velocity),
            duration=duration,
            beat=beat,
        )

    @classmethod
    def note_off(
        cls,
        port_label: str,
        channel: int,
        note: int,
        beat: float = 0.0,
    ) -> TransportEvent:
        """Create a NOTE_OFF event."""
        return cls(
            kind=EventKind.NOTE_OFF,
            port_label=port_label,
            channel=int(channel),
            note=int(note),
            beat=beat,
        )

    @classmethod
    def control_change(
        cls,
        port_label: str,
        channel: int,
        control: int,
        value: int,
        beat: float = 0.0,
    ) -> TransportEvent:
        """Create a CONTROL_CHANGE event."""
        return cls(
            kind=EventKind.CONTROL_CHANGE,
            port_label=port_label,
            channel=int(channel),
            control=int(control),
            value=int(value),
            beat=beat,
        )

    @classmethod
    def all_notes_off(cls, port_label: str) -> TransportEvent:
        """Create an ALL_NOTES_OFF event."""
        return cls(
            kind=EventKind.ALL_NOTES_OFF,
            port_label=port_label,
        )
