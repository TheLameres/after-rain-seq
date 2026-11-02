"""Интеграционные тесты D2: PushDisplay.update_screen + Push2Device screen_view."""

from unittest.mock import MagicMock

from src.devices.display_state import (
    DisplayState,
    ScaleView,
    ScreenView,
    TrackRowView,
)
from src.devices.push2.display import PushDisplay
from src.devices.push2.push2_device import Push2Device
from tests.test_push2_device import _make_device_with_mock_ports


def _tracks_view(title: str = "TRACKS 1-8/1") -> ScreenView:
    return ScreenView(
        screen="tracks",
        title=title,
        tab=None,
        flash=None,
        tracks=(
            TrackRowView(
                name="Pad 1",
                kind="melodic",
                profile="pad",
                channel=0,
                port=None,
                frozen=False,
                mutation_count=0,
                selected=True,
            ),
        ),
    )


def _scale_view() -> ScreenView:
    return ScreenView(
        screen="scale",
        title="SCALE",
        tab=None,
        flash=None,
        scale=ScaleView(
            roots=("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"),
            scales=("major", "dorian", "phrygian", "lydian"),
            root_index=9,
            scale_index=1,
        ),
    )


# ── PushDisplay.update_screen: инвалидация регионов ──────────────────────────


def test_screen_change_full_invalidate() -> None:
    """Смена экрана = full reset: все три региона dirty, даже при равных DTO."""
    disp = PushDisplay(fps=25)
    disp.update_screen(_tracks_view())
    disp.render_frame_only()  # сброс dirty
    disp.update_screen(_scale_view())
    assert disp._dirty_regions == {"header", "body"}


def test_same_view_no_dirty_and_no_second_frame() -> None:
    frames: list = []
    disp = PushDisplay(fps=25, on_frame=frames.append)
    view = _tracks_view()
    disp.update_screen(view)
    disp.render_frame_only()
    disp.update_screen(view)
    assert disp._dirty_regions == set()
    disp.render_frame_only()
    assert len(frames) == 1
    assert frames[0].size == (960, 160)
    assert frames[0].mode == "RGB"


def test_title_change_dirty_only_header() -> None:
    disp = PushDisplay(fps=25)
    disp.update_screen(_tracks_view(title="TRACKS 1-8/1"))
    disp.render_frame_only()
    disp.update_screen(_tracks_view(title="TRACKS 1-8/2"))
    assert disp._dirty_regions == {"header"}


def test_tracks_change_dirty_only_body() -> None:
    disp = PushDisplay(fps=25)
    v1 = _tracks_view()
    disp.update_screen(v1)
    disp.render_frame_only()
    changed = TrackRowView(
        name="Pad 1",
        kind="melodic",
        profile="pad",
        channel=0,
        port="Синт A",  # было None
        frozen=False,
        mutation_count=0,
        selected=True,
    )
    v2 = ScreenView(
        screen="tracks",
        title=v1.title,
        tab=v1.tab,
        flash=None,
        tracks=(changed,),
    )
    disp.update_screen(v2)
    assert disp._dirty_regions == {"body"}


def test_update_screen_then_render_frame_only_fails_without_on_frame() -> None:
    """render_frame_only без callback не падает и не шлёт наружу ничего."""
    disp = PushDisplay(fps=25)  # on_frame=None
    disp.update_screen(_tracks_view())
    disp.render_frame_only()  # не должно бросить
    assert disp._dirty_regions == set()


# ── Push2Device: маршрутизация screen_view ────────────────────────────────────


def test_render_display_with_screen_view_goes_to_update_screen() -> None:
    device, _, _ = _make_device_with_mock_ports(display_enabled=True)
    device._display = MagicMock()
    view = _tracks_view()
    state = DisplayState(device_connected=True, screen_view=view)
    device.render_display(state)
    device._display.update_screen.assert_called_once_with(view)
    device._display.update_state.assert_not_called()


def test_render_display_without_screen_view_uses_legacy_path() -> None:
    device, _, _ = _make_device_with_mock_ports(display_enabled=True)
    device._display = MagicMock()
    state = DisplayState(
        device_connected=True,
        sync_bpm=120.0,
        sync_link_peers=0,
        sync_link_active=False,
        sync_clock_source="internal",
    )
    device.render_display(state)
    device._display.update_screen.assert_not_called()
    device._display.update_state.assert_called_once()


def test_set_button_leds_sends_cc_per_button() -> None:
    device, _, mock_out = _make_device_with_mock_ports()
    device.send_midi = Push2Device.send_midi.__get__(device, Push2Device)

    device.set_button_leds({"Session": 122, "Play": 126, "Lower Row 1": 126})

    sent = [c[0][0] for c in mock_out.send.call_args_list]
    cc_msgs = [m for m in sent if m.type == "control_change"]
    by_control = {int(m.control): int(m.value) for m in cc_msgs}
    assert by_control == {51: 122, 85: 126, 20: 126}


def test_set_button_leds_noop_without_midi_out() -> None:
    device = Push2Device()  # не подключён — _midi_out is None
    device.set_button_leds({"Play": 126})  # не должно бросить
