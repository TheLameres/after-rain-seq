"""Single CC mapping entry: logical parameter → CC number with invert/range.

This is a pure data class with no dependencies on MIDI or config layers.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.midi.abc import MidiCC

# ---------------------------------------------------------------------------
# CCMapEntry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CCMapEntry:
    """Resolved CC mapping entry for one logical parameter on one port.

    Parameters
    ----------
    cc:
        MIDI CC number (0–127).
    invert:
        If ``True``, the value direction is flipped (0 = max, 127 = min).
        Some synths have cutoff that opens *down* (0 = bright, 127 = dull).
    range:
        ``(lo, hi)`` — clamp the output to this sub-range of 0–127.
        Some synths do not respond to the full 0–127 range.
    """

    cc: MidiCC
    invert: bool = False
    range: tuple[int, int] = (0, 127)

    def __post_init__(self) -> None:
        lo, hi = self.range
        if not (0 <= lo < hi <= 127):
            raise ValueError(
                f"CCMapEntry range must satisfy 0 <= lo < hi <= 127, got {self.range}"
            )

    def transform(self, value: int) -> int:
        """Map a normalised 0–127 value through invert + range.

        The generator always works in normalised 0–127 space.  This method
        applies the per-port invert and range so the generator does not need
        to know about hardware quirks.

        Parameters
        ----------
        value:
            Normalised value in 0–127.

        Returns
        -------
        int
            Transformed value in ``range``, direction adjusted by ``invert``.
        """
        if self.invert:
            value = 127 - value
        lo, hi = self.range
        return lo + round(value * (hi - lo) / 127)
