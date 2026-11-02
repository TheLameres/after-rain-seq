"""Swing — groove through duration modification, not wall-clock shifts.

Motivation (plan v5.4 §4.1a): isobar has no swing (``PShuffle`` shuffles
values, not timing).  The key insight is that swing can be applied by
modifying event *durations* rather than shifting wall-clock time.  This
works under both clock modes (IsobarClock and ExternalClock) and does not
break note-on/off pairs.

Grid: 1/8 notes.  At 118 BPM an 1/8 step is ~254 ms; a 20 % shift is
~51 ms — clearly audible.  On 1/16 the same percentage is half as small
and barely perceptible.

Swing acts on **all** tracks (melodic + drum) intentionally: inter-section
desynchronisation sounds like a bug, not a groove.
"""

from __future__ import annotations

import logging
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


def swing_duration(base: float, step_index: int, amount: float) -> float:
    """Apply swing to a single duration value.

    Even steps are shortened, odd steps are lengthened by the same amount.
    The sum of each pair equals ``2 * base`` — tempo does not drift.

    Parameters
    ----------
    base:
        Base duration in beats (or any consistent unit).
    step_index:
        Position within the swing grid (0-based).  Even = shortened,
        odd = lengthened.
    amount:
        Swing amount 0.0–1.0.  ``0.0`` returns *base* unchanged.

    Returns
    -------
    float
        Swung duration.  Pair sum is preserved.
    """
    if amount == 0.0:
        return base
    shift = base * amount * 0.5
    return base - shift if step_index % 2 == 0 else base + shift


# ---------------------------------------------------------------------------
# SwingApplier
# ---------------------------------------------------------------------------


class SwingApplier:
    """Applies swing to a sequence of (duration, beat) pairs.

    Tracks the step index internally so that consecutive calls form
    a continuous swing grid.  Resets automatically when a beat
    discontinuity is detected (e.g. after a timeline reset).

    Usage
    -----
    >>> applier = SwingApplier(SwingConfig(amount=0.3))
    >>> swung = applier.apply_duration(base=0.5, beat=0.0)
    >>> swung  # even step: shortened
    """

    def __init__(self, config: SwingConfig) -> None:
        self._config = config
        self._step: int = 0
        self._last_beat: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def amount(self) -> float:
        """Current swing amount (0.0–1.0)."""
        return self._config.amount

    def set_amount(self, amount: float) -> None:
        """Установить величину свинга в рантайме (0.0–1.0).

        Шаг счётчика не сбрасываем — сетка свинга непрерывна.
        """
        self._config = SwingConfig(amount=amount, grid=self._config.grid)

    @property
    def grid(self) -> int:
        """Current swing grid (subdivision)."""
        return self._config.grid

    def apply_duration(self, base: float, beat: float) -> float:
        """Apply swing to a duration at the given beat position.

        Parameters
        ----------
        base:
            Base duration in beats.
        beat:
            Current beat position in the timeline.  Used to detect
            discontinuities and reset the step counter.

        Returns
        -------
        float
            Swung duration.
        """
        if self._config.amount == 0.0:
            return base

        # Detect discontinuity: beat jumped backwards or forward by
        # more than 2 bars — reset step counter.
        if self._last_beat is not None:
            delta = beat - self._last_beat
            if delta < 0 or delta > 8.0:
                self._step = 0

        step_index = self._step % self._config.grid
        result = swing_duration(base, step_index, self._config.amount)

        self._step += 1
        self._last_beat = beat
        return result

    def reset(self) -> None:
        """Reset the internal step counter.

        Call on timeline reset / stop to ensure swing starts fresh.
        """
        self._step = 0
        self._last_beat = None

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SwingApplier(amount={self._config.amount}, "
            f"grid={self._config.grid}, step={self._step})"
        )
