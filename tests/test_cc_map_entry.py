"""Tests for CCMapEntry — single CC mapping entry with invert/range."""

from __future__ import annotations

import pytest

from src.midi.abc import MidiCC
from src.sync.cc_map_entry import CCMapEntry


class TestCCMapEntry:
    """Tests for the frozen dataclass."""

    def test_defaults(self):
        """Default entry: no invert, full range."""
        entry = CCMapEntry(cc=MidiCC(74))
        assert entry.cc == 74
        assert entry.invert is False
        assert entry.range == (0, 127)

    def test_frozen(self):
        """CCMapEntry is immutable."""
        entry = CCMapEntry(cc=MidiCC(74))
        with pytest.raises(AttributeError):
            entry.cc = MidiCC(71)  # type: ignore[misc]

    def test_invalid_cc_raises(self):
        """CC number out of 0-127 raises ValueError."""
        with pytest.raises(ValueError, match="MidiCC"):
            CCMapEntry(cc=MidiCC(128))

    def test_invalid_range_lo_greater_than_hi(self):
        """Range with lo > hi raises ValueError."""
        with pytest.raises(ValueError, match="0 <= lo < hi <= 127"):
            CCMapEntry(cc=MidiCC(74), range=(100, 50))

    def test_invalid_range_equal(self):
        """Range with lo == hi raises ValueError."""
        with pytest.raises(ValueError, match="0 <= lo < hi <= 127"):
            CCMapEntry(cc=MidiCC(74), range=(64, 64))

    def test_invalid_range_negative(self):
        """Negative range bound raises ValueError."""
        with pytest.raises(ValueError, match="0 <= lo < hi <= 127"):
            CCMapEntry(cc=MidiCC(74), range=(-1, 100))

    def test_invalid_range_over_127(self):
        """Range bound over 127 raises ValueError."""
        with pytest.raises(ValueError, match="0 <= lo < hi <= 127"):
            CCMapEntry(cc=MidiCC(74), range=(0, 128))


class TestTransform:
    """Tests for CCMapEntry.transform() — invert + range mapping."""

    def test_identity(self):
        """Default entry maps 0→0, 64→64, 127→127."""
        entry = CCMapEntry(cc=MidiCC(74))
        assert entry.transform(0) == 0
        assert entry.transform(64) == 64
        assert entry.transform(127) == 127

    def test_invert(self):
        """Invert flips the value direction."""
        entry = CCMapEntry(cc=MidiCC(74), invert=True)
        assert entry.transform(0) == 127
        assert entry.transform(127) == 0
        assert entry.transform(64) == 63  # 127 - 64 = 63

    def test_range(self):
        """Range clamps output to [lo, hi]."""
        entry = CCMapEntry(cc=MidiCC(74), range=(20, 110))
        assert entry.transform(0) == 20
        assert entry.transform(127) == 110
        # Midpoint: 20 + round(64 * 90 / 127) = 20 + 45 = 65
        assert entry.transform(64) == 65

    def test_invert_and_range(self):
        """Invert + range combined: invert first, then map to range."""
        entry = CCMapEntry(cc=MidiCC(74), invert=True, range=(20, 110))
        # value=0 → invert → 127 → range → 110
        assert entry.transform(0) == 110
        # value=127 → invert → 0 → range → 20
        assert entry.transform(127) == 20

    def test_range_narrow(self):
        """Narrow range still covers full input span."""
        entry = CCMapEntry(cc=MidiCC(74), range=(60, 68))
        assert entry.transform(0) == 60
        assert entry.transform(127) == 68
