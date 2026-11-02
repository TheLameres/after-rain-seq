"""Tests for FrameBuffer primitives in src/devices/push2/renderer.py."""

import numpy
import pytest

from src.devices.push2.renderer import (
    Colors,
    FrameBuffer,
    brighten565,
    rgb_to_bgr565,
)

# ── color helpers ─────────────────────────────────────────────────────────────


def test_bgr565_channel_layout() -> None:
    """Ableton wire layout: bits 15..0 = b g r (blue high, red low)."""
    assert rgb_to_bgr565(255, 0, 0) == 0x001F  # red
    assert rgb_to_bgr565(0, 255, 0) == 0x07E0  # green
    assert rgb_to_bgr565(0, 0, 255) == 0xF800  # blue
    assert rgb_to_bgr565(0, 0, 0) == 0x0000
    assert rgb_to_bgr565(255, 255, 255) == 0xFFFF


def test_bgr565_quantization() -> None:
    """5/6/5-bit truncation of low bits."""
    assert rgb_to_bgr565(7, 3, 7) == 0x0000  # all below bit 3/2
    assert rgb_to_bgr565(8, 0, 0) == 0x0001  # r bit0


def test_brighten565() -> None:
    red8 = 8  # raw 565 value with r-channel = 8
    bright = brighten565(red8, 2.0)
    assert bright & 0x1F == 16
    # channels beyond max are clamped
    white = rgb_to_bgr565(255, 255, 255)
    assert brighten565(white, 1.5) == white


# ── fill / fill_rect ──────────────────────────────────────────────────────────


def test_fill_marks_full_dirty() -> None:
    fb = FrameBuffer(960, 160)
    fb.dirty.clear()
    fb.fill(Colors.WHITE)
    assert fb.dirty.is_full
    assert fb.pixels[0, 0] == Colors.WHITE
    assert fb.pixels[959, 159] == Colors.WHITE


def test_fill_rect_pixels() -> None:
    fb = FrameBuffer(960, 160)
    fb.dirty.clear()
    fb.fill_rect(10, 20, 30, 40, Colors.TRACK_FILL)
    # corners and center
    assert fb.pixels[10, 20] == Colors.TRACK_FILL
    assert fb.pixels[39, 20] == Colors.TRACK_FILL
    assert fb.pixels[10, 59] == Colors.TRACK_FILL
    assert fb.pixels[39, 59] == Colors.TRACK_FILL
    assert fb.pixels[24, 39] == Colors.TRACK_FILL
    # outside stays black
    assert fb.pixels[9, 20] == Colors.BG
    assert fb.pixels[40, 20] == Colors.BG
    assert fb.pixels[10, 19] == Colors.BG
    assert fb.pixels[10, 60] == Colors.BG


def test_fill_rect_marks_dirty_bbox() -> None:
    fb = FrameBuffer(960, 160)
    fb.dirty.clear()
    fb.fill_rect(10, 20, 30, 40, Colors.WHITE)
    assert fb.dirty.rects() == ((10, 20, 40, 60),)


def test_fill_rect_clipped_at_frame_edge() -> None:
    fb = FrameBuffer(960, 160)
    fb.fill_rect(950, 150, 100, 100, Colors.WHITE)  # extends past both edges
    assert fb.pixels[959, 159] == Colors.WHITE
    assert fb.dirty.rects() == ((950, 150, 960, 160),)


def test_fill_rect_fully_outside_is_noop() -> None:
    fb = FrameBuffer(960, 160)
    fb.dirty.clear()
    fb.fill_rect(-100, 0, 50, 50, Colors.WHITE)
    assert fb.dirty.rects() == ()


# ── lines ─────────────────────────────────────────────────────────────────────


def test_hline() -> None:
    fb = FrameBuffer(960, 160)
    fb.dirty.clear()
    fb.hline(10, 5, 20, Colors.WHITE)
    assert fb.pixels[10, 5] == Colors.WHITE
    assert fb.pixels[29, 5] == Colors.WHITE
    assert fb.pixels[30, 5] == Colors.BG
    assert fb.pixels[10, 6] == Colors.BG
    assert fb.dirty.rects() == ((10, 5, 30, 6),)


def test_vline() -> None:
    fb = FrameBuffer(960, 160)
    fb.dirty.clear()
    fb.vline(10, 5, 20, Colors.WHITE)
    assert fb.pixels[10, 5] == Colors.WHITE
    assert fb.pixels[10, 24] == Colors.WHITE
    assert fb.pixels[10, 25] == Colors.BG
    assert fb.pixels[11, 5] == Colors.BG
    assert fb.dirty.rects() == ((10, 5, 11, 25),)


def test_rect_outline() -> None:
    fb = FrameBuffer(960, 160)
    fb.dirty.clear()
    fb.rect(10, 10, 20, 10, Colors.WHITE)
    # border painted
    assert fb.pixels[10, 10] == Colors.WHITE  # top-left
    assert fb.pixels[29, 10] == Colors.WHITE  # top-right
    assert fb.pixels[10, 19] == Colors.WHITE  # bottom-left
    assert fb.pixels[29, 19] == Colors.WHITE  # bottom-right
    # interior empty
    assert fb.pixels[15, 14] == Colors.BG
    assert fb.pixels[20, 10] == Colors.WHITE  # top edge middle
    assert fb.dirty.rects() == ((10, 10, 30, 20),)


# ── blit ──────────────────────────────────────────────────────────────────────


def test_blit_patch() -> None:
    fb = FrameBuffer(960, 160)
    patch = numpy.full((8, 6), Colors.WHITE, dtype=numpy.uint16)  # (w, h)
    fb.dirty.clear()
    fb.blit(patch, 100, 50)
    assert fb.pixels[100, 50] == Colors.WHITE
    assert fb.pixels[107, 55] == Colors.WHITE
    assert fb.pixels[108, 55] == Colors.BG
    assert fb.dirty.rects() == ((100, 50, 108, 56),)


def test_blit_clipped() -> None:
    fb = FrameBuffer(960, 160)
    patch = numpy.full((20, 20), Colors.WHITE, dtype=numpy.uint16)
    fb.blit(patch, 955, 155)
    assert fb.pixels[959, 159] == Colors.WHITE
    assert fb.dirty.rects() == ((955, 155, 960, 160),)


# ── bar / grid_cell ───────────────────────────────────────────────────────────


def test_bar_fill_ratio() -> None:
    fb = FrameBuffer(960, 160)
    fb.bar(0, 0, 100, 10, 0, 127, Colors.WHITE, Colors.ENCODER_BG)
    assert fb.pixels[0, 0] == Colors.ENCODER_BG  # empty: only background
    fb.bar(0, 0, 100, 10, 64, 127, Colors.WHITE, Colors.ENCODER_BG)
    fill_w = 100 * 64 // 127  # 50
    assert fb.pixels[49, 0] == Colors.WHITE
    assert fb.pixels[50, 0] == Colors.ENCODER_BG
    _ = fill_w
    fb.bar(0, 0, 100, 10, 127, 127, Colors.WHITE, Colors.ENCODER_BG)
    assert fb.pixels[99, 0] == Colors.WHITE


def test_bar_clamps_over_max() -> None:
    fb = FrameBuffer(960, 160)
    fb.bar(0, 0, 100, 10, 200, 127, Colors.WHITE, Colors.ENCODER_BG)
    assert fb.pixels[99, 0] == Colors.WHITE


def test_bar_dirty() -> None:
    fb = FrameBuffer(960, 160)
    fb.dirty.clear()
    fb.bar(10, 10, 100, 10, 64, 127, Colors.WHITE, Colors.ENCODER_BG)
    assert fb.dirty.rects() == ((10, 10, 110, 20),)


def test_grid_cell_states() -> None:
    fb = FrameBuffer(960, 160)
    # unlit
    fb.grid_cell(0, 0, 10, 10, Colors.CONNECTED, lit=False)
    assert fb.pixels[5, 5] == Colors.ENCODER_BG
    # lit
    fb.grid_cell(0, 0, 10, 10, Colors.CONNECTED, lit=True)
    assert fb.pixels[5, 5] == Colors.CONNECTED
    # lit + head → white border on top of fill
    fb.grid_cell(0, 0, 10, 10, Colors.CONNECTED, lit=True, head=True)
    assert fb.pixels[5, 5] == Colors.CONNECTED
    assert fb.pixels[0, 0] == Colors.WHITE  # border corner
    assert fb.pixels[9, 9] == Colors.WHITE  # border corner
    assert fb.pixels[5, 0] == Colors.WHITE  # top edge


# ── misc ──────────────────────────────────────────────────────────────────────


def test_reset_clears_to_color() -> None:
    fb = FrameBuffer(960, 160)
    fb.fill_rect(0, 0, 100, 100, Colors.WHITE)
    fb.reset()
    assert fb.pixels[50, 50] == Colors.BG
    assert fb.dirty.is_full


def test_text_without_fonts_raises() -> None:
    fb = FrameBuffer(960, 160)  # no fonts
    with pytest.raises(RuntimeError, match="without fonts"):
        fb.text(0, 0, "hi", "sm", Colors.WHITE)
