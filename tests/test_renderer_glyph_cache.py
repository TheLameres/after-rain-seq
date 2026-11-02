"""Tests for GlyphCache and text drawing in src/devices/push2/renderer.py."""

from PIL import ImageFont

from src.devices.push2.renderer import Colors, FrameBuffer, GlyphCache

_FONTS = {
    "sm": ImageFont.load_default(size=10),
    "md": ImageFont.load_default(size=12),
}


def _cache() -> GlyphCache:
    return GlyphCache(_FONTS)


# ── GlyphCache ────────────────────────────────────────────────────────────────


def test_glyph_cache_hit_returns_same_object() -> None:
    c = _cache()
    mask1, adv1 = c.glyph("A", "sm")
    mask2, adv2 = c.glyph("A", "sm")
    assert mask1 is mask2
    assert adv1 == adv2
    assert len(c._cache) == 1


def test_glyph_cache_keyed_by_font() -> None:
    c = _cache()
    c.glyph("A", "sm")
    c.glyph("A", "md")
    assert len(c._cache) == 2


def test_glyph_cache_color_not_in_key() -> None:
    """Recoloring must not re-rasterize — the key is (char, font_key)."""
    c = _cache()
    c.glyph("A", "sm")
    c.glyph("A", "sm")  # same key regardless of intended color
    assert len(c._cache) == 1


def test_glyph_cache_lru_eviction() -> None:
    c = GlyphCache(_FONTS, max_entries=4)
    for ch in "ABCDE":
        c.glyph(ch, "sm")
    assert len(c._cache) == 4
    assert ("A", "sm") not in c._cache  # oldest evicted
    assert ("E", "sm") in c._cache


def test_space_glyph_is_empty_mask() -> None:
    c = _cache()
    mask, advance = c.glyph(" ", "sm")
    assert advance > 0  # advances the cursor
    assert not mask.any()  # paints nothing


def test_text_width_monospace_additive() -> None:
    """Width of AA = 2 × width of A for a monospace font."""
    c = _cache()
    single = c.text_width("A", "sm")
    double = c.text_width("AA", "sm")
    assert double == 2 * single


def test_line_height_positive() -> None:
    c = _cache()
    assert c.line_height("sm") > 0


# ── text drawing ──────────────────────────────────────────────────────────────


def _fb() -> FrameBuffer:
    return FrameBuffer(960, 160, fonts=_FONTS)


def test_text_paints_something_and_advances() -> None:
    fb = _fb()
    fb.dirty.clear()
    width = fb.text(10, 10, "AB", "sm", Colors.WHITE)
    assert width == fb.text_width("AB", "sm")
    # at least some pixel in the glyph box got painted
    region = fb.pixels[10 : 10 + width, 10 : 10 + fb._glyphs.line_height("sm")]
    assert (region == Colors.WHITE).any()


def test_text_does_not_erase_background() -> None:
    """Masked write: pixels outside glyph strokes keep their color."""
    fb = _fb()
    fb.fill_rect(0, 0, 200, 40, Colors.ENCODER_BG)
    fb.dirty.clear()
    fb.text(10, 10, "A", "sm", Colors.WHITE)
    # background outside the glyph strokes survives
    assert (fb.pixels[10:40, 10:30] == Colors.ENCODER_BG).any()


def test_text_marks_dirty() -> None:
    fb = _fb()
    fb.dirty.clear()
    width = fb.text(10, 10, "AB", "sm", Colors.WHITE)
    h = fb._glyphs.line_height("sm")
    assert fb.dirty.rects() == ((10, 10, 10 + width, 10 + h),)


def test_text_color_applied() -> None:
    fb = _fb()
    fb.text(10, 10, "A", "sm", Colors.CONNECTED)
    region = fb.pixels[10:30, 10:30]
    assert (region == Colors.CONNECTED).any()


def test_text_centered() -> None:
    fb = _fb()
    width = fb.text_width("AB", "sm")
    x0_left = 100
    w_left = fb.text(x0_left, 10, "AB", "sm", Colors.WHITE)
    # centered at 100 = left-aligned starting at 100 - width//2
    fb.dirty.clear()
    fb.text_centered(100, 40, "AB", "sm", Colors.WHITE)
    assert w_left == width
    # dirty rect x0 must equal the centered start
    rect = fb.dirty.rects()[0]
    assert rect[0] == 100 - width // 2


def test_text_clipped_at_frame_edge() -> None:
    fb = _fb()
    fb.text(950, 150, "AB", "sm", Colors.WHITE)  # runs off bottom-right
    assert fb.dirty.rects()[0][2] <= 960
    assert fb.dirty.rects()[0][3] <= 160
