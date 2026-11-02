"""DeviceManager — device lifecycle: connect, disconnect, input callback dispatch.

Imports DeviceSlot (app/slot.py) + LoadedConfig (app/config.py).
Does NOT import DisplayState or DisplayRenderer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from src.app.config import LoadedConfig
from src.app.slot import DeviceSlot

log = logging.getLogger(__name__)


class DeviceManager:
    """Device lifecycle: connect, disconnect, input callback dispatch.

    Input events (pad/button/encoder/fader) are forwarded to callbacks
    set by the App via `on_pad`, `on_button`, `on_encoder`, `on_fader` attributes.
    """

    def __init__(
        self,
        config: LoadedConfig,
        simulate: bool,
        on_device_connected: Callable[[bool], None],
        on_devices_changed: Callable[[list[str]], None],
    ) -> None:
        self._config = config
        self._simulate = simulate
        self._on_device_connected = on_device_connected
        self._on_devices_changed = on_devices_changed
        self._slots: list[DeviceSlot] = []

        # Input callbacks — set by App after construction
        self.on_pad: Callable[[DeviceSlot, int, int], None] = self._default_pad
        self.on_button: Callable[[DeviceSlot, str, bool], None] = self._default_button
        self.on_encoder: Callable[[DeviceSlot, str, int], None] = self._default_encoder
        self.on_fader: Callable[[DeviceSlot, str, int], None] = self._default_fader

    @property
    def slots(self) -> list[DeviceSlot]:
        return self._slots

    def connect_all(self) -> list[DeviceSlot]:
        """Connect all active devices and return slots."""
        for device_type in self._config.active_device_types:
            slot = self._create_slot(device_type)
            if slot is None:
                continue
            self._slots.append(slot)
            self._register_slot_callbacks(slot)

        if self._slots:
            self._on_device_connected(True)
            self._on_devices_changed([s.device.name for s in self._slots])

        return self._slots

    def disconnect_all(self) -> None:
        """Disconnect all devices and clear slots."""
        for slot in self._slots:
            slot.device.disconnect()
        self._slots.clear()
        self._on_device_connected(False)
        self._on_devices_changed([])

    # Default no-op input handlers (App overrides these)
    def _default_pad(self, slot: DeviceSlot, pad_n: int, velocity: int) -> None:
        log.debug("pad %s %d vel=%d", slot.device.name, pad_n, velocity)

    def _register_slot_callbacks(self, slot: DeviceSlot) -> None:
        """Bind DeviceManager-level handlers to one slot's device.

        Замыкания вместо лямбд с дефолтными аргументами — mypy не может
        вывести типы таких лямбд.
        """

        def on_pad(n: int, v: int) -> None:
            self.on_pad(slot, n, v)

        def on_button(nm: str, pressed: bool) -> None:
            self.on_button(slot, nm, pressed)

        def on_encoder(nm: str, increment: int) -> None:
            self.on_encoder(slot, nm, increment)

        def on_fader(nm: str, value: int) -> None:
            self.on_fader(slot, nm, value)

        slot.device.register_callbacks(
            on_pad=on_pad,
            on_button=on_button,
            on_encoder=on_encoder,
            on_fader=on_fader,
        )

    def _default_button(
        self, slot: DeviceSlot, button_name: str, pressed: bool
    ) -> None:
        log.debug("button %s %s %s", slot.device.name, button_name, pressed)

    def _default_encoder(
        self, slot: DeviceSlot, encoder_name: str, increment: int
    ) -> None:
        log.debug("encoder %s %s inc=%d", slot.device.name, encoder_name, increment)

    def _default_fader(self, slot: DeviceSlot, fader_name: str, value: int) -> None:
        log.debug("fader %s %s val=%d", slot.device.name, fader_name, value)

    def _create_slot(self, device_type: str) -> DeviceSlot | None:
        """Connect one device and return its DeviceSlot."""
        from src.devices.registry import get_definition

        defn = get_definition(device_type)
        dev_cfg = self._config.device_configs.get(device_type)
        if dev_cfg is None:
            return None

        runtime_cfg = dev_cfg.apply_runtime_opts(simulate=self._simulate)

        try:
            device = defn.device_factory()
            device.connect(runtime_cfg)
            log.info("Device %r connected", device_type)
        except Exception as exc:
            log.warning("Device %r not available: %s", device_type, exc)
            return None

        return DeviceSlot(device=device)
