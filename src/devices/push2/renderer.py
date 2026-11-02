"""Renderer primitives for the Push 2 960×160 display (D1).

Owns the frame buffer and the only drawing API used by display composers:

- ``DirtyTracker`` — region invalidation with merge and full-frame degrade.
- ``FrameBuffer`` — uint16 BGR565 pixels (W, H) + drawing primitives. Every
  primitive invalidates its bounding box.
- ``GlyphCache`` — PIL rasterizes each glyph once into an L-mode mask; the
  hot path is a masked numpy write, color applied at draw time (the cache
  key is (char, font_key), not color — recoloring is free).
- Color helpers — RGB→BGR565, LPP3 palette→BGR565, 565 brighten.

BGR565 layout follows the Ableton Push 2 MIDI & Display Interface spec:
bits 15..0 = b4..b0 g5..g0 r4..r0 (blue in the high bits), matching the
legacy ``_rgb_to_bgr565`` in ``display.py``.

Wire format note: the Push 2 USB protocol accepts complete frames only —
dirty rects save CPU on compose, never USB traffic.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping

import numpy
from PIL import Image, ImageDraw, ImageFont

# Frame geometry (Push 2 display)
FRAME_W = 960
FRAME_H = 160

# Type alias: (x0, y0, x1, y1) — half-open [x0, x1) × [y0, y1)
Rect = tuple[int, int, int, int]

# Pixels with mask value >= threshold are painted; below — left as-is.
# 96 (не 128): у 10px-глифов ('m', 'w') тонкие колонки имеют яркость
# 120-154 из-за антиалиасинга — при пороге 128 левая ножка 'm' терялась.
_GLYPH_THRESHOLD = 96


# ── colors ────────────────────────────────────────────────────────────────────


def rgb_to_bgr565(r: int, g: int, b: int) -> int:
    """Convert 8-bit RGB to BGR565 uint16 (Ableton wire layout)."""
    return int(((b >> 3) << 11) | ((g >> 2) << 5) | (r >> 3))


def brighten565(color: int, factor: float = 1.5) -> int:
    """Brighten a BGR565 color by *factor*, clamped to channel maxima."""
    r = color & 0x1F
    g = (color >> 5) & 0x3F
    b = (color >> 11) & 0x1F
    r = min(0x1F, int(r * factor))
    g = min(0x3F, int(g * factor))
    b = min(0x1F, int(b * factor))
    return (b << 11) | (g << 5) | r


class Colors:
    """Named project colors, BGR565."""

    BG = rgb_to_bgr565(0, 0, 0)
    WHITE = rgb_to_bgr565(255, 255, 255)
    BLACK = rgb_to_bgr565(0, 0, 0)
    GRAY = rgb_to_bgr565(160, 160, 170)
    DIM = rgb_to_bgr565(75, 75, 95)
    DARK_GRAY = rgb_to_bgr565(60, 60, 75)
    ENCODER_BG = rgb_to_bgr565(28, 28, 42)
    CONNECTED = rgb_to_bgr565(55, 195, 75)
    DISCONNECTED = rgb_to_bgr565(195, 55, 55)
    BPM_LINK = rgb_to_bgr565(80, 200, 255)  # cyan — BPM when source=link
    BPM_MIDI = rgb_to_bgr565(255, 165, 60)  # orange — BPM when source=midi
    LINK_ACTIVE = rgb_to_bgr565(80, 200, 255)
    TRACK_FILL = rgb_to_bgr565(55, 145, 225)


# ── dirty tracking ────────────────────────────────────────────────────────────


class DirtyTracker:
    """Registry of dirty frame regions.

    Rectangles are stored half-open ``(x0, y0, x1, y1)``, clamped to the
    frame. Overlapping or touching rects are merged; if the number of rects
    exceeds ``max_rects`` the tracker degrades to "full frame dirty" instead
    of doing quadratic merge work.
    """

    def __init__(
        self, width: int = FRAME_W, height: int = FRAME_H, max_rects: int = 64
    ) -> None:
        self._width = width
        self._height = height
        self._max_rects = max_rects
        self._rects: list[Rect] = []
        self._full = False

    @property
    def is_full(self) -> bool:
        """True when the whole frame is dirty (or the tracker degraded)."""
        return self._full

    def invalidate(self, x: int, y: int, w: int, h: int) -> None:
        """Mark a region dirty. Clamped to frame bounds."""
        if self._full:
            return
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self._width, int(x) + int(w))
        y1 = min(self._height, int(y) + int(h))
        if x1 <= x0 or y1 <= y0:
            return
        if x0 == 0 and y0 == 0 and x1 == self._width and y1 == self._height:
            self._full = True
            self._rects = []
            return
        rect: Rect = (x0, y0, x1, y1)
        # Merge with any overlapping or touching existing rect; repeat until
        # the rect no longer grows (a merge can make it touch another rect).
        merged = True
        while merged:
            merged = False
            for i, other in enumerate(self._rects):
                if self._touches(rect, other):
                    rect = self._union(rect, other)
                    del self._rects[i]
                    merged = True
                    break
        self._rects.append(rect)
        if len(self._rects) > self._max_rects:
            self._full = True
            self._rects = []

    def rects(self) -> tuple[Rect, ...]:
        """Current dirty regions (protected copy)."""
        if self._full:
            return ((0, 0, self._width, self._height),)
        return tuple(self._rects)

    def take(self) -> tuple[Rect, ...]:
        """Return the dirty regions and clear the tracker."""
        result = self.rects()
        self.clear()
        return result

    def clear(self) -> None:
        """Forget all dirty regions."""
        self._rects = []
        self._full = False

    @staticmethod
    def _touches(a: Rect, b: Rect) -> bool:
        """True if a and b overlap or are directly adjacent (gap <= 1 px)."""
        return (
            a[0] <= b[2] + 1
            and b[0] <= a[2] + 1
            and a[1] <= b[3] + 1
            and b[1] <= a[3] + 1
        )

    @staticmethod
    def _union(a: Rect, b: Rect) -> Rect:
        return (
            min(a[0], b[0]),
            min(a[1], b[1]),
            max(a[2], b[2]),
            max(a[3], b[3]),
        )


# ── glyph cache ───────────────────────────────────────────────────────────────


class GlyphCache:
    """Rasterized glyph masks: (char, font_key) → (mask, advance).

    PIL renders each glyph exactly once into an L-mode bitmap (0..255).
    Color is applied at draw time via a masked write — recoloring does not
    re-rasterize, so the cache key deliberately excludes color.

    LRU-bounded: rendering an uncached glyph evicts the oldest entry when
    the cache is full.
    """

    def __init__(
        self,
        fonts: Mapping[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
        max_entries: int = 512,
    ) -> None:
        self._fonts = dict(fonts)
        self._cache: OrderedDict[tuple[str, str], tuple[numpy.ndarray, int]] = (
            OrderedDict()
        )
        self._max = max_entries
        self._line_heights: dict[str, int] = {}

    def glyph(self, ch: str, font_key: str) -> tuple[numpy.ndarray, int]:
        """Return (mask uint8 (h, w), advance width in px) for *ch*.

        Space and zero-width characters return an all-zero mask.
        """
        key = (ch, font_key)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        rendered = self._rasterize(ch, font_key)
        self._cache[key] = rendered
        if len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return rendered

    def text_width(self, s: str, font_key: str) -> int:
        """Sum of advance widths for *s* (no drawing)."""
        return sum(self.glyph(ch, font_key)[1] for ch in s)

    def line_height(self, font_key: str) -> int:
        """Raster height (px) for one line of *font_key*."""
        if font_key not in self._line_heights:
            mask, _ = self.glyph("X", font_key)
            self._line_heights[font_key] = mask.shape[0]
        return self._line_heights[font_key]

    def _rasterize(self, ch: str, font_key: str) -> tuple[numpy.ndarray, int]:
        font = self._fonts[font_key]
        # Universal metrics: textlength works for TrueType and bitmap fonts.
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        advance = round(probe.textlength(ch, font=font))
        try:
            ascent, descent = font.getmetrics()  # type: ignore[union-attr]
            height = ascent + descent
        except AttributeError:
            height = 13  # PIL bitmap fallback font
        width = max(advance, 1) + 2  # +2 px pad for right-side overhang
        if not ch.strip():
            return numpy.zeros((max(height, 1), width), dtype=numpy.uint8), advance
        im = Image.new("L", (width, height), 0)
        ImageDraw.Draw(im).text((1, 0), ch, font=font, fill=255)
        return numpy.array(im, dtype=numpy.uint8), advance


# ── frame buffer + primitives ─────────────────────────────────────────────────


class FrameBuffer:
    """BGR565 frame buffer (W, H) uint16 + drawing primitives.

    Storage order (W, H) matches the wire-format encoder input. Every
    primitive paints pixels and invalidates its bounding box in ``dirty``.
    """

    def __init__(
        self,
        width: int = FRAME_W,
        height: int = FRAME_H,
        fonts: Mapping[str, ImageFont.FreeTypeFont | ImageFont.ImageFont] | None = None,
    ) -> None:
        self._w = width
        self._h = height
        self.pixels = numpy.zeros((width, height), dtype=numpy.uint16)
        self.dirty = DirtyTracker(width, height)
        self._glyphs = GlyphCache(fonts) if fonts is not None else None

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    # ── base primitives ─────────────────────────────────────────────────────

    def fill(self, color: int) -> None:
        """Fill the whole frame with *color* (marks full dirty)."""
        self.pixels[:, :] = color
        self.dirty.invalidate(0, 0, self._w, self._h)

    def reset(self, color: int = Colors.BG) -> None:
        """Clear to *color* and mark the whole frame dirty (screen change)."""
        self.fill(color)

    def fill_rect(self, x: int, y: int, w: int, h: int, color: int) -> None:
        """Paint a filled rectangle; clipped to the frame."""
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self._w, int(x) + int(w))
        y1 = min(self._h, int(y) + int(h))
        if x1 <= x0 or y1 <= y0:
            return
        self.pixels[x0:x1, y0:y1] = color
        self.dirty.invalidate(x0, y0, x1 - x0, y1 - y0)

    def rect(
        self, x: int, y: int, w: int, h: int, color: int, width_px: int = 1
    ) -> None:
        """Paint a rectangle outline."""
        for i in range(width_px):
            self.hline(x + i, y + i, w - 2 * i, color)
            if h - 2 * i > 1:
                self.hline(x + i, y + h - 1 - i, w - 2 * i, color)
            if w - 2 * i > 1:
                self.vline(x + i, y + i, h - 2 * i, color)
                self.vline(x + w - 1 - i, y + i, h - 2 * i, color)
        self.dirty.invalidate(x, y, w, h)

    def hline(self, x: int, y: int, w: int, color: int) -> None:
        """Horizontal line from (x, y), *w* px long, clipped."""
        x0 = max(0, int(x))
        x1 = min(self._w, int(x) + int(w))
        if x1 <= x0 or not (0 <= int(y) < self._h):
            return
        self.pixels[x0:x1, int(y)] = color
        self.dirty.invalidate(x0, int(y), x1 - x0, 1)

    def vline(self, x: int, y: int, h: int, color: int) -> None:
        """Vertical line from (x, y), *h* px long, clipped."""
        y0 = max(0, int(y))
        y1 = min(self._h, int(y) + int(h))
        if y1 <= y0 or not (0 <= int(x) < self._w):
            return
        self.pixels[int(x), y0:y1] = color
        self.dirty.invalidate(int(x), y0, 1, y1 - y0)

    def blit(self, patch: numpy.ndarray, x: int, y: int) -> None:
        """Copy a (w, h) uint16 patch into the frame at (x, y), clipped."""
        w, h = patch.shape
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self._w, int(x) + w)
        y1 = min(self._h, int(y) + h)
        if x1 <= x0 or y1 <= y0:
            return
        self.pixels[x0:x1, y0:y1] = patch[
            x0 - int(x) : x1 - int(x), y0 - int(y) : y1 - int(y)
        ]
        self.dirty.invalidate(x0, y0, x1 - x0, y1 - y0)

    # ── text ────────────────────────────────────────────────────────────────

    def text(self, x: int, y: int, s: str, font_key: str, color: int) -> int:
        """Draw *s* at (x, y) top-left; return total advance width in px.

        Paints pixels where the glyph mask is bright; other pixels in the
        glyph box are left untouched (no background erase).
        """
        if self._glyphs is None:
            raise RuntimeError("FrameBuffer created without fonts")
        self.dirty.invalidate(
            x,
            y,
            self._glyphs.text_width(s, font_key),
            self._glyphs.line_height(font_key),
        )
        cx = int(x)
        for ch in s:
            mask, advance = self._glyphs.glyph(ch, font_key)
            gh, gw = mask.shape
            w = min(gw, self._w - cx)
            h = min(gh, self._h - int(y))
            if w > 0 and h > 0:
                region = self.pixels[cx : cx + w, int(y) : int(y) + h]
                region[mask[:h, :w].transpose() >= _GLYPH_THRESHOLD] = color
            cx += advance
        return cx - int(x)

    def text_width(self, s: str, font_key: str) -> int:
        """Advance width of *s* without drawing."""
        if self._glyphs is None:
            raise RuntimeError("FrameBuffer created without fonts")
        return self._glyphs.text_width(s, font_key)

    def text_centered(self, cx: int, y: int, s: str, font_key: str, color: int) -> None:
        """Draw *s* horizontally centered on *cx*."""
        self.text(cx - self.text_width(s, font_key) // 2, y, s, font_key, color)

    # ── high-level widgets ──────────────────────────────────────────────────

    def bar(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        value: int,
        maximum: int = 127,
        color: int = Colors.TRACK_FILL,
        bg: int = Colors.ENCODER_BG,
    ) -> None:
        """Horizontal value bar: background always, fill proportional."""
        self.fill_rect(x, y, w, h, bg)
        clamped = max(0, min(int(value), int(maximum)))
        if clamped > 0:
            fill_w = max(1, int(w) * clamped // int(maximum))
            self.fill_rect(x, y, min(fill_w, int(w)), h, color)

    def grid_cell(
        self, x: int, y: int, w: int, h: int, color: int, lit: bool, head: bool = False
    ) -> None:
        """Drum-grid cell: unlit = dark background, lit = *color*, head = white frame."""
        self.fill_rect(x, y, w, h, color if lit else Colors.ENCODER_BG)
        if head:
            self.rect(x, y, w, h, Colors.WHITE)
