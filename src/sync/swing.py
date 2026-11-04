"""Swing — off-beat delay applied once, at send time in the Transport.

Motivation (plan v5.4 §4.1a): isobar has no swing (``PShuffle`` shuffles
values, not timing).  The MIDI port API takes no duration
(``note_on(channel, note, velocity)``), so swing cannot be expressed by
rewriting durations on the way out.  It is expressed as a *delay of the
onset*: even grid steps play on time, odd steps are pushed later.  Pair
period is preserved, so tempo does not drift.

Where it is applied (plan §4.2): exactly one place — ``Transport``, at
the moment the event is handed to the port.  Generating engines put the
unmodified musical beat on the event; they never swing.

Grid: 1/8 notes.  At 118 BPM an 1/8 step is ~254 ms; a 20 % shift is
~51 ms — clearly audible.  On 1/16 the same percentage is half as small
and barely perceptible.

Swing acts on **all** tracks (melodic + drum) intentionally: inter-section
desynchronisation sounds like a bug, not a groove.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SwingConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SwingConfig:
    """Configuration for swing.

    Parameters
    ----------
    amount:
        Swing amount, 0.0–1.0.  ``0.0`` means no swing (passthrough).
        ``0.5`` is a typical shuffle feel.  Values outside [0, 1] are
        rejected.
    grid:
        Subdivision grid.  ``2`` = 1/8 notes (default, recommended).
        ``4`` = 1/16 notes (subtle).  Only powers of 2 make sense.
    """

    amount: float = 0.0
    grid: int = 2

    def __post_init__(self) -> None:
        if not 0.0 <= self.amount <= 1.0:
            raise ValueError(f"Swing amount must be in [0.0, 1.0], got {self.amount}")
        if self.grid < 2:
            raise ValueError(f"Swing grid must be >= 2, got {self.grid}")


# ---------------------------------------------------------------------------
# Pure function
# ---------------------------------------------------------------------------


def swing_shift(beat: float, grid: int, amount: float) -> float:
    """Delay, in beats, for an onset landing at *beat*.

    Even grid steps get no delay; odd steps are pushed later by at most
    half a step.  This is the shuffle feel expressed as onset placement,
    which is what a MIDI port can actually consume.

    Parameters
    ----------
    beat:
        Absolute musical position of the onset, in beats.
    grid:
        Subdivision grid (``2`` = 1/8, ``4`` = 1/16).  Must be >= 2.
    amount:
        Swing amount 0.0–1.0.  ``0.0`` returns 0.0 (no delay).

    Returns
    -------
    float
        Non-negative delay in beats.  Two onsets one grid step apart keep
        their combined period, so no tempo drift accumulates.
    """
    if amount == 0.0 or grid < 2:
        return 0.0
    # epsilon: a beat that lands exactly on a grid line must not slip into
    # the previous step because of binary rounding (e.g. 0.1 + 0.2).
    step_index = math.floor(beat * grid + 1e-9)
    if step_index % 2 == 0:
        return 0.0
    return (1.0 / grid) * amount * 0.5


# ---------------------------------------------------------------------------
# SwingApplier
# ---------------------------------------------------------------------------


class SwingApplier:
    """Swing as an onset delay, computed from musical position.

    The step is derived from the *beat*, not from a call counter:
    ``step = floor(beat * grid) % grid``.  The same beat therefore always
    gives the same delay, regardless of call history or of how many tracks
    are running (§4.2).

    Usage
    -----
    >>> applier = SwingApplier(SwingConfig(amount=0.3))
    >>> applier.shift(0.0)   # even step: on time
    0.0
    >>> applier.shift(0.5)   # odd step: pushed later
    0.075
    """

    def __init__(self, config: SwingConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def amount(self) -> float:
        """Current swing amount (0.0–1.0)."""
        return self._config.amount

    def set_amount(self, amount: float) -> None:
        """Установить величину свинга в рантайме (0.0–1.0)."""
        self._config = SwingConfig(amount=amount, grid=self._config.grid)

    @property
    def grid(self) -> int:
        """Current swing grid (subdivision)."""
        return self._config.grid

    def shift(self, beat: float) -> float:
        """Задержка в долях для она (onset) в позиции *beat*.

        Это единственная точка, где свинг влияет на звук: Transport
        сдвигает момент отправки note_on, движки не трогают ничего.
        """
        return swing_shift(beat, self._config.grid, self._config.amount)

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """No-op: swing is derived from the beat, so there is no state to clear.

        Kept so callers (Transport on panic / stop) need not special-case it.
        """

    def __repr__(self) -> str:
        return f"SwingApplier(amount={self._config.amount}, grid={self._config.grid})"
