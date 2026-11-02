"""Tests for PushDisplay (interim status screen) in src/devices/push2/display.py."""

from unittest.mock import MagicMock

from src.devices.push2.display import (
    _RECT_HEADER,
    PushDisplay,
)


def _state(**overrides) -> dict:
    base = {
        "push2_connected": True,
        "sync_bpm": 120.0,
        "sync_link_peers": 0,
        "sync_link_active": False,
        "sync_clock_source": "internal",
    }
    base.update(overrides)
    return base


def _rect_within(rect: tuple[int, int, int, int], bounds) -> bool:
    """True if rect fits inside bounds (x, y, w, h) with 1 px tolerance."""
    x, y, w, h = bounds
    return (
        rect[0] >= x - 1
        and rect[1] >= y - 1
        and rect[2] <= x + w + 1
        and (rect[3] <= y + h + 1)
    )


# ── API stability / smoke ─────────────────────────────────────────────────────


def test_render_frame_only_fires_on_frame() -> None:
    frames: list = []
    disp = PushDisplay(fps=25, on_frame=frames.append)
    disp.update_state(**_state())
    disp.render_frame_only()
    assert len(frames) == 1
    img = frames[0]
    assert img.size == (960, 160)
    assert img.mode == "RGB"


def test_no_on_frame_when_state_unchanged() -> None:
    """Second render with identical state must not redraw or fire the callback."""
    frames: list = []
    disp = PushDisplay(fps=25, on_frame=frames.append)
    disp.update_state(**_state())
    disp.render_frame_only()
    disp.update_state(**_state())
    disp.render_frame_only()
    assert len(frames) == 1


# ── partial invalidation ──────────────────────────────────────────────────────


def test_first_update_marks_header_dirty() -> None:
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    assert disp._dirty_regions == {"header"}


def test_bpm_change_marks_nothing() -> None:
    """Статус-бара нет (D2-5): sync-поля принимаются, но регионов не рождают."""
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    disp._compose()
    disp._fb.dirty.take()

    disp.update_state(**_state(sync_bpm=121.0, sync_clock_source="link"))
    assert disp._dirty_regions == set()


def test_connection_change_dirty_only_header() -> None:
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    disp._compose()
    disp._fb.dirty.take()

    disp.update_state(**_state(push2_connected=False))
    assert disp._dirty_regions == {"header"}
    disp._compose()
    rects = disp._fb.dirty.rects()
    assert rects
    assert all(_rect_within(r, _RECT_HEADER) for r in rects)


def test_unrelated_repeat_update_marks_nothing() -> None:
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    disp._compose()
    disp._fb.dirty.take()
    disp.update_state(**_state())
    assert not disp._dirty_regions
    disp._compose()
    assert disp._fb.dirty.rects() == ()


# ── render_usb: send-on-dirty + keepalive ─────────────────────────────────────


def test_render_usb_sends_when_dirty() -> None:
    usb = MagicMock()
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    disp.render_usb(usb)
    assert usb.send_frame.call_count == 1


def test_render_usb_silent_when_clean() -> None:
    """Clean frame + keepalive not due → no USB traffic."""
    usb = MagicMock()
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    disp.render_usb(usb)  # dirty → send
    usb.reset_mock()
    disp.render_usb(usb)  # nothing changed
    usb.send_frame.assert_not_called()


def test_render_usb_keepalive_after_silence() -> None:
    """After 1 s of silence a keepalive frame goes out (display blanks at 2 s)."""
    usb = MagicMock()
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    disp.render_usb(usb)
    usb.reset_mock()
    disp._last_send -= 2.0  # simulate 2 s passed
    disp.render_usb(usb)
    usb.send_frame.assert_called_once()


def test_render_usb_dirty_clears_after_send() -> None:
    usb = MagicMock()
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    disp.render_usb(usb)
    assert disp._fb.dirty.rects() == ()


def test_render_usb_sends_updated_frame_after_change() -> None:
    usb = MagicMock()
    disp = PushDisplay(fps=25)
    disp.update_state(**_state())
    disp.render_usb(usb)
    usb.reset_mock()
    disp.update_state(**_state(push2_connected=False))
    disp.render_usb(usb)
    usb.send_frame.assert_called_once()
