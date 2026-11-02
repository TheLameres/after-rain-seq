"""Push 2 DeviceDefinition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.devices.definition import (
    BoolField,
    DeviceDefinition,
    MidiPortConfig,
    SliderField,
)
from src.devices.push2.config import Push2Config

if TYPE_CHECKING:
    from src.devices.push2.push2_device import Push2Device


def _factory() -> Push2Device:
    from src.devices.push2.push2_device import (
        Push2Device,
    )  # lazy: тяжёлые USB-зависимости

    return Push2Device()


PUSH2_DEFINITION = DeviceDefinition(
    type_key="push2",
    display_name="Ableton Push 2",
    config_class=Push2Config,
    device_factory=_factory,
    midi_ports=MidiPortConfig(style="none"),
    extra_fields=[
        BoolField(
            key="use_user_midi_port", label="Use User Port  (uncheck = Live Port)"
        ),
        BoolField(key="display_enabled", label="Enable display"),
        SliderField(key="display_fps", label="Display FPS", min_val=1, max_val=60),
    ],
)
