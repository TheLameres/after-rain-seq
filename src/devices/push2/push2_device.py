"""Push 2 device plugin implementing ControllerDevice.

Custom implementation using src.midi for MIDI I/O and Push2UsbDisplay
for the display — no push2-python dependency.

Lifecycle
---------
1. Construct (no hardware interaction yet).
2. Call ``connect(config)`` to open MIDI ports and USB display.
3. Call ``register_callbacks(...)`` to wire up input events.
4. Call ``render_display(state)`` in the render loop.
5. Call ``disconnect()`` on shutdown.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from src.devices.base import ControllerDevice
from src.devices.definition import DeviceConfig
from src.devices.display_state import DisplayState
from src.devices.push2.config import Push2Config
from src.devices.push2.display import PushDisplay
from src.devices.push2.mapping import (
    PUSH2_BUTTON_NAME_TO_CC,
    PUSH2_CC_TO_BUTTON_NAME,
    PUSH2_ENCODER_CC_TO_NAME,
    sysex_display_brightness,
)
from src.devices.push2.push2_display import Push2UsbDisplay
from src.midi import (
    MidiInPort,
    MidiMessage,
    MidiOutPort,
    create_in_port,
    create_out_port,
    create_registry,
)

log = logging.getLogger(__name__)

# Касания энкодеров (спека «Encoders»: touch = note-on, nn0–nn10).
# Используем только глобальные: nn10 — Tempo (BPM во flash), nn9 — Swing.
_ENCODER_TOUCH_NOTES: dict[int, str] = {
    10: "Tempo Encoder",
    9: "Swing Encoder",
}


class Push2Device(ControllerDevice):
    """Ableton Push 2 device plugin — custom driver without push2-python."""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Ableton Push 2"

    @property
    def supports_display(self) -> bool:
        return True  # Push 2 has a display; actual rendering is guarded in render_display()

    @property
    def pad_note_range(self) -> tuple[int, int]:
        return (36, 99)

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._midi_in: MidiInPort | None = None
        self._midi_out: MidiOutPort | None = None
        self._usb_display: Push2UsbDisplay | None = None
        self._display: PushDisplay | None = None
        self._is_connected: bool = False
        self._display_enabled: bool = True
        self._simulate: bool = False

        # Input callbacks — stored so _on_midi_in can forward events
        self._on_pad: Callable[[int, int], None] | None = None
        self._on_button: Callable[[str, bool], None] | None = None
        self._on_encoder: Callable[[str, int], None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self, config: DeviceConfig) -> None:  # type: ignore[override]
        """Open hardware connections.

        Parameters
        ----------
        config:
            Push2Config instance (call apply_runtime_opts() before passing).
        """
        assert isinstance(
            config, Push2Config
        ), f"Expected Push2Config, got {type(config)}"
        use_user_port = config.use_user_midi_port
        self._display_enabled = config.display_enabled
        self._simulate = config.simulate
        display_fps = config.display_fps

        if not self._simulate:
            # MIDI port discovery
            registry = create_registry()
            needle = "Push 2 User" if use_user_port else "Push 2 Live"

            in_name = registry.find_input(needle)
            out_name = registry.find_output(needle)
            if in_name is None or out_name is None:
                raise RuntimeError(
                    f"Push 2 MIDI ports not found for '{needle}' "
                    f"(in={in_name!r}, out={out_name!r})"
                )

            self._midi_in = create_in_port()
            self._midi_in.open(in_name)
            self._midi_in.set_callback(self._on_midi_in)

            self._midi_out = create_out_port()
            self._midi_out.open(out_name)

            # Подсветка дисплея: без sysex 0x08 кадры принимаются,
            # но панель остаётся чёрной (spec §"Display Backlight").
            self._midi_out.send(
                MidiMessage.sysex(sysex_display_brightness(config.brightness))
            )

            # USB display (optional — MIDI input continues if unavailable)
            if self._display_enabled:
                usb_display = Push2UsbDisplay()
                try:
                    usb_display.open()
                    self._usb_display = usb_display
                except Exception as exc:
                    log.warning("Push 2 display USB init failed — MIDI only: %s", exc)
        else:
            log.info("Push 2 simulate mode — MIDI ports and USB display skipped")

        # PushDisplay is always created when display is enabled (USB or simulate)
        if self._display_enabled:
            self._display = PushDisplay(fps=display_fps)

        self._is_connected = True
        log.info(
            "Push 2 connected (simulate=%s, user_port=%s, display=%s)",
            self._simulate,
            use_user_port,
            self._usb_display is not None,
        )

    def disconnect(self) -> None:
        """Clean shutdown: turn off all LEDs, blank display, close ports."""
        if self._midi_out is not None:
            # Turn off all pad LEDs (notes 36-99, MIDI ch 0 = static)
            try:
                for note in range(36, 100):
                    self._midi_out.send(
                        MidiMessage.note_off(channel=0, note=note, velocity=0)
                    )
            except Exception as exc:
                log.debug("Push 2 pad LED cleanup: %s", exc)

            # Turn off all button LEDs
            try:
                for cc in PUSH2_BUTTON_NAME_TO_CC.values():
                    self._midi_out.send(MidiMessage.cc(channel=0, control=cc, value=0))
            except Exception as exc:
                log.debug("Push 2 button LED cleanup: %s", exc)

        # Blank the display before closing USB
        if self._usb_display is not None:
            try:
                self._usb_display.clear()
            except Exception as exc:
                log.debug("Push 2 display clear: %s", exc)
            self._usb_display.close()
            self._usb_display = None

        if self._midi_in is not None:
            self._midi_in.clear_callback()
            self._midi_in.close()
            self._midi_in = None

        if self._midi_out is not None:
            self._midi_out.close()
            self._midi_out = None

        self._display = None
        self._is_connected = False
        log.info("Push 2 disconnected")

    # ------------------------------------------------------------------
    # MIDI output
    # ------------------------------------------------------------------

    def send_midi(self, msg: MidiMessage) -> None:
        """Send a MIDI message to Push 2 (e.g. for LED control)."""
        if self._midi_out is None:
            log.debug("Push2Device.send_midi: not connected — dropped %s", msg)
            return
        self._midi_out.send(msg)
        log.debug("Push2Device → Push2  %s", msg)

    # ------------------------------------------------------------------
    # Input callbacks
    # ------------------------------------------------------------------

    def register_callbacks(
        self,
        on_pad: Callable[[int, int], None],
        on_button: Callable[[str, bool], None],
        on_encoder: Callable[[str, int], None],
        on_fader: Callable[[str, int], None] | None = None,
    ) -> None:
        """Register input event callbacks.

        ``on_fader`` is accepted for interface compatibility but ignored —
        Push 2 has no motorised faders.
        """
        self._on_pad = on_pad
        self._on_button = on_button
        self._on_encoder = on_encoder

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def render_display(self, state: DisplayState) -> None:
        """Render application state to the Push 2 display.

        D2: при наличии ``state.screen_view`` — экраны навигации;
        иначе — legacy interim-экран (BPM/LINK/клок).
        """
        if self._display is None:
            return
        if state.screen_view is not None:
            self._display.update_screen(state.screen_view)
        else:
            self._display.update_state(
                push2_connected=state.device_connected,
                sync_bpm=state.sync_bpm,
                sync_link_peers=state.sync_link_peers,
                sync_link_active=state.sync_link_active,
                sync_clock_source=state.sync_clock_source,
            )
        try:
            if self._usb_display is not None:
                self._display.render_usb(self._usb_display)
            else:
                self._display.render_frame_only()
        except Exception as exc:
            log.debug("Push2Device display render error: %s", exc)

    def set_button_leds(self, states: dict[str, int]) -> None:
        """Подсветка кнопок: имя кнопки → индекс цвета палитры (0 = off).

        Спека «LEDs»: LED кнопок управляются тем же CC, что и нажатия
        (channel 0 — без анимации); белые кнопки трактуют значение как
        яркость, RGB — как индекс палитры (122 white, 126 green, 127 red).
        App шлёт дифф (только изменившиеся); LCXL3-путь не трогаем.
        """
        if self._midi_out is None:
            return
        for name, value in states.items():
            cc = PUSH2_BUTTON_NAME_TO_CC.get(name)
            if cc is None:
                continue
            self._midi_out.send(MidiMessage.cc(channel=0, control=cc, value=value))

    def set_display_frame_callback(self, cb: Callable | None) -> None:
        """Wire an on_frame callback into PushDisplay (e.g. for screen emulator)."""
        if self._display is not None:
            self._display.set_on_frame(cb)

    # ------------------------------------------------------------------
    # MIDI input dispatcher
    # ------------------------------------------------------------------

    def _on_midi_in(self, msg: MidiMessage) -> None:
        """Dispatch incoming MIDI message from Push 2.

        Runs on the mido callback thread — must be fast; no blocking I/O.
        """
        # Поля data-сообщений в union-типе MidiMessage — Optional:
        # заполнены только поля, относящиеся к type (см. MidiMessage docstring).
        if msg.type == "note_on" and msg.note is not None and msg.velocity is not None:
            note = int(msg.note)
            vel = int(msg.velocity)
            if 36 <= note <= 99:
                # Pad press or release (velocity 0 on note_on = release)
                if self._on_pad:
                    self._on_pad(note, vel)
            elif (
                note in _ENCODER_TOUCH_NOTES and vel > 0 and self._on_button is not None
            ):
                # Касание энкодера (спека «Encoders»: note-on touch, nn9/nn10).
                # Идём через on_button: касание = press-эквивалент, контроллер
                # показывает BPM/свинг во flash-строке (статус-бара нет, D2-5).
                self._on_button(_ENCODER_TOUCH_NOTES[note], True)

        elif msg.type == "note_off" and msg.note is not None:
            note = int(msg.note)
            if 36 <= note <= 99:
                if self._on_pad:
                    self._on_pad(note, 0)
            elif note in _ENCODER_TOUCH_NOTES and self._on_button is not None:
                self._on_button(_ENCODER_TOUCH_NOTES[note], False)

        elif (
            msg.type == "control_change"
            and msg.control is not None
            and msg.value is not None
        ):
            cc = int(msg.control)
            val = int(msg.value)

            if cc in PUSH2_ENCODER_CC_TO_NAME:
                # Relative encoder (two's complement):
                # val 1-64 = positive steps, 65-127 = negative steps
                increment = val if val <= 64 else val - 128
                if self._on_encoder:
                    self._on_encoder(PUSH2_ENCODER_CC_TO_NAME[cc], increment)

            elif cc in PUSH2_CC_TO_BUTTON_NAME:
                # Button: value 127 = press, 0 = release
                if self._on_button:
                    self._on_button(PUSH2_CC_TO_BUTTON_NAME[cc], val == 127)
