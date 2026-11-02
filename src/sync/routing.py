"""Port routing — isobar-compatible output adapters and port lifecycle registry.

This module provides:
- :class:`MidiPortOutput` — wraps a :class:`MidiOutPort` in the interface
  that isobar Timeline expects from its output devices, plus CC mapping
  and throttling for logical parameter names
- :class:`PortRegistry` — manages the lifecycle of opened output ports,
  mapping human-readable labels to active adapters

The registry reacts to :class:`PortEvent` instances from PortManager:
- ``CONNECTED`` → open the port, create a MidiPortOutput
- ``DISCONNECTED`` / ``AMBIGUOUS`` → all_notes_off, close the port
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.midi.abc import MidiMessage
from src.sync.cc_map import CCMap, CCMapError
from src.sync.port_state import PortStatus
from src.sync.ports import PortEvent, PortManager
from src.sync.throttle import CCThrottle

if TYPE_CHECKING:
    from src.midi.abc import MidiOutPort

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MidiPortOutput — isobar-compatible output device
# ---------------------------------------------------------------------------


class MidiPortOutput:
    """Adapter that exposes a :class:`MidiOutPort` as an isobar output device.

    isobar Timeline calls these methods on every output device in
    ``timeline.output_devices``:

    - ``all_notes_off()``
    - ``note_on(channel, note, velocity)``
    - ``note_off(channel, note)``
    - ``control_change(channel, control, value)``

    In addition, this adapter provides CC automation with logical parameter
    names (plan v5.4 §2.4):

    - ``control(param_name, channel, value)`` — resolve logical name via
      :class:`CCMap`, transform value (invert + range), submit to throttle
    - ``flush()`` — deliver all pending throttled CC values

    All numeric values are converted with ``int()`` because isobar may
    produce ``numpy.int64`` which mido cannot handle directly.

    Parameters
    ----------
    label:
        Human-readable port label from config (e.g. ``"Синт A"``).
    port:
        The underlying :class:`MidiOutPort` to send through.
    cc_map:
        Optional :class:`CCMap` for resolving logical parameter names.
        If ``None``, :meth:`control` is a no-op.
    throttle:
        Optional :class:`CCThrottle` for rate-limiting CC.  If ``None``,
        :meth:`control` sends immediately without throttling.
    """

    def __init__(
        self,
        label: str,
        port: MidiOutPort,
        cc_map: CCMap | None = None,
        throttle: CCThrottle | None = None,
    ) -> None:
        self.label = label
        self._port = port
        self._cc_map = cc_map
        self._throttle = throttle

    # ------------------------------------------------------------------
    # isobar output device interface
    # ------------------------------------------------------------------

    def all_notes_off(self) -> None:
        """Send All Notes Off (CC 123) on all 16 channels.

        Also resets the CC throttle so no stale pending values are
        delivered after the silence.
        """
        for ch in range(16):
            self._port.send(MidiMessage.cc(channel=ch, control=123, value=0))
        if self._throttle is not None:
            self._throttle.reset()

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        """Send a Note On message."""
        self._port.send(
            MidiMessage.note_on(
                channel=int(channel),
                note=int(note),
                velocity=int(velocity),
            )
        )

    def note_off(self, channel: int, note: int) -> None:
        """Send a Note Off message."""
        self._port.send(
            MidiMessage.note_off(
                channel=int(channel),
                note=int(note),
            )
        )

    def control_change(self, channel: int, control: int, value: int) -> None:
        """Send a Control Change message directly (no mapping, no throttling).

        Use this for service CCs like All Notes Off (CC 123) or when the
        caller already knows the exact CC number.
        """
        self._port.send(
            MidiMessage.cc(
                channel=int(channel),
                control=int(control),
                value=int(value),
            )
        )

    # ------------------------------------------------------------------
    # CC automation: logical names + throttling
    # ------------------------------------------------------------------

    def control(self, param_name: str, channel: int, value: int) -> None:
        """Send CC by logical parameter name with mapping and throttling.

        Resolution chain (plan v5.4 §2.4):

        1. Resolve *param_name* → CC number via :class:`CCMap`.
        2. Transform value through invert + range.
        3. Submit to :class:`CCThrottle` — may be deferred to ``flush()``.

        Silently ignores (with a warning) when:

        - ``cc_map`` is ``None`` (no mapping configured)
        - Port has ``_no_automation: true``
        - *param_name* is not found in the mapping (:class:`CCMapError`)

        Parameters
        ----------
        param_name:
            Logical parameter name, e.g. ``"filter"``, ``"resonance"``.
        channel:
            MIDI channel, 0–15.
        value:
            Normalised CC value, 0–127 (before invert/range transform).
        """
        if self._cc_map is None:
            log.debug(
                "MidiPortOutput %r: no CCMap, ignoring %r", self.label, param_name
            )
            return

        try:
            entry = self._cc_map.resolve(self.label, param_name)
        except CCMapError:
            log.warning(
                "MidiPortOutput %r: unknown CC parameter %r",
                self.label,
                param_name,
            )
            return

        # Port opts out of CC automation
        if entry is None:
            return

        transformed = entry.transform(int(value))

        if self._throttle is not None:
            events = self._throttle.submit(
                port=self.label,
                channel=int(channel),
                cc=int(entry.cc),
                value=transformed,
            )
            for event in events:
                self._port.send(
                    MidiMessage.cc(
                        channel=int(event.key.channel),
                        control=int(event.key.cc),
                        value=int(event.value),
                    )
                )
        else:
            self._port.send(
                MidiMessage.cc(
                    channel=int(channel),
                    control=int(entry.cc),
                    value=transformed,
                )
            )

    def flush(self) -> None:
        """Deliver all pending throttled CC values.

        Call at the end of each transport tick or bar to guarantee the
        final value of a CC sweep is delivered.
        """
        if self._throttle is None:
            return
        for event in self._throttle.flush():
            self._port.send(
                MidiMessage.cc(
                    channel=int(event.key.channel),
                    control=int(event.key.cc),
                    value=int(event.value),
                )
            )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """True if the underlying port is still available."""
        return self._port is not None

    def __repr__(self) -> str:
        return f"MidiPortOutput(label={self.label!r})"


# ---------------------------------------------------------------------------
# PortRegistry
# ---------------------------------------------------------------------------


class PortRegistry:
    """Manages opened output ports and their MidiPortOutput adapters.

    Maps configured port labels to active :class:`MidiPortOutput` instances.
    Reacts to :class:`PortEvent` from PortManager to open/close ports.

    Parameters
    ----------
    port_manager:
        The PortManager instance used to resolve labels to system port names.
    out_port_factory:
        Factory callable that creates a new MidiOutPort.  Defaults to
        :func:`src.midi.factory.create_out_port`.
    cc_map:
        Optional :class:`CCMap` passed to every created MidiPortOutput.
    throttle:
        Optional :class:`CCThrottle` passed to every created MidiPortOutput.

    Usage
    -----
    >>> registry = PortRegistry(port_manager, cc_map=cc_map, throttle=throttle)
    >>> for event in port_manager.poll():
    ...     registry.handle_port_event(event)
    >>> adapter = registry.get_output("Синт A")
    >>> if adapter:
    ...     adapter.note_on(channel=0, note=60, velocity=100)
    """

    def __init__(
        self,
        port_manager: PortManager,
        out_port_factory: Callable[[], MidiOutPort] | None = None,
        cc_map: CCMap | None = None,
        throttle: CCThrottle | None = None,
    ) -> None:
        self._pm = port_manager
        self._factory = out_port_factory or self._default_factory
        self._cc_map = cc_map
        self._throttle = throttle
        self._adapters: dict[str, MidiPortOutput] = {}
        self._raw_ports: dict[str, MidiOutPort] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_output(self, label: str) -> MidiPortOutput | None:
        """Return the adapter for *label*, or ``None`` if not connected.

        A ``None`` return means the track using this port should be silent —
        the session continues running.
        """
        return self._adapters.get(label)

    def all_outputs(self) -> list[MidiPortOutput]:
        """Return all active output adapters."""
        return list(self._adapters.values())

    def flush_all(self) -> None:
        """Flush pending throttled CC values on all active ports."""
        for adapter in self._adapters.values():
            adapter.flush()

    def flush_port(self, label: str) -> None:
        """Flush pending throttled CC values on a specific port."""
        adapter = self._adapters.get(label)
        if adapter is not None:
            adapter.flush()

    def handle_port_event(self, event: PortEvent) -> None:
        """React to a port status change.

        - ``CONNECTED`` → open the port and create an adapter
        - ``DISCONNECTED`` / ``AMBIGUOUS`` / ``ERROR`` → all_notes_off + close
        """
        if event.direction != "output":
            return

        if event.new_status is PortStatus.CONNECTED:
            self._open_port(event.label, event.resolved_name)
        elif event.new_status in (
            PortStatus.DISCONNECTED,
            PortStatus.AMBIGUOUS,
            PortStatus.ERROR,
        ):
            self._close_port(event.label)

    def stop(self) -> None:
        """Close all ports and clear all adapters."""
        for label in list(self._adapters.keys()):
            self._close_port(label)
        log.info("PortRegistry stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open_port(self, label: str, resolved_name: str | None) -> None:
        """Open a port and create an adapter."""
        if resolved_name is None:
            log.warning("PortRegistry: cannot open %r — no resolved name", label)
            return

        # Already open — close first (reconnect scenario)
        if label in self._adapters:
            self._close_port(label)

        try:
            raw: MidiOutPort = self._factory()
            raw.open(resolved_name)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "PortRegistry: failed to open %r (%s): %s", label, resolved_name, exc
            )
            return

        adapter = MidiPortOutput(
            label=label,
            port=raw,
            cc_map=self._cc_map,
            throttle=self._throttle,
        )
        self._adapters[label] = adapter
        self._raw_ports[label] = raw
        log.info("PortRegistry: opened %r → %s", label, resolved_name)

    def _close_port(self, label: str) -> None:
        """Silence and close a port, removing its adapter."""
        adapter = self._adapters.pop(label, None)
        raw = self._raw_ports.pop(label, None)

        if adapter is not None:
            try:
                adapter.all_notes_off()
            except Exception as exc:  # noqa: BLE001
                log.warning("PortRegistry: all_notes_off error for %r: %s", label, exc)

        if raw is not None:
            try:
                raw.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("PortRegistry: close error for %r: %s", label, exc)

        if adapter is not None or raw is not None:
            log.info("PortRegistry: closed %r", label)

    @staticmethod
    def _default_factory() -> MidiOutPort:
        """Default factory — creates a MidoOutPort."""
        from src.midi.factory import create_out_port

        return create_out_port()
