"""Application configuration: Pydantic schemas, YAML load/save, defaults.

Importing this module triggers ``src.devices.registry`` registration so that
``AppConfig`` model validation can resolve device configs through the registry.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# Importing registry registers all device definitions as a side effect.
import src.devices.registry  # noqa: F401
from src.devices.definition import DeviceConfig
from src.devices.registry import get_definition
from src.session.drum.drum_config import DrumConfig
from src.session.mutation.mutation_config import MutationConfig
from src.sync.cc_map import CCMapConfig, default_cc_map_config
from src.sync.config import SyncConfig
from src.sync.ports import PortsConfig

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class LoggingConfig(BaseModel):
    """Spring Boot-style logging levels.

    Keys are logger names (``"root"`` for the root logger), values are
    level names: TRACE, DEBUG, INFO, WARN, ERROR, OFF.
    """

    level: dict[str, str] = Field(default_factory=lambda: {"root": "INFO"})


# ---------------------------------------------------------------------------
# UI (D2) — макро-оси и настройки экранов Push 2
# ---------------------------------------------------------------------------


class UiConfig(BaseModel):
    """Конфигурация UI Push 2 (план D2 §3.7).

    Валидация имён параметров CC-осей — против :data:`DEFAULT_CC_PARAMS`
    (валидация на этапе загрузки, до построения CCMap).
    """

    macro_axes: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "tone": ["filter"],
            "space": ["reverb", "delay"],
            "depth": ["resonance"],
        }
    )
    flash_seconds: float = 3.0

    @field_validator("macro_axes")
    @classmethod
    def _validate_macro_axes(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        from src.app.ui.macro_axes import MacroAxes

        MacroAxes(value)  # ValueError с человекочитаемым текстом
        return value


# ---------------------------------------------------------------------------
# Main application config
# ---------------------------------------------------------------------------


class AppConfig(BaseModel):
    """Root configuration object loaded from config.yaml."""

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    ports: PortsConfig = Field(default_factory=PortsConfig)
    cc_map: CCMapConfig = Field(default_factory=default_cc_map_config)
    drum: DrumConfig = Field(default_factory=DrumConfig)
    mutation: MutationConfig = Field(default_factory=MutationConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    devices: dict[str, DeviceConfig] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Device config access
    # ------------------------------------------------------------------

    def get_device_config(self, type_key: str) -> DeviceConfig | None:
        """Return the config for *type_key*, or None if not configured."""
        return self.devices.get(type_key)

    def set_device_config(self, type_key: str, cfg: DeviceConfig) -> None:
        """Store *cfg* under *type_key*."""
        self.devices[type_key] = cfg

    # ------------------------------------------------------------------
    # Validation — deserialize device dicts through registry schemas
    # ------------------------------------------------------------------

    @model_validator(mode="before")
    @classmethod
    def _deserialize_devices(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        devices = data.get("devices")
        if not isinstance(devices, dict):
            return data

        resolved: dict[str, DeviceConfig] = {}
        for type_key, raw in devices.items():
            if raw is None:
                raw = {}
            if isinstance(raw, DeviceConfig):
                resolved[type_key] = raw
                continue
            if not isinstance(raw, dict):
                raise ValueError(
                    f"devices.{type_key}: expected mapping, got {type(raw).__name__}"
                )
            defn = get_definition(type_key)
            resolved[type_key] = defn.config_class.model_validate(raw)

        data = dict(data)
        data["devices"] = resolved
        return data


# ---------------------------------------------------------------------------
# Default config template
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_YAML: str = """\
# after-rain-seq configuration — created automatically on first run.
# Edit this file to customize your setup.

logging:
  level:
    root: INFO

sync:
  enabled: true
  clock_source: "internal"
  midi_clock_device: null
  bpm: 120.0
  swing_amount: 0.0

ports:
  outputs: []
  inputs: []

cc_map:
  default:
    filter: 74
    resonance: 71
    reverb: 91
    delay: 93
    delay_feedback: 94
    mod_wheel: 1
    volume: 7
    pan: 10
  ports: {}

drum:
  preview_on_select: true
  preview_velocity: 100
  mutate_min_seconds: 8.0
  mutate_max_seconds: 16.0

mutation:
  enabled: true
  mutate_min_seconds: 8.0
  mutate_max_seconds: 16.0
  default_mutate: 0.5
  drift_step_gate: 0.05
  drift_step_density: 0.1
  drift_step_register: 1.0

ui:
  macro_axes:
    tone: [filter]
    space: [reverb, delay]
    depth: [resonance]
  flash_seconds: 3.0

devices:
  push2:
    enabled: true
    use_user_midi_port: false
    simulate: false
    display_enabled: true
    display_fps: 25

  lcxl3:
    enabled: false
    midi_in_port_name: "LCXL3 1 DAW Out"
    midi_out_port_name: "LCXL3 1 DAW In"
"""


# ---------------------------------------------------------------------------
# Load / save helpers
# ---------------------------------------------------------------------------


def ensure_default_config(path: str | Path) -> None:
    """Write the default config to *path* if the file does not exist."""
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")


def load_config(path: str | Path) -> AppConfig:
    """Load and validate config from *path*.

    Exits with ``SystemExit`` on any error (missing file, invalid YAML,
    validation failure).
    """
    p = Path(path)
    if not p.exists():
        print(f"Config file not found: {p}", file=sys.stderr)
        sys.exit(1)

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"Invalid YAML in {p}: {exc}", file=sys.stderr)
        sys.exit(1)

    if raw is None:
        raw = {}

    try:
        return AppConfig.model_validate(raw)
    except Exception as exc:
        print(f"Config validation error in {p}:\n{exc}", file=sys.stderr)
        sys.exit(1)


def save_config(cfg: AppConfig, path: str | Path) -> None:
    """Serialize *cfg* to YAML and write to *path*."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode="json")
    p.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8"
    )
