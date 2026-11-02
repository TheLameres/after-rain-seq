"""Abstract base class for controller devices.

All hardware-specific logic (USB/MIDI I/O, LED control, display) is
encapsulated behind this interface so new devices can be added as plugins
without touching the application logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from src.devices.definition import DeviceConfig
from src.devices.display_state import DisplayState
from src.midi import MidiMessage


class ControllerDevice(ABC):
    """Abstract controller device interface.

    Implementors (e.g. Push2Device) handle hardware-specific init/shutdown,
    MIDI I/O, callback registration, and display rendering.
    """

    # ------------------------------------------------------------------
    # Properties (must be implemented as class or instance attributes)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable device name, e.g. 'Ableton Push 2'."""

    @property
    @abstractmethod
    def supports_display(self) -> bool:
        """True if the device has a pixel display."""

    @property
    @abstractmethod
    def pad_note_range(self) -> tuple[int, int]:
        """Inclusive (min, max) MIDI note numbers for the pad grid."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True after a successful connect(); False after disconnect()."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, config: DeviceConfig) -> None:
        """Open hardware connections and prepare the device.

        Parameters
        ----------
        config:
            Device-specific configuration object (DeviceConfig subclass).
            Call ``config.apply_runtime_opts(...)`` before passing here to
            merge CLI and global display settings.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Cleanly shut down all connections and release resources."""

    # ------------------------------------------------------------------
    # MIDI output
    # ------------------------------------------------------------------

    @abstractmethod
    def send_midi(self, msg: MidiMessage) -> None:
        """Send a MIDI message to the device (e.g. for LED control)."""

    # ------------------------------------------------------------------
    # Input callbacks
    # ------------------------------------------------------------------

    @abstractmethod
    def register_callbacks(
        self,
        on_pad: Callable[[int, int], None],
        on_button: Callable[[str, bool], None],
        on_encoder: Callable[[str, int], None],
        on_fader: Callable[[str, int], None] | None = None,
    ) -> None:
        """Register input event callbacks.

        Parameters
        ----------
        on_pad:
            Called with ``(note: int, velocity: int)`` on pad press/release.
            Velocity 0 means released.
        on_button:
            Called with ``(name: str, pressed: bool)`` on button events.
            *name* uses the driver's button name convention.
        on_encoder:
            Called with ``(name: str, increment: int)`` on encoder rotation.
            *increment* is a signed relative value.
        on_fader:
            Called with ``(name: str, value: int)`` on fader movement.
            *value* is an absolute value 0-127. Optional; None if device has no
            faders or fader support is not needed.
        """

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    @abstractmethod
    def render_display(self, state: DisplayState) -> None:
        """Render the current application state to the device display.

        No-op if ``supports_display`` is False or display is disabled.

        Parameters
        ----------
        state:
            DisplayState dataclass with typed fields:
              - ``device_connected``: bool
              - ``sync_bpm`` / ``sync_link_peers`` / ``sync_link_active``
              - ``sync_clock_source``: str (``"internal"`` / ``"midi"`` /
                ``"link"`` / ``"off"``)
        """
