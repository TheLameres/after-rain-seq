"""Device definition framework.

DeviceConfig     — базовый Pydantic-класс конфига устройства.
DeviceDefinition — полное описание устройства: schema, factory, capabilities, UI,
                   runtime encoder/mapping данные для app._create_slot.
FieldDescriptor  — declarative UI field descriptors.
MidiPortConfig   — описывает MIDI-порты устройства для generic UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.devices.base import ControllerDevice


class DeviceConfig(BaseModel):
    """Базовый класс конфига для всех устройств.

    enabled рендерится UI автоматически — не добавлять в extra_fields.
    simulate — runtime-флаг (CLI --simulate ИЛИ YAML), в UI не показывается.
    """

    enabled: bool = False

    def apply_runtime_opts(self, simulate: bool) -> "DeviceConfig":
        """Apply runtime overrides before passing config to device.connect().

        Base implementation is a no-op. Subclasses override to merge in
        CLI flags (e.g. --simulate) that may override config.yaml values.
        """
        return self


# ---------------------------------------------------------------------------
# Field descriptors
# ---------------------------------------------------------------------------


@dataclass
class BoolField:
    """Рендерится как QCheckBox."""

    key: str
    label: str


@dataclass
class SliderField:
    """Рендерится как QSlider + QLabel."""

    key: str
    label: str
    min_val: int
    max_val: int


# Добавление нового типа поля требует:
#   1. Нового @dataclass здесь
#   2. Обновления type alias FieldDescriptor
#   3. Нового isinstance-branch в config_dialog._build_extra_field
type FieldDescriptor = BoolField | SliderField


@dataclass
class MidiPortConfig:
    """Описывает MIDI-порты устройства для generic UI.

    style="none"   — USB-устройство (Push 2), порты в UI не показываются.
    style="in_out" — два отдельных порта: in + out (LCXL3).
    """

    style: Literal["none", "in_out"] = "none"
    in_port_key: str = "midi_in_port_name"
    out_port_key: str = "midi_out_port_name"
    in_label: str = "MIDI in port  (device → computer)"
    out_label: str = "MIDI out port (computer → device)"


# ---------------------------------------------------------------------------
# DeviceDefinition
# ---------------------------------------------------------------------------


@dataclass
class DeviceDefinition:
    """Полное описание устройства — единственный источник правды.

    Поля UI-группы (midi_ports, extra_fields) используются в config_dialog
    для generic построения панели устройства.

    Добавить новое устройство:
        1. Создать src/devices/<name>/  (config.py, definition.py, device_class.py)
        2. Добавить две строки в registry.py (import + register)
    """

    # --- Идентификация ---
    type_key: str  # "push2" | "lcxl3" | …
    display_name: str  # "Ableton Push 2" | …

    # --- Config и factory ---
    config_class: type[DeviceConfig]
    device_factory: Callable[
        [], ControllerDevice
    ]  # lazy — вызывается только при коннекте

    # --- UI capabilities ---
    midi_ports: MidiPortConfig = field(default_factory=MidiPortConfig)
    extra_fields: list[FieldDescriptor] = field(default_factory=list)
