"""Push 2 display composer (D1) — interim screen after the M8-legacy cleanup.

Renders a minimal status screen onto the Push 2's 960×160 display via USB
using ``Push2UsbDisplay`` and the numpy primitives from ``renderer.py``:

  y   0-23 : header — application title
  y 138-160: status bar — BPM/LINK (left), connection dot (right)

Full screens with track banks, macros and navigation arrive in D2
(``screens.py``); this interim state keeps the render pipeline (dirty
rects, glyph cache, keepalive) exercised until then.

``update_state()`` compares the new snapshot against the previous one and
marks only the regions whose inputs changed.  ``_compose()`` redraws dirty
regions through ``FrameBuffer`` primitives (each redraws its full rect, so
no stale trails).  The wire protocol accepts complete frames only, so a
frame is sent when something is dirty or when the keepalive deadline
(1 s, display blanks after 2 s of silence per the Ableton spec) is due.

Thread-safety: state updates via update_state() are lock-guarded; compose
and send run in the render thread (render_usb / render_frame_only).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy
from PIL import Image, ImageFont

from src.devices.push2.renderer import FRAME_H, FRAME_W, Colors, FrameBuffer
from src.devices.push2.screens import Screens

if TYPE_CHECKING:
    from src.devices.display_state import ScreenView
    from src.devices.push2.push2_display import Push2UsbDisplay

# Region rectangles: (x, y, w, h)
# Header = таб-бар (0–21) + заголовок под ним (22–35) — см. screens.py.
# Нижнего статус-бара нет (D2-5): body занимает всё до нижнего края.
_RECT_HEADER = (0, 0, FRAME_W, 36)

# Send a keepalive frame after this much silence — the display blanks after
# 2 s without a complete frame (Ableton Push 2 Interface Manual, Frame Buffering).
_KEEPALIVE_SECONDS = 1.0

# Sentinel for "no previous state" — every region starts dirty.
_MISSING = object()

_APP_TITLE = "after-rain-seq"


# ── fonts (loaded once; chain inherited from push2-m8) ───────────────────────
def _try_load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Menlo.ttc",  # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",  # Debian/Ubuntu
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",  # Arch
        "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",  # Fedora
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)  # type: ignore[return-value]
        except OSError:
            pass
    return ImageFont.load_default()


_FONTS = {
    "lg": _try_load_font(14),  # large text — header title
    "md": _try_load_font(12),  # main text
    "sm": _try_load_font(10),  # small text — status bar
}


class PushDisplay:
    """Renders a minimal status screen on Push 2.

    Thread-safe: state is updated via update_state(); render_usb() /
    render_frame_only() run in the render thread.
    """

    def __init__(
        self, fps: int = 15, on_frame: Callable[[Image.Image], None] | None = None
    ) -> None:
        self._fps = fps
        self._on_frame = on_frame
        self._lock = threading.Lock()
        self._fb = FrameBuffer(FRAME_W, FRAME_H, fonts=_FONTS)
        # Экраны (реестр + композитор): таб-бар/заголовок/body по ScreenView.
        self._screens = Screens()

        # Input state (as passed to update_state)
        self._push2_ok = False
        self._sync_bpm: float | None = None
        self._sync_link_peers: int = 0
        self._sync_link_active: bool = False
        self._sync_clock_source: str = "off"

        # D2 screen state (as passed to update_screen); None — legacy режим.
        self._screen_view: ScreenView | None = None

        # Region invalidation
        self._dirty_regions: set[str] = set()
        self._prev: dict[str, object] = {}

        self._last_send = 0.0

    # ------------------------------------------------------------------
    # Public API (stable — used by Push2Device)
    # ------------------------------------------------------------------

    def set_on_frame(self, cb: Callable[[Image.Image], None] | None) -> None:
        """Set or replace the frame-ready callback (thread-safe)."""
        self._on_frame = cb

    def update_state(
        self,
        push2_connected: bool,
        sync_bpm: float | None = None,
        sync_link_peers: int = 0,
        sync_link_active: bool = False,
        sync_clock_source: str = "off",
    ) -> None:
        """Update display state. Thread-safe; marks changed regions dirty."""
        with self._lock:
            self._push2_ok = push2_connected
            self._sync_bpm = sync_bpm
            self._sync_link_peers = sync_link_peers
            self._sync_link_active = sync_link_active
            self._sync_clock_source = sync_clock_source
            self._invalidate_changed_regions()

    def update_screen(self, view: ScreenView) -> None:
        """Update D2 screen view. Thread-safe; per-region invalidation.

        Смена экрана (``view.screen``) — full reset (как D1 ``reset()``);
        внутри одного экрана сравниваем view по регионам и помечаем dirty
        только изменённые (header/body/status).
        """
        with self._lock:
            prev = self._screen_view
            if prev is not None and prev.screen != view.screen:
                self._fb.reset(Colors.BG)
                self._prev.clear()
            self._screen_view = view
            self._invalidate_screen_regions(view)

    def render_usb(self, usb_display: Push2UsbDisplay) -> None:
        """Compose dirty regions and send a frame when needed.

        A frame goes out when any region is dirty, or when the keepalive
        deadline (1 s) has passed — the Push 2 display blanks after 2 s
        without a complete frame. Static screens cost zero USB traffic.
        """
        now = time.monotonic()
        frame: numpy.ndarray | None = None
        preview: Image.Image | None = None
        send = False
        with self._lock:
            self._compose()
            if self._fb.dirty.rects():
                send = True
                frame = self._fb.pixels
                if self._on_frame is not None:
                    preview = self._build_preview()
                self._fb.dirty.take()
            elif now - self._last_send >= _KEEPALIVE_SECONDS:
                send = True
                frame = self._fb.pixels
            if send:
                self._last_send = now
        if frame is not None:
            usb_display.send_frame(frame)
        if preview is not None and self._on_frame is not None:
            self._on_frame(preview)

    def render_frame_only(self) -> None:
        """Compose dirty regions and fire on_frame without USB (simulate mode)."""
        preview: Image.Image | None = None
        with self._lock:
            self._compose()
            if self._fb.dirty.rects():
                if self._on_frame is not None:
                    preview = self._build_preview()
                self._fb.dirty.take()
        if preview is not None and self._on_frame is not None:
            self._on_frame(preview)

    # ------------------------------------------------------------------
    # Region invalidation
    # ------------------------------------------------------------------

    def _invalidate_changed_regions(self) -> None:
        """Compare snapshot fields per region; mark changed regions dirty.

        Must be called under self._lock.
        """
        checks: dict[str, object] = {
            "header": self._push2_ok,
        }
        for name, key in checks.items():
            if self._prev.get(name, _MISSING) != key:
                self._dirty_regions.add(name)
                self._prev[name] = key

    def _invalidate_screen_regions(self, view: ScreenView) -> None:
        """Per-region diff D2-view (frozen DTO сравниваются по значению).

        Must be called under self._lock.
        """
        checks: dict[str, object] = {
            "header": (view.tab, view.title, view.flash),
            "body": (
                view.tracks,
                view.track,
                view.track_macro,
                view.sync,
                view.ports,
                view.scale,
                view.wizard,
            ),
        }
        for name, key in checks.items():
            if self._prev.get(name, _MISSING) != key:
                self._dirty_regions.add(name)
                self._prev[name] = key

    def _compose(self) -> None:
        """Redraw dirty regions. Must be called under self._lock."""
        if not self._dirty_regions:
            return
        if self._screen_view is not None:
            self._compose_screen()
            return
        dirty = self._dirty_regions
        if "header" in dirty:
            self._draw_header()
        dirty.clear()

    def _compose_screen(self) -> None:
        """Compose D2 screen view. Must be called under self._lock."""
        view = self._screen_view
        assert view is not None
        dirty = self._dirty_regions
        if "header" in dirty:
            self._screens.draw_header(self._fb, view)
        if "body" in dirty:
            self._screens.draw_body(self._fb, view)
        dirty.clear()

    # ------------------------------------------------------------------
    # Preview (screen emulator): BGR565 → RGB888
    # ------------------------------------------------------------------

    def _build_preview(self) -> Image.Image:
        """Convert the frame buffer to a PIL image for the emulator."""
        px = self._fb.pixels  # (W, H) uint16
        r = (px & 0x1F) << 3
        g = ((px >> 5) & 0x3F) << 2
        b = ((px >> 11) & 0x1F) << 3
        rgb = numpy.stack([r, g, b], axis=-1).transpose(1, 0, 2)  # (H, W, 3)
        return Image.fromarray(rgb.astype(numpy.uint8), "RGB")

    # ------------------------------------------------------------------
    # Regions (each fully repaints its own rect — no stale trails)
    # ------------------------------------------------------------------

    def _draw_header(self) -> None:
        """y 0-23: application title + connection dot."""
        fb = self._fb
        fb.fill_rect(*_RECT_HEADER, Colors.BG)
        fb.text(4, 4, _APP_TITLE, "lg", Colors.GRAY)
        dot_color = Colors.CONNECTED if self._push2_ok else Colors.DISCONNECTED
        fb.fill_rect(FRAME_W - 14, 8, 8, 8, dot_color)
