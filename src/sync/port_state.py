"""PortStatus enum and PortState frozen dataclass for display rendering."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class PortStatus(Enum):
    """Connection status of a configured MIDI port."""

    CONNECTED = auto()
    """Port found, identified unambiguously, and open."""

    DISCONNECTED = auto()
    """Port not found in the system.  Tracks using this port are silent."""

    AMBIGUOUS = auto()
    """Multiple ports match the ``match`` substring and no ``serial`` resolves
    the ambiguity.  This is an explicit error — the system never guesses."""

    ERROR = auto()
    """An unexpected error occurred (e.g. failed to open the port)."""


@dataclass(frozen=True)
class PortState:
    """Immutable snapshot of a single configured port's status.

    Consumed by the display renderer every frame — no locks needed because
    PortManager replaces the entire instance atomically via assignment.
    """

    label: str
    """Human-readable label from config (e.g. ``"Синт A"``, ``"Drum Machine"``)."""

    match: str
    """Substring used to find the port in the system list."""

    serial: str | None
    """Optional serial number for disambiguation."""

    role: str
    """Port role: ``"melodic"``, ``"drum"``, or ``"clock"``."""

    direction: str
    """``"output"`` or ``"input"``."""

    resolved_name: str | None
    """Actual system port name, or ``None`` if not resolved."""

    status: PortStatus
    """Current connection status."""

    error: str | None
    """Human-readable error message, or ``None`` if no error."""

    @property
    def is_connected(self) -> bool:
        """True when the port is connected and usable."""
        return self.status is PortStatus.CONNECTED

    @property
    def status_display(self) -> str:
        """Short string for display rendering."""
        match self.status:
            case PortStatus.CONNECTED:
                return "ok"
            case PortStatus.DISCONNECTED:
                return "no port"
            case PortStatus.AMBIGUOUS:
                return "ambiguous"
            case PortStatus.ERROR:
                return "error"
