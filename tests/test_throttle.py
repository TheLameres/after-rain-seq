"""Tests for CCThrottle — CC rate limiter."""

from __future__ import annotations

import time

import pytest

from src.midi.abc import MidiCC, MidiChannel, MidiValue
from src.sync.throttle import CCEvent, CCKey, CCThrottle


class TestCCKey:
    """Tests for the throttle key dataclass."""

    def test_frozen(self):
        """CCKey is immutable."""
        key = CCKey(port="A", channel=MidiChannel(0), cc=MidiCC(74))
        with pytest.raises(AttributeError):
            key.port = "B"  # type: ignore[misc]

    def test_hashable(self):
        """CCKey can be used as dict key."""
        k1 = CCKey(port="A", channel=MidiChannel(0), cc=MidiCC(74))
        k2 = CCKey(port="A", channel=MidiChannel(0), cc=MidiCC(74))
        k3 = CCKey(port="B", channel=MidiChannel(0), cc=MidiCC(74))
        d = {k1: 1}
        assert d[k2] == 1
        assert k3 not in d


class TestCCEvent:
    """Tests for the CC event dataclass."""

    def test_frozen(self):
        """CCEvent is immutable."""
        key = CCKey(port="A", channel=MidiChannel(0), cc=MidiCC(74))
        event = CCEvent(key=key, value=MidiValue(64))
        with pytest.raises(AttributeError):
            event.value = MidiValue(100)  # type: ignore[misc]


class TestCCThrottle:
    """Tests for the rate limiter."""

    def test_first_submit_sends_immediately(self):
        """First submit for a key returns the event immediately."""
        throttle = CCThrottle(max_rate_hz=30.0)
        events = throttle.submit("Synth A", channel=0, cc=74, value=64)
        assert len(events) == 1
        assert events[0].key.port == "Synth A"
        assert events[0].key.channel == 0
        assert events[0].key.cc == 74
        assert events[0].value == 64

    def test_rapid_submit_throttled(self):
        """Second submit within interval returns empty list."""
        throttle = CCThrottle(max_rate_hz=30.0)
        throttle.submit("Synth A", channel=0, cc=74, value=64)
        events = throttle.submit("Synth A", channel=0, cc=74, value=80)
        assert events == []
        assert throttle.pending_count() == 1

    def test_flush_delivers_pending(self):
        """flush() returns the last pending value."""
        throttle = CCThrottle(max_rate_hz=30.0)
        throttle.submit("Synth A", channel=0, cc=74, value=64)
        throttle.submit("Synth A", channel=0, cc=74, value=80)
        throttle.submit("Synth A", channel=0, cc=74, value=100)

        events = throttle.flush()
        assert len(events) == 1
        assert events[0].value == 100  # last value wins
        assert throttle.pending_count() == 0

    def test_flush_empty_when_no_pending(self):
        """flush() returns empty list when nothing is pending."""
        throttle = CCThrottle(max_rate_hz=30.0)
        assert throttle.flush() == []

    def test_flush_clears_pending(self):
        """flush() clears all pending state."""
        throttle = CCThrottle(max_rate_hz=30.0)
        throttle.submit("A", channel=0, cc=74, value=64)
        throttle.submit("A", channel=0, cc=74, value=80)
        throttle.flush()
        assert throttle.pending_count() == 0
        # Second flush returns nothing
        assert throttle.flush() == []

    def test_submit_after_interval_sends(self):
        """Submit after the interval has passed sends immediately."""
        throttle = CCThrottle(max_rate_hz=1000.0)  # 1 ms interval
        throttle.submit("A", channel=0, cc=74, value=64)
        time.sleep(0.002)  # 2 ms > 1 ms
        events = throttle.submit("A", channel=0, cc=74, value=80)
        assert len(events) == 1
        assert events[0].value == 80

    def test_different_keys_independent(self):
        """Different (port, channel, cc) keys throttle independently."""
        throttle = CCThrottle(max_rate_hz=30.0)
        e1 = throttle.submit("A", channel=0, cc=74, value=64)
        e2 = throttle.submit("A", channel=0, cc=71, value=64)  # different CC
        e3 = throttle.submit("A", channel=1, cc=74, value=64)  # different channel
        e4 = throttle.submit("B", channel=0, cc=74, value=64)  # different port
        assert len(e1) == 1
        assert len(e2) == 1
        assert len(e3) == 1
        assert len(e4) == 1

    def test_same_cc_different_names_shared_key(self):
        """Two logical names resolving to same CC share one throttle key.

        This is the plan v5.4 requirement: key is (port, channel, resolved_cc),
        not (port, channel, logical_name).
        """
        throttle = CCThrottle(max_rate_hz=30.0)
        # Both "filter" and "brightness" resolve to CC 74
        throttle.submit("A", channel=0, cc=74, value=64)  # "filter"
        events = throttle.submit("A", channel=0, cc=74, value=80)  # "brightness"
        assert events == []  # throttled — same key

    def test_reset_clears_everything(self):
        """reset() clears pending and last_sent."""
        throttle = CCThrottle(max_rate_hz=30.0)
        throttle.submit("A", channel=0, cc=74, value=64)
        throttle.submit("A", channel=0, cc=74, value=80)
        assert throttle.pending_count() == 1

        throttle.reset()
        assert throttle.pending_count() == 0

        # After reset, first submit goes through immediately
        events = throttle.submit("A", channel=0, cc=74, value=100)
        assert len(events) == 1

    def test_invalid_rate_raises(self):
        """Zero or negative max_rate_hz raises ValueError."""
        with pytest.raises(ValueError, match="positive"):
            CCThrottle(max_rate_hz=0.0)
        with pytest.raises(ValueError, match="positive"):
            CCThrottle(max_rate_hz=-1.0)

    def test_repr(self):
        """Repr shows rate and pending count."""
        throttle = CCThrottle(max_rate_hz=30.0)
        throttle.submit("A", channel=0, cc=74, value=64)
        throttle.submit("A", channel=0, cc=74, value=80)
        r = repr(throttle)
        assert "30.0" in r
        assert "pending=1" in r


class TestThrottlingScenario:
    """Integration-style test simulating a real CC sweep."""

    def test_sweep_throttled_to_30hz(self):
        """A 127-step sweep at high rate is throttled, final value preserved.

        Simulates plan v5.4 §3.4: raw sweep = 3840 CC, after 30 Hz throttle
        the final value must still be delivered via flush().
        """
        throttle = CCThrottle(max_rate_hz=30.0)
        sent_values: list[int] = []

        # Simulate a rapid sweep of 127 values
        for v in range(128):
            events = throttle.submit("Synth A", channel=0, cc=74, value=v)
            for e in events:
                sent_values.append(e.value)

        # Most values were throttled
        assert len(sent_values) < 128

        # flush delivers the final value
        flushed = throttle.flush()
        assert len(flushed) == 1
        assert flushed[0].value == 127  # final value of the sweep
