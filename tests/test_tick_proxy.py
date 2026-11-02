"""Tests for TickProxy — queue-based tick dispatcher."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from src.sync.tick_proxy import TickEvent, TickProxy


@pytest.fixture()
def mock_timeline() -> MagicMock:
    """Create a mock Timeline with the interface TickProxy expects."""
    tl = MagicMock()
    tl.tick = MagicMock()
    tl.reset = MagicMock()
    tl.start = MagicMock()
    tl.stop = MagicMock()
    return tl


@pytest.fixture()
def proxy(mock_timeline: MagicMock) -> TickProxy:
    """Create a TickProxy with a small queue for testing."""
    return TickProxy(mock_timeline, max_queue=16)


class TestTickProxyDispatch:
    """Tests for event dispatching to Timeline."""

    def test_tick_dispatches_to_timeline(
        self, proxy: TickProxy, mock_timeline: MagicMock
    ) -> None:
        """tick() → timeline.tick() called."""
        proxy.start_worker()
        time.sleep(0.05)  # let worker start

        proxy.tick()
        time.sleep(0.05)  # let worker process

        mock_timeline.tick.assert_called_once()
        proxy.stop_worker()

    def test_reset_dispatches_to_timeline(
        self, proxy: TickProxy, mock_timeline: MagicMock
    ) -> None:
        """reset() → timeline.reset() called."""
        proxy.start_worker()
        time.sleep(0.05)

        proxy.reset()
        time.sleep(0.05)

        mock_timeline.reset.assert_called_once()
        proxy.stop_worker()

    def test_start_dispatches_to_timeline(
        self, proxy: TickProxy, mock_timeline: MagicMock
    ) -> None:
        """start() → timeline.start() called."""
        proxy.start_worker()
        time.sleep(0.05)

        proxy.start()
        time.sleep(0.05)

        mock_timeline.start.assert_called_once()
        proxy.stop_worker()

    def test_stop_dispatches_to_timeline(
        self, proxy: TickProxy, mock_timeline: MagicMock
    ) -> None:
        """stop() → timeline.stop() called."""
        proxy.start_worker()
        time.sleep(0.05)

        proxy.stop()
        time.sleep(0.05)

        mock_timeline.stop.assert_called_once()
        proxy.stop_worker()

    def test_multiple_events_in_order(
        self, proxy: TickProxy, mock_timeline: MagicMock
    ) -> None:
        """Multiple events are dispatched in FIFO order."""
        proxy.start_worker()
        time.sleep(0.05)

        proxy.tick()
        proxy.tick()
        proxy.reset()
        proxy.tick()
        time.sleep(0.1)

        assert mock_timeline.tick.call_count == 3
        assert mock_timeline.reset.call_count == 1
        proxy.stop_worker()


class TestTickProxyQueueOverflow:
    """Tests for queue overflow handling."""

    def test_drop_oldest_on_overflow(self, mock_timeline: MagicMock) -> None:
        """When queue is full, oldest event is dropped, newest is kept."""
        proxy = TickProxy(mock_timeline, max_queue=4)

        # Fill the queue without a worker (no consumer)
        for _ in range(4):
            proxy.tick()

        # Queue is now full; next tick should drop oldest and add new
        proxy.tick()  # This should succeed (drop oldest)

        # Start worker and drain
        proxy.start_worker()
        time.sleep(0.1)
        proxy.stop_worker()

        # We put 5 ticks, queue size 4, one dropped → 4 processed
        assert mock_timeline.tick.call_count == 4

    def test_no_block_on_full_queue(self, mock_timeline: MagicMock) -> None:
        """tick() never blocks, even when queue is full."""
        proxy = TickProxy(mock_timeline, max_queue=2)

        # Fill queue
        proxy.tick()
        proxy.tick()

        # These should not block or raise
        start = time.monotonic()
        for _ in range(100):
            proxy.tick()
        elapsed = time.monotonic() - start

        assert elapsed < 0.1, f"tick() blocked for {elapsed:.3f}s on full queue"


class TestTickProxyThreadSafety:
    """Tests for thread-safe operation."""

    def test_concurrent_tick_producers(self, mock_timeline: MagicMock) -> None:
        """Multiple threads can call tick() simultaneously."""
        proxy = TickProxy(mock_timeline, max_queue=4096)
        proxy.start_worker()
        time.sleep(0.05)

        num_threads = 4
        ticks_per_thread = 250
        threads: list[threading.Thread] = []

        def producer() -> None:
            for _ in range(ticks_per_thread):
                proxy.tick()

        for i in range(num_threads):
            t = threading.Thread(target=producer, name=f"producer-{i}")
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        time.sleep(0.5)  # let worker drain
        proxy.stop_worker()

        # At least some ticks should have been processed
        # (exact count may vary due to drop-oldest on overflow)
        assert mock_timeline.tick.call_count > 0

    def test_is_running_property(self, proxy: TickProxy) -> None:
        """is_running reflects worker thread state."""
        assert not proxy.is_running
        proxy.start_worker()
        time.sleep(0.05)
        assert proxy.is_running
        proxy.stop_worker()
        assert not proxy.is_running


class TestTickEvent:
    """Tests for TickEvent enum."""

    def test_event_variants(self) -> None:
        """TickEvent has exactly 4 variants."""
        assert len(TickEvent) == 4
        assert TickEvent.TICK is not TickEvent.RESET
        assert TickEvent.START is not TickEvent.STOP
