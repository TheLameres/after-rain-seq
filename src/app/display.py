"""DisplayRenderer — display render loop.

Imports DisplayState + DeviceSlot (app/slot.py).
Does NOT import DeviceManager or any M8 modules.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.app.slot import DeviceSlot
from src.devices.display_state import DisplayState, ScreenView

if TYPE_CHECKING:
    from src.sync.clock_state import ClockState

log = logging.getLogger(__name__)


class DisplayRenderer:
    """Display render loop."""

    def __init__(self, fps: int) -> None:
        self._fps = fps

    @property
    def frame_interval(self) -> float:
        return 1.0 / self._fps

    def build_display_state(
        self,
        slot: DeviceSlot,
        all_slots: list[DeviceSlot],
        sync_state: ClockState | None = None,
        screen_view: ScreenView | None = None,
    ) -> DisplayState:
        """Build a DisplayState for the given slot."""
        return DisplayState(
            device_connected=any(s.device.is_connected for s in all_slots),
            sync_bpm=sync_state.bpm if sync_state else None,
            sync_link_peers=sync_state.link_peers if sync_state else 0,
            sync_link_active=sync_state.link_active if sync_state else False,
            sync_clock_source=sync_state.clock_source if sync_state else "off",
            screen_view=screen_view,
        )

    def render_frame(
        self,
        slots: list[DeviceSlot],
        sync_state: ClockState | None = None,
        screen_view: ScreenView | None = None,
    ) -> None:
        """Render all connected devices at configured fps."""
        for slot in slots:
            if slot.device.is_connected and slot.device.supports_display:
                try:
                    state = self.build_display_state(
                        slot,
                        slots,
                        sync_state=sync_state,
                        screen_view=screen_view,
                    )
                    slot.device.render_display(state)
                except Exception as exc:
                    log.warning("Display render error (%s): %s", slot.device.name, exc)
