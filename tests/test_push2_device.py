"""Tests for src/devices/push2/push2_device.py — Push 2 device plugin."""

from unittest.mock import MagicMock, patch

import pytest

from src.devices.push2.config import Push2Config
from src.devices.push2.mapping import PUSH2_BUTTON_NAME_TO_CC
from src.devices.push2.push2_device import Push2Device
from src.midi import MidiMessage
from src.midi.abc import MidiInPort, MidiOutPort, MidiPortRegistry

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_device_with_mock_ports(
    display_enabled: bool = False,
) -> tuple[Push2Device, MagicMock, MagicMock]:
    """Create a Push2Device with mocked MIDI ports (no hardware needed).

    Returns (device, mock_in_port, mock_out_port).
    """
    device = Push2Device()

    mock_in = MagicMock(spec=MidiInPort)
    mock_out = MagicMock(spec=MidiOutPort)
    mock_registry = MagicMock(spec=MidiPortRegistry)
    mock_registry.find_input.return_value = "Ableton Push 2 Live Port"
    mock_registry.find_output.return_value = "Ableton Push 2 Live Port"

    with (
        patch("src.devices.push2.push2_device.create_in_port", return_value=mock_in),
        patch("src.devices.push2.push2_device.create_out_port", return_value=mock_out),
        patch(
            "src.devices.push2.push2_device.create_registry", return_value=mock_registry
        ),
        patch("src.devices.push2.push2_device.Push2UsbDisplay") as mock_usb_cls,
    ):
        if display_enabled:
            mock_usb_cls.return_value = MagicMock()
        else:
            # Simulate USB not found so display path is skipped
            mock_usb_cls.return_value.open.side_effect = RuntimeError("no USB")
        device.connect(Push2Config(display_enabled=display_enabled))

    # Replace send_midi with a mock so tests can inspect MidiMessage objects
    device.send_midi = MagicMock()

    return device, mock_in, mock_out


# ---------------------------------------------------------------------------
# MIDI input dispatcher
# ---------------------------------------------------------------------------


def _fire_midi(device: Push2Device, msg: MidiMessage) -> None:
    """Invoke the device's internal MIDI callback directly (simulates hardware input)."""
    device._on_midi_in(msg)


def test_midi_in_pad_press_fires_on_pad() -> None:
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=cb, on_button=MagicMock(), on_encoder=MagicMock())

    _fire_midi(device, MidiMessage.note_on(channel=0, note=36, velocity=100))

    cb.assert_called_once_with(36, 100)


def test_midi_in_pad_release_via_note_off() -> None:
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=cb, on_button=MagicMock(), on_encoder=MagicMock())

    _fire_midi(device, MidiMessage.note_off(channel=0, note=99, velocity=0))

    cb.assert_called_once_with(99, 0)


def test_midi_in_pad_note_on_vel0_is_release() -> None:
    """note_on with velocity 0 is treated as a release (standard MIDI convention)."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=cb, on_button=MagicMock(), on_encoder=MagicMock())

    _fire_midi(device, MidiMessage.note_on(channel=0, note=44, velocity=0))

    cb.assert_called_once_with(44, 0)


def test_midi_in_encoder_positive_increment() -> None:
    """CC 71 val=1 → Track1 Encoder increment +1 (спека: track 1 encoder)."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=MagicMock(), on_button=MagicMock(), on_encoder=cb)

    _fire_midi(device, MidiMessage.cc(channel=0, control=71, value=1))

    cb.assert_called_once_with("Track1 Encoder", 1)


def test_midi_in_encoder_negative_increment() -> None:
    """CC 71 val=127 → Track1 Encoder increment -1 (two's complement)."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=MagicMock(), on_button=MagicMock(), on_encoder=cb)

    _fire_midi(device, MidiMessage.cc(channel=0, control=71, value=127))

    cb.assert_called_once_with("Track1 Encoder", -1)


def test_midi_in_encoder_max_positive() -> None:
    """CC 71 val=64 → increment +64 (boundary: last positive step value)."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=MagicMock(), on_button=MagicMock(), on_encoder=cb)

    _fire_midi(device, MidiMessage.cc(channel=0, control=71, value=64))

    cb.assert_called_once_with("Track1 Encoder", 64)


def test_midi_in_encoder_min_negative() -> None:
    """CC 71 val=65 → increment -63 (boundary: first negative step value)."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=MagicMock(), on_button=MagicMock(), on_encoder=cb)

    _fire_midi(device, MidiMessage.cc(channel=0, control=71, value=65))

    cb.assert_called_once_with("Track1 Encoder", -63)


def test_midi_in_all_encoder_names_dispatched() -> None:
    """All encoder CC numbers dispatch to the correct encoder name."""
    from src.devices.push2.mapping import PUSH2_ENCODER_CC_TO_NAME

    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=MagicMock(), on_button=MagicMock(), on_encoder=cb)

    for cc, expected_name in PUSH2_ENCODER_CC_TO_NAME.items():
        cb.reset_mock()
        _fire_midi(device, MidiMessage.cc(channel=0, control=cc, value=1))
        cb.assert_called_once()
        assert cb.call_args[0][0] == expected_name


def test_midi_in_button_press() -> None:
    """CC for Play button val=127 → on_button('Play', True)."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=MagicMock(), on_button=cb, on_encoder=MagicMock())

    play_cc = PUSH2_BUTTON_NAME_TO_CC["Play"]
    _fire_midi(device, MidiMessage.cc(channel=0, control=play_cc, value=127))

    cb.assert_called_once_with("Play", True)


def test_midi_in_button_release() -> None:
    """CC for Play button val=0 → on_button('Play', False)."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=MagicMock(), on_button=cb, on_encoder=MagicMock())

    play_cc = PUSH2_BUTTON_NAME_TO_CC["Play"]
    _fire_midi(device, MidiMessage.cc(channel=0, control=play_cc, value=0))

    cb.assert_called_once_with("Play", False)


def test_midi_in_unknown_cc_ignored() -> None:
    """CC not in any mapping should not invoke any callback."""
    device, _, _ = _make_device_with_mock_ports()
    on_button = MagicMock()
    on_encoder = MagicMock()
    device.register_callbacks(
        on_pad=MagicMock(), on_button=on_button, on_encoder=on_encoder
    )

    # CC 0 is not mapped to any button or encoder
    _fire_midi(device, MidiMessage.cc(channel=0, control=0, value=127))

    on_button.assert_not_called()
    on_encoder.assert_not_called()


def test_midi_in_note_outside_pad_range_ignored() -> None:
    """Note on/off outside 36-99 range should not fire on_pad."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=cb, on_button=MagicMock(), on_encoder=MagicMock())

    _fire_midi(
        device, MidiMessage.note_on(channel=0, note=35, velocity=100)
    )  # below range
    _fire_midi(
        device, MidiMessage.note_on(channel=0, note=100, velocity=100)
    )  # above range

    cb.assert_not_called()


# ---------------------------------------------------------------------------
# Касания энкодеров (спека «Encoders»: touch = note-on nn9/nn10)
# ---------------------------------------------------------------------------


def test_midi_in_tempo_touch_fires_button_press() -> None:
    """note_on nn10 (velocity > 0) → on_button('Tempo Encoder', True)."""
    device, _, _ = _make_device_with_mock_ports()
    on_button = MagicMock()
    device.register_callbacks(
        on_pad=MagicMock(), on_button=on_button, on_encoder=MagicMock()
    )

    _fire_midi(device, MidiMessage.note_on(channel=0, note=10, velocity=100))

    on_button.assert_called_once_with("Tempo Encoder", True)


def test_midi_in_swing_touch_release_fires_button_release() -> None:
    """note_off nn9 → on_button('Swing Encoder', False) (release игнорируется UI)."""
    device, _, _ = _make_device_with_mock_ports()
    on_button = MagicMock()
    device.register_callbacks(
        on_pad=MagicMock(), on_button=on_button, on_encoder=MagicMock()
    )

    _fire_midi(device, MidiMessage.note_off(channel=0, note=9, velocity=0))

    on_button.assert_called_once_with("Swing Encoder", False)


def test_midi_in_touch_note_on_vel0_is_not_touch() -> None:
    """note_on nn10 с velocity 0 — не касание (стандартная конвенция release)."""
    device, _, _ = _make_device_with_mock_ports()
    on_button = MagicMock()
    device.register_callbacks(
        on_pad=MagicMock(), on_button=on_button, on_encoder=MagicMock()
    )

    _fire_midi(device, MidiMessage.note_on(channel=0, note=10, velocity=0))

    on_button.assert_not_called()


def test_midi_in_other_encoder_touch_notes_ignored() -> None:
    """Касания энкодеров E1–E8 (nn0–nn8) не обрабатываются — без назначения."""
    device, _, _ = _make_device_with_mock_ports()
    on_button = MagicMock()
    device.register_callbacks(
        on_pad=MagicMock(), on_button=on_button, on_encoder=MagicMock()
    )

    for note in (0, 1, 7, 8, 11, 35):
        _fire_midi(device, MidiMessage.note_on(channel=0, note=note, velocity=100))

    on_button.assert_not_called()


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


def test_connect_raises_if_port_not_found() -> None:
    """connect() should raise RuntimeError if MIDI ports are not found."""
    device = Push2Device()
    mock_registry = MagicMock(spec=MidiPortRegistry)
    mock_registry.find_input.return_value = None
    mock_registry.find_output.return_value = None

    with (
        patch(
            "src.devices.push2.push2_device.create_registry", return_value=mock_registry
        ),
        pytest.raises(RuntimeError, match="Push 2 MIDI ports not found"),
    ):
        device.connect(Push2Config())


def test_disconnect_sends_note_off_all_pads() -> None:
    """disconnect() should send note_off for notes 36-99."""
    device, _, mock_out = _make_device_with_mock_ports()
    # Restore the real send_midi so it goes through to mock_out
    device.send_midi = Push2Device.send_midi.__get__(device, Push2Device)

    device.disconnect()

    sent = [c[0][0] for c in mock_out.send.call_args_list]
    note_offs = [m for m in sent if m.type == "note_off"]
    note_off_notes = {int(m.note) for m in note_offs}
    assert set(range(36, 100)) <= note_off_notes


def test_disconnect_sends_cc0_all_buttons() -> None:
    """disconnect() should send CC value=0 for all mapped buttons."""
    device, _, mock_out = _make_device_with_mock_ports()
    device.send_midi = Push2Device.send_midi.__get__(device, Push2Device)

    device.disconnect()

    sent = [c[0][0] for c in mock_out.send.call_args_list]
    cc_zeros = {
        int(m.control) for m in sent if m.type == "control_change" and int(m.value) == 0
    }
    assert set(PUSH2_BUTTON_NAME_TO_CC.values()) <= cc_zeros


def test_send_midi_calls_out_port() -> None:
    """send_midi() should forward the message to the MIDI out port."""
    device, _, mock_out = _make_device_with_mock_ports()
    # Use real send_midi (not the mocked one from fixture)
    device.send_midi = Push2Device.send_midi.__get__(device, Push2Device)

    msg = MidiMessage.cc(channel=0, control=85, value=127)
    device.send_midi(msg)

    mock_out.send.assert_called_with(msg)


# ---------------------------------------------------------------------------
# Display backlight sysex (0x08)
# ---------------------------------------------------------------------------


def _backlight_messages(mock_out: MagicMock) -> list[MidiMessage]:
    return [
        c[0][0]
        for c in mock_out.send.call_args_list
        if c[0][0].type == "sysex" and 0x08 in (c[0][0].data or ())
    ]


def test_connect_sends_backlight_sysex_default_brightness() -> None:
    """connect() должен включить подсветку: sysex 0x08 с яркостью по умолчанию."""
    _, _, mock_out = _make_device_with_mock_ports()

    backlight = _backlight_messages(mock_out)
    assert len(backlight) == 1
    assert tuple(backlight[0].data) == (0x00, 0x21, 0x1D, 0x01, 0x01, 0x08, 100, 0)


def test_connect_sends_backlight_sysex_max_brightness() -> None:
    """Яркость 255 кодируется 14-битно: LSB 0x7F + старший бит 1."""
    device = Push2Device()
    mock_out = MagicMock(spec=MidiOutPort)
    mock_registry = MagicMock(spec=MidiPortRegistry)
    mock_registry.find_input.return_value = "Ableton Push 2 Live Port"
    mock_registry.find_output.return_value = "Ableton Push 2 Live Port"

    with (
        patch("src.devices.push2.push2_device.create_in_port"),
        patch("src.devices.push2.push2_device.create_out_port", return_value=mock_out),
        patch(
            "src.devices.push2.push2_device.create_registry", return_value=mock_registry
        ),
        patch("src.devices.push2.push2_device.Push2UsbDisplay") as mock_usb_cls,
    ):
        mock_usb_cls.return_value.open.side_effect = RuntimeError("no USB")
        device.connect(Push2Config(display_enabled=True, brightness=255))

    backlight = _backlight_messages(mock_out)
    assert len(backlight) == 1
    assert tuple(backlight[0].data) == (0x00, 0x21, 0x1D, 0x01, 0x01, 0x08, 0x7F, 1)


def test_connect_sends_backlight_sysex_two_byte_encoding() -> None:
    """Яркость >127 требует старшего бита: 200 → LSB 72, MSB 1."""
    device = Push2Device()
    mock_out = MagicMock(spec=MidiOutPort)
    mock_registry = MagicMock(spec=MidiPortRegistry)
    mock_registry.find_input.return_value = "Ableton Push 2 Live Port"
    mock_registry.find_output.return_value = "Ableton Push 2 Live Port"

    with (
        patch("src.devices.push2.push2_device.create_in_port"),
        patch("src.devices.push2.push2_device.create_out_port", return_value=mock_out),
        patch(
            "src.devices.push2.push2_device.create_registry", return_value=mock_registry
        ),
        patch("src.devices.push2.push2_device.Push2UsbDisplay") as mock_usb_cls,
    ):
        mock_usb_cls.return_value.open.side_effect = RuntimeError("no USB")
        device.connect(Push2Config(brightness=200))

    backlight = _backlight_messages(mock_out)
    assert len(backlight) == 1
    assert tuple(backlight[0].data) == (0x00, 0x21, 0x1D, 0x01, 0x01, 0x08, 72, 1)


def test_connect_simulate_sends_no_backlight_sysex() -> None:
    """В simulate-режиме MIDI-порты не открываются — sysex не отправляется."""
    device = Push2Device()
    with patch("src.devices.push2.push2_device.create_registry") as mock_registry:
        device.connect(Push2Config(simulate=True))

    mock_registry.assert_not_called()


# ---------------------------------------------------------------------------
# Полнота карты кнопок по официальной спеке (Ableton Push 2 MIDI & Display
# Interface, MIDI Implementation Chart v2.0; сверено 02.11.2026)
# ---------------------------------------------------------------------------

# CC всех кнопок Push 2 из Implementation Chart (кроме педалей 64/69 и
# служебных зарезервированных 114-115, 120-127).
SPEC_BUTTON_CCS = {
    3,
    9,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
    52,
    53,
    54,
    55,
    56,
    57,
    58,
    59,
    60,
    61,
    62,
    63,
    85,
    86,
    87,
    88,
    89,
    90,
    116,
    117,
    118,
    119,
    102,
    103,
    104,
    105,
    106,
    107,
    108,
    109,
    110,
    111,
    112,
    113,
}


def test_button_map_covers_all_spec_buttons() -> None:
    """Каждая кнопка из спеки присутствует в PUSH2_BUTTON_NAME_TO_CC."""
    from src.devices.push2.mapping import PUSH2_BUTTON_NAME_TO_CC

    assert set(PUSH2_BUTTON_NAME_TO_CC.values()) == SPEC_BUTTON_CCS


def test_button_map_key_assignments() -> None:
    """Ключевые назначения CC согласно спеке (регрессия remap'а 02.11.2026)."""
    from src.devices.push2.mapping import PUSH2_BUTTON_NAME_TO_CC as M

    assert M["Add Track"] == 53  # был добавлен по запросу (wizard создания)
    assert M["Duplicate"] == 88
    assert M["Browse"] == 111  # был ошибочно 69 (foot pedal 2)
    assert M["Select"] == 48
    assert M["Page Left"] == 62
    assert M["Page Right"] == 63


def test_encoder_map_matches_spec() -> None:
    """Энкодеры: track 1-8 = CC 71-78, master = 79, tempo = 14, swing = 15.

    Регрессия: раньше карта была сдвинута на −1 (track 1 = 70), swing
    энкодер (CC 15) отсутствовал, а CC 78 (track 8) ошибочно значился
    как swing — на реальном Push 2 все энкодеры были смещены.
    """
    from src.devices.push2.mapping import PUSH2_ENCODER_CC_TO_NAME as E

    for i in range(8):
        assert E[71 + i] == f"Track{i + 1} Encoder"
    assert E[79] == "Master Encoder"
    assert E[14] == "Tempo Encoder"
    assert E[15] == "Swing Encoder"
    assert len(E) == 11


def test_midi_in_swing_encoder_dispatched() -> None:
    """CC 15 → Swing Encoder (спека; раньше отсутствовал в карте)."""
    device, _, _ = _make_device_with_mock_ports()
    cb = MagicMock()
    device.register_callbacks(on_pad=MagicMock(), on_button=MagicMock(), on_encoder=cb)

    _fire_midi(device, MidiMessage.cc(channel=0, control=15, value=1))

    cb.assert_called_once_with("Swing Encoder", 1)


def test_midi_in_add_track_button_dispatched() -> None:
    """CC 53 → 'Add Track' (wizard создания дорожки)."""
    device, _, _ = _make_device_with_mock_ports()
    button_cb = MagicMock()
    device.register_callbacks(
        on_pad=MagicMock(), on_button=button_cb, on_encoder=MagicMock()
    )

    _fire_midi(device, MidiMessage.cc(channel=0, control=53, value=127))

    button_cb.assert_called_once_with("Add Track", True)
