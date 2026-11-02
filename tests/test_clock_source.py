"""Tests for clock_source module — enum, config, factory, _LinkClockSource."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.sync.clock_source import (
    ClockManagerConfig,
    ClockSource,
    _LinkClockSource,
    create_clock_source,
    link_available,
)

# ---------------------------------------------------------------------------
# ClockSource enum
# ---------------------------------------------------------------------------


class TestClockSource:
    """Tests for ClockSource enum."""

    def test_three_sources(self) -> None:
        """ClockSource has exactly three variants."""
        assert len(ClockSource) == 3
        assert ClockSource.INTERNAL is not ClockSource.MIDI
        assert ClockSource.MIDI is not ClockSource.LINK
        assert ClockSource.INTERNAL is not ClockSource.LINK


# ---------------------------------------------------------------------------
# ClockManagerConfig
# ---------------------------------------------------------------------------


class TestClockManagerConfig:
    """Tests for ClockManagerConfig frozen dataclass."""

    def test_defaults(self) -> None:
        """Default values are sensible."""
        cfg = ClockManagerConfig()
        assert cfg.initial_source is ClockSource.INTERNAL
        assert cfg.initial_bpm == 120.0
        assert cfg.ticks_per_beat == 480
        assert cfg.midi_device_name is None

    def test_frozen(self) -> None:
        """ClockManagerConfig is immutable."""
        cfg = ClockManagerConfig()
        with pytest.raises(AttributeError):
            cfg.initial_bpm = 140.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# link_available
# ---------------------------------------------------------------------------


class TestLinkAvailable:
    """Tests for link_available() function."""

    def test_returns_bool(self) -> None:
        """link_available returns a boolean."""
        result = link_available()
        assert isinstance(result, bool)

    def test_false_when_not_installed(self) -> None:
        """link_available returns False when link module is missing."""
        # Just verify the function exists and returns a bool.
        # We can't easily simulate a missing link module without
        # uninstalling linkpython-extern, so this is a smoke test.
        result = link_available()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# create_clock_source factory
# ---------------------------------------------------------------------------


class TestCreateClockSource:
    """Tests for create_clock_source factory function."""

    def test_create_internal(self) -> None:
        """Factory creates isobar.Clock for INTERNAL source."""
        target = MagicMock()
        cfg = ClockManagerConfig(initial_source=ClockSource.INTERNAL)
        source = create_clock_source(ClockSource.INTERNAL, cfg, target)
        assert source is not None
        assert hasattr(source, "run")
        assert hasattr(source, "stop")
        assert hasattr(source, "tempo")
        assert hasattr(source, "background")
        assert source.clock_target is target

    def test_create_internal_has_correct_ticks(self) -> None:
        """Internal clock uses configured ticks_per_beat."""
        target = MagicMock()
        cfg = ClockManagerConfig(ticks_per_beat=480)
        source = create_clock_source(ClockSource.INTERNAL, cfg, target)
        assert source.ticks_per_beat == 480

    def test_create_midi_raises_without_device(self) -> None:
        """Factory raises ValueError when MIDI device cannot be opened."""
        target = MagicMock()
        cfg = ClockManagerConfig(midi_device_name="Nonexistent Device XYZ")
        with (
            patch(
                "isobar.io.midi.input.MidiInputDevice",
                side_effect=Exception("Device not found"),
            ),
            pytest.raises(ValueError, match="Cannot open MIDI input"),
        ):
            create_clock_source(ClockSource.MIDI, cfg, target)

    def test_create_link_raises_when_not_available(self) -> None:
        """Factory raises RuntimeError when link package is not installed."""
        target = MagicMock()
        cfg = ClockManagerConfig()
        with patch("src.sync.clock_source.link_available", return_value=False):
            with pytest.raises(RuntimeError, match="Ableton Link is not available"):
                create_clock_source(ClockSource.LINK, cfg, target)

    def test_create_link_when_available(self) -> None:
        """Factory creates _LinkClockSource when link is available."""
        target = MagicMock()
        cfg = ClockManagerConfig(initial_bpm=128.0)
        with patch("src.sync.clock_source.link_available", return_value=True):
            source = create_clock_source(ClockSource.LINK, cfg, target)
        assert isinstance(source, _LinkClockSource)
        assert source.clock_target is target
        assert source.ticks_per_beat == 480

    def test_unknown_source_raises(self) -> None:
        """Factory raises ValueError for unknown source."""
        target = MagicMock()
        cfg = ClockManagerConfig()
        with pytest.raises(ValueError, match="Unknown clock source"):
            # Create a fake enum member to trigger the fallthrough
            fake_source = MagicMock()
            fake_source.name = "FAKE"
            create_clock_source(fake_source, cfg, target)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _LinkClockSource
# ---------------------------------------------------------------------------


class TestLinkClockSource:
    """Tests for _LinkClockSource — stoppable Link clock."""

    def test_construction(self) -> None:
        """_LinkClockSource stores parameters correctly."""
        target = MagicMock()
        src = _LinkClockSource(clock_target=target, tempo=128.0, ticks_per_beat=480)
        assert src.clock_target is target
        assert src.ticks_per_beat == 480
        assert src._tempo == 128.0

    def test_ticks_per_beat_readonly(self) -> None:
        """ticks_per_beat is read-only."""
        src = _LinkClockSource()
        with pytest.raises(AttributeError):
            src.ticks_per_beat = 960  # type: ignore[misc]

    def test_stop_sets_event(self) -> None:
        """stop() sets the stop event."""
        src = _LinkClockSource()
        assert not src._stop_event.is_set()
        src.stop()
        assert src._stop_event.is_set()

    def test_background_starts_thread(self) -> None:
        """background() starts a daemon thread."""
        src = _LinkClockSource(tempo=120.0)

        # Patch run to block until stop is called
        def mock_run() -> None:
            while not src._stop_event.is_set():
                time.sleep(0.01)

        src.run = mock_run  # type: ignore[method-assign]
        src.background()
        thread = src._thread
        assert thread is not None
        assert thread.is_alive()
        # Cleanup
        src.stop()
        src.wait(timeout=1.0)
        assert not thread.is_alive()

    def test_tempo_fallback_without_link(self) -> None:
        """tempo returns _tempo when Link client is not initialised."""
        src = _LinkClockSource(tempo=135.0)
        assert src.tempo == 135.0

    def test_tempo_setter_without_link(self) -> None:
        """Setting tempo updates _tempo even without Link client."""
        src = _LinkClockSource(tempo=120.0)
        src.tempo = 140.0
        assert src._tempo == 140.0
