"""CC rate limiter — throttles Control Change messages to a fixed rate.

Motivation (plan v5.4 §3.4): a raw CC interpolation sweep generates ~3 840
messages, consuming ~54 % of the DIN MIDI bandwidth.  After throttling to
30 Hz only ~93 messages remain (1.3 %).  **Throttling is mandatory, not
optional.**

Design:

- **Key** is ``(port_label, channel, cc)`` — two tracks that resolve to the
  same CC on the same port share one throttler, not two.
- **Not thread-safe** — designed for the single-threaded transport event loop.
- ``flush()`` guarantees the *final* value of a series is always delivered,
  preventing a sweep from stopping one step short.
- ``reset()`` clears pending values on panic / ``all_notes_off``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from src.midi.abc import MidiCC, MidiChannel, MidiValue

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CCKey:
    """Throttle key: (port_label, channel, cc)."""

    port: str
    channel: MidiChannel
    cc: MidiCC


@dataclass(frozen=True)
class CCEvent:
    """A CC event ready for delivery."""

    key: CCKey
    value: MidiValue


# ---------------------------------------------------------------------------
# CCThrottle
# ---------------------------------------------------------------------------


class CCThrottle:
    """Rate-limits CC messages per (port, channel, cc) key.

    Parameters
    ----------
    max_rate_hz:
        Maximum send rate in Hz.  Default 30 Hz (plan v5.4 §3.4).

    Example
    -------
    >>> throttle = CCThrottle(max_rate_hz=30.0)
    >>> events = throttle.submit("Синт A", channel=0, cc=74, value=64)
    >>> # events is [CCEvent(...)] — first send goes through immediately
    >>> events = throttle.submit("Синт A", channel=0, cc=74, value=80)
    >>> # events is [] — too soon, value stored as pending
    >>> events = throttle.flush()
    >>> # events is [CCEvent(...value=80)] — final value delivered
    """

    def __init__(self, max_rate_hz: float = 30.0) -> None:
        if max_rate_hz <= 0:
            raise ValueError(f"max_rate_hz must be positive, got {max_rate_hz}")
        self._interval = 1.0 / max_rate_hz
        self._last_sent: dict[CCKey, float] = {}
        self._pending: dict[CCKey, MidiValue] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        port: str,
        channel: int,
        cc: int,
        value: int,
    ) -> list[CCEvent]:
        """Submit a CC value for throttled delivery.

        If the key was last sent less than ``1/max_rate_hz`` seconds ago,
        the value is stored as *pending* and an empty list is returned.
        Otherwise the event is returned for immediate delivery.

        Parameters
        ----------
        port:
            Port label (part of the throttle key).
        channel:
            MIDI channel, 0–15.
        cc:
            CC number, 0–127.
        value:
            CC value, 0–127.

        Returns
        -------
        list[CCEvent]
            Events to send immediately (empty if throttled).
        """
        key = CCKey(
            port=port,
            channel=MidiChannel(channel),
            cc=MidiCC(cc),
        )
        val = MidiValue(value)
        now = time.monotonic()

        last = self._last_sent.get(key)
        if last is None or (now - last) >= self._interval:
            self._last_sent[key] = now
            return [CCEvent(key=key, value=val)]

        # Too soon — store as pending, will be flushed later
        self._pending[key] = val
        return []

    def flush(self) -> list[CCEvent]:
        """Force-send all pending values.

        Call at the end of each transport tick or bar to guarantee the
        final value of a series is delivered.

        Returns
        -------
        list[CCEvent]
            All pending events, cleared from internal state.
        """
        if not self._pending:
            return []

        now = time.monotonic()
        events = [CCEvent(key=k, value=v) for k, v in self._pending.items()]
        self._pending.clear()
        for event in events:
            self._last_sent[event.key] = now
        return events

    def pending_count(self) -> int:
        """Number of keys with unsent pending values."""
        return len(self._pending)

    def reset(self) -> None:
        """Clear all pending values and send history.

        Call on panic / ``all_notes_off`` so stale pending values are not
        delivered after a silence.
        """
        self._pending.clear()
        self._last_sent.clear()

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"CCThrottle(rate={1 / self._interval:.1f} Hz, "
            f"pending={self.pending_count()})"
        )
