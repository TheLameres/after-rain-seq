"""Tests for src/devices/lcxl3/lcxl3_device.py — LCXL3 device plugin."""

from unittest.mock import MagicMock, patch

from src.devices.display_state import DisplayState
from src.devices.lcxl3.config import LCXL3Config
from src.devices.lcxl3.lcxl3_device import LCXL3Device
from src.devices.lcxl3.mapping import (
    ALL_ENCODER_ABS_CCS,
    ARRANGEMENT_3LINE,
    ARRANGEMENT_CTRL,
    BTN_GLOBAL_MUTE,
    BTN_GLOBAL_SOLO,
    BTN_MUTE_SELECT_CCS,
    BTN_NAME_SHIFT,
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
    CH_LED_IN,
    ENCODER_ROW1_REL,
    ENCODER_ROW2_REL,
    ENCODER_ROW3_REL,
    FADER_CCS,
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
from src.midi import MidiMessage

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_device_with_mock_ports(port_name: str = "Test DAW Port"):
    """Create an LCXL3Device with mocked ports and a connected state."""
    device = LCXL3Device()

    mock_in = MagicMock()
    mock_out_port = MagicMock()
    # iter_pending returns empty by default (no incoming messages)
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch(
            "src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out_port
        ),
    ):
        device.connect(
            LCXL3Config(midi_in_port_name=port_name, midi_out_port_name=port_name)
        )

    return device, mock_in, mock_out_port


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def test_name() -> None:
    device = LCXL3Device()
    assert device.name == "Launch Control XL 3"


def test_supports_display() -> None:
    device = LCXL3Device()
    assert device.supports_display is True


def test_pad_note_range() -> None:
    device = LCXL3Device()
    assert device.pad_note_range == (-1, -1)


def test_is_connected_before_connect() -> None:
    device = LCXL3Device()
    assert device.is_connected is False


# ---------------------------------------------------------------------------
# Connect: SysEx messages sent
# ---------------------------------------------------------------------------


def test_connect_sends_daw_mode_enter() -> None:
    """connect() must send SYSEX_DAW_MODE_ENTER."""
    device = LCXL3Device()
    mock_in = MagicMock()
    mock_out = MagicMock()
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch("src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out),
    ):
        device.connect(LCXL3Config(midi_in_port_name="Test", midi_out_port_name="Test"))

    # First call to send should be the DAW mode enter SysEx
    first_msg = mock_out.send.call_args_list[0][0][0]
    assert first_msg.is_sysex
    assert tuple(first_msg.data) == SYSEX_DAW_MODE_ENTER


def test_connect_enables_relative_encoders() -> None:
    """connect() must send relative encoder enable for all 3 rows."""
    device = LCXL3Device()
    mock_in = MagicMock()
    mock_out = MagicMock()
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch("src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out),
    ):
        device.connect(LCXL3Config(midi_in_port_name="Test", midi_out_port_name="Test"))

    sent_messages = [call[0][0] for call in mock_out.send.call_args_list]
    cc_messages = [m for m in sent_messages if m.is_cc]

    # Find the 3 relative-enable messages
    rel_ccs = {
        m.control
        for m in cc_messages
        if m.channel == CH_FEATURE_SEND and m.value == 0x7F
    }
    assert FEAT_ROW1_RELATIVE in rel_ccs, f"Row 1 relative not enabled; got {rel_ccs}"
    assert FEAT_ROW2_RELATIVE in rel_ccs, f"Row 2 relative not enabled; got {rel_ccs}"
    assert FEAT_ROW3_RELATIVE in rel_ccs, f"Row 3 relative not enabled; got {rel_ccs}"


def test_connect_configures_stationary_display() -> None:
    """connect() must configure the stationary display (target 53, arrangement 2)."""
    device = LCXL3Device()
    mock_in = MagicMock()
    mock_out = MagicMock()
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch("src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out),
    ):
        device.connect(LCXL3Config(midi_in_port_name="Test", midi_out_port_name="Test"))

    sysex_messages = [
        call[0][0] for call in mock_out.send.call_args_list if call[0][0].is_sysex
    ]
    # Look for display config SysEx with target=53 and arrangement=2
    expected_cfg_data = (
        *SYSEX_DISPLAY_CFG_PREFIX,
        TARGET_STATIONARY,
        ARRANGEMENT_3LINE,
    )
    found = any(tuple(m.data) == expected_cfg_data for m in sysex_messages)
    assert (
        found
    ), f"Stationary display config SysEx not found. Got: {[tuple(m.data) for m in sysex_messages]}"


def test_connect_configures_per_encoder_displays() -> None:
    """connect() must configure temp displays for all 24 encoder absolute CCs."""
    device = LCXL3Device()
    mock_in = MagicMock()
    mock_out = MagicMock()
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch("src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out),
    ):
        device.connect(LCXL3Config(midi_in_port_name="Test", midi_out_port_name="Test"))

    sysex_messages = [
        tuple(call[0][0].data)
        for call in mock_out.send.call_args_list
        if call[0][0].is_sysex
    ]

    # Each encoder absolute CC (13-36) should have a config SysEx with ARRANGEMENT_CTRL
    for abs_cc in ALL_ENCODER_ABS_CCS:
        expected = (*SYSEX_DISPLAY_CFG_PREFIX, abs_cc, ARRANGEMENT_CTRL)
        assert (
            expected in sysex_messages
        ), f"Per-encoder display config not found for CC {abs_cc}"


def test_connect_sets_is_connected() -> None:
    device = LCXL3Device()
    mock_in = MagicMock()
    mock_out = MagicMock()
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch("src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out),
    ):
        device.connect(LCXL3Config(midi_in_port_name="Test", midi_out_port_name="Test"))

    assert device.is_connected is True


# ---------------------------------------------------------------------------
# Encoder parsing
# ---------------------------------------------------------------------------


def _send_msg_to_device(device: LCXL3Device, msg: MidiMessage) -> None:
    """Call the device's internal _parse_message directly for testing."""
    device._parse_message(msg)


def test_encoder_row1_increment_positive() -> None:
    """Relative encoder value > 64 should produce positive increment."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: received.append((name, inc)),
    )

    # Enc_A1 = ENCODER_ROW1_REL[0] = CC 77 on CH_ANALOG_OUT
    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW1_REL[0], value=70)
    _send_msg_to_device(device, msg)

    assert len(received) == 1
    name, inc = received[0]
    assert name == "Enc_A1"
    assert inc == 70 - 64  # = 6


def test_encoder_row1_increment_negative() -> None:
    """Relative encoder value < 64 should produce negative increment."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: received.append((name, inc)),
    )

    # Value 60: 60 - 64 = -4
    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW1_REL[0], value=60)
    _send_msg_to_device(device, msg)

    assert received[0][1] == -4


def test_encoder_row2_parsed() -> None:
    """Row 2 encoder parses to Enc_B* names."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: received.append((name, inc)),
    )

    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW2_REL[3], value=65)
    _send_msg_to_device(device, msg)

    name, _ = received[0]
    assert name == "Enc_B4"


def test_encoder_row3_parsed() -> None:
    """Row 3 encoder parses to Enc_C* names."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: received.append((name, inc)),
    )

    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW3_REL[7], value=66)
    _send_msg_to_device(device, msg)

    name, _ = received[0]
    assert name == "Enc_C8"


def test_encoder_display_value_updates() -> None:
    """Encoder movements should accumulate in display_values dict."""
    device = LCXL3Device()
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: None,
    )

    # Start at 64, add +6 → 70
    msg1 = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW1_REL[0], value=70)
    _send_msg_to_device(device, msg1)
    assert device._display_values.get("Enc_A1") == 70

    # Add another +4 → 74
    msg2 = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW1_REL[0], value=68)
    _send_msg_to_device(device, msg2)
    assert device._display_values.get("Enc_A1") == 74


def test_encoder_display_value_clamps_upper() -> None:
    """Display value should not exceed 127."""
    device = LCXL3Device()
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: None,
    )

    # Value 127 → increment = 63 → 64 + 63 = 127 (clamped)
    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW1_REL[0], value=127)
    _send_msg_to_device(device, msg)
    assert device._display_values.get("Enc_A1") == 127


def test_encoder_display_value_clamps_lower() -> None:
    """Display value should not go below 0."""
    device = LCXL3Device()
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: None,
    )

    # Value 0 → increment = -64 → 64 - 64 = 0 (clamped)
    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW1_REL[0], value=0)
    _send_msg_to_device(device, msg)
    assert device._display_values.get("Enc_A1") == 0


def test_encoder_updates_last_active() -> None:
    """Encoder movement updates _last_active_label and _last_active_value."""
    device = LCXL3Device()
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=ENCODER_ROW1_REL[0], value=70)
    _send_msg_to_device(device, msg)

    assert device._last_active_label == "Enc_A1"
    assert device._last_active_value == 70


# ---------------------------------------------------------------------------
# Fader parsing
# ---------------------------------------------------------------------------


def test_fader_parsed_absolute() -> None:
    """Fader CC on CH_ANALOG_OUT should call on_fader with absolute value."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: None,
        on_fader=lambda name, val: received.append((name, val)),
    )

    # Fader 1 = CC 5
    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=FADER_CCS[0], value=80)
    _send_msg_to_device(device, msg)

    assert len(received) == 1
    assert received[0] == ("Fader1", 80)


def test_fader_all_indices_parsed() -> None:
    """All 8 fader CCs should dispatch to correct fader names."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: None,
        on_fader=lambda name, val: received.append((name, val)),
    )

    for i, cc in enumerate(FADER_CCS):
        received.clear()
        msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=cc, value=64)
        _send_msg_to_device(device, msg)
        assert len(received) == 1
        assert received[0][0] == f"Fader{i + 1}"


def test_fader_updates_last_active() -> None:
    """Fader movement updates _last_active_label and _last_active_value."""
    device = LCXL3Device()
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: None,
        on_fader=lambda name, val: None,
    )

    msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=FADER_CCS[2], value=100)
    _send_msg_to_device(device, msg)

    assert device._last_active_label == "Fader3"
    assert device._last_active_value == 100


def test_fader_no_accumulation() -> None:
    """Fader uses absolute values — no accumulation like encoders."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda n, p: None,
        on_encoder=lambda name, inc: None,
        on_fader=lambda name, val: received.append((name, val)),
    )

    cc = FADER_CCS[0]
    for val in [30, 80, 10]:
        received.clear()
        msg = MidiMessage.cc(channel=CH_ANALOG_OUT, control=cc, value=val)
        _send_msg_to_device(device, msg)
        assert received[0][1] == val  # exact absolute value, no accumulation


# ---------------------------------------------------------------------------
# Button parsing
# ---------------------------------------------------------------------------


def test_button_solo_arm_pressed() -> None:
    """Solo/Arm row CC on ch0 with value >= 64 → pressed=True."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_SOLO_ARM_CCS[0], value=127)
    _send_msg_to_device(device, msg)

    assert received[0] == ("Select 1", True)


def test_button_solo_arm_released() -> None:
    """Solo/Arm row CC with value 0 → pressed=False."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_SOLO_ARM_CCS[4], value=0)
    _send_msg_to_device(device, msg)

    assert received[0] == ("Select 5", False)


def test_button_mute_select_bank_names() -> None:
    """Mute/Select row CCs map to 'Bank 1'-'Bank 8' names."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    for i, cc in enumerate(BTN_MUTE_SELECT_CCS):
        received.clear()
        msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=cc, value=127)
        _send_msg_to_device(device, msg)
        assert received[0][0] == f"Bank {i + 1}"


def test_button_global_mute() -> None:
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_GLOBAL_MUTE, value=127)
    _send_msg_to_device(device, msg)

    assert received[0][0] == "Mute"
    assert received[0][1] is True


def test_button_global_solo() -> None:
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_GLOBAL_SOLO, value=64)
    _send_msg_to_device(device, msg)

    assert received[0][0] == "Solo"
    assert received[0][1] is True


def test_button_play() -> None:
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_PLAY, value=127)
    _send_msg_to_device(device, msg)

    assert received[0][0] == "Play"


def test_button_record() -> None:
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_RECORD, value=127)
    _send_msg_to_device(device, msg)

    assert received[0][0] == "Record"


def test_button_page_up() -> None:
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_PAGE_UP, value=127)
    _send_msg_to_device(device, msg)

    assert received[0][0] == "Page Up"


def test_button_page_down() -> None:
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_PAGE_DOWN, value=127)
    _send_msg_to_device(device, msg)

    assert received[0][0] == "Page Down"


def test_button_track_left() -> None:
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_TRACK_LEFT, value=127)
    _send_msg_to_device(device, msg)

    assert received[0][0] == "Track Left"


def test_button_track_right() -> None:
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_TRACK_RIGHT, value=127)
    _send_msg_to_device(device, msg)

    assert received[0][0] == "Track Right"


def test_button_pressed_threshold_64() -> None:
    """Value 64 should be treated as pressed (>= 64 = pressed)."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_PLAY, value=64)
    _send_msg_to_device(device, msg)
    assert received[0][1] is True


def test_button_not_pressed_below_64() -> None:
    """Value 63 should be treated as released (< 64 = released)."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_BUTTON_OUT, control=BTN_PLAY, value=63)
    _send_msg_to_device(device, msg)
    assert received[0][1] is False


def test_button_shift_pressed() -> None:
    """Shift button sends CC 63 on CH_FEATURE_SEND (ch6), value 127 = pressed."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_FEATURE_SEND, control=BTN_SHIFT, value=127)
    _send_msg_to_device(device, msg)

    assert len(received) == 1
    assert received[0] == (BTN_NAME_SHIFT, True)


def test_button_shift_released() -> None:
    """Shift button release: value 0 = released."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_FEATURE_SEND, control=BTN_SHIFT, value=0)
    _send_msg_to_device(device, msg)

    assert len(received) == 1
    assert received[0] == (BTN_NAME_SHIFT, False)


def test_button_shift_threshold_64() -> None:
    """Shift value 64 should be treated as pressed (>= 64 = pressed)."""
    device = LCXL3Device()
    received: list = []
    device.register_callbacks(
        on_pad=lambda n, v: None,
        on_button=lambda name, pressed: received.append((name, pressed)),
        on_encoder=lambda name, inc: None,
    )

    msg = MidiMessage.cc(channel=CH_FEATURE_SEND, control=BTN_SHIFT, value=64)
    _send_msg_to_device(device, msg)
    assert received[0][1] is True


# ---------------------------------------------------------------------------
# render_display
# ---------------------------------------------------------------------------


def _make_display_state(**kwargs) -> DisplayState:
    """Helper to create a DisplayState with defaults."""
    defaults = {
        "device_connected": False,
        "sync_bpm": None,
        "sync_link_peers": 0,
        "sync_link_active": False,
        "sync_clock_source": "off",
    }
    defaults.update(kwargs)
    return DisplayState(**defaults)


def test_render_display_sends_sysex_on_state_change() -> None:
    """render_display should send SysEx when state differs from last state."""
    device = LCXL3Device()
    mock_out = MagicMock()
    device._out = mock_out

    # Initial state is ("----", "", ""), so a BPM value is different
    device.render_display(_make_display_state(sync_bpm=120.0))
    assert mock_out.send.call_count > 0


def test_render_display_no_duplicate_sends() -> None:
    """render_display should NOT send SysEx if state is unchanged."""
    device = LCXL3Device()
    mock_out = MagicMock()
    device._out = mock_out

    device.render_display(_make_display_state(sync_bpm=120.0))
    count_after_first = mock_out.send.call_count

    # Call again with same state → no additional sends
    device.render_display(_make_display_state(sync_bpm=120.0))
    assert mock_out.send.call_count == count_after_first


def test_render_display_bpm_goes_to_field0() -> None:
    """BPM string should be sent as field 0 of the stationary display."""
    device = LCXL3Device()
    mock_out = MagicMock()
    device._out = mock_out

    device.render_display(_make_display_state(sync_bpm=118.5))

    # Find SysEx for field 0
    sent_sysex = [
        tuple(call[0][0].data)
        for call in mock_out.send.call_args_list
        if call[0][0].is_sysex
    ]
    field0_prefix = (*SYSEX_DISPLAY_TEXT_PREFIX, TARGET_STATIONARY, 0)
    found = any(data[: len(field0_prefix)] == field0_prefix for data in sent_sysex)
    assert found, f"Field 0 SysEx not found. Sent: {sent_sysex}"


def test_render_display_no_bpm_shows_dashes() -> None:
    """No BPM should display '----'."""
    device = LCXL3Device()
    mock_out = MagicMock()
    device._out = mock_out

    # Force a previous state that differs
    device._last_display_state = ("120.0", "", "")
    device.render_display(_make_display_state(sync_bpm=None))

    sent_sysex = [
        tuple(call[0][0].data)
        for call in mock_out.send.call_args_list
        if call[0][0].is_sysex
    ]
    # Field 0 should have "----" encoded as ASCII
    field0_prefix = (*SYSEX_DISPLAY_TEXT_PREFIX, TARGET_STATIONARY, 0)
    dashes_chars = tuple(ord(c) for c in "----")
    expected = field0_prefix + dashes_chars
    assert expected in sent_sysex


def test_render_display_label_and_value_shown() -> None:
    """Last active label and value should appear in fields 1 and 2."""
    device = LCXL3Device()
    mock_out = MagicMock()
    device._out = mock_out
    device._last_active_label = "DlyT"
    device._last_active_value = 42

    device.render_display(_make_display_state(sync_bpm=120.0))

    sent_sysex = [
        tuple(call[0][0].data)
        for call in mock_out.send.call_args_list
        if call[0][0].is_sysex
    ]
    # Field 1 should have "DlyT"
    field1_prefix = (*SYSEX_DISPLAY_TEXT_PREFIX, TARGET_STATIONARY, 1)
    label_chars = tuple(ord(c) for c in "DlyT")
    assert (field1_prefix + label_chars) in sent_sysex

    # Field 2 should have "42"
    field2_prefix = (*SYSEX_DISPLAY_TEXT_PREFIX, TARGET_STATIONARY, 2)
    value_chars = tuple(ord(c) for c in "42")
    assert (field2_prefix + value_chars) in sent_sysex


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------


def test_disconnect_sends_daw_exit_sysex() -> None:
    """disconnect() must send SYSEX_DAW_MODE_EXIT."""
    device = LCXL3Device()
    mock_in = MagicMock()
    mock_out = MagicMock()
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch("src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out),
    ):
        device.connect(LCXL3Config(midi_in_port_name="Test", midi_out_port_name="Test"))

    mock_out.reset_mock()
    device.disconnect()

    sysex_calls = [
        tuple(call[0][0].data)
        for call in mock_out.send.call_args_list
        if call[0][0].is_sysex
    ]
    assert SYSEX_DAW_MODE_EXIT in sysex_calls, f"DAW exit not found. Got: {sysex_calls}"


def test_disconnect_turns_off_leds() -> None:
    """disconnect() must send LED_OFF to all button CCs."""
    device = LCXL3Device()
    mock_in = MagicMock()
    mock_out = MagicMock()
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch("src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out),
    ):
        device.connect(LCXL3Config(midi_in_port_name="Test", midi_out_port_name="Test"))

    mock_out.reset_mock()
    device.disconnect()

    cc_msgs = {
        call[0][0].control: call[0][0].value
        for call in mock_out.send.call_args_list
        if call[0][0].type == "control_change"
    }
    # All Mute/Select bank button CCs should be turned off
    for cc in BTN_MUTE_SELECT_CCS:
        assert cc in cc_msgs, f"CC {cc} LED not turned off on disconnect"
        assert cc_msgs[cc] == LED_OFF


def test_disconnect_sets_is_connected_false() -> None:
    device = LCXL3Device()
    mock_in = MagicMock()
    mock_out = MagicMock()
    mock_in.iter_pending.return_value = iter([])

    with (
        patch("src.devices.lcxl3.lcxl3_device.mido.open_input", return_value=mock_in),
        patch("src.devices.lcxl3.lcxl3_device.create_out_port", return_value=mock_out),
    ):
        device.connect(LCXL3Config(midi_in_port_name="Test", midi_out_port_name="Test"))

    device.disconnect()
    assert device.is_connected is False


# ---------------------------------------------------------------------------
# send_midi — LED feedback
# ---------------------------------------------------------------------------


def test_send_midi_forwards_known_button_cc() -> None:
    """LED feedback for known button CCs should be forwarded to LCXL3 output."""
    device = LCXL3Device()
    mock_out = MagicMock()
    device._out = mock_out

    cc = BTN_MUTE_SELECT_CCS[0]  # 45
    msg = MidiMessage.cc(channel=CH_LED_IN, control=cc, value=60)
    device.send_midi(msg)

    mock_out.send.assert_called_once()
    sent = mock_out.send.call_args[0][0]
    assert sent.control == cc
    assert sent.value == 60


def test_send_midi_ignores_note_on() -> None:
    """note_on messages should be silently ignored (no pads on LCXL3)."""
    device = LCXL3Device()
    mock_out = MagicMock()
    device._out = mock_out

    msg = MidiMessage.note_on(channel=0, note=60, velocity=100)
    device.send_midi(msg)

    mock_out.send.assert_not_called()


def test_send_midi_ignores_unknown_cc() -> None:
    """CC not in the known LED map should be silently ignored."""
    device = LCXL3Device()
    mock_out = MagicMock()
    device._out = mock_out

    # CC 99 is not a mapped LED CC
    msg = MidiMessage.cc(channel=CH_LED_IN, control=99, value=60)
    device.send_midi(msg)

    mock_out.send.assert_not_called()

    mock_out.send.assert_not_called()
