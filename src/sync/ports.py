"""Port discovery, identification, and hot-plug monitoring.

This module provides:
- :class:`PortConfig` — Pydantic model for a single port entry in config.yaml
- :class:`PortsConfig` — Pydantic model for the ``ports:`` config section
- :class:`PortEvent` — frozen dataclass describing a port status change
- :class:`PortManager` — discovery, identification, hot-plug polling

Identification strategy: **label for humans, fingerprint for code**.

The ``match`` substring is used to find candidate ports.  When exactly one
candidate matches, the port is selected.  When multiple candidates match,
the optional ``serial`` field resolves the ambiguity.  Without a serial the
port is marked ``AMBIGUOUS`` — an explicit error, never a guess.

Hot-plug: :meth:`PortManager.poll` is called periodically from the main
loop.  It detects appearance, disappearance, and ambiguity changes and
returns :class:`PortEvent` instances so the caller can react (open/close
ports, silence notes, update the display).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from src.sync.port_state import PortState, PortStatus

if TYPE_CHECKING:
    from src.midi.abc import MidiPortRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class PortConfig(BaseModel):
    """Description of a single MIDI port from config.yaml.

    Parameters
    ----------
    label:
        Human-readable name shown on the display and referenced by tracks.
    match:
        Case-insensitive substring to find the port in the system list.
    serial:
        Optional serial number substring for disambiguation when multiple
        ports match.
    role:
        Port role: ``"melodic"``, ``"drum"``, or ``"clock"``.
    no_automation:
        If ``True``, CC automation is not sent to this port (e.g. controller
        ports like Launch Control XL 3 that should not receive CC from
        generators).  Maps to ``_no_automation: true`` in cc_map config.
    clock:
        If ``True`` (default), MIDI Clock and Start/Continue/Stop are sent to
        this output while the app is the clock master (internal or Link).
    """

    label: str
    match: str
    serial: str | None = None
    role: str = "melodic"
    no_automation: bool = False
    clock: bool = True


class PortsConfig(BaseModel):
    """The ``ports:`` section in config.yaml."""

    outputs: list[PortConfig] = Field(default_factory=list)
    inputs: list[PortConfig] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# PortEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortEvent:
    """A change in a configured port's status.

    Produced by :meth:`PortManager.poll` when a port appears, disappears,
    or changes ambiguity state.
    """

    label: str
    """Human-readable label of the configured port."""

    direction: str
    """``"output"`` or ``"input"``."""

    role: str
    """Port role: ``"melodic"``, ``"drum"``, or ``"clock"``."""

    old_status: PortStatus
    """Status before the change."""

    new_status: PortStatus
    """Status after the change."""

    resolved_name: str | None
    """Resolved system port name after the change, or ``None``."""


# ---------------------------------------------------------------------------
# Internal: per-port runtime record
# ---------------------------------------------------------------------------


@dataclass
class _PortRecord:
    """Mutable runtime state for one configured port."""

    config: PortConfig
    direction: str  # "output" or "input"
    status: PortStatus = PortStatus.DISCONNECTED
    resolved_name: str | None = None
    error: str | None = None

    def to_state(self) -> PortState:
        """Build an immutable PortState snapshot."""
        return PortState(
            label=self.config.label,
            match=self.config.match,
            serial=self.config.serial,
            role=self.config.role,
            direction=self.direction,
            resolved_name=self.resolved_name,
            status=self.status,
            error=self.error,
        )


# ---------------------------------------------------------------------------
# PortManager
# ---------------------------------------------------------------------------


class PortManager:
    """Discovers, identifies, and monitors MIDI ports.

    Does **not** block startup — if a port is missing the session still
    starts, tracks using that port are silent.

    Parameters
    ----------
    config:
        PortsConfig with output and input port descriptions.
    registry:
        MidiPortRegistry used to list available system ports.

    Usage
    -----
    >>> pm = PortManager(ports_config, create_registry())
    >>> pm.start()                        # initial scan, never raises
    >>> events = pm.poll()                # call periodically (e.g. every 2 s)
    >>> for ev in events:
    ...     handle(ev)                    # open/close ports, update display
    >>> pm.stop()
    """

    def __init__(self, config: PortsConfig, registry: MidiPortRegistry) -> None:
        self._config = config
        self._registry = registry

        # Build runtime records for all configured ports
        self._records: dict[str, _PortRecord] = {}
        for pc in config.outputs:
            self._records[pc.label] = _PortRecord(config=pc, direction="output")
        for pc in config.inputs:
            self._records[pc.label] = _PortRecord(config=pc, direction="input")

        # Pending runtime switch (label, match) requested from another
        # thread (e.g. REPL). Applied by the next poll() call, which also
        # produces the PortEvent chain that makes PortRegistry close the old
        # device and open the new one.
        self._pending_switch: tuple[str, str] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> list[PortEvent]:
        """Perform initial scan.  Never raises — missing ports are OK.

        Returns:
            События начального скана (например, ``CONNECTED`` для портов,
            уже подключённых к моменту старта). Вызывающий обязан
            обработать их — иначе порт не откроется до hot-plug переподключения.
        """
        log.info(
            "PortManager starting (%d outputs, %d inputs configured)",
            len(self._config.outputs),
            len(self._config.inputs),
        )
        return self._scan_all()

    def stop(self) -> None:
        """Release resources (no-op — ports are managed by PortRegistry)."""
        log.info("PortManager stopped")

    # ------------------------------------------------------------------
    # Hot-plug polling
    # ------------------------------------------------------------------

    def poll(self) -> list[PortEvent]:
        """Check for port changes and return a list of events.

        Call this periodically from the main loop (e.g. every 2 seconds).
        The method is cheap — it only calls ``list_*_names()`` on the registry.

        Applies a pending runtime switch (see :meth:`request_switch`) first.
        """
        self._apply_pending_switch()
        return self._scan_all()

    def request_switch(self, label: str, match: str) -> None:
        """Schedule a runtime re-pointing of a configured port to another device.

        Only in-memory — ``config.yaml`` on disk is not touched, the change
        reverts on restart. The switch applies on the next :meth:`poll`
        (~2 s in the App main loop): the record's ``match`` is updated
        (``serial`` is cleared — a new device means a new disambiguator) and
        the following scan emits the :class:`PortEvent` chain that makes
        :class:`PortRegistry` close the old device (all_notes_off) and open
        the new one.

        Safe to call from any thread; the assignment of the pending tuple
        is atomic and last request wins.

        Raises
        ------
        ValueError
            Unknown label or empty/blank match.
        """
        if label not in self._records:
            raise ValueError(f"unknown port label: {label!r}")
        match = match.strip()
        if not match:
            raise ValueError("match must not be empty")
        self._pending_switch = (label, match)

    @property
    def pending_switch(self) -> tuple[str, str] | None:
        """Currently scheduled switch ``(label, match)``, if any."""
        return self._pending_switch

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def resolve_output(self, label: str) -> str | None:
        """Resolve *label* to an actual output port name.

        Returns ``None`` if the port is not connected or is ambiguous.
        """
        record = self._records.get(label)
        if record is None or record.direction != "output":
            return None
        if record.status is not PortStatus.CONNECTED:
            return None
        return record.resolved_name

    def clock_input_name(self) -> str | None:
        """Системное имя первого входа с ``role: clock`` (или ``None``)."""
        for pc in self._config.inputs:
            if pc.role == "clock":
                return self.resolve_input(pc.label)
        return None

    def resolve_input(self, label: str) -> str | None:
        """Resolve *label* to an actual input port name.

        Returns ``None`` if the port is not connected or is ambiguous.
        """
        record = self._records.get(label)
        if record is None or record.direction != "input":
            return None
        if record.status is not PortStatus.CONNECTED:
            return None
        return record.resolved_name

    def get_state(self, label: str) -> PortState | None:
        """Return a PortState snapshot for *label*, or None if not configured."""
        record = self._records.get(label)
        if record is None:
            return None
        return record.to_state()

    def all_states(self) -> list[PortState]:
        """Return PortState snapshots for all configured ports."""
        return [r.to_state() for r in self._records.values()]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_pending_switch(self) -> None:
        """Apply a scheduled switch (if any) before scanning."""
        pending = self._pending_switch
        if pending is None:
            return
        self._pending_switch = None
        label, match = pending
        record = self._records.get(label)
        if record is None:
            return
        log.info(
            "Port %s (%s): switch → match %r (serial cleared)",
            label,
            record.direction,
            match,
        )
        record.config.match = match
        record.config.serial = None

    def _scan_all(self) -> list[PortEvent]:
        """Scan all configured ports, update records, and return events."""
        try:
            output_names = self._registry.list_output_names()
            input_names = self._registry.list_input_names()
        except Exception as exc:  # noqa: BLE001
            log.error("PortManager: failed to list MIDI ports: %s", exc)
            return []

        events: list[PortEvent] = []
        for record in self._records.values():
            candidates = output_names if record.direction == "output" else input_names
            event = self._scan_one(record, candidates)
            if event is not None:
                events.append(event)
        return events

    def _scan_one(
        self,
        record: _PortRecord,
        candidates: list[str],
    ) -> PortEvent | None:
        """Scan a single port record against the current candidate list.

        Updates the record in-place and returns a PortEvent if the status
        changed, or ``None`` if nothing changed.
        """
        old_status = record.status
        old_name = record.resolved_name

        status, resolved_name, error = self._identify(record.config, candidates)

        record.status = status
        record.resolved_name = resolved_name
        record.error = error

        if status is old_status and resolved_name == old_name:
            return None

        log.info(
            "Port %s (%s): %s → %s (name=%r)",
            record.config.label,
            record.direction,
            old_status.name,
            status.name,
            resolved_name,
        )
        return PortEvent(
            label=record.config.label,
            direction=record.direction,
            role=record.config.role,
            old_status=old_status,
            new_status=status,
            resolved_name=resolved_name,
        )

    @staticmethod
    def _identify(
        config: PortConfig,
        candidates: list[str],
    ) -> tuple[PortStatus, str | None, str | None]:
        """Identify a port from the candidate list.

        Returns
        -------
        tuple of (status, resolved_name, error)
        """
        match_lower = config.match.lower()
        matches = [name for name in candidates if match_lower in name.lower()]

        if len(matches) == 0:
            return PortStatus.DISCONNECTED, None, None

        if len(matches) == 1:
            return PortStatus.CONNECTED, matches[0], None

        # Multiple candidates — try serial disambiguation
        if config.serial is not None:
            serial_lower = config.serial.lower()
            serial_matches = [name for name in matches if serial_lower in name.lower()]
            if len(serial_matches) == 1:
                return PortStatus.CONNECTED, serial_matches[0], None
            if len(serial_matches) == 0:
                # Serial not found among matches — treat as disconnected
                return PortStatus.DISCONNECTED, None, None

        # Ambiguous — explicit error, never guess
        names_str = ", ".join(repr(n) for n in matches)
        error_msg = (
            f"Multiple ports match {config.match!r}: {names_str}. "
            f"Add a 'serial' field to disambiguate."
        )
        return PortStatus.AMBIGUOUS, None, error_msg
