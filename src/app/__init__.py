"""App package — orchestrator modules for after-rain-seq.

Exports: App, DeviceSlot, LoadedConfig, load_app_config, DisplayRenderer, DeviceManager.
"""

from src.app.application import App
from src.app.config import LoadedConfig, load_app_config
from src.app.device_manager import DeviceManager
from src.app.display import DisplayRenderer
from src.app.slot import DeviceSlot

__all__ = [
    "App",
    "DeviceManager",
    "DeviceSlot",
    "DisplayRenderer",
    "LoadedConfig",
    "load_app_config",
]
