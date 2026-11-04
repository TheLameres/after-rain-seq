"""Transport — MIDI event delivery engine.

Picks up :class:`TransportEvent` instances from the CaptureOutput queue,
applies swing (onset delay) and delivers them to physical MIDI ports via
:class:`PortRegistry`.

Swing lives here and nowhere else (plan §4.2): engines emit unmodified
musical beats, and this layer decides *when* to hand each NOTE_ON to the
port.  Events that swing pushes into the future wait in a small buffer
and are released by a later ``process_events()`` call.

Two modes under one interface (plan v5.4 §5.1):

- **Mode A (ISOBAR)** — isobar Timeline drives ticks via TickProxy.
  ``process_events()`` is called from the TickProxy dispatch hook after
  each ``timeline.tick()``.  Delivery happens in the same thread as
  generation.  This is the starting mode.

- **Mode B (EXTERNAL)** — own thread with look-ahead scheduling using
  ``perf_counter()``.  Interface is in place; implementation deferred
  until Mode A precision is evaluated on target hardware.

Three rules mandatory in both modes (plan v5.4 §5.1):

1. ``int()`` on all values from isobar (``numpy.int64`` breaks mido)
2. CC throttling on output (flush at bar boundaries)
3. ``all_notes_off`` on panic and port loss
"""

from __future__ import annotations

import logging
import queue
from enum import Enum, auto
from typing import TYPE_CHECKING

from src.sync.swing import SwingApplier
from src.sync.transport_event import EventKind, TransportEvent

if TYPE_CHECKING:
    from src.sync.routing import PortRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TransportMode enum
# ---------------------------------------------------------------------------


class TransportMode(Enum):
    """Delivery mode for the transport engine."""

    ISOBAR = auto()  # Mode A: delivery in TickProxy worker thread
    EXTERNAL = auto()  # Mode B: own thread with look-ahead (TODO)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class Transport:
    """MIDI event delivery engine.

    Parameters
    ----------
    event_queue:
        The queue fed by :class:`CaptureOutput`.
    port_registry:
        Registry of active output ports for event delivery.
    swing:
        Swing applier for duration transformation.  Use a default
        :class:`SwingApplier` with amount=0 for no swing.
    mode:
        Delivery mode.  Default is ``TransportMode.ISOBAR``.

    Usage
    -----
    >>> transport = Transport(queue, registry, swing)
    >>> # In TickProxy dispatch hook, after timeline.tick():
    >>> transport.process_events()
    """

    _EPSILON: float = 1e-9

    def __init__(
        self,
        event_queue: queue.Queue[TransportEvent],
        port_registry: PortRegistry,
        swing: SwingApplier,
        mode: TransportMode = TransportMode.ISOBAR,
    ) -> None:
        self._queue = event_queue
        self._registry = port_registry
        self._swing = swing
        self._mode = mode
        self._last_bar_flush: int = -1
        # Свинг сдвигает onset в будущее — ждущие события лежат здесь,
        # отсортированные по моменту отправки (plan §4.2).
        self._held: list[tuple[float, TransportEvent]] = []
        # Страховка от неограниченного роста, если timeline встал.
        self._max_held: int = 512

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def mode(self) -> TransportMode:
        """Current delivery mode."""
        return self._mode

    @property
    def swing(self) -> SwingApplier:
        """Swing applier instance."""
        return self._swing

    def set_mode(self, mode: TransportMode) -> None:
        """Switch delivery mode.

        Mode B (EXTERNAL) is not yet implemented — raises
        ``NotImplementedError``.
        """
        if mode is TransportMode.EXTERNAL:
            raise NotImplementedError(
                "TransportMode.EXTERNAL is not yet implemented. "
                "Use TransportMode.ISOBAR."
            )
        self._mode = mode

    def process_events(self, current_beat: float = 0.0) -> int:
        """Drain the event queue and deliver all events.

        Called after each ``timeline.tick()`` from the TickProxy dispatch
        hook.  Delivers events (swing is already applied upstream) to ports via
        :class:`PortRegistry`, and flushes throttled CC at bar boundaries.

        Parameters
        ----------
        current_beat:
            Current timeline position in beats.  Used for swing step
            detection and bar-boundary CC flush.

        Returns
        -------
        int
            Number of events delivered.
        """
        delivered = 0
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            deliver_at = self._schedule(event, current_beat)
            if deliver_at is None:
                delivered += 1

        delivered += self._release_due(current_beat)

        # Flush CC at bar boundaries (every 4 beats)
        bar_number = int(current_beat // 4)
        if bar_number != self._last_bar_flush:
            self._last_bar_flush = bar_number
            self._registry.flush_all()

        return delivered

    def all_notes_off(self) -> None:
        """Panic: silence all notes on all ports and clear the queue.

        Clears pending events so nothing is delivered after the silence.
        Resets the swing applier step counter.
        """
        # Drain queue
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        # Отложенные свингом события тоже не должны прозвучать после паники.
        self._held.clear()

        # Silence all ports
        for adapter in self._registry.all_outputs():
            try:
                adapter.all_notes_off()
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Transport: all_notes_off error on %r: %s", adapter.label, exc
                )

        # Reset swing state
        self._swing.reset()

        # Reset bar flush tracker
        self._last_bar_flush = -1

        log.info("Transport: all notes off")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _schedule(self, event: TransportEvent, current_beat: float) -> float | None:
        """Отправить сейчас или отложить по свингу.

        Свинг сдвигает только *onset* (NOTE_ON): длительность ноты задаётся
        моментом NOTE_OFF, который приходит отдельным событием и не трогается,
        поэтому пара сохраняет длину, а groove меняется.

        Returns:
            Момент отложенной отправки, либо ``None``, если событие уже
            передано в порт.
        """
        # Свинг касается только начала ноты.
        if event.kind is not EventKind.NOTE_ON:
            self._deliver(event, current_beat)
            return None

        delay = self._swing.shift(event.beat)
        if delay <= 0.0:
            self._deliver(event, current_beat)
            return None

        deliver_at = event.beat + delay
        if deliver_at <= current_beat + self._EPSILON:
            # Событие уже «прозевало» свой сдвиг — не тянем его в будущее.
            self._deliver(event, current_beat)
            return None

        if len(self._held) >= self._max_held:
            log.warning("Transport: swing buffer full, dropping held event")
            return deliver_at
        self._held.append((deliver_at, event))
        self._held.sort(key=lambda item: item[0])
        return deliver_at

    def _release_due(self, current_beat: float) -> int:
        """Отправить отложенные события, чей момент наступил."""
        released = 0
        limit = current_beat + self._EPSILON
        while self._held and self._held[0][0] <= limit:
            _, event = self._held.pop(0)
            self._deliver(event, current_beat)
            released += 1
        return released

    def _deliver(self, event: TransportEvent, current_beat: float) -> None:
        """Deliver a single event to its target port."""
        adapter = self._registry.get_output(event.port_label)
        if adapter is None:
            log.debug(
                "Transport: no port for label %r, dropping event %s",
                event.port_label,
                event.kind.name,
            )
            return

        match event.kind:
            case EventKind.NOTE_ON:
                self._deliver_note_on(adapter, event, current_beat)
            case EventKind.NOTE_OFF:
                adapter.note_off(
                    channel=int(event.channel),
                    note=int(event.note),  # type: ignore[arg-type]
                )
            case EventKind.CONTROL_CHANGE:
                adapter.control_change(
                    channel=int(event.channel),
                    control=int(event.control),  # type: ignore[arg-type]
                    value=int(event.value),  # type: ignore[arg-type]
                )
            case EventKind.ALL_NOTES_OFF:
                adapter.all_notes_off()

    def _deliver_note_on(
        self, adapter: object, event: TransportEvent, current_beat: float
    ) -> None:
        """Deliver a NOTE_ON.

        Timing was already decided in :meth:`_schedule`; the port API takes
        no duration, so there is nothing to transform here.
        """
        adapter.note_on(  # type: ignore[attr-defined]
            channel=int(event.channel),
            note=int(event.note),  # type: ignore[arg-type]
            velocity=int(event.velocity),  # type: ignore[arg-type]
        )
