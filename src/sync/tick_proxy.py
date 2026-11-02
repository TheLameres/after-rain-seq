"""TickProxy — decouples clock source threads from the Timeline worker.

All clock sources (internal Clock, MidiInputDevice, _LinkClockSource) call
``tick()`` / ``reset()`` / ``start()`` / ``stop()`` on this proxy.  The proxy
places events into a single queue.  A dedicated worker thread dequeues and
dispatches them to the Timeline.  This guarantees that all Timeline
processing happens in one thread, regardless of which clock source is active.

Thread safety
-------------
``tick()`` etc. are called from arbitrary threads (rtmidi callback, clock
threads).  They are O(1) and non-blocking (``put_nowait``).  On queue
overflow the oldest event is dropped — better to miss an old tick than to
freeze the MIDI callback.
"""

from __future__ import annotations

import logging
import queue
import threading
from enum import Enum, auto
from typing import Any

log = logging.getLogger(__name__)


class TickEvent(Enum):
    """Types of events that can be placed in the TickProxy queue."""

    TICK = auto()
    RESET = auto()
    START = auto()
    STOP = auto()


class TickProxy:
    """Queue-based tick dispatcher that serialises all Timeline calls.

    Parameters
    ----------
    timeline:
        The isobar Timeline instance to dispatch events to.
    max_queue:
        Maximum queue size.  When full, the oldest event is dropped to make
        room for the new one.  Default 4096 ≈ 2.7 seconds at 480 PPQN.
    """

    def __init__(
        self,
        timeline: Any,
        max_queue: int = 4096,
        on_idle: Any | None = None,
    ) -> None:
        self._timeline = timeline
        self._queue: queue.Queue[TickEvent] = queue.Queue(maxsize=max_queue)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_idle = on_idle

    def set_on_idle(self, cb: Any | None) -> None:
        """Назначить/снять idle-колбэк (вызывается из worker при тишине)."""
        self._on_idle = cb

    # ------------------------------------------------------------------
    # Duck-typed interface for isobar clock sources
    # ------------------------------------------------------------------

    @property
    def ticks_per_beat(self) -> int:
        """Expose the Timeline's ticks_per_beat.

        isobar ``Clock`` reads ``clock_target.ticks_per_beat`` during
        construction to compute the clock multiplier.  We delegate to the
        Timeline so the value is always consistent.
        """
        return getattr(self._timeline, "ticks_per_beat", 480)

    # ------------------------------------------------------------------
    # Producer API — called from any thread (clock sources)
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Enqueue a tick event.  Called by clock sources on each tick."""
        self._enqueue(TickEvent.TICK)

    def reset(self) -> None:
        """Enqueue a reset event.  Called by clock sources on transport reset."""
        self._enqueue(TickEvent.RESET)

    def start(self) -> None:
        """Enqueue a start event.  Called by clock sources on transport start."""
        self._enqueue(TickEvent.START)

    def stop(self) -> None:
        """Enqueue a stop event.  Called by clock sources on transport stop."""
        self._enqueue(TickEvent.STOP)

    # ------------------------------------------------------------------
    # Consumer API — worker thread management
    # ------------------------------------------------------------------

    def start_worker(self) -> None:
        """Start the worker daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="tick-proxy",
            daemon=True,
        )
        self._thread.start()
        log.info("TickProxy worker started")

    def stop_worker(self) -> None:
        """Signal the worker to stop and wait for it."""
        self._stop_event.set()
        # Unblock the worker if it is waiting on queue.get()
        try:
            self._queue.put_nowait(TickEvent.STOP)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        log.info("TickProxy worker stopped")

    @property
    def is_running(self) -> bool:
        """True if the worker thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _enqueue(self, event: TickEvent) -> None:
        """Place an event in the queue, dropping the oldest if full."""
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # Drop oldest to make room — never block the producer
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except queue.Empty:
                # Race: queue was drained between get and put — retry once
                try:
                    self._queue.put_nowait(event)
                except queue.Full:
                    log.warning("TickProxy: queue still full after drop, event lost")

    def _run(self) -> None:
        """Worker thread main loop — dequeues and dispatches events."""
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=0.1)
            except queue.Empty:
                # Тишина (~0.1 с без тиков): шанс для watchdog-колбэка
                # (квантизация клока при мёртвом внешнем источнике).
                if self._on_idle is not None:
                    try:
                        self._on_idle()
                    except Exception as exc:  # noqa: BLE001
                        log.warning("TickProxy on_idle error: %s", exc)
                continue

            if self._stop_event.is_set():
                break

            self._dispatch(event)

    def _dispatch(self, event: TickEvent) -> None:
        """Dispatch a single event to the Timeline."""
        match event:
            case TickEvent.TICK:
                self._timeline.tick()
            case TickEvent.RESET:
                self._timeline.reset()
            case TickEvent.START:
                self._timeline.start()
            case TickEvent.STOP:
                self._timeline.stop()
