"""Push 2 device configuration schema."""

from __future__ import annotations

from pydantic import Field

from src.devices.definition import DeviceConfig


class Push2Config(DeviceConfig):
    use_user_midi_port: bool = False
    # simulate: runtime-флаг (CLI --simulate переопределяет это значение).
    # Оставлен в конфиге для ручной отладки через config.yaml.
    simulate: bool = False
    display_enabled: bool = True
    display_fps: int = Field(default=25, ge=1, le=60)
    # Яркость подсветки дисплея (sysex 0x08, 0–255).
    # При питании по USB реально ≈ min(brightness, 100).
    brightness: int = Field(default=100, ge=0, le=255)

    def apply_runtime_opts(self, simulate: bool) -> Push2Config:
        return self.model_copy(update={"simulate": simulate or self.simulate})
