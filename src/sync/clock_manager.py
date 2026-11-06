"""ClockManager — manages clock source switching for the isobar Timeline.

Wraps three clock sources (internal, MIDI, Link) and provides:
- Runtime switching with beat-quantized application
- ``all_notes_off()`` before every switch (prevents stuck notes)
- Link package availability check with explicit error
- MIDI transport state tracking
- Phase preservation across switches (current_time)

The ClockManager does not receive ticks directly.  Instead, it hooks into
the TickProxy dispatch loop via :meth:`on_tick`, which is called by the
TickProxy worker thread before dispatching each event to the Timeline.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.sync.clock_source import (
    ClockManagerConfig,
    ClockSource,
    _LinkClockSource,
    create_clock_source,
    link_available,
)
from src.sync.clock_state import ClockState

if TYPE_CHECKING:
    from src.sync.tick_proxy import TickProxy

log = logging.getLogger(__name__)

# Допуск «на доле» для квантизации переключения клока: полтика при 480 tpq
# (см. on_tick — float-накопление current_time убивает точное равенство).
_BEAT_EPSILON = 0.001


class ClockManager:
    """Manages the active clock source for an isobar Timeline.

    Parameters
    ----------
    timeline:
        The isobar Timeline instance.
    tick_proxy:
        The TickProxy that serialises ticks into a single worker thread.
    config:
        ClockManagerConfig with initial source, BPM, and MIDI device.

    Usage
    -----
    >>> cm = ClockManager(timeline, proxy, config)
    >>> cm.start()                     # start initial source
    >>> cm.request_source(ClockSource.MIDI, device="LCXL3 DAW Out")
    >>> # switch applied on next beat boundary
    >>> cm.stop()                      # stop current source
    """

    def __init__(
        self,
        timeline: Any,
        tick_proxy: TickProxy,
        config: ClockManagerConfig,
    ) -> None:
        self._timeline = timeline
        self._proxy = tick_proxy
        self._config = config

        self._current: ClockSource = config.initial_source
        self._pending: tuple[ClockSource, str | None] | None = None
        self._clock_source: Any = None  # active isobar clock source object

        self._midi_transport_started: bool = False
        self._error: str | None = None
        self._running: bool = False
        # Слушатели транспорта: (event, beat), event = "start" | "stop".
        # Вызываются до активации/после остановки источника (порядок важен
        # для MIDI-выхода: Start должен уйти раньше первого импульса).
        self._transport_listeners: list[Callable[[str, float], None]] = []

        # Watchdog квантизации: сколько idle-раундов подряд таймлайн
        # не продвинулся (тихий внешний клок — MIDI без устройства,
        # Link без пиров: тиков нет, on_tick не вызывается, pending
        # квантизировать некому). См. on_idle.
        self._idle_last_time: float | None = None
        self._idle_frozen_rounds = 0
        self._proxy.set_on_idle(self.on_idle)

        # Lock protects _pending and _current from concurrent access
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def add_transport_listener(self, listener: Callable[[str, float], None]) -> None:
        """Подписаться на старт/стоп транспорта (для исходящего MIDI Clock)."""
        self._transport_listeners.append(listener)

    def _notify_transport(self, event: str) -> None:
        beat = float(self._timeline.current_time)
        for listener in self._transport_listeners:
            try:
                listener(event, beat)
            except Exception as exc:  # noqa: BLE001 — слушатель не должен ронять часы
                log.warning("ClockManager: transport listener %s error: %s", event, exc)

    def start(self) -> None:
        """Start the initial clock source.

        Если внешний источник не открывается (нет порта, занят, нет прав),
        запуск не роняет приложение: причина уходит в ``state.error``, а
        транспорт поднимается на внутренних часах.
        """
        if self._running:
            return
        self._running = True
        self._notify_transport("start")
        try:
            self._activate_source(
                self._config.initial_source, self._config.midi_device_name
            )
        except (RuntimeError, ValueError) as exc:
            source = self._config.initial_source
            log.error("ClockManager: start with %s failed: %s", source.name, exc)
            if source is ClockSource.INTERNAL:
                self._running = False
                raise
            log.info("ClockManager: falling back to internal clock")
            self._error = str(exc)
            self._current = ClockSource.INTERNAL
            self._activate_source(ClockSource.INTERNAL, None)
        log.info("ClockManager started (source=%s)", self._current.name)

    def stop(self) -> None:
        """Stop the current clock source and silence all notes."""
        if not self._running:
            return
        self._running = False
        self._all_notes_off()
        self._notify_transport("stop")
        self._stop_current_source()
        log.info("ClockManager stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_source(self, source: ClockSource, device: str | None = None) -> None:
        """Request a clock source switch.

        The switch is queued and applied on the next beat boundary
        (when ``current_time % 1 == 0``).  If another request is made
        before the pending one is applied, the last request wins.

        Parameters
        ----------
        source:
            The desired clock source.
        device:
            MIDI device name (only for MIDI source).  ``None`` means
            use ``ISOBAR_DEFAULT_MIDI_IN``.

        Raises
        ------
        ValueError
            If the source is not a valid ClockSource.
        """
        if not isinstance(source, ClockSource):
            raise ValueError(f"Unknown clock source: {source!r}")

        # Pre-flight check for Link
        if source is ClockSource.LINK and not link_available():
            self._error = "Ableton Link not installed (pip install LinkPython-extern)"
            log.warning("ClockManager: %s", self._error)
            return

        with self._lock:
            self._pending = (source, device)
            self._error = None

        log.info(
            "ClockManager: requested switch to %s (device=%r), pending beat boundary",
            source.name,
            device,
        )

    @property
    def state(self) -> ClockState:
        """Build a ClockState snapshot for display."""
        bpm: float | None = None
        link_peers = 0

        if self._clock_source is not None:
            try:
                bpm = self._clock_source.tempo
            except Exception:
                bpm = None

        link_active = self._current is ClockSource.LINK and self._error is None
        if link_active and self._clock_source is not None:
            link_peers = getattr(self._clock_source, "_peers", 0)

        with self._lock:
            pending_source = self._pending[0] if self._pending else None

        return ClockState(
            source=self._current,
            pending=pending_source,
            bpm=bpm,
            midi_transport_started=self._midi_transport_started,
            link_peers=link_peers,
            link_active=link_active,
            error=self._error,
            running=self._running,
        )

    @property
    def current_source(self) -> ClockSource:
        """Currently active clock source."""
        return self._current

    # ------------------------------------------------------------------
    # TickProxy hook — called from worker thread before each dispatch
    # ------------------------------------------------------------------

    def on_tick(self) -> None:
        """Called by TickProxy worker before dispatching each event.

        Checks for pending source switch and applies it if we are on
        a beat boundary (``current_time % 1 == 0``).
        """
        with self._lock:
            has_pending = self._pending is not None

        if not has_pending:
            return

        # Тик = 1/480 доли; float-накопление делает точное `% 1.0 == 0.0`
        # почти недостижимым на работающем транспорте (найдено spike_ui_simulate:
        # pending «висел» бесконечно). Допуск — полтика при 480 tpq.
        current_time = self._timeline.current_time
        phase = current_time % 1.0
        if phase < _BEAT_EPSILON or phase > 1.0 - _BEAT_EPSILON:
            self._apply_pending()

    def on_idle(self) -> None:
        """TickProxy worker жив, но тиков нет (~0.1 c тишины).

        Внешний клок без сигнала (MIDI без устройства, Link без пиров)
        не шлёт тики — квантизация pending на доле невозможна в принципе.
        Если таймлайн застыл, применяем pending без квантизации: лучше
        переключиться сразу, чем висеть до перезапуска. Найдено
        spike_ui_simulate (сценарий 5: возврат internal после midi).
        """
        with self._lock:
            if self._pending is None:
                self._idle_frozen_rounds = 0
                self._idle_last_time = None
                return

        current = self._timeline.current_time
        if current == self._idle_last_time:
            self._idle_frozen_rounds += 1
        else:
            self._idle_frozen_rounds = 0
            self._idle_last_time = current

        if self._idle_frozen_rounds >= 4:  # ~0.4–0.5 c без прогресса
            log.info(
                "ClockManager: timeline frozen at beat %.3f — applying pending "
                "switch without beat quantization",
                current,
            )
            self._apply_pending()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_pending(self) -> None:
        """Apply the pending source switch.

        Steps:
        1. Clear pending
        2. all_notes_off() on all output devices
        3. Stop old source
        4. Save phase (current_time)
        5. Create and start new source
        6. Restore phase
        """
        with self._lock:
            if self._pending is None:
                return
            source, device = self._pending
            self._pending = None

        log.info(
            "ClockManager: applying switch %s → %s at beat %.2f",
            self._current.name,
            source.name,
            self._timeline.current_time,
        )

        # 1. Silence all notes before switching
        self._all_notes_off()

        # 2. Stop old source
        self._stop_current_source()

        # 3. Save phase
        saved_beats = self._timeline.current_time

        # 4. Create and activate new source
        try:
            self._activate_source(source, device)
        except (RuntimeError, ValueError) as exc:
            self._error = str(exc)
            log.error("ClockManager: switch to %s failed: %s", source.name, exc)
            # Fall back to internal clock
            if source is not ClockSource.INTERNAL:
                log.info("ClockManager: falling back to internal clock")
                self._activate_source(ClockSource.INTERNAL, None)
            return

        # 5. Restore phase
        self._timeline.current_time = saved_beats

        self._current = source
        self._error = None
        log.info("ClockManager: now using %s", source.name)

    def _activate_source(self, source: ClockSource, device: str | None) -> None:
        """Create and start a clock source.

        Raises
        ------
        RuntimeError
            If Link is not available.
        ValueError
            If MIDI device cannot be opened.
        """
        cfg = ClockManagerConfig(
            initial_source=source,
            initial_bpm=self._config.initial_bpm,
            ticks_per_beat=self._config.ticks_per_beat,
            midi_device_name=device
            if device is not None
            else self._config.midi_device_name,
        )

        clock_src = create_clock_source(source, cfg, clock_target=self._proxy)
        self._clock_source = clock_src
        self._current = source

        # Start the source
        if source is ClockSource.INTERNAL:
            # isobar Clock has background() that starts a daemon thread
            clock_src.background()
        elif source is ClockSource.LINK:
            # _LinkClockSource has background()
            clock_src.background()
        elif source is ClockSource.MIDI:
            clock_src.background()

    def _stop_current_source(self) -> None:
        """Stop the currently active clock source."""
        if self._clock_source is None:
            return

        src = self._clock_source
        self._clock_source = None

        try:
            if isinstance(src, _LinkClockSource):
                src.stop()
                src.wait(timeout=2.0)
            elif hasattr(src, "stop"):
                src.stop()
        except Exception as exc:
            log.debug("ClockManager: error stopping source: %s", exc)

        # For internal Clock, also join the thread if background() was used
        if hasattr(src, "_thread") and src._thread is not None:
            try:
                src._thread.join(timeout=1.0)
            except Exception:
                pass

    def _all_notes_off(self) -> None:
        """Send all-notes-off to every output device on the Timeline."""
        devices = getattr(self._timeline, "output_devices", None)
        if devices is None:
            return
        for device in devices:
            try:
                device.all_notes_off()
            except Exception as exc:
                log.warning("ClockManager: all_notes_off error: %s", exc)
