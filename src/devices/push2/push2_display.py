"""Push 2 USB display driver.

Sends BGR565 frames to the Push 2's 960×160 pixel display via USB bulk transfer.

USB wire format (Ableton Push 2 MIDI & Display Interface spec):
  - 16-byte frame header (separate USB write)
  - (960 + 64 filler) × 160 uint16 BGR565 values, XOR-scrambled, as one USB write
  - XOR pattern: repeating uint16 pairs [0xE7F3, 0xE7FF] applied via double-byteswap trick
  - Color format: BGR565 (16 bits per pixel)

USB device:
  VENDOR_ID  = 0x2982  (Ableton)
  PRODUCT_ID = 0x1967  (Push 2)
  Endpoint   = 0x01    (Bulk OUT)
"""

from __future__ import annotations

import logging

import numpy
import usb.core
import usb.util

log = logging.getLogger(__name__)

# ── USB device constants ──────────────────────────────────────────────────────
VENDOR_ID = 0x2982
PRODUCT_ID = 0x1967
BULK_OUT_ENDPOINT = 0x01

# ── Frame geometry ────────────────────────────────────────────────────────────
LINES = 160
PIXELS_PER_LINE = 960
FILLER_PER_LINE = 128  # zero-padding to align each line to 2048 bytes

# ── Wire encoding constants ───────────────────────────────────────────────────
_HEADER = bytes([0xFF, 0xCC, 0xAA, 0x88, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])

# XOR scrambling: repeating 4-byte pattern E7 F3 E7 FF applied to entire frame.
# Stored as uint16 pairs for the double-byteswap numpy trick (same as push2-python):
#   frame.byteswap() → bitwise_xor([0xE7F3, 0xE7FF]) → byteswap() back
_FRAME_WIDTH = PIXELS_PER_LINE + FILLER_PER_LINE // 2  # 960 + 64 = 1024 uint16/line
_XOR_PATTERN_U16: numpy.ndarray = numpy.array(
    [0xE7F3, 0xE7FF] * (_FRAME_WIDTH * LINES // 2),
    dtype=numpy.uint16,
)


class Push2UsbDisplay:
    """Owns the USB device handle for the Push 2 display.

    Thread model: single-threaded. Call send_frame() from one thread only
    (the render loop). No internal thread; caller is responsible for fps limiting.

    Usage::

        display = Push2UsbDisplay()
        display.open()          # find USB device; raises RuntimeError if absent
        display.send_frame(np_array)   # BGR565 array shape (960, 160) uint16
        display.close()
    """

    def __init__(self) -> None:
        self._device: usb.core.Device | None = None
        self._encoder = FrameEncoder()

    def open(self) -> None:
        """Find and configure the Push 2 USB device.

        Raises
        ------
        RuntimeError
            If the Push 2 USB device is not found.
        """
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev is None:
            raise RuntimeError(
                f"Ableton Push 2 USB device not found "
                f"(VID={VENDOR_ID:#06x} PID={PRODUCT_ID:#06x})"
            )

        # On Linux the kernel HID driver may own the interface — detach it.
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass  # macOS / Windows — no kernel driver concept

        try:
            dev.set_configuration()
        except usb.core.USBError as exc:
            raise RuntimeError(f"Push 2 USB set_configuration failed: {exc}") from exc

        # Per the Ableton Push 2 MIDI & Display Interface spec, interface 0 must
        # be claimed before bulk transfers to the display endpoint will work.
        try:
            usb.util.claim_interface(dev, 0)
        except usb.core.USBError as exc:
            raise RuntimeError(f"Push 2 USB claim_interface failed: {exc}") from exc

        self._device = dev
        log.info("Push 2 USB display opened (vid=%04x pid=%04x)", VENDOR_ID, PRODUCT_ID)

    def close(self) -> None:
        """Release the USB device handle."""
        if self._device is not None:
            try:
                usb.util.dispose_resources(self._device)
            except Exception as exc:  # noqa: BLE001
                log.debug("Push2UsbDisplay.close error: %s", exc)
            self._device = None
            log.debug("Push 2 USB display closed")

    def send_frame(self, frame: numpy.ndarray) -> None:
        """Encode and transmit one BGR565 frame to the display.

        Mirrors push2-python's send_to_display(): sends the 16-byte header
        in a first USB write, then the prepared frame data in a second write.

        Parameters
        ----------
        frame:
            numpy array shape ``(960, 160)`` dtype ``uint16``, BGR565 format.
            Produced by ``FrameBuffer.pixels`` (src/devices/push2/renderer.py).
        """
        if self._device is None:
            return
        buf = self._encoder.encode(frame)
        try:
            self._device.write(BULK_OUT_ENDPOINT, _HEADER)
            self._device.write(BULK_OUT_ENDPOINT, buf)
        except usb.core.USBError as exc:
            log.debug("Push2UsbDisplay.send_frame USB error: %s", exc)

    def clear(self) -> None:
        """Send an all-black frame (used during disconnect to blank the display)."""
        black = numpy.zeros((PIXELS_PER_LINE, LINES), dtype=numpy.uint16)
        self.send_frame(black)


class FrameEncoder:
    """BGR565 (960, 160) → Push 2 wire payload, allocation-free.

    Two buffers are preallocated at construction; ``encode()`` only writes
    into them, so the hot path performs no frame-sized allocations. The
    returned memoryview is valid until the next ``encode()`` call.

    Byte-identical to the legacy ``_encode_frame()`` (roundtrip-tested).
    """

    def __init__(self) -> None:
        # Line-major view of the wire payload: (LINES, _FRAME_WIDTH) C-order,
        # so row ``line`` is one display line (960 px + 64 filler columns).
        self._flat = numpy.zeros(_FRAME_WIDTH * LINES, dtype=numpy.uint16)
        self._lines = self._flat.reshape(LINES, _FRAME_WIDTH)

    def encode(self, frame: numpy.ndarray) -> memoryview:
        """Encode *frame* (960, 160) uint16 BGR565 into the wire payload.

        Returns a byte-level memoryview over the internal buffer.
        """
        lines = self._lines
        lines[:, PIXELS_PER_LINE:] = 0  # filler stays zero
        # frame is (W, H); transposed view assigns line-major without a copy
        lines[:, :PIXELS_PER_LINE] = frame.transpose()
        self._flat.byteswap(inplace=True)
        numpy.bitwise_xor(self._flat, _XOR_PATTERN_U16, out=self._flat)
        self._flat.byteswap(inplace=True)
        return memoryview(self._flat).cast("B")


def _encode_frame(frame: numpy.ndarray) -> bytes:
    """Encode a ``(960, 160)`` uint16 BGR565 array into Push 2 USB wire format.

    Mirrors push2-python's ``prepare_frame()`` for BGR565 input:
    1. Expand (960, 160) → (1024, 160) by appending 64 zero-filled filler columns.
    2. Transpose → (160, 1024) and flatten → 163,840 uint16 values.
    3. byteswap → bitwise_xor(_XOR_PATTERN_U16) → byteswap back.

    The result is sent as the second USB write (header is sent separately).

    Returns
    -------
    bytes
        163,840 uint16 values = 327,680 bytes (no header).
    """
    prepared = numpy.zeros(shape=(_FRAME_WIDTH, LINES), dtype=numpy.uint16)
    prepared[0:PIXELS_PER_LINE, :] = frame
    flat = prepared.transpose().flatten()
    flat = flat.byteswap()
    flat = numpy.bitwise_xor(flat, _XOR_PATTERN_U16)
    flat = flat.byteswap()
    return flat.tobytes()
