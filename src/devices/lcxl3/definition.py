"""LCXL3 DeviceDefinition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.devices.definition import DeviceDefinition, MidiPortConfig
from src.devices.lcxl3.config import LCXL3Config

if TYPE_CHECKING:
    from src.devices.lcxl3.lcxl3_device import LCXL3Device


def _factory() -> LCXL3Device:
    from src.devices.lcxl3.lcxl3_device import LCXL3Device  # lazy: mido

    return LCXL3Device()


LCXL3_DEFINITION = DeviceDefinition(
    type_key="lcxl3",
    display_name="Launch Control XL 3",
    config_class=LCXL3Config,
    device_factory=_factory,
    midi_ports=MidiPortConfig(
        style="in_out",
        in_port_key="midi_in_port_name",
        out_port_key="midi_out_port_name",
        in_label="MIDI in port  (device DAW Out → computer)",
        out_label="MIDI out port (computer → device DAW In)",
    ),
    extra_fields=[],
)
