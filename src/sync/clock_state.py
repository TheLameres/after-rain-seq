"""ClockState — immutable snapshot of clock status for display rendering."""

from __future__ import annotations

from dataclasses import dataclass

from src.sync.clock_source import ClockSource


@dataclass(frozen=True)
class ClockState:
    """Snapshot of current clock manager status.

    Consumed by DisplayRenderer every render frame — no locks needed because
    ClockManager replaces the entire instance atomically via assignment.
    """

    source: ClockSource
    """Current active clock source."""

    pending: ClockSource | None
    """Pending source switch, or None if no switch is queued."""

    bpm: float | None
    """Current BPM, or None if not known (e.g. waiting for MIDI clock)."""

    midi_transport_started: bool
    """True if MIDI transport has been started (relevant in MIDI mode)."""

    link_peers: int
    """Number of Ableton Link peers (0 if Link disabled or no session)."""

    link_active: bool
    """True if Link session is active (source=LINK and link module available)."""

    error: str | None
    """Last error message, or None if everything is fine."""

    running: bool
    """True if the transport is running."""

    @property
    def clock_source(self) -> str:
        """String representation for display compatibility.

        Returns lowercase source name: ``"internal"``, ``"midi"``, or
        ``"link"``.  When not running, returns ``"off"``.
        """
        if not self.running:
            return "off"
        return self.source.name.lower()
