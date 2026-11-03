"""Тесты Grid-макета (Ф1): типы слотов, полосы, render_layout."""

from __future__ import annotations

import numpy

from src.devices.push2.display import _FONTS
from src.devices.push2.layout import (
    BODY_BAND,
    FOOT_BAND,
    FOOT_Y0,
    HEADER_BAND,
    KNOBS_BAND,
    KNOBS_Y0,
    KNOBS_Y1,
    LOWER_BAND,
    LOWER_Y0,
    UPPER_BAND,
    UPPER_H,
    Button,
    Empty,
    FlowList,
    List,
    Panel,
    Range,
    ScreenLayout,
    Tabs,
    Text,
    render_layout,
    slot_rect,
)
from src.devices.push2.renderer import FRAME_W, Colors, FrameBuffer
from src.devices.push2.widgets import BODY_Y0, BODY_Y1, SLOT_COUNT, SLOT_W


def make_fb() -> FrameBuffer:
    fb = FrameBuffer(fonts=_FONTS)
    fb.fill(Colors.BG)
    fb.dirty.clear()
    return fb


def non_bg_count(fb: FrameBuffer, x: int, y: int, w: int, h: int) -> int:
    region = fb.pixels[x : x + w, y : y + h]
    return int(numpy.count_nonzero(region != Colors.BG))


def color_count(fb: FrameBuffer, color: int, x: int, y: int, w: int, h: int) -> int:
    region = fb.pixels[x : x + w, y : y + h]
    return int(numpy.count_nonzero(region == color))


class TestBands:
    def test_header_band_is_top_14(self) -> None:
        assert (HEADER_BAND.y0, HEADER_BAND.y1, HEADER_BAND.h) == (0, 14, 14)

    def test_body_starts_under_header(self) -> None:
        assert BODY_BAND.y0 == BODY_Y0 == 14
        assert BODY_BAND.y1 == BODY_Y1 == 160

    def test_four_rows_fill_body_without_gaps(self) -> None:
        assert UPPER_BAND.y0 == BODY_Y0
        assert UPPER_BAND.y1 == KNOBS_BAND.y0
        assert KNOBS_BAND.y1 == LOWER_BAND.y0
        assert LOWER_BAND.y1 == FOOT_BAND.y0
        assert FOOT_BAND.y1 == BODY_Y1

    def test_foot_and_lower_heights(self) -> None:
        assert LOWER_BAND.h == 18
        assert FOOT_BAND.h == 18
        assert FOOT_Y0 == 142
        assert LOWER_Y0 == 124

    def test_knobs_band_height(self) -> None:
        assert (KNOBS_Y0, KNOBS_Y1) == (32, 124)
        assert KNOBS_BAND.h == 92

    def test_upper_row_height_constant(self) -> None:
        assert UPPER_H == UPPER_BAND.h


class TestSlotRect:
    def test_eight_slots_of_120(self) -> None:
        assert SLOT_COUNT == 8
        assert SLOT_W == 120
        for i in range(8):
            rect = slot_rect(i, UPPER_BAND.y0, UPPER_BAND.y1)
            assert rect.x == i * SLOT_W + 4
            assert rect.w == SLOT_W - 8
            assert (rect.y, rect.h) == (UPPER_BAND.y0, UPPER_BAND.h)

    def test_inset_shrinks_width_only(self) -> None:
        wide = slot_rect(0, 100, 120, inset=0)
        narrow = slot_rect(0, 100, 120, inset=4)
        assert (wide.y, wide.h) == (narrow.y, narrow.h)
        assert wide.w == SLOT_W and narrow.w == SLOT_W - 8


class TestEmpty:
    def test_renders_nothing(self) -> None:
        fb = make_fb()
        Empty().render(fb, slot_rect(0, KNOBS_Y0, KNOBS_Y1))
        assert fb.dirty.rects() == ()


class TestButton:
    def test_active_is_white_fill(self) -> None:
        fb = make_fb()
        Button("CLIP", active=True).render(fb, slot_rect(0, UPPER_BAND.y0, UPPER_BAND.y1))
        assert color_count(fb, Colors.WHITE, 0, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h) > 100

    def test_inactive_is_not_white(self) -> None:
        fb = make_fb()
        Button("CLIP").render(fb, slot_rect(0, UPPER_BAND.y0, UPPER_BAND.y1))
        assert color_count(fb, Colors.WHITE, 0, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h) == 0
        assert non_bg_count(fb, 0, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h) > 5

    def test_led_dot_drawn(self) -> None:
        fb = make_fb()
        Button("X", led=Colors.CONNECTED).render(
            fb, slot_rect(0, UPPER_BAND.y0, UPPER_BAND.y1)
        )
        assert color_count(fb, Colors.CONNECTED, 0, UPPER_BAND.y0, SLOT_W, UPPER_H) > 0

    def test_no_led_by_default(self) -> None:
        fb = make_fb()
        Button("X").render(fb, slot_rect(0, UPPER_BAND.y0, UPPER_BAND.y1))
        assert color_count(fb, Colors.CONNECTED, 0, UPPER_BAND.y0, SLOT_W, UPPER_H) == 0

    def test_half_fit_uses_half_slot(self) -> None:
        fb = make_fb()
        Button("X", fit="half").render(fb, slot_rect(0, UPPER_BAND.y0, UPPER_BAND.y1))
        assert non_bg_count(fb, SLOT_W // 2 + 8, UPPER_BAND.y0, SLOT_W // 2, UPPER_H) == 0


class TestPanel:
    def test_label_value_footer(self) -> None:
        fb = make_fb()
        rect = slot_rect(0, KNOBS_Y0, KNOBS_Y1)
        Panel("LAYOUT", "A", "chromatic").render(fb, rect)
        assert non_bg_count(fb, rect.x, rect.y + 4, rect.w, 12) > 3
        assert non_bg_count(fb, rect.x, rect.y + 22, rect.w, 18) > 3
        assert non_bg_count(fb, rect.x, rect.y + 46, rect.w, 12) > 3

    def test_no_footer(self) -> None:
        fb = make_fb()
        rect = slot_rect(0, KNOBS_Y0, KNOBS_Y1)
        Panel("DIRECTION", "—").render(fb, rect)
        assert non_bg_count(fb, rect.x, rect.y + 46, rect.w, 12) == 0


class TestRange:
    def test_frac_maps_value_to_range(self) -> None:
        assert Range("GATE", 0.0, 0.0, 1.0).frac == 0.0
        assert Range("GATE", 0.5, 0.0, 1.0).frac == 0.5
        assert Range("GATE", 0.25, 0.0, 1.0).frac == 0.25

    def test_frac_clamped(self) -> None:
        assert Range("GATE", -1.0, 0.0, 1.0).frac == 0.0
        assert Range("GATE", 2.0, 0.0, 1.0).frac == 1.0

    def test_frac_none_on_empty_span(self) -> None:
        assert Range("GATE", 1.0, 1.0, 1.0).frac is None

    def test_value_with_unit_and_bar(self) -> None:
        fb = make_fb()
        rect = slot_rect(2, KNOBS_Y0, KNOBS_Y1)
        Range("GATE", 0.5, 0.0, 1.0, unit=" %").render(fb, rect)
        assert non_bg_count(fb, rect.x, rect.y + 22, rect.w, 18) > 3
        assert color_count(fb, Colors.TRACK_FILL, rect.x + 10, rect.y + 46, rect.w - 20, 8) > 10

    def test_empty_span_draws_no_bar(self) -> None:
        fb = make_fb()
        rect = slot_rect(2, KNOBS_Y0, KNOBS_Y1)
        Range("GATE", 1.0, 1.0, 1.0).render(fb, rect)
        assert color_count(fb, Colors.TRACK_FILL, rect.x + 10, rect.y + 46, rect.w - 20, 8) == 0


class TestList:
    def test_cursor_marked(self) -> None:
        fb = make_fb()
        rect = slot_rect(0, KNOBS_Y0, KNOBS_Y1)
        List("SRC", ("pad", "stab", "bass"), index=1).render(fb, rect)
        # Курсор — вторая строка окна (y = rect.y + 35).
        assert color_count(fb, Colors.BPM_LINK, rect.x, rect.y + 20, rect.w, 45) > 0
        assert non_bg_count(fb, rect.x, rect.y + 4, rect.w, 12) > 3

    def test_empty_options_dash(self) -> None:
        fb = make_fb()
        rect = slot_rect(0, KNOBS_Y0, KNOBS_Y1)
        List("SRC", ()).render(fb, rect)
        assert non_bg_count(fb, rect.x, rect.y + 20, rect.w, 15) > 0

    def test_window_follows_index(self) -> None:
        fb = make_fb()
        rect = slot_rect(0, KNOBS_Y0, KNOBS_Y1)
        options = tuple(f"opt{i}" for i in range(12))
        List("SRC", options, index=11, rows=3).render(fb, rect)
        # Последние три варианта попали в окно, курсор на последней строке.
        assert color_count(fb, Colors.BPM_LINK, rect.x, rect.y + 20, rect.w, 45) > 0

    def test_index_clamped(self) -> None:
        fb = make_fb()
        rect = slot_rect(0, KNOBS_Y0, KNOBS_Y1)
        List("SRC", ("a", "b"), index=99).render(fb, rect)


class TestFlowList:
    def test_items_split_across_slots(self) -> None:
        flow = FlowList(("a", "b", "c", "d", "e", "f", "g", "h"), slots=(0, 7), rows_per_slot=4)
        assert flow.items[0:4] == ("a", "b", "c", "d")
        assert flow.items[4:8] == ("e", "f", "g", "h")

    def test_renders_cursor_in_first_slot(self) -> None:
        fb = make_fb()
        rect = slot_rect(0, KNOBS_Y0, KNOBS_Y1)
        FlowList(("a", "b", "c", "d", "e"), index=1, slots=(0, 7), rows_per_slot=4).render(
            fb, rect
        )
        assert color_count(fb, Colors.BPM_LINK, rect.x, rect.y, rect.w, rect.h) > 0

    def test_second_slot_renders_its_half(self) -> None:
        fb = make_fb()
        flow = FlowList(("a", "b", "c", "d", "e", "f", "g", "h"), index=6, slots=(0, 7))
        rect_zero = slot_rect(0, KNOBS_Y0, KNOBS_Y1)
        rect_seven = slot_rect(7, KNOBS_Y0, KNOBS_Y1)
        flow.render_slot(fb, rect_zero, 0)
        flow.render_slot(fb, rect_seven, 1)
        assert non_bg_count(fb, rect_zero.x, rect_zero.y, rect_zero.w, rect_zero.h) > 3
        assert non_bg_count(fb, rect_seven.x, rect_seven.y, rect_seven.w, rect_seven.h) > 3
        # Курсор (index=6) — во втором слоте, в первом его быть не должно.
        assert color_count(fb, Colors.BPM_LINK, rect_zero.x, rect_zero.y, rect_zero.w, rect_zero.h) == 0
        assert color_count(fb, Colors.BPM_LINK, rect_seven.x, rect_seven.y, rect_seven.w, rect_seven.h) > 0


class TestRenderLayout:
    def test_empty_layout_clears_body(self) -> None:
        fb = make_fb()
        fb.fill_rect(0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0, Colors.WHITE)
        render_layout(fb, ScreenLayout())
        assert non_bg_count(fb, 0, BODY_Y0, FRAME_W, BODY_Y1 - BODY_Y0) == 0

    def test_upper_row_in_upper_band(self) -> None:
        fb = make_fb()
        render_layout(fb, ScreenLayout(upper=(Button("A", active=True),) + (Empty(),) * 7))
        assert color_count(fb, Colors.WHITE, 0, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h) > 100
        assert non_bg_count(fb, 0, KNOBS_Y0, SLOT_W, KNOBS_Y1 - KNOBS_Y0) == 0

    def test_encoders_in_knobs_band(self) -> None:
        fb = make_fb()
        render_layout(
            fb,
            ScreenLayout(encoders=(Range("GATE", 0.5, 0.0, 1.0),) + (Empty(),) * 7),
        )
        assert non_bg_count(fb, 0, KNOBS_Y0, SLOT_W, 60) > 5
        assert non_bg_count(fb, 0, UPPER_BAND.y0, SLOT_W, UPPER_BAND.h) == 0

    def test_lower_and_foot_rows_are_separate(self) -> None:
        fb = make_fb()
        layout = ScreenLayout(
            lower=(Button("L1"),) + (Empty(),) * 7,
            foot=(Button("F1"),) + (Empty(),) * 7,
        )
        render_layout(fb, layout)
        assert non_bg_count(fb, 0, LOWER_BAND.y0, SLOT_W, LOWER_BAND.h) > 3
        assert non_bg_count(fb, 0, FOOT_BAND.y0, SLOT_W, FOOT_BAND.h) > 3

    def test_short_tuples_leave_tail_slots_empty(self) -> None:
        fb = make_fb()
        render_layout(fb, ScreenLayout(upper=(Button("A", active=True),)))
        assert non_bg_count(fb, SLOT_W, UPPER_BAND.y0, FRAME_W - SLOT_W, UPPER_BAND.h) == 0

    def test_flow_list_in_non_adjacent_slots(self) -> None:
        fb = make_fb()
        layout = ScreenLayout(
            encoders=tuple(
                FlowList(("a", "b", "c", "d", "e", "f", "g", "h"), slots=(0, 7))
                if i in (0, 7)
                else Empty()
                for i in range(8)
            )
        )
        render_layout(fb, layout)
        assert non_bg_count(fb, 0, KNOBS_Y0, SLOT_W, KNOBS_Y1 - KNOBS_Y0) > 3
        assert non_bg_count(fb, 7 * SLOT_W, KNOBS_Y0, SLOT_W, KNOBS_Y1 - KNOBS_Y0) > 3
        assert non_bg_count(fb, SLOT_W, KNOBS_Y0, 6 * SLOT_W, KNOBS_Y1 - KNOBS_Y0) == 0

    def test_layout_lists_only_buttons(self) -> None:
        layout = ScreenLayout(
            upper=(Button("A"), Panel("p", "v")),
            lower=(Empty(), Button("B")),
        )
        assert [b.text for b in layout.all_buttons()] == ["A", "B"]


class TestText:
    """Text \u2014 \u043e\u0434\u043d\u043e\u0441\u0442\u0440\u043e\u0447\u043d\u0430\u044f \u043f\u043e\u0434\u043f\u0438\u0441\u044c (\u043f\u043e\u043b\u043e\u0441\u0430 FOOT)."""

    def test_label_and_value(self) -> None:
        fb = make_fb()
        Text("PORT", "> \u0421\u0438\u043d\u0442 A").render(fb, slot_rect(0, FOOT_BAND.y0, FOOT_BAND.y1))
        assert non_bg_count(fb, 0, FOOT_BAND.y0, SLOT_W, FOOT_BAND.h) > 10

    def test_long_value_is_truncated(self) -> None:
        """\u0414\u043b\u0438\u043d\u043d\u043e\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435 \u043d\u0435 \u0432\u044b\u043b\u0435\u0437\u0430\u0435\u0442 \u0437\u0430 \u0441\u043b\u043e\u0442 (\u043e\u0431\u0440\u0435\u0437\u043a\u0430 \u0441 \u00ab\u2026\u00bb)."""
        fb = make_fb()
        rect = slot_rect(0, FOOT_BAND.y0, FOOT_BAND.y1)
        Text("X", "A" * 200).render(fb, rect)
        assert non_bg_count(fb, rect.x + rect.w, FOOT_BAND.y0, SLOT_W, FOOT_BAND.h) == 0

    def test_empty_label_renders_value_only(self) -> None:
        fb = make_fb()
        Text("", "\u2014").render(fb, slot_rect(0, FOOT_BAND.y0, FOOT_BAND.y1))
        assert non_bg_count(fb, 0, FOOT_BAND.y0, SLOT_W, FOOT_BAND.h) > 0


class TestRangeNotApplicable:
    def test_none_value_draws_dash_without_bar(self) -> None:
        """value=None \u2014 \u00ab\u2014\u00bb \u0431\u0435\u0437 \u0431\u0430\u0440\u0430 (\u0441\u0435\u043c\u0430\u043d\u0442\u0438\u043a\u0430 \u00ab\u043d\u0435 \u043f\u0440\u0438\u043c\u0435\u043d\u0438\u043c\u043e\u00bb, \u043a\u0430\u043a GATE \u0443 drum)."""
        fb = make_fb()
        r = Range("GATE (E3)", None, 0.0, 100.0, unit=" %")
        r.render(fb, slot_rect(2, KNOBS_Y0, KNOBS_Y1))
        assert r.frac is None
        assert non_bg_count(fb, 2 * SLOT_W, KNOBS_Y0, SLOT_W, 60) > 3
        assert color_count(fb, Colors.TRACK_FILL, 2 * SLOT_W, KNOBS_Y0, SLOT_W, 60) == 0


class TestLayoutStripe:
    def test_stripe_paints_left_four_columns(self) -> None:
        """\u0426\u0432\u0435\u0442 \u0434\u043e\u0440\u043e\u0436\u043a\u0438 \u2014 \u043f\u043e\u043b\u043e\u0441\u0430 4 px \u0441\u043b\u0435\u0432\u0430 \u0432\u043e \u0432\u0441\u044e \u0432\u044b\u0441\u043e\u0442\u0443 body."""
        fb = make_fb()
        color = Colors.CONNECTED
        render_layout(fb, ScreenLayout(stripe=color))
        assert color_count(fb, color, 0, BODY_Y0, 4, BODY_Y1 - BODY_Y0) == 4 * (
            BODY_Y1 - BODY_Y0
        )


class TestLayoutTabs:
    def test_tabs_render_across_foot(self) -> None:
        """\u041f\u043e\u043b\u043e\u0441\u0430 \u0432\u043a\u043b\u0430\u0434\u043e\u043a \u043d\u0430 \u0432\u0441\u044e \u0448\u0438\u0440\u0438\u043d\u0443 FOOT (\u0430\u043a\u0442\u0438\u0432\u043d\u0430\u044f \u2014 \u0431\u0435\u043b\u043e\u0439 \u0437\u0430\u043b\u0438\u0432\u043a\u043e\u0439)."""
        fb = make_fb()
        render_layout(
            fb,
            ScreenLayout(tabs=Tabs(("clock", "midi", "link"), active="midi")),
        )
        assert non_bg_count(fb, 0, FOOT_BAND.y0, FRAME_W, FOOT_BAND.h) > 50
        assert color_count(fb, Colors.WHITE, 0, FOOT_BAND.y0, FRAME_W, FOOT_BAND.h) > 20


class TestScaleRootRows:
    """SCALE (\u04245): \u043a\u043e\u0440\u043d\u0438 \u043e\u0431\u0440\u0430\u043c\u043b\u044f\u044e\u0442 \u043b\u0430\u0434\u044b \u043f\u043e \u043a\u0432\u0438\u043d\u0442\u043e\u0432\u043e\u043c\u0443 \u043a\u0440\u0443\u0433\u0443."""

    def test_twelve_roots_split_by_fifths(self) -> None:
        from src.devices.push2.screens import scale_root_rows

        roots = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
        top, bottom = scale_root_rows(roots)
        assert top == ("C", "G", "D", "A", "E", "B")
        assert bottom == ("F", "A#", "D#", "G#", "C#", "F#")

    def test_other_lengths_split_in_half(self) -> None:
        from src.devices.push2.screens import scale_root_rows

        top, bottom = scale_root_rows(("a", "b", "c", "d"))
        assert (top, bottom) == (("a", "b"), ("c", "d"))

    def test_empty_roots_do_not_crash(self) -> None:
        from src.devices.push2.screens import scale_root_rows

        assert scale_root_rows(()) == ((), ())


class TestScaleScreenLayout:
    """\u042d\u043a\u0440\u0430\u043d SCALE \u0432 \u0444\u043e\u0440\u043c\u0435 \u044d\u0442\u0430\u043b\u043e\u043d\u0430 Scale Push 2."""

    def _layout(self, **overrides):
        from src.devices.display_state import ScaleView, ScreenView
        from src.devices.push2.screens import ScaleScreen

        base = {
            "roots": ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"),
            "scales": ("major", "dorian", "phrygian", "lydian",
                       "mixolydian", "aeolian", "locrian", "minor"),
            "root_index": 0,
            "scale_index": 0,
        }
        base.update(overrides)
        view = ScreenView(screen="scale", title="", flash=None, scale=ScaleView(**base))
        return ScaleScreen().layout(view)

    def test_upper_row_holds_six_roots(self) -> None:
        layout = self._layout()
        buttons = [i for i in layout.upper if isinstance(i, Button)]
        assert [b.text for b in buttons] == ["C", "G", "D", "A", "E", "B"]
        assert all(isinstance(i, Empty) for i in layout.upper[6:])

    def test_lower_row_holds_six_roots(self) -> None:
        layout = self._layout()
        buttons = [i for i in layout.lower if isinstance(i, Button)]
        assert [b.text for b in buttons] == ["F", "A#", "D#", "G#", "C#", "F#"]

    def test_active_root_is_the_only_active_button(self) -> None:
        layout = self._layout(root_index=7)  # G
        active = [i.text for i in scale_all_buttons(layout) if i.active]
        assert active == ["G"]

    def test_one_scale_per_encoder_slot(self) -> None:
        layout = self._layout()
        names = [i.value for i in layout.encoders if isinstance(i, Text)]
        assert names == ["major", "dorian", "phrygian", "lydian",
                         "mixolydian", "aeolian", "locrian", "minor"]

    def test_active_scale_marked(self) -> None:
        layout = self._layout(scale_index=1)
        active = [i.value for i in layout.encoders if isinstance(i, Text) and i.active]
        assert active == ["dorian"]

    def test_foot_shows_key_and_scale_then_empty(self) -> None:
        layout = self._layout(root_index=9, scale_index=1)  # A dorian
        labels = [i.label for i in layout.foot if isinstance(i, Text)]
        values = [i.value for i in layout.foot if isinstance(i, Text)]
        assert labels == ["KEY", "SCALE"]
        assert values == ["A", "dorian"]
        assert all(isinstance(i, Empty) for i in layout.foot[2:])

    def test_no_dead_placeholders_in_foot(self) -> None:
        """\u041d\u0438\u043a\u0430\u043a\u0438\u0445 LAYOUT/DIRECTION \u2014 \u044d\u0442\u0438\u0445 \u0434\u0430\u043d\u043d\u044b\u0445 \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0435 \u043d\u0435\u0442."""
        layout = self._layout()
        for item in layout.foot:
            assert getattr(item, "label", "") not in ("LAYOUT", "DIRECTION")


def scale_all_buttons(layout):
    """\u0412\u0441\u0435 \u043a\u043d\u043e\u043f\u043a\u0438 Upper/Lower Row \u043c\u0430\u043a\u0435\u0442\u0430."""
    return [i for row in (layout.upper, layout.lower) for i in row if isinstance(i, Button)]
