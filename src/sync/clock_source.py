"""ClockSource enum, ClockManagerConfig, and clock source factory.

This module provides:
- :class:`ClockSource` — enum for the three clock sources
- :class:`ClockManagerConfig` — frozen dataclass for ClockManager configuration
- :class:`_LinkClockSource` — stoppable Ableton Link clock source
- :func:`create_clock_source` — factory that creates the appropriate source
- :func:`link_available` — check if the ``link`` package is installed
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ClockSource enum
# ---------------------------------------------------------------------------


class ClockSource(Enum):
    """Available clock sources."""

    INTERNAL = auto()
    MIDI = auto()
    LINK = auto()


# ---------------------------------------------------------------------------
# ClockManagerConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClockManagerConfig:
    """Configuration for ClockManager.

    Parameters
    ----------
    initial_source:
        Which clock source to use at startup.
    initial_bpm:
        Initial tempo in BPM (used for internal and link sources).
    ticks_per_beat:
        Timeline resolution in PPQN.
    midi_device_name:
        MIDI input port name for MIDI clock.  ``None`` means use
        ``ISOBAR_DEFAULT_MIDI_IN`` environment variable.
    """

    initial_source: ClockSource = ClockSource.INTERNAL
    initial_bpm: float = 120.0
    ticks_per_beat: int = 480
    midi_device_name: str | None = None


# ---------------------------------------------------------------------------
# Link availability check
# ---------------------------------------------------------------------------


def link_available() -> bool:
    """Return True if the ``link`` package (LinkPython-extern) is installed."""
    try:
        import link  # noqa: F401

        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# _LinkClockSource — stoppable Ableton Link clock
# ---------------------------------------------------------------------------


class _LinkClockSource:
    """Stoppable Ableton Link clock source.

    isobar's ``AbletonLinkClock`` has a bug: ``run()`` is ``while True:``
    without checking ``self.running``, so ``stop()`` has no effect.  This
    class reimplements the Link polling loop with a proper stop event.

    The interface is duck-typed to match isobar clock sources:
    ``clock_target``, ``ticks_per_beat``, ``tempo``, ``run()``, ``stop()``,
    ``background()``.
    """

    def __init__(
        self,
        clock_target: Any = None,
        tempo: float = 120.0,
        ticks_per_beat: int = 480,
    ) -> None:
        self.clock_target = clock_target
        self._tempo = tempo
        self._ticks_per_beat = ticks_per_beat
        self._stop_event = threading.Event()
        self._link_client: Any = None  # link.Link instance
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API (duck-typed to match isobar clock sources)
    # ------------------------------------------------------------------

    @property
    def tempo(self) -> float:
        """Current tempo from Link session."""
        if self._link_client is not None:
            try:
                state = self._link_client.captureSessionState()
                return state.tempo()
            except Exception as exc:
                log.debug("_LinkClockSource: error reading tempo: %s", exc)
        return self._tempo

    @tempo.setter
    def tempo(self, value: float) -> None:
        """Set tempo in Link session."""
        self._tempo = value
        if self._link_client is not None:
            try:
                state = self._link_client.captureSessionState()
                now = self._link_client.clock().micros()
                state.setTempo(value, now)
                self._link_client.commitSessionState(state)
            except Exception as exc:
                log.debug("_LinkClockSource: error setting tempo: %s", exc)

    @property
    def ticks_per_beat(self) -> int:
        """Ticks per beat (read-only)."""
        return self._ticks_per_beat

    def run(self) -> None:
        """Poll Link session and emit ticks.  Blocks until :meth:`stop`.

        Starts ticking on the next 4-beat boundary (bar start), then
        catches up on missed ticks by computing delta from Link beat time.
        """
        import link

        self._link_client = link.Link(self._tempo)
        self._link_client.enabled = True
        self._link_client.startStopSyncEnabled = True
        log.info("_LinkClockSource: Link session started (bpm=%.1f)", self._tempo)

        ticks_previous = 0
        started = False

        while not self._stop_event.is_set():
            try:
                state = self._link_client.captureSessionState()
                beats = state.beatAtTime(self._link_client.clock().micros(), 4)
                ticks_current = int(beats * self._ticks_per_beat)
            except Exception as exc:
                log.debug("_LinkClockSource: poll error: %s", exc)
                self._stop_event.wait(0.001)
                continue

            if not started:
                # Wait for 4-beat boundary before starting (like isobar)
                if ticks_current % (self._ticks_per_beat * 4) == 0:
                    started = True
                    ticks_previous = ticks_current
                    log.debug("_LinkClockSource: started at tick %d", ticks_current)
                else:
                    self._stop_event.wait(0.001)
                    continue

            delta = ticks_current - ticks_previous
            if delta > 0:
                for _ in range(delta):
                    if self._stop_event.is_set():
                        return
                    if self.clock_target is not None:
                        self.clock_target.tick()
                ticks_previous = ticks_current

            self._stop_event.wait(0.001)

    def stop(self) -> None:
        """Signal the polling loop to stop."""
        self._stop_event.set()

    def background(self) -> None:
        """Start :meth:`run` in a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self.run,
            name="link-clock",
            daemon=True,
        )
        self._thread.start()

    def wait(self, timeout: float = 1.0) -> None:
        """Wait for the background thread to finish."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_clock_source(
    source: ClockSource,
    config: ClockManagerConfig,
    clock_target: Any,
) -> Any:
    """Create a clock source instance for the given type.

    Parameters
    ----------
    source:
        Which clock source to create.
    config:
        Configuration (BPM, ticks_per_beat, MIDI device name).
    clock_target:
        The object that receives ``tick()`` calls (should be a TickProxy).

    Returns
    -------
    Any
        An object with ``clock_target``, ``ticks_per_beat``, ``tempo``,
        ``run()``, ``stop()``, and optionally ``background()``.

    Raises
    ------
    RuntimeError
        If the ``link`` package is not installed for LINK source.
    ValueError
        If the MIDI device cannot be opened.
    """
    if source is ClockSource.INTERNAL:
        from isobar import Clock

        clock = Clock(
            clock_target=clock_target,
            tempo=config.initial_bpm,
            ticks_per_beat=config.ticks_per_beat,
        )
        log.info("Created internal clock (bpm=%.1f)", config.initial_bpm)
        return clock

    if source is ClockSource.MIDI:
        from src.sync.midi_clock_in import MidiClockInput

        if not config.midi_device_name:
            raise ValueError(
                "MIDI clock input is not configured "
                "(set sync.midi_clock_device or a role: clock input port)"
            )
        log.info("Created MIDI clock input (device=%r)", config.midi_device_name)
        return MidiClockInput(
            clock_target,
            config.midi_device_name,
            config.ticks_per_beat,
        )

    if source is ClockSource.LINK:
        if not link_available():
            raise RuntimeError(
                "Ableton Link is not available. "
                "Install with: uv add LinkPython-extern --group link"
            )
        link_clock = _LinkClockSource(
            clock_target=clock_target,
            tempo=config.initial_bpm,
            ticks_per_beat=config.ticks_per_beat,
        )
        log.info("Created Link clock source (bpm=%.1f)", config.initial_bpm)
        return link_clock

    raise ValueError(f"Unknown clock source: {source}")
