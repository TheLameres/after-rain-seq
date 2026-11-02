"""LCXL3 device configuration schema."""

from __future__ import annotations

from src.devices.definition import DeviceConfig


class LCXL3Config(DeviceConfig):
    midi_in_port_name: str = "Launch Control XL 3 DAW Out"
    midi_out_port_name: str = "Launch Control XL 3 DAW In"
