"""Tests for src/devices/push2/push2_display.py — USB display driver."""

from unittest.mock import MagicMock, patch

import numpy
import pytest

from src.devices.push2.push2_display import (
    _FRAME_WIDTH,
    _HEADER,
    _XOR_PATTERN_U16,
    BULK_OUT_ENDPOINT,
    FILLER_PER_LINE,
    LINES,
    PIXELS_PER_LINE,
    FrameEncoder,
    Push2UsbDisplay,
    _encode_frame,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _black_frame() -> numpy.ndarray:
    return numpy.zeros((PIXELS_PER_LINE, LINES), dtype=numpy.uint16)


def _white_frame() -> numpy.ndarray:
    return numpy.full((PIXELS_PER_LINE, LINES), 0xFFFF, dtype=numpy.uint16)


# ---------------------------------------------------------------------------
# _encode_frame — pure encoding function
# ---------------------------------------------------------------------------


def test_encode_frame_total_size() -> None:
    """Encoded frame must be exactly LINES × _FRAME_WIDTH uint16 values = 327 680 bytes."""
    result = _encode_frame(_black_frame())
    assert len(result) == LINES * _FRAME_WIDTH * 2


def test_encode_frame_xor_applied_to_black_frame() -> None:
    """Black frame (all zeros) — first 4 bytes of output equal the raw XOR pattern bytes.

    The double-byteswap trick maps uint16 XOR values to their little-endian byte pairs:
        0 ^ 0xE7F3 → 0xF3E7 → LE bytes [0xE7, 0xF3]
        0 ^ 0xE7FF → 0xFFE7 → LE bytes [0xE7, 0xFF]
    """
    result = _encode_frame(_black_frame())
    assert result[:4] == bytes([0xE7, 0xF3, 0xE7, 0xFF])


def test_encode_frame_xor_applied_to_white_frame() -> None:
    """White frame (0xFFFF per pixel) — bytes equal the complement of the XOR pattern.

    0xFFFF ^ 0xE7F3 → 0x180C → byteswap → 0x0C18 → LE bytes [0x18, 0x0C]
    0xFFFF ^ 0xE7FF → 0x1800 → byteswap → 0x0018 → LE bytes [0x18, 0x00]
    """
    result = _encode_frame(_white_frame())
    assert result[:4] == bytes([0x18, 0x0C, 0x18, 0x00])


def test_encode_frame_deterministic() -> None:
    """Same input frame must produce identical output every time."""
    frame = numpy.arange(PIXELS_PER_LINE * LINES, dtype=numpy.uint16).reshape(
        (PIXELS_PER_LINE, LINES)
    )
    assert _encode_frame(frame) == _encode_frame(frame)


def test_encode_frame_xor_pattern_length() -> None:
    """_XOR_PATTERN_U16 must cover the entire encoded frame."""
    assert len(_XOR_PATTERN_U16) == LINES * _FRAME_WIDTH


def test_encode_frame_filler_is_xord() -> None:
    """Filler columns (indices 960-1023 per line) are XOR-scrambled, not left as zeros.

    The XOR mask is applied to the entire prepared frame including the filler area.
    Filler columns start at the same XOR-pattern offset as position 960 in each line.
    """
    result = _encode_frame(_black_frame())
    # Filler for line 0 starts at byte offset 960*2 = 1920
    filler_start = PIXELS_PER_LINE * 2
    filler_bytes = result[filler_start : filler_start + FILLER_PER_LINE]
    # XOR of zeros with pattern → filler is not zero
    assert filler_bytes != bytes(FILLER_PER_LINE)
    # Specifically: position 960 is even in the repeating pair → XOR 0xE7F3
    # 0 ^ 0xE7F3 = 0xF3E7 → LE bytes [0xE7, 0xF3]
    assert filler_bytes[:2] == bytes([0xE7, 0xF3])


# ---------------------------------------------------------------------------
# FrameEncoder — allocation-free hot path, byte-identical to _encode_frame
# ---------------------------------------------------------------------------


def _pattern_frame() -> numpy.ndarray:
    """Frame with varied pixel values (gradient + noise-ish pattern)."""
    frame = numpy.zeros((PIXELS_PER_LINE, LINES), dtype=numpy.uint16)
    frame[:, :] = numpy.arange(PIXELS_PER_LINE, dtype=numpy.uint16)[:, None]
    frame[::7, ::3] = 0xF800
    frame[1::11, 1::5] = 0x07FF
    return frame


def test_frame_encoder_matches_legacy() -> None:
    """FrameEncoder.encode must be byte-identical to legacy _encode_frame."""
    enc = FrameEncoder()
    frame = _pattern_frame()
    assert bytes(enc.encode(frame)) == _encode_frame(frame)


def test_frame_encoder_reuse_stable() -> None:
    """Repeated encodes of the same frame give the same bytes, no realloc."""
    enc = FrameEncoder()
    frame = _pattern_frame()
    first = bytes(enc.encode(frame))
    buf_id = id(enc._flat)
    for _ in range(10):
        again = bytes(enc.encode(frame))
        assert again == first
        assert id(enc._flat) == buf_id


def test_frame_encoder_black_and_white() -> None:
    enc = FrameEncoder()
    assert bytes(enc.encode(_black_frame()))[:4] == bytes([0xE7, 0xF3, 0xE7, 0xFF])
    assert bytes(enc.encode(_white_frame()))[:4] == bytes([0x18, 0x0C, 0x18, 0x00])


def test_frame_encoder_filler_zeroed_between_calls() -> None:
    """Filler columns must be zero on every encode even after a larger frame."""
    enc = FrameEncoder()
    enc.encode(_pattern_frame())
    out = numpy.frombuffer(bytes(enc.encode(_black_frame())), dtype=numpy.uint16)
    line0 = out[:_FRAME_WIDTH]
    filler = line0[PIXELS_PER_LINE:]
    # filler XOR-scrambled from zeros → raw pattern, but never stale pixel data
    assert filler[:1].tobytes() == bytes([0xE7, 0xF3])


# ---------------------------------------------------------------------------
# Push2UsbDisplay — unit tests with mocked USB
# ---------------------------------------------------------------------------


def test_open_raises_if_device_not_found() -> None:
    """open() must raise RuntimeError if Push 2 USB device is absent."""
    display = Push2UsbDisplay()
    with patch("src.devices.push2.push2_display.usb.core.find", return_value=None):
        with pytest.raises(RuntimeError, match="Push 2 USB device not found"):
            display.open()


def test_open_calls_set_configuration() -> None:
    """open() must call set_configuration() on the found device."""
    display = Push2UsbDisplay()
    mock_dev = MagicMock()
    mock_dev.is_kernel_driver_active.return_value = False

    with patch("src.devices.push2.push2_display.usb.core.find", return_value=mock_dev):
        display.open()

    mock_dev.set_configuration.assert_called_once()


def test_send_frame_noop_when_closed() -> None:
    """send_frame() must not raise when the device is not open."""
    display = Push2UsbDisplay()
    frame = _black_frame()
    display.send_frame(frame)  # _device is None — should silently return


def test_send_frame_calls_device_write_twice() -> None:
    """send_frame() must call device.write() twice: header first, then frame data."""
    display = Push2UsbDisplay()
    mock_dev = MagicMock()
    mock_dev.is_kernel_driver_active.return_value = False

    with patch("src.devices.push2.push2_display.usb.core.find", return_value=mock_dev):
        display.open()

    frame = _black_frame()
    display.send_frame(frame)

    assert mock_dev.write.call_count == 2

    # First write: 16-byte header
    first_call_args = mock_dev.write.call_args_list[0][0]
    assert first_call_args[0] == BULK_OUT_ENDPOINT
    assert first_call_args[1] == _HEADER

    # Second write: encoded frame data
    second_call_args = mock_dev.write.call_args_list[1][0]
    assert second_call_args[0] == BULK_OUT_ENDPOINT
    assert len(second_call_args[1]) == LINES * _FRAME_WIDTH * 2


def test_clear_sends_black_frame() -> None:
    """clear() must send an all-zero (black) frame via two device.write() calls."""
    display = Push2UsbDisplay()
    mock_dev = MagicMock()
    mock_dev.is_kernel_driver_active.return_value = False

    with patch("src.devices.push2.push2_display.usb.core.find", return_value=mock_dev):
        display.open()

    display.clear()

    assert mock_dev.write.call_count == 2
    second_call_args = mock_dev.write.call_args_list[1][0]
    assert second_call_args[0] == BULK_OUT_ENDPOINT
    assert len(second_call_args[1]) == LINES * _FRAME_WIDTH * 2


def test_close_disposes_resources() -> None:
    """close() must release the USB device handle."""
    display = Push2UsbDisplay()
    mock_dev = MagicMock()
    mock_dev.is_kernel_driver_active.return_value = False

    with (
        patch("src.devices.push2.push2_display.usb.core.find", return_value=mock_dev),
        patch(
            "src.devices.push2.push2_display.usb.util.dispose_resources"
        ) as mock_dispose,
    ):
        display.open()
        display.close()

    mock_dispose.assert_called_once_with(mock_dev)
    assert display._device is None
