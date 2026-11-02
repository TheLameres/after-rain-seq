"""DeviceSlot — thin wrapper bundling a connected device.

No dependencies on M8 or translation modules.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.devices.base import ControllerDevice


@dataclass
class DeviceSlot:
    """A connected device plus any per-device application state."""

    device: ControllerDevice
