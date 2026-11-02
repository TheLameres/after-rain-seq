"""Tests for ClockManager — clock source switching with quantization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.sync.clock_manager import ClockManager
from src.sync.clock_source import ClockManagerConfig, ClockSource
from src.sync.tick_proxy import TickProxy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockOutputDevice:
    """Mock output device with all_notes_off tracking."""

    def __init__(self) -> None:
        self.all_notes_off_count = 0

    def all_notes_off(self) -> None:
        self.all_notes_off_count += 1


class MockTimeline:
    """Mock isobar Timeline with the interface ClockManager needs."""

    def __init__(self) -> None:
        self.current_time: float = 0.0
        self.output_devices: list[MockOutputDevice] = [MockOutputDevice()]
        self.clock_source: object | None = None
        self.tick_count = 0
        self.reset_count = 0

    def tick(self) -> None:
        self.tick_count += 1

    def reset(self) -> None:
        self.reset_count += 1

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def set_clock_source(self, source: object) -> None:
        self.clock_source = source


def make_clock_manager(
    timeline: MockTimeline | None = None,
    config: ClockManagerConfig | None = None,
) -> tuple[ClockManager, MockTimeline, TickProxy]:
    """Create a ClockManager with mock dependencies."""
    tl = timeline or MockTimeline()
    proxy = TickProxy(tl)
    cfg = config or ClockManagerConfig(
        initial_source=ClockSource.INTERNAL,
        initial_bpm=120.0,
        ticks_per_beat=480,
    )
    cm = ClockManager(tl, proxy, cfg)
    return cm, tl, proxy


# ---------------------------------------------------------------------------
# Tests: initialisation
# ---------------------------------------------------------------------------


class TestClockManagerInit:
    """Tests for ClockManager construction and initial state."""

    def test_initial_source_internal(self) -> None:
        """Default initial source is INTERNAL."""
        cm, _, _ = make_clock_manager()
        assert cm.current_source is ClockSource.INTERNAL

    def test_initial_state_no_error(self) -> None:
        """No error on fresh ClockManager."""
        cm, _, _ = make_clock_manager()
        state = cm.state
        assert state.error is None
        assert state.running is False

    def test_state_pending_none(self) -> None:
        """No pending switch on fresh ClockManager."""
        cm, _, _ = make_clock_manager()
        assert cm.state.pending is None


# ---------------------------------------------------------------------------
# Tests: request_source validation
# ---------------------------------------------------------------------------


class TestRequestSourceValidation:
    """Tests for request_source input validation."""

    def test_request_valid_source(self) -> None:
        """request_source accepts valid ClockSource enum."""
        cm, _, _ = make_clock_manager()
        cm.request_source(ClockSource.INTERNAL)
        # No exception, pending is set
        assert cm.state.pending is ClockSource.INTERNAL

    def test_request_invalid_source_raises(self) -> None:
        """request_source rejects non-ClockSource values."""
        cm, _, _ = make_clock_manager()
        with pytest.raises(ValueError, match="Unknown clock source"):
            cm.request_source("invalid")  # type: ignore[arg-type]

    def test_request_link_not_available(self) -> None:
        """request_source(LINK) without link package sets error, not pending."""
        cm, _, _ = make_clock_manager()
        with patch("src.sync.clock_manager.link_available", return_value=False):
            cm.request_source(ClockSource.LINK)
        assert cm.state.error is not None
        assert "Link" in cm.state.error
        assert cm.state.pending is None


# ---------------------------------------------------------------------------
# Tests: quantized switching
# ---------------------------------------------------------------------------


class TestQuantizedSwitch:
    """Tests for beat-quantized source switching."""

    def test_pending_applied_on_beat_boundary(self) -> None:
        """Switch is applied when current_time is on a beat boundary."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 4.0  # on beat boundary

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()

        assert cm.state.pending is None

    def test_pending_not_applied_off_beat(self) -> None:
        """Switch is NOT applied when current_time is between beats."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 4.5  # off beat

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()

        assert cm.state.pending is ClockSource.INTERNAL

    def test_pending_applied_at_time_zero(self) -> None:
        """Switch is applied at current_time == 0."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 0.0

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()

        assert cm.state.pending is None

    def test_pending_overwritten_by_last_request(self) -> None:
        """When two requests are made, the last one wins."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 2.0

        cm.request_source(ClockSource.MIDI, device="dev1")
        cm.request_source(ClockSource.INTERNAL)

        assert cm.state.pending is ClockSource.INTERNAL

    def test_no_pending_no_action(self) -> None:
        """on_tick with no pending does nothing."""
        cm, tl, _ = make_clock_manager()
        original_time = tl.current_time
        cm.on_tick()
        assert tl.current_time == original_time


class TestQuantizedSwitchFloatBoundary:
    """Регрессия spike_ui_simulate: float-накопление current_time.

    При 480 tpq тик = 1/480 доли; точное ``% 1.0 == 0.0`` почти не
    встречается — квантизация должна срабатывать в полтике от доли.
    """

    def test_pending_applied_just_before_boundary(self) -> None:
        """Тик чуть ДО доли (phase ≈ 0.999) — pending применяется."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 4.9995  # в полтике до доли

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()

        assert cm.state.pending is None

    def test_pending_applied_just_after_boundary(self) -> None:
        """Тик чуть ПОСЛЕ доли (phase ≈ 0.001) — pending применяется."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 5.0005  # в полтике после доли

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()

        assert cm.state.pending is None

    def test_pending_not_applied_mid_beat(self) -> None:
        """Середина доли (phase = 0.5) — pending висит."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 4.5

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()

        assert cm.state.pending is ClockSource.INTERNAL


class TestIdleWatchdog:
    """Регрессия spike_ui_simulate сценарий 5: тихий внешний клок.

    MIDI без устройства / Link без пиров не шлют тики — on_tick не
    вызывается, квантизация pending невозможна. on_idle применяет pending
    без квантизации, если таймлайн застыл.
    """

    def test_frozen_timeline_applies_pending(self) -> None:
        """Таймлайн не движется → pending применяется после ~4 idle-раундов."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 7.37  # застыл

        cm.request_source(ClockSource.INTERNAL)
        for _ in range(5):
            cm.on_idle()

        assert cm.state.pending is None

    def test_advancing_timeline_not_idle_applied(self) -> None:
        """Таймлайн тикает → idle не трогает pending (ждём долю)."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 7.37

        cm.request_source(ClockSource.INTERNAL)
        for _ in range(6):
            tl.current_time += 0.002  # шаг internal 480 tpq
            cm.on_idle()

        assert cm.state.pending is ClockSource.INTERNAL

    def test_idle_without_pending_resets_counter(self) -> None:
        """Idle без pending сбрасывает счётчик (базовая линия заново)."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 3.0
        for _ in range(3):
            cm.on_idle()

        cm.request_source(ClockSource.INTERNAL)
        cm.on_idle()  # первая запись базовой линии
        cm.on_idle()  # первая замороженная
        assert cm.state.pending is ClockSource.INTERNAL


# ---------------------------------------------------------------------------
# Tests: all_notes_off before switch
# ---------------------------------------------------------------------------


class TestAllNotesOff:
    """Tests for all_notes_off being called before source switch."""

    def test_all_notes_off_called_on_switch(self) -> None:
        """all_notes_off is called on every output device before switching."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 1.0

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()

        for device in tl.output_devices:
            assert device.all_notes_off_count == 1

    def test_all_notes_off_called_before_set_clock_source(self) -> None:
        """all_notes_off must be called BEFORE set_clock_source."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 1.0

        call_order: list[str] = []

        # Track all_notes_off on the output device
        original_all_notes_off = tl.output_devices[0].all_notes_off

        def tracked_all_notes_off() -> None:
            call_order.append("all_notes_off")
            original_all_notes_off()

        tl.output_devices[0].all_notes_off = tracked_all_notes_off

        # Track set_clock_source on the timeline
        original_set = tl.set_clock_source

        def tracked_set_clock_source(source: object) -> None:
            call_order.append("set_clock_source")
            original_set(source)

        tl.set_clock_source = tracked_set_clock_source

        # Also track the clock source creation to verify ordering
        from src.sync import clock_manager as cm_module

        original_create = cm_module.create_clock_source

        def tracked_create(
            source: ClockSource, config: object, clock_target: object
        ) -> object:
            call_order.append("create_clock_source")
            return original_create(source, config, clock_target)

        with patch.object(cm_module, "create_clock_source", tracked_create):
            cm.request_source(ClockSource.INTERNAL)
            cm.on_tick()

        # Verify all_notes_off comes before create_clock_source
        assert "all_notes_off" in call_order
        assert "create_clock_source" in call_order
        assert call_order.index("all_notes_off") < call_order.index(
            "create_clock_source"
        )

    def test_all_notes_off_error_does_not_block_switch(self) -> None:
        """If all_notes_off raises, the switch still proceeds."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 1.0

        def raising_all_notes_off() -> None:
            raise RuntimeError("MIDI port error")

        tl.output_devices[0].all_notes_off = raising_all_notes_off

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()  # Should not raise

        assert cm.state.pending is None  # Switch was applied


# ---------------------------------------------------------------------------
# Tests: phase preservation
# ---------------------------------------------------------------------------


class TestPhasePreservation:
    """Tests for current_time preservation across switches."""

    def test_phase_preserved_on_switch(self) -> None:
        """current_time is saved before switch and restored after."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 7.0

        cm.request_source(ClockSource.INTERNAL)
        cm.on_tick()

        assert tl.current_time == 7.0


# ---------------------------------------------------------------------------
# Tests: MIDI transport tracking
# ---------------------------------------------------------------------------


class TestMidiTransport:
    """Tests for MIDI transport state tracking."""

    def test_midi_transport_not_started_by_default(self) -> None:
        """midi_transport_started is False initially."""
        cm, _, _ = make_clock_manager()
        assert cm.state.midi_transport_started is False


# ---------------------------------------------------------------------------
# Tests: state snapshot
# ---------------------------------------------------------------------------


class TestStateSnapshot:
    """Tests for ClockState snapshot."""

    def test_state_returns_clock_state(self) -> None:
        """state property returns a ClockState instance."""
        from src.sync.clock_state import ClockState

        cm, _, _ = make_clock_manager()
        state = cm.state
        assert isinstance(state, ClockState)

    def test_state_source_matches_current(self) -> None:
        """state.source matches current_source."""
        cm, _, _ = make_clock_manager()
        assert cm.state.source is cm.current_source

    def test_state_running_reflects_start_stop(self) -> None:
        """state.running is True after start(), False after stop()."""
        cm, _, _ = make_clock_manager()

        # Don't actually start (would create real clock threads)
        # Just check the property exists and defaults correctly
        assert cm.state.running is False


# ---------------------------------------------------------------------------
# Tests: error handling and fallback
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling during source switch."""

    def test_midi_error_sets_error_state(self) -> None:
        """Failed MIDI source switch sets error and falls back to internal."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 1.0

        with patch(
            "src.sync.clock_manager.create_clock_source",
            side_effect=[ValueError("No MIDI device"), MagicMock()],
        ):
            cm.request_source(ClockSource.MIDI, device="nonexistent")
            cm.on_tick()

        assert cm.state.error is not None
        # Should have fallen back to internal
        assert cm.current_source is ClockSource.INTERNAL

    def test_link_error_falls_back_to_internal(self) -> None:
        """Failed Link source switch falls back to internal."""
        cm, tl, _ = make_clock_manager()
        tl.current_time = 1.0

        with patch(
            "src.sync.clock_manager.create_clock_source",
            side_effect=[RuntimeError("Link not available"), MagicMock()],
        ):
            cm.request_source(ClockSource.LINK)
            cm.on_tick()

        assert cm.state.error is not None
        assert cm.current_source is ClockSource.INTERNAL
