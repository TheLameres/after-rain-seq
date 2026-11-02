"""Config loading for App subsystems.

Loads config.yaml, resolves active devices, converts channels.
No dependencies on M8 or translation modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import AppConfig
from src.config import UiConfig
from src.config import load_config as _load_config
from src.devices.definition import DeviceConfig
from src.session.drum.drum_config import DrumConfig
from src.session.mutation.mutation_config import MutationConfig
from src.sync.cc_map import CCMapConfig, default_cc_map_config
from src.sync.config import SyncConfig
from src.sync.ports import PortsConfig


@dataclass(frozen=True)
class LoadedConfig:
    """Resolved, typed config ready for use by App subsystems."""

    display_fps: int
    active_device_types: list[str]
    device_configs: dict[str, DeviceConfig]  # per-device config instances
    sync_config: SyncConfig = field(default_factory=SyncConfig)
    ports_config: PortsConfig = field(default_factory=PortsConfig)
    cc_map_config: CCMapConfig = field(default_factory=default_cc_map_config)
    drum_config: DrumConfig = field(default_factory=DrumConfig)
    mutation_config: MutationConfig = field(default_factory=MutationConfig)
    ui_config: UiConfig = field(default_factory=UiConfig)


def load_app_config(config_path: str, simulate: bool = False) -> LoadedConfig:
    """Load config.yaml, resolve active devices."""
    cfg: AppConfig = _load_config(config_path)

    from src.devices.registry import get_all_definitions

    active_types = [
        defn.type_key
        for defn in get_all_definitions()
        if (dc := cfg.get_device_config(defn.type_key)) is not None and dc.enabled
    ]

    device_configs: dict[str, DeviceConfig] = {}
    for type_key in active_types:
        dc = cfg.get_device_config(type_key)
        if dc is not None:
            device_configs[type_key] = dc

    from src.devices.push2.config import Push2Config as _Push2Config

    push2_cfg = device_configs.get("push2")
    display_fps = push2_cfg.display_fps if isinstance(push2_cfg, _Push2Config) else 15

    return LoadedConfig(
        display_fps=display_fps,
        active_device_types=active_types,
        device_configs=device_configs,
        sync_config=cfg.sync,
        ports_config=cfg.ports,
        cc_map_config=cfg.cc_map,
        drum_config=cfg.drum,
        mutation_config=cfg.mutation,
        ui_config=cfg.ui,
    )
