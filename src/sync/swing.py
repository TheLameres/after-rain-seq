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
    """Applies swing to a duration at a position in musical time.

    The swing step is derived from the *beat*, not from a call counter:
    ``step = floor(beat * grid) % grid``.  Two identical ``(duration,
    beat)`` pairs therefore always give the same result regardless of
    call history or of how many tracks are running (§4.2).

    Usage
    -----
    >>> applier = SwingApplier(SwingConfig(amount=0.3))
    >>> swung = applier.apply_duration(base=0.5, beat=0.0)
    >>> swung  # even step: shortened
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

        # Позиция в сетке свинга берётся из музыкального времени, а не из
        # порядка вызовов: иначе чередование ломается, когда зовут несколько
        # дорожек (§4.2).
        grid = self._config.grid
        step_index = math.floor(beat * grid) % grid
        return swing_duration(base, step_index, self._config.amount)

    def apply_step(self, base: float, step_index: int) -> float:
        """Применить свинг к длительности на шаге сетки.

        Для движков, у которых сетка задана номером шага паттерна, а не
        абсолютным beat (ударные: шаг = 1/16 при ``steps=16``).

        Parameters
        ----------
        base:
            Базовая длительность в долях.
        step_index:
            Номер шага паттерна (0-based), неубывающий.

        Returns
        -------
        float
            Свингованная длительность.
        """
        return swing_duration(base, step_index % self._config.grid, self._config.amount)

    def reset(self) -> None:
        """No-op: свинг не хранит состояния.

        Оставлен для совместимости — вызывается на STOP/панике.
        """

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"SwingApplier(amount={self._config.amount}, grid={self._config.grid})"
