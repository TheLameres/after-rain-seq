"""sync — clock source management, tick dispatch, and transport delivery."""

from src.sync.capture_output import CaptureOutput
from src.sync.clock_manager import ClockManager
from src.sync.clock_source import ClockManagerConfig, ClockSource
from src.sync.clock_state import ClockState
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.tick_proxy import TickProxy
from src.sync.transport import Transport, TransportMode
from src.sync.transport_event import EventKind, TransportEvent

__all__ = [
    "CaptureOutput",
    "ClockManager",
    "ClockManagerConfig",
    "ClockSource",
    "ClockState",
    "EventKind",
    "SwingApplier",
    "SwingConfig",
    "TickProxy",
    "Transport",
    "TransportEvent",
    "TransportMode",
]
