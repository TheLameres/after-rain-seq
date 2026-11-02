"""Novation Launch Control XL 3 device plugin implementing ControllerDevice.

Uses the MIDI abstraction layer (src/midi/) to communicate with the LCXL3
in DAW mode.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from src.devices.base import ControllerDevice
from src.devices.definition import DeviceConfig
from src.devices.display_state import DisplayState
from src.devices.lcxl3.config import LCXL3Config
from src.devices.lcxl3.mapping import (
    ALL_ENCODER_ABS_CCS,
    ARRANGEMENT_3LINE,
    ARRANGEMENT_CTRL,
    BTN_GLOBAL_MUTE,
    BTN_GLOBAL_SOLO,
    BTN_MUTE_SELECT_CCS,
    BTN_NAME_MUTE,
    BTN_NAME_PAGE_DOWN,
    BTN_NAME_PAGE_UP,
    BTN_NAME_PLAY,
    BTN_NAME_RECORD,
    BTN_NAME_SHIFT,
    BTN_NAME_SOLO,
    BTN_NAME_TRACK_LEFT,
    BTN_NAME_TRACK_RIGHT,
    BTN_NAMES_BANK,
    BTN_NAMES_SELECT,
    BTN_PAGE_DOWN,
    BTN_PAGE_UP,
    BTN_PLAY,
    BTN_RECORD,
    BTN_SHIFT,
    BTN_SOLO_ARM_CCS,
    BTN_TRACK_LEFT,
    BTN_TRACK_RIGHT,
    CH_ANALOG_OUT,
    CH_BUTTON_OUT,
    CH_FEATURE_SEND,
    ENCODER_NAMES,
    ENCODER_PIVOT,
    ENCODER_ROW1_REL,
    ENCODER_ROW2_REL,
    ENCODER_ROW3_REL,
    FADER_CCS,
    FADER_NAMES,
    FEAT_ROW1_RELATIVE,
    FEAT_ROW2_RELATIVE,
    FEAT_ROW3_RELATIVE,
    LED_OFF,
    SYSEX_DAW_MODE_ENTER,
    SYSEX_DAW_MODE_EXIT,
    SYSEX_DISPLAY_CFG_PREFIX,
    SYSEX_DISPLAY_TEXT_PREFIX,
    TARGET_STATIONARY,
)
from src.midi import MidiMessage, MidiOutPort, create_out_port

log = logging.getLogger(__name__)

# For input, LCXL3 uses mido's iter_pending() polling pattern which doesn't
# map cleanly to the callback-based MidiInPort.  The input side keeps using
# mido directly; only the output side uses the abstraction.
import contextlib

import mido

# Relative CC -> (encoder name index into ENCODER_NAMES)
_REL_CC_TO_ENC_IDX: dict[int, int] = {
    **{cc: i for i, cc in enumerate(ENCODER_ROW1_REL)},  # 77-84 -> 0-7
    **{cc: i + 8 for i, cc in enumerate(ENCODER_ROW2_REL)},  # 85-92 -> 8-15
    **{cc: i + 16 for i, cc in enumerate(ENCODER_ROW3_REL)},  # 93-100 -> 16-23
}

# Fader CC -> fader name index
_FADER_CC_TO_IDX: dict[int, int] = {cc: i for i, cc in enumerate(FADER_CCS)}

# Button CC (ch0) -> button name
_BTN_CC_TO_NAME: dict[int, str] = {
    **{cc: BTN_NAMES_SELECT[i] for i, cc in enumerate(BTN_SOLO_ARM_CCS)},
    **{cc: BTN_NAMES_BANK[i] for i, cc in enumerate(BTN_MUTE_SELECT_CCS)},
    BTN_GLOBAL_SOLO: BTN_NAME_SOLO,
    BTN_GLOBAL_MUTE: BTN_NAME_MUTE,
    BTN_PLAY: BTN_NAME_PLAY,
    BTN_RECORD: BTN_NAME_RECORD,
    BTN_PAGE_UP: BTN_NAME_PAGE_UP,
    BTN_PAGE_DOWN: BTN_NAME_PAGE_DOWN,
    BTN_TRACK_RIGHT: BTN_NAME_TRACK_RIGHT,
    BTN_TRACK_LEFT: BTN_NAME_TRACK_LEFT,
}

# LED-able CCs: Solo/Arm row (T1-T8 feedback) + Mute/Select row + global buttons + Play/Rec
_LED_CCS: frozenset[int] = (
    frozenset(BTN_SOLO_ARM_CCS)
    | frozenset(BTN_MUTE_SELECT_CCS)
    | {BTN_GLOBAL_SOLO, BTN_GLOBAL_MUTE, BTN_PLAY, BTN_RECORD}
)


class LCXL3Device(ControllerDevice):
    """Novation Launch Control XL 3 in DAW mode."""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Launch Control XL 3"

    @property
    def supports_display(self) -> bool:
        return True  # LCXL3 has built-in text screen

    @property
    def pad_note_range(self) -> tuple[int, int]:
        return (-1, -1)  # no pad grid

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._out: MidiOutPort | None = None
        self._in: mido.ports.BaseInput | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._connected: bool = False

        # Callbacks set by register_callbacks()
        self._on_pad: Callable[[int, int], None] | None = None
        self._on_button: Callable[[str, bool], None] | None = None
        self._on_encoder: Callable[[str, int], None] | None = None
        self._on_fader: Callable[[str, int], None] | None = None

        # Display tracking (display-only values)
        self._display_values: dict[str, int] = {}  # name -> running absolute value
        self._last_active_label: str = ""
        self._last_active_value: int = 0
        self._last_display_state: tuple[str, str, str] = ("", "", "")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self, config: DeviceConfig) -> None:  # type: ignore[override]
        """Open LCXL3 DAW ports and initialise DAW mode."""
        assert isinstance(
            config, LCXL3Config
        ), f"Expected LCXL3Config, got {type(config)}"
        # Separate in/out port names (computer perspective):
        #   in_port:  computer reads from device (device DAW output, e.g. "LCXL3 1 DAW Out")
        #   out_port: computer writes to device  (device DAW input,  e.g. "LCXL3 1 DAW In")
        in_port_name = config.midi_in_port_name
        out_port_name = config.midi_out_port_name

        # Open MIDI ports
        self._out = create_out_port()
        self._out.open(out_port_name)
        self._in = mido.open_input(in_port_name)

        # Enter DAW mode
        self._out.send(MidiMessage.sysex(SYSEX_DAW_MODE_ENTER))

        # Enable relative encoder output on all 3 rows (ch6 = CH_FEATURE_SEND)
        for cc in (FEAT_ROW1_RELATIVE, FEAT_ROW2_RELATIVE, FEAT_ROW3_RELATIVE):
            self._out.send(
                MidiMessage.cc(
                    channel=CH_FEATURE_SEND,  # 0-indexed ch7
                    control=cc,
                    value=127,
                )
            )

        # Configure stationary display: 3 fields, no auto-trigger
        self._out.send(
            MidiMessage.sysex(
                (*SYSEX_DISPLAY_CFG_PREFIX, TARGET_STATIONARY, ARRANGEMENT_3LINE)
            )
        )
        # Set initial text
        self._send_text(TARGET_STATIONARY, 0, "----")
        self._send_text(TARGET_STATIONARY, 1, "")
        self._send_text(TARGET_STATIONARY, 2, "")
        self._last_display_state = ("----", "", "")

        # Pre-configure per-encoder temp displays (targets 13-36)
        for i, abs_cc in enumerate(ALL_ENCODER_ABS_CCS):
            self._out.send(
                MidiMessage.sysex((*SYSEX_DISPLAY_CFG_PREFIX, abs_cc, ARRANGEMENT_CTRL))
            )
            self._send_text(abs_cc, 0, ENCODER_NAMES[i][:12])

        # Pre-configure per-fader temp displays (targets 5-12)
        for i, fader_cc in enumerate(FADER_CCS):
            self._out.send(
                MidiMessage.sysex(
                    (*SYSEX_DISPLAY_CFG_PREFIX, fader_cc, ARRANGEMENT_CTRL)
                )
            )
            self._send_text(fader_cc, 0, FADER_NAMES[i][:12])

        # Start background MIDI reader thread
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._reader_thread, daemon=True, name="lcxl3-midi-reader"
        )
        self._thread.start()

        self._connected = True
        log.info("LCXL3 connected (in=%r, out=%r)", in_port_name, out_port_name)

    def disconnect(self) -> None:
        """Exit DAW mode and close ports."""
        if not self._connected:
            return

        # Turn off all button LEDs
        if self._out is not None:
            for cc in [*list(BTN_MUTE_SELECT_CCS), BTN_GLOBAL_SOLO, BTN_GLOBAL_MUTE]:
                with contextlib.suppress(Exception):
                    self._out.send(MidiMessage.cc(channel=0, control=cc, value=LED_OFF))

            # Clear stationary display
            try:
                self._send_text(TARGET_STATIONARY, 0, "")
                self._send_text(TARGET_STATIONARY, 1, "")
                self._send_text(TARGET_STATIONARY, 2, "")
            except Exception:
                pass

            # Exit DAW mode
            with contextlib.suppress(Exception):
                self._out.send(MidiMessage.sysex(SYSEX_DAW_MODE_EXIT))

        # Stop reader thread
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        # Close ports
        if self._in is not None:
            self._in.close()
            self._in = None
        if self._out is not None:
            self._out.close()
            self._out = None

        self._connected = False
        log.info("LCXL3 disconnected")

    # ------------------------------------------------------------------
    # MIDI output
    # ------------------------------------------------------------------

    def send_midi(self, msg: MidiMessage) -> None:
        """Forward LED feedback to LCXL3.

        Only forwards control_change on ch0 for LED-able CCs.
        Ignores note_on (LCXL3 has no pad grid).
        """
        if self._out is None:
            return
        if msg.is_cc and msg.channel == 0 and msg.control in _LED_CCS:
            self._out.send(msg)
            log.debug("LCXL3 <- LED cc=%d val=%d", msg.control, msg.value)
        # note_on ignored

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
        self._on_pad = on_pad
        self._on_button = on_button
        self._on_encoder = on_encoder
        self._on_fader = on_fader

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def render_display(self, state: DisplayState) -> None:
        """Update the stationary 3-line display. Only sends SysEx on change."""
        if self._out is None:
            return

        label = self._last_active_label
        value = self._last_active_value

        bpm = state.sync_bpm
        line1 = f"{bpm:.1f}" if bpm is not None else "----"
        line2 = label[:12] if label else ""
        line3 = str(value) if label else ""

        if (line1, line2, line3) == self._last_display_state:
            return

        self._send_text(TARGET_STATIONARY, 0, line1)
        self._send_text(TARGET_STATIONARY, 1, line2)
        self._send_text(TARGET_STATIONARY, 2, line3)
        self._last_display_state = (line1, line2, line3)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _send_text(self, target: int, field: int, text: str) -> None:
        """Send a display text field SysEx message."""
        if self._out is None:
            return
        data = (
            *SYSEX_DISPLAY_TEXT_PREFIX,
            target,
            field,
            *(ord(c) for c in text if 0x20 <= ord(c) <= 0x7E),
        )
        self._out.send(MidiMessage.sysex(data))

    def _reader_thread(self) -> None:
        """Background thread: read MIDI from LCXL3 and dispatch callbacks."""
        while not self._stop_event.is_set():
            if self._in is None:
                break
            try:
                for msg in self._in.iter_pending():
                    self._parse_message(MidiMessage.from_mido(msg))
            except Exception as exc:
                log.debug("LCXL3 reader error: %s", exc)
            self._stop_event.wait(timeout=0.001)

    def _parse_message(self, msg: MidiMessage) -> None:
        """Dispatch an incoming MIDI message to the appropriate callback."""
        if not msg.is_cc:
            return

        assert msg.channel is not None
        assert msg.control is not None
        assert msg.value is not None

        ch = int(msg.channel)
        cc = int(msg.control)
        val = int(msg.value)

        if ch == CH_ANALOG_OUT:
            # Encoder relative CCs (77-100)
            enc_idx = _REL_CC_TO_ENC_IDX.get(cc)
            if enc_idx is not None:
                name = ENCODER_NAMES[enc_idx]
                increment = val - ENCODER_PIVOT  # positive = CW, negative = CCW
                # Update display-only running value (clamped to 0-127)
                prev = self._display_values.get(name, 64)
                new_val = max(0, min(127, prev + increment))
                self._display_values[name] = new_val
                self._last_active_label = name
                self._last_active_value = new_val
                if self._on_encoder is not None:
                    self._on_encoder(name, increment)
                return

            # Fader absolute CCs (5-12)
            fader_idx = _FADER_CC_TO_IDX.get(cc)
            if fader_idx is not None:
                name = FADER_NAMES[fader_idx]
                self._display_values[name] = val
                self._last_active_label = name
                self._last_active_value = val
                if self._on_fader is not None:
                    self._on_fader(name, val)
                return

        elif ch == CH_BUTTON_OUT:
            btn_name = _BTN_CC_TO_NAME.get(cc)
            if btn_name is not None:
                pressed = val >= 64
                if self._on_button is not None:
                    self._on_button(btn_name, pressed)

        elif ch == CH_FEATURE_SEND and cc == BTN_SHIFT:
            # Shift button sends on channel 6 (CH_FEATURE_SEND), CC 63
            pressed = val >= 64
            if self._on_button is not None:
                self._on_button(BTN_NAME_SHIFT, pressed)
